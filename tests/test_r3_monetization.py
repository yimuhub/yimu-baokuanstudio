# SPDX-License-Identifier: BUSL-1.1
"""R3 变现通路批次回归测试：价格页 / 下单收款 / 额度引导 / 发放 / 退款 / 用户 / 审计 / 草稿隔离。

===========================================================================
验收标准与对应测试
===========================================================================
- R3-1 三档定价如实展示（Free 跑不完完整短剧）→ TestPricing
- R3-2 下单 → 拿卡密 → 核销 → 兑换到账（**端到端**）→ TestOrderToCdkeyFlow
- R3-3 升级弹窗不再是死胡同（前端静态护栏）→ TestFrontendUpgradeModal
- R3-4 额度墙引导带缺口与套餐（不与 R5-3 邮件冲突）→ TestQuotaWallGuide
- R3-5 grant_credits 有 HTTP 入口 → TestGrantCreditsRoute
- R3-6 退款**真的扣回额度** + 审计记录 + 防重复退 → TestRefund
- R3-7 用户列表/ 封禁，且普通用户调管理接口 → 403 → TestUserAdmin
- R3-8 审计日志可查询 → TestAuditQuery
- R3-9 用户 B 看不到用户 A 的草稿（**含图片直链**）→ TestDraftIsolation

隔离红线（沿用 R1 的做法）：core.db / core.auth / core.billing 全部指向
pytest 临时目录，studio 侧指向 YIMU_DB_URL 隔离库，绝不写生产 data/。
"""
# ⭐ 环境变量必须在任何 studio / gateway / web import 之前就绪
import os

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-r3")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")

import re  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from tests.wsb_common import unique_name  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "web" / "templates" / "index.html"


# ---------------------------------------------------------------------------
# 测试客户端（沿用 R1 的隔离方案：双库隔离 + CSRF token）
# ---------------------------------------------------------------------------

