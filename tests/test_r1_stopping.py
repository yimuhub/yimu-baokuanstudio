# SPDX-License-Identifier: BUSL-1.1
"""R1 止血批次回归测试：卡密后门、扣费拦截、管理员鉴权、fail-closed、XSS、死函数。

覆盖 R1-1 ~ R1-7 的可判定验收标准：
- R1-1 万能码 / 伪造前缀码一律兑换失败且余额不变；
- R1-2 /api/billing/redeem 走 ledger-backed 适配器（原子核销防重放）；
- R1-3 普通用户调 gen_keys → 403，管理员 → 200；
- R1-4 额度为 0 时 /api/drafts/create → 402 + 引导文案 + 不产生草稿；
- R1-5 未配置 ADMIN_PASSWORD 时 loopback 不免密、固定 token 不可伪造；
- R1-6 前端 toast 用 textContent，LLM 输出经escapeHtml；
- R1-7 三个命令面板函数已接真实实现，异常不再静默吞掉。
"""
# ⭐ 环境变量必须在任何 studio / gateway / web import 之前就绪
import os

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-r1")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")
os.environ.setdefault("YIMU_ADMIN_KEY", "test-admin-key-r1-2026")

import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from tests.wsb_common import make_tenant_stack, unique_name  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "web" / "templates" / "index.html"
MODERN_JS = REPO_ROOT / "web" / "static" / "js" / "modern_studio.js"


# ---------------------------------------------------------------------------
# web/admin.py 的 TestClient（core.db 与 core.billing 全部指向临时目录）
# ---------------------------------------------------------------------------

class _AdminClient:
    """web/admin.py 端点的测试客户端包装。

    ⭐ 隔离红线：core.db.DB_PATH 与 core.billing 的 JSON 账本都重定向到
       pytest 临时目录，绝不写生产data/ 目录。
    """

    def __init__(self, client, db_session, tmp):
        self._c = client
        self.db_session = db_session
        self._tmp = tmp
        # ⭐ 这些用例模拟**浏览器 Cookie 登录态**（mf_v6_token），必须像真实前端
        #   一样带上 Double Submit Cookie 的 CSRF token，否则请求会被
        #   core.security_middleware.CSRFMiddleware 挡成 403，
        #   掩盖用例真正要验的行为（角色鉴权 403 / 额度拦截 402）——那会造成假绿。
        self._csrf = "r1-csrf-token"
        self._c.cookies.set("csrf_token", self._csrf)

    def post(self, url, **kw):
        headers = dict(kw.pop("headers", None) or {})
        headers.setdefault("X-CSRF-Token", self._csrf)
        return self._c.post(url, headers=headers, **kw)

    def delete(self, url, **kw):
        headers = dict(kw.pop("headers", None) or {})
        headers.setdefault("X-CSRF-Token", self._csrf)
        return self._c.delete(url, headers=headers, **kw)

    def get(self, url, **kw):
        return self._c.get(url, **kw)

    def set_balance(self, amount: int) -> None:
        """设置 core.billing 账本余额（测试用）。"""
        from core import billing

        data = billing._load_data()
        data["balance"] = amount
        billing._save_data(data)

    def as_user(self, role: str = "user", user_id: str | None = None):
        """以指定角色的 V6 登录态调用。

        ⭐ 两个隔离红线：
           1) 必须在 core.auth 的 users 表里真实落一行——get_current_user 会
              用 token 里的 user_id 查库核对 is_active，查不到直接 401，
              只签 token 不建用户是测不出 403 的；
           2) core.auth._db() 用的是**模块导入时绑定的** DB_PATH，
              只 monkeypatch core.db.DB_PATH 拦不住它，必须改core.auth.DB_PATH，
              否则测试用户会写进真实 data/mediaflow.db。
        """
        from core import auth

        assert str(auth.DB_PATH) == str(self._tmp / "core_mediaflow.db"), (
            f"core.auth 未指向隔离库（当前 {auth.DB_PATH}），拒绝写生产库"
        )
        if user_id is None:
            user_id = auth.register_user(
                unique_name("r1user"), "".join(["pw", unique_name("x")[:8]])
            )["user"]["id"]
            if role in ("admin", "owner"):
                c = auth._db()
                c.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
                c.commit()
                c.close()
        token = auth.make_token({"user_id": user_id, "username": user_id, "role": role})
        self._c.cookies.set("mf_v6_token", token)
        return self


