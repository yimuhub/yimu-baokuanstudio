# SPDX-License-Identifier: BUSL-1.1
"""R10 运营收入看板与续费提醒（Revenue Analytics & Renewal Reminders）。

===========================================================================
解决什么问题
===========================================================================
R10 审查结论：漏斗看板只到「兑换卡密」，**没有 GMV / MRR / ARPU 等
收入维度**；会员到期完全被动（仅被动刷新），续费是成本最低的收入
来源却没有任何提醒机制。本模块补上：

1. :func:`revenue_summary`：收入看板数据——
   GMV（已收款订单实收总额）、订单数、按套餐分布、近 N 天日收入序列、
   MRR（月度经常性收入，按套餐周期天数折算）、ARPU、付费转化率、
   退款额。价格一律取 :mod:`studio.pricing` 真源，不硬编码。
2. :func:`expiring_memberships` / :func:`send_renewal_reminders`：
   付费会员到期前 7/3/1 天自动发送续费提醒（经 ``core.user_notify``
   既有通道投递，24h 节流幂等，通道未配置时只落台账不阻塞）。

口径说明：
- GMV 只统计 ``status='paid'``（含后来退款的不剔除，另给 refunded 指标）；
- MRR 把周期价折算为 30 天：``price_cents * 30 / period_days``，
  只统计 active 且未过期的付费档 memberships。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "revenue_summary",
    "expiring_memberships",
    "send_renewal_reminders",
]

_REMIND_MARKS_DAYS = (7, 3, 1)
_RENEW_KIND = "renewal_reminder"


def _utc8_now() -> datetime:
    """账务口径统一按 UTC+8 自然日（与 README 面向市场一致）。"""
    return datetime.now(timezone.utc) + timedelta(hours=8)


def revenue_summary(db: Any, tenant_id: str, *, days: int = 30) -> dict[str, Any]:
    """收入看板汇总（管理员）。所有金额字段同时给分与元两个口径。"""
    from sqlalchemy import func

    from ..db_models import Membership, Order, User, utcnow
    from ..pricing import PLANS

    tenant_id = str(tenant_id)
    q = db.query(Order).filter(Order.tenant_id == tenant_id)

    paid_rows = q.filter(Order.status == "paid").all()
    refunded_rows = q.filter(Order.status == "refunded").all()
    total_orders = q.count()

    gmv_cents = sum(int(o.amount_cents) for o in paid_rows)
    refund_cents = sum(int(o.amount_cents) for o in refunded_rows)

    by_plan: dict[str, dict[str, int]] = {}
    for o in paid_rows:
        slot = by_plan.setdefault(str(o.plan), {"orders": 0, "gmv_cents": 0})
        slot["orders"] += 1
        slot["gmv_cents"] += int(o.amount_cents)

    # 近 N 天日收入序列（UTC+8 自然日；升序，空日补 0）
    days = max(1, min(120, int(days)))
    today = _utc8_now().date()
    daily: dict[str, int] = {
        (today - timedelta(days=i)).isoformat(): 0 for i in range(days - 1, -1, -1)
    }
    for o in paid_rows:
        paid_at = o.paid_at
        if paid_at is None:
            continue
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=timezone.utc)
        key = (paid_at + timedelta(hours=8)).date().isoformat()
        if key in daily:
            daily[key] += int(o.amount_cents)

    # MRR：active 付费会员按周期折算 30 天
    mrr_cents = 0.0
    tier_counts: dict[str, int] = {}
    mrows = (
        db.query(Membership)
        .filter(Membership.tenant_id == tenant_id, Membership.status == "active")
        .all()
    )
    now = utcnow()
    for m in mrows:
        tier = str(m.tier or "free")
        if tier == "free":
            continue
        cfg = PLANS.get(tier) or {}
        period_days = int(cfg.get("period_days") or 30) or 30
        # 过期的不计入 MRR
        pend = m.period_end
        if pend is not None:
            if pend.tzinfo is None:
                pend = pend.replace(tzinfo=timezone.utc)
            if pend < now:
                continue
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        mrr_cents += float(cfg.get("price_cents") or 0) * 30.0 / period_days

    total_users = db.query(func.count(User.id)).filter(User.tenant_id == tenant_id).scalar() or 0
    paying_users = len({str(o.user_id) for o in paid_rows})

    return {
        "ok": True,
        "days": days,
        "gmv_cents": gmv_cents,
        "gmv_yuan": round(gmv_cents / 100.0, 2),
        "refund_cents": refund_cents,
        "refund_yuan": round(refund_cents / 100.0, 2),
        "net_yuan": round((gmv_cents - refund_cents) / 100.0, 2),
        "paid_orders": len(paid_rows),
        "total_orders": int(total_orders),
        "pay_conversion": round(len(paid_rows) / total_orders, 4) if total_orders else 0.0,
        "by_plan": by_plan,
        "mrr_cents": int(round(mrr_cents)),
        "mrr_yuan": round(mrr_cents / 100.0, 2),
        "active_paid_tiers": tier_counts,
        "total_users": int(total_users),
        "paying_users": paying_users,
        # ARPU：近 N 天 GMV / 全部注册用户（运营惯例口径）
        "arpu_yuan": round(
            (sum(v for k, v in daily.items()) / 100.0) / total_users, 2
        ) if total_users else 0.0,
        "daily_series": [
            {"date": k, "gmv_cents": v, "gmv_yuan": round(v / 100.0, 2)}
            for k, v in sorted(daily.items())
        ],
        "generated_at": time.time(),
    }


def expiring_memberships(db: Any, tenant_id: str, *, within_days: int = 7) -> list[dict[str, Any]]:
    """未来 N 天内到期的付费会员（续费提醒目标名单）。"""
    from ..db_models import Membership, User, utcnow

    now = utcnow()
    horizon = now + timedelta(days=max(1, int(within_days)))
    rows = (
        db.query(Membership, User.username)
        .join(User, User.id == Membership.user_id)
        .filter(
            Membership.tenant_id == str(tenant_id),
            Membership.status == "active",
            Membership.tier != "free",
            Membership.period_end.isnot(None),
            Membership.period_end >= now,
            Membership.period_end <= horizon,
        )
        .all()
    )
    items = []
    for m, username in rows:
        pend = m.period_end
        if pend.tzinfo is None:
            pend = pend.replace(tzinfo=timezone.utc)
        days_left = max(0, round((pend - now).total_seconds() / 86400.0))
        items.append({
            "user_id": m.user_id,
            "username": username or m.user_id,
            "tier": str(m.tier),
            "period_end": pend.isoformat(),
            "days_left": days_left,
        })
    items.sort(key=lambda x: x["days_left"])
    return items


def send_renewal_reminders(db: Any, tenant_id: str, *, force: bool = False) -> dict[str, Any]:
    """给到期前 7/3/1 天的付费会员发送续费提醒（幂等：同用户同档 24h 一封）。

    Returns:
        ``{"checked": n, "sent": n, "skipped": n, "items": [...]}``。
        投递走 ``core.user_notify.deliver``：未配置邮件通道时只落台账
        （status=pending），绝不抛异常、绝不阻塞主流程。
    """
    from core import user_notify

    targets = expiring_memberships(db, tenant_id, within_days=max(_REMIND_MARKS_DAYS))
    sent = skipped = 0
    details: list[dict[str, Any]] = []
    for t in targets:
        if t["days_left"] not in _REMIND_MARKS_DAYS:
            continue
        # 收件人：users.email（可空；为空时 deliver 只落台账待补发）
        from ..db_models import User

        u = db.query(User).filter(User.id == t["user_id"]).first()
        recipient = (u.email if u else "") or ""
        tier_name = {"pro": "超级创作者 Pro", "studio": "MCN 机构矩阵版 Studio"}.get(
            t["tier"], t["tier"].upper())
        title = f"[{_RENEW_KIND}] {tier_name} 会员将于 {t['days_left']} 天后到期"
        body = (
            f"您好 {t['username']}，\n\n您的 {tier_name} 会员将于 "
            f"{t['period_end'][:10]}（{t['days_left']} 天后）到期。\n"
            "到期后创作额度将不再刷新，模板与音色等会员权益同步暂停。\n"
            "现在续费可无缝衔接：登录一幕·YIMU → 套餐与价格 → 一键续费。"
        )
        r = user_notify.deliver(
            t["user_id"], recipient, title, body,
            kind=_RENEW_KIND, tenant_id=str(tenant_id), force=force,
        )
        if r.get("status") == "sent":
            sent += 1
        else:
            skipped += 1
        details.append({"user_id": t["user_id"], "days_left": t["days_left"],
                        "status": r.get("status"), "reason": r.get("reason", "")})
    return {"checked": len(targets), "sent": sent, "skipped": skipped, "items": details}
