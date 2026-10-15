# SPDX-License-Identifier: BUSL-1.1
"""R3 变现通路的业务层：下单 / 退款 / 用户管理 / 审计查询。

===========================================================================
本模块解决什么
===========================================================================
R3 批次之前，收款链路只有「运营手工生成 CDKey → 微信群发给用户」，
系统内**没有任何一行记录「谁付了钱、付了多少、是否已退」**。本模块补上：

- :func:`create_order`（R3-2）：下单即生成一张 CDKey + 支付指引。
  ⭐ 这是**手工核销收款方案**：支付资质（微信支付/支付宝商户号）尚未落地，
     系统不假装有「一键支付」按钮。真实链路是
     「下单 → 转账/线下支付 → 管理员核销 → 用户兑换到账」。
     收款不依赖任何支付网关资质，因此**今天就能收钱**。
- :func:`refund_order`（R3-6）：退款 + 扣回额度 + 审计，幂等防重复退。
- :func:`list_users` / :func:`set_user_banned`（R3-7）：用户列表与封禁。
- :func:`query_audit_logs`（R3-8）：审计日志查询。

===========================================================================
三条不可让步的底线
===========================================================================
1. **额度是账，审计是据**：任何动额度的动作（发放/扣回）必须落AuditLog，
   否则事后无法对账，退款纠纷无从举证。
2. **退款要真的扣回额度**：只改订单状态不扣额度，等于退款只退了个显示，
   用户照样拿额度用——这是最典型的「假退款」漏洞，本模块强制扣回。
3. **金额与额度都取定价真源**：价格来自 :mod:`studio.pricing`，
   禁止在本模块硬编码「300 元」这类数字。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from .. import errors
from ..db_models import AuditLog, Invite, Membership, Order, User, new_id, utcnow
from ..pricing import PLANS, plan_price_cents, plan_capacity
from .service import credits_left, ensure_membership

__all__ = [
    "create_order",
    "confirm_order_paid",
    "cancel_order",
    "refund_order",
    "list_orders",
    "list_users",
    "set_user_banned",
    "query_audit_logs",
    "grant_credits_to_user",
    "PAYMENT_INSTRUCTIONS",
]


# ---------------------------------------------------------------------------
# R3-2收款：下单
# ---------------------------------------------------------------------------

#: ⭐ 支付指引（手工核销方案）。这里**故意不写「点击支付」**——
#:   没有商户资质就不能假装有支付按钮，否则就是欺诈式界面。
#:   文案明确告知线下转账 + 管理员核销的真实流程。
PAYMENT_INSTRUCTIONS: list[str] = [
    "1. 订单已生成，下方卡密即为你的兑换码（仅需兑换一次，请勿转发他人）。",
    "2. 按订单金额完成转账/线下支付，并把付款凭证发给管理员。",
    "3. 管理员核销收款后，卡密即可兑换额度；在「设置 - 会员与额度」粘贴卡密即可到账。",
    "4. 若长时间未核销，请联系管理员；退款与撤单请联系管理员处理。",
]


def _get_tenant(db: Session, tenant_id: str):
    """取租户行；不存在则按 id 兜底返回 None（调用方决定是否报错）。"""
    from ..db_models import Tenant

    if tenant_id in ("", None, "default"):
        # 兼容 web 层的历史口径：tenant_id 传字符串 'default' 时按名字找
        return (
            db.query(Tenant).filter(Tenant.name == "default").first()
            or db.query(Tenant).filter(Tenant.id == str(tenant_id)).first()
        )
    from ..db_models import Tenant

    return db.query(Tenant).filter(Tenant.id == str(tenant_id)).first()


def _resolve_order_user(db: Session, tenant_id: str, user_id: str) -> User:
    """定位下单用户，必须同租户存在；兼容单机默认租户 'default' 与 UUID 自动对齐。"""
    user = (
        db.query(User)
        .filter(User.id == str(user_id), User.tenant_id == str(tenant_id))
        .first()
    )
    if user is None:
        u_any = db.query(User).filter(User.id == str(user_id)).first()
        def_t = _get_tenant(db, "default")
        def_ids = {"default", def_t.id if def_t else "default"}
        if u_any is not None and str(u_any.tenant_id) in def_ids and str(tenant_id) in def_ids:
            u_any.tenant_id = str(tenant_id)
            db.commit()
            return u_any
        errors.raise_err("NOT_FOUND", "用户不存在")
    return user


def create_order(
    db: Session,
    tenant_id: str,
    user_id: str,
    plan: str,
    *,
    actor: str = "",
) -> dict:
    """R3-2：创建订单并生成 CDKey。

    Args:
        plan: 套餐码（pro / studio）。free 不可购买。
        actor: 操作者（用户自助下单时为 user_id，管理员代下单为管理员 id）。

    Returns:
        含订单 id / 金额 / CDKey / 支付指引的 dict。

    ⚠️ 关键设计：**卡密在「下单」时就生成并返回给用户**（而不是等付款后才给）。
       因为卡密额度只在「兑换」时才真正发放到 memberships，
       即用户付款前自己把卡密兑换掉也不损失什么（那相当于他已付费却没付款，
       是平台营收损失；因此 :func:`confirm_order_paid` 之前的兑换应视为
       「预支额度」，运营核销时务必先确认是否已收到款）。
       这是手工核销方案的固有取舍，已在价格页与下单页明示。
    """
    from ..pricing import _sync_from_disk
    _sync_from_disk()
    plan_code = (plan or "").strip().lower()
    if plan_code not in PLANS:
        errors.raise_err(
            "BAD_REQUEST",
            "该套餐不可购买",
            hint="可选套餐：pro、studio；free 为免费档无需购买",
        )
    user = _resolve_order_user(db, tenant_id, user_id)
    if not user.is_active:
        errors.raise_err("FORBIDDEN", "账号已被停用，无法下单")

    cfg = PLANS[plan_code]
    credits = int(cfg["credits"])
    amount_cents = int(cfg["price_cents"])

    # 卡密与redeem 同源（都写 invites 表），否则生成的码无处可兑——
    # 这正是历史上「core.billing 写 JSON、adapter 读 invites」两套账本各说各话的老问题。
    from .service import create_invite

    tenant = _get_tenant(db, tenant_id)
    if tenant is None:
        errors.raise_err("INTERNAL", "租户不存在，无法下单")
    invite = create_invite(
        db, tenant, max_uses=1, credits_grant=credits, actor=actor or user.id
    )

    order = Order(
        id=new_id(),
        tenant_id=str(tenant_id),
        user_id=user.id,
        plan=plan_code,
        credits=credits,
        amount_cents=amount_cents,
        status="pending",
        cdkey=invite.code,
        note="",
    )
    db.add(order)
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=str(tenant_id),
            actor=actor or user.id,
            action="order.create",
            target=f"order:{order.id}",
            detail={
                "plan": plan_code,
                "credits": credits,
                "amount_cents": amount_cents,
                "amount_yuan": round(amount_cents / 100.0, 2),
                "username": user.username,
            },
        )
    )
    db.commit()
    db.refresh(order)
    return _order_view(db, order)


def _order_view(db: Session, order: Order) -> dict:
    """订单对外视图（含卡密；退款后不再返回卡密明文）。"""
    return {
        "id": order.id,
        "plan": order.plan,
        "credits": int(order.credits),
        "amount_cents": int(order.amount_cents),
        "amount_yuan": round(int(order.amount_cents) / 100.0, 2),
        "status": order.status,
        "cdkey": order.cdkey if order.status != "refunded" else "",
        "refunded_credits": int(order.refunded_credits),
        "note": order.note,
        "created_at": _iso(order.created_at),
        "paid_at": _iso(order.paid_at),
        "refunded_at": _iso(order.refunded_at),
        "payment_instructions": PAYMENT_INSTRUCTIONS if order.status == "pending" else [],
    }


def _iso(dt: datetime | None) -> str | None:
    """datetime → ISO 字符串（None 安全）。"""
    return dt.isoformat() if dt else None


def confirm_order_paid(
    db: Session, tenant_id: str, order_id: str, *, actor: str = ""
) -> dict:
    """管理员确认收款：pending → paid。

    幂等：已 paid 的重复确认直接返回当前状态，不报错（运营重复点不会失败）。
    """
    order = _get_order(db, tenant_id, order_id)
    if order.status == "paid":
        return _order_view(db, order)
    if order.status != "pending":
        errors.raise_err(
            "CONFLICT",
            f"当前订单状态为「{_status_cn(order.status)}」，无法标记为已收款",
            hint="只有待支付订单可以确认收款",
        )
    order.status = "paid"
    order.paid_at = utcnow()
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=str(tenant_id),
            actor=actor or "system",
            action="order.paid",
            target=f"order:{order.id}",
            detail={"amount_cents": int(order.amount_cents), "cdkey": order.cdkey},
        )
    )
    db.commit()
    db.refresh(order)
    return _order_view(db, order)


def cancel_order(
    db: Session, tenant_id: str, order_id: str, *, actor: str = "", reason: str = ""
) -> dict:
    """管理员/用户取消未支付订单：pending → cancelled，并作废对应卡密。"""
    order = _get_order(db, tenant_id, order_id)
    if order.status != "pending":
        errors.raise_err(
            "CONFLICT",
            f"当前订单状态为「{_status_cn(order.status)}」，无法取消",
            hint="只有待支付订单可以取消",
        )
    order.status = "cancelled"
    order.note = (reason or "用户放弃")[:512]
    # 作废卡密：撤销后即使拿到码也换不到额度
    if order.cdkey:
        db.execute(
            text("UPDATE invites SET status='revoked' WHERE tenant_id=:t AND code=:c"),
            {"t": str(tenant_id), "c": order.cdkey},
        )
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=str(tenant_id),
            actor=actor or "system",
            action="order.cancel",
            target=f"order:{order.id}",
            detail={"reason": order.note, "cdkey": order.cdkey},
        )
    )
    db.commit()
    db.refresh(order)
    return _order_view(db, order)


def _get_order(db: Session, tenant_id: str, order_id: str) -> Order:
    """按 (tenant, id) 取订单；跨租户一律404，兼容默认租户 'default' 与 UUID 对齐。"""
    order = (
        db.query(Order)
        .filter(Order.id == str(order_id), Order.tenant_id == str(tenant_id))
        .first()
    )
    if order is None:
        o_any = db.query(Order).filter(Order.id == str(order_id)).first()
        def_t = _get_tenant(db, "default")
        def_ids = {"default", def_t.id if def_t else "default"}
        if o_any is not None and str(o_any.tenant_id) in def_ids and str(tenant_id) in def_ids:
            return o_any
        errors.raise_err("NOT_FOUND", "订单不存在或无权查看")
    return order


def _status_cn(status: str) -> str:
    """订单状态中文名（给用户看，避免内部黑话）。"""
    return {
        "pending": "待支付",
        "paid": "已收款",
        "refunded": "已退款",
        "cancelled": "已取消",
    }.get(status, "未知状态")


# ---------------------------------------------------------------------------
# R3-6 退款
# ---------------------------------------------------------------------------

def refund_order(
    db: Session,
    tenant_id: str,
    order_id: str,
    *,
    actor: str = "",
    reason: str = "",
) -> dict:
    """R3-6 退款：**扣回已发放的额度** + 作废卡密 + 写审计日志。

    ⭐ 核心是「额度真的扣回」：只改订单状态不扣额度 = 假退款，
       用户退了款照样拿额度用。本函数会：
         1. 校验状态机（只有 paid 可退；已退订单直接拒，防重复退款）；
         2. 把 memberships.credits_total 减去本单发放额度，
            并把 credits_used 收敛到不超过新的 credits_total
            （否则会留下 total=3000 / used=32000 的坏数据）；
         3. **余额不会被扣成负数**（用户已花掉的部分扣不回来，
            最多把 credits_total 收到 0，差额如实返回给运营）；
         4. 作废卡密；
         5. 写 AuditLog（退款是资金动作，必须留证）。

    Returns:
        含 ``deducted``（实际从**可用余额**里扣回了多少）、``shortfall``
        （扣不回的差额）的视图。
        ⚠️ deducted 衡量的是「用户真正损失了多少可用额度」，
           而不是 credits_total 的减少量——若用户已把额度花掉，
           后者会虚高（看起来扣了 3 万，实际只扣回 1000）。
    """
    order = _get_order(db, tenant_id, order_id)
    if order.status == "refunded":
        errors.raise_err("CONFLICT", "该订单已退款，请勿重复操作")
    if order.status != "paid":
        errors.raise_err(
            "CONFLICT",
            f"当前订单状态为「{_status_cn(order.status)}」，无法退款",
            hint="只有已收款订单可以退款；未支付请直接取消",
        )

    granted = int(order.credits)
    membership = ensure_membership(db, str(tenant_id), order.user_id)
    before_total = int(membership.credits_total)
    before_used = int(membership.credits_used)
    balance_before = max(0, before_total - before_used)

    after_total = max(0, before_total - granted)
    #⭐ 额度扣回下限保护：不得把 credits_total 扣成负数；
    #   同时把 credits_used 收敛到不超过 credits_total——
    #   否则会出现 total=3000 / used=32000 这种「已用超过额度」的坏数据，
    #   余额被 max(0,...) 掩盖成0，看起来对、实则账坏了。
    after_used = min(before_used, after_total)
    deducted = balance_before - max(0, after_total - after_used)
    shortfall = granted - deducted
    membership.credits_total = after_total
    membership.credits_used = after_used
    db.add(membership)

    # 作废卡密，防止退款后还能兑换
    if order.cdkey:
        db.execute(
            text("UPDATE invites SET status='revoked' WHERE tenant_id=:t AND code=:c"),
            {"t": str(tenant_id), "c": order.cdkey},
        )

    order.status = "refunded"
    order.refunded_credits = deducted
    order.refunded_at = utcnow()
    order.note = (reason or "运营退款")[:512]

    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=str(tenant_id),
            actor=actor or "system",
            action="order.refund",
            target=f"order:{order.id}",
            detail={
                "reason": order.note,
                "granted": granted,
                "deducted": deducted,
                "shortfall": shortfall,
                "credits_total_before": before_total,
                "credits_total_after": after_total,
                "credits_used_before": before_used,
                "credits_used_after": after_used,
                "balance_before": balance_before,
                "user_id": order.user_id,
            },
        )
    )
    db.commit()
    db.refresh(order)
    view = _order_view(db, order)
    view["deducted"] = deducted
    view["shortfall"] = shortfall
    return view


def list_orders(
    db: Session, tenant_id: str, *, status: str = "", limit: int = 50, offset: int = 0
) -> dict:
    """R3-2/R3-6：订单列表（管理端用），支持按状态筛选与分页。

    Returns:
        ``{"items": [...], "total": n, "limit": l, "offset": o}``。
        卡密明文仅对未退款订单返回（退款后无意义且是凭据泄露面）。
    """
    q = db.query(Order).filter(Order.tenant_id == str(tenant_id))
    if status:
        q = q.filter(Order.status == str(status))
    total = q.count()
    rows = (
        q.order_by(Order.created_at.desc())
        .offset(max(0, int(offset)))
        .limit(min(200, max(1, int(limit))))
        .all()
    )
    return {
        "items": [_order_view(db, r) for r in rows],
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
    }


# ---------------------------------------------------------------------------
# R3-5 额度发放
# ---------------------------------------------------------------------------

def grant_credits_to_user(
    db: Session, tenant_id: str, user_id: str, amount: int, *, reason: str, actor: str
) -> dict:
    """R3-5：给指定用户发放额度（管理端HTTP 入口背后的业务逻辑）。

    复用 :func:`studio.membership.service.grant_credits`，因此
    「发放 + 审计」是同一事务，不会出现发了额度没留痕的情况。
    """
    if int(amount) <= 0:
        errors.raise_err("BAD_REQUEST", "发放额度必须为正数")
    membership = ensure_membership(db, str(tenant_id), str(user_id))
    before = credits_left(membership)
    from .service import grant_credits as _grant

    _grant(db, membership, int(amount), reason=reason or "管理员发放", actor=actor)
    db.refresh(membership)
    return {
        "user_id": str(user_id),
        "granted": int(amount),
        "balance_before": before,
        "balance_after": credits_left(membership),
        "credits_total": int(membership.credits_total),
        "tier": membership.tier,
    }


# ---------------------------------------------------------------------------
# R3-7 用户列表与封禁
# ---------------------------------------------------------------------------

def list_users(
    db: Session,
    tenant_id: str,
    *,
    keyword: str = "",
    tier: str = "",
    banned: str = "",
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """R3-7：用户列表（分页 + 搜用户名/邮箱/档位）。

    Args:
        keyword: 模糊匹配用户名 / 邮箱。
        tier:按档位过滤（free/pro/studio），空=不限。
        banned: "1" 只看封禁、"0" 只看正常、空=不限。
    """
    q = db.query(User).filter(User.tenant_id == str(tenant_id))
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(User.username.like(like), User.email.like(like)))
    if banned == "1":
        q = q.filter(User.is_active.is_(False))
    elif banned == "0":
        q = q.filter(User.is_active.is_(True))
    total = q.count()

    rows = (
        q.order_by(User.created_at.desc())
        .offset(max(0, int(offset)))
        .limit(min(100, max(1, int(limit))))
        .all()
    )
    items = []
    for u in rows:
        m = (
            db.query(Membership)
            .filter(Membership.tenant_id == str(tenant_id), Membership.user_id == u.id)
            .first()
        )
        cur_tier = (m.tier if m is not None else "free") or "free"
        if tier and cur_tier != str(tier).lower():
            continue
        total_credits = int(m.credits_total) if m is not None else 0
        used = int(m.credits_used) if m is not None else 0
        items.append({
            "user_id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            # ⭐ is_active=False 即「已封禁」，页面直接显示封禁态
            "is_active": bool(u.is_active),
            "banned": not bool(u.is_active),
            "tier": cur_tier,
            "credits_total": total_credits,
            "credits_used": used,
            "credits_left": max(0, total_credits - used),
            "avatar_url": "/static/img/default-avatar.png",
            "created_at": _iso(u.created_at),
            "last_login_at": _iso(u.last_login_at),
        })
    return {"items": items, "total": int(total), "limit": int(limit), "offset": int(offset)}


def set_user_banned(
    db: Session,
    tenant_id: str,
    user_id: str,
    banned: bool,
    *,
    actor: str = "",
    reason: str = "",
) -> dict:
    """R3-7：封禁 / 解封用户（**必须留审计日志**）。

    封禁只改 ``users.is_active``，不动额度、不删数据——
    解封后用户原样回来，这才是「禁用」而非「删除」。

    ⭐ 安全约束：不允许封禁管理员账号，否则可能把系统最后一个能进管理端的人
       锁在门外（无人可解封）。运营需先提升另一个账号再封禁。
    """
    user = _resolve_order_user(db, tenant_id, user_id)
    if user.role in ("admin", "owner"):
        errors.raise_err(
            "FORBIDDEN",
            "不能封禁管理员账号",
            hint="请先将权限移交给其他账号，避免系统失去管理入口",
        )
    before = bool(user.is_active)
    user.is_active = not bool(banned)
    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=str(tenant_id),
            actor=actor or "system",
            action="user.ban" if banned else "user.unban",
            target=f"user:{user.id}",
            detail={
                "username": user.username,
                "reason": (reason or "")[:512],
                "is_active_before": before,
                "is_active_after": bool(user.is_active),
            },
        )
    )
    db.commit()
    db.refresh(user)
    return {
        "user_id": user.id,
        "username": user.username,
        "is_active": bool(user.is_active),
        "banned": not bool(user.is_active),
    }


# ---------------------------------------------------------------------------
# R3-8 审计日志查询
# ---------------------------------------------------------------------------

def query_audit_logs(
    db: Session,
    tenant_id: str,
    *,
    action: str = "",
    actor: str = "",
    target: str = "",
    keyword: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """R3-8：审计日志查询（分页 + 按动作/操作人/对象过滤）。

    ⚠️ 审计表只增不改，本查询**永远不提供删除/修改接口**。
    """
    q = db.query(AuditLog).filter(AuditLog.tenant_id == str(tenant_id))
    if action:
        q = q.filter(AuditLog.action == str(action))
    if actor:
        q = q.filter(AuditLog.actor == str(actor))
    if target:
        q = q.filter(AuditLog.target.like(f"%{target.strip()}%"))
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(AuditLog.action.like(like), AuditLog.target.like(like)))
    total = q.count()
    rows = (
        q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(max(0, int(offset)))
        .limit(min(200, max(1, int(limit))))
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "actor": r.actor,
                "action": r.action,
                "target": r.target,
                "detail": r.detail or {},
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ],
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
    }


def audit_actions(db: Session, tenant_id: str) -> list[str]:
    """已出现过的审计动作列表（供查询页做下拉筛选，避免用户瞎猜动作名）。"""
    rows = (
        db.query(AuditLog.action)
        .filter(AuditLog.tenant_id == str(tenant_id))
        .distinct()
        .order_by(AuditLog.action.asc())
        .limit(100)
        .all()
    )
    return [str(r[0]) for r in rows if r and r[0]]