@pytest.fixture()
def client_for_admin_tests(tmp_path, db_session, monkeypatch):
    """可切换登录态的 web/admin.py TestClient。"""
    from fastapi.testclient import TestClient

    from core import billing as cb
    from core import db as core_db

    # 1) core.db 与 core.auth 都指向临时 sqlite
    #    ⭐ core.auth 在import 时就把 DB_PATH 绑成模块属性了，
    #      只改 core.db.DB_PATH 拦不住它，必须一并改，否则会写生产库。
    test_db = tmp_path / "core_mediaflow.db"
    monkeypatch.setattr(core_db, "DB_PATH", test_db)
    monkeypatch.setattr(core_db, "DATA", tmp_path)

    from core import auth as core_auth

    monkeypatch.setattr(core_auth, "DB_PATH", test_db)

    # 2) core.billing JSON 账本指向临时目录
    monkeypatch.setattr(cb, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cb, "BILLING_FILE", tmp_path / "billing.json")

    # 3) studio 侧账本指向隔离测试库（billing_adapter / memberships 用）
    from studio.membership import capabilities as caps

    test_db_url = f"sqlite:///{db_session.bind.url.database}"
    monkeypatch.setenv("YIMU_DB_URL", test_db_url)
    monkeypatch.setattr(caps, "_session_factory_cache", {})

    from web import admin as web_admin

    monkeypatch.setattr(web_admin, "load_env",
                        lambda: {"ADMIN_PASSWORD": "r1-test-password"})
    monkeypatch.setattr(web_admin, "JOBS", {})

    with TestClient(web_admin.app) as client:
        # ⭐ 断言隔离到位：core.auth 绝不能指向生产库
        assert str(core_auth.DB_PATH) == str(test_db), (
            f"core.auth.DB_PATH 未隔离（{core_auth.DB_PATH}），拒绝运行"
        )
        yield _AdminClient(client, db_session, tmp_path)


# ---------------------------------------------------------------------------
# R1-1 卡密万能后门已下线
# ---------------------------------------------------------------------------

@pytest.fixture()
def billing_json(tmp_path, monkeypatch):
    """把 core.billing 的 JSON 账本指到临时目录，绝不碰真实 data/billing.json。"""
    from core import billing

    f = tmp_path / "billing.json"
    monkeypatch.setattr(billing, "DATA_DIR", tmp_path)
    monkeypatch.setattr(billing, "BILLING_FILE", f)
    return billing


def _balance(billing) -> int:
    return billing.get_billing_status()["balance"]


@pytest.mark.parametrize(
    "code",
    [
        "VIP999", "MEDIAFLOW888", "PRO2026",        # 硬编码通用体验码
        "TOKEN-ARBITRARY", "TOKEN-0000",             # 伪造前缀（TOKEN-）
        "PRO-ANYTHING", "PRO-1234",                  # 伪造前缀（PRO-）
        "MCN-ANYTHING", "MCN-9999",                  # 伪造前缀（MCN-）
        "vip999",                                    # 小写也必须无效
    ],
)
def test_r1_1_backdoor_codes_rejected(billing_json, code):
    """R1-1：万能码与伪造前缀码必须兑换失败，且余额不变。"""
    before = _balance(billing_json)
    res = billing_json.redeem_cdkey(code)
    assert res["ok"] is False, f"{code} 应被拒绝：{res}"
    assert "无效" in res["msg"], f"应保留无效卡密提示，实际：{res['msg']}"
    assert _balance(billing_json) == before, f"{code} 不得改变余额"


def test_r1_1_generated_key_still_works_and_no_replay(billing_json):
    """R1-1 回归：正式生成的卡密仍可兑换，且 used 防重放依然生效。"""
    keys = billing_json.generate_cdkeys("tokens", amount=12345, count=1)
    assert len(keys) == 1

    before = _balance(billing_json)
    ok = billing_json.redeem_cdkey(keys[0])
    assert ok["ok"] is True, f"正式卡密应可兑换：{ok}"
    assert _balance(billing_json) == before + 12345

    again = billing_json.redeem_cdkey(keys[0])
    assert again["ok"] is False, "同一张卡密不得二次兑换"
    assert _balance(billing_json) == before + 12345, "重复兑换不得再加分"


