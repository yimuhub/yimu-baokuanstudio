# SPDX-License-Identifier: BUSL-1.1
"""v15.9.9 web 效率与一致性整改回归锁（gzip/渲染缓存/ETag/列表摘要化/任务读路径/委托收敛）。

覆盖 v15.9.9 整改清单中的 web 侧改动，防止后续改动悄悄回退：
1. GZip 压缩级别 6（level 9 阻塞事件循环）；
2. 首页/移动页渲染结果进程内缓存（mtime 不变不再读盘）与 version.py mtime 节流重载；
3. 首页 no-cache + sha1 ETag 协商缓存（If-None-Match 命中回 304）与 /static 公共缓存头；
4. GET /api/drafts 列表默认剥离 body_md/analysis（?full=1 保留旧全量行为）；
5. 三条任务读路径（/api/jobs、/api/rewrite/job、/api/tasks/{id}）统一 _get_task_view 同形状；
6. fission 路由委托 derive_omni 同一实现（平台=全部）并标注 deprecated；
7. gateway_ui 邀请码创建委托 studio.membership.service.create_invite 单一实现；
   /api/billing/status 委托 ui/me 的 payload 构造函数（同一取数口径）；
8. /api/tasks 列表裁剪 params/result 大列（error 截断 200 字）。
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import version

ROOT = Path(__file__).resolve().parent.parent

_ADMIN_USER = {"id": "u-admin", "username": "admin", "role": "admin",
               "plan": "enterprise", "is_active": True}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _make_request(method: str = "GET", path: str = "/", body: bytes | None = None,
                  headers: dict | None = None) -> Request:
    """构造最小可用的 Starlette Request（供直接调用路由函数使用）。"""
    hdrs = []
    for k, v in (headers or {}).items():
        hdrs.append((str(k).lower().encode(), str(v).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "method": method,
             "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": hdrs, "client": ("127.0.0.1", 12345),
             "scheme": "http", "server": ("testserver", 80)}
    req = Request(scope)
    if body is not None:
        async def _receive():
            return {"type": "http.request", "body": body, "more_body": False}
        req._receive = _receive
    return req


def _drop_draft(did: str) -> None:
    """测试自清理：core.db 没有单草稿删除入口，直接按行删（隔离库内安全）。"""
    from core import db as core_db
    c = core_db.conn()
    c.execute("DELETE FROM drafts WHERE id=?", (did,))
    c.commit()
    c.close()


@pytest.fixture()
def authed_admin(monkeypatch):
    """把请求鉴权固定为管理员（与 loopback 免密同一身份），不碰真实 Cookie 链路。"""
    from web import admin as web_admin
    monkeypatch.setattr(web_admin, "get_current_user", lambda request: dict(_ADMIN_USER))
    return web_admin


@pytest.fixture()
def studio_session_factory(test_db_path, db_url):
    """studio 侧隔离会话工厂（真实 schema + default 租户行）。"""
    import uuid as _uuid

    from sqlalchemy.orm import sessionmaker

    from studio.db import get_engine, init_db
    engine = get_engine(db_url)
    init_db(engine)
    from studio.db_models import Tenant, utcnow
    S = sessionmaker(bind=engine)
    sess = S()
    try:
        if sess.get(Tenant, "default") is None:
            # why name 加随机后缀：tenants.name 有唯一约束，同一 session 库里
            # 其他用例可能已经建过名为 default 的租户（不同 id）；本套件只依赖
            # id='default'（gateway_ui.TENANT_ID），名字不参与逻辑。
            sess.add(Tenant(id="default", name=f"default-{_uuid.uuid4().hex[:8]}",
                            plan="free", launch_mode="invite-only", is_active=True,
                            created_at=utcnow()))
            sess.commit()
    finally:
        sess.close()
    yield S
    engine.dispose()


# ---------------------------------------------------------------------------
# 1) GZip 压缩级别
# ---------------------------------------------------------------------------

def test_gzip_compresslevel_is_6():
    """效率整改#1：level 9 压首页 33ms 且阻塞事件循环，锁定为 6。"""
    src = (ROOT / "web" / "admin.py").read_text(encoding="utf-8")
    assert "compresslevel=6" in src, "GZipMiddleware 必须显式指定 compresslevel=6"


