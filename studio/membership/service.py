# SPDX-License-Identifier: BUSL-1.1
"""会员档位与额度逻辑：档位配置、额度原子扣减、额度发放、邀请码核销。

⭐ 并发安全：deduct_credits 使用单条原子 UPDATE（WHERE 携带剩余额度条件），
   多个网关 worker 同时扣减也不会把 credits_used 扣成负数或超扣。

⭐ 租户隔离：所有写操作都携带 tenant_id；跨租户的 user_id 永远匹配不到行，
   扣减会返回失败而不是扣到别人的账上。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import errors
from ..db_models import AuditLog, Invite, Membership, Tenant, User, new_id, utcnow

# V7.0 会员档位配置（每周期授信额度，单位：credits 点数）。
#
# 口径对齐（2026-10-06 战略调整：V7 改为"移植 B 代码 + 手术式修改"）：
#   本表对应 B 代码基线 /home/hatch/workspace/yimu-v7-port/core/billing.py
#   的 DEFAULT_TIERS —— 中文名与 tokens_grant 点数一一对齐：
#     free   → B「新人体验官」                tokens_grant=10000
#     pro    → B「超级创作者 (Pro)」          tokens_grant=500000
#     studio → B「MCN 机构矩阵版 (Studio)」   tokens_grant=6000000
#   V7 的 credits 点数即 B 的 tokens 点数（同一账本：会员额度 = 网关 credits，
#   网关每次调用扣减 memberships.credits_used，明细记 ledger 表）。
#   B 的 ACTION_COSTS（rewrite 800 / score 300 等动作单价）由 billing_adapter
#   桥接：adapter 把 B 的 check_and_deduct(action, count) 换算成点数后调用
#   本模块 deduct_credits(db, tenant_id, user_id, amount)。
#
# 说明：V7.0 先写死配置；后续后台会员管理页（WS-F）上线后改为从数据库/配置中心
#      读取，到时只需替换本字典的取值来源，调用方签名不变。
TIERS: dict[str, dict[str, object]] = {
    "free": {"credits": 10000, "name": "新人体验官"},
    "pro": {"credits": 500000, "name": "超级创作者"},
    "studio": {"credits": 6000000, "name": "MCN机构版"},
}

# 邀请码可读前缀与随机部分长度（形如 YIMU-XXXXXX）
_INVITE_PREFIX = "YIMU-"
_INVITE_RANDOM_LEN = 6
_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉易混淆的 0/O/1/I


def tier_credits(tier: str) -> int:
    """取某档位每周期授信额度；未知档位按 free 处理。"""
    cfg = TIERS.get(tier, TIERS["free"])
    return int(cfg["credits"])  # type: ignore[arg-type]


def tier_name(tier: str) -> str:
    """取某档位的中文展示名。"""
    cfg = TIERS.get(tier, TIERS["free"])
    return str(cfg["name"])


def ensure_membership(db: Session, tenant_id: str, user_id: str) -> Membership:
    """取用户会员记录；不存在则按 free 档创建（幂等）。

    ⭐ 写入前确认 user 归属该租户，防止把会员记录挂到别的租户的用户上。
    """
    m = (
        db.query(Membership)
        .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .first()
    )
    if m is not None:
        return m
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == tenant_id)
        .first()
    )
    if user is None:
        errors.raise_err("NOT_FOUND", "用户不存在", hint="请重新登录后再试")
    m = Membership(
        id=new_id(),
        tenant_id=tenant_id,
        user_id=user_id,
        tier="free",
        credits_total=tier_credits("free"),
        credits_used=0,
        period_start=utcnow(),
        period_end=None,
        status="active",
    )
    db.add(m)
    db.flush()
    return m


def credits_left(m: Membership) -> int:
    """剩余额度（永不为负）。"""
    return max(0, int(m.credits_total) - int(m.credits_used))


def deduct_credits(
    db: Session, tenant_id: str, user_id: str, amount: int
) -> tuple[bool, int]:
    """⭐ 原子扣减额度（并发安全，防超扣）。

    用单条 ``UPDATE ... WHERE credits_used + :n <= credits_total`` 实现：
    额度不足或记录不存在/非 active 时该语句影响 0 行，返回 (False, 当前剩余额度)，
    绝不会把剩余额度扣成负数。多个进程/线程同时扣减也只会有先到先得的
    其中一方成功，不会产生脏写（靠数据库行级原子性保证）。

    Args:
        amount: 本次扣减点数，必须为正整数；≤0 直接返回失败且不改数据。

    Returns:
        (ok, left)：是否扣减成功，以及操作完成后的剩余额度。
    """
    if amount <= 0:
        m = (
            db.query(Membership)
            .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
            .first()
        )
        return False, credits_left(m) if m else 0
    # ⭐ 原子更新：条件里同时校验租户、用户、状态与剩余额度
    result = db.execute(
        text(
            "UPDATE memberships SET credits_used = credits_used + :n, "
            "updated_at = :now "
            "WHERE tenant_id = :t AND user_id = :u AND status = 'active' "
            "AND credits_used + :n <= credits_total"
        ),
        {"n": amount, "t": tenant_id, "u": user_id, "now": utcnow()},
    )
    db.commit()
    ok = result.rowcount == 1
    m = (
        db.query(Membership)
        .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .first()
    )
    return ok, credits_left(m) if m else 0


def grant_credits(
    db: Session, membership: Membership, amount: int, reason: str, actor: str = "system"
) -> Membership:
    """发放额度：增加 credits_total 并写审计日志（只增不改账本）。

    ⭐ amount 必须为正数；reason 会写入审计日志便于对账。
    """
    if amount <= 0:
        errors.raise_err("BAD_REQUEST", "发放额度必须为正数")
    membership.credits_total = int(membership.credits_total) + amount
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=membership.tenant_id,
            actor=actor,
            action="membership.grant",
            target=f"membership:{membership.id}",
            detail={"amount": amount, "reason": reason},
        )
    )
    db.commit()
    db.refresh(membership)
    return membership


def _redeem_invite_atomic(db: Session, tenant: Tenant, code: str) -> Invite:
    """⭐ 原子核销邀请码：used_count + 1 与有效性校验在同一条 UPDATE 里完成。

    邀请码已用完 / 过期 / 被作废 / 非 active 时影响 0 行，
    高并发下也不会出现「两次核销都成功」的超发。
    """
    now = utcnow()
    result = db.execute(
        text(
            "UPDATE invites SET used_count = used_count + 1 "
            "WHERE tenant_id = :t AND code = :c AND status = 'active' "
            "AND used_count < max_uses "
            "AND (expires_at IS NULL OR expires_at > :now)"
        ),
        {"t": tenant.id, "c": code.strip(), "now": now},
    )
    if result.rowcount != 1:
        errors.raise_err(
            "BAD_REQUEST",
            "邀请码无效或已用完",
            hint="请检查邀请码是否正确、是否过期，或联系管理员重新发放",
        )
    invite = (
        db.query(Invite)
        .filter(Invite.tenant_id == tenant.id, Invite.code == code.strip())
        .first()
    )
    # 若用完则顺手置 exhausted（不影响本次核销结果）
    if invite is not None and int(invite.used_count) >= int(invite.max_uses):
        invite.status = "exhausted"
    db.flush()
    assert invite is not None  # 刚原子更新成功，行必存在
    return invite


def redeem_invite(db: Session, tenant: Tenant, code: str, user: User) -> Membership:
    """已登录用户核销邀请码：原子占用一次名额，按 credits_grant 加额度。

    ⭐ 先原子占用名额再加额度；任一步失败则抛 400 且已占用的名额
       会随事务回滚释放（调用方未提交前不落盘）。
    """
    if user.tenant_id != tenant.id:
        errors.raise_err("FORBIDDEN", "无权操作该租户的邀请码")
    invite = _redeem_invite_atomic(db, tenant, code)
    membership = ensure_membership(db, tenant.id, user.id)
    if int(invite.credits_grant) > 0:
        membership.credits_total = int(membership.credits_total) + int(
            invite.credits_grant
        )
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=tenant.id,
            actor=user.id,
            action="invite.redeem",
            target=f"invite:{invite.id}",
            detail={
                "code": invite.code,
                "credits_grant": int(invite.credits_grant),
                "username": user.username,
            },
        )
    )
    db.commit()
    db.refresh(membership)
    return membership


def generate_invite_code(db: Session) -> str:
    """生成全局唯一的邀请码（形如 YIMU-XXXXXX，碰撞时重试）。"""
    for _ in range(20):
        code = _INVITE_PREFIX + "".join(
            secrets.choice(_INVITE_ALPHABET) for _ in range(_INVITE_RANDOM_LEN)
        )
        exists = db.query(Invite).filter(Invite.code == code).first()
        if exists is None:
            return code
    errors.raise_err("INTERNAL", "邀请码生成失败，请稍后重试")


def create_invite(
    db: Session,
    tenant: Tenant,
    *,
    max_uses: int = 1,
    credits_grant: int = 0,
    expires_at: datetime | None = None,
    actor: str = "system",
) -> Invite:
    """管理员发放邀请码并写审计日志。"""
    if max_uses < 1:
        errors.raise_err("BAD_REQUEST", "邀请码可用次数至少为 1")
    if credits_grant < 0:
        errors.raise_err("BAD_REQUEST", "赠送额度不能为负数")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= utcnow():
            errors.raise_err("BAD_REQUEST", "过期时间必须晚于当前时间")
    invite = Invite(
        id=new_id(),
        tenant_id=tenant.id,
        code=generate_invite_code(db),
        max_uses=max_uses,
        used_count=0,
        credits_grant=credits_grant,
        expires_at=expires_at,
        status="active",
    )
    db.add(invite)
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=tenant.id,
            actor=actor,
            action="invite.create",
            target=f"invite:{invite.id}",
            detail={
                "code": invite.code,
                "max_uses": max_uses,
                "credits_grant": credits_grant,
            },
        )
    )
    db.commit()
    db.refresh(invite)
    return invite