def test_r1_1_pro_and_studio_keys_upgrade_tier(billing_json):
    """R1-1 回归：正式生成的 Pro / Studio 卡密仍能升级档位。"""
    for key_type, tier in (("pro", "pro"), ("studio", "studio")):
        code = billing_json.generate_cdkeys(key_type, count=1)[0]
        res = billing_json.redeem_cdkey(code)
        assert res["ok"] is True, f"{key_type} 卡密应可兑换：{res}"
        assert billing_json.get_billing_status()["tier"] == tier


def test_r1_1_no_backdoor_literals_in_source():
    """R1-1 静态护栏：redeem_cdkey 的可执行代码里不得再出现万能码与前缀放行。

    用 AST 只扫「字符串常量与比较/调用」，避免误伤 docstring 里
    对历史后门的说明文字（那是刻意留档，不是代码）。
    """
    import ast

    src = (REPO_ROOT / "core" / "billing.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "redeem_cdkey")

    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for token in ("VIP999", "MEDIAFLOW888", "PRO2026"):
        assert token not in literals, f"redeem_cdkey 仍含万能码字面量 {token}"

    called = {getattr(n.func, "attr", None) for n in ast.walk(fn)
              if isinstance(n, ast.Call)}
    for bad in ("startswith", "endswith"):
        assert bad not in called, f"redeem_cdkey 仍有前缀/后缀放行判断：{bad}"

    # 整个文件的其他函数也不得引用这些字面量
    for token in ("VIP999", "MEDIAFLOW888", "PRO2026"):
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and n.value == token:
                raise AssertionError(f"core/billing.py 代码中仍出现万能码 {token}")


# ---------------------------------------------------------------------------
# R1-2 /api/billing/redeem 改调 billing_adapter（ledger-backed + 防重放）
# ---------------------------------------------------------------------------

def test_r1_2_redeem_route_uses_adapter_not_legacy():
    """R1-2 静态护栏：兑换路由不得再调 core.billing.redeem_cdkey。

    只看可执行代码（剥离注释与 docstring），避免误伤说明文字。
    """
    import ast
    import io
    import tokenize

    src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
    route = src.split('@app.post("/api/billing/redeem")', 1)[1].split("@app.post", 1)[0]

    #剥离注释
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(route).readline):
        if tok.type != tokenize.COMMENT:
            out.append(tok)
    code_only = tokenize.untokenize(out)

    assert "billing_adapter" in code_only, "兑换路由应改调 billing_adapter"
    assert "billing.redeem_cdkey" not in code_only, "兑换路由不应再走 core.billing"

    # AST 层复核：路由内不得出现 core.billing 的 redeem_cdkey 调用
    fn = next(n for n in ast.walk(ast.parse(route))
              if isinstance(n, ast.AsyncFunctionDef))
    called = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            called.add(getattr(f, "attr", None) or getattr(f, "id", None))
    assert "redeem_cdkey" not in called, "路由仍在直接调用 redeem_cdkey"
    assert "redeem_cdkey_for_user" in called, "路由应调用 web 层适配封装"


def test_r1_2_adapter_contract_unchanged():
    """R1-2 契约护栏：不得破坏 billing_adapter 既有对外签名与返回结构。"""
    import inspect

    from studio import billing_adapter

    sig = inspect.signature(billing_adapter.redeem_cdkey)
    assert list(sig.parameters) == ["db", "tenant_id", "user_id", "code"], (
        f"redeem_cdkey 签名被改动：{sig}"
    )
    for name in ("redeem_cdkey", "generate_cdkeys", "check_and_deduct",
                 "get_billing_status", "grant_tokens", "set_tier"):
        assert name in billing_adapter.__all__, f"{name} 不应从 __all__ 消失"


class _TenantShim:
    """只带 id 的租户替身（供 monkeypatch get_default_billing_user 用）。"""

    def __init__(self, tenant_id: str):
        self.id = tenant_id


@pytest.fixture()
def web_db_url(db_session):
    """studio 侧账本的隔离库 URL（billing_adapter / memberships 用）。"""
    return f"sqlite:///{db_session.bind.url.database}"


