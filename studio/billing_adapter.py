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

# B 的档位与动作单价：优先从移植后的 core.billing 导入，保持同源；
# 导入失败时用本地副本（与 port/core/billing.py 同源，改动时请同步）。
try:
    from core.billing import ACTION_COSTS as _B_ACTION_COSTS
    from core.billing import DEFAULT_TIERS as _B_DEFAULT_TIERS

    DEFAULT_TIERS = _B_DEFAULT_TIERS
    ACTION_COSTS = _B_ACTION_COSTS
    _CONFIG_SOURCE = "core.billing"
except ImportError:  # pragma: no cover - ws-b 独立工作区时的回退
    _CONFIG_SOURCE = "vendored"
    # 与 port/core/billing.py 同源（2026-10-06），修改时请同步两处。
    DEFAULT_TIERS = {
        "free": {"name": "新人体验官", "tokens_grant": 10000,
                 "max_drafts_daily": 3,
                 "features": ["basic_rewrite", "basic_video", "single_furnace"]},
        "pro": {"name": "超级创作者 (Pro)", "tokens_grant": 500000,
                "max_drafts_daily": 50,
                "features": ["all_xhs_styles", "full_furnace", "voices",
                             "export_jianying", "ai_drama"]},
        "studio": {"name": "MCN 机构矩阵版 (Studio)", "tokens_grant": 6000000,
                   "max_drafts_daily": 500,
                   "features": ["all_features", "auto_matrix_publish",
                                "deep_distill", "priority_compute"]},
    }
    ACTION_COSTS = {
        "rewrite": 800, "score": 300, "refine_single": 400,
        "refine_batch": 1200, "furnace_round": 1000, "xhs_card_layout": 500,
        "drama_decompose": 1000, "drama_image": 1000, "drama_tts": 500,
        "drama_render": 5000, "deep_distill": 2500,
    }


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
    from studio.db_models import AuditLog, new_id, utcnow

    if tier not in DEFAULT_TIERS:
        return False
    ensure_membership, _, _ = _membership_svc()
    ms = ensure_membership(db, tenant_id, user_id)
    ms.tier = tier
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
        return {"ok": False, "msg": "该卡密已被兑换使用过"}
    db.commit()

    if code.startswith("YIMU-PRO-"):
        set_tier(db, tenant_id, user_id, "pro")
        return {"ok": True, "msg": "兑换成功！已升级为超级创作者 Pro 并获得配额"}
    if code.startswith("YIMU-STUDIO-"):
        set_tier(db, tenant_id, user_id, "studio")
        return {"ok": True, "msg": "兑换成功！已升级为 MCN 机构版并获得配额"}
    amt = inv.credits_grant or 0
    bal = grant_tokens(db, tenant_id, user_id, amt, "兑换卡密: " + code)
    return {"ok": True, "msg": "兑换成功！已为账户注入 %s 点数" % f"{amt:,}", "balance": bal}


def get_default_billing_user(db, tenant_name: str = "default"):
    """本地单机模式：取默认租户的首个用户（B 单用户语义的对应）。"""
    from studio.db_models import Tenant, User

    tenant = db.query(Tenant).filter(Tenant.name == tenant_name).first()
    if tenant is None:
        return None, None
    user = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.is_active.is_(True))
        .order_by(User.created_at.asc())
        .first()
    )
    return tenant, user


__all__ = [
    "DEFAULT_TIERS", "ACTION_COSTS",
    "get_billing_status", "check_and_deduct", "grant_tokens",
    "set_tier", "generate_cdkeys", "redeem_cdkey",
    "get_default_billing_user",
]