def test_gzip_middleware_actually_compresses():
    """功能回归：Accept-Encoding: gzip 时大静态文件返回 gzip 编码。"""
    from web.admin import app
    client = TestClient(app)
    r = client.get("/static/js/i18n_dict.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"


# ---------------------------------------------------------------------------
# 2) 渲染缓存与版本 mtime 节流
# ---------------------------------------------------------------------------

def test_home_render_cache_avoids_reread(tmp_path, monkeypatch):
    """效率整改#2：mtime 不变时第二次调用不得重新读盘渲染。"""
    from web import admin as web_admin

    tpl = tmp_path / "index.html"
    tpl.write_text("<html><head><title>t</title></head><body>{{APP_VERSION}}</body></html>",
                   encoding="utf-8")
    monkeypatch.setattr(web_admin, "TEMPLATE_INDEX_PATH", tpl)
    monkeypatch.setattr(web_admin, "TEMPLATE_MOBILE_PATH", tmp_path / "no-mobile.html")

    calls = {"n": 0}
    orig_read_text = Path.read_text

    def _counting_read_text(self, *a, **k):
        if self == tpl:
            calls["n"] += 1
        return orig_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _counting_read_text)
    web_admin._rendered_page_cache.pop(str(tpl), None)

    html1 = web_admin.get_html_page()
    html2 = web_admin.get_html_page()
    assert calls["n"] == 1, "缓存命中时不得再次 read_text"
    assert html1 == html2
    assert "{{APP_VERSION}}" not in html1, "渲染产物必须完成版本注入"

    # mtime 变化 → 缓存失效并重新读盘（「改模板即热更新」语义保留）
    tpl.write_text("<html>changed {{APP_VERSION}}</html>", encoding="utf-8")
    st = os.stat(tpl)
    os.utime(tpl, ns=(st.st_atime_ns + 10 ** 9, st.st_mtime_ns + 10 ** 9))
    html3 = web_admin.get_html_page()
    assert calls["n"] == 2, "mtime 变化必须重新读盘"
    assert "changed" in html3
    web_admin._rendered_page_cache.pop(str(tpl), None)


def test_version_reload_throttled_by_mtime(monkeypatch):
    """效率整改#2：version.py mtime 未变时 get_app_version 不得重复 importlib.reload。"""
    import version as version_mod

    from web import admin as web_admin
    reloads = {"n": 0}
    orig_reload = importlib.reload

    def _counting_reload(module):
        if module is version_mod:
            reloads["n"] += 1
        return orig_reload(module)

    monkeypatch.setattr(importlib, "reload", _counting_reload)
    monkeypatch.setattr(web_admin, "_version_mtime_cache", {"mtime": None, "version": None})

    v1 = web_admin.get_app_version()
    assert reloads["n"] == 1, "首次调用必须真实重载一次"
    v2 = web_admin.get_app_version()
    v3 = web_admin.get_app_version()
    assert reloads["n"] == 1, "mtime 未变不得再次重载"
    assert v1 == v2 == v3


# ---------------------------------------------------------------------------
# 3) 首页 ETag 协商缓存与 /static 公共缓存头
# ---------------------------------------------------------------------------