def test_r1_2_web_helper_redeem_is_ledger_backed(db_session, web_db_url, monkeypatch):
    """R1-2 行为：web 层封装走 invites 表，前缀码无效且同码不可重放。"""
    from studio import billing_adapter
    from studio.db_models import User
    from studio.membership import capabilities as caps

    #⭐ 用独立租户，不碰 default 租户：
    #   default 租户的用户数决定 tests/test_membership.py 的「首个用户=owner」，
    #   在这里插队会让那个测试失败。
    stack = make_tenant_stack(db_session, unique_name("r1bill"))
    tid, uid = stack["tenant_id"], stack["user_id"]

    # 把 web 层封装指向隔离测试库
    monkeypatch.setenv("YIMU_DB_URL", web_db_url)
    monkeypatch.setattr(caps, "_session_factory_cache", {})
    monkeypatch.setattr(billing_adapter, "_web_session",
                        lambda: caps.get_db_session(web_db_url))
    # web 层封装默认按 default 租户解析，这里改为本次测试的独立租户
    monkeypatch.setattr(
        billing_adapter, "get_default_billing_user",
        lambda db, name="default": (_TenantShim(tid), None),
    )

    codes = billing_adapter.generate_cdkeys_for_actor(
        key_type="tokens", amount=3000, count=1, actor=uid)
    assert len(codes) == 1 and codes[0].startswith("YIMU-TOKEN-")

    first = billing_adapter.redeem_cdkey_for_user(codes[0], uid)
    assert first["ok"] is True, f"正式卡密应可兑换：{first}"
    assert first.get("balance", 0) >= 3000, f"兑换后应返回新余额：{first}"

    replay = billing_adapter.redeem_cdkey_for_user(codes[0], uid)
    assert replay["ok"] is False, "同一卡密不得重复兑换"

    forged = billing_adapter.redeem_cdkey_for_user("MCN-任意串", uid)
    assert forged["ok"] is False, "伪造前缀码必须无效"
    assert "无效" in forged["msg"]


def test_r1_2_failed_grant_refunds_the_card(db_session):
    """R1-2 回归：发放失败必须退还卡密，不能"卡密作废+额度没到账"。"""
    from sqlalchemy import text

    from studio import billing_adapter

    stack = make_tenant_stack(db_session, unique_name("r1refund"))
    tid = stack["tenant_id"]
    codes = billing_adapter.generate_cdkeys(
        db_session, tid, "admin", amount=5000, count=1)

    with pytest.raises(Exception):
        # 用户不存在 → grant_tokens 抛错
        billing_adapter.redeem_cdkey(db_session, tid, "u-ghost", codes[0])

    used = db_session.execute(
        text("SELECT used_count FROM invites WHERE code=:c"),
        {"c": codes[0]},
    ).scalar()
    assert used == 0, f"发放失败后卡密应退还（used_count 应为 0），实际 {used}"

    # 换成真实用户应能正常兑换到账
    uid = stack["user_id"]
    res = billing_adapter.redeem_cdkey(db_session, tid, uid, codes[0])
    assert res["ok"] is True, f"真实用户应能兑换：{res}"
    assert res["balance"] >= 5000


# ---------------------------------------------------------------------------
# R1-3 gen_keys 需要管理员权限
# ---------------------------------------------------------------------------

def test_r1_3_gen_keys_requires_admin_role():
    """R1-3 静态+行为护栏：gen_keys 用 guard_admin，普通用户 403。"""
    src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
    route = src.split('@app.post("/api/billing/admin/gen_keys")', 1)[1].split("@app.post", 1)[0]
    assert "guard_admin(request)" in route, "发卡密接口必须校验管理员角色"
    assert re.search(r"guard\(request\)", route) is None or "guard_admin" in route


def test_r1_3_normal_user_gets_403(client_for_admin_tests):
    """R1-3 行为：普通登录用户调 gen_keys → 403，且不生成任何卡密。"""
    from studio.db_models import Invite

    client_for_admin_tests.as_user(role="user")
    resp = client_for_admin_tests.post(
        "/api/billing/admin/gen_keys",
        json={"key_type": "tokens", "amount": 999999, "count": 3},
    )
    assert resp.status_code == 403, f"普通用户应被拒绝，实际 {resp.status_code}"
    # ⭐ 断言拒绝原因确实是「角色不足」，而不是被 CSRF 之类的中间件拦下（假绿）
    assert "管理员权限" in resp.text, (
        f"403 必须来自角色校验，实际响应：{resp.text[:200]}"
    )
    assert "CSRF" not in resp.text, "403 不得由 CSRF 中间件产生"
    n = client_for_admin_tests.db_session.query(Invite).filter(
        Invite.credits_grant == 999999).count()
    assert n == 0, "被拒绝的请求不得生成卡密"


