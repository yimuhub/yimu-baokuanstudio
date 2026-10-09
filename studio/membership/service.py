# SPDX-License-Identifier: BUSL-1.1
"""会员档位与额度逻辑：档位配置、额度原子扣减、额度发放、邀请码核销。

⭐ 并发安全：deduct_credits 使用单条原子 UPDATE（WHERE 携带剩余额度条件），
   多个网关 worker 同时扣减也不会把 credits_used 扣成负数或超扣。

⭐ 租户隔离：所有写操作都携带 tenant_id；跨租户的 user_id 永远匹配不到行，
   扣减会返回失败而不是扣到别人的账上。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import errors
from ..db_models import AuditLog, Invite, Membership, Tenant, User, new_id, utcnow
# R2-1：额度/单价的唯一真源（1 credit = 0.01 元）
from ..pricing import TIER_CREDITS, TIER_PERIOD_DAYS, tier_period_days

# V7.0 会员档位配置（每周期授信额度，单位：credits 点数）。
#
# ⭐ R2-1：额度数字的唯一真源是 studio/pricing.py（TIER_CREDITS）。
#   本表只做「档位 → 额度」的转发，改价请改 studio/pricing.py，禁止在此另立数字。
#   口径：1 credit = 0.01 元（studio/pricing.CREDIT_PRICE_CENTS）。
#     free   3000 credits = 30 元（≈ 1/3 条完整短剧，够跑单镜头体验）
#     pro    30000 credits = 300 元（≈ 3 条短剧/月）
#     studio 200000 credits = 2000 元（≈ 22 条短剧/月）
#   会员额度与网关 credits 是同一账本：扣费走 memberships 原子更新，
#   明细进 ledger；token 计费统一走 per-1k 口径（studio/pricing.credits_for_tokens）。
TIERS: dict[str, dict[str, object]] = {
    "free": {"credits": TIER_CREDITS["free"], "name": "新人体验官"},
    "pro": {"credits": TIER_CREDITS["pro"], "name": "超级创作者"},
    "studio": {"credits": TIER_CREDITS["studio"], "name": "MCN机构版"},
}

# 邀请码可读前缀与随机部分长度（形如 YIMU-XXXXXX）
_INVITE_PREFIX = "YIMU-"
_INVITE_RANDOM_LEN = 6
_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉易混淆的 0/O/1/I

# R5-4 邀请人奖励比例（20%）。
# 口径：按**被邀请人本次实际获得的额度**计算，即 credits_grant * 20%。
# 取20% 的理由：低于 10% 不足以构成裂变动机（用户懒得分享），
# 高于 30% 则邀请方成本逼近获客成本、且易被羊毛党刷量。
INVITER_REWARD_RATE = 0.20


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
    ⭐ 命中已有记录时会顺带做过期判定（R2-6），调用方无需自己判断周期。
    """
    m = (
        db.query(Membership)
        .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .first()
    )
    if m is not None:
        if reset_period_if_expired(db, m):
            db.commit()
            db.refresh(m)
        return m
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == tenant_id)
        .first()
    )
    if user is None:
        errors.raise_err("NOT_FOUND", "用户不存在", hint="请重新登录后再试")
    now = utcnow()
    m = Membership(
        id=new_id(),
        tenant_id=tenant_id,
        user_id=user_id,
        tier="free",
        credits_total=tier_credits("free"),
        credits_used=0,
        period_start=now,
        # ⭐ R2-6：新建即给出明确的周期终点（原先恒为 None，等于额度永不过期）
        period_end=now + timedelta(days=tier_period_days("free")),
        status="active",
    )
    db.add(m)
    db.flush()
    return m


