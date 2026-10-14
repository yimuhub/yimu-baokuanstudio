# SPDX-License-Identifier: BUSL-1.1
"""统一商业化门面服务（BillingService）：

收敛 core/billing.py、studio/billing_adapter.py 与 studio/membership/commerce.py，
对外提供单一事务级接口：查询状态、创建订单、收款确认、卡密核销、一键激活、撤单与退款。
"""
from __future__ import annotations

from typing import Any
from studio import billing_adapter, pricing
from studio.auth import ensure_default_tenant
from studio.db_models import Order, Tenant, User as StudioUser
from studio.membership import commerce
from studio.membership.service import ensure_membership


class BillingService:
    """大厂级单一计费与订单领域服务门面。"""

    @staticmethod
    def ensure_user_context(db, user_id: str, user_meta: dict[str, Any] | None = None) -> str:
        """确保用户在 studio 账本库中拥有对齐的 Tenant 与 Membership 行，返回权威 tenant_id。"""
        uid = str(user_id or "u-admin")
        u_row = db.query(StudioUser).filter(StudioUser.id == uid).first()
        if u_row is not None and u_row.tenant_id:
            t_exists = db.query(Tenant).filter(Tenant.id == str(u_row.tenant_id)).first()
            if t_exists is not None:
                ensure_membership(db, str(u_row.tenant_id), uid)
                db.commit()
                return str(u_row.tenant_id)
            t_def = ensure_default_tenant(db)
            u_row.tenant_id = t_def.id
            db.commit()
            ensure_membership(db, t_def.id, uid)
            db.commit()
            return str(t_def.id)

        t_def = ensure_default_tenant(db)
        meta = user_meta or {}
        db.add(
            StudioUser(
                id=uid,
                tenant_id=t_def.id,
                username=str(meta.get("username") or uid),
                email=str(meta.get("email") or ""),
                password_hash="x",
                salt="x",
                role=str(meta.get("role") or ("admin" if uid == "u-admin" else "user")),
                is_active=True,
            )
        )
        db.commit()
        ensure_membership(db, t_def.id, uid)
        db.commit()
        return str(t_def.id)

    def get_catalog(self, current_user: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "plans": pricing.plan_catalog(),
            "full_drama_credits": pricing.FULL_DRAMA_CREDITS,
            "credit_price_cents": pricing.CREDIT_PRICE_CENTS,
        }
        if current_user:
            payload["current"] = {
                "user_id": str(current_user.get("id") or ""),
                "tier": str(current_user.get("plan") or "free"),
            }
        return payload

    def create_order_for_user(self, user_id: str, plan: str, user_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        db = billing_adapter._web_session()
        try:
            tid = self.ensure_user_context(db, user_id, user_meta)
            return commerce.create_order(db, tid, user_id, plan)
        finally:
            db.close()

    def activate_order_one_step(self, order_id: str, actor_id: str, user_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """一步完成订单确认收款 + 卡密核销激活到账。"""
        db = billing_adapter._web_session()
        try:
            tid = self.ensure_user_context(db, actor_id, user_meta)
            order = (
                db.query(Order).filter(Order.id == str(order_id), Order.tenant_id == tid).first()
                or db.query(Order).filter(Order.id == str(order_id)).first()
            )
            if order is None:
                return {"ok": False, "msg": "订单不存在"}
            if order.status == "pending":
                commerce.confirm_order_paid(db, str(order.tenant_id), str(order.id), actor=actor_id)
                db.refresh(order)
            cdkey = order.cdkey
            buyer_id = order.user_id
        finally:
            db.close()
        if not cdkey:
            return {"ok": False, "msg": "该订单无可用卡密"}
        res = billing_adapter.redeem_cdkey_for_user(cdkey, buyer_id)
        return {"ok": bool(res.get("ok")), "redeem": res, "order_id": order_id}


billing_service = BillingService()