def test_r1_3_admin_can_gen_keys(client_for_admin_tests):
    """R1-3 行为：管理员调 gen_keys → 200 且返回卡密列表。"""
    client_for_admin_tests.as_user(role="admin")
    resp = client_for_admin_tests.post(
        "/api/billing/admin/gen_keys",
        json={"key_type": "tokens", "amount": 1234, "count": 2},
    )
    assert resp.status_code == 200, f"管理员应放行，实际 {resp.status_code}：{resp.text}"
    data = resp.json()
    assert data["ok"] is True
    assert len(data["keys"]) == 2
    assert all(k.startswith("YIMU-TOKEN-") for k in data["keys"])


def test_r1_3_unauthenticated_gets_401(client_for_admin_tests):
    """R1-3：未登录访问 → 401（先过登录关，再谈角色）。"""
    client_for_admin_tests._c.cookies.clear()
    resp = client_for_admin_tests.post("/api/billing/admin/gen_keys", json={})
    assert resp.status_code in (401, 403), f"未登录应被拒绝，实际 {resp.status_code}"


# ---------------------------------------------------------------------------
# R1-4 扣费检查返回值：余额不足 → 402 + 引导文案 + 不执行业务动作
# ---------------------------------------------------------------------------

def test_r1_4_no_unchecked_check_and_deduct_calls():
    """R1-4 静态护栏：web/admin.py 不得再有裸调用 billing.check_and_deduct。"""
    src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
    raw = re.findall(r"^\s*billing\.check_and_deduct\(", src, re.M)
    assert not raw, f"仍有 {len(raw)} 处未检查返回值的扣费调用"
    assert src.count("require_credits(") >= 15, "扣费应统一走 require_credits"


def test_r1_4_require_credits_raises_402_with_guide(billing_json, monkeypatch):
    """R1-4：额度不足时 require_credits 抛 402，文案可读且不含开发者黑话。"""
    import core.billing as cb
    from fastapi import HTTPException

    from web import admin as web_admin

    # 余额清零
    data = cb._load_data()
    data["balance"] = 0
    cb._save_data(data)

    with pytest.raises(HTTPException) as exc:
        web_admin.require_credits("rewrite", 1, "测试")
    assert exc.value.status_code == 402, f"应为 402，实际 {exc.value.status_code}"

    detail = str(exc.value.detail)
    assert "额度不足" in detail, f"应说明额度不足：{detail}"
    assert "兑换卡密" in detail or "升级" in detail, f"应给出升级/充值引导：{detail}"
    # 面向用户的文案不得出现内部黑话（与 tests/test_no_internal_jargon.py 同标准）
    for jargon in ("check_and_deduct", "token", "Token", "ledger", "402", "扣费", "quota"):
        assert jargon not in detail, f"引导文案含开发者黑话 {jargon}：{detail}"


def test_r1_4_require_credits_passes_when_enough(billing_json):
    """R1-4：额度充足时正常返回 True 并实际扣费。

    ⭐ R2-3：core.billing 的 JSON 账本已废弃为「空壳」，余额真源是
       memberships。这里显式给 legacy JSON 账本灌入额度再验扣费行为
       （R1 的护栏语义——额度充足放行、且确实扣了——保持不变）。
    """
    from studio.pricing import TIER_CREDITS

    from web import admin as web_admin

    billing_json.grant_tokens(TIER_CREDITS["free"], "R1 测试灌额度")
    before = _balance(billing_json)
    assert before > 0, "前置条件：额度应充足"
    assert web_admin.require_credits("rewrite", 1, "测试") is True
    assert _balance(billing_json) == before - billing_json.ACTION_COSTS["rewrite"]


