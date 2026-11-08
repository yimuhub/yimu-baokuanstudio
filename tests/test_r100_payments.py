# SPDX-License-Identifier: BUSL-1.1
"""R10 在线支付闭环回归：渠道适配器 / 回调验签 / 自动核销 / 幂等 / 金额防篡改。

验收标准（对应审查报告 P0「支付闭环」整改）：
- P10-1 沙箱支付端到端：下单 → 模拟支付 → 自动确认收款 + 卡密自动兑换到账
- P10-2 幂等：同一订单重复回调/重复结算不重复加额度
- P10-3 金额防篡改：回调金额与订单不符时拒绝自动核销且订单保持待支付
- P10-4 虎皮椒验签：合法签名通过、伪造签名拒绝、非 00 状态拒绝
- P10-5 Stripe Webhook 验签：合法通过、过期/伪造拒绝
- P10-6 渠道列表：manual 恒可用，沙箱默认可用
- P10-7 越权：不能为他人订单创建支付/沙箱核销
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import time

import pytest

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-r10pay")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")

from tests.wsb_common import unique_name  # noqa: E402


# ---------------------------------------------------------------------------
# 签名原语
# ---------------------------------------------------------------------------

class TestSignatures:
    def test_xunhu_sign_matches_reference_construction(self):
        from studio.membership.payments import xunhu_sign
        params = {"version": "1.1", "appid": "app123", "tradeorderid": "o-1",
                  "totalfee": "30.00", "hash": "should-be-ignored", "note": ""}
        # 手工按规范重算：key 升序、跳过 hash 与空值、拼接 appsecret 后 MD5
        items = sorted((k, v) for k, v in params.items() if k != "hash" and v != "")
        qs = "&".join(f"{k}={v}" for k, v in items)
        expect = hashlib.md5((qs + "sec-abc").encode()).hexdigest()
        assert xunhu_sign(params, "sec-abc") == expect

    def test_xunhu_verify_callback_ok_and_forge(self, monkeypatch):
        from studio.membership import payments
        monkeypatch.setenv("YIMU_PAY_XUNHU_SECRET", "sec-abc")
        cb = {"tradeorderid": "ord-1", "orderly": "ch-9", "price": "30.00",
              "returncode": "00", "platform": "wechat"}
        cb["hash"] = payments.xunhu_sign(cb, "sec-abc")
        evt = payments.verify_callback("xunhu", query=cb, body=b"", headers={})
        assert evt["order_id"] == "ord-1"
        assert evt["amount_cents"] == 3000
        assert evt["trade_no"] == "ch-9"
        # 伪造：篡改金额但保留原 hash
        bad = dict(cb, price="0.01")
        with pytest.raises(ValueError, match="验签"):
            payments.verify_callback("xunhu", query=bad, body=b"", headers={})
        # 非 00 状态（需按新参数重算合法签名，才能走到状态检查）
        bad2 = dict(cb, returncode="01")
        bad2["hash"] = payments.xunhu_sign(bad2, "sec-abc")
        with pytest.raises(ValueError, match="状态"):
            payments.verify_callback("xunhu", query=bad2, body=b"", headers={})

    def test_stripe_webhook_signature(self, monkeypatch):
        from studio.membership.payments import stripe_verify_webhook
        secret = "whsec_test"
        payload = json.dumps({"type": "checkout.session.completed"}).encode()
        t = str(int(time.time()))
        good = hmac_mod.new(secret.encode(), f"{t}.".encode() + payload,
                            hashlib.sha256).hexdigest()
        assert stripe_verify_webhook(payload, f"t={t},v1={good}", secret)
        # 伪造签名
        assert not stripe_verify_webhook(payload, f"t={t},v1={'0' * 64}", secret)
        # 超过时间容差（构造 10 分钟前的时间戳）
        old_t = str(int(time.time()) - 600)
        old_sig = hmac_mod.new(secret.encode(), f"{old_t}.".encode() + payload,
                               hashlib.sha256).hexdigest()
        assert not stripe_verify_webhook(payload, f"t={old_t},v1={old_sig}", secret)


# ---------------------------------------------------------------------------
# 业务层：沙箱端到端 / 幂等 / 金额防篡改
# ---------------------------------------------------------------------------

@pytest.fixture()
def pay_env(db_session, monkeypatch):
    """支付测试公共环境：隔离租户 + 用户 + membership。"""
    from studio.auth import ensure_default_tenant
    from studio.db_models import User
    from studio.membership.service import ensure_membership

    db = db_session
    db.rollback()
    t = ensure_default_tenant(db)
    db.commit()
    uid = unique_name("payu")
    db.add(User(id=uid, tenant_id=t.id, username=uid, email="",
                password_hash="x", salt="x", role="user", is_active=True))
    db.commit()
    m = ensure_membership(db, t.id, uid)
    db.commit()
    return {"db": db, "tenant_id": t.id, "user_id": uid, "balance0": m.credits_total - m.credits_used}


def _mk_order(env, plan="pro"):
    from studio.membership import commerce
    return commerce.create_order(env["db"], env["tenant_id"], env["user_id"], plan, actor=env["user_id"])


class TestSandboxSettle:
    def test_end_to_end_auto_redeem(self, pay_env):
        from studio.membership import commerce, payments
        from studio.membership.service import credits_left, ensure_membership

        order = _mk_order(pay_env)
        # R11 融合:远端修复 0 元开通漏洞,paid 前 _order_view 不下发卡密(库内仍有,供自动核销)
        assert order["status"] == "pending" and order["cdkey"] == ""
        r = payments.settle_paid_order(
            pay_env["db"], pay_env["tenant_id"], order["id"],
            channel="sandbox", trade_no="sb-1", amount_cents=order["amount_cents"])
        assert r["ok"] is True
        assert r["order"]["status"] == "paid"
        assert r["auto_redeem"]["redeemed"] is True
        # 余额真实增加（自动兑换已到账）
        m = ensure_membership(pay_env["db"], pay_env["tenant_id"], pay_env["user_id"])
        pay_env["db"].commit()
        assert credits_left(m) == pay_env["balance0"] + int(order["credits"])

    def test_double_settle_idempotent(self, pay_env):
        from studio.membership import payments
        from studio.membership.service import credits_left, ensure_membership

        order = _mk_order(pay_env)
        payments.settle_paid_order(pay_env["db"], pay_env["tenant_id"], order["id"],
                                   channel="sandbox", amount_cents=order["amount_cents"])
        m0 = ensure_membership(pay_env["db"], pay_env["tenant_id"], pay_env["user_id"])
        bal0 = credits_left(m0)
        r2 = payments.settle_paid_order(pay_env["db"], pay_env["tenant_id"], order["id"],
                                        channel="sandbox", amount_cents=order["amount_cents"])
        assert r2["idempotent"] is True
        m1 = ensure_membership(pay_env["db"], pay_env["tenant_id"], pay_env["user_id"])
        assert credits_left(m1) == bal0, "重复结算不得重复加额度"

    def test_amount_mismatch_rejected(self, pay_env):
        import pytest as _pytest
        from fastapi import HTTPException
        from studio.membership import payments

        order = _mk_order(pay_env)
        with _pytest.raises(HTTPException) as _ei:
            payments.settle_paid_order(pay_env["db"], pay_env["tenant_id"], order["id"],
                                       channel="xunhu", amount_cents=1)
        # 订单必须仍是待支付（留给人工核对）
        from studio.membership import commerce
        v = commerce._order_view(pay_env["db"], commerce._get_order(
            pay_env["db"], pay_env["tenant_id"], order["id"]))
        assert v["status"] == "pending"

    def test_settle_foreign_order_404(self, pay_env):
        import pytest as _pytest
        from fastapi import HTTPException
        from studio.membership import payments

        with _pytest.raises(HTTPException):
            payments.settle_paid_order(pay_env["db"], pay_env["tenant_id"],
                                       "no-such-order", channel="sandbox")


# ---------------------------------------------------------------------------
# HTTP 层：渠道列表 / 沙箱收银台 / 越权
# ---------------------------------------------------------------------------

class _PayClient:
    """复用 R3 隔离方案的最小 web 客户端。"""

    def __init__(self, client, db_session, tmp):
        self._c = client
        self.db = db_session
        self._tmp = tmp
        self._csrf = "r10-csrf"
        self._c.cookies.set("csrf_token", self._csrf)
        self._uid = None

    def as_user(self, role: str = "user"):
        from core import auth
        uid = auth.register_user(unique_name("payweb"), "pw123456")["user"]["id"]
        if role in ("admin", "owner"):
            c = auth._db()
            c.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
            c.commit(); c.close()
        self._c.cookies.set("mf_v6_token", auth.make_token(
            {"user_id": uid, "username": uid, "role": role}))
        self._uid = uid
        return self

    def post(self, url, **kw):
        h = dict(kw.pop("headers", None) or {})
        h.setdefault("X-CSRF-Token", self._csrf)
        return self._c.post(url, headers=h, **kw)

    def get(self, url, **kw):
        return self._c.get(url, **kw)


@pytest.fixture()
def pay_web(tmp_path, db_session, monkeypatch):
    from fastapi.testclient import TestClient

    from core import auth as core_auth
    from core import billing as cb
    from core import db as core_db

    test_db = tmp_path / "core_mediaflow.db"
    monkeypatch.setattr(core_db, "DB_PATH", test_db)
    monkeypatch.setattr(core_db, "DATA", tmp_path)
    monkeypatch.setattr(core_auth, "DB_PATH", test_db)
    monkeypatch.setattr(cb, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cb, "BILLING_FILE", tmp_path / "billing.json")

    from studio.membership import capabilities as caps
    monkeypatch.setenv("YIMU_DB_URL", f"sqlite:///{db_session.bind.url.database}")
    monkeypatch.setattr(caps, "_session_factory_cache", {})

    from web import admin as web_admin
    monkeypatch.setattr(web_admin, "load_env", lambda: {"ADMIN_PASSWORD": "r10-test-pw"})
    monkeypatch.setattr(web_admin, "JOBS", {})

    with TestClient(web_admin.app) as client:
        yield _PayClient(client, db_session, tmp_path)


class TestPayHttp:
    def test_channels_list(self, pay_web):
        pay_web.as_user()
        r = pay_web.get("/api/billing/pay/channels")
        assert r.status_code == 200
        codes = [c["code"] for c in r.json()["channels"]]
        assert "manual" in codes and "sandbox" in codes

    def test_sandbox_checkout_end_to_end(self, pay_web):
        pay_web.as_user()
        # 下单（走既有 HTTP 接口，保持与真实链路一致）
        r = pay_web.post("/api/billing/order", json={"plan": "pro"})
        assert r.status_code == 200, r.text
        order = r.json()["order"]
        # 沙箱模拟支付成功
        r2 = pay_web.post(f"/api/billing/pay/sandbox/{order['id']}/confirm")
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["order"]["status"] == "paid"
        assert body["auto_redeem"]["redeemed"] is True
        # 再点一次幂等
        r3 = pay_web.post(f"/api/billing/pay/sandbox/{order['id']}/confirm")
        assert r3.status_code == 200 and r3.json()["idempotent"] is True

    def test_cannot_pay_others_order(self, pay_web):
        pay_web.as_user()
        r = pay_web.post("/api/billing/order", json={"plan": "pro"})
        order_id = r.json()["order"]["id"]
        # 切换到另一个用户
        pay_web.as_user()
        r2 = pay_web.post(f"/api/billing/pay/sandbox/{order_id}/confirm")
        assert r2.status_code in (403, 404)
        r3 = pay_web.post("/api/billing/pay/create",
                          json={"order_id": order_id, "channel": "sandbox"})
        assert r3.status_code in (403, 404)

    def test_unknown_notify_channel_rejected(self, pay_web):
        pay_web.as_user()
        r = pay_web.get("/api/billing/pay/notify/evil", params={"hash": "x"})
        assert r.status_code == 400

    def test_xunhu_notify_settles_order(self, pay_web, monkeypatch):
        """虎皮椒合法回调 → 订单自动 paid + 卡密自动兑换。"""
        monkeypatch.setenv("YIMU_PAY_XUNHU_SECRET", "sec-notify")
        from studio.membership import payments as pay

        pay_web.as_user()
        r = pay_web.post("/api/billing/order", json={"plan": "pro"})
        order = r.json()["order"]
        cb = {"tradeorderid": order["id"], "orderly": "ch-77", "price": f"{order['amount_yuan']:.2f}",
              "returncode": "00", "platform": "alipay"}
        cb["hash"] = pay.xunhu_sign(cb, "sec-notify")
        r2 = pay_web.get("/api/billing/pay/notify/xunhu", params=cb)
        assert r2.status_code == 200 and r2.text == "success"
        # 订单已支付
        ro = pay_web.get("/api/billing/orders")
        found = [x for x in ro.json()["items"] if x["id"] == order["id"]][0]
        assert found["status"] == "paid"
        # 伪造回调被拒
        cb_bad = dict(cb, price="0.01")
        r3 = pay_web.get("/api/billing/pay/notify/xunhu", params=cb_bad)
        assert r3.status_code == 400