class _R3Client:
    """可切换登录态的 web/admin.py TestClient 包装。"""

    def __init__(self, client, db_session, tmp):
        self._c = client
        self.db_session = db_session
        self._tmp = tmp
        self._user_id: str | None = None
        self._csrf = "r3-csrf-token"
        self._c.cookies.set("csrf_token", self._csrf)

    def post(self, url, **kw):
        headers = dict(kw.pop("headers", None) or {})
        headers.setdefault("X-CSRF-Token", self._csrf)
        return self._c.post(url, headers=headers, **kw)

    def get(self, url, **kw):
        return self._c.get(url, **kw)

    def as_user(self, role: str = "user", user_id: str | None = None):
        """以指定角色的 V6 登录态调用（必须在 core.auth 库真实落一行）。

        ⚠️ 返回的是**同一个** client 对象（登录态是 cookie）。
           因此需要「A 下单 → 切管理员核销 → 切回 A 兑换」时，
           必须自己把 user_id 存成局部变量，不要依赖实例属性——
           否则两次 as_user() 之后旧变量其实指向了新用户（假绿）。
        """
        from core import auth

        assert str(auth.DB_PATH) == str(self._tmp / "core_mediaflow.db"), (
            f"core.auth 未指向隔离库（当前 {auth.DB_PATH}），拒绝写生产库"
        )
        if user_id is None:
            user_id = auth.register_user(
                unique_name("r3user"), "".join(["pw", unique_name("x")[:8]])
            )["user"]["id"]
            if role in ("admin", "owner"):
                c = auth._db()
                c.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
                c.commit()
                c.close()
        token = auth.make_token({"user_id": user_id, "username": user_id, "role": role})
        self._c.cookies.set("mf_v6_token", token)
        self._user_id = user_id
        return self

    @property
    def user_id(self) -> str:
        assert self._user_id, "需先调用 as_user()"
        return self._user_id

    def ensure_studio_user(self, user_id: str | None = None):
        """在studio 库补齐 user + membership 行（R3 各接口都走 studio 账本）。

        ⭐ 角色从 core.auth 库同步过来。生产环境 core.auth 与 studio 指向
           **同一个 sqlite 文件**（users 表共用，web/admin.py 把 YIMU_DB_URL
           指向 core.db.DB_PATH），角色天然一致；测试里两库分离，
           不同步就会出现「管理员在 studio 侧仍是普通用户」，
           导致封禁管理员等校验测不出真实行为。
        """
        from core import auth as core_auth
        from studio import billing_adapter
        from studio.auth import ensure_default_tenant
        from studio.db_models import User
        from studio.membership.service import ensure_membership

        db = self.db_session
        uid = user_id or self.user_id
        db.rollback()
        t = ensure_default_tenant(db)
        db.commit()

        # 从 core.auth 读真实角色（与生产同源）
        row = core_auth._db().execute(
            "SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        role = (row[0] if row else "user") or "user"

        exists = db.query(User).filter(User.id == uid).first()
        if exists is None:
            db.add(User(id=uid, tenant_id=t.id, username=f"r3-{uid[:12]}",
                        email="", password_hash="x", salt="x",
                        role=role, is_active=True))
            db.commit()
        elif exists.role != role:
            exists.role = role
            db.commit()
        m = ensure_membership(db, t.id, uid)
        db.commit()
        return t.id, m

    def balance(self, tenant_id: str, user_id: str | None = None) -> int:
        """当前余额（走账本真源）。"""
        from studio.membership.service import credits_left, ensure_membership

        db = self.db_session
        uid = user_id or self.user_id
        m = ensure_membership(db, tenant_id, uid)
        db.commit()
        return credits_left(m)

    def set_balance(self, amount: int, tenant_id: str, user_id: str | None = None) -> None:
        from studio.membership.service import ensure_membership

        db = self.db_session
        uid = user_id or self.user_id
        m = ensure_membership(db, tenant_id, uid)
        m.credits_used = max(0, int(m.credits_total) - amount)
        db.commit()

    def mirror_is_active(self, user_id: str, is_active: bool) -> None:
        """把 is_active 同步到 core.auth 的 users 行。

        ⚠️ 生产环境根本不需要这一步：``web/admin.py:139`` 把 ``YIMU_DB_URL``
           指向 ``core.db.DB_PATH``，**core.auth 与 studio 是同一个 sqlite 文件**，
           ``users.is_active`` 只有一列，封禁 studio 侧即等于封禁 auth 侧。
           测试里两者被刻意隔离（避免写生产库），所以必须手工同步，
           才能验证「封禁后 get_current_user 返回 None → 401」这条真实链路。
        """
        from core import auth as core_auth

        c = core_auth._db()
        c.execute("UPDATE users SET is_active=? WHERE id=?",
                  (1 if is_active else 0, user_id))
        c.commit()
        c.close()


@pytest.fixture()
def r3_client(tmp_path, db_session, monkeypatch):
    """R3 用的 web/admin.py TestClient（core 侧与 studio 侧双库隔离）。"""
    from fastapi.testclient import TestClient

    from core import billing as cb
    from core import db as core_db

    test_db = tmp_path / "core_mediaflow.db"
    monkeypatch.setattr(core_db, "DB_PATH", test_db)
    monkeypatch.setattr(core_db, "DATA", tmp_path)

    from core import auth as core_auth

    monkeypatch.setattr(core_auth, "DB_PATH", test_db)
    monkeypatch.setattr(cb, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cb, "BILLING_FILE", tmp_path / "billing.json")

    from studio.membership import capabilities as caps

    test_db_url = f"sqlite:///{db_session.bind.url.database}"
    monkeypatch.setenv("YIMU_DB_URL", test_db_url)
    monkeypatch.setattr(caps, "_session_factory_cache", {})

    from web import admin as web_admin

    monkeypatch.setattr(web_admin, "load_env",
                        lambda: {"ADMIN_PASSWORD": "r3-test-password"})
    monkeypatch.setattr(web_admin, "JOBS", {})

    with TestClient(web_admin.app) as client:
        assert str(core_auth.DB_PATH) == str(test_db), "core.auth 未隔离"
        yield _R3Client(client, db_session, tmp_path)


# ---------------------------------------------------------------------------
# R3-1 定价
# ---------------------------------------------------------------------------

class TestPricing:
    """R3-1：三档明确定价 + 如实说明 Free 跑不完短剧。"""

    def test_price_page_api_lists_three_tiers(self, r3_client):
        """价格接口返回三档，且售价与定价真源一致。"""
        from studio import pricing

        r3_client.as_user().ensure_studio_user()
        r = r3_client.get("/api/pricing")
        assert r.status_code == 200
        plans = r.json()["plans"]
        assert [p["code"] for p in plans] == ["free", "pro", "studio"]
        pro = next(p for p in plans if p["code"] == "pro")
        assert pro["price_yuan"] == 300.0
        assert pro["credits"] == pricing.TIER_CREDITS["pro"]
        assert r.json()["credit_price_cents"] == pricing.CREDIT_PRICE_CENTS

    def test_free_cannot_run_full_drama_is_honest(self, r3_client):
        """⭐ 诚实性红线：Free 额度 < 一条短剧，必须标 can_run_full_drama=False。"""
        from studio import pricing

        assert pricing.TIER_CREDITS["free"] < pricing.FULL_DRAMA_CREDITS, (
            "前提失效：Free 额度已不低于一条短剧，本用例需同步更新"
        )
        r3_client.as_user().ensure_studio_user()
        plans = r3_client.get("/api/pricing").json()["plans"]
        free = next(p for p in plans if p["code"] == "free")
        assert free["capacity"]["can_run_full_drama"] is False
        assert free["capacity"]["dramas"] == 0
        # Pro/Studio 必须够跑完整短剧
        for code in ("pro", "studio"):
            p = next(x for x in plans if x["code"] == code)
            assert p["capacity"]["can_run_full_drama"] is True

    def test_pricing_page_html_renders(self, r3_client):
        """价格页可访问（登录态即可，无需管理员）。"""
        r3_client.as_user().ensure_studio_user()
        r = r3_client.get("/pricing")
        assert r.status_code == 200
        assert "价格" in r.text

    def test_no_price_hardcoded_in_frontends(self):
        """⭐ 价格单一真源：前端不得硬编码「300 元 / 2000 元」。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        for literal in ("300 元", "2000 元", "300元", "2000元"):
            assert literal not in html, f"前端硬编码了售价 {literal}，应改读 /api/pricing"


# ---------------------------------------------------------------------------
# R3-2 下单 → 卡密 → 核销 → 到账（端到端）
# ---------------------------------------------------------------------------

class TestOrderToCdkeyFlow:
    """R3-2 端到端：未付费用户 → 下单 → 拿卡密 → 核销 → 兑换到账。"""

    def test_end_to_end_purchase_flows(self, r3_client):
        """⭐⭐ 核心验收：完整付费闭环，额度真的到账。"""
        r3_client.as_user()
        buyer_id = r3_client.user_id          # ⚠️ 先存id：登录态是同一个对象
        tid, _m = r3_client.ensure_studio_user(buyer_id)
        before = r3_client.balance(tid, buyer_id)

        # 1) 下单
        r = r3_client.post("/api/billing/order", json={"plan": "pro"})
        assert r.status_code == 200, r.text
        order = r.json()["order"]
        assert order["status"] == "pending"
        assert order["amount_yuan"] == 300.0
        assert order["credits"] == 30000
        cdkey = order["cdkey"]
        assert cdkey, "下单必须返回卡密"

        # 2) 支付指引必须存在且**不含一键支付按钮**（无支付资质不假装）
        assert order["payment_instructions"], "必须给出支付指引"
        joined = " ".join(order["payment_instructions"])
        assert "管理员" in joined and "核销" in joined

        # 3) 下单后额度**还没到账**（卡密未兑换）
        assert r3_client.balance(tid, buyer_id) == before

        # 4) 管理员核销收款
        r3_client.as_user(role="admin").ensure_studio_user()
        r = r3_client.post(f"/api/admin/orders/{order['id']}/confirm", json={})
        assert r.status_code == 200, r.text
        assert r.json()["order"]["status"] == "paid"

        # 5) 切回买家兑换卡密 → 额度到账
        r3_client.as_user(user_id=buyer_id).ensure_studio_user(buyer_id)
        r = r3_client.post("/api/billing/redeem", json={"code": cdkey})
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        after = r3_client.balance(tid, buyer_id)
        assert after == before + 30000, f"兑换后余额应为 {before + 30000}，实际 {after}"

    def test_free_plan_cannot_be_ordered(self, r3_client):
        """Free 不是商品，下单必须被拒。"""
        r3_client.as_user().ensure_studio_user()
        r = r3_client.post("/api/billing/order", json={"plan": "free"})
        assert r.status_code == 400

    def test_unknown_plan_rejected(self, r3_client):
        r3_client.as_user().ensure_studio_user()
        r = r3_client.post("/api/billing/order", json={"plan": "enterprise"})
        assert r.status_code == 400

    def test_cancel_order_revokes_cdkey(self, r3_client):
        """取消订单后卡密作废，兑换必须失败。"""
        r3_client.as_user()
        buyer_id = r3_client.user_id
        tid, _ = r3_client.ensure_studio_user(buyer_id)
        before = r3_client.balance(tid, buyer_id)
        order = r3_client.post(
            "/api/billing/order", json={"plan": "studio"}).json()["order"]

        r3_client.as_user(role="admin").ensure_studio_user()
        r = r3_client.post(f"/api/admin/orders/{order['id']}/cancel", json={"reason": "测试"})
        assert r.status_code == 200
        assert r.json()["order"]["status"] == "cancelled"

        # 卡密已作废 → 兑换失败，额度不变
        r3_client.as_user(user_id=buyer_id).ensure_studio_user(buyer_id)
        r = r3_client.post("/api/billing/redeem", json={"code": order["cdkey"]})
        assert r.status_code != 200 or r.json().get("ok") is not True
        assert r3_client.balance(tid, buyer_id) == before

    def test_user_only_sees_own_orders(self, r3_client):
        """A 不能看到 B 的订单。"""
        r3_client.as_user().ensure_studio_user()
        order_a = r3_client.post("/api/billing/order", json={"plan": "pro"}).json()["order"]

        r3_client.as_user().ensure_studio_user()   # 换成 B
        items = r3_client.get("/api/billing/orders").json()["items"]
        assert all(o["id"] != order_a["id"] for o in items)

    def test_order_requires_login(self, r3_client):
        """未登录下单 → 401。"""
        r3_client._c.cookies.clear()
        r = r3_client.post("/api/billing/order", json={"plan": "pro"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# R3-3 升级弹窗接真实购买
# ---------------------------------------------------------------------------

class TestFrontendUpgradeModal:
    """R3-3：升级弹窗不再是「只有我知道了」的死胡同。"""

    def test_upgrade_modal_has_purchase_entry(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        block = re.search(
            r"function showUpgradeModal\(msg\)\s*\{.*?\n\}", html, re.S)
        assert block, "未找到 showUpgradeModal"
        body = block.group(0)
        # 必须有真实购买出口，而不是只有「我知道了」
        assert "goToPricing" in body, "升级弹窗必须接上价格页/购买入口"
        assert "我知道了" not in body, "「我知道了」式死胡同已修复，不应保留"

    def test_go_to_pricing_function_exists(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "function goToPricing()" in html
        assert "/pricing" in html

    def test_upgrade_modal_shows_real_price_from_api(self):
        """弹窗价格必须来自接口，不得前端硬编码。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "loadUpgradePrice" in html
        assert "/api/pricing" in html

    def test_billing_panel_button_buys(self):
        """会员面板的入口也应导向真实购买。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "查看价格并购买" in html


# ---------------------------------------------------------------------------
# R3-4 额度墙引导
# ---------------------------------------------------------------------------

class TestQuotaWallGuide:
    """R3-4：额度不足时给出缺口 + 套餐，且不与 R5-3 召回邮件冲突。"""

    def test_upgrade_endpoint_returns_shortfall_and_options(self, r3_client):
        r3_client.as_user()
        tid, _ = r3_client.ensure_studio_user()
        r3_client.set_balance(500, tid)

        r = r3_client.get("/api/billing/upgrade?need=12000")
        assert r.status_code == 200
        d = r.json()
        assert d["shortfall"] == 11500
        codes = [o["code"] for o in d["options"]]
        assert codes == ["pro", "studio"]
        pro = next(o for o in d["options"] if o["code"] == "pro")
        assert pro["covers_action"] is True
        assert pro["covers_full_drama"] is True

    def test_upgrade_endpoint_requires_login(self, r3_client):
        r3_client._c.cookies.clear()
        r = r3_client.get("/api/billing/upgrade?need=100")
        assert r.status_code == 401

    def test_402_message_contains_gap_and_price(self, r3_client):
        """⭐ 402 文案必须含「还差多少」与真实套餐价格。"""
        r3_client.as_user()
        tid, _ = r3_client.ensure_studio_user()
        r3_client.set_balance(0, tid)

        r = r3_client.post("/api/drafts/create",
                            json={"title": "额度耗尽", "body_md": "正文"})
        assert r.status_code == 402
        detail = r.json()["detail"]
        assert "还差" in detail, f"应说明缺口：{detail}"
        assert "300 元" in detail or "300.0" in detail, f"应给出真实价格：{detail}"
        assert "/pricing" in detail, f"应给出购买入口：{detail}"

    def test_402_guide_does_not_conflict_with_r5_recall(self):
        """⭐ R3-4（页面引导）与 R5-3（召回邮件）是两条独立通道，不得互相触发。

        判定方式：``require_credits`` 内只允许调``_on_quota_blocked``（R5-3
        的邮件召回钩子），**不得直接引用 user_notify**——否则两套引导会叠加打扰。
        """
        src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
        # require_credits 函数体：从定义处切到下一个顶层 def
        seg = src.split("def require_credits(")[1].split("\ndef _is_admin_user")[0]
        # 只看代码行，剔除注释（注释里提到 user_notify 是设计说明，不是调用）
        code = "\n".join(l for l in seg.split("\n") if not l.strip().startswith("#"))
        assert "_on_quota_blocked" in code, "额度墙仍应触发 R5-3 召回钩子"
        assert "user_notify" not in code, "402 文案组装不应直接触发邮件召回"
        assert "deliver" not in code, "402 文案组装不应直接投递通知"
        # 邮件召回逻辑仍在钩子里（R5-3 未被破坏）
        hook = src.split("def _on_quota_blocked")[1].split("\ndef ")[0]
        assert "user_notify" in hook and "quota_recall" in hook


# ---------------------------------------------------------------------------
# R3-5 额度发放 HTTP 路由
# ---------------------------------------------------------------------------

class TestGrantCreditsRoute:
    """R3-5：grant_credits 终于有 HTTP 入口。"""

    def test_admin_can_grant(self, r3_client):
        r3_client.as_user()
        tid, _ = r3_client.ensure_studio_user()
        before = r3_client.balance(tid)

        admin = r3_client.as_user(role="admin")
        admin.ensure_studio_user()
        r = admin.post("/api/admin/grant_credits",
                       json={"user_id": r3_client.user_id, "amount": 5000,
                             "reason": "补偿"})
        assert r.status_code == 200, r.text
        assert r.json()["granted"] == 5000
        assert r3_client.balance(tid) == before + 5000

    def test_normal_user_forbidden(self, r3_client):
        """⭐ 普通用户调发放接口 → 403。"""
        r3_client.as_user()
        r3_client.ensure_studio_user()
        r = r3_client.post("/api/admin/grant_credits",
                           json={"user_id": "u-x", "amount": 1000})
        assert r.status_code == 403

    def test_non_positive_amount_rejected(self, r3_client):
        admin = r3_client.as_user(role="admin")
        admin.ensure_studio_user()
        r = admin.post("/api/admin/grant_credits",
                       json={"user_id": "u-x", "amount": 0})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# R3-6 退款
# ---------------------------------------------------------------------------

class TestRefund:
    """R3-6：退款必须真的扣回额度 + 留审计 + 防重复退。"""

    def _paid_order(self, r3_client, plan="pro", credits=30000):
        """下单 → 核销 → 兑换。

        Returns: (order, 买家 id, 兑换前余额, 兑换后余额, 租户 id)
        ⚠️ 登录态是同一个 client 对象，因此全程用显式 user_id 定位买家，
           切管理员后不要依赖 r3_client.user_id。
        """
        r3_client.as_user()
        buyer_id = r3_client.user_id
        tid, _ = r3_client.ensure_studio_user(buyer_id)
        before = r3_client.balance(tid, buyer_id)
        order = r3_client.post("/api/billing/order",
                               json={"plan": plan}).json()["order"]
        # 管理员核销收款
        r3_client.as_user(role="admin").ensure_studio_user()
        r = r3_client.post(f"/api/admin/orders/{order['id']}/confirm", json={})
        assert r.status_code == 200, r.text
        # 切回买家兑换
        r3_client.as_user(user_id=buyer_id).ensure_studio_user(buyer_id)
        r = r3_client.post("/api/billing/redeem", json={"code": order["cdkey"]})
        assert r.json().get("ok") is True, r.text
        after_redeem = r3_client.balance(tid, buyer_id)
        return order, buyer_id, before, after_redeem, tid

    def test_refund_deducts_credits_and_writes_audit(self, r3_client):
        """⭐⭐ 核心验收：额度真的被扣回，且有审计记录。"""
        order, buyer_id, before, after_redeem, tid = self._paid_order(r3_client)
        assert after_redeem == before + 30000, (
            f"前置失败：兑换后应到账 30000，实际 {after_redeem - before}")

        r3_client.as_user(role="admin").ensure_studio_user()
        r = r3_client.post(f"/api/admin/orders/{order['id']}/refund",
                           json={"reason": "用户申请退款"})
        assert r.status_code == 200, r.text
        data = r.json()["order"]
        assert data["status"] == "refunded"
        assert data["deducted"] == 30000
        assert data["shortfall"] == 0

        # 额度真的扣回了
        back = r3_client.balance(tid, buyer_id)
        assert back == before, f"退款后余额应回到 {before}，实际 {back}"

        # 审计日志里有记录
        from studio.db_models import AuditLog

        logs = (r3_client.db_session.query(AuditLog)
                .filter(AuditLog.action == "order.refund").all())
        assert len(logs) == 1
        detail = logs[0].detail or {}
        assert detail.get("deducted") == 30000
        assert detail.get("reason") == "用户申请退款"

    def test_refund_rejected_twice(self, r3_client):
        """防重复退款：第二次必须被拒。"""
        order, buyer_id, before, _after, tid = self._paid_order(r3_client)
        r3_client.as_user(role="admin").ensure_studio_user()
        assert r3_client.post(f"/api/admin/orders/{order['id']}/refund",
                              json={"reason": "第一次"}).status_code == 200
        r = r3_client.post(f"/api/admin/orders/{order['id']}/refund",
                           json={"reason": "第二次"})
        assert r.status_code == 409, "重复退款必须被拒"
        assert r3_client.balance(tid, buyer_id) == before

    def test_refund_unpaid_order_rejected(self, r3_client):
        """未支付订单不能退款（应先取消）。"""
        r3_client.as_user()
        r3_client.ensure_studio_user()
        order = r3_client.post("/api/billing/order",
                               json={"plan": "pro"}).json()["order"]
        r3_client.as_user(role="admin").ensure_studio_user()
        r = r3_client.post(f"/api/admin/orders/{order['id']}/refund", json={})
        assert r.status_code == 409

    def test_refund_partial_when_user_spent_credits(self, r3_client):
        """⭐ 用户已花掉部分额度 → 扣到0为止，shortfall 如实回报，不扣成负数。"""
        order, buyer_id, _before, _after, tid = self._paid_order(r3_client)
        # 模拟用户已消耗掉大部分额度，只剩 1000 点
        r3_client.set_balance(1000, tid, buyer_id)

        r3_client.as_user(role="admin").ensure_studio_user()
        r = r3_client.post(f"/api/admin/orders/{order['id']}/refund", json={})
        data = r.json()["order"]
        assert data["deducted"] == 1000, "只能扣回剩余的 1000 点"
        assert data["shortfall"] == 29000, "已消费部分应如实报告为差额"
        assert r3_client.balance(tid, buyer_id) == 0, "余额不得为负"

    def test_normal_user_cannot_refund(self, r3_client):
        """普通用户调退款 → 403。"""
        order, buyer_id, _b, _a, _t = self._paid_order(r3_client)
        r = r3_client.post(f"/api/admin/orders/{order['id']}/refund", json={})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# R3-7 用户列表与封禁
# ---------------------------------------------------------------------------

class TestUserAdmin:
    """R3-7：用户列表 + 封禁/解封 + 审计 + 封禁后无法调 API。"""

    def test_admin_lists_users_with_tier_and_balance(self, r3_client):
        r3_client.as_user().ensure_studio_user()
        admin = r3_client.as_user(role="admin")
        tid, _ = admin.ensure_studio_user()
        r = admin.get("/api/admin/users?limit=50")
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "应至少列出管理员自己"
        assert all("tier" in i and "credits_left" in i for i in items)

    def test_keyword_search(self, r3_client):
        r3_client.as_user().ensure_studio_user()
        admin = r3_client.as_user(role="admin")
        admin.ensure_studio_user()
        kw = unique_name("findme")[:8]
        r = admin.get(f"/api/admin/users?keyword={kw}")
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_normal_user_cannot_list_users(self, r3_client):
        r3_client.as_user().ensure_studio_user()
        assert r3_client.get("/api/admin/users").status_code == 403

    def test_ban_blocks_api_calls_and_writes_audit(self, r3_client):
        """⭐⭐ 核心验收：封禁后该用户无法调用任何 API，且有审计日志。"""
        r3_client.as_user()
        victim_id = r3_client.user_id        # ⚠️ 先存id：登录态是同一个对象
        r3_client.ensure_studio_user(victim_id)

        r3_client.as_user(role="admin").ensure_studio_user()
        r = r3_client.post(f"/api/admin/users/{victim_id}/ban",
                           json={"banned": True, "reason": "违规"})
        assert r.status_code == 200, r.text
        assert r.json()["banned"] is True

        # 生产环境 core.auth 与 studio 同库（web/admin.py:139），
        # 测试隔离了两库，故同步 is_active 以走通真实鉴权链路
        r3_client.mirror_is_active(victim_id, False)

        # 被封禁用户再调 API → 401（令牌因 is_active=0 失效）
        r3_client.as_user(user_id=victim_id)
        assert r3_client.get("/api/billing/status").status_code == 401
        assert r3_client.post("/api/drafts/create",
                              json={"title": "x", "body_md": "y"}).status_code == 401

        # 审计日志必须留痕
        from studio.db_models import AuditLog

        logs = (r3_client.db_session.query(AuditLog)
                .filter(AuditLog.action == "user.ban").all())
        assert len(logs) == 1
        assert (logs[0].detail or {}).get("reason") == "违规"

    def test_unban_restores_access(self, r3_client):
        r3_client.as_user()
        victim_id = r3_client.user_id
        r3_client.ensure_studio_user(victim_id)
        r3_client.as_user(role="admin").ensure_studio_user()

        r3_client.post(f"/api/admin/users/{victim_id}/ban", json={"banned": True})
        r3_client.mirror_is_active(victim_id, False)
        r3_client.as_user(user_id=victim_id)
        assert r3_client.get("/api/billing/status").status_code == 401

        r3_client.as_user(role="admin").ensure_studio_user()
        r = r3_client.post(f"/api/admin/users/{victim_id}/ban", json={"banned": False})
        assert r.status_code == 200
        assert r.json()["is_active"] is True
        r3_client.mirror_is_active(victim_id, True)
        r3_client.as_user(user_id=victim_id)
        assert r3_client.get("/api/billing/status").status_code == 200

    def test_cannot_ban_admin(self, r3_client):
        """不能封禁管理员，避免把最后一个管理入口锁死。"""
        r3_client.as_user(role="admin")
        admin_id = r3_client.user_id
        r3_client.ensure_studio_user(admin_id)
        r = r3_client.post(f"/api/admin/users/{admin_id}/ban", json={"banned": True})
        assert r.status_code == 403

    def test_normal_user_cannot_ban(self, r3_client):
        r3_client.as_user()
        target_id = r3_client.user_id
        r3_client.ensure_studio_user(target_id)
        r3_client.as_user().ensure_studio_user()
        r = r3_client.post(f"/api/admin/users/{target_id}/ban", json={"banned": True})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# R3-8 审计日志
# ---------------------------------------------------------------------------

class TestAuditQuery:
    """R3-8：审计日志可查询（此前只有写入、没有查询）。"""

    def test_admin_can_query_audit_logs(self, r3_client):
        r3_client.as_user()
        tid, _ = r3_client.ensure_studio_user()
        admin = r3_client.as_user(role="admin")
        admin.ensure_studio_user()
        # 造一条审计：发放额度
        admin.post("/api/admin/grant_credits",
                   json={"user_id": r3_client.user_id, "amount": 100,
                         "reason": "审计测试"})

        r = admin.get("/api/admin/audit_logs?limit=50")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 1
        actions = [i["action"] for i in d["items"]]
        assert "membership.grant" in actions

    def test_filter_by_action(self, r3_client):
        admin = r3_client.as_user(role="admin")
        admin.ensure_studio_user()
        admin.get("/api/admin/audit_logs?action=membership.grant")
        d = admin.get("/api/admin/audit_logs?action=membership.grant").json()
        assert all(i["action"] == "membership.grant" for i in d["items"])

    def test_audit_actions_endpoint(self, r3_client):
        admin = r3_client.as_user(role="admin")
        admin.ensure_studio_user()
        r = admin.get("/api/admin/audit_actions")
        assert r.status_code == 200
        assert isinstance(r.json()["actions"], list)

    def test_normal_user_cannot_query_audit(self, r3_client):
        r3_client.as_user().ensure_studio_user()
        assert r3_client.get("/api/admin/audit_logs").status_code == 403

    def test_audit_page_requires_admin(self, r3_client):
        r3_client.as_user().ensure_studio_user()
        assert r3_client.get("/admin/audit").status_code == 403
        admin = r3_client.as_user(role="admin")
        admin.ensure_studio_user()
        assert admin.get("/admin/audit").status_code == 200


# ---------------------------------------------------------------------------
# R3-9 草稿归属隔离（安全项）
# ---------------------------------------------------------------------------

class TestDraftIsolation:
    """R3-9：用户 B 看不到用户 A 的草稿，含图片/卡片/音频直链。"""

    @pytest.fixture()
    def two_users_drafts(self, r3_client, monkeypatch, tmp_path):
        """造 A / B 各一篇草稿，且产物文件真实存在。

        ⚠️ 草稿的 user_id 必须用**显式存下来的** id，不能用 r3_client.user_id
           ——登录态是同一个对象，第二次 as_user() 会把它指向 B。
        """
        from core import db as core_db

        # ⚠️ 必须在 r3_client 之后再指定（r3_client 也monkeypatch 了这两个），
        #    且要用独立子目录，避免和 r3_client 的隔离库串味。
        iso = tmp_path / "draft_iso"
        iso.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(core_db, "DATA", iso)
        monkeypatch.setattr(core_db, "DB_PATH", iso / "iso.db")

        r3_client.as_user()
        uid_a = r3_client.user_id
        r3_client.ensure_studio_user(uid_a)
        draft_a = core_db.add_draft("t1", "A的机密稿件", "机密正文A", ["wechat_mp"],
                                    user_id=uid_a)
        ddir_a = core_db.draft_dir(draft_a["id"])
        (ddir_a / "img").mkdir(parents=True, exist_ok=True)
        (ddir_a / "img" / "secret.png").write_bytes(b"PNG-A-SECRET")
        (ddir_a / "card-secret.png").write_bytes(b"PNG-A-CARD")
        (ddir_a / "drama" / "images").mkdir(parents=True, exist_ok=True)
        (ddir_a / "drama" / "images" / "s.png").write_bytes(b"PNG-A-DRAMA")
        (ddir_a / "preview-wechat_mp.html").write_text("<html>A机密</html>",
                                                      encoding="utf-8")

        r3_client.as_user()
        uid_b = r3_client.user_id
        r3_client.ensure_studio_user(uid_b)
        draft_b = core_db.add_draft("t1", "B的稿件", "正文B", ["wechat_mp"],
                                    user_id=uid_b)
        return {"a": uid_a, "b": uid_b,
                "did_a": draft_a["id"], "did_b": draft_b["id"]}

    def test_backfill_makes_orphan_drafts_admin_only(self, r3_client, monkeypatch,
                                                     tmp_path):
        """⭐ 历史草稿（user_id 空）回填后，不再对所有登录用户公开。"""
        from core import db as core_db

        monkeypatch.setattr(core_db, "DATA", tmp_path)
        monkeypatch.setattr(core_db, "DB_PATH", tmp_path / "orphan.db")
        orphan = core_db.add_draft("t1", "无归属历史稿", "正文", ["wechat_mp"])
        assert orphan["user_id"] == ""
        # 建连即回填（core.db.conn 内置幂等回填）
        assert core_db.get_draft(orphan["id"])["user_id"] == "u-admin"

        # 普通用户不得访问
        user = r3_client.as_user()
        user.ensure_studio_user()
        assert not core_db.is_draft_owner(
            core_db.get_draft(orphan["id"]), user.user_id, is_admin=False)
        # 管理员可以
        assert core_db.is_draft_owner(
            core_db.get_draft(orphan["id"]), "u-admin", is_admin=True)

    def test_user_b_cannot_read_user_a_draft_api(self, r3_client, two_users_drafts):
        """B 读 A 的草稿接口 → 404。"""
        r3_client.as_user(user_id=two_users_drafts["b"]).ensure_studio_user()
        r = r3_client.get(f"/api/drafts/{two_users_drafts['did_a']}")
        assert r.status_code == 404

    def test_user_b_cannot_fetch_a_img_direct_link(self, r3_client, two_users_drafts):
        """⭐⭐ 核心验收：图片直链同样受归属保护。"""
        r3_client.as_user(user_id=two_users_drafts["b"]).ensure_studio_user()
        did = two_users_drafts["did_a"]
        assert r3_client.get(f"/img/{did}/secret.png").status_code == 404
        assert r3_client.get(f"/card/{did}/card-secret.png").status_code == 404
        assert r3_client.get(
            f"/img/drama/{did}/images/s.png").status_code == 404

    def test_owner_can_access_own_draft(self, r3_client, two_users_drafts):
        """A 访问自己的草稿与图片必须正常（不能把功能打死）。"""
        r3_client.as_user(user_id=two_users_drafts["a"]).ensure_studio_user()
        did = two_users_drafts["did_a"]
        assert r3_client.get(f"/img/{did}/secret.png").status_code == 200
        assert r3_client.get(f"/card/{did}/card-secret.png").status_code == 200
        assert r3_client.get(f"/api/drafts/{did}").status_code == 200

    def test_list_drafts_only_returns_own(self, r3_client, two_users_drafts):
        """草稿列表按归属过滤：A 只看到自己。

        ⚠️ 不要再monkeypatch core.db.DATA/DB_PATH——fixture 已指向独立子目录，
           这里重复设置会把草稿库切到别处，读到空列表（假失败）。
        """
        from core import db as core_db

        a_list = core_db.list_drafts(two_users_drafts["a"])
        b_list = core_db.list_drafts(two_users_drafts["b"])
        assert [d["id"] for d in a_list] == [two_users_drafts["did_a"]]
        assert [d["id"] for d in b_list] == [two_users_drafts["did_b"]]
        # 不传 user_id 且非管理员 → fail-closed 返回空（绝不退化成「全部可见」）
        assert core_db.list_drafts() == []
        # 管理员看全部
        assert len(core_db.list_drafts(is_admin=True)) == 2

    def test_status_only_returns_own_drafts(self, r3_client, two_users_drafts):
        """/api/status 只返回当前用户的草稿。"""
        r3_client.as_user(user_id=two_users_drafts["b"]).ensure_studio_user(
            two_users_drafts["b"])
        d = r3_client.get("/api/status").json()
        assert [x["id"] for x in d["drafts"]] == [two_users_drafts["did_b"]]

    def test_admin_can_read_any_draft(self, r3_client, two_users_drafts):
        """管理员仍可跨用户访问（排障与合规复核需要）。"""
        r3_client.as_user(role="admin").ensure_studio_user()
        assert r3_client.get(
            f"/img/{two_users_drafts['did_a']}/secret.png").status_code == 200

    def test_draft_route_class_covers_all_did_routes(self):
        """⭐ 静态护栏：所有带 {did} 的路由都必须走归属校验的路由类。"""
        from web import admin as web_admin

        n_did, n_guarded = 0, 0
        for route in web_admin.app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", None) or set()
            if "{did}" not in path or not methods:
                continue
            n_did += 1
            is_exempt = path.startswith(("/s/", "/preview/"))
            if isinstance(route, web_admin.DraftOwnerRoute) or is_exempt:
                n_guarded += 1
        assert n_did > 50, f"带 did 的路由数量异常少（{n_did}），护栏可能失效"
        assert n_guarded == n_did, (
            f"有 {n_did - n_guarded} 条带 did 的路由未走归属校验："
            + str([r.path for r in web_admin.app.routes
                   if "{did}" in getattr(r, "path", "")
                   and not isinstance(r, web_admin.DraftOwnerRoute)
                   and not getattr(r, "path", "").startswith(("/s/", "/preview/"))])
        )


# ---------------------------------------------------------------------------
# R3 交叉护栏
# ---------------------------------------------------------------------------

def test_all_new_admin_routes_use_guard_admin():
    """⭐ 所有新增资金/权限接口都必须过 guard_admin，不能只护一个。"""
    from web import admin as web_admin

    must_guard = [
        "/api/admin/grant_credits",
        "/api/admin/orders/{order_id}/refund",
        "/api/admin/orders/{order_id}/confirm",
        "/api/admin/orders/{order_id}/cancel",
        "/api/admin/users/{user_id}/ban",
        "/api/admin/users",
        "/api/admin/audit_logs",
        "/api/admin/audit_actions",
    ]
    by_path = {}
    for route in web_admin.app.routes:
        p = getattr(route, "path", "")
        if p in must_guard:
            by_path[p] = getattr(route, "endpoint", None)
    for p in must_guard:
        assert p in by_path, f"未找到路由 {p}"
        src = re.search(
            r"def\s+\w+\s*\([^)]*\):\s*((?:.|\n)*?)(?=\n@app|\Z)",
            Path(by_path[p].__code__.co_filename).read_text(encoding="utf-8"), re.S)
        body = by_path[p].__code__.co_names
        assert "guard_admin" in body, f"{p} 未调用 guard_admin，资金接口必须管理员鉴权"


def test_refund_and_ban_are_audited():
    """⭐ 退款与封禁必须落审计（静态 + 行为双重护栏）。"""
    from studio.membership import commerce

    for fn, action in ((commerce.refund_order, "order.refund"),
                       (commerce.set_user_banned, "user.ban")):
        assert action in fn.__code__.co_names or any(
            action in str(c) for c in fn.__code__.co_consts
        ), f"{fn.__name__} 未写审计动作 {action}"


class TestSharedUsersSchema:
    """R3-9 顺带修复：core.db 与 studio 共用一张 users 表时的缺列自愈。"""

    def test_auth_survives_studio_first_table_creation(self, tmp_path, monkeypatch):
        """⭐⭐ 回归：新装机器若 studio 先建表，鉴权曾 500（no such column: plan）。

        背景：两套 schema 共用 ``users`` 表但列集不同，SQLite 的
        ``CREATE TABLE IF NOT EXISTS`` 不给已存在的表补列。
        这里模拟「studio 先 init_db」的最坏启动顺序。
        """
        import sqlite3

        from core import auth as core_auth
        from core import db as core_db

        dbp = tmp_path / "fresh_install.db"
        monkeypatch.setattr(core_db, "DB_PATH", dbp)
        monkeypatch.setattr(core_db, "DATA", tmp_path)
        monkeypatch.setattr(core_auth, "DB_PATH", dbp)

        # 1) studio 侧先建表（只有 studio 的列）
        from sqlalchemy.orm import sessionmaker

        from studio.db import get_engine, init_db

        eng = get_engine(f"sqlite:///{dbp}")
        init_db(eng)
        s = sessionmaker(bind=eng)()
        from studio.auth import ensure_default_tenant
        from studio.db_models import User as SUser

        t = ensure_default_tenant(s)
        s.commit()
        s.add(SUser(id="u-fresh", tenant_id=t.id, username="u-fresh", email="",
                    password_hash="x", salt="x", role="user", is_active=True))
        s.commit()
        s.close()

        # 2) ⭐ V9.3.2 P0-2：ORM 真源已补齐 plan/quota_* 列（双层数据访问合并），
        #    「studio 先建表 → 缺列 → 鉴权 500」的事故前提不复存在；
        #    此断言保留是为了锁定真源列完整性：studio 侧建表即含全部鉴权依赖列。
        cols = {r[1] for r in sqlite3.connect(dbp).execute("PRAGMA table_info(users)")}
        assert {"plan", "quota_used", "quota_max", "last_login"} <= cols, (
            f"studio ORM 真源缺少 core.auth 依赖列（{sorted(cols)}）——双层数据访问未合并"
        )

        # 3) 但鉴权仍必须成功（core.auth._db 会自愈补列）
        u = core_auth.get_user_by_id("u-fresh")
        assert u is not None, "鉴权查询返回空"
        assert u["username"] == "u-fresh"
        assert u["plan"] == "free"
        assert u["quota_max"] == 3000

    def test_ensure_users_columns_is_idempotent(self, tmp_path):
        """重复调用不得报错（幂等）。"""
        import sqlite3

        from core.db import ensure_users_columns

        dbp = tmp_path / "idem.db"
        c = sqlite3.connect(dbp)
        c.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT)")
        c.commit()
        ensure_users_columns(c)
        ensure_users_columns(c)   # 第二次必须仍不报错
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
        assert {"plan", "quota_used", "quota_max", "last_login"} <= cols
        c.close()