def test_r1_4_drafts_create_402_and_no_draft_created(client_for_admin_tests):
    """R1-4 验收：额度为 0 时 /api/drafts/create → 402 + 引导文案 + 不产生草稿。"""
    from core import db as core_db

    c = client_for_admin_tests
    c.as_user(role="user")
    n_before = len(_all_draft_ids(core_db))

    c.set_balance(0)
    resp = c.post("/api/drafts/create", json={"title": "不该出现的草稿", "body_md": "内容"})

    assert resp.status_code == 402, f"额度为 0 应返回 402，实际 {resp.status_code}"
    detail = resp.text
    assert "CSRF" not in detail, "402 不得由 CSRF 中间件产生"
    assert "额度不足" in detail, f"应说明额度不足：{detail}"
    assert "兑换卡密" in detail or "升级" in detail, f"应给出升级引导：{detail}"

    n_after = len(_all_draft_ids(core_db))
    assert n_after == n_before, f"402 后不得新建草稿（{n_before} → {n_after}）"
    assert "不该出现的草稿" not in _all_draft_titles(core_db), \
        "被拒绝的草稿标题不得落盘"


def test_r1_4_drafts_create_ok_when_enough(client_for_admin_tests):
    """R1-4 回归：额度充足时 /api/drafts/create 正常建档。"""
    c = client_for_admin_tests
    c.as_user(role="user")
    c.set_balance(500000)
    title = f"R1正常建档-{unique_name('t')}"
    resp = c.post("/api/drafts/create", json={"title": title, "body_md": "正文"})
    assert resp.status_code == 200, f"额度充足应建档成功，实际 {resp.status_code}：{resp.text}"
    assert title in _all_draft_titles(_core_db())


def _core_db():
    from core import db as core_db

    return core_db


def _all_draft_ids(core_db):
    try:
        return list(core_db.list_drafts())
    except Exception:
        return []


def _all_draft_titles(core_db):
    try:
        return [d.get("title", "") for d in core_db.list_drafts()]
    except Exception:
        return []


def test_r1_4_every_billing_call_site_charges_before_side_effect():
    """R1-4 静态护栏：每个扣费点都必须在产生副作用之前调用。"""
    import ast

    src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    side_effects = {
        "start_async_job", "create_custom_draft", "generate_scene_image",
        "decompose_draft_to_drama", "step1_analyze_and_rewrite",
        "generate_omnichannel_matrix", "derive_all_platforms_from_master",
        "deep_distill_anything", "regenerate_draft_image",
        "generate_storyboard_image", "step4_generate_asset_image",
        "step4_batch_generate_assets", "step6_generate_shot_image",
        "render_short_drama_video",
    }
    checked = 0
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]:
        idx_call = None
        for i, st in enumerate(fn.body):
            if (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
                    and getattr(st.value.func, "id", "") == "require_credits"):
                idx_call = i
        if idx_call is None:
            continue
        checked += 1
        for st in fn.body[:idx_call]:
            for node in ast.walk(st):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    assert name not in side_effects, (
                        f"{fn.name}:扣费前发生副作用 {name}"
                    )
    assert checked >= 15, f"应至少 15 个扣费点，实际 {checked}"


# ---------------------------------------------------------------------------
# R1-5 loopback 默认口令改 fail-closed
# ---------------------------------------------------------------------------

def test_r1_5_no_password_no_loopback_passthrough(monkeypatch):
    """R1-5：未配置 ADMIN_PASSWORD 时 loopback 不再自动获得超管权限。"""
    from web import admin as web_admin

    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(web_admin, "load_env", lambda: {})
    assert web_admin._admin_password() is None, "未配置口令时不得返回默认值"
    assert web_admin._loopback_admin_allowed() is False

    class _FakeClient:
        host = "127.0.0.1"

    class _FakeReq:
        client = _FakeClient()
        cookies = {}
        headers = {}

    assert web_admin.get_current_user(_FakeReq()) is None, (
        "未配置口令时 loopback 不得免密通行"
    )


def test_r1_5_weak_default_password_treated_as_unset(monkeypatch):
    """R1-5：.env 里写着历史弱口令 local-admin 也视为未配置。"""
    from web import admin as web_admin

    monkeypatch.setattr(web_admin, "load_env", lambda: {"ADMIN_PASSWORD": "local-admin"})
    assert web_admin._admin_password() is None
    assert web_admin._loopback_admin_allowed() is False


def test_r1_5_configured_password_keeps_local_dev_working(monkeypatch):
    """R1-5：已配置口令时，本机开发流程仍可免密（启动脚本会生成随机口令）。"""
    from web import admin as web_admin

    monkeypatch.setattr(web_admin, "load_env",
                        lambda: {"ADMIN_PASSWORD": "yimu-random-generated"})

    class _FakeClient:
        host = "127.0.0.1"

    class _FakeReq:
        client = _FakeClient()
        cookies = {}
        headers = {}

    assert web_admin._admin_password() == "yimu-random-generated"
    assert web_admin._loopback_admin_allowed() is True
    u = web_admin.get_current_user(_FakeReq())
    assert u is not None and u.get("role") == "admin", "本机开发流程不应被打死"