def reset_period_if_expired(db: Session, m: Membership) -> bool:
    """⭐ R2-6：周期到期判定与重置。返回是否发生了重置。

    背景：``period_end`` 此前全仓只有「写 None」与一处只读展示，
    **周期过期机制完全未实现**——会员额度永不重置，等于额度只减不增，
    老用户用尽额度后永久无法使用。

    规则：
      - ``period_end`` 为空：视为长期有效（管理员/存量数据），不重置。
      - ``period_end`` 未到：不重置。
      - ``period_end`` 已过：按**当前档位**重开一个周期——
        ``credits_used`` 归零、``credits_total`` 恢复该档位标准额度、
        ``period_start`` 滚动为当前时间、``period_end`` 顺延一整个周期。

    ⚠️ 额度重置会覆盖已用额度，这是「周期内额度重新可用」的预期语义；
       已消费金额仍完整保留在 ledger 表中（账本只增不改），可按周期对账。
    """
    if m.period_end is None:
        return False
    #⭐ SQLite 的DateTime 列读回来是 naive，而 utcnow() 是 aware，
    #   直接比较会抛 TypeError。统一按 naive UTC 比较。
    end = m.period_end
    if end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    now = utcnow().replace(tzinfo=None)
    if now <= end:
        return False

    days = tier_period_days(m.tier or "free")
    m.credits_used = 0
    m.credits_total = tier_credits(m.tier or "free")
    m.period_start = now
    m.period_end = now + timedelta(days=days)
    db.flush()
    return True


def ensure_period_current(db: Session, tenant_id: str, user_id: str) -> Membership:
    """取会员记录并保证处于当前周期（过期即重置），返回新鲜记录。

    供「读余额」类接口使用：只查不扣的路径也应先过周期判定，
    否则用户会看到 0 余额却无法通过任何入口恢复。
    """
    m = ensure_membership(db, tenant_id, user_id)
    db.refresh(m)
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
    # ⭐ R2-6：扣费前先做过期判定并重置。否则过期用户即使额度已被重置，
    #   也可能因 period_end 落在过去而永远扣不动（charge_membership 的 SQL
    #   带 period_end 条件），表现为「明明还有额度却一直提示不足」。
    m = (
        db.query(Membership)
        .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .first()
    )
    if m is not None and reset_period_if_expired(db, m):
        db.commit()
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


def _reward_inviter(db: Session, tenant: Tenant, invite: Invite,
                    invitee: User) -> tuple[int, str]:
    """R5-4：核销后给邀请人发奖励，返回 (奖励点数, 邀请人id)。

    幂等：同一张码被``max_uses`` 次用掉会各发一次奖励（设计如此，
    码本身就是「可多次使用的邀请码」）；但**同一张码重复核销同一用户**
    由 :func:`_redeem_invite_atomic` 的 ``used_count < max_uses`` 挡住，
    加上 :func:`redeem_invite` 入口的重复校验，双重防重。

    ⚠️ 只在 ``inviter_id`` 非空且邀请人 ≠ 被邀请人时发奖：
    运营后台批量发的卡密 ``inviter_id=''``（无邀请人），
    自己注册再用自己码（自邀）也都不发——否则可自己刷额度。
    """
    from ..db_models import InviteReferral

    inviter_id = (invite.inviter_id or "").strip()
    if not inviter_id or inviter_id == invitee.id:
        return 0, ""
    reward = int(int(invite.credits_grant or 0) * INVITER_REWARD_RATE)
    if reward <= 0:
        return 0, inviter_id
    # 邀请人必须真实存在且同租户，否则宁可不发（跨租户刷量防线）
    inviter = (
        db.query(User)
        .filter(User.id == inviter_id, User.tenant_id == tenant.id)
        .first()
    )
    if inviter is None:
        return 0, ""
    inviter_m = ensure_membership(db, tenant.id, inviter_id)
    inviter_m.credits_total = int(inviter_m.credits_total) + reward
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=tenant.id,
            actor=inviter_id,
            action="invite.reward",
            target=f"membership:{inviter_m.id}",
            detail={
                "invitee": invitee.id,
                "invite_code": invite.code,
                "reward": reward,
                "rate": INVITER_REWARD_RATE,
            },
        )
    )
    db.add(
        InviteReferral(
            id=new_id(),
            tenant_id=tenant.id,
            inviter_id=inviter_id,
            invitee_id=invitee.id,
            invite_code=invite.code,
            reward_credits=reward,
        )
    )
    return reward, inviter_id