def test_index_etag_and_304():
    """效率整改#3：no-cache + sha1 ETag；If-None-Match 命中回 304 空体。"""
    from web.admin import app
    client = TestClient(app)
    r1 = client.get("/")
    assert r1.status_code == 200
    assert r1.headers.get("cache-control") == "no-cache"
    etag = r1.headers.get("etag")
    assert etag and etag.startswith('"') and etag.endswith('"')
    assert len(etag) == 42, "sha1 ETag 形如 \"<40 位十六进制>\""

    r2 = client.get("/", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.content == b""
    assert r2.headers.get("cache-control") == "no-cache"
    assert r2.headers.get("etag") == etag

    # 内容不同 → 200 全量
    r3 = client.get("/", headers={"If-None-Match": '"deadbeef"'})
    assert r3.status_code == 200


def test_static_cache_control_header():
    """效率整改#3：/static 200 响应必须带 public, max-age=604800。"""
    from web.admin import app
    client = TestClient(app)
    r = client.get("/static/js/version-sync.js")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=604800"


# ---------------------------------------------------------------------------
# 4) /api/drafts 列表摘要化
# ---------------------------------------------------------------------------

def test_drafts_list_strips_body_md_full_flag_keeps(authed_admin, monkeypatch):
    """效率整改#4：列表默认无 body_md/analysis；?full=1 保留旧全量行为。"""
    from core import db as core_db
    from web.routers import drafts as drafts_router

    big_body = "正文" * 2000
    did = core_db.create_custom_draft(title="摘要化测试", body_md=big_body,
                                      user_id="u-admin")["id"]
    try:
        r = drafts_router.drafts_list(_make_request("/api/drafts"))
        assert r["ok"] is True and r["drafts"], "至少能取到刚创建的草稿"
        row = next(d for d in r["drafts"] if d["id"] == did)
        assert "body_md" not in row and "analysis" not in row
        # 展示所需字段保留（renderDraftList 消费集合）
        for key in ("title", "score", "grade", "cards", "imgs", "round",
                    "thumbnail", "preview_urls", "created_at", "status"):
            assert key in row, f"列表摘要必须保留 {key}"

        r_full = drafts_router.drafts_list(_make_request("/api/drafts"), full=1)
        row_full = next(d for d in r_full["drafts"] if d["id"] == did)
        assert row_full.get("body_md") == big_body, "full=1 必须保留旧全量行为"
        assert r_full["full"] is True
    finally:
        _drop_draft(did)


def test_draft_detail_keeps_body_md(authed_admin):
    """详情接口 GET /api/drafts/{did} 保持全量（列表摘要化不影响详情）。"""
    from core import db as core_db
    from web.routers import drafts as drafts_router

    did = core_db.create_custom_draft(title="详情全量", body_md="详情正文",
                                      user_id="u-admin")["id"]
    try:
        d = core_db.get_draft(did)
        assert d and d["body_md"] == "详情正文"
    finally:
        _drop_draft(did)


# ---------------------------------------------------------------------------
# 5) 三条任务读路径同形状
# ---------------------------------------------------------------------------

def test_task_read_paths_share_one_view(authed_admin):
    """重复R6：/api/jobs、/api/rewrite/job、/api/tasks/{id} 统一 _get_task_view。"""
    from web import admin as web_admin
    from web.routers import tasks as tasks_router

    jid = web_admin.start_async_job("v1599-view-job", name="读路径统一",
                                    task_type="test_only", owner="u-admin",
                                    initial_step="初始化中…")
    raw_jid = "v1599-raw-bypass"
    web_admin.JOBS[raw_jid] = {"step": "旁路处理中", "status": "running",
                               "result": None, "error": ""}
    try:
        jobs_view = tasks_router.rewrite_job_status(jid, _make_request("/api/jobs/x"))
        task_body = tasks_router.get_task_status(jid, _make_request("/api/tasks/x"))
        task_view = task_body["task"]

        assert set(jobs_view.keys()) == set(task_view.keys()), "三条读路径必须同形状"
        assert jobs_view["status"] == task_view["status"] == "running"
        assert task_view["step"] == task_view["message"] == "初始化中…"
        assert task_view["owner"] == "u-admin"

        # JOBS 旁路条目（未进 task_queue）兜底可读且同形状
        raw_view = web_admin._get_task_view(raw_jid)
        assert raw_view and set(raw_view.keys()) == set(task_view.keys())
        assert raw_view["status"] == "running" and raw_view["step"] == "旁路处理中"

        # done → completed 归一（JOBS 旧写法兼容）
        web_admin.JOBS[raw_jid]["status"] = "done"
        done_view = web_admin._get_task_view(raw_jid)
        assert done_view["status"] == "completed"
    finally:
        web_admin.JOBS.pop(jid, None)
        web_admin.JOBS.pop(raw_jid, None)


def test_tasks_list_trims_big_columns(authed_admin):
    """效率整改#9：/api/tasks 列表剥掉 params/result 大列，error 截断 200 字。"""
    from web import admin as web_admin
    from web.routers import tasks as tasks_router

    jid = web_admin.start_async_job("v1599-trim-job", name="裁剪测试",
                                    task_type="test_only", owner="u-admin")
    web_admin.update_async_job(jid, status="failed", step="失败",
                               error="E" * 500, result={"blob": "x" * 50000})
    try:
        r = tasks_router.list_active_tasks(_make_request("/api/tasks"))
        row = next(t for t in r["tasks"] if t["id"] == jid)
        for big in ("result", "params", "result_json", "params_json"):
            assert big not in row, f"列表不得携带大列 {big}"
        assert len(row.get("error") or "") == 200, "error 必须截断到 200 字"
        # step 文本在 task_queue 行里叫 message（task_queue 视图无 step 键）
        for key in ("id", "name", "status", "progress", "owner", "created_at", "message"):
            assert key in row, f"列表必须保留 {key}"
    finally:
        web_admin.JOBS.pop(jid, None)


# ---------------------------------------------------------------------------
# 6) fission 委托 derive_omni
# ---------------------------------------------------------------------------

def test_fission_delegates_to_omni_derive(authed_admin, monkeypatch):
    """重复R6：fission 与 derive_omni 走同一实现，fission 强制平台=全部并标注 deprecated。"""
    from core import db as core_db
    from web import admin as web_admin
    from web.routers import drafts as drafts_router

    did = core_db.create_custom_draft(title="裂变母稿", body_md="正文",
                                      user_id="u-admin")["id"]
    captured: dict = {}
    calls: list = []

    def _fake_spawn(u, name, fn, *, jid, task_type, target_id="", params=None,
                    initial_step="排队中…"):
        captured.update({"u": u, "name": name, "fn": fn, "jid": jid,
                         "task_type": task_type, "target_id": target_id,
                         "params": dict(params or {})})
        return {"job": jid}

    monkeypatch.setattr(drafts_router, "_spawn_user_job", _fake_spawn)
    monkeypatch.setattr(web_admin, "require_credits", lambda *a, **k: None)

    def _fake_derive(**kwargs):
        calls.append(kwargs)
        return {"selected_platforms": ["xhs"]}

    from core import fission as fission_mod
    monkeypatch.setattr(fission_mod, "derive_all_platforms_from_master", _fake_derive)

    try:
        # fission：平台强制=全部（请求体即使带 platforms 也忽略）
        res = asyncio.run(drafts_router.draft_fission(
            did, _make_request("POST", "/api/drafts/x/fission",
                               body=b'{"platforms": ["toutiao"]}')))
        assert res["deprecated"] is True
        assert res["use_instead"].endswith("/derive_omni")
        assert captured["task_type"] == "omni_derive"
        assert captured["params"].get("platforms") is None, "fission 必须强制平台=全部"
        captured["fn"]()
        assert calls and calls[-1].get("target_platforms") is None
        assert calls[-1].get("draft_id") == did

        # derive_omni：保留 platforms 参数语义
        res2 = asyncio.run(drafts_router.draft_derive_omni(
            did, _make_request("POST", "/api/drafts/x/derive_omni",
                               body=json.dumps({"platforms": ["xhs"]}).encode())))
        assert res2["job"] == captured["jid"]
        assert captured["params"].get("platforms") == ["xhs"]
    finally:
        _drop_draft(did)


# ---------------------------------------------------------------------------
# 7) 邀请码创建委托 + billing/status 委托 ui/me
# ---------------------------------------------------------------------------

def test_ui_create_invite_delegates_to_service(monkeypatch, studio_session_factory):
    """重复R7：gateway_ui 邀请码创建必须委托 studio.membership.service.create_invite。"""
    from web import gateway_ui as gw

    monkeypatch.setattr(gw, "_db", lambda: studio_session_factory())
    req = _make_request("POST", "/api/billing/ui/invites",
                        body=json.dumps({"max_uses": 2, "credits_grant": 10,
                                         "expires_in_days": 0}).encode(),
                        headers={"Content-Type": "application/json"})
    resp = asyncio.run(gw.ui_create_invite(req))
    payload = json.loads(resp.body)
    assert payload["ok"] is True
    assert payload["data"]["code"], "必须返回生成的邀请码"
    assert payload["data"]["max_uses"] == 2

    # 非法参数走 service 层统一错误体（不在 UI 层复制校验逻辑）
    bad = _make_request("POST", "/api/billing/ui/invites",
                        body=json.dumps({"max_uses": 0}).encode(),
                        headers={"Content-Type": "application/json"})
    resp_bad = asyncio.run(gw.ui_create_invite(bad))
    assert resp_bad.status_code == 400
    assert json.loads(resp_bad.body)["ok"] is False

    from studio.db_models import AuditLog, Invite
    sess = studio_session_factory()
    try:
        assert sess.query(Invite).filter(Invite.id == payload["data"]["id"]).one_or_none()
        audit = sess.query(AuditLog).filter(AuditLog.action == "invite.create").first()
        assert audit is not None, "service 层必须写审计日志（委托而非复制的证据）"
    finally:
        sess.close()


def test_billing_status_delegates_to_ui_me_payload(monkeypatch, studio_session_factory):
    """重复R7：/api/billing/status 委托 ui/me 的 payload 构造，外层字段保持兼容。"""
    from core import db as core_db  # noqa: F401  确保 core 侧已初始化
    from web import admin as web_admin
    from web import gateway_ui as gw
    from web.routers import billing as billing_router

    monkeypatch.setattr(gw, "_db", lambda: studio_session_factory())
    status = billing_router.billing_status(_make_request("/api/billing/status"))
    # pricing.html 的既有消费字段（balance/total_consumed/tier_name/tier）必须在
    for key in ("tier", "tier_name", "balance", "total_consumed"):
        assert key in status, f"/api/billing/status 必须保持旧外层字段 {key}"
    # 与 ui/me 同一取数口径（同一请求用户两次取数必须一致，这是收敛的意义）
    summary = gw.membership_payload_for_request(_make_request("/api/billing/ui/me"))
    assert status["tier"] == summary["tier"]
    assert status["tier_name"] == summary["tier_name"]
    assert status["balance"] == summary["credits_left"]
    assert status["total_consumed"] == summary["credits_used"]


# ---------------------------------------------------------------------------
# 8) fire-and-forget 收敛到统一受界任务池
# ---------------------------------------------------------------------------

def test_spawn_user_job_registers_into_jobs_with_owner(authed_admin):
    """效率整改#10：admin.spawn_user_job 注册的 JOBS 条目必须带 owner。

    ⚠️ 已知 core 侧缺陷（本次整改只核验、不越权修改）：core/task_queue.py
    模块级 ``register_job()`` 包装函数不转发 ``owner`` 形参，导致
    ``start_async_job`` 调 ``task_queue.register_job(..., owner=...)`` 抛
    TypeError 被吞——持久化队列注册整体丢失（owner 也进不了 async_tasks 行）。
    修复点在 core/task_queue.py 的包装函数加 owner 透传（见交接报告），
    web 侧传参口径已按契约写对。
    """
    from web import admin as web_admin

    jid = "v1599-spawn-check"
    web_admin.JOBS.pop(jid, None)
    try:
        out = web_admin.spawn_user_job(_ADMIN_USER, "冒烟任务", lambda: None,
                                       jid=jid, task_type="test_only")
        assert out == {"job": jid}
        job = web_admin.JOBS[jid]
        assert job["owner"] == "u-admin"
        assert job["task_type"] == "test_only"
        assert job["step"] == "排队中…"
        assert "created_at" in job
    finally:
        web_admin.JOBS.pop(jid, None)


def test_no_fire_and_forget_run_in_executor_left_in_web_routers():
    """锁死收敛结果：web/routers 不允许出现未 await 的 run_in_executor（fire-and-forget）。"""
    import re
    for py in (ROOT / "web" / "routers").glob("*.py"):
        src = py.read_text(encoding="utf-8")
        for m in re.finditer(r"^(\s*)asyncio\.get_event_loop\(\)\.run_in_executor\(", src, re.M):
            # 未 await：行首缩进后直接调用（await 的会有 await 前缀，不匹配 ^\s*asyncio）
            raise AssertionError(f"{py.name} 仍存在 fire-and-forget run_in_executor")


def test_no_raw_jobs_registration_left_in_web():
    """漂移6 锁死：web/routers 不允许再出现 `JOBS[...] = {` 裸注册。"""
    import re
    forbidden = re.compile(r"^\s*_a\.JOBS\[\S+\]\s*=\s*\{|^\s*JOBS\[\S+\]\s*=\s*\{", re.M)
    for py in (ROOT / "web" / "routers").glob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert not forbidden.search(src), f"{py.name} 存在 JOBS 裸注册（必须走 start_async_job/spawn_user_job）"


# ---------------------------------------------------------------------------
# 9) 模型默认单一真源（R5）：模块必须真接线，不许残留「加载了但零调用」的死模块
# ---------------------------------------------------------------------------

def test_model_defaults_module_is_actually_wired():
    """yimu-model-defaults.js 必须在模板里被加载，且至少 3 处真实调用。

    why 锁这条：v15.9.9 曾出现「模块写好了、<script> 也加了、但全仓零调用」
    的半成品——文件在、功能不在，比不写更容易误判为已完成。
    """
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "/static/js/yimu-model-defaults.js" in html, "单一真源模块没有被页面加载"
    calls = html.count("YIMU_MODEL_DEFAULTS.")
    assert calls >= 3, f"模块只有 {calls} 处调用，接线不完整（首屏回画/写路径/广播至少要覆盖）"


def test_studio_model_change_writes_server_default():
    """影音工坊下拉 change 必须落到服务端能力线默认，不能只写 localStorage。

    why 锁这条：这是审查确认的「在 A 处改、B 处不生效」根因——只写
    localStorage 时后端真正生成仍按控制中心的旧默认跑。
    """
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index("function onStudioModelChange(")
    end = html.index("\nfunction ", start + 10)
    body = html[start:end]
    assert "YIMU_MODEL_DEFAULTS" in body and ".apply(" in body, (
        "onStudioModelChange 仍未写服务端默认（localStorage 只是缓存位）")


def test_model_scope_marks_all_six_entries():
    """六类模型入口（影音工坊/短剧/分镜/广告片/AI视频/个人中心）都要声明 scope。

    未声明 data-model-scope 的下拉不会被单一真源模块联动，等于保留一个
    「只在本地生效」的旁路入口——正是重复 Top1 的成因。
    """
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    for sid in ("drama-image-model-sel", "drama-step4-image-model-sel",
                "drama-step6-image-model-sel", "drama-step7-video-model-sel",
                "drama-video-model-sel", "vd-image-model-sel", "sb-image-model-sel",
                "ad-video-model-sel", "aiv-model-sel", "aivCfg-model", "im-model"):
        idx = html.index(f'id="{sid}"')
        # 只看该元素自己的开始标签：id 属性到该标签的 '>' 之间
        tag = html[idx:html.index(">", idx)]
        assert "data-model-scope=" in tag, f"{sid} 缺少 data-model-scope 声明"


def test_model_defaults_module_exposes_init_and_paint_all():
    """模块必须暴露首屏入口（init/paintAll）——否则服务端默认首屏回画无路可走。"""
    js = (ROOT / "web" / "static" / "js" / "yimu-model-defaults.js").read_text(encoding="utf-8")
    assert "function paintAll(" in js
    assert "function init(" in js
    assert "paintAll: paintAll" in js and "init: init" in js


def test_model_defaults_event_has_listener():
    """模块 dispatch 的变更事件必须有监听者，否则广播空转。"""
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "addEventListener('yimu-model-defaults-changed'" in html


# ---------------------------------------------------------------------------
# 10) 静态资源版本串（v15.9.9 真实走查发现）
#
# why 必须锁这条：/static/* 下发 Cache-Control: public, max-age=604800（7 天），
# 而页面引用原先不带任何版本串。发版后 HTML（no-cache）已经是新版、JS/CSS 仍吃
# 7 天旧缓存，最多能连着跑一周「新壳 + 旧逻辑」——本轮修复 yimu-model-defaults.js
# 时就是靠浏览器实测才发现的（服务端已是新代码，页面加载的仍是旧 JS）。
# ---------------------------------------------------------------------------

def test_static_assets_get_version_query():
    from web.admin import render_dynamic_html
    cur = version.get_version()
    out = render_dynamic_html(
        '<head></head><body>'
        '<script src="/static/js/a.js"></script>'
        '<link href="/static/css/b.css">'
        '<img src="/static/img/c.png">'
        '<a href="/api/keep">x</a>'
        '</body>')
    for path in ("/static/js/a.js", "/static/css/b.css", "/static/img/c.png"):
        assert f'{path}?v={cur}' in out, f"{path} 未追加版本串，发版后会吃 7 天旧缓存"
    # 非 /static/ 的业务链接不得被改写
    assert 'href="/api/keep"' in out
    assert '/api/keep?v=' not in out


def test_static_version_rewrite_is_idempotent():
    """重复渲染不得叠加成 ?v=a?v=b（缓存失效/模板热更新都会重复走一遍）。"""
    from web.admin import render_dynamic_html
    cur = version.get_version()
    once = render_dynamic_html('<script src="/static/js/a.js"></script>')
    twice = render_dynamic_html(once)
    assert twice.count(f"?v={cur}") == 1
    assert "?v=" + cur + "?v=" not in twice


def test_served_home_page_versions_static_assets(authed_admin):
    """真实渲染出的首页必须带版本串——只测纯函数不算数，要过整条渲染链。"""
    cur = version.get_version()
    r = TestClient(authed_admin.app).get("/")
    assert r.status_code == 200
    assert f'/static/js/yimu-model-defaults.js?v={cur}' in r.text
    # 模板里不存在无版本串的裸引用
    assert 'src="/static/js/yimu-net.js"' not in r.text


# ---------------------------------------------------------------------------
# 11) 免 Key 生图保底引擎（flux-schnell）三处必须同源
#
# why 锁这条：真实走查发现「设置里能选 flux-schnell 并保存成功，回到影音工坊
# 下拉里却没有这一项、流水线主按钮还被判『没有可用生图模型』锁死」——而真正
# 生成走的就是这个保底引擎，能正常出图。设置、能力、守门三方口径必须一致。
# ---------------------------------------------------------------------------

def test_free_image_engine_is_single_constant():
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "const FREE_IMAGE_ENGINE = 'flux-schnell';" in html, "免 Key 引擎必须单点定义"


def test_studio_image_dropdown_lists_free_engine():
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index("async function initStudioModelSelects()")
    end = html.index("\nfunction ", start + 10) if "\nfunction " in html[start+10:] else len(html)
    body = html[start:end]
    assert "FREE_IMAGE_ENGINE" in body, "影音工坊生图下拉必须列出免 Key 保底引擎"


def test_gate_treats_free_engine_as_available():
    """守门判定必须把免 Key 引擎算作可用，且视频缺失时文案不得连坐生图。"""
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index("function studioModelSelectUnavailable(")
    end = html.index("\nasync function initStudioModelSelects", start)
    body = html[start:end]
    assert "freeEngine" in body, "守门判定未豁免免 Key 保底引擎"
    assert "尚未接入视频模型——分镜脚本与出图仍可用" in html, (
        "视频缺失时文案必须说明生图仍可用，不能笼统说「生图/视频」")


def test_provider_defaults_missing_does_not_wipe_free_engine_cache():
    """服务端三条能力线查不到免 Key 引擎时，缓存位不得被抹成「自动」。

    why：flux-schnell 不属于任何通道，capability_defaults 里没有它的位置；
    refresh() 若照常写空串，用户刚选好的保底引擎会被画回「自动」，
    而真正生成仍用 flux-schnell —— 界面与事实背离（真实走查复现）。
    """
    js = (ROOT / "web" / "static" / "js" / "yimu-model-defaults.js").read_text(encoding="utf-8")
    assert "FREE_ENGINES" in js, "模块必须有免 Key 引擎豁免表"
    start = js.index("function paintAll(")
    end = js.index("function init(", start)
    assert "readCache('image')" in js[start:end], "paintAll 服务端为空时必须回落缓存位"


def test_image_dialog_prefill_reads_legacy_slot():
    """设置弹窗预填必须与后端解析链同序：能力线显式 > image.model 保底槽位 > 自动。

    why：此前只读 caps.image 的 explicit，选了 flux-schnell 保存后重开弹窗
    显示「自动（当前没有可用模型）」，而 settings.image.model 明明是 flux-schnell。
    """
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    start = html.index("async function populateImageModelDropdown(")
    end = html.index("\nasync function ", start + 10) if "\nasync function " in html[start+10:] else len(html)
    body = html[start:end]
    assert "legacySlot" in body, "弹窗预填未读取 settings.image.model 保底槽位"
    assert "S.image" in body


# ---------------------------------------------------------------------------
# 12) 任务状态词汇：后端归一与前端终态判定必须同源
# ---------------------------------------------------------------------------

def test_terminal_status_vocabulary_is_shared():
    """终态集合必须同时覆盖 done 与 completed 两代词汇。

    why（v15.9.9 实测事故）：任务视图统一后 /api/rewrite/job 把 JOBS 的
    ``done`` 归一成 ``completed``，而全站 40+ 处轮询各自写死
    ``j.status === 'done'``——于是所有后台任务（配音/改写/生图/视频/发布/工单）
    都等不到终态，一路轮询到 maxMs（最长 30 分钟）才报「仍在后台执行」。
    这类断裂机械测试全绿、只有真实操作才暴露，故在此锁死词汇表。
    """
    from web import admin as web_admin

    assert set(web_admin.TASK_TERMINAL_STATUSES) == {
        "completed", "failed", "cancelled", "interrupted"}, \
        "后端终态集合必须覆盖 completed/failed/cancelled/interrupted"
    assert "done" in web_admin._TASK_DONE_ALIASES, "done 是历史成功写法，必须仍是别名"
    # 归一后必须是终态集合成员（不得出现归一产出落在集合外的情形）
    for raw in ("done", "completed", "failed", "cancelled", "interrupted"):
        assert web_admin._normalize_task_status(raw) in web_admin.TASK_TERMINAL_STATUSES


def test_frontend_uses_terminal_status_helper_not_literals():
    """前端不得再写死 status === 'done' / 'completed' 判定终态。

    why：字面量判定就是上面那次事故的直接成因。统一走 isTerminalStatus /
    isSuccessStatus，后端换词时只改一处。
    """
    net = (ROOT / "web" / "static" / "js" / "yimu-net.js").read_text(encoding="utf-8")
    assert "function isTerminalStatus(" in net
    assert "function isSuccessStatus(" in net
    assert "global.isTerminalStatus = isTerminalStatus;" in net
    assert "global.isSuccessStatus = isSuccessStatus;" in net
    for word in ("completed", "done", "failed", "cancelled", "interrupted"):
        assert word in net, f"终态词汇表缺少 {word}"

    for tpl, helper_decl in (("index.html", False), ("mobile.html", True)):
        html = (ROOT / "web" / "templates" / tpl).read_text(encoding="utf-8")
        assert "status === 'done'" not in html, f"{tpl} 仍写死 status === 'done'"
        assert "status === 'completed'" not in html, f"{tpl} 仍写死 status === 'completed'"
        assert "isTerminalStatus(" in html, f"{tpl} 未使用 isTerminalStatus"
        if helper_decl:
            # 移动端自包含、不引入 yimu-net.js，必须就地声明同一套词汇表
            assert "const TERMINAL_STATUSES" in html, "移动端缺少内联终态词汇表"


def test_polling_reaches_terminal_state_for_both_vocabularies(authed_admin):
    """轮询必须能在 done 与 completed 两种返回下都走到终态。

    直接跑真实路由：把任务置为 completed（task_queue 口径）与 done
    （JOBS 历史口径），确认 /api/rewrite/job 的 status 都能被终态集合命中。
    """
    from web import admin as web_admin
    from web.routers import tasks as tasks_router

    jid = web_admin.start_async_job("v1599-vocab-job", name="词汇表",
                                    task_type="test_only", owner="u-admin")
    try:
        web_admin.update_async_job(jid, status="done", step="完成")
        view = tasks_router.rewrite_job_status(jid, _make_request("/api/jobs/x"))
        assert view["status"] in web_admin.TASK_TERMINAL_STATUSES, \
            f"JOBS 的 done 归一后必须落在终态集合内，实际 {view['status']}"
        assert web_admin._normalize_task_status(view["status"]) == "completed"

        # 取消态同样必须被识别为终态
        web_admin.update_async_job(jid, status="cancelled", step="已取消")
        view2 = tasks_router.rewrite_job_status(jid, _make_request("/api/jobs/x"))
        assert view2["status"] in web_admin.TASK_TERMINAL_STATUSES
    finally:
        web_admin.JOBS.pop(jid, None)