def test_r1_5_mf_token_not_predictable_constant(monkeypatch):
    """R1-5：mf_token 不再是可通过默认值推导的常量。"""
    import hashlib

    from web import admin as web_admin

    monkeypatch.setattr(web_admin, "load_env", lambda: {})
    legacy = hashlib.sha256(b"mf|local-admin").hexdigest()
    assert web_admin._token() != legacy, "mf_token 不得等于历史可推导常量"
    assert web_admin._token() == web_admin._token(), "同进程内应稳定（登录后可复验）"


def test_r1_5_token_rotates_across_processes(monkeypatch):
    """R1-5：进程重启后旧 mf_token 失效。"""
    import importlib

    from web import admin as web_admin

    monkeypatch.setattr(web_admin, "load_env", lambda: {"ADMIN_PASSWORD": "pw-abc"})
    first = web_admin._token()
    reloaded = importlib.reload(web_admin)
    monkeypatch.setattr(reloaded, "load_env", lambda: {"ADMIN_PASSWORD": "pw-abc"})
    assert reloaded._token() != first, "重启后 token 必须变化"
    # 还原模块，避免影响后续测试
    importlib.reload(web_admin)


def test_r1_5_login_rejects_when_password_unset(monkeypatch):
    """R1-5：未配置口令时，用历史默认口令登录也必须失败。"""
    from web import admin as web_admin

    monkeypatch.setattr(web_admin, "load_env", lambda: {})
    assert web_admin._admin_password() is None, (
        "未配置口令时不得回落到 local-admin"
    )


def test_r1_5_startup_warning_emitted(capsys, monkeypatch):
    """R1-5：服务启动时对未配置口令给出明确告警。"""
    from web import admin as web_admin

    monkeypatch.setattr(web_admin, "load_env", lambda: {})
    web_admin._warn_admin_password_state()
    out = capsys.readouterr().out
    assert "ADMIN_PASSWORD" in out, f"启动告警应点明配置项：{out}"


# ---------------------------------------------------------------------------
# R1-6 前端 XSS
# ---------------------------------------------------------------------------

def test_r1_6_toast_uses_textcontent():
    """R1-6：toast 必须用 textContent，杜绝经后端错误消息注入脚本。"""
    src = INDEX_HTML.read_text(encoding="utf-8")
    fn = src.split("function toast(", 1)[1].split("\n}", 1)[0]
    assert "t.textContent = msg" in fn, "toast 应使用 textContent"
    assert "t.innerHTML = msg" not in fn, "toast 不得再使用 innerHTML"


def test_r1_6_ad_result_rendering_escaped():
    """R1-6：广告短片结果渲染的 LLM 输出必须转义。

    锚点用 ``escapeHtml(p)``（卖点映射）定位真正的渲染函数，
    避免被文件里更早出现的 selling_points 字样带偏。
    """
    src = INDEX_HTML.read_text(encoding="utf-8")
    assert "escapeHtml(p)" in src, "未找到卖点渲染锚点，index.html 结构可能已变"

    start = src.index("escapeHtml(p)")
    # 取该渲染函数往后的 3000 字符作为待检区
    block = src[start:start + 3000]

    for field in ("info.hook", "info.body", "info.cta"):
        assert f"${{{field}}}" not in block, f"{field} 仍裸插值进 innerHTML"
        assert f"escapeHtml({field})" in block, f"{field} 应经 escapeHtml"

    assert "${p}</li>" not in block, "卖点仍裸插值进 innerHTML"
    for field in ("vc.product_desc", "vc.person_desc", "vc.style_desc"):
        assert f"${{{field}}}" not in block, f"{field} 仍裸插值进 innerHTML"
        assert f"escapeHtml({field})" in block, f"{field} 应经 escapeHtml"