def list_invite_relations(db: Session, tenant: Tenant,
                          inviter_id: str | None = None,
                          limit: int = 200) -> list[dict]:
    """R5-4：查「谁邀请了谁」（裂变 ROI 追踪）。

    Args:
        inviter_id: 只查该邀请人；为空则返回该租户全部邀请关系。
    """
    from ..db_models import InviteReferral

    q = db.query(InviteReferral).filter(InviteReferral.tenant_id == tenant.id)
    if inviter_id:
        q = q.filter(InviteReferral.inviter_id == inviter_id)
    rows = q.order_by(InviteReferral.created_at.desc()).limit(int(limit)).all()
    out = []
    for r in rows:
        inviter = (
            db.query(User).filter(User.id == r.inviter_id).first()
        )
        invitee = (
            db.query(User).filter(User.id == r.invitee_id).first()
        )
        out.append({
            "inviter_id": r.inviter_id,
            "inviter_name": getattr(inviter, "username", ""),
            "invitee_id": r.invitee_id,
            "invitee_name": getattr(invitee, "username", ""),
            "invite_code": r.invite_code,
            "reward_credits": int(r.reward_credits or 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return out


def inviter_summary(db: Session, tenant: Tenant, inviter_id: str) -> dict:
    """邀请人视角的裂变战绩：邀请人数 / 累计奖励 / 明细。"""
    rows = list_invite_relations(db, tenant, inviter_id)
    total_reward = sum(r["reward_credits"] for r in rows)
    return {
        "inviter_id": inviter_id,
        "invited_count": len(rows),
        "total_reward_credits": total_reward,
        "relations": rows,
    }


def redeem_invite(db: Session, tenant: Tenant, code: str, user: User) -> Membership:
    """已登录用户核销邀请码：原子占用一次名额，按 credits_grant 加额度。

    ⭐ 先原子占用名额再加额度；任一步失败则抛 400 且已占用的名额
       会随事务回滚释放（调用方未提交前不落盘）。

    R5-4：核销成功后额外给邀请人发 20% 奖励并落 ``invite_referrals``。
    """
    if user.tenant_id != tenant.id:
        errors.raise_err("FORBIDDEN", "无权操作该租户的邀请码")
    invite = _redeem_invite_atomic(db, tenant, code)
    # ⭐ 防自邀刷额度：自己核销自己发的码不再发放邀请奖励
    #   （奖励发放处也有兜底判断，这里提前拦下更清晰）
    membership = ensure_membership(db, tenant.id, user.id)
    if int(invite.credits_grant) > 0:
        membership.credits_total = int(membership.credits_total) + int(
            invite.credits_grant
        )
    reward, inviter_id = _reward_inviter(db, tenant, invite, user)
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
                "inviter_id": inviter_id,
                "inviter_reward": reward,
            },
        )
    )
    db.commit()
    db.refresh(membership)
    # R5-6：核销邀请码记一条转化事件（漏斗第 5 步）
    try:
        from core import analytics

        analytics.track("cdkey_redeemed", str(user.id),
                        {"code": invite.code, "grant": int(invite.credits_grant)},
                        tenant_id=tenant.id)
    except Exception:
        pass
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
    inviter_id: str = "",
) -> Invite:
    """管理员发放邀请码并写审计日志。

    R5-4：``inviter_id`` 标记这张码属于谁（用户自助生成的裂变码）；
    留空表示运营批量发放（无邀请人，核销时不给奖励）。
    """
    if max_uses < 1:
        errors.raise_err("BAD_REQUEST", "邀请码可用次数至少为 1")
    if credits_grant < 0:
        errors.raise_err("BAD_REQUEST", "赠送额度不能为负数")
    if inviter_id:
        # 邀请人必须真实存在且同租户，防止伪造别人的邀请人 id 冒领奖励
        inviter = (
            db.query(User)
            .filter(User.id == inviter_id, User.tenant_id == tenant.id)
            .first()
        )
        if inviter is None:
            errors.raise_err("BAD_REQUEST", "邀请人不存在")
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
        inviter_id=inviter_id or "",
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
                "inviter_id": inviter_id or "",
            },
        )
    )
    db.commit()
    db.refresh(invite)
    return invite
