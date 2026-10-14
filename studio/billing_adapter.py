# SPDX-License-Identifier: BUSL-1.1
"""B 计费逻辑到 V7 ledger 表的适配器。

背景（移植策略，2026-10-06 战略调整）：
B 的 port/core/billing.py 是单用户 JSON 文件账本，接口为
get_billing_status / check_and_deduct / grant_tokens / set_tier /
generate_cdkeys / redeem_cdkey，另有 DEFAULT_TIERS 与 ACTION_COSTS。
V7 不替换它，而是把后端统一接到 ledger 表：本模块提供与 B 同签名的
ledger-backed 实现。集成时二选一：路由层直接调本模块，或对 billing.py
做手术式修改（把 _load_data/_save_data 换成调本模块）。
会员额度与网关 credits 是同一账本：扣费走 memberships 原子更新，明细进 ledger。

星标规则：本模块只 INSERT（ledger / audit_logs），绝不 UPDATE/DELETE 账本行；
余额由 memberships.credits_total - credits_used 推导，不另存快照。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

# ⭐ R2-1/R2-3：档位与动作单价的唯一真源是 studio/pricing.py。
#   历史做法是「优先 core.billing，失败回落到本地副本」——那等于把价格
#   复制了两份，改价必然漂移。现改为无条件从 pricing 取，删掉 vendored 副本。
from .pricing import ACTION_COSTS, DEFAULT_TIERS

#: 保留字段兼容既有调用方（历史值为 "core.billing"）
_CONFIG_SOURCE = "studio.pricing"


def _membership_svc():
    """懒加载会员服务（避免导入期循环依赖）。"""
    from studio.membership.service import (
        deduct_credits,
        ensure_membership,
        grant_credits,
    )

    return ensure_membership, deduct_credits, grant_credits


def _balance_of(membership) -> int:
    """当前可用点数。"""
    return max(0, (membership.credits_total or 0) - (membership.credits_used or 0))


def get_billing_status(db, tenant_id: str, user_id: str) -> dict:
    """B 兼容：当前账户状态与点数余额。

    balance 语义为会员剩余额度（credits_total - credits_used）；
    total_consumed 与 recent_history 从 ledger 表推导。
    """
    from studio.db_models import Ledger

    ensure_membership, _, _ = _membership_svc()
    ms = ensure_membership(db, tenant_id, user_id)
    tier_info = DEFAULT_TIERS.get(ms.tier or "free", DEFAULT_TIERS["free"])

    rows = (
        db.query(Ledger)
        .filter(Ledger.tenant_id == tenant_id)
        .order_by(Ledger.created_at.desc())
        .limit(50)
        .all()
    )
    total_consumed = sum(r.cost_cents or 0 for r in rows if (r.cost_cents or 0) > 0)
    recent = [
        {
            "time": int(r.created_at.replace(tzinfo=timezone.utc).timestamp()),
            "action": r.model or "",
            "delta": -(r.cost_cents or 0),
        }
        for r in rows[:10]
    ]
    return {
        "tier": ms.tier,
        "tier_name": tier_info["name"],
        "balance": _balance_of(ms),
        "total_consumed": total_consumed,
        "action_costs": dict(ACTION_COSTS),
        "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()},
        "recent_history": recent,
        "config_source": _CONFIG_SOURCE,
    }


def check_and_deduct(db, tenant_id: str, user_id: str, action: str,
                     count: int = 1, desc: str = "") -> bool:
    """B 兼容：扣除指定动作的点数。余额不足返回 False。

    顺序：先原子扣会员额度，成功后再写 ledger 行与审计行；
    扣费失败不产生任何账本行（防消费了但没收费）。
    """
    from studio.db_models import AuditLog, Ledger, new_id, utcnow

    _, deduct_credits, _ = _membership_svc()
    unit = ACTION_COSTS.get(action, 500)
    total = unit * max(1, count)
    ok, _ = deduct_credits(db, tenant_id, user_id, total)
    if not ok:
        return False
    db.add(Ledger(
        id=new_id(), tenant_id=tenant_id, key_id=None,
        model="billing:" + action, direction="input",
        tokens=0, cost_cents=total, latency_ms=0, cached=False,
        created_at=utcnow(),
    ))
    db.add(AuditLog(
        id=new_id(), tenant_id=tenant_id, actor=user_id,
        action="billing.deduct:" + action, target="ledger",
        detail={"desc": desc or ("执行动作: " + action + " x " + str(count)),
                "cost_credits": total},
        created_at=utcnow(),
    ))
    db.commit()
    return True


def grant_tokens(db, tenant_id: str, user_id: str, amount: int,
                 reason: str = "充值增加") -> int:
    """B 兼容：增加点数，返回充值后余额。"""
    from studio.db_models import AuditLog, new_id, utcnow

    ensure_membership, _, grant_credits = _membership_svc()
    ms = ensure_membership(db, tenant_id, user_id)
    if int(ms.credits_used or 0) > int(ms.credits_total or 0):
        ms.credits_used = 0
    grant_credits(db, ms, amount, reason)
    db.add(AuditLog(
        id=new_id(), tenant_id=tenant_id, actor=user_id,
        action="billing.grant", target="membership:" + ms.id,
        detail={"reason": reason, "amount": amount},
        created_at=utcnow(),
    ))
    db.commit()
    db.refresh(ms)
    return _balance_of(ms)


def set_tier(db, tenant_id: str, user_id: str, tier: str) -> bool:
    """B 兼容：切换档位并按档位发放配额（语义与 B 一致：余额上累加）。"""
    from datetime import timedelta
    from studio.db_models import AuditLog, new_id, utcnow
    from studio.pricing import tier_period_days

    if tier not in DEFAULT_TIERS:
        return False
    ensure_membership, _, _ = _membership_svc()
    ms = ensure_membership(db, tenant_id, user_id)
    ms.tier = tier
    now_dt = utcnow().replace(tzinfo=None)
    days = tier_period_days(tier)
    ms.period_start = now_dt
    ms.period_end = now_dt + timedelta(days=days)
    if int(ms.credits_used or 0) >= int(ms.credits_total or 0):
        ms.credits_used = 0
    db.add(AuditLog(
        id=new_id(), tenant_id=tenant_id, actor=user_id,
        action="billing.set_tier", target="membership:" + ms.id,
        detail={"tier": tier, "tier_name": DEFAULT_TIERS[tier]["name"]},
        created_at=utcnow(),
    ))
    db.commit()
    grant_tokens(db, tenant_id, user_id, DEFAULT_TIERS[tier]["tokens_grant"],
                 "升级档位至[" + DEFAULT_TIERS[tier]["name"] + "]，发放配额")
    return True


def _make_code(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:8].upper() + "-" + uuid.uuid4().hex[:4].upper()


def generate_cdkeys(db, tenant_id: str, actor: str, key_type: str = "tokens",
                    amount: int = 100000, count: int = 5) -> list:
    """B 兼容：生成卡密。V7 存入 invites 表（卡密即一种邀请码）。

    key_type: tokens（充点数）/ pro（升级 Pro）/ studio（升级 Studio），
    类型编码在 code 前缀里（YIMU-TOKEN- / YIMU-PRO- / YIMU-STUDIO-）。
    """
    from studio.db_models import Invite, new_id, utcnow

    prefix = {"pro": "YIMU-PRO-", "studio": "YIMU-STUDIO-"}.get(key_type, "YIMU-TOKEN-")
    codes = []
    for _ in range(count):
        code = _make_code(prefix)
        db.add(Invite(
            id=new_id(), tenant_id=tenant_id, code=code,
            max_uses=1, used_count=0,
            credits_grant=amount if key_type == "tokens" else 0,
            expires_at=None, status="active", created_at=utcnow(),
        ))
        codes.append(code)
    db.commit()
    return codes


def redeem_cdkey(db, tenant_id: str, user_id: str, code: str) -> dict:
    """B 兼容：兑换卡密。

    手术式变更：B 内置的通用体验卡密（VIP999 / MEDIAFLOW888 / PRO2026）
    是写死的万能后门，V7 不再保留；如需体验额度请走 generate_cdkeys 发放。

    ⭐ 核销与发放必须同生共死：额度发放失败（如用户不存在）时回滚
       核销，把卡密还给用户。否则会出现"卡密已作废、额度没到账"，
       用户既拿不到额度也无法重试。
    """
    from sqlalchemy import update

    from studio.db_models import Invite

    code = (code or "").strip().upper()
    inv = (
        db.query(Invite)
        .filter(Invite.tenant_id == tenant_id, Invite.code == code,
                Invite.status == "active")
        .first()
    )
    if inv is None:
        # 兼容单机默认租户与 uuid 租户并存场景：按 code 查找有效卡密并对齐 tenant_id
        inv = (
            db.query(Invite)
            .filter(Invite.code == code, Invite.status == "active")
            .first()
        )
    if inv is None:
        return {"ok": False, "msg": "无效的卡密兑换码，请检查拼写"}
    if inv.expires_at is not None and inv.expires_at.replace(
            tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return {"ok": False, "msg": "该卡密已过期"}
    # 原子核销，防并发重复兑换
    res = db.execute(
        update(Invite)
        .where(Invite.id == inv.id, Invite.used_count < Invite.max_uses)
        .values(used_count=Invite.used_count + 1)
    )
    if res.rowcount == 0:
        db.rollback()
        return {"ok": False, "msg": "该卡密已被兑换使用过"}
    db.commit()

    # ⭐ 发放环节：任何异常都把核销回滚，卡密退还用户（可重试）
    try:
        if code.startswith("YIMU-PRO-"):
            set_tier(db, tenant_id, user_id, "pro")
            return {"ok": True, "msg": "兑换成功！已升级为超级创作者 Pro 并获得配额"}
        if code.startswith("YIMU-STUDIO-"):
            set_tier(db, tenant_id, user_id, "studio")
            return {"ok": True, "msg": "兑换成功！已升级为 MCN 机构版并获得配额"}
        amt = inv.credits_grant or 0
        bal = grant_tokens(db, tenant_id, user_id, amt, "兑换卡密: " + code)
        # 若该卡密来自套餐购买订单（orders.cdkey），同步升级用户会员档位并更新订单状态
        upgraded_plan = ""
        try:
            from sqlalchemy import func, text
            from studio.db_models import Order, Membership, utcnow
            ord_row = db.query(Order).filter(func.upper(Order.cdkey) == code).first()
            if ord_row and ord_row.plan in ("pro", "studio"):
                upgraded_plan = ord_row.plan
                m_row = (
                    db.query(Membership)
                    .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
                    .first()
                )
                if m_row is None:
                    m_row = db.query(Membership).filter(Membership.user_id == user_id).first()
                if m_row is not None:
                    m_row.tier = upgraded_plan
                    from datetime import timedelta
                    from studio.pricing import tier_period_days
                    now_dt = utcnow().replace(tzinfo=None)
                    days = tier_period_days(upgraded_plan)
                    m_row.period_start = now_dt
                    m_row.period_end = now_dt + timedelta(days=days)
                    if int(m_row.credits_used or 0) >= int(m_row.credits_total or 0):
                        m_row.credits_used = 0
                    bal = max(0, int(m_row.credits_total or 0) - int(m_row.credits_used or 0))
                if ord_row.status == "pending":
                    ord_row.status = "paid"
                    ord_row.paid_at = utcnow()
                try:
                    db.execute(text("UPDATE users SET plan = :p WHERE id = :u"), {"p": upgraded_plan, "u": user_id})
                except Exception:
                    pass
                db.commit()
                try:
                    from core import auth as _core_auth
                    c_auth = _core_auth._db()
                    c_auth.execute("UPDATE users SET plan=? WHERE id=?", (upgraded_plan, user_id))
                    c_auth.commit()
                    c_auth.close()
                except Exception:
                    pass
        except Exception:
            pass
        if upgraded_plan:
            plan_label = "Pro 专业版" if upgraded_plan == "pro" else "Studio 工作室版"
            return {
                "ok": True,
                "msg": f"兑换成功！已升级为【{plan_label}】并注入 {amt:,} 点算力额度",
                "balance": bal,
                "tier": upgraded_plan,
            }
        return {"ok": True, "msg": "兑换成功！已为账户注入 %s 点数" % f"{amt:,}", "balance": bal}
    except Exception:
        db.rollback()
        db.execute(
            update(Invite)
            .where(Invite.id == inv.id, Invite.used_count > 0)
            .values(used_count=Invite.used_count - 1)
        )
        db.commit()
        raise


def get_default_billing_user(db, tenant_name: str = "default"):
    """本地单机模式：取默认租户的首个用户（B 单用户语义的对应）。"""
    from studio.auth import ensure_default_tenant
    from studio.db_models import Tenant, User, utcnow

    tenant = ensure_default_tenant(db)
    user = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.id.in_(("u-admin", "admin")))
        .first()
    )
    if user is None:
        user = (
            db.query(User)
            .filter(User.tenant_id == tenant.id, User.is_active.is_(True))
            .order_by(User.created_at.asc())
            .first()
        )
    if user is None:
        user = User(
            id="u-admin", tenant_id=tenant.id, username="admin",
            email="", password_hash="!", salt="", role="admin",
            is_active=True, created_at=utcnow(),
        )
        db.add(user)
        db.commit()
    return tenant, user


# ---------------------------------------------------------------------------
# web 层便捷封装（B 风格的 web/admin.py 单机调用方使用）
#
# ⭐ 为什么不直接把db 依赖塞进路由：web/admin.py 走自己的 V6 鉴权
#    （core.auth，返回 dict 用户，不是 studio.auth 的 User 行），
#    且用的是 core.billing 的 JSON 账本。这里补一层薄封装：
#    自己开session、自己关session，路由侧只传 user_id。
#    ⭐ 只做编排，不改 redeem_cdkey / generate_cdkeys 的对外签名与返回结构。
# ---------------------------------------------------------------------------

#: web 层单机模式使用的租户名（与 web/admin.py 的 _tier_quota_check 保持一致）
WEB_TENANT_NAME = "default"


def _web_session():
    """web 层取一个 studio DB session（调用方负责 close）。"""
    from studio.membership.capabilities import get_db_session

    return get_db_session()


def redeem_cdkey_for_user(code: str, user_id: str,
                         tenant_name: str = WEB_TENANT_NAME) -> dict:
    """web 层卡密兑换：按 web 用户 id 兑换，返回结构同 redeem_cdkey。"""
    from studio.db_models import User as _StudioUser
    db = _web_session()
    try:
        uid = str(user_id or "")
        tenant_id = ""
        if uid:
            row = db.query(_StudioUser.tenant_id).filter(_StudioUser.id == uid).first()
            if row and row[0]:
                tenant_id = str(row[0])
        if not tenant_id:
            tenant, _user = get_default_billing_user(db, tenant_name)
            tenant_id = tenant.id if tenant is not None else tenant_name
        return redeem_cdkey(db, tenant_id, uid, code)
    finally:
        db.close()


def generate_cdkeys_for_actor(key_type: str = "tokens", amount: int = 100000,
                              count: int = 5, actor: str = "u-admin",
                              tenant_name: str = WEB_TENANT_NAME) -> list:
    """web 层卡密生成：按 web 用户 id 记审计，返回卡密列表。

    ⭐ 必须与 redeem_cdkey_for_user 同源（都写 invites 表），否则
       生成的卡密无处可兑——历史上core.billing 写 JSON、adapter 读
       invites，两套账本曾各说各话。
    """
    db = _web_session()
    try:
        tenant, _user = get_default_billing_user(db, tenant_name)
        tenant_id = tenant.id if tenant is not None else tenant_name
        return generate_cdkeys(db, tenant_id, actor, key_type=key_type,
                               amount=amount, count=count)
    finally:
        db.close()


__all__ = [
    "DEFAULT_TIERS", "ACTION_COSTS",
    "get_billing_status", "check_and_deduct", "grant_tokens",
    "set_tier", "generate_cdkeys", "redeem_cdkey",
    "get_default_billing_user",
    "redeem_cdkey_for_user", "generate_cdkeys_for_actor",
]