def test_r1_6_external_image_urls_escaped_and_protocol_checked():
    """R1-6：采集来的图片 URL 需转义并拒绝非 http(s) 协议。"""
    src = INDEX_HTML.read_text(encoding="utf-8")
    idx = src.find("data.images.slice(0, 10)")
    assert idx > 0, "未找到图集渲染代码"
    block = src[idx:idx + 900]
    assert "escapeHtml(imgUrl)" in block, "图集 URL 应转义"
    assert "https?" in block, "应校验协议，防 javascript: 伪协议"


def test_r1_6_no_bare_interpolation_of_user_fields():
    """R1-6 扫描护栏：常见用户/LLM 字段不得再裸插值进 innerHTML。"""
    src = INDEX_HTML.read_text(encoding="utf-8")
    bad = []
    for line in src.splitlines():
        if "innerHTML" not in line:
            continue
        for expr in re.findall(r"\$\{([^{}]*)\}", line):
            if "escapeHtml" in expr or "encodeURIComponent" in expr:
                continue
            if re.search(r"\b(d\.title|st\.likes|st\.collects|st\.comments|"
                         r"stats\.likes|stats\.collects|stats\.comments|stats\.reads|"
                         r"res\.error|res\.model|res\.url|j\.step|img\.section_title|"
                         r"imgUrl|res\.segments)\b", expr):
                bad.append(expr)
    assert not bad, f"仍有裸插值：{bad}"


# ---------------------------------------------------------------------------
# R1-7 死函数修复
# ---------------------------------------------------------------------------

def test_r1_7_cmdk_actions_reach_real_implementations():
    """R1-7：三个死函数必须映射到 index.html 里真实存在的实现。"""
    js = MODERN_JS.read_text(encoding="utf-8")
    src = INDEX_HTML.read_text(encoding="utf-8")
    mapping = {
        "runDecorateImages": "triggerAutoImages",
        "runJudgeScore": "rescoreCurrent",
        "exportJianyingDraft": "exportJianying",
    }
    for dead, real in mapping.items():
        assert dead in js, f"{dead} 的映射声明丢失"
        assert re.search(rf"(async\s+)?function\s+{re.escape(real)}\s*\(", src), (
            f"真实实现 {real} 在 index.html 中不存在"
        )
    # 旧的裸调用不得残留
    for dead in mapping:
        assert f"{{ {dead}(); }}" not in js, f"{dead} 仍在被裸调用"


def test_r1_7_cmdk_error_is_user_visible():
    """R1-7：命令执行异常必须提示用户，不得再 console.error 静默吞掉。"""
    js = MODERN_JS.read_text(encoding="utf-8")
    fn = js.split("function executeSelectedCmd()", 1)[1].split("\n  }", 1)[0]
    assert "console.error(err)" not in fn, "异常不得再被静默吞掉"
    assert "notifyError" in fn, "异常应走 notifyError 给用户提示"
    assert "window.toast" in js, "应复用已有 toast 做可见提示"


def test_r1_7_lite_drawer_functions_exist():
    """R1-7：草稿箱抽屉开合与搜索过滤函数必须真实存在。"""
    src = INDEX_HTML.read_text(encoding="utf-8")
    for fn in ("toggleLiteDraftsDrawer", "filterLiteDraftsList"):
        assert re.search(rf"(async\s+)?function\s+{fn}\s*\(", src), f"{fn} 未实现"
        assert f'window.{fn} = {fn}' in src, f"{fn} 未挂到 window（onclick 取不到）"


def test_r1_7_drawer_elements_exist_and_are_wired():
    """R1-7：抽屉 DOM 与 oninput/onclick 入口齐全，实现能对上。"""
    src = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="lite-drafts-drawer"' in src, "抽屉容器缺失"
    assert 'id="lite-drafts-list-container"' in src, "列表容器缺失"
    assert 'id="lite-drafts-search"' in src, "搜索框缺失"
    assert 'onclick="toggleLiteDraftsDrawer()"' in src
    assert 'oninput="filterLiteDraftsList(this.value)"' in src


def test_r1_7_drawer_filter_escapes_titles():
    """R1-7：抽屉列表渲染标题需转义（草稿标题为用户输入）。"""
    src = INDEX_HTML.read_text(encoding="utf-8")
    fn = src.split("function filterLiteDraftsList(", 1)[1].split("\n}", 1)[0]
    assert "escapeHtml(d.title" in fn, "抽屉列表标题应转义"
    assert "${d.title || '无标题草稿'}" not in fn, "抽屉标题仍裸插值"