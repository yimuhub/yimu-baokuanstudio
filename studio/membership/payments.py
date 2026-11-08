# SPDX-License-Identifier: BUSL-1.1
"""R10 在线支付闭环：渠道适配器 → 回调验签 → 自动核销（下款到账）。

===========================================================================
本模块解决什么
===========================================================================
R3 的收款链路是「下单 → 线下转账 → 管理员核销 → 用户兑换」，整条链路唯一
无法自助完成的环节是收款本身。本模块在不破坏既有账本安全设计的前提下补上
「支付回调 = 自动核销」这层胶水：

    create_order（不变）
        → create_payment（生成渠道收银台链接）
        → 渠道回调 notify
        → verify_callback（验签，防伪造）
        → settle_paid_order（幂等确认收款 + **自动把卡密兑换到下单用户**）
        → 用户直接可用，无需再手动兑换

===========================================================================
安全不变量（不可让步）
===========================================================================
1. **验签不过 = 拒绝**：回调必须先通过渠道签名校验，才允许触碰订单状态。
2. **金额不符 = 拒绝自动核销**：回调金额与订单金额不一致时拒收（留人工处理），
   防止「1 分钱买 Pro」类金额篡改。
3. **幂等**：同一订单重复回调只生效一次（渠道重试是常态）。
4. **已收款不回滚**：先确认收款再兑换；兑换失败自动转为「手动兑换」通道，
   绝不把已收款订单退回 pending（钱已到账，状态不可逆）。
5. **密钥只走环境变量**：绝不硬编码，与 .env / CI 密钥扫描体系一致。

===========================================================================
渠道与配置（全部通过环境变量启用，缺省仅沙箱）
===========================================================================
- ``sandbox``（默认开）：本地/演示用模拟收银台，不产生真实资金；
  生产环境请设置 ``YIMU_PAY_SANDBOX=0`` 关闭。
- ``xunhu`` 虎皮椒（个人可用，微信/支付宝扫码）：
  ``YIMU_PAY_XUNHU_APPID`` / ``YIMU_PAY_XUNHU_SECRET``（必填），
  ``YIMU_PAY_XUNHU_GATEWAY``（选填，默认官方 v1 网关）。
- ``stripe`` Stripe Checkout（海外/标准 Webhook）：
  ``YIMU_PAY_STRIPE_KEY`` / ``YIMU_PAY_STRIPE_WEBHOOK_SECRET``（必填）。
- 公网回调地址前缀：``YIMU_PUBLIC_BASE_URL``（如 https://yimu.example.com）。

签名算法说明（虎皮椒 v1）：参数按 key ASCII 升序拼接为 ``k1=v1&k2=v2…``
（跳过 hash 与空值），末尾直接拼接 appsecret 后取 MD5，与官方示例一致；
若渠道升级签名规范，仅需调整 :func:`_xunhu_sign` 一处。
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os
from typing import Any

import httpx

__all__ = [
    "available_channels",
    "create_payment",
    "verify_callback",
    "settle_paid_order",
    "xunhu_sign",
    "stripe_verify_webhook",
]

_TIMEOUT = 15


# ---------------------------------------------------------------------------
# 渠道配置探测
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _public_base() -> str:
    return _env("YIMU_PUBLIC_BASE_URL").rstrip("/")


def available_channels() -> list[dict[str, Any]]:
    """当前可用的支付渠道（给前端渲染收银台按钮）。manual 恒可用。"""
    chans: list[dict[str, Any]] = []
    if _env("YIMU_PAY_SANDBOX", "1") not in ("0", "false", "no"):
        chans.append({
            "code": "sandbox", "name": "沙箱模拟支付",
            "desc": "开发/演示环境模拟收款，不产生真实资金",
            "online": True,
        })
    if _env("YIMU_PAY_XUNHU_APPID") and _env("YIMU_PAY_XUNHU_SECRET"):
        chans.append({
            "code": "xunhu", "name": "微信/支付宝扫码（虎皮椒）",
            "desc": "扫码支付，回调验签后自动到账", "online": True,
        })
    if _env("YIMU_PAY_STRIPE_KEY") and _env("YIMU_PAY_STRIPE_WEBHOOK_SECRET"):
        chans.append({
            "code": "stripe", "name": "Stripe Checkout",
            "desc": "海外银行卡支付，Webhook 验签后自动到账", "online": True,
        })
    chans.append({
        "code": "manual", "name": "线下转账 + 核销",
        "desc": "按订单金额转账并联系管理员确认收款", "online": False,
    })
    return chans


# ---------------------------------------------------------------------------
# 签名原语（可单测）
# ---------------------------------------------------------------------------

def xunhu_sign(params: dict[str, Any], app_secret: str) -> str:
    """虎皮椒 v1 签名：key ASCII 升序拼 query（跳过 hash/空值）+ appsecret 后 MD5。"""
    items = sorted((k, v) for k, v in params.items() if k != "hash" and str(v) != "")
    qs = "&".join(f"{k}={v}" for k, v in items)
    return hashlib.md5((qs + app_secret).encode("utf-8")).hexdigest()


def stripe_verify_webhook(payload: bytes, sig_header: str, secret: str, *, tol_seconds: int = 300) -> bool:
    """Stripe Webhook 验签（Stripe-Signature: t=...,v1=...，HMAC-SHA256(t + '.' + body)）。"""
    try:
        parts = dict(
            p.split("=", 1) for p in (sig_header or "").split(",") if "=" in p
        )
        t = parts.get("t", "")
        v1 = parts.get("v1", "")
        if not t or not v1:
            return False
        import time as _time
        if abs(_time.time() - int(t)) > tol_seconds:
            return False
        signed = f"{t}.".encode("utf-8") + payload
        expect = hmac_mod.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        return hmac_mod.compare_digest(expect, v1)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 创建支付
# ---------------------------------------------------------------------------

def create_payment(
    db: Any, tenant_id: str, user_id: str, order_id: str, channel: str
) -> dict[str, Any]:
    """为待支付订单生成渠道收银台链接（sandbox 返回页内模拟标识）。

    越权防护：订单必须属于 (tenant_id, user_id) 本人，否则 NOT_FOUND。
    """
    from .. import errors
    from ..db_models import Order
    from . import commerce

    order = (
        db.query(Order)
        .filter(Order.id == str(order_id), Order.tenant_id == str(tenant_id))
        .first()
    )
    if order is None or str(order.user_id) != str(user_id):
        errors.raise_err("NOT_FOUND", "订单不存在或无权支付")
    if order.status != "pending":
        errors.raise_err("CONFLICT", f"订单当前为「{commerce._status_cn(order.status)}」，无需支付")

    channel = (channel or "").strip().lower()
    base = _public_base()
    notify = f"{base}/api/billing/pay/notify"

    if channel == "sandbox":
        if _env("YIMU_PAY_SANDBOX", "1") in ("0", "false", "no"):
            errors.raise_err("FORBIDDEN", "沙箱支付已在生产配置中关闭")
        return {"channel": "sandbox", "mode": "in-page", "order_id": order.id,
                "amount_yuan": round(int(order.amount_cents) / 100.0, 2)}

    if channel == "xunhu":
        appid = _env("YIMU_PAY_XUNHU_APPID")
        secret = _env("YIMU_PAY_XUNHU_SECRET")
        gateway = _env("YIMU_PAY_XUNHU_GATEWAY", "https://pay.xunhuweb.cn/main.php/pay/payload")
        if not (appid and secret):
            errors.raise_err("BAD_REQUEST", "虎皮椒渠道未配置")
        if not base:
            errors.raise_err("BAD_REQUEST", "未配置 YIMU_PUBLIC_BASE_URL，无法回传支付结果")
        params = {
            "version": "1.1",
            "lang": "zh-cn",
            "plugins": "yimu-studio",
            "appid": appid,
            "tradeorderid": order.id,
            "totalfee": f"{int(order.amount_cents) / 100.0:.2f}",
            "goodsname": f"一幕YIMU {str(order.plan).upper()} 套餐",
            "returnurl": f"{base}/pricing",
            "notifyurl": f"{notify}/xunhu",
        }
        params["hash"] = xunhu_sign(params, secret)
        try:
            resp = httpx.post(gateway, data=params, timeout=_TIMEOUT)
            data = resp.json()
        except Exception as e:  # 网络失败不吞，向上给可行动提示
            raise RuntimeError(f"支付网关连接失败：{e}") from e
        pay_url = data.get("payurl") or data.get("url") or ""
        if not pay_url:
            raise RuntimeError(f"支付网关未返回收银台链接：{str(data.get('msg') or data)[:200]}")
        return {"channel": "xunhu", "mode": "redirect", "pay_url": pay_url, "order_id": order.id}

    if channel == "stripe":
        key = _env("YIMU_PAY_STRIPE_KEY")
        whsec = _env("YIMU_PAY_STRIPE_WEBHOOK_SECRET")
        if not (key and whsec):
            errors.raise_err("BAD_REQUEST", "Stripe 渠道未配置")
        if not base:
            errors.raise_err("BAD_REQUEST", "未配置 YIMU_PUBLIC_BASE_URL，无法回传支付结果")
        form = {
            "mode": "payment",
            "client_reference_id": order.id,
            "metadata[order_id]": order.id,
            "metadata[tenant_id]": str(tenant_id),
            "success_url": f"{base}/pricing?paid={order.id}",
            "cancel_url": f"{base}/pricing?cancelled={order.id}",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "cny",
            "line_items[0][price_data][unit_amount]": str(int(order.amount_cents)),
            "line_items[0][price_data][product_data][name]": f"一幕YIMU {str(order.plan).upper()} 套餐",
        }
        try:
            resp = httpx.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=form,
                auth=(key, ""),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=_TIMEOUT,
            )
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Stripe 连接失败：{e}") from e
        pay_url = data.get("url") or ""
        if not pay_url:
            raise RuntimeError(f"Stripe 未返回收银台链接：{str(data.get('error') or data)[:200]}")
        return {"channel": "stripe", "mode": "redirect", "pay_url": pay_url, "order_id": order.id}

    errors.raise_err("BAD_REQUEST", f"未知支付渠道：{channel or '(空)'}")
    raise AssertionError  # unreachable


# ---------------------------------------------------------------------------
# 回调验签 → 结构化结果
# ---------------------------------------------------------------------------

def verify_callback(channel: str, *, query: dict[str, Any], body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """验签并归一化回调为 {order_id, trade_no, amount_cents, raw}；验签失败抛 ValueError。"""
    if channel == "xunhu":
        secret = _env("YIMU_PAY_XUNHU_SECRET")
        if not secret:
            raise ValueError("渠道未配置")
        got = str(query.get("hash") or "")
        if not got or not hmac_mod.compare_digest(got, xunhu_sign(query, secret)):
            raise ValueError("虎皮椒验签失败")
        if str(query.get("returncode") or "") != "00":
            raise ValueError(f"渠道返回非成功状态：{query.get('returncode')}")
        price = str(query.get("price") or "0")
        try:
            amount_cents = int(round(float(price) * 100))
        except ValueError:
            raise ValueError(f"回调金额非法：{price}") from None
        return {
            "order_id": str(query.get("tradeorderid") or ""),
            "trade_no": str(query.get("orderly") or query.get("transactionid") or ""),
            "amount_cents": amount_cents,
            "raw": dict(query),
        }
    if channel == "stripe":
        secret = _env("YIMU_PAY_STRIPE_WEBHOOK_SECRET")
        if not secret:
            raise ValueError("渠道未配置")
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature") or ""
        if not stripe_verify_webhook(body, sig, secret):
            raise ValueError("Stripe 验签失败")
        import json as _json
        try:
            event = _json.loads(body or b"{}")
        except Exception:
            raise ValueError("Stripe 事件体非法") from None
        if str(event.get("type") or "") != "checkout.session.completed":
            raise ValueError(f"忽略非完成事件：{event.get('type')}")
        obj = (event.get("data") or {}).get("object") or {}
        meta = obj.get("metadata") or {}
        received = int(obj.get("amount_total") or obj.get("amount_received") or 0)
        return {
            "order_id": str(meta.get("order_id") or obj.get("client_reference_id") or ""),
            "trade_no": str(obj.get("payment_intent") or obj.get("id") or ""),
            "amount_cents": received,
            "raw": {"id": event.get("id"), "type": event.get("type")},
        }
    raise ValueError(f"未知回调渠道：{channel}")


# ---------------------------------------------------------------------------
# 自动核销（幂等）
# ---------------------------------------------------------------------------

def settle_paid_order(
    db: Any,
    tenant_id: str,
    order_id: str,
    *,
    channel: str,
    trade_no: str = "",
    amount_cents: int | None = None,
) -> dict[str, Any]:
    """回调确认后的自动核销：确认收款 + 把卡密自动兑换到下单用户。

    幂等：已 paid 的订单重复结算直接返回（不重复加额度）。
    金额不符：抛 CONFLICT 拒绝自动核销，留给管理员人工核对（资金安全不变量）。
    """
    from .. import errors
    from ..db_models import AuditLog, User, new_id
    from . import commerce, service

    order = commerce._get_order(db, str(tenant_id), str(order_id))
    if order.status == "paid":
        return {"ok": True, "idempotent": True, "order": commerce._order_view(db, order),
                "auto_redeem": {"redeemed": False, "reason": "订单此前已完成收款"}}
    if order.status != "pending":
        errors.raise_err("CONFLICT", f"订单状态为「{commerce._status_cn(order.status)}」，无法自动核销")
    if amount_cents is not None and int(amount_cents) != int(order.amount_cents):
        db.add(AuditLog(
            id=new_id(), tenant_id=str(tenant_id), actor=f"pay:{channel}",
            action="order.pay_amount_mismatch", target=f"order:{order.id}",
            detail={"expected": int(order.amount_cents), "received": int(amount_cents),
                    "trade_no": trade_no},
        ))
        db.commit()
        errors.raise_err("CONFLICT", "回调金额与订单金额不符，已拒绝自动核销（请人工核对）")

    # 1. 先确认收款（幂等，状态 pending→paid，落审计）
    commerce.confirm_order_paid(db, str(tenant_id), order.id, actor=f"pay:{channel}")

    # 2. 再自动兑换卡密到下单用户（失败自动转人工兑换，绝不回滚已收款状态）
    auto: dict[str, Any] = {"redeemed": False}
    if order.cdkey:
        try:
            user = db.query(User).filter(User.id == order.user_id).first()
            tenant = service.get_tenant(db, str(tenant_id)) if hasattr(service, "get_tenant") else None
            if tenant is None:
                from ..db_models import Tenant
                tenant = (
                    db.query(Tenant).filter(Tenant.id == str(tenant_id)).first()
                    or db.query(Tenant).filter(Tenant.name == "default").first()
                )
            if user is None or tenant is None:
                raise RuntimeError("用户或租户缺失，无法自动兑换")
            service.redeem_invite(db, tenant, order.cdkey, user)
            auto = {"redeemed": True, "credits": int(order.credits)}
        except Exception as e:
            db.rollback()  # 只回滚兑换事务；收款状态已提交，不受影响
            auto = {"redeemed": False, "reason": str(e)[:200]}
            db.add(AuditLog(
                id=new_id(), tenant_id=str(tenant_id), actor=f"pay:{channel}",
                action="order.auto_redeem_failed", target=f"order:{order.id}",
                detail={"reason": str(e)[:200], "cdkey": order.cdkey,
                        "hint": "用户可在核销框手动兑换该卡密"},
            ))
            db.commit()

    # 3. 漏斗埋点：支付成功（自动化）
    try:
        from core import analytics
        analytics.track("order_paid_auto", order.user_id,
                        {"plan": order.plan, "channel": channel,
                         "amount_yuan": round(int(order.amount_cents) / 100.0, 2)})
    except Exception:
        pass

    view = commerce._order_view(db, order)
    view["auto_redeem"] = auto
    view["trade_no"] = trade_no
    view["channel"] = channel
    return {"ok": True, "idempotent": False, "order": view, "auto_redeem": auto}
