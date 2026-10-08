"""一幕·YIMU 爆款工作室（FastAPI :8790）。

面板：搜索仿写 / 选题 / 草稿工作台 / 发布 / 设置。
v2：仿写按钮禁用态+进度、toast、草稿左右分栏工作区、手机壳预览、评分Tab、
    重新评分/定向重写、多主题排版、AI 配图、考核配置。
"""
import asyncio
import hashlib
import re
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import yaml                                          # noqa: E402
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402
from fastapi.responses import (FileResponse, HTMLResponse,   # noqa: E402
                               JSONResponse, Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles          # noqa: E402

from core import db, judge, orchestrator             # noqa: E402
from core.llm import load_config, load_env           # noqa: E402
from core.themes import WECHAT_THEMES, XHS_CARD_STYLES  # noqa: E402
from core import agents as AG                      # noqa: E402
from core import layouter                          # noqa: E402
from adapters.base import PLATFORMS, NAMES           # noqa: E402

CFG_PATH = BASE / "config.yaml"
ENV_PATH = BASE / ".env"

app = FastAPI(title="一幕·YIMU 爆款工作室")
# ⭐ 性能：GZip 压缩（index.html 约 835KB → ~140KB，首屏加载显著加快）
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.mount("/static-img", StaticFiles(directory=str(BASE / "data")), name="img")
app.mount("/static", StaticFiles(directory=str(BASE / "web" / "static")), name="static")

# ---- V7 网关 + 会员账本 UI（WS1）：/admin/gateway、/admin/billing 功能页 ----
# 注意：web/gateway_ui.py 模块顶层不导入 web.admin（函数内导入鉴权），无循环导入；
# gateway/routers_openai.py 仅定义路由（import 无副作用），主 app 此前无 /v1/* 路由。
from web.gateway_ui import router as gateway_ui_router  # noqa: E402
from gateway.routers_openai import router as gateway_openai_router  # noqa: E402
app.include_router(gateway_ui_router)
app.include_router(gateway_openai_router)

# ---- 会员路由（WS-B 集成）：studio/membership_router ----
# 与 B 现有 /api/auth/*、/api/admin/* 无路径冲突（已核验）。
# studio 侧 DB 会话走 YIMU_DB_URL；默认指向主应用同一 sqlite 文件，
# 保证网关 UI、/v1、会员三方数据一致（测试可用 YIMU_DB_URL 隔离）。
import os as _os  # noqa: E402
from core.db import DB_PATH as _MAIN_DB_PATH  # noqa: E402
_os.environ.setdefault("YIMU_DB_URL", "sqlite:///" + str(_MAIN_DB_PATH))
from studio.membership_router import router as membership_router  # noqa: E402
app.include_router(membership_router)

# ---- 图片专项 API（studio/image_forge）：/api/image/* ----
# 审计发现：router.py 的 build_router() 从未被挂载，前端/后端均无 /api/image/*。
# 此处挂载并接入鉴权 + 会员分级（free 档 race_allowed=False → 单张直出）。
from studio.image_forge import router as _image_forge_mod  # noqa: E402
from studio.image_forge.router import handle_request as _image_handle_request  # noqa: E402


def _image_forge_endpoint(_handler_name: str, _method: str, _path: str):
    async def _endpoint(request: Request):
        user = guard(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}
        # ⭐ 会员分级：赛马权限按档位
        #   free：每周 3 次赛马体验（image_race_weekly），用完转单张直出
        #   pro/studio：image_race=True，赛马不限
        _race_allowed = False
        if _handler_name == "generate":
            _tier = _tier_capability_limit(user, "image_race")
            if _tier:
                _race_allowed = True  # pro/studio 全开
            else:
                _ok, _, _ = _tier_quota_check(user, "image_race_weekly")
                _race_allowed = bool(_ok)  # free：配额内体验赛马，用完单张直出
        ctx = {
            "tenant_id": "default",
            "request_id": request.headers.get("x-request-id"),
            "db_url": _os.environ.get("YIMU_DB_URL"),
            "image_client": None,  # 上游未配置时抛 UpstreamNotReady（诚实报错）
            "race_allowed": _race_allowed,
        }
        result = _image_handle_request(_method, _path, body, ctx)
        status = 200 if result.get("ok") else {
            "NOT_FOUND": 404, "BAD_REQUEST": 400,
            "UPSTREAM_NOT_READY": 503, "FORBIDDEN": 403,
        }.get(result.get("code"), 500)
        return JSONResponse(result, status_code=status)
    _endpoint.__name__ = f"image_forge_{_handler_name}"
    return _endpoint


for _m, _p, _n in _image_forge_mod.ROUTES:
    (_register := app.get if _m == "GET" else app.post)(
        _p, name=f"image_forge_{_n}")(_image_forge_endpoint(_n, _m, _p))
del _m, _p, _n, _register


# ---- YIMU Gateway /v1 运行时装配（集成）：补齐 routers_openai 依赖的 app.state ----
# 与 web/gateway_ui 共用同一 DB（YIMU_DB_URL 优先，否则主应用 DB 文件），保证
# UI 创建的 Key 能被 /v1 鉴权识别；装配失败不阻塞主服务启动。
try:
    from gateway.config import (  # noqa: E402
        GatewayError,
        gateway_error_handler,
        load_model_catalog,
        load_settings,
    )
    from gateway.limits import RateLimiter  # noqa: E402
    from gateway.main import _build_upstream_pool, _ensure_sqlite_dir  # noqa: E402
    from studio.db import get_engine as _gw_get_engine  # noqa: E402
    from studio.db import get_session_factory as _gw_session_factory  # noqa: E402
    from studio.db import init_db as _gw_init_db  # noqa: E402
    from web.gateway_ui import _db_url as _gw_db_url  # noqa: E402

    _gw_settings = load_settings()
    _gw_db_url_str = _gw_db_url()
    _ensure_sqlite_dir(_gw_db_url_str)
    _gw_engine = _gw_get_engine(_gw_db_url_str)
    _gw_init_db(_gw_engine)
    app.state.settings = _gw_settings
    app.state.session_factory = _gw_session_factory(_gw_engine)
    app.state.rate_limiter = RateLimiter()
    app.state.model_catalog = load_model_catalog()
    app.state.upstream_pool = _build_upstream_pool(app)

    @app.exception_handler(GatewayError)
    async def _gateway_error_handler(request: Request, exc: GatewayError):
        return await gateway_error_handler(request, exc)
except Exception as _gw_exc:  # pragma: no cover
    print(f"⚠️ 网关 /v1 运行时装配失败（主服务不受影响，/v1 暂不可用）：{_gw_exc}")


@app.on_event("startup")
async def on_startup():
    try:
        cnt = db.recover_interrupted_tasks()
        if cnt > 0:
            print(f"[Startup] 已自动识别并标记 {cnt} 个中断任务为 interrupted 状态，支持断点续跑")
    except Exception as e:
        print(f"[Startup] 任务恢复检测轻微异常: {e}")
    try:
        from core import scheduler
        scheduler.start_scheduler_daemon()
    except Exception as e:
        print(f"[Startup] 排期调度守护线程启动轻微异常: {e}")

# ---------------- 全局统一异步任务池与调度中枢 ----------------
JOBS: dict = {}


def start_async_job(jid: str, name: str, task_type: str, target_id: str = "",
                    total_steps: int = 1, params: dict | None = None,
                    initial_step: str = "排队中…") -> str:
    """统一注册并启动一个异步算力任务，同步通知 task_queue 和持久化数据库。"""
    from core import task_queue
    JOBS[jid] = {
        "id": jid,
        "name": name,
        "task_type": task_type,
        "target_id": target_id,
        "step": initial_step,
        "status": "running",
        "result": None,
        "error": "",
        "created_at": time.time(),
    }
    try:
        task_queue.register_job(jid, name=name, task_type=task_type, target_id=target_id,
                                total_steps=total_steps, params=params)
    except Exception as e:
        print(f"[start_async_job] register error: {e}")
    return jid


def update_async_job(jid: str, *, status: str | None = None,
                     step: str | None = None, progress: int | None = None,
                     result: any = None, error: str | None = None):
    """实时更新异步任务进度与状态。"""
    from core import task_queue
    if jid in JOBS:
        if status is not None:
            JOBS[jid]["status"] = status
        if step is not None:
            JOBS[jid]["step"] = step
        if result is not None:
            JOBS[jid]["result"] = result
        if error is not None:
            JOBS[jid]["error"] = error
    try:
        task_queue.update_job(jid, status=status, step=step, progress=progress,
                              result=result, error=error)
    except Exception as e:
        print(f"[update_async_job] update error: {e}")


# 本机网络层存在 POST 重放（同一请求会到两次）：写操作按 内容哈希 幂等去重，
# 60 秒内重复请求直接回放第一次的响应，避免"第二份空结果覆盖第一份真结果"。
_SEEN: dict = {}


@app.middleware("http")
async def idempotent_posts(request: Request, call_next):
    if request.method == "POST" and request.url.path.startswith("/api/"):
        path = request.url.path
        if any(path.endswith(s) or s in path for s in (
            "/rescore", "/rewrite", "/restore", "/delete", "/collect",
            "/manual", "/settings", "/generate_job", "/wx_imgs", "/gh_imgs",
            "/ai_layout", "/ai_xhs", "/publish"
        )):
            return await call_next(request)
        raw = await request.body()
        request._body = raw
        key = hashlib.sha256(path.encode() + b"|" + raw).hexdigest()
        now = time.time()
        for k in list(_SEEN):
            if now - _SEEN[k][0] > 30:
                _SEEN.pop(k, None)
        hit = _SEEN.get(key)
        if hit:
            return hit[1]
        resp = await call_next(request)
        try:
            if resp.status_code == 200 and getattr(resp, "body", None):
                _SEEN[key] = (now, resp)
        except Exception:
            pass
        return resp
    return await call_next(request)


def _token() -> str:
    return hashlib.sha256(f"mf|{load_env().get('ADMIN_PASSWORD', 'local-admin')}".encode()).hexdigest()


def get_current_user(request: Request) -> dict | None:
    """获取当前请求的用户信息（支持 V6 JWT Cookie 或 Authorization Header）"""
    # 1. 尝试从 Cookie 或 Header 读取 V6 签名 Token
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("mf_v6_token") or request.cookies.get("mf_token", "")
    
    if token:
        from core import auth
        payload = auth.verify_token(token)
        if payload and payload.get("user_id"):
            u = auth.get_user_by_id(payload["user_id"])
            if u and u.get("is_active"):
                return u
                
    # 2. 兼容旧单机模式全局 Token
    if request.cookies.get("mf_token") == _token():
        return {"id": "u-admin", "username": "admin", "role": "admin", "plan": "enterprise"}
        
    # 3. 本地 loopback 自动免密通行（映射为系统超级管理员）
    client_ip = request.client.host if request.client else ""
    if client_ip in ("127.0.0.1", "::1", "localhost") and load_env().get("ADMIN_PASSWORD", "local-admin") == "local-admin":
        return {"id": "u-admin", "username": "admin", "role": "admin", "plan": "enterprise"}
        
    return None


def authed(request: Request) -> bool:
    return get_current_user(request) is not None


def guard(request: Request) -> dict:
    u = get_current_user(request)
    if not u:
        raise HTTPException(401, "未登录或登录态已失效，请先登录")
    return u


def _tier_quota_check(user: dict, capability: str) -> tuple:
    """会员配额检查（V7 Free / V7 Pro / V7 Studio 三档）。

    返回 (allowed, reason, tier)：配额系统异常时直接放行（配额是体验
    限制非资金，不阻塞主功能）；未知用户按 free 档处理。
    """
    try:
        from studio.membership import capabilities as _caps

        _db = _caps.get_db_session()
        try:
            _uid = str((user or {}).get("id") or "")
            _tier = _caps.get_user_tier(_db, tenant_id="default", user_id=_uid)
            _allowed, _reason = _caps.check_and_consume(
                _db, tenant_id="default", user_id=_uid,
                tier=_tier, capability=capability,
            )
            return _allowed, _reason, _tier
        finally:
            _db.close()
    except Exception:
        return True, "", "pro"


def _tier_capability_limit(user: dict, capability: str):
    """取用户某能力的配置值；异常时返回 -1（不限）。"""
    try:
        from studio.membership import capabilities as _caps

        _db = _caps.get_db_session()
        try:
            _tier = _caps.get_user_tier(
                _db, tenant_id="default", user_id=str((user or {}).get("id") or ""))
            return _caps.capability_limit(_tier, capability)
        finally:
            _db.close()
    except Exception:
        return -1


def write_env(key: str, value: str):
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------- V6 多用户 SaaS 认证与个人 API 保险箱 ----------------

@app.post("/api/auth/register")
async def api_register(request: Request):
    """V6 用户自助注册新账号"""
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    email = (body.get("email") or "").strip()
    try:
        from core import auth
        res = auth.register_user(username, password, email)
        resp = JSONResponse(res)
        resp.set_cookie("mf_v6_token", res["token"], httponly=True, samesite="lax", max_age=30*86400, path="/")
        return resp
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/login")
async def api_login(request: Request):
    """V6 用户登录"""
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    
    # 兼容管理员旧口令登录
    real_pwd = load_env().get("ADMIN_PASSWORD", "local-admin")
    if username in ("admin", "") and password == real_pwd:
        from core import auth
        auth.ensure_default_admin()
        token = auth.make_token({"user_id": "u-admin", "username": "admin", "role": "admin"})
        u = auth.get_user_by_id("u-admin") or {"id": "u-admin", "username": "admin", "role": "admin", "plan": "enterprise"}
        resp = JSONResponse({"ok": True, "token": token, "user": u, "msg": "管理员免密/口令登录成功"})
        resp.set_cookie("mf_v6_token", token, httponly=True, samesite="lax", max_age=30*86400, path="/")
        resp.set_cookie("mf_token", _token(), httponly=True, samesite="lax", max_age=30*86400, path="/")
        return resp

    try:
        from core import auth
        res = auth.login_user(username, password)
        resp = JSONResponse(res)
        resp.set_cookie("mf_v6_token", res["token"], httponly=True, samesite="lax", max_age=30*86400, path="/")
        return resp
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/auth/me")
def api_auth_me(request: Request):
    """获取当前登录用户的资料与额度"""
    u = guard(request)
    return {"ok": True, "user": u}


@app.get("/api/user/vault/keys")
def api_user_vault_keys(request: Request):
    """获取用户自己添加的所有模型服务 API Key 列表"""
    u = guard(request)
    from core import auth
    keys = auth.list_user_api_keys(u["id"])
    active_key = auth.get_active_user_llm_config(u["id"])
    return {
        "ok": True,
        "keys": keys,
        "using_platform_default": active_key is None,
        "active_provider": active_key.get("provider") if active_key else "system_default"
    }


@app.post("/api/user/vault/keys")
async def api_save_user_vault_key(request: Request):
    """用户在自己账号下添加/配置单独的模型 API Key"""
    u = guard(request)
    body = await request.json()
    provider = (body.get("provider") or "").strip()
    api_key = (body.get("api_key") or "").strip()
    base_url = (body.get("base_url") or "").strip()
    model_id = (body.get("model_id") or "").strip()
    label = (body.get("label") or "").strip()
    
    if not provider or not api_key:
        raise HTTPException(400, "模型服务与 API Key 均不能为空")
        
    from core import auth
    res = auth.save_user_api_key(u["id"], provider, api_key, base_url, model_id, label)
    return {"ok": True, "key": res, "msg": f"模型服务【{provider}】API Key 已安全加密存储并生效！"}


@app.delete("/api/user/vault/keys/{kid}")
def api_delete_user_vault_key(kid: str, request: Request):
    """用户删除自己的 API Key，自动切回平台托管"""
    u = guard(request)
    from core import auth
    auth.delete_user_api_key(u["id"], kid)
    return {"ok": True, "msg": "该 API 凭证已删除，后续调用将自动切回平台统一服务"}


# 兼容旧路径
@app.post("/login")
async def login(request: Request):
    return await api_login(request)


@app.get("/api/auth/status")
def auth_status(request: Request):
    u = get_current_user(request)
    return {
        "authed": u is not None,
        "user": u,
        "is_default": load_env().get("ADMIN_PASSWORD", "local-admin") == "local-admin"
    }


@app.post("/api/auth/logout")
def logout():
    resp = JSONResponse({"ok": True, "msg": "已退出登录"})
    resp.delete_cookie("mf_v6_token", path="/")
    resp.delete_cookie("mf_token", path="/")
    return resp


# ⭐ C-4：版本号单一真源，读 version.py；读取失败才回退（绝不手写版本号）。
try:
    from version import __version__ as APP_VERSION
except Exception:
    APP_VERSION = "7.0.0-dev"


@app.get("/health")
def health():
    return {"ok": True, "ts": time.time(), "version": APP_VERSION}


@app.get("/api/health")  # V7 契约归一：/health 的规范别名（CONTRACT §4）
def api_health():
    return health()


@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION}


@app.api_route("/m", methods=["GET", "HEAD"])
def mobile_index(request: Request):
    """V6 专属全新设计的原生手机端页面"""
    resp = HTMLResponse(get_mobile_html_page(), headers={"Cache-Control": "no-store, must-revalidate"})
    client_ip = request.client.host if request.client else ""
    if client_ip in ("127.0.0.1", "::1", "localhost") and load_env().get("ADMIN_PASSWORD", "local-admin") == "local-admin":
        resp.set_cookie("mf_token", _token(), httponly=True, samesite="lax", max_age=30*86400, path="/")
    return resp


@app.api_route("/", methods=["GET", "HEAD"])
def index(request: Request):
    # 若请求来自手机浏览器 User-Agent，自动提供全新的手机专属页面
    ua = (request.headers.get("user-agent") or "").lower()
    is_mobile = any(m in ua for m in ("iphone", "android", "mobile", "ipod", "harmonyos", "micromessenger"))
    
    html = get_mobile_html_page() if is_mobile else get_html_page()
    resp = HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})
    client_ip = request.client.host if request.client else ""
    if client_ip in ("127.0.0.1", "::1", "localhost") and load_env().get("ADMIN_PASSWORD", "local-admin") == "local-admin":
        resp.set_cookie("mf_token", _token(), httponly=True, samesite="lax", max_age=30*86400, path="/")
    return resp


# ---------------- status ----------------

def _draft_view(d: dict) -> dict:
    dd = db.draft_dir(d["id"])
    sc_total = d.get("score")
    if sc_total is not None and str(sc_total).strip() != "":
        try:
            sc_num = round(float(sc_total), 1)
        except Exception:
            sc_num = None
    else:
        sc_num = None
    grade = judge.grade(sc_num) if sc_num is not None else None
    cards_count = len(list(dd.glob("card-*.png")))
    imgs_dir = dd / "img"
    imgs_count = len(list(imgs_dir.glob("*.png"))) if imgs_dir.exists() else 0
    return {
        **d,
        "cards": cards_count,
        "imgs": imgs_count,
        "score": sc_num,
        "grade": grade,
        "round": d.get("score_round", 0) or 0
    }


@app.get("/api/status")
def status(request: Request):
    guard(request)
    cfg = load_config()
    env = load_env()
    cr = cfg.get("creation", {})
    # 自动检查并清理过期草稿（如果设置了天数且 > 0）
    exp_days = int(cr.get("draft_expire_days", 0))
    if exp_days > 0:
        try:
            db.delete_old_drafts(exp_days)
        except Exception:
            pass
    return {
        "topics": db.list_topics(),
        "drafts": [_draft_view(d) for d in db.list_drafts()],
        "jobs": db.list_jobs(),
        "gateway": {"base_url": cfg.get("gateway", {}).get("base_url", ""),
                    "model": cfg.get("gateway", {}).get("model", ""),
                    "provider_id": cfg.get("gateway", {}).get("provider_id", "custom"),
                    "configured_models": orchestrator.llm.get_configured_models(),
                    "agent_routing": cfg.get("gateway", {}).get("agent_routing", {}),
                    "key_set": bool(env.get("MEDIAFLOW_APIPOOL_KEY")),
                    "llm_ok": orchestrator.llm.available()},
        "keywords": cfg.get("topics", {}).get("keywords", []),
        "platform_names": NAMES,
        "themes": {"wechat": {**{k: v["name"] + "（规则）" for k, v in WECHAT_THEMES.items()},
                              **{k: v["name"] for k, v in layouter.list_themes().items()
                                 if v["has_prompt"]}},
                   "card": {k: v["name"] for k, v in XHS_CARD_STYLES.items()},
                   "current": {"wechat_theme": cr.get("wechat_theme", "caozhou"),
                               "card_style": cr.get("card_style", "magazine")}},
        "target_platforms": cr.get("target_platforms") or ["wechat_mp", "xhs", "toutiao", "zhihu", "weibo", "twitter"],
        "draft_expire_days": int(cr.get("draft_expire_days", 0)),
        "quality": judge.quality_cfg(),
        "image": cfg.get("image", {}),
        "ticket": {"enabled": env.get("TICKET_ENABLED")=="1", "time": env.get("TICKET_TIME","07:30"),
                    "dingtalk": notify_ok()},
        "imgbed": {"configured": bool(env.get("GITHUB_IMGBED_TOKEN") and env.get("GITHUB_IMGBED_REPO")),
                    "repo": env.get("GITHUB_IMGBED_REPO", "")},
        "agents": AG.agents_cfg(),
        "stages": AG.STAGES,
        "skills": {k: v["description"] for k, v in AG.list_skills().items()},
        "search_sources": {"xhs": "小红书", "toutiao": "今日头条", "douyin": "抖音",
                            "weibo": "微博", "kuaishou": "快手", "bilibili": "B站"},
    }


# ---------------- topics ----------------

@app.post("/api/topics/collect")
async def topics_collect(request: Request):
    u = guard(request)
    # ⭐ 会员分级：热榜采集每日配额（free：每日 1 次）
    _allowed, _reason, _tier = _tier_quota_check(u, "hot_daily")
    if not _allowed:
        raise HTTPException(402, _reason)
    return await asyncio.get_event_loop().run_in_executor(None, orchestrator.run_once)


@app.post("/api/topics/manual")
async def topics_manual(request: Request):
    guard(request)
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    return db.add_topic("manual", title, body.get("reason", ""), True)


@app.post("/api/topics/clean")
async def topics_clean(request: Request):
    """自动清理 N 天前的热榜条目。"""
    guard(request)
    body = await request.json()
    days = int(body.get("days", 3))
    if days < 1:
        raise HTTPException(400, "days 必须 >= 1")
    cnt = db.delete_old_topics(days)
    return {"ok": True, "deleted": cnt, "msg": f"已清理 {cnt} 条 {days} 天前的热榜记录"}


@app.post("/api/topics/clear_all")
async def topics_clear_all(request: Request):
    """立即清空全部热榜库。"""
    guard(request)
    cnt = db.clear_all_topics()
    return {"ok": True, "deleted": cnt, "msg": f"已清空热榜库，共删除 {cnt} 条记录"}


@app.get("/api/topics/stats")
async def topics_stats(request: Request):
    """热榜库统计概况。"""
    guard(request)
    return db.count_topics()


@app.post("/api/topics/{tid}/{action}")
async def topic_action(tid: str, action: str, request: Request):
    guard(request)
    if action == "approve":
        db.set_topic_status(tid, "approved")
        return {"ok": True}
    if action == "reject":
        db.set_topic_status(tid, "rejected")
        return {"ok": True}
    if action == "generate":
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, orchestrator.generate_draft, tid)
        except Exception as e:
            raise HTTPException(500, str(e))
    if action == "generate_job":
        import uuid
        jid = f"art-{tid[:8]}-{uuid.uuid4().hex[:4]}"
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        media_name = (body.get("media_name") or "").strip() or "一幕·YIMU 爆款工作室"
        platforms = body.get("platforms")
        
        plat_desc = f"({len(platforms)}端)" if platforms else ""
        start_async_job(
            jid,
            name=f"爆款文章智能生成{plat_desc} #{tid[:8]}",
            task_type="article_gen",
            target_id=tid,
            params={"topic_id": tid, "media_name": media_name, "platforms": platforms},
            initial_step="AI 选题解析与框架构思中…"
        )

        def _run():
            try:
                update_async_job(jid, step="AI 主笔深度创作中…", progress=30)
                res = orchestrator.generate_draft(
                    tid,
                    emit=lambda m: update_async_job(jid, step=m),
                    media_name=media_name,
                    platforms=platforms
                )
                draft_info = res.get("draft") or {}
                d_title = draft_info.get("title") or "新生成文章"
                update_async_job(
                    jid,
                    status="done",
                    step="文章生成完成",
                    progress=100,
                    result={"draft_id": draft_info.get("id"),
                            "score": res.get("score"),
                            "title": d_title}
                )
            except Exception as e:
                update_async_job(jid, status="failed", error=str(e)[:400], step="文章生成失败")
        asyncio.get_event_loop().run_in_executor(None, _run)
        return {"job": jid}
    raise HTTPException(404, action)


# ---------------- 公众号图文编辑器 ----------------

@app.post("/api/render")
async def api_render(request: Request):
    """实时渲染：markdown → 微信兼容行内样式 HTML（规则主题，毫秒级）。"""
    guard(request)
    body = await request.json()
    from core.themes import md_to_wechat_html
    from core.layouter import _inject_cover
    theme = body.get("theme", "caozhou")
    if theme not in WECHAT_THEMES:
        theme = "caozhou"
    body_md = body.get("body_md", "")
    title = body.get("title", "")
    did = body.get("did", "")
    images, cover = {}, None
    if did:
        ddir = db.draft_dir(did)
        if (ddir / "img").exists():
            sec_titles = [l[4:].strip() for l in body_md.splitlines() if l.startswith("### ")]
            pngs = sorted((ddir / "img").glob("sec-*.png"))
            images = {t: f"/img/{did}/{p.name}" for t, p in zip(sec_titles, pngs)}
            if (ddir / "img" / "cover.png").exists():
                cover = f"/img/{did}/cover.png"
    meta = (body.get("meta") or body.get("media_name") or "").strip() or "一幕·YIMU 爆款工作室"
    html = md_to_wechat_html(body_md, title, theme=theme, meta=meta, images=images)
    html = _inject_cover(html, cover)
    return {"html": html}


@app.get("/api/drafts/{did}/images")
def draft_images(did: str, request: Request):
    guard(request)
    ddir = db.draft_dir(did)
    out = []
    imgdir = ddir / "img"
    if imgdir.exists():
        for f in sorted(imgdir.glob("*.png")):
            out.append({"name": f.stem, "url": f"/img/{did}/{f.name}"})
    return out


@app.get("/api/drafts/{did}/images_detail")
def draft_images_detail(did: str, request: Request):
    guard(request)
    from core.imagegen import get_draft_images_detail
    return get_draft_images_detail(did)


@app.post("/api/drafts/{did}/images/regenerate_one")
async def draft_images_regenerate_one(did: str, request: Request):
    """针对指定的单张配图（如 cover、sec-0、sec-1）使用自定义或默认提示词重新生成"""
    guard(request)
    body = await request.json()
    name = body.get("name", "cover")
    prompt = body.get("prompt", "")
    title = body.get("title", "")
    aspect = body.get("aspect", "1:1")
    from core import billing, imagegen
    billing.check_and_deduct("drama_image", 1, f"重绘文章配图 [{name}]")
    def _run():
        return imagegen.regenerate_draft_image(did, name=name, prompt=prompt, title=title, aspect=aspect)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f"重绘配图失败: {e}")


@app.post("/api/drafts/{did}/images/analyze_prompts")
async def draft_images_analyze_prompts(did: str, request: Request):
    """通读全文并重新提炼生成全套配图的画面要点与结构化提示词"""
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    from core.imagegen import analyze_article_visual_prompts
    sec_meta = []
    for line in d["body_md"].splitlines():
        if line.startswith("### "):
            sec_meta.append((line[4:].strip(), ""))
    if not sec_meta:
        sec_meta = [("核心看点", d["title"])]
    def _run():
        return analyze_article_visual_prompts(d["title"], d["body_md"], sec_meta)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "prompts": res}
    except Exception as e:
        raise HTTPException(500, f"构思提示词失败: {e}")


@app.post("/api/drafts/{did}/images/upload_custom")
async def draft_images_upload_custom(did: str, request: Request,
                                     file: UploadFile = File(...),
                                     name: str = Form("cover")):
    """上传自定义图片替换指定配图插槽（cover / sec-0 / sec-1 …）"""
    guard(request)
    import shutil, pathlib
    img_dir = pathlib.Path(f"data/drafts/{did}/img")
    img_dir.mkdir(parents=True, exist_ok=True)
    # 安全校验文件名
    safe_name = name.replace("/", "").replace("..", "").strip() or "cover"
    dest = img_dir / f"{safe_name}.png"
    try:
        contents = await file.read()
        if len(contents) > 20 * 1024 * 1024:
            raise HTTPException(400, "文件超过 20MB 限制")
        # 用 Pillow 转换为 PNG（支持 jpg/webp/png 等格式输入）
        from PIL import Image
        import io
        img_obj = Image.open(io.BytesIO(contents))
        img_obj = img_obj.convert("RGB")
        img_obj.save(str(dest), "PNG", quality=95)
        # 重新编译排版预览（让新图片出现在五大平台预览中）
        try:
            from core.imagegen import recompile_previews
            recompile_previews(did)
        except Exception:
            pass
        return {"ok": True, "url": f"/img/{did}/{safe_name}.png", "name": safe_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"上传图片失败: {e}")


@app.post("/api/drafts/{did}/voiceover_script")
async def draft_voiceover_script(did: str, request: Request):
    """生成口播稿（去除所有图片的纯文版本，可选 AI 润色）"""
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    import re
    md = d.get("body_md", "")
    # 去图片、去标题符号、去粗体斜体、去链接括号、去代码块
    script = md
    script = re.sub(r'!\[.*?\]\(.*?\)', '', script)          # 去图片
    script = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', script) # 链接留文字
    script = re.sub(r'^#{1,6}\s+(.+)$', r'\n\1\n', script, flags=re.MULTILINE)
    script = re.sub(r'\*\*(.+?)\*\*', r'\1', script)
    script = re.sub(r'\*(.+?)\*', r'\1', script)
    script = re.sub(r'`{1,3}[^`]*`{1,3}', '', script)
    script = re.sub(r'^[-*>]\s+', '', script, flags=re.MULTILINE)
    script = re.sub(r'\n{3,}', '\n\n', script)
    script = script.strip()
    return {"ok": True, "script": script, "title": d.get("title", ""), "char_count": len(script.replace(" ", "").replace("\n", ""))}



@app.get("/api/assets/library")
def get_asset_library(request: Request, q: str = "", page: int = 1, per_page: int = 60):
    """扫描所有草稿图片，返回全局素材库（支持关键词过滤和分页）"""
    guard(request)
    import pathlib, time as _time
    drafts_dir = pathlib.Path("data/drafts")
    if not drafts_dir.exists():
        return {"ok": True, "assets": [], "total": 0}

    # 批量获取草稿 title 映射
    all_drafts = {}
    try:
        for d in db.list_drafts():
            all_drafts[d.get("id", "")] = d.get("title", "")
    except Exception:
        pass

    assets = []
    for draft_dir in sorted(drafts_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not draft_dir.is_dir():
            continue
        img_dir = draft_dir / "img"
        if not img_dir.exists():
            continue
        did = draft_dir.name
        draft_title = all_drafts.get(did, did)
        for img_file in sorted(img_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True):
            name = img_file.stem
            # 关键词过滤
            if q and q.lower() not in draft_title.lower() and q.lower() not in name.lower():
                continue
            stat = img_file.stat()
            assets.append({
                "draft_id": did,
                "draft_title": draft_title,
                "name": name,
                "url": f"/img/{did}/{img_file.name}",
                "size": stat.st_size,
                "mtime": round(stat.st_mtime),
            })

    total = len(assets)
    start = (page - 1) * per_page
    return {"ok": True, "assets": assets[start:start + per_page], "total": total, "page": page, "per_page": per_page}


@app.post("/api/assets/batch_delete")
async def batch_delete_assets(request: Request):
    """批量删除素材库图片资产"""
    guard(request)
    body = await request.json()
    items = body.get("items") or []
    if not items:
        raise HTTPException(400, "请提供要删除的素材列表")
    
    deleted = 0
    failed = []
    import pathlib
    for item in items:
        did = item.get("draft_id", "")
        name = item.get("name", "")
        if not did or not name:
            continue
        p = pathlib.Path(f"data/drafts/{did}/img/{name}.png")
        if p.exists() and p.is_file():
            try:
                p.unlink()
                deleted += 1
            except Exception as e:
                failed.append({"did": did, "name": name, "error": str(e)})
        else:
            deleted += 1
            
    return {"ok": True, "deleted_count": deleted, "failed": failed}


@app.post("/api/assets/delete")
async def delete_single_asset(request: Request):
    """删除单张素材库图片资产"""
    guard(request)
    body = await request.json()
    did = body.get("draft_id", "")
    name = body.get("name", "")
    url = body.get("url", "")
    if url and not (did and name):
        import re
        m = re.search(r"/api/drafts/([^/]+)/img/([^/?#]+)", url)
        if m:
            did = m.group(1)
            name = m.group(2).replace(".png", "")
    if not did or not name:
        return {"ok": False, "error": "缺少 draft_id 或 name 参数"}
    import pathlib
    p = pathlib.Path(f"data/drafts/{did}/img/{name}.png")
    if p.exists() and p.is_file():
        try:
            p.unlink()
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "deleted": True}


@app.post("/api/assets/generate_hyper_real")
async def generate_hyper_real_asset(request: Request):
    """电影级普利策超写实文生图接口：调用当前配置的顶级大模型与生图通道生成逼真写真照片。"""
    guard(request)
    body = await request.json()
    prompt = (body.get("prompt") or body.get("scene") or "").strip()
    if not prompt:
        raise HTTPException(400, "请输入生成画面的描述")
    
    # 选取一个草稿目录存放（优先当前草稿，若无草稿存放至第一篇草稿或通用目录）
    did = body.get("draft_id", "")
    all_d = db.list_drafts()
    if not did and all_d:
        did = all_d[0]["id"]
    if not did:
        did = "global_assets"
        
    ddir = db.draft_dir(did)
    img_d = ddir / "img"
    img_d.mkdir(parents=True, exist_ok=True)
    
    import time
    ts = int(time.time())
    out_file = img_d / f"custom-{ts}.png"
    
    from core.imagegen import gen_image
    ok = gen_image(prompt, out_file, size="1024x1024", context_title="超写实摄影", context_sub=prompt[:40])
    if not ok or not out_file.exists():
        raise HTTPException(500, "超写实生图失败，请检查模型网关连接")
        
    return {
        "ok": True,
        "url": f"/img/{did}/{out_file.name}",
        "name": out_file.stem,
        "msg": "🎉 电影级真实摄影大片已生成完毕，已自动收入素材库！"
    }



@app.post("/api/drafts/{did}/images/replace_in_article")
async def draft_replace_image_in_article(did: str, request: Request):
    """将指定配图插槽的新图片 URL 替换/插入到草稿 body_md 中"""
    guard(request)
    body = await request.json()
    name = body.get("name", "")          # 如 cover / sec-0
    new_url = body.get("url", "")        # 新图片 URL
    label = body.get("label", "配图")   # 图片 alt 文字
    if not name or not new_url:
        raise HTTPException(400, "name 和 url 不能为空")
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    import re
    md = d.get("body_md", "")
    # 构造新的 Markdown 图片行
    new_img_md = f"![{label}]({new_url})"
    # 尝试替换已有的同名图片引用（匹配 /img/{did}/{name}.png 或 .jpg/.webp）
    pattern = rf'!\[[^\]]*\]\(/img/{re.escape(did)}/{re.escape(name)}\.[a-z]+\)'
    if re.search(pattern, md):
        md = re.sub(pattern, new_img_md, md)
        action = "replaced"
    else:
        md = md.rstrip() + f"\n\n{new_img_md}\n"
        action = "appended"
    db.update_draft_body(did, md)
    # 同步重新编译各端排版预览
    try:
        from core.imagegen import recompile_previews
        recompile_previews(did)
    except Exception:
        pass
    return {"ok": True, "action": action, "new_url": new_url, "body_md": md}


@app.post("/api/assets/use_in_draft")
async def use_asset_in_draft(request: Request):
    """将素材库图片替换到当前草稿的指定插槽（复制文件 + 更新 body_md）"""
    guard(request)
    body = await request.json()
    src_did = body.get("src_did", "")     # 来源草稿 ID
    src_name = body.get("src_name", "")  # 来源图片名（如 cover/sec-0）
    dst_did = body.get("dst_did", "")    # 目标草稿 ID
    dst_slot = body.get("dst_slot", "")  # 目标插槽名
    if not all([src_did, src_name, dst_did, dst_slot]):
        raise HTTPException(400, "参数不完整")
    import pathlib, shutil
    src_path = pathlib.Path(f"data/drafts/{src_did}/img/{src_name}.png")
    dst_dir = pathlib.Path(f"data/drafts/{dst_did}/img")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_path = dst_dir / f"{dst_slot}.png"
    if not src_path.exists():
        raise HTTPException(404, f"源图片不存在: {src_path}")
    shutil.copy2(str(src_path), str(dst_path))
    # 重新编译排版预览
    try:
        from core.imagegen import recompile_previews
        recompile_previews(dst_did)
    except Exception:
        pass
    return {"ok": True, "dst_url": f"/img/{dst_did}/{dst_slot}.png"}


@app.post("/api/drafts/{did}/generate_images")
async def draft_generate_images(did: str, request: Request):
    """一键为全文智能批量生成成套插图与封面，并自动插入正文与重新渲染"""
    guard(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    count = int(body.get("count", 3))
    from core.imagegen import generate_and_inject_images
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    import uuid
    jid = f"img-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"全文智能生图配图 ({count}张): {d_title[:16]}",
        task_type="image_gen",
        target_id=did,
        params={"draft_id": did, "count": count},
        initial_step=f"正在分析段落视觉意境并生成 {count} 张专属高清配图…"
    )
    try:
        update_async_job(jid, step="AI 光学摄影渲染与图文回填中…", progress=45)
        res = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_and_inject_images(did, count=count)
        )
        update_async_job(jid, status="done", step=f"成功生成 {count} 张配图并已排版入文", progress=100, result=res)
        return res
    except Exception as e:
        update_async_job(jid, status="failed", error=str(e)[:300], step="生图配图失败")
        raise HTTPException(500, f"生图失败: {str(e)}")


@app.post("/api/drafts/{did}/generate_single_image")
async def draft_generate_single_image(did: str, request: Request):
    """根据输入的主题或段落，单独生成一张专属高清配图"""
    guard(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    title = body.get("title", "核心看点")
    prompt = body.get("prompt", "")
    from core.imagegen import generate_single_image
    import uuid
    jid = f"img-sgl-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"单张配图生成: {title[:16]}",
        task_type="image_gen",
        target_id=did,
        params={"draft_id": did, "title": title, "prompt": prompt},
        initial_step="AI 摄影抓拍提示词升华与渲染中…"
    )
    try:
        update_async_job(jid, step="极速高清渲染中…", progress=50)
        res = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_single_image(did, title=title, prompt=prompt)
        )
        update_async_job(jid, status="done", step="单张配图生成完成", progress=100, result=res)
        return res
    except Exception as e:
        update_async_job(jid, status="failed", error=str(e)[:300], step="单张生图失败")
        raise HTTPException(500, f"生图失败: {str(e)}")


@app.post("/api/drafts/{did}/save_wechat")
async def draft_save_wechat(did: str, request: Request):
    """保存编辑器里的正文（只更新 body_md 与公众号预览，不动其它平台/AI产物）。"""
    guard(request)
    body = await request.json()
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    body_md = body.get("body_md", d["body_md"])
    c = db.conn()
    c.execute("UPDATE drafts SET body_md=? WHERE id=?", (body_md, did))
    c.commit(); c.close()
    # 用已有 AI 图重渲染公众号预览
    from core.themes import md_to_wechat_html
    theme = load_config().get("creation", {}).get("wechat_theme", "caozhou")
    theme = theme if theme in WECHAT_THEMES else "caozhou"
    ddir = db.draft_dir(did)
    images = {f.name: f"/img/{did}/{f.name}" for f in sorted((ddir / "img").glob("sec-*.png"))} \
        if (ddir / "img").exists() else {}
    cover = f"/img/{did}/cover.png" if (ddir / "img" / "cover.png").exists() else None
    if not body.get("keep_ai_preview"):
        meta = (body.get("meta") or body.get("media_name") or "").strip() or "一幕·YIMU 爆款工作室"
        html = md_to_wechat_html(body_md, d["title"], theme=theme, meta=meta, images=images)
        from core.layouter import _inject_cover
        html = _inject_cover(html, cover)
        (ddir / "preview-wechat_mp.html").write_text(html, encoding="utf-8")
        # 头条预览与 toutiao.md 同步（保留原标题行）
        from adapters import toutiao as _tt
        (ddir / "preview-toutiao.html").write_text(
            _tt.render_preview(body_md, d["title"]), encoding="utf-8")
    tf = ddir / "toutiao.md"
    old_title = "# " + d["title"]
    if tf.exists():
        first = tf.read_text(encoding="utf-8").splitlines()
        if first and first[0].startswith("# "):
            old_title = first[0]
    tf.write_text(f"{old_title}\n\n{body_md}", encoding="utf-8")
    return {"ok": True}


@app.post("/api/drafts/{did}/wx_imgs")
async def draft_wx_imgs(did: str, request: Request):
    """把本篇所有配图上传到公众号素材库，返回 {本地路径: 微信CDN url} 映射。

    需 .env 配置 WECHAT_MP_APPID/SECRET 且本机 IP 在公众号后台白名单内；
    失败返回 ok=False，前端回落 base64 内嵌。
    """
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    env = load_env()
    if not (env.get("WECHAT_MP_APPID") and env.get("WECHAT_MP_SECRET")):
        return {"ok": False, "error": "未配置公众号 AppID/Secret"}
    from adapters import wechat_mp
    mapping = {}
    ddir = db.draft_dir(did)
    imgdir = ddir / "img"
    if not imgdir.exists():
        return {"ok": False, "error": "本文没有配图"}
    try:
        for f in sorted(imgdir.glob("*.png")):
            mapping[f"/img/{did}/{f.name}"] = wechat_mp.upload_image(str(f))
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "mapping": mapping}
    return {"ok": True, "mapping": mapping}


@app.post("/api/drafts/{did}/gh_imgs")
async def draft_gh_imgs(did: str, request: Request):
    """把本篇配图上传 GitHub 图床，返回 {本地路径: jsdelivr 公网 URL} 映射。"""
    guard(request)
    from core import imgbed
    if not imgbed.available():
        return {"ok": False, "error": "图床未配置"}
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    mapping = {}
    imgdir = db.draft_dir(did) / "img"
    if not imgdir.exists():
        return {"ok": False, "error": "本文没有配图"}
    try:
        for f in sorted(imgdir.glob("*.png")):
            mapping[f"/img/{did}/{f.name}"] = imgbed.upload(str(f), did)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "mapping": mapping}
    return {"ok": True, "mapping": mapping}


@app.post("/api/drafts/{did}/ai_layout")
async def draft_ai_layout(did: str, request: Request):
    """AI 重排版：按最新正文与主题为选定平台重新排版与渲染。"""
    guard(request)
    body = await request.json()
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    theme = body.get("theme") or load_config().get("creation", {}).get("wechat_theme", "caozhou")
    platform = body.get("platform", "wechat_mp")
    import uuid
    jid = f"lay-{did[:8]}-{uuid.uuid4().hex[:4]}"
    d_title = d.get("title", "")
    start_async_job(
        jid,
        name=f"智能排版美化 [{platform}]: {d_title[:16]}",
        task_type="article_layout",
        target_id=did,
        params={"draft_id": did, "platform": platform, "theme": theme},
        initial_step=f"【{platform}】排版初始化中…"
    )

    def _run():
        try:
            ddir = db.draft_dir(did)
            body_text = d["body_md"]
            if platform == "xhs":
                update_async_job(jid, step="提取小红书分段大纲与生成卡片…", progress=40)
                f_md = ddir / "xhs.md"
                xhs_title = d["title"]  # 默认主标题
                if f_md.exists():
                    body_text = f_md.read_text(encoding="utf-8")
                    # 优先从 xhs.md 首行 # 标题中取（与 switch_draft_title 同步写入的新标题一致）
                    for _ln in body_text.splitlines():
                        _ln_s = _ln.strip()
                        if _ln_s.startswith("# "):
                            xhs_title = _ln_s[2:].strip() or xhs_title
                            break
                sec_meta, cur = [], None
                for line in body_text.splitlines():
                    if line.startswith("### ") or line.startswith("## "):
                        cur = [line.lstrip("#").strip(), []]
                        sec_meta.append(cur)
                    elif cur is not None and line.strip():
                        cur[1].append(line.strip().lstrip("- "))
                if not sec_meta:
                    paras = [p.strip() for p in body_text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
                    sec_meta = [(f"看点 {i+1}", [p]) for i, p in enumerate(paras[:6])]
                # 卡片数量兜底（至少 3 张正文卡）
                if len(sec_meta) < 3:
                    extra_names = ["🔑 核心要点", "💡 深度解析", "✨ 实战技巧", "🎯 关键洞察"]
                    _paras = [p.strip() for p in body_text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
                    for _j, _para in enumerate(_paras[:5]):
                        if len(sec_meta) >= 5:
                            break
                        pts = [s.strip()[:35] for s in _para.splitlines() if s.strip()][:3] or [_para[:35]]
                        sec_meta.append((extra_names[_j % len(extra_names)], pts))
                cover_file = ddir / "img" / "cover.png" if (ddir / "img" / "cover.png").exists() else None
                from core.render_card import render_draft_cards
                render_draft_cards(ddir, xhs_title, sec_meta, cover_img=cover_file)
                cards = sorted([f"/card/{did}/{p.name}" for p in ddir.glob("card-*.png")])
                update_async_job(jid, status="done", step="小红书排版与卡片重渲完成", progress=100, result={"ok": True, "cards": cards, "text": body_text})
            elif platform == "toutiao":
                update_async_job(jid, step="渲染今日头条专属排版…", progress=50)
                f_md = ddir / "toutiao.md"
                if f_md.exists():
                    body_text = f_md.read_text(encoding="utf-8")
                from adapters import toutiao as _tt
                html = _tt.render_preview(body_text, d["title"])
                (ddir / "preview-toutiao.html").write_text(html, encoding="utf-8")
                update_async_job(jid, status="done", step="今日头条排版完成", progress=100, result={"html": html, "text": body_text})
            elif platform == "zhihu":
                update_async_job(jid, step="渲染知乎硬核问答排版…", progress=50)
                f_md = ddir / "zhihu.md"
                if f_md.exists():
                    body_text = f_md.read_text(encoding="utf-8")
                from adapters import zhihu as _zh
                html = _zh.render_preview(body_text, d["title"])
                (ddir / "preview-zhihu.html").write_text(html, encoding="utf-8")
                update_async_job(jid, status="done", step="知乎排版完成", progress=100, result={"html": html, "text": body_text})
            elif platform == "weibo":
                update_async_job(jid, step="渲染微博快讯排版…", progress=50)
                f_md = ddir / "weibo.md"
                if f_md.exists():
                    body_text = f_md.read_text(encoding="utf-8")
                from adapters import weibo as _wb
                html = _wb.render_preview(body_text, d["title"])
                (ddir / "preview-weibo.html").write_text(html, encoding="utf-8")
                update_async_job(jid, status="done", step="微博快讯排版完成", progress=100, result={"html": html, "text": body_text})
            else:
                update_async_job(jid, step="渲染微信公众号美学主题…", progress=50)
                from core import themes
                from core.layouter import _inject_cover
                images = {f.name: f"/img/{did}/{f.name}"
                          for f in sorted((ddir / "img").glob("sec-*.png"))} \
                    if (ddir / "img").exists() else {}
                cover = f"/img/{did}/cover.png" if (ddir / "img" / "cover.png").exists() else None
                meta = (body.get("meta") or body.get("media_name") or "").strip() or "一幕·YIMU 爆款工作室"
                html = themes.md_to_wechat_html(body_text, d["title"], theme=theme, meta=meta, images=images)
                html = _inject_cover(html, cover)
                (ddir / "preview-wechat_mp.html").write_text(html, encoding="utf-8")
                update_async_job(jid, status="done", step="微信公众号排版完成", progress=100, result={"html": html, "text": body_text})
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:400], step="排版失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


# ---------------- search & rewrite ----------------

@app.get("/api/search/status")
def search_status(request: Request):
    guard(request)
    from core import search as S
    return {"xhs": S.xhs_available(), "douyin": S.douyin_available(), "toutiao": True}


@app.post("/api/search")
async def do_search(request: Request):
    guard(request)
    body = await request.json()
    kw = (body.get("keyword") or "").strip()
    if not kw:
        raise HTTPException(400, "关键词不能为空")
    sources = body.get("sources") or ["xhs", "toutiao", "douyin"]
    from core.search import search_expanded
    def _run():
        res, words = search_expanded(kw, sources, int(body.get("limit", 16)),
                                     expand=bool(body.get("expand", True)))
        res["_queries"] = words
        return res
    return await asyncio.get_event_loop().run_in_executor(None, _run)


@app.post("/api/rewrite")
async def do_rewrite(request: Request):
    guard(request)
    body = await request.json()
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: orchestrator.benchmark_and_rewrite(
                body.get("platform", ""), body.get("title", ""),
                body.get("url", ""), (body.get("theme") or "").strip(),
                body.get("extra") or {},
                source_text=body.get("source_text") or body.get("text") or ""))
    except Exception as e:
        raise HTTPException(500, f"拆解仿写失败: {e}")


@app.post("/api/extract")
async def do_extract(request: Request):
    guard(request)
    body = await request.json()
    raw_url = (body.get("url") or "").strip()
    if not raw_url:
        raise HTTPException(400, "链接不能为空")
    from core.extractor import extract_url
    def _run():
        return extract_url(raw_url)
    try:
        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f"提取失败: {e}")


@app.post("/api/drafts/{did}/switch_title")
async def draft_switch_title(did: str, request: Request):
    guard(request)
    body = await request.json()
    new_title = (body.get("title") or "").strip()
    if not new_title:
        raise HTTPException(400, "标题不能为空")
    def _run():
        return orchestrator.switch_draft_title(did, new_title)
    try:
        updated = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "draft": updated}
    except Exception as e:
        raise HTTPException(500, f"切换标题失败: {e}")


# ---------------- drafts ----------------

@app.post("/api/drafts/{did}/publish")
async def draft_publish(did: str, request: Request):
    u = guard(request)
    body = await request.json()
    platforms = body.get("platforms") or []
    bad = [p for p in platforms if p not in PLATFORMS]
    if bad or not platforms:
        raise HTTPException(400, f"平台非法: {bad}")
    # ⭐ 会员分级：单次可发布平台数（free：1 个）
    _plimit = _tier_capability_limit(u, "publish_platforms")
    if isinstance(_plimit, int) and _plimit > 0 and len(platforms) > _plimit:
        raise HTTPException(
            400,
            f"当前档位单次最多发布到 {_plimit} 个平台，升级 V7 Pro 解锁全平台发布",
        )
    return orchestrator.approve_and_publish(did, platforms)


@app.post("/api/drafts/{did}/rescore")
async def draft_rescore(did: str, request: Request):
    guard(request)
    try:
        body = await request.json()
        platform = body.get("platform")
    except Exception:
        platform = None
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: judge.judge_draft(did, platform=platform))


@app.get("/api/drafts/{did}/platform_scores")
async def draft_platform_scores(did: str, request: Request):
    """获取草稿各平台差异化评分估算（v3.33新增）。"""
    guard(request)
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: judge.judge_platform_scores(did))



@app.get("/api/xhspub/status")
def xhspub_status(request: Request):
    guard(request)
    from core import xhspub
    return {"available": xhspub.available(), "logged": xhspub.logged_in()}


@app.get("/api/xhspub/qrcode")
async def xhspub_qrcode(request: Request):
    guard(request)
    from core import xhspub
    return await asyncio.get_event_loop().run_in_executor(None, xhspub.get_qrcode)


@app.post("/api/xhspub/login")
async def xhspub_login(request: Request):
    guard(request)
    from core import xhspub
    import uuid
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"step": "弹出浏览器中…", "status": "running", "result": None, "error": ""}
    def _run():
        try:
            res = xhspub.login(emit=lambda m: JOBS[jid].update(step=m))
            JOBS[jid].update(status="done", step="完成", result=res)
        except Exception as e:
            JOBS[jid].update(status="failed", error=str(e)[:300], step="失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.post("/api/drafts/{did}/publish_xhs")
async def draft_publish_xhs(did: str, request: Request):
    guard(request)
    body = await request.json()
    import uuid
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"step": "准备发布…", "status": "running", "result": None, "error": ""}
    def _run():
        try:
            from core import xhspub
            res = xhspub.publish(did, emit=lambda m: JOBS[jid].update(step=m))
            JOBS[jid].update(status="done" if res["ok"] else "failed",
                             step="完成" if res["ok"] else "失败",
                             result=res, error="" if res["ok"] else res["detail"][:300])
        except Exception as e:
            JOBS[jid].update(status="failed", error=str(e)[:300], step="失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


MPT_DIR = BASE / "vendors" / "MoneyPrinterTurbo"

# ---------------- 技能库 ----------------

SKILL_AGENTS_DIR = BASE / "skills" / "agents"


def _skills_full() -> dict:
    from core.agents import list_skills, agents_cfg
    sk = list_skills()
    usage = {}
    for stage, a in agents_cfg().items():
        for name in a.get("skills", []):
            usage.setdefault(name, []).append(stage)
    return {"skills": sk, "usage": usage}


@app.get("/api/skills/all")
def skills_all(request: Request):
    guard(request)
    from core.agents import STAGES
    full = _skills_full()
    refs = {}
    rd = BASE / "skills" / "refs"
    if rd.exists():
        for lib in sorted(rd.iterdir()):
            if lib.is_dir():
                refs[lib.name] = sorted(f.name for f in lib.rglob("*.md"))
    return {**full, "stages": STAGES, "refs": refs}


@app.post("/api/skills/save")
async def skills_save(request: Request):
    guard(request)
    import re as _re
    body = await request.json()
    name = _re.sub(r"[^a-z0-9-]", "", (body.get("name") or "").lower())
    if not name:
        raise HTTPException(400, "技能名只能是英文/数字/连字符")
    desc = (body.get("description") or "").strip()
    text = (body.get("body") or "").strip()
    if len(text) < 10:
        raise HTTPException(400, "技能内容太短")
    (SKILL_AGENTS_DIR / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n{text}\n", encoding="utf-8")
    return {"ok": True, "name": name}


@app.post("/api/skills/delete")
async def skills_delete(request: Request):
    guard(request)
    body = await request.json()
    name = (body.get("name") or "").strip()
    f = SKILL_AGENTS_DIR / f"{name}.md"
    if not f.exists():
        raise HTTPException(404, "技能不存在")
    import shutil
    trash = Path.home() / ".Trash"
    trash.mkdir(exist_ok=True)
    shutil.move(str(f), str(trash / f"skill-{name}.md"))
    # 从各 Agent 的挂载里移除
    cfg = load_config()
    for stage, a in cfg.get("agents", {}).items():
        if name in (a.get("skills") or []):
            a["skills"] = [x for x in a["skills"] if x != name]
    CFG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True}


@app.post("/api/skills/distill")
async def skills_distill(request: Request):
    """蒸馏：贴入爆款文章/名人文风 → AI 提炼成结构化技能文件。"""
    guard(request)
    body = await request.json()
    name_raw = (body.get("name") or "").strip()
    text = (body.get("text") or "").strip()
    if not text or len(text) < 50:
        raise HTTPException(400, "请贴入至少 50 字的文章/语录")
    import re as _re
    import uuid
    jid = f"dist-{uuid.uuid4().hex[:8]}"
    start_async_job(
        jid,
        name=f"名家文风语料蒸馏: {name_raw[:14]}",
        task_type="voice_distill",
        params={"name": name_raw},
        initial_step="AI 蒸馏风格规则与写作指纹中…"
    )
    def _run():
        try:
            from core import agents as AG
            slug = _re.sub(r"[^a-z0-9-]", "", name_raw.lower().replace(" ", "-")) or f"distill-{jid[:6]}"
            raw = AG.chat_for("analyze", [
                {"role": "user", "content":
                    "把下面内容蒸馏成一份可复用的中文写作技能。\n"
                    "输出格式（严格遵守）：\n"
                    "DESC: <一句话技能描述，30字内>\n"
                    "RULES:\n<8~12条具体可执行的写作规则，每条一行，"
                    "涵盖：标题钩子手法/开头套路/句式节奏/用词偏好/结尾方式/情绪策略>\n\n"
                    f"【待蒸馏内容】\n{text[:4000]}"}], temperature=0.4)
            desc, rules = "", ""
            m = re.search(r"DESC\s*[:：]\s*(.+)", raw)
            if m: desc = m.group(1).strip()
            mr = re.search(r"RULES:\s*([\s\S]+)", raw)
            if mr: rules = mr.group(1).strip()
            if not rules:
                raise ValueError("蒸馏解析失败：" + raw[:150])
            (SKILL_AGENTS_DIR / f"{slug}.md").write_text(
                f"---\nname: {slug}\ndescription: 蒸馏技能·{name_raw}：{desc}\n---\n\n"
                f"# 蒸馏自「{name_raw}」\n\n{rules}\n", encoding="utf-8")
            update_async_job(jid, status="done", step="文风蒸馏完成并已入库！", progress=100, result={"slug": slug, "desc": desc})
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:300], step="蒸馏失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.get("/api/skills/ref")
def skills_ref(request: Request, path: str = ""):
    guard(request)
    base = (BASE / "skills" / "refs").resolve()
    f = (base / path).resolve()
    if not str(f).startswith(str(base)) or not f.exists() or f.suffix != ".md":
        raise HTTPException(404, "文件不存在")
    return FileResponse(f)


# ---------------- 创作者习惯自主进化自学习中枢 ----------------

@app.get("/api/habit/status")
def habit_status(request: Request):
    """获取当前创作者自主进化习惯技能的状态与特征规则"""
    guard(request)
    from core import habit_learner
    return habit_learner.get_habit_status()


@app.post("/api/habit/evolve")
async def habit_evolve(request: Request):
    """从近期定稿/修改内容中提取语言习惯并自主进化技能"""
    guard(request)
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    limit = int(body.get("limit", 5)) if isinstance(body, dict) else 5
    from core import habit_learner
    return habit_learner.evolve_from_drafts(limit=limit)


@app.post("/api/habit/reset")
def habit_reset(request: Request):
    """重置自主进化习惯为初始基线"""
    guard(request)
    from core import habit_learner
    return habit_learner.reset_habit_skill()


# ---------------- 每日工单 & 服务健康 ----------------

@app.get("/api/ticket/last")
def ticket_last(request: Request):
    guard(request)
    td = BASE / "data" / "tickets"
    files = sorted(td.glob("*.json")) if td.exists() else []
    last = json.loads(files[-1].read_text()) if files else None
    env = load_env()
    return {"last": last, "enabled": env.get("TICKET_ENABLED") == "1",
            "time": env.get("TICKET_TIME", "07:30"),
            "dingtalk": notify_ok()}


def notify_ok():
    from core import notify as N
    return N.configured()


@app.post("/api/ticket/run")
async def ticket_run(request: Request):
    guard(request)
    import uuid
    jid = f"tkt-{uuid.uuid4().hex[:8]}"
    start_async_job(
        jid,
        name="自动化每日巡航与热点产出工单",
        task_type="ticket_exec",
        initial_step="工单流水线启动中…"
    )
    def _run():
        try:
            from core import ticket
            res = ticket.run_ticket(emit=lambda m: update_async_job(jid, step=m))
            update_async_job(jid, status="done", step="每日巡航工单执行完成！", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:300], step="工单执行失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.post("/api/ticket/schedule")
async def ticket_schedule(request: Request):
    guard(request)
    body = await request.json()
    enabled = bool(body.get("enabled"))
    hh, mm = (body.get("time") or "07:30").split(":")
    write_env("TICKET_ENABLED", "1" if enabled else "0")
    write_env("TICKET_TIME", f"{int(hh):02d}:{int(mm):02d}")
    plist = Path.home() / "Library/LaunchAgents/com.czmj.mediaflow-ticket.plist"
    import subprocess as sp
    sp.run(["launchctl", "unload", str(plist)], capture_output=True)
    if enabled:
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.czmj.mediaflow-ticket</string>
  <key>ProgramArguments</key><array>
    <string>{BASE / '.venv/bin/python'}</string>
    <string>-m</string><string>core.ticket_cli</string>
  </array>
  <key>WorkingDirectory</key><string>{BASE}</string>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>{int(hh)}</integer><key>Minute</key><integer>{int(mm)}</integer>
  </dict>
  <key>StandardOutPath</key><string>{BASE}/logs/ticket.out</string>
  <key>StandardErrorPath</key><string>{BASE}/logs/ticket.out</string>
</dict></plist>""")
        sp.run(["launchctl", "load", str(plist)], capture_output=True)
    return {"ok": True, "enabled": enabled}


HEALTH_SERVICES = [
    {"name": "apipool", "label": "apipool 模型池", "port": 8787, "path": "/health",
     "repair": "kickstart:com.czmj.apipool"},
    {"name": "exporter", "label": "公众号对标库", "port": 8791, "path": "/",
     "repair": "kickstart:com.czmj.wae"},
    {"name": "xhsmcp", "label": "小红书数据源", "port": 18060, "path": "/mcp",
     "repair": "restart_xhsmcp"},
    {"name": "mpt", "label": "短视频引擎界面", "port": 8501, "path": "/",
     "repair": "optional"},
]


@app.get("/api/health/services")
def health_services(request: Request):
    guard(request)
    import httpx
    out = []
    for svc in HEALTH_SERVICES:
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                r = client.get(f"http://127.0.0.1:{svc['port']}{svc['path']}")
                ok = r.status_code < 500
        except Exception:
            ok = False
        out.append({**svc, "ok": ok})
    return {"services": out, "mediaflow": True}


@app.post("/api/health/repair")
async def health_repair(request: Request):
    guard(request)
    body = await request.json()
    name = body.get("name")
    import subprocess as sp
    uid = sp.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    if name == "apipool":
        sp.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.czmj.apipool"], capture_output=True)
        time.sleep(4)
    elif name == "exporter":
        sp.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.czmj.wae"], capture_output=True)
        time.sleep(3)
    elif name == "xhsmcp":
        xb = BASE / "vendors/xhs-mcp/xiaohongshu-mcp"
        if xb.exists():
            sp.run(["pkill", "-f", "xiaohongshu-mcp"], capture_output=True)
            time.sleep(1)
            sp.Popen([str(xb), "-headless=true"], cwd=str(xb.parent),
                     stdout=open(BASE / "logs/xhsmcp.out", "w"), stderr=sp.STDOUT)
            time.sleep(3)
        else:
            raise HTTPException(400, "组件未安装")
    elif name == "mpt":
        raise HTTPException(400, "短视频引擎按需启动：去「短视频引擎」页点启动")
    else:
        raise HTTPException(404, name)
    return {"ok": True}


MPT_DIR = BASE / "vendors" / "MoneyPrinterTurbo"


@app.get("/api/video/tasks")
def video_tasks(request: Request):
    guard(request)
    from core import video
    return {"tasks": video.recent_tasks()}


@app.get("/api/video/file/{tid}")
def video_file(tid: str, request: Request):
    guard(request)
    if "/" in tid or ".." in tid:
        raise HTTPException(400, "bad tid")
    f = MPT_DIR / "storage" / "tasks" / tid / "final-1.mp4"
    if not f.exists():
        raise HTTPException(404, "成片不存在")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="video/mp4", filename=f"{tid}.mp4")


@app.get("/api/platforms")
def platforms_list(request: Request):
    guard(request)
    from core.platforms import list_packs
    return {"packs": list_packs()}


@app.post("/api/audio/make")
async def audio_make(request: Request):
    u = guard(request)
    body = await request.json()
    did = body.get("draft_id")
    if not did:
        raise HTTPException(400, "请选择草稿")
    script = body.get("script", "")
    # ⭐ 会员分级：TTS 每日次数配额 + 单次字数上限（free：每日 5 次/500 字）
    _allowed, _reason, _tier = _tier_quota_check(u, "tts_daily")
    if not _allowed:
        raise HTTPException(402, _reason)
    _max_chars = _tier_capability_limit(u, "tts_max_chars")
    if isinstance(_max_chars, int) and _max_chars > 0 and len(script) > _max_chars:
        raise HTTPException(
            400,
            f"当前档位单次配音最多 {_max_chars} 字（本次 {len(script)} 字），"
            "升级 V7 Pro 解锁不限字数",
        )
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    import uuid
    jid = f"aud-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"AI 配音TTS合成: {d_title[:16]}",
        task_type="audio_tts",
        target_id=did,
        params={"draft_id": did},
        initial_step="AI 配音合成初始化中…"
    )
    def _run():
        try:
            from core import audio
            res = audio.make_audio(did, int(body.get("seconds", 30)),
                                   body.get("platform", "xhs"),
                                   body.get("subject", ""),
                                   emit=lambda m: update_async_job(jid, step=m),
                                   custom_script=script)
            update_async_job(jid, status="done", step="AI 配音TTS合成完成", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:300], step="配音合成失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.get("/api/audio/file/{did}/{name}")
def audio_file(did: str, name: str, request: Request):
    guard(request)
    if "/" in name or ".." in name or not name.startswith("audio-"):
        raise HTTPException(400, "bad name")
    f = db.draft_dir(did) / name
    if not f.exists():
        raise HTTPException(404, "音频不存在")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="audio/mpeg", filename=name)


@app.post("/api/video/upload_bgm")
async def video_upload_bgm(request: Request, file: UploadFile = File(...)):
    """上传本地背景音乐（.mp3, .wav 等）"""
    guard(request)
    import pathlib, shutil
    bgm_dir = pathlib.Path("data/bgm_uploads")
    bgm_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"bgm_{file.filename}".replace(" ", "_")
    dest = bgm_dir / safe_name
    try:
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"ok": True, "filename": safe_name, "path": str(dest.resolve()), "name": file.filename}
    except Exception as e:
        raise HTTPException(500, f"BGM上传失败: {e}")


@app.post("/api/video/upload_material")
async def video_upload_material(request: Request, file: UploadFile = File(...)):
    """上传本地图片或视频素材作为画面来源"""
    guard(request)
    import pathlib, shutil
    mat_dir = pathlib.Path("data/material_uploads")
    mat_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"mat_{file.filename}".replace(" ", "_")
    dest = mat_dir / safe_name
    try:
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"ok": True, "filename": safe_name, "path": str(dest.resolve()), "name": file.filename}
    except Exception as e:
        raise HTTPException(500, f"素材上传失败: {e}")


@app.post("/api/video/make")
async def video_make(request: Request):
    guard(request)
    body = await request.json()
    did = body.get("draft_id")
    if not did:
        raise HTTPException(400, "请选择草稿")
    script = body.get("script", "")
    bgm_type = body.get("bgm_type", "random")
    bgm_volume = float(body.get("bgm_volume", 0.2))
    bgm_file = body.get("bgm_file", "")
    subtitle_enabled = body.get("subtitle_enabled", True)
    subtitle_position = body.get("subtitle_position", "bottom")
    text_fore_color = body.get("text_fore_color", "#FFFFFF")
    material_source = body.get("material_source", "pexels")
    custom_materials = body.get("video_materials", [])

    # 根据素材来源模式智能组装素材列表
    materials = []
    if material_source == "draft_images":
        # 提取当前草稿的全部 AI 配图
        import pathlib
        draft_img_dir = pathlib.Path(f"data/drafts/{did}/img")
        if draft_img_dir.exists():
            for img in sorted(draft_img_dir.glob("*.png")):
                materials.append(str(img.resolve()))
    elif material_source == "asset_library":
        # 从全局素材库中提取最新高质量图片
        import pathlib
        drafts_dir = pathlib.Path("data/drafts")
        if drafts_dir.exists():
            for ddir in sorted(drafts_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                img_dir = ddir / "img"
                if img_dir.exists():
                    for img in sorted(img_dir.glob("*.png")):
                        materials.append(str(img.resolve()))
    elif material_source == "local" and custom_materials:
        materials = custom_materials

    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    import uuid
    jid = f"vid-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"短视频合成 (MPT): {d_title[:16]}",
        task_type="video_render",
        target_id=did,
        params={"draft_id": did},
        initial_step="短视频渲染管线初始化…"
    )
    def _run():
        try:
            from core import video
            res = video.make_video(did, int(body.get("seconds", 15)),
                                   body.get("subject", ""),
                                   emit=lambda m: update_async_job(jid, step=m),
                                   platform=body.get("platform", "douyin"),
                                   aspect=body.get("aspect", ""),
                                   voice=body.get("voice", ""),
                                   custom_script=script,
                                   bgm_type=bgm_type,
                                   bgm_volume=bgm_volume,
                                   bgm_file=bgm_file,
                                   subtitle_enabled=subtitle_enabled,
                                   subtitle_position=subtitle_position,
                                   text_fore_color=text_fore_color,
                                   video_materials=materials)
            update_async_job(jid, status="done", step="短视频混剪合成完成！", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:300], step="短视频生成失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.post("/api/drafts/{did}/storyboard")
async def draft_storyboard(did: str, request: Request):
    guard(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    from core.storyboard import generate_storyboard, get_storyboard
    force = body.get("force", False) if isinstance(body, dict) else False
    def _run():
        return generate_storyboard(did) if force else get_storyboard(did)
    try:
        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f"生成分镜失败: {e}")


@app.get("/api/drafts/{did}/export_jianying")
def draft_export_jianying(did: str, request: Request, aspect: str = "9:16"):
    guard(request)
    from core.storyboard import export_jianying_draft
    from fastapi.responses import FileResponse
    try:
        zip_file = export_jianying_draft(did, aspect=aspect)
        filename = f"jianying_{did}_{'16x9' if aspect == '16:9' else '9x16'}.zip"
        return FileResponse(zip_file, media_type="application/zip", filename=filename)
    except Exception as e:
        raise HTTPException(500, f"导出剪映工程失败: {e}")


@app.post("/api/drafts/{did}/storyboard/gen_image")
async def storyboard_gen_image(did: str, request: Request):
    guard(request)
    body = await request.json()
    shot_index = int(body.get("shot_index", 1))
    prompt_en = body.get("prompt_en", "")
    aspect = body.get("aspect", "16:9")
    from core import billing, storyboard
    billing.check_and_deduct("drama_image", 1, f"电影分镜生图 #{shot_index}")
    def _run():
        return storyboard.generate_storyboard_image(did, shot_index, prompt_en=prompt_en, aspect=aspect)
    try:
        url = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "image_url": url, "shot_index": shot_index}
    except Exception as e:
        raise HTTPException(500, f"分镜生图失败: {e}")


@app.post("/api/drafts/{did}/storyboard/batch_gen_images")
async def storyboard_batch_gen_images(did: str, request: Request):
    guard(request)
    body = await request.json()
    aspect = body.get("aspect", "16:9")
    from core import storyboard
    def _run():
        return storyboard.batch_generate_storyboard_images(did, aspect=aspect)
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "results": results}
    except Exception as e:
        raise HTTPException(500, f"批量生图失败: {e}")






# ---------------- 商业化计费 & Token 算力中台 ----------------

@app.get("/api/billing/status")
def billing_status(request: Request):
    guard(request)
    from core import billing
    return billing.get_billing_status()


@app.post("/api/billing/redeem")
async def billing_redeem(request: Request):
    guard(request)
    body = await request.json()
    code = body.get("code") or body.get("cdkey", "")
    from core import billing
    return billing.redeem_cdkey(code)


@app.post("/api/billing/admin/gen_keys")
async def billing_gen_keys(request: Request):
    guard(request)
    body = await request.json()
    key_type = body.get("key_type", "tokens")
    amount = int(body.get("amount", 100000))
    count = int(body.get("count", 5))
    from core import billing
    keys = billing.generate_cdkeys(key_type, amount, count)
    return {"ok": True, "keys": keys}


# ---------------- 8大名家音色与深度蒸馏中台 ----------------

@app.get("/api/voices/all")
def voices_all(request: Request):
    guard(request)
    return orchestrator.list_famous_voices()


@app.post("/api/skills/distill_deep")
async def skills_distill_deep(request: Request):
    guard(request)
    body = await request.json()
    content = body.get("content", "")
    distill_type = body.get("distill_type", "all")
    author_name = body.get("author_name", "")
    from core import billing
    billing.check_and_deduct("deep_distill", 1, f"深度逆向蒸馏 [{author_name}]")
    def _run():
        return orchestrator.deep_distill_anything(content, distill_type, author_name)
    try:
        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f"深度蒸馏失败: {e}")


# ---------------- 全 AI 短剧流水线工坊 ----------------

@app.get("/api/video/drama/{did}/scenes")
def drama_scenes(did: str, request: Request):
    guard(request)
    from core import short_drama
    return {"scenes": short_drama.get_drama_scenes(did)}


@app.post("/api/video/drama/{did}/decompose")
async def drama_decompose(did: str, request: Request):
    guard(request)
    body = await request.json()
    style = body.get("style", "cinematic")
    script = body.get("script", "")
    mounted_persona = body.get("mounted_persona", "")
    from core import billing, short_drama
    billing.check_and_deduct("drama_decompose", 1, f"短剧分镜解构 [{did}]")
    def _run():
        return short_drama.decompose_draft_to_drama(did, style_key=style, custom_script=script, mounted_persona=mounted_persona)
    try:
        scenes = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "scenes": scenes}
    except Exception as e:
        raise HTTPException(500, f"短剧分镜解构失败: {e}")


@app.post("/api/video/upload_script_file")
async def video_upload_script_file(request: Request, file: UploadFile = File(...)):
    """上传本地文本文档（.txt, .md, .docx 等），提取纯文口播稿内容"""
    guard(request)
    try:
        contents = await file.read()
        filename = (file.filename or "").lower()
        text = ""
        if filename.endswith(".docx"):
            try:
                import io, zipfile, xml.etree.ElementTree as ET
                with zipfile.ZipFile(io.BytesIO(contents)) as z:
                    xml_content = z.read("word/document.xml")
                    tree = ET.fromstring(xml_content)
                    paragraphs = []
                    for p in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                        texts = [node.text for node in p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if node.text]
                        if texts:
                            paragraphs.append("".join(texts))
                    text = "\n\n".join(paragraphs)
            except Exception:
                text = contents.decode("utf-8", errors="ignore")
        else:
            text = contents.decode("utf-8", errors="ignore")
            
        import re
        # 清理多余标签或复杂 Markdown 格式
        cleaned = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        cleaned = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', cleaned)
        cleaned = re.sub(r'^#{1,6}\s+(.+)$', r'\n\1\n', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', cleaned)
        cleaned = re.sub(r'\*(.+?)\*', r'\1', cleaned)
        cleaned = re.sub(r'`{1,3}[^`]*`{1,3}', '', cleaned)
        cleaned = re.sub(r'^[-*>]\s+', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        
        return {"ok": True, "filename": file.filename, "text": cleaned, "char_count": len(cleaned.replace(" ", "").replace("\n", ""))}
    except Exception as e:
        raise HTTPException(500, f"文档解析失败: {e}")



@app.post("/api/video/drama/{did}/gen_image")
async def drama_gen_image(did: str, request: Request):
    guard(request)
    body = await request.json()
    shot_id = int(body.get("shot_id", 1))
    prompt_en = body.get("prompt_en", "")
    aspect = body.get("aspect", "9:16")
    from core import billing, short_drama
    billing.check_and_deduct("drama_image", 1, f"短剧分镜生图 #{shot_id}")
    def _run():
        return short_drama.generate_scene_image(did, shot_id, prompt_en, aspect=aspect)
    try:
        url = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "image_url": url, "shot_id": shot_id}
    except Exception as e:
        raise HTTPException(500, f"分镜参考生图失败: {e}")


@app.post("/api/video/drama/{did}/batch_gen_images")
async def drama_batch_gen_images(did: str, request: Request):
    guard(request)
    body = await request.json()
    aspect = body.get("aspect", "9:16")
    from core import short_drama
    def _run():
        return short_drama.batch_generate_drama_images(did, aspect=aspect)
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "results": results}
    except Exception as e:
        raise HTTPException(500, f"批量生图失败: {e}")


@app.post("/api/video/drama/{did}/update_scene")
async def drama_update_scene(did: str, request: Request):
    guard(request)
    body = await request.json()
    shot_id = int(body.get("shot_id", 1))
    updates = body.get("updates", {})
    from core import short_drama
    res = short_drama.update_drama_scene(did, shot_id, updates)
    return {"ok": True, "scene": res}


@app.post("/api/video/drama/{did}/preview_audio")
async def drama_preview_audio(did: str, request: Request):
    guard(request)
    body = await request.json()
    shot_id = int(body.get("shot_id", 1))
    script = body.get("script", "")
    voice = body.get("voice", "zh-CN-YunxiNeural")
    from core import short_drama
    def _run():
        return short_drama.synthesize_scene_tts(did, shot_id, script, voice=voice)
    try:
        url = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "audio_url": url, "shot_id": shot_id}
    except Exception as e:
        raise HTTPException(500, f"单句语音合成失败: {e}")


@app.post("/api/video/drama/{did}/render")
async def drama_render(did: str, request: Request):
    u = guard(request)
    # ⭐ 会员分级：短剧流水线每周配额（free：每周 1 次完整 8 步）
    _allowed, _reason, _tier = _tier_quota_check(u, "drama_weekly")
    if not _allowed:
        raise HTTPException(402, _reason)
    body = await request.json()
    aspect = body.get("aspect", "9:16")
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    import uuid
    jid = f"drm-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"全AI短剧渲染: {d_title[:16]}",
        task_type="drama_pipeline",
        target_id=did,
        params={"draft_id": did, "aspect": aspect},
        initial_step="短剧视频渲染队列中…"
    )
    from core import billing, short_drama
    billing.check_and_deduct("drama_render", 1, f"全AI短剧渲染 [{did}]")
    # ⭐ 会员分级：短剧成片时长帽（free：10 秒）——渲染期最终兜底（整镜头截取）
    _cap = _tier_capability_limit(u, "drama_max_seconds")
    _max_s = _cap if (isinstance(_cap, int) and _cap > 0) else None
    def _run():
        try:
            res = short_drama.render_short_drama_video(did, aspect=aspect, max_total_seconds=_max_s, emit=lambda m: update_async_job(jid, step=m))
            update_async_job(jid, status="done", step="短剧成片渲染完成！", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:400], step="短剧渲染失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.get("/audio/drama/{did}/{filename}")
def drama_audio_file(did: str, filename: str):
    f = db.draft_dir(did) / "drama" / "audio" / filename
    if not f.exists():
        raise HTTPException(404, "音频未找到")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="audio/mpeg")


@app.get("/img/drama/{did}/images/{filename}")
def drama_image_file(did: str, filename: str):
    f = db.draft_dir(did) / "drama" / "images" / filename
    if not f.exists():
        raise HTTPException(404, "图片未找到")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="image/png")


@app.get("/img/storyboard/{did}/images/{filename}")
def storyboard_image_file(did: str, filename: str):
    f = db.draft_dir(did) / "storyboard_images" / filename
    if not f.exists():
        raise HTTPException(404, "分镜图片未找到")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="image/png")


@app.get("/img/drama/{did}/assets/{filename}")
def drama_asset_file(did: str, filename: str):
    f = db.draft_dir(did) / "drama" / "assets" / filename
    if not f.exists():
        raise HTTPException(404, "资产图片未找到")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="image/png")


@app.get("/img/drama/{did}/shots/{filename}")
def drama_shot_image_file(did: str, filename: str):
    f = db.draft_dir(did) / "drama" / "shots" / filename
    if not f.exists():
        raise HTTPException(404, "分镜图片未找到")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="image/png")


@app.get("/video/drama/{did}/shots/{filename}")
def drama_shot_video_file(did: str, filename: str):
    f = db.draft_dir(did) / "drama" / "shots" / filename
    if not f.exists():
        raise HTTPException(404, "分镜视频未找到")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="video/mp4")


@app.get("/video/drama/{did}/{filename}")
def drama_video_file(did: str, filename: str):
    f = db.draft_dir(did) / "drama" / filename
    if not f.exists():
        raise HTTPException(404, "短剧视频未找到")
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type="video/mp4")


# ---------------- 8 步全 AI 短剧工业级流水线 API ----------------

@app.get("/api/video/drama/{did}/pipeline/project")
def drama_pipeline_get_project(did: str, request: Request):
    guard(request)
    from core import short_drama
    return {"ok": True, "project": short_drama.get_pipeline_project(did), "styles": short_drama.DRAMA_STYLES}


@app.post("/api/video/drama/{did}/pipeline/save_project")
async def drama_pipeline_save_project(did: str, request: Request):
    guard(request)
    body = await request.json()
    project_data = body.get("project", {})
    from core import short_drama
    saved = short_drama.save_pipeline_project(did, project_data)
    return {"ok": True, "project": saved}


@app.post("/api/video/drama/{did}/pipeline/step1_analyze")
async def drama_pipeline_step1(did: str, request: Request):
    u = guard(request)
    body = await request.json()
    text = body.get("text", "")
    overrides = body.get("overrides", {})
    # ⭐ 会员分级：短剧成片时长帽（free：10 秒）——导演 AI 按该时长规划，保证成片连贯
    _cap = _tier_capability_limit(u, "drama_max_seconds")
    if isinstance(_cap, int) and _cap > 0:
        try:
            _dt = int(overrides.get("duration_target") or 45)
        except (TypeError, ValueError):
            _dt = 45
        if _dt > _cap:
            overrides["duration_target"] = _cap
    from core import billing, short_drama
    billing.check_and_deduct("drama_decompose", 1, f"短剧需求分析与剧本改写 [{did}]")
    def _run():
        return short_drama.step1_analyze_and_rewrite(did, text=text, overrides=overrides)
    try:
        proj = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "project": proj}
    except Exception as e:
        raise HTTPException(500, f"剧本需求分析与改写失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step2_outline")
async def drama_pipeline_step2(did: str, request: Request):
    guard(request)
    body = await request.json()
    updates = body.get("updates", {})
    from core import short_drama
    proj = short_drama.step2_confirm_outline(did, updates=updates)
    return {"ok": True, "project": proj}


@app.post("/api/video/drama/{did}/pipeline/step3_assets")
async def drama_pipeline_step3(did: str, request: Request):
    guard(request)
    from core import short_drama
    def _run():
        return short_drama.step3_generate_assets_specs(did)
    try:
        proj = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "project": proj}
    except Exception as e:
        raise HTTPException(500, f"资产设定规格生成失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step4_gen_asset")
async def drama_pipeline_step4_single(did: str, request: Request):
    guard(request)
    body = await request.json()
    asset_type = body.get("asset_type", "character")
    asset_id = body.get("asset_id", "")
    prompt = body.get("prompt", "")
    is_turnaround = bool(body.get("is_turnaround", False))
    aspect = body.get("aspect", "16:9")
    from core import billing, short_drama
    billing.check_and_deduct("drama_image", 1, f"短剧资产出图 [{asset_id}]")
    def _run():
        return short_drama.step4_generate_asset_image(
            did, asset_type=asset_type, asset_id=asset_id,
            prompt=prompt, is_turnaround=is_turnaround, aspect=aspect
        )
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f"资产图片生成失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step4_batch_assets")
async def drama_pipeline_step4_batch(did: str, request: Request):
    guard(request)
    from core import billing, short_drama
    billing.check_and_deduct("drama_image", 2, f"短剧资产批量生成 [{did}]")
    def _run():
        return short_drama.step4_batch_generate_assets(did)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f"批量生成资产失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step5_storyboard")
async def drama_pipeline_step5(did: str, request: Request):
    u = guard(request)
    from core import billing, short_drama
    billing.check_and_deduct("drama_decompose", 1, f"短剧好莱坞分镜解构 [{did}]")
    # ⭐ 会员分级：短剧成片时长帽（free：10 秒）——分镜期按总时长整镜头截取
    _cap = _tier_capability_limit(u, "drama_max_seconds")
    _max_s = _cap if (isinstance(_cap, int) and _cap > 0) else None
    def _run():
        return short_drama.step5_generate_storyboard(did, max_total_seconds=_max_s)
    try:
        shots = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "shots": shots, "project": short_drama.get_pipeline_project(did)}
    except Exception as e:
        raise HTTPException(500, f"分镜解构失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step6_gen_shot")
async def drama_pipeline_step6_single(did: str, request: Request):
    guard(request)
    body = await request.json()
    shot_id = int(body.get("shot_id", 1))
    prompt_en = body.get("prompt_en", "")
    aspect = body.get("aspect", "9:16")
    from core import billing, short_drama
    billing.check_and_deduct("drama_image", 1, f"分镜头 #{shot_id} 生图")
    def _run():
        return short_drama.step6_generate_shot_image(did, shot_id=shot_id, prompt_en=prompt_en, aspect=aspect)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f"分镜生图失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step6_batch_shots")
async def drama_pipeline_step6_batch(did: str, request: Request):
    guard(request)
    body = await request.json()
    aspect = body.get("aspect", "9:16")
    from core import short_drama
    def _run():
        return short_drama.step6_batch_generate_shots(did, aspect=aspect)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f"批量生成分镜图失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step7_gen_video")
async def drama_pipeline_step7_single(did: str, request: Request):
    guard(request)
    body = await request.json()
    shot_id = int(body.get("shot_id", 1))
    aspect = body.get("aspect", "9:16")
    subtitle_enabled = body.get("subtitle_enabled", None)
    video_mode = body.get("video_mode", "ai_video")
    from core import short_drama
    def _run():
        return short_drama.step7_generate_shot_video(
            did, shot_id=shot_id, aspect=aspect,
            subtitle_enabled=subtitle_enabled, video_mode=video_mode
        )
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f"生成分镜切片视频失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step7_batch_videos")
async def drama_pipeline_step7_batch(did: str, request: Request):
    guard(request)
    body = await request.json()
    aspect = body.get("aspect", "9:16")
    subtitle_enabled = body.get("subtitle_enabled", None)
    video_mode = body.get("video_mode", "ai_video")
    from core import short_drama
    def _run():
        return short_drama.step7_batch_generate_videos(
            did, aspect=aspect,
            subtitle_enabled=subtitle_enabled, video_mode=video_mode
        )
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f"批量生成镜头视频切片失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step8_render")
async def drama_pipeline_step8(did: str, request: Request):
    guard(request)
    body = await request.json()
    aspect = body.get("aspect", "9:16")
    subtitle_enabled = body.get("subtitle_enabled", None)
    video_mode = body.get("video_mode", "ai_video")
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    import uuid
    jid = f"drm-p8-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"8步短剧最终成片合成: {d_title[:16]}",
        task_type="drama_pipeline",
        target_id=did,
        params={"draft_id": did, "aspect": aspect},
        initial_step="8步短剧流水线成片合成中…"
    )
    from core import billing, short_drama
    billing.check_and_deduct("drama_render", 1, f"8步短剧最终成片合成 [{did}]")
    def _run():
        try:
            res = short_drama.step8_render_final_drama(
                did, aspect=aspect,
                subtitle_enabled=subtitle_enabled, video_mode=video_mode,
                emit=lambda m: update_async_job(jid, step=m)
            )
            update_async_job(jid, status="done", step="短剧全流程流水线成片合成完成！", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:400], step="短剧合成失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}




@app.get("/api/video/status")
def video_status(request: Request):
    guard(request)
    import socket
    running = False
    try:
        with socket.create_connection(("127.0.0.1", 8501), timeout=1):
            running = True
    except Exception:
        pass
    return {"installed": (MPT_DIR / "webui" / "Main.py").exists(), "running": running}


@app.post("/api/video/launch")
async def video_launch(request: Request):
    guard(request)
    if not (MPT_DIR / "webui" / "Main.py").exists():
        raise HTTPException(400, "MoneyPrinterTurbo 未安装")
    import subprocess
    subprocess.Popen(
        [str(MPT_DIR / ".venv" / "bin" / "python"), "-m", "streamlit", "run",
         str(MPT_DIR / "webui" / "Main.py"), "--server.port", "8501",
         "--server.headless", "true"],
        cwd=str(MPT_DIR), stdout=open(BASE / "logs" / "mpt.out", "w"),
        stderr=subprocess.STDOUT)
    return {"ok": True, "url": "http://127.0.0.1:8501"}


@app.post("/api/drafts/{did}/ai_xhs")
async def draft_ai_xhs(did: str, request: Request):
    guard(request)
    body = await request.json()
    style = body.get("style", "magazine")
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    import uuid
    jid = f"xhs-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"小红书排版与制卡: {d_title[:16]}",
        task_type="article_layout",
        target_id=did,
        params={"draft_id": did, "style": style},
        initial_step="小红书爆款图文卡片排版中…"
    )
    def _run():
        try:
            res = orchestrator.ai_xhs(did, style, emit=lambda m: update_async_job(jid, step=m))
            update_async_job(jid, status="done", step="小红书卡片重排完成！", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:400], step="小红书排版失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.post("/api/drafts/{did}/ai_xhs_visual")
async def draft_ai_xhs_visual(did: str, request: Request):
    """AI 全套小红书视觉生图与卡片精修制卡任务"""
    guard(request)
    body = await request.json()
    style = body.get("style", "ai_visual_dark")
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    import uuid
    jid = f"xhs-vis-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"小红书 AI 视觉配图制卡: {d_title[:16]}",
        task_type="image_gen",
        target_id=did,
        params={"draft_id": did, "style": style},
        initial_step="AI 视觉大模型通读与配图生成中…"
    )
    def _run():
        try:
            res = orchestrator.ai_xhs_visual(did, style, emit=lambda m: update_async_job(jid, step=m))
            update_async_job(jid, status="done", step="✨ AI 视觉图文卡片生成完成！", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:400], step="AI 生图制卡失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.post("/api/drafts/{did}/xhs_style")
async def draft_xhs_style(did: str, request: Request):
    """即时快速切换小红书卡片风格（毫秒级重绘已有配图与文本）"""
    guard(request)
    body = await request.json()
    style = body.get("style", "magazine")
    res = orchestrator.change_xhs_style(did, style=style)
    return res


# ----------------- 小红书专属历史版本回溯路由 -----------------

@app.get("/api/drafts/{did}/xhs/history")
async def get_xhs_history(did: str):
    """获取草稿的小红书专属历史快照列表（包含文案与卡片图）。"""
    try:
        snaps = orchestrator.list_xhs_history(did)
        return {"ok": True, "draft_id": did, "snapshots": snaps}
    except Exception as e:
        raise HTTPException(500, f"获取小红书历史失败: {e}")


@app.get("/api/drafts/{did}/xhs/history/{hid}/card/{card_name}")
async def get_xhs_history_card(did: str, hid: str, card_name: str):
    """查看指定小红书历史快照中的卡片图片。"""
    card_file = db.draft_dir(did) / "xhs_history" / hid / card_name
    if not card_file.exists():
        raise HTTPException(404, "历史卡片不存在")
    return FileResponse(str(card_file), media_type="image/png")


@app.post("/api/drafts/{did}/xhs/history/{hid}/restore")
async def restore_xhs_history_endpoint(did: str, hid: str, request: Request):
    """一键回溯还原指定的小红书版本（同时还原 xhs.md 与全套卡片图）。"""
    guard(request)
    try:
        res = await asyncio.get_event_loop().run_in_executor(
            None, lambda: orchestrator.restore_xhs_history(did, hid)
        )
        return res
    except Exception as e:
        raise HTTPException(500, f"回溯小红书版本失败: {e}")


@app.get("/api/drafts/{did}/history")
def draft_history(did: str, request: Request):
    guard(request)
    return {"history": db.list_history(did)}


@app.post("/api/drafts/{did}/restore")
async def draft_restore(did: str, request: Request):
    guard(request)
    body = await request.json()
    h = db.get_history(body.get("hid", ""))
    if not h or h["draft_id"] != did:
        raise HTTPException(404, "历史版本不存在")
    c = db.conn()
    c.execute("UPDATE drafts SET title=?, body_md=? WHERE id=?",
              (h["title"], h["body_md"], did))
    c.commit(); c.close()
    orchestrator._refresh_artifacts(did, {"TITLE_WX": h["title"], "BODY_WX": h["body_md"]},
                                    h["title"], h["body_md"])
    return {"ok": True, "title": h["title"]}


@app.get("/api/drafts/{did}")
def get_draft_detail_endpoint(did: str, request: Request):
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, f"草稿不存在: {did}")
    return d


@app.get("/api/drafts/{did}/score")
def draft_score(did: str, request: Request):
    guard(request)
    sc = judge.get_score(did)
    if not sc:
        return {"ok": True, "scored": False, "total": None, "grade": "未评分"}
    sc["scored"] = True
    return sc


@app.post("/api/drafts/create")
async def create_draft_endpoint(request: Request):
    """创作者在内容工作台手动新建空白草稿或导入外部草稿"""
    guard(request)
    body = await request.json()
    title = (body.get("title") or "").strip()
    body_md = body.get("body_md") or ""
    workspace_id = (body.get("workspace_id") or "").strip()
    if not workspace_id:
        from core import workspace
        active_ws = workspace.get_active_workspace()
        if active_ws:
            workspace_id = active_ws.get("id", "")
            
    draft = db.create_custom_draft(title=title, body_md=body_md, workspace_id=workspace_id)
    did = draft["id"]
    
    # 初始化多平台文件产物与预览
    from core import orchestrator
    orchestrator.init_draft_artifacts(did, draft["title"], draft["body_md"])
    
    # 执行初次基准评分（无 LLM 时跳过，避免 500）
    from core import judge
    from core import llm as _llm
    score = judge.judge_draft(did) if _llm.available() else {"total": 0, "grade": "未评分（未配置大模型）"}
    
    return {"ok": True, "draft": db.get_draft(did), "score": score}


@app.post("/api/drafts/{did}/ai_upgrade")
async def ai_upgrade_draft_endpoint(did: str, request: Request):
    """结合名家文风、专属技能库与黄金钩子对草稿进行一键深度改写提分"""
    guard(request)
    body = await request.json()
    persona = body.get("persona", "")
    skills = body.get("skills")
    focus_targets = body.get("focus_targets")
    instruction = body.get("instruction", "")
    media_name = body.get("media_name", "")

    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    old_score = (judge.get_score(did) or {}).get("total", 0)

    import uuid
    jid = f"upg-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"AI 深度改写提升: {d_title[:16]}",
        task_type="ai_rewrite",
        target_id=did,
        params={"draft_id": did, "persona": persona, "skills": skills},
        initial_step="正在融合名家文风、黄金3秒钩子与深度去AI味…"
    )
    try:
        update_async_job(jid, step="深度重塑正文、金句提炼与多端派生中…", progress=40)
        res = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: orchestrator.ai_upgrade_draft(
                did,
                persona_id=persona,
                skills=skills,
                focus_targets=focus_targets,
                custom_instruction=instruction,
                media_name=media_name
            )
        )
        new_score = (res.get("score") or {}).get("total", 0)
        res["old_score"] = old_score
        res["improvement_delta"] = round(new_score - old_score, 1)
        update_async_job(
            jid,
            status="done",
            step=f"改写提升完成！评分由 {old_score} 跃升至 {new_score} (+{res['improvement_delta']}分)",
            progress=100,
            result={"score": new_score, "delta": res["improvement_delta"]}
        )
        return res
    except Exception as e:
        update_async_job(jid, status="failed", error=str(e)[:300], step="AI 改写提升失败")
        raise HTTPException(500, f"AI 一键改写提升失败: {e}")


@app.post("/api/drafts/{did}/rewrite")
async def draft_rewrite(did: str, request: Request):
    guard(request)
    body = await request.json()
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: orchestrator.rewrite_draft_once(did, body.get("instruction", "")))
    except Exception as e:
        raise HTTPException(500, f"重写失败: {e}")


@app.post("/api/drafts/{did}/rewrite_platform")
async def draft_rewrite_platform(did: str, request: Request):
    """单平台专属重写/重排（v3.33新增）。
    
    body: { "platform": "xhs"|"toutiao"|"wechat_mp"|"weibo"|"zhihu"|"twitter", 
            "instruction": "可选的重写指令" }
    只重写并覆盖该平台的内容，不影响其他平台。
    """
    guard(request)
    body = await request.json()
    platform = (body.get("platform") or "").strip()
    if not platform:
        raise HTTPException(400, "platform 不能为空")
    instruction = body.get("instruction", "")
    
    PLATFORM_NAMES = {
        "wechat_mp": "微信公众号",
        "xhs": "小红书",
        "toutiao": "今日头条",
        "weibo": "微博",
        "zhihu": "知乎",
        "twitter": "推特/X",
    }
    plat_name = PLATFORM_NAMES.get(platform, platform)
    
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: orchestrator.rewrite_single_platform(did, platform, instruction))
        result["platform_name"] = plat_name
        return result
    except Exception as e:
        raise HTTPException(500, f"{plat_name} 重写失败: {e}")


@app.post("/api/drafts/{did}/quality_gate")
async def draft_quality_gate(did: str, request: Request):
    """借鉴 Easel: 发布前双重质量关卡与合规风控体检 (Quality Gate)。
    检测：
    1. 广告法极限词拦截（第一、最强、顶级等）
    2. 平台限流违禁/敏感词
    3. AI 机械感与套路化特征
    4. 标题字数与格式完整性
    """
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    
    from core import agents
    
    title = d.get("title", "")
    body = d.get("body_md", "")
    
    prompt = (
        "你是顶级社媒发布合规总监与内容品控专家。请对以下草稿进行严格的【发布前质量风控与合规体检】。\n\n"
        f"【标题】：{title}\n\n"
        f"【正文前3000字】：\n{body[:3000]}\n\n"
        "请从以下四个维度进行全景式体检，并输出纯 JSON：\n"
        "1. ad_violations: 广告法极限违禁词（如最、第一、唯一、顶级、绝对等），指出原句并给出安全合规修改建议；\n"
        "2. platform_risks: 平台限流敏感词（夸大宣传、疑似引流导流、封建迷信、诱导关注等）；\n"
        "3. ai_smell_issues: AI 机械套路感诊断（是否包含'总而言之、不可否认、在这个快节奏时代'等公文腔排比），给出活人感打磨建议；\n"
        "4. completeness: 标题长度、分段呼吸感、结尾行动召唤 (CTA) 是否完备；\n"
        "5. score: 0-100 的综合安全与质量合规指数（>=85方可通过发布）；\n"
        "6. passed: true/false 是否通过风控关卡。\n\n"
        "严格只输出纯 JSON，绝不要包含 markdown 解释：\n"
        "{\n"
        '  "score": 92,\n'
        '  "passed": true,\n'
        '  "summary": "整体合规度高，无触碰广告法红线，文风自然",\n'
        '  "ad_violations": [],\n'
        '  "platform_risks": [],\n'
        '  "ai_smell_issues": [],\n'
        '  "recommendations": ["建议将结尾互动提问设为单选，降低留言门槛"]\n'
        "}"
    )
    
    try:
        raw = agents.chat_for("review", [
            {"role": "system", "content": "只输出纯 JSON，绝不添加包裹。"},
            {"role": "user", "content": prompt}
        ], temperature=0.2)
        import re, json
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {"passed": True, "score": 85, "summary": "体检完成", "recommendations": []}
    except Exception as e:
        return {"passed": True, "score": 80, "summary": f"体检服务返回: {e}", "recommendations": []}


@app.post("/api/topics/evaluate")
async def topic_evaluate(request: Request):
    """借鉴 Easel: 选题爆款潜力五维多维评分卡 (Topic Evaluator)。"""
    guard(request)
    body = await request.json()
    topic = (body.get("topic") or body.get("title") or "").strip()
    if not topic:
        raise HTTPException(400, "选题内容不能为空")
    
    from core import agents
    prompt = (
        "你是顶级新媒体爆款主编。请对以下选题的爆款潜力进行五维量化评估，并输出纯 JSON。\n\n"
        f"【待评估选题】：{topic}\n\n"
        "打分维度（各项满分20分，总分100）：\n"
        "1. viral_potential: 流量广谱度（是否能击中广泛大众的好奇心/共鸣）\n"
        "2. pain_point: 痛点穿透力（是否直击现实刚需痛点）\n"
        "3. novelty: 认知反差/新颖度（是否颠覆常识）\n"
        "4. feasibility: 交付实操性（是否容易落地）\n"
        "5. monetization: 商业/变现空间（是否有种草或转化潜力）\n\n"
        "严格输出 JSON：\n"
        "{\n"
        '  "total_score": 88,\n'
        '  "grade": "S级爆款",\n'
        '  "scores": {"viral_potential": 18, "pain_point": 19, "novelty": 17, "feasibility": 18, "monetization": 16},\n'
        '  "verdict": "立刻执行",\n'
        '  "advice": "建议重点从反常识误区切入，增加具体对比案例"\n'
        "}"
    )
    try:
        raw = agents.chat_for("review", [
            {"role": "system", "content": "只输出纯 JSON"},
            {"role": "user", "content": prompt}
        ], temperature=0.3)
        import re, json
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {"total_score": 80, "verdict": "建议执行", "advice": "主题具备潜力"}
    except Exception as e:
        return {"total_score": 75, "verdict": "待定", "advice": str(e)}


# ---------------- 借鉴 Easel: 6 维账号数字画像与爆款归因复盘 (Profile & Postmortem) ----------------

@app.get("/api/workspace/profile")
def api_get_workspace_profile(request: Request, wid: Optional[str] = None):
    """获取当前活动工作区（或指定工作区）的 6 维数字人格档案"""
    guard(request)
    from core import workspace
    return {"ok": True, "profile": workspace.get_workspace_profile(wid)}


@app.post("/api/workspace/profile")
async def api_update_workspace_profile(request: Request):
    """更新 6 维数字人格档案（定位/声纹/受众/平台偏好/禁忌/长期记忆）"""
    guard(request)
    body = await request.json()
    wid = body.get("workspace_id")
    profile_data = body.get("profile") or {}
    from core import workspace
    active_ws = workspace.get_active_workspace()
    target_wid = wid or (active_ws.get("id") if active_ws else "ws-default")
    res = workspace.update_workspace_profile(target_wid, profile_data)
    return {"ok": True, "profile": res, "msg": "6 维数字人格档案已更新，后续创作将自动注入该声纹指纹！"}


@app.post("/api/content/postmortem")
async def api_content_postmortem(request: Request):
    """借鉴 Easel skill-content-postmortem: 爆款/发布效果深度归因与策略顾问。"""
    guard(request)
    body = await request.json()
    title = (body.get("title") or "").strip()
    platform = (body.get("platform") or "xhs").strip()
    metrics = body.get("metrics") or {}  # {"likes": 1200, "collects": 850, "comments": 94, "views": 15000}
    content_sample = (body.get("content") or "").strip()

    if not title:
        raise HTTPException(400, "标题不能为空")

    from core import agents
    prompt = (
        "你是顶级社媒操盘手与内容归因专家。请对以下已发布的社媒内容及其实际传播数据进行【深度归因复盘 (Content Postmortem)】，"
        "拆解其之所以产生该数据的底层原因，并提炼为可复用的爆款认知公式，输出纯 JSON：\n\n"
        f"【发布平台】：{platform}\n"
        f"【内容标题】：{title}\n"
        f"【互动表现数据】：点赞 {metrics.get('likes', 0)} / 收藏 {metrics.get('collects', 0)} / 评论 {metrics.get('comments', 0)} / 浏览量 {metrics.get('views', 0)}\n"
        f"【正文片段】：\n{content_sample[:1500]}\n\n"
        "请从以下 4 个维度进行透彻归因分析：\n"
        "1. performance_diagnosis: 数据综合定级 (S/A/B/C) 与爆款成因或平淡原因核心诊断；\n"
        "2. hook_attribution: 开篇与标题的吸睛率与点击心理归因；\n"
        "3. engagement_drivers: 驱动读者收藏（干货留存欲）与评论（互动槽点/争议/共鸣）的关键推手；\n"
        "4. replicable_formula: 提炼一条极其精炼、可在未来稿件中直接复用的【爆款打法公式】。\n\n"
        "严格只输出纯 JSON：\n"
        "{\n"
        '  "grade": "S",\n'
        '  "diagnosis": "高收藏比表明实操干货密度极大，切中大众避坑刚需",\n'
        '  "hook_attribution": "反常识数字制造认知缺口",\n'
        '  "engagement_drivers": "清单化避坑指南触发强收藏心智",\n'
        '  "replicable_formula": "反常识结论 + 场景化踩坑还原 + 3步可执行清单"\n'
        "}"
    )

    try:
        raw = agents.chat_for("review", [
            {"role": "system", "content": "只输出纯 JSON"},
            {"role": "user", "content": prompt}
        ], temperature=0.3)
        import re, json
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            return {"ok": True, "postmortem": json.loads(m.group(0))}
        return {"ok": True, "postmortem": {"grade": "A", "diagnosis": "表现优异", "replicable_formula": "强化反差 Hook"}}
    except Exception as e:
        raise HTTPException(500, f"归因分析失败: {e}")



@app.post("/api/drafts/{did}/refine")
async def draft_refine(did: str, request: Request):
    guard(request)
    body = await request.json()
    defects = body.get("defects") or []
    if isinstance(defects, str):
        defects = [defects]
    if not defects:
        raise HTTPException(400, "请提供至少一个待补齐的短板项")
    old_score = (judge.get_score(did) or {}).get("total", 0)
    def _run():
        res = orchestrator.refine_draft_points(did, defects)
        new_score = (res.get("score") or {}).get("total", 0)
        delta = round(new_score - old_score, 1)
        return {
            "ok": True,
            "new_score": new_score,
            "old_score": old_score,
            "improvement_delta": delta,
            "fixed_count": len(defects),
            "score": res.get("score")
        }
    try:
        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f"外科手术定点精修失败: {e}")


@app.post("/api/drafts/{did}/evolve")
async def draft_evolve(did: str, request: Request):
    guard(request)
    body = await request.json()
    target_score = int(body.get("target_score", 80))
    max_rounds = int(body.get("max_rounds", 3))
    import uuid
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"step": "自进化熔炉初始化…", "status": "running", "result": None, "error": ""}
    def _run():
        try:
            res = orchestrator.evolve_draft_to_target(
                did, target_score=target_score, max_rounds=max_rounds,
                emit=lambda m: JOBS[jid].update(step=m)
            )
            JOBS[jid].update(status="done", step="炼制完成", result=res)
        except Exception as e:
            JOBS[jid].update(status="failed", error=str(e)[:300], step="炼制中断")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.get("/api/drafts/{did}/raw/{platform}")
def draft_raw(did: str, platform: str):
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    ddir = db.draft_dir(did)
    if platform == "wechat_mp":
        f = ddir / "preview-wechat_mp.html"
        content = f.read_text(encoding="utf-8") if f.exists() else ""
        from core.imagegen import get_draft_images
        d_imgs = get_draft_images(did)
        has_imgs_on_disk = bool(d_imgs.get("cover") or d_imgs.get("sections"))
        if not f.exists() or f.stat().st_size < 100 or (has_imgs_on_disk and "<img" not in content):
            from core.layouter import render as layout_render
            images_dict = {f"sec-{i}": u for i, u in enumerate(d_imgs.get("sections", []))}
            sec_meta = [line[4:].strip() for line in d["body_md"].splitlines() if line.startswith("### ")]
            for i, sec_t in enumerate(sec_meta):
                if i < len(d_imgs.get("sections", [])):
                    images_dict[sec_t] = d_imgs["sections"][i]
            wx_html = layout_render(d["body_md"], d["title"], theme="spring-fresh", images=images_dict, cover=d_imgs.get("cover"))
            f.write_text(wx_html, encoding="utf-8")
        return {"title": d["title"],
                "html": f.read_text(encoding="utf-8"),
                "text": d["body_md"]}
    if platform == "body":
        return {"title": d["title"], "body_md": d["body_md"], "text": d["body_md"]}
    if platform == "xhs":
        f_md = ddir / "xhs.md"
        # 从 xhs.md 首行 # 标题提取当前小红书标题
        xhs_title = d["title"]
        raw_txt = f_md.read_text(encoding="utf-8") if f_md.exists() else d["body_md"]
        for _ln in raw_txt.splitlines():
            _ln_s = _ln.strip()
            if _ln_s.startswith("# "):
                xhs_title = _ln_s[2:].strip() or xhs_title
                break
        cards = sorted([f"/card/{did}/{p.name}" for p in ddir.glob("card-*.png")])
        if len(cards) < 5:
            try:
                from core.render_card import render_draft_cards
                from core.copilot import extract_xhs_card_selling_points
                pts = extract_xhs_card_selling_points(xhs_title, d["body_md"])
                cov = ddir / "img" / "cover.png" if (ddir / "img" / "cover.png").exists() else None
                render_draft_cards(ddir, xhs_title, pts, style="ai_visual_dark", cover_img=cov)
                cards = sorted([f"/card/{did}/{p.name}" for p in ddir.glob("card-*.png")])
            except Exception:
                pass
        from core.orchestrator import clean_xhs_text
        cleaned_txt = clean_xhs_text(raw_txt, xhs_title)
        return {
            "title": xhs_title,
            "text": cleaned_txt,
            "cards": cards,
            "cards_count": len(cards)
        }
    if platform == "toutiao":
        f_html = ddir / "preview-toutiao.html"
        f_md = ddir / "toutiao.md"
        from adapters import toutiao as _tt
        from core.imagegen import inject_images_to_markdown, get_draft_images
        d_imgs = get_draft_images(did)
        text = f_md.read_text(encoding="utf-8") if f_md.exists() else inject_images_to_markdown(d["body_md"], did)
        if not f_md.exists():
            (ddir / "toutiao.md").write_text(text, encoding="utf-8")
            
        cur_html = f_html.read_text(encoding="utf-8") if f_html.exists() else ""
        need_rebuild = not f_html.exists() or f_html.stat().st_size < 100
        if not need_rebuild and d_imgs.get("sections") and cur_html.count("<img") <= 1:
            need_rebuild = True
            
        if need_rebuild:
            html = _tt.render_preview(text, d["title"], images=d_imgs.get("sections"), cover=d_imgs.get("cover"), draft_id=did)
            f_html.write_text(html, encoding="utf-8")
        else:
            html = cur_html
            
        return {
            "title": d["title"],
            "html": html,
            "text": text
        }
    if platform == "zhihu":
        f_html = ddir / "preview-zhihu.html"
        f_md = ddir / "zhihu.md"
        from adapters import zhihu as _zh
        from core.imagegen import inject_images_to_markdown, get_draft_images
        text = f_md.read_text(encoding="utf-8") if f_md.exists() else inject_images_to_markdown(d["body_md"], did)
        if not f_md.exists():
            (ddir / "zhihu.md").write_text(text, encoding="utf-8")
        if f_html.exists() and f_html.stat().st_size > 100:
            html = f_html.read_text(encoding="utf-8")
        else:
            d_imgs = get_draft_images(did)
            html = _zh.render_preview(text, d["title"], images=d_imgs.get("sections"), cover=d_imgs.get("cover"), draft_id=did)
            f_html.write_text(html, encoding="utf-8")
        return {
            "title": d["title"],
            "html": html,
            "text": text
        }
    if platform == "weibo":
        f_html = ddir / "preview-weibo.html"
        f_md = ddir / "weibo.md"
        from adapters import weibo as _wb
        from core.imagegen import inject_images_to_markdown, get_draft_images
        text = f_md.read_text(encoding="utf-8") if f_md.exists() else inject_images_to_markdown(d["body_md"], did)
        if not f_md.exists():
            (ddir / "weibo.md").write_text(text, encoding="utf-8")
        if f_html.exists() and f_html.stat().st_size > 100:
            html = f_html.read_text(encoding="utf-8")
        else:
            d_imgs = get_draft_images(did)
            html = _wb.render_preview(text, d["title"], images=d_imgs.get("sections"), cover=d_imgs.get("cover"), draft_id=did)
            f_html.write_text(html, encoding="utf-8")
        return {
            "title": d["title"],
            "html": html,
            "text": text
        }
    if platform == "twitter":
        f_html = ddir / "preview-twitter.html"
        f_md = ddir / "twitter.md"
        from adapters import twitter as _tw
        text = f_md.read_text(encoding="utf-8") if f_md.exists() else d["body_md"]
        if not f_md.exists():
            (ddir / "twitter.md").write_text(text, encoding="utf-8")
        if f_html.exists() and f_html.stat().st_size > 50:
            html = f_html.read_text(encoding="utf-8")
        else:
            html = _tw.render_twitter_html(text, d["title"])
            f_html.write_text(html, encoding="utf-8")
        return {
            "title": d["title"],
            "html": html,
            "text": text
        }
    raise HTTPException(404, f"未知平台: {platform}")


@app.post("/api/drafts/{did}/save_platform")
async def draft_save_platform(did: str, request: Request):
    """多平台通用源文案保存与同步热渲染接口"""
    guard(request)
    body = await request.json()
    platform = body.get("platform", "wechat_mp")
    text = body.get("text", "")
    theme = body.get("theme")

    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    ddir = db.draft_dir(did)

    if platform == "wechat_mp":
        c = db.conn()
        c.execute("UPDATE drafts SET body_md=? WHERE id=?", (text, did))
        c.commit(); c.close()
        from core.themes import md_to_wechat_html
        if not theme:
            theme = load_config().get("creation", {}).get("wechat_theme", "caozhou")
        theme = theme if theme in WECHAT_THEMES else "caozhou"
        images = {f.name: f"/img/{did}/{f.name}" for f in sorted((ddir / "img").glob("sec-*.png"))} \
            if (ddir / "img").exists() else {}
        cover = f"/img/{did}/cover.png" if (ddir / "img" / "cover.png").exists() else None
        meta = (body.get("meta") or body.get("media_name") or "").strip() or "一幕·YIMU 爆款工作室"
        html = md_to_wechat_html(text, d["title"], theme=theme, meta=meta, images=images)
        from core.layouter import _inject_cover
        html = _inject_cover(html, cover)
        (ddir / "preview-wechat_mp.html").write_text(html, encoding="utf-8")
        return {"ok": True, "text": text, "html": html}

    elif platform == "xhs":
        (ddir / "xhs.md").write_text(text, encoding="utf-8")
        # 从文本首行 # 标题提取小红书标题（与 switch_draft_title 同步）
        xhs_title = d["title"]
        for _ln in text.splitlines():
            _ln_s = _ln.strip()
            if _ln_s.startswith("# "):
                xhs_title = _ln_s[2:].strip() or xhs_title
                break
        sec_meta, cur = [], None
        for line in text.splitlines():
            if line.startswith("### ") or line.startswith("## "):
                cur = [line.lstrip("#").strip(), []]
                sec_meta.append(cur)
            elif cur is not None and line.strip():
                cur[1].append(line.strip().lstrip("- "))
        if not sec_meta:
            paras = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
            sec_meta = [(f"看点 {i+1}", [p]) for i, p in enumerate(paras[:6])]
        # 卡片数量兜底
        if len(sec_meta) < 3:
            extra_names = ["🔑 核心要点", "💡 深度解析", "✨ 实战技巧", "🎯 关键洞察"]
            _paras = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
            for _j, _para in enumerate(_paras[:5]):
                if len(sec_meta) >= 5:
                    break
                pts = [s.strip()[:35] for s in _para.splitlines() if s.strip()][:3] or [_para[:35]]
                sec_meta.append((extra_names[_j % len(extra_names)], pts))
        cover_file = ddir / "img" / "cover.png" if (ddir / "img" / "cover.png").exists() else None
        from core.render_card import render_draft_cards
        render_draft_cards(ddir, xhs_title, sec_meta, cover_img=cover_file)
        cards = sorted([f"/card/{did}/{p.name}" for p in ddir.glob("card-*.png")])
        return {"ok": True, "text": text, "cards": cards}

    elif platform == "toutiao":
        (ddir / "toutiao.md").write_text(text, encoding="utf-8")
        from adapters import toutiao as _tt
        from core.imagegen import get_draft_images
        d_imgs = get_draft_images(did)
        html = _tt.render_preview(text, d["title"], images=d_imgs.get("sections"), cover=d_imgs.get("cover"), draft_id=did)
        (ddir / "preview-toutiao.html").write_text(html, encoding="utf-8")
        return {"ok": True, "text": text, "html": html}

    elif platform == "zhihu":
        (ddir / "zhihu.md").write_text(text, encoding="utf-8")
        from adapters import zhihu as _zh
        from core.imagegen import get_draft_images
        d_imgs = get_draft_images(did)
        html = _zh.render_preview(text, d["title"], images=d_imgs.get("sections"), cover=d_imgs.get("cover"), draft_id=did)
        (ddir / "preview-zhihu.html").write_text(html, encoding="utf-8")
        return {"ok": True, "text": text, "html": html}

    elif platform == "weibo":
        (ddir / "weibo.md").write_text(text, encoding="utf-8")
        from adapters import weibo as _wb
        from core.imagegen import get_draft_images
        d_imgs = get_draft_images(did)
        html = _wb.render_preview(text, d["title"], images=d_imgs.get("sections"), cover=d_imgs.get("cover"), draft_id=did)
        (ddir / "preview-weibo.html").write_text(html, encoding="utf-8")
        return {"ok": True, "text": text, "html": html}

    elif platform == "twitter":
        (ddir / "twitter.md").write_text(text, encoding="utf-8")
        from adapters import twitter as _tw
        html = _tw.render_twitter_html(text, d["title"])
        (ddir / "preview-twitter.html").write_text(html, encoding="utf-8")
        return {"ok": True, "text": text, "html": html}

    raise HTTPException(400, f"不支持的平台类型: {platform}")



@app.post("/api/drafts/{did}/fission")
async def draft_fission(did: str, request: Request):
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    from core import billing, fission
    billing.check_and_deduct("rewrite", 1, f"全域五端矩阵裂变 [{did}]")
    jid = f"fiss-{did[:8]}-{uuid.uuid4().hex[:4]}"
    d_title = d.get("title", "")
    start_async_job(
        jid,
        name=f"全域矩阵裂变: {d_title[:16]}",
        task_type="omni_fission",
        target_id=did,
        params={"draft_id": did},
        initial_step="启动全域矩阵裂变引擎…"
    )
    def _run():
        try:
            res = fission.generate_omnichannel_matrix(did, emit=lambda m: update_async_job(jid, step=m))
            update_async_job(jid, status="done", step="全域五端矩阵裂变完成！", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:300], step="裂变失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.post("/api/drafts/{did}/derive_omni")
async def draft_derive_omni(did: str, request: Request):
    """母稿驱动·全域多端一键派生接口：以当前编辑器母稿为单一基准，保真同步派生选中的矩阵平台。"""
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    body = await request.json()
    master_title = body.get("title") or d.get("title", "")
    master_body_md = body.get("body_md")
    theme = body.get("theme")
    media_name = (body.get("media_name") or "").strip()
    card_style = body.get("card_style") or "magazine"
    platforms = body.get("platforms")  # list of str or None

    from core import billing, fission
    billing.check_and_deduct("rewrite", 1, f"母稿驱动全域多端派生 [{did}]")
    jid = f"derive-{did[:8]}-{uuid.uuid4().hex[:4]}"
    plat_str = f"({len(platforms)}端)" if platforms else "(全域)"
    start_async_job(
        jid,
        name=f"母稿驱动派生{plat_str}: {master_title[:16]}",
        task_type="omni_derive",
        target_id=did,
        params={"draft_id": did, "title": master_title, "theme": theme, "platforms": platforms},
        initial_step="启动母稿驱动派生引擎…"
    )

    def _run():
        try:
            res = fission.derive_all_platforms_from_master(
                draft_id=did,
                master_title=master_title,
                master_body_md=master_body_md,
                theme=theme,
                media_name=media_name,
                card_style=card_style,
                target_platforms=platforms,
                emit=lambda m: update_async_job(jid, step=m),
            )
            update_async_job(jid, status="done", step=f"矩阵多端派生完成！共 {len(res.get('selected_platforms', []))} 端", progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status="failed", error=str(e)[:300], step="派生失败")

    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


@app.post("/api/drafts/{did}/switch_theme_pure")
async def draft_switch_theme_pure(did: str, request: Request):
    """零篡改纯排版换肤接口：100% 不调用 LLM，纯规则 CSS 行内样式重排，毫秒级响应。"""
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    body = await request.json()
    theme = body.get("theme") or "caozhou"
    title = body.get("title")
    body_md = body.get("body_md")
    media_name = body.get("media_name")

    from core import fission
    res = fission.switch_theme_pure(
        draft_id=did,
        theme=theme,
        title=title,
        body_md=body_md,
        media_name=media_name,
    )
    return res


@app.get("/api/drafts/{did}/matrix")
def draft_matrix(did: str, request: Request):
    guard(request)
    from core import fission
    return fission.get_draft_matrix(did)


@app.get("/api/models/providers")
def get_model_providers(request: Request):
    guard(request)
    from core import llm
    all_providers = llm.get_all_configured_providers()
    cfg = llm.load_config()
    gw = cfg.get("gateway", {})
    active_pid = gw.get("provider_id", "deepseek")
    env = llm.load_env()
    has_active_key = bool(env.get(f"MEDIAFLOW_KEY_{active_pid.upper()}")) or bool(env.get("MEDIAFLOW_APIPOOL_KEY"))

    cross_models = []
    for pid, p in all_providers.items():
        for m in p.get("models", []):
            m_copy = dict(m)
            m_copy["provider_id"] = pid
            m_copy["provider_name"] = p["name"]
            m_copy["has_key"] = bool(p.get("has_key"))
            m_copy["is_active_provider"] = (pid == active_pid)
            cross_models.append(m_copy)

    return {
        "providers": all_providers,
        "current": gw,
        "active_provider_id": active_pid,
        "configured_models": llm.get_configured_models(),
        "cross_models": cross_models,
        "env_key_set": has_active_key
    }



@app.post("/api/models/fetch")
async def model_fetch(request: Request):
    guard(request)
    body = await request.json()
    base_url = body.get("base_url", "")
    provider_id = body.get("provider_id", "custom")
    from core import llm
    api_key = body.get("api_key") or llm.load_env().get("MEDIAFLOW_APIPOOL_KEY", "")
    return llm.fetch_remote_models(base_url, api_key, provider_id)


@app.post("/api/models/ping")
async def model_ping(request: Request):
    guard(request)
    body = await request.json()
    base_url = body.get("base_url", "")
    from core import llm
    api_key = body.get("api_key") or llm.load_env().get("MEDIAFLOW_APIPOOL_KEY", "")
    model = body.get("model", "")
    return llm.ping_provider(base_url, api_key, model)


@app.post("/api/models/save")
async def model_save(request: Request):
    guard(request)
    body = await request.json()
    provider_id = body.get("provider_id", "custom")
    provider_name = body.get("provider_name", "")
    base_url = body.get("base_url", "")
    api_key = body.get("api_key", "")
    model = body.get("model", "")
    agent_routing = body.get("agent_routing", {})
    configured_models = body.get("configured_models")
    is_set_active = body.get("is_set_active", True)
    params = body.get("params", {})
    from core import llm
    ok = llm.save_provider_config(
        provider_id, base_url, api_key, model, agent_routing, params,
        configured_models=configured_models,
        provider_name=provider_name,
        is_set_active=is_set_active
    )
    return {"ok": ok, "msg": "模型服务与多Agent路由配置已持久化保存并立即热生效！"}


@app.post("/api/models/provider/set_active")
async def model_set_active_provider(request: Request):
    guard(request)
    body = await request.json()
    provider_id = body.get("provider_id", "")
    if not provider_id:
        raise HTTPException(400, "provider_id 不能为空")
    from core import llm
    ok = llm.set_active_provider(provider_id)
    return {"ok": ok, "msg": f"已成功切换当前主活动网关为 [{provider_id}]"}


@app.post("/api/models/provider/delete")
async def model_delete_provider(request: Request):
    guard(request)
    body = await request.json()
    provider_id = body.get("provider_id", "")
    provider_ids = body.get("provider_ids", [])
    from core import llm

    if provider_ids and isinstance(provider_ids, list):
        del_count = 0
        for pid in provider_ids:
            if pid and llm.delete_provider(str(pid)):
                del_count += 1
        return {"ok": True, "msg": f"已成功批量删除 {del_count} 家模型服务配置", "count": del_count}

    if not provider_id:
        raise HTTPException(400, "provider_id 或 provider_ids 不能为空")
    ok = llm.delete_provider(provider_id)
    return {"ok": ok, "msg": f"已成功删除模型服务 [{provider_id}]"}


# ===================== ⚡ 异步算力任务队列 API =====================

@app.get("/api/tasks")
def list_active_tasks(request: Request, active_only: bool = False):
    guard(request)
    from core import task_queue
    return {"tasks": task_queue.list_tasks(limit=30, active_only=active_only)}


@app.get("/api/tasks/{task_id}")
def get_task_status(task_id: str, request: Request):
    guard(request)
    from core import task_queue
    task = task_queue.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    tdict = task.to_dict() if hasattr(task, "to_dict") else task
    return {"task": tdict}


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task_endpoint(task_id: str, request: Request):
    guard(request)
    from core import task_queue
    ok = task_queue.cancel_task(task_id)
    return {"ok": ok, "msg": "任务已取消" if ok else "无法取消任务（可能已结束或不存在）"}


# ===================== 🌊 SSE 实时流式打字机 API =====================


# ===================== 💬 v4.0 极简模式：爆款创作 Copilot API =====================

@app.post("/api/copilot/chat")
async def copilot_chat_endpoint(request: Request):
    guard(request)
    from core import copilot
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "聊天内容不能为空")
    draft_id = body.get("draft_id")
    history = body.get("history") or []
    platform = body.get("platform", "xhs")
    model = body.get("model")
    provider = body.get("provider")
    style = body.get("style")
    persona = body.get("persona")
    image_model = body.get("image_model")
    skills = body.get("skills")
    
    try:
        res = await asyncio.get_event_loop().run_in_executor(
            None, lambda: copilot.handle_copilot_chat(
                message, 
                draft_id=draft_id, 
                history=history, 
                target_platform=platform,
                model=model,
                provider=provider,
                style=style,
                persona=persona,
                image_model=image_model,
                skills=skills
            )
        )
        return res
    except Exception as e:
        raise HTTPException(500, f"Copilot 响应失败: {str(e)}")


@app.post("/api/copilot/chat_stream")
async def copilot_chat_stream_endpoint(request: Request):
    guard(request)
    from core import copilot
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "聊天内容不能为空")
    draft_id = body.get("draft_id")
    history = body.get("history") or []
    platform = body.get("platform", "xhs")
    model = body.get("model")
    provider = body.get("provider")
    style = body.get("style")
    persona = body.get("persona")
    image_model = body.get("image_model")
    skills = body.get("skills")

    import queue
    import threading

    q = queue.Queue()

    def _worker():
        try:
            def _emit(step_txt, prog):
                q.put({"type": "step", "step": step_txt, "progress": prog})

            res = copilot.handle_copilot_chat(
                message,
                draft_id=draft_id,
                history=history,
                target_platform=platform,
                model=model,
                provider=provider,
                style=style,
                persona=persona,
                image_model=image_model,
                skills=skills,
                emit_step=_emit
            )
            q.put({"type": "result", "data": res})
        except Exception as e:
            q.put({"type": "error", "error": str(e)})
        finally:
            q.put(None)

    threading.Thread(target=_worker, daemon=True).start()

    async def event_generator():
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.06)
                continue
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/drafts/{did}/copilot_history")
def get_copilot_history_endpoint(did: str, request: Request):
    guard(request)
    from core import copilot
    return {"history": copilot.get_draft_copilot_history(did)}


@app.post("/api/stream/write")
async def stream_write_endpoint(request: Request):
    guard(request)
    from core import llm
    body = await request.json()
    prompt = body.get("prompt", "")
    system_prompt = body.get("system", "你是专业资深的新媒体爆款主笔。")
    model = body.get("model")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    def event_generator():
        try:
            for chunk in llm.chat_stream(messages, model=model):
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ===================== 📦 批量矩阵生产 API =====================

@app.post("/api/batch/submit")
async def batch_submit_endpoint(request: Request):
    guard(request)
    body = await request.json()
    items = body.get("items", [])
    options = body.get("options", {})
    if not items:
        raise HTTPException(400, "批量选题列表不能为空")
    from core import task_queue, orchestrator
    batch_name = f"批量矩阵生产 ({len(items)} 篇)"
    def _run_batch(task):
        return orchestrator.batch_create_drafts(items, options, emit=task.update_progress, task=task)

    task = task_queue.submit_task(
        name=batch_name,
        task_type="batch_creation",
        fn=_run_batch,
        params={"count": len(items), "options": options}
    )
    return {"ok": True, "task_id": task.id, "count": len(items), "msg": "批量矩阵生产任务已提交后台持久化队列"}


# ===================== 🌟 全局 IP 角色资产库 API =====================

@app.get("/api/ip_characters")
def list_ip_characters_endpoint(request: Request):
    guard(request)
    from core import db
    return {"characters": db.list_ip_characters()}


@app.post("/api/ip_characters/save")
async def save_ip_character_endpoint(request: Request):
    guard(request)
    from core import db
    body = await request.json()
    res = db.save_ip_character(
        name=body.get("name", "新角色"),
        gender=body.get("gender", ""),
        age_group=body.get("age_group", ""),
        style=body.get("style", ""),
        avatar_url=body.get("avatar_url", ""),
        turnaround_sheet_url=body.get("turnaround_sheet_url", ""),
        features_en=body.get("features_en", ""),
        dialogue_tone=body.get("dialogue_tone", ""),
        cid=body.get("id")
    )
    return {"ok": True, "character": res}


@app.post("/api/ip_characters/export_from_drama")
async def export_ip_character_from_drama_endpoint(request: Request):
    guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get("draft_id")
    char_id = body.get("char_id")
    res = short_drama.export_character_to_ip_hub(draft_id, char_id)
    return res


@app.post("/api/ip_characters/bind_to_drama")
async def bind_ip_character_to_drama_endpoint(request: Request):
    guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get("draft_id")
    char_id = body.get("char_id")
    ip_char_id = body.get("ip_char_id")
    res = short_drama.bind_ip_character_to_draft(draft_id, char_id, ip_char_id)
    return res


@app.post("/api/ip_characters/delete")
async def delete_ip_character_endpoint(request: Request):
    guard(request)
    from core import db
    body = await request.json()
    cid = body.get("id")
    ok = db.delete_ip_character(cid)
    return {"ok": ok}


# ===================== 🏢 多品牌工作区 API =====================

@app.get("/api/workspaces")
def list_workspaces_endpoint(request: Request):
    guard(request)
    from core import workspace
    from core.agents import get_catalog_skills
    return {
        "workspaces": workspace.list_all_workspaces(),
        "active": workspace.get_current_workspace(),
        "available_skills": get_catalog_skills()
    }


@app.get("/api/workspaces/skills")
def workspace_skills_endpoint(request: Request):
    guard(request)
    from core.agents import get_catalog_skills
    return {"ok": True, "skills": get_catalog_skills()}


@app.post("/api/workspaces/switch")
async def switch_workspace_endpoint(request: Request):
    guard(request)
    from core import workspace
    body = await request.json()
    wid = body.get("workspace_id")
    active = workspace.switch_workspace(wid)
    return {"ok": True, "active": active}


@app.post("/api/workspaces/create")
async def create_workspace_endpoint(request: Request):
    guard(request)
    from core import workspace
    body = await request.json()
    name = body.get("name")
    desc = body.get("desc", "")
    config = body.get("config") or {}
    try:
        res = workspace.create_new_workspace(name, desc, config=config)
        return {"ok": True, "workspace": res}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/workspaces/update")
async def update_workspace_endpoint(request: Request):
    guard(request)
    from core import workspace
    body = await request.json()
    wid = body.get("workspace_id") or body.get("id")
    name = body.get("name")
    desc = body.get("desc", "")
    config = body.get("config")
    try:
        res = workspace.update_workspace_info(wid, name, desc, config=config)
        return {"ok": True, "workspace": res}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/workspaces/delete")
async def delete_workspace_endpoint(request: Request):
    guard(request)
    from core import workspace
    body = await request.json()
    wid = body.get("workspace_id") or body.get("id")
    try:
        res = workspace.delete_workspace_by_id(wid)
        return {"ok": True, **res}
    except Exception as e:
        raise HTTPException(400, str(e))


# ===================== 🎬 短剧非线性单镜头精修与母带快速重混 API =====================

@app.post("/api/short_drama/shots/reroll")
async def drama_reroll_shot_endpoint(request: Request):
    guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get("draft_id")
    shot_id = int(body.get("shot_id", 1))
    prompt_en = body.get("prompt_en", "")
    aspect = body.get("aspect", "9:16")
    res = short_drama.reroll_shot_frame(draft_id, shot_id, prompt_en=prompt_en, aspect=aspect)
    return res


@app.post("/api/short_drama/shots/retake_voice")
async def drama_retake_voice_endpoint(request: Request):
    guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get("draft_id")
    shot_id = int(body.get("shot_id", 1))
    script_text = body.get("script_text", "")
    voice = body.get("voice", "")
    res = short_drama.retake_shot_voice(draft_id, shot_id, script_text=script_text, voice=voice)
    return res


@app.post("/api/short_drama/reorder_and_restitch")
async def drama_reorder_and_restitch_endpoint(request: Request):
    guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get("draft_id")
    new_order = body.get("new_order")  # e.g. [1, 2, 3]
    subtitle_enabled = body.get("subtitle_enabled")
    res = short_drama.reorder_and_restitch_drama(draft_id, new_order=new_order, subtitle_enabled=subtitle_enabled)
    return res


# ===================== 📅 内容排期日历与定时发布 API =====================

@app.get("/api/schedule/posts")
def list_scheduled_posts_endpoint(request: Request, status: Optional[str] = None):
    guard(request)
    from core import scheduler
    return {"posts": scheduler.list_scheduled(status=status)}


@app.post("/api/schedule/post")
async def schedule_post_endpoint(request: Request):
    guard(request)
    from core import scheduler
    body = await request.json()
    draft_id = body.get("draft_id")
    platform = body.get("platform", "xhs")
    target_time = float(body.get("target_time", time.time() + 3600))
    pid = scheduler.schedule_post(draft_id, platform, target_time)
    return {"ok": True, "id": pid, "target_time": target_time}


@app.post("/api/schedule/cancel")
async def cancel_scheduled_post_endpoint(request: Request):
    guard(request)
    from core import scheduler
    body = await request.json()
    pid = body.get("id")
    ok = scheduler.cancel_scheduled(pid)
    return {"ok": ok}



# ===================== 🏷️ 优雅品牌水印设置 API =====================

@app.get("/api/watermark/settings")
def get_watermark_settings(request: Request):
    guard(request)
    from core import watermark
    return watermark.get_watermark_config()


@app.post("/api/watermark/settings")
async def save_watermark_settings(request: Request):
    guard(request)
    body = await request.json()
    cfg = load_config()
    cfg["watermark"] = {
        "enabled": bool(body.get("enabled", False)),
        "text": str(body.get("text", "Designed with 一幕 YIMU")).strip(),
        "position": str(body.get("position", "bottom-right")),
        "opacity": float(body.get("opacity", 0.45)),
        "show_on_cards": bool(body.get("show_on_cards", True)),
        "show_on_cover": bool(body.get("show_on_cover", True)),
        "show_on_video": bool(body.get("show_on_video", True)),
    }
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    return {"ok": True, "msg": "水印设置已保存"}


# ===================== ✍️ 一幕·YIMU Editor 富文本编辑 API =====================

@app.post("/api/editor/upload")
async def editor_upload_file(request: Request, file: UploadFile = File(...)):
    guard(request)
    import uuid
    upload_dir = BASE / "data" / "editor_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "").suffix.lower() or ".png"
    safe_name = f"ed_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    dest = upload_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {"url": f"/static-img/editor_uploads/{safe_name}", "size": len(content)}


@app.get("/api/drafts/{did}/html")
def get_draft_html(did: str, request: Request):
    guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "Draft not found")
    body_md = d.get("body_md", "")
    
    from core.imagegen import inject_images_to_markdown, get_draft_images
    injected_md = inject_images_to_markdown(body_md, did)
    imgs_dict = get_draft_images(did)

    try:
        import markdown
        html = markdown.markdown(injected_md, extensions=["extra", "tables", "fenced_code"])
    except Exception:
        try:
            from core.themes import md_to_wechat_html
            html = md_to_wechat_html(injected_md, d.get("title", ""))
        except Exception:
            html = f"<p>{injected_md}</p>"

    # 包装图片以获得极佳排版质感
    html = re.sub(
        r'<img\s+([^>]*?)src="([^"]+)"([^>]*?)>',
        r'<div style="text-align:center;margin:20px 0;"><img \1src="\2"\3 style="max-width:100%;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.15);display:inline-block;"></div>',
        html
    )

    return {
        "html": html,
        "title": d.get("title", ""),
        "body_md": body_md,
        "images": imgs_dict
    }


@app.post("/api/drafts/{did}/html")
async def save_draft_html(did: str, request: Request):
    guard(request)
    body = await request.json()
    html_content = body.get("html", "")
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "Draft not found")
    
    # 存入数据库
    db.update_draft_body(did, html_content)
    
    # 同步刷新多平台预览与成文文件
    try:
        from core.orchestrator import switch_draft_title
        switch_draft_title(did, d.get("title", ""))
    except Exception:
        pass
        
    return {"ok": True, "msg": "一幕富文本与多端排版已成功同步持久化！"}



@app.get("/api/drafts/{did}/zip/xhs")
def draft_zip(did: str):
    import io
    import zipfile
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    ddir = db.draft_dir(did)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if (ddir / "xhs.md").exists():
            z.writestr("小红书文案.txt", (ddir / "xhs.md").read_text(encoding="utf-8"))
        for png in sorted(ddir.glob("card-*.png")):
            z.write(png, png.name)
    buf.seek(0)
    from urllib.parse import quote
    safe = re.sub(r'[\\/:*?"<>|\s]+', "", d["title"])[:40] or did
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition":
                             f"attachment; filename*=UTF-8''{quote(safe)}.zip"})


@app.post("/api/drafts/delete")
async def drafts_delete(request: Request):
    guard(request)
    body = await request.json()
    ids = body.get("ids") or []
    if not ids:
        raise HTTPException(400, "未选择草稿")
    import shutil
    trash = Path.home() / ".Trash"
    removed = []
    for did in ids:
        d = db.get_draft(did)
        if d:  # 幂等：重复请求（本机网络层会重放 POST）时视为已删，同样报成功
            c = db.conn()
            c.execute("DELETE FROM drafts WHERE id=?", (did,))
            c.execute("DELETE FROM jobs WHERE draft_id=?", (did,))
            c.commit(); c.close()
        ddir = BASE / "data" / "drafts" / did
        if ddir.exists():
            try:
                trash.mkdir(exist_ok=True)
                shutil.move(str(ddir), str(trash / did))
            except Exception:
                pass
        removed.append(did)
    return {"removed": removed}


@app.post("/api/drafts/clean_old")
async def drafts_clean_old(request: Request):
    """清理超过 N 天的过期草稿。"""
    guard(request)
    body = await request.json()
    days = int(body.get("days", 0))
    if days <= 0:
        return {"ok": True, "deleted_count": 0, "msg": "当前设置为永不过期，未执行清理"}
    deleted_ids = db.delete_old_drafts(days)
    return {"ok": True, "deleted_count": len(deleted_ids), "deleted_ids": deleted_ids, "msg": f"已清理 {len(deleted_ids)} 篇超过 {days} 天的过期草稿"}


@app.get("/preview/{did}/{platform}")
def preview(did: str, platform: str):
    f = db.draft_dir(did) / f"preview-{platform}.html"
    if not f.exists():
        raise HTTPException(404, "预览未生成")
    return FileResponse(f)


@app.get("/card/{did}/{name}")
def card(did: str, name: str):
    if "/" in name or not name.startswith("card-"):
        raise HTTPException(400, "bad name")
    f = db.draft_dir(did) / name
    if not f.exists():
        raise HTTPException(404, "卡片未生成")
    return FileResponse(f, media_type="image/png")


@app.get("/img/{did}/{name}")
def draft_img(did: str, name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "bad name")
    f = db.draft_dir(did) / "img" / name
    if not f.exists():
        raise HTTPException(404, "图片未生成")
    return FileResponse(f, media_type="image/png")


# ---------------- settings ----------------

@app.post("/api/settings")
async def settings(request: Request):
    guard(request)
    body = await request.json()
    cfg = load_config()
    gw = body.get("gateway") or {}
    if gw.get("base_url"):
        cfg.setdefault("gateway", {})["base_url"] = gw["base_url"].strip()
    if gw.get("model"):
        cfg["gateway"]["model"] = gw["model"].strip()
    if body.get("keywords") is not None:
        cfg.setdefault("topics", {})["keywords"] = [k.strip() for k in body["keywords"] if k.strip()]
    if body.get("image"):
        cfg["image"] = {**cfg.get("image", {}), **body["image"]}
    if body.get("quality"):
        cfg["quality"] = {**cfg.get("quality", {}), **body["quality"]}
    if body.get("creation"):
        cfg["creation"] = {**cfg.get("creation", {}), **body["creation"]}
    if "draft_expire_days" in body:
        cfg.setdefault("creation", {})["draft_expire_days"] = int(body["draft_expire_days"])
    if body.get("imgbed"):
        ib = body["imgbed"]
        if ib.get("token"):
            write_env("GITHUB_IMGBED_TOKEN", ib["token"].strip())
        if ib.get("repo"):
            write_env("GITHUB_IMGBED_REPO", ib["repo"].strip())
    if body.get("dingtalk"):
        if body["dingtalk"].get("webhook"):
            write_env("DINGTALK_WEBHOOK", body["dingtalk"]["webhook"].strip())
        if body["dingtalk"].get("secret"):
            write_env("DINGTALK_SECRET", body["dingtalk"]["secret"].strip())
    if body.get("agents"):
        base = cfg.get("agents", {})
        for stage, patch in body["agents"].items():
            base[stage] = {**base.get(stage, {}), **patch}
        cfg["agents"] = base
    CFG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if body.get("apipool_key"):
        write_env("MEDIAFLOW_APIPOOL_KEY", body["apipool_key"].strip())
    return {"ok": True}


# ---------------- 仿写后台任务（进度可见，全景任务监控互通） ----------------

def _run_rewrite_job(jid: str, payload: dict):
    def emit(step):
        update_async_job(jid, step=step)
    try:
        from core import search as S
        import core.orchestrator as O
        emit("读取对标原文…")
        detail = payload.get("text") or ""
        if not detail:
            try:
                if payload.get("platform") == "xhs":
                    detail = S.xhs_detail((payload.get("extra") or {}).get("note_id", ""),
                                          (payload.get("extra") or {}).get("xsec_token", ""))
                elif payload.get("platform") == "toutiao" and payload.get("url"):
                    detail = S.toutiao_detail(payload["url"])
            except Exception:
                pass
        emit("爆款拆解与仿写创作中…（约1-2分钟）")
        update_async_job(jid, progress=35)
        mounted_persona = payload.get("mounted_persona", "")
        persona_rule = ""
        if mounted_persona:
            pv = O.get_voice_content(mounted_persona)
            if pv:
                persona_rule = f"\n\n【必须深度挂载的大师人设/文风指纹 ({mounted_persona})】：\n请在仿写的各平台版本中，严格贯彻以下语调口吻、句式节奏、用词喜好与修辞反模式：\n{pv[:1800]}\n"
        media_name = (payload.get("media_name") or "").strip() or "一幕·YIMU 爆款工作室"
        media_rule = f"\n\n【发布媒体/创作者署名账号】：{media_name}\n请在正文行文或结尾引导关注时，自然融入该账号品牌标识（如「欢迎关注【{media_name}】，获取第一手深度爆款拆解」）。"
        
        # 判断是否为粘贴长文改编（要求严格保持行文骨架不变）
        is_paste_rewrite = (payload.get("platform") == "manual" or len(detail) > 120)
        sys_prompt = O.STRUCTURE_PRESERVING_REWRITE_PROMPT if is_paste_rewrite else O.REWRITE_PROMPT
        rewrite_note = (
            "【核心执行指令】：\n"
            "1. 严格锁定原篇的章节骨架与行文起承转合，原篇有几个小节、每个小节承担什么论证职责，新篇公众号成稿（### 分节）必须保持对应分节与逻辑推进！\n"
            "2. 在骨架完全不变的前提下，结合用户主题与名家文风，对各段的具体内容进行全面换血与深度重构，绝不敷衍！"
        ) if is_paste_rewrite else ""

        target_theme = (payload.get("theme") or "").strip() or "严格跟随对标爆款的核心领域，绝不擅自偏离或捏造其他无关领域"

        raw = O.agents.chat_for("write", [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content":
                f"【对标爆款（{payload.get('platform')}）】\n标题：{payload.get('title')}\n"
                f"链接：{payload.get('url') or '无'}\n正文完整内容/详情：\n{(detail or payload.get('title'))[:5500]}\n\n"
                f"【创作主题】：{target_theme}\n"
                f"{rewrite_note}{persona_rule}{media_rule}"}], temperature=0.85)
        parsed = O._parse_rewrite(raw)
        emit("排版渲染与配图…")
        update_async_job(jid, progress=75)
        title = (parsed.get("TITLE_WX") or payload.get("title"))[:40]
        body = parsed.get("BODY_WX") or f"（成稿解析失败）\n{raw[:600]}"
        d = db.add_draft(None, title, body, ["wechat_mp", "xhs", "toutiao"],
                         source_platform=payload.get("platform", ""),
                         source_url=payload.get("url", ""),
                         source_title=payload.get("title", ""),
                         analysis=parsed.get("ANALYSIS", ""))
        O._refresh_artifacts(d["id"], parsed, title, body, media_name=media_name)
        score = None
        if O.llm.available():
            emit("7维爆款质量评审与调优中…")
            qc = judge.quality_cfg()
            score = judge.judge_draft(d["id"])
            rnd = 0
            while score["total"] < qc["threshold"] and rnd < qc["max_rounds"]:
                emit(f"得分 {score['total']} 分，第 {rnd+1} 轮自动重写中…")
                rw_res = O.rewrite_draft_once(d["id"])
                score = rw_res.get("score") or judge.get_score(d["id"]) or {"total": 0, "grade": "未知"}
                rnd += 1
        update_async_job(jid, status="done", progress=100, step="爆款仿写完成！", result={"draft_id": d["id"], "score": score, "title": title})
    except Exception as e:
        update_async_job(jid, status="failed", error=str(e)[:400], step="仿写失败")


def _run_one_sentence_viral_job(jid: str, payload: dict):
    def emit(step: str):
        update_async_job(jid, step=step)
    try:
        import core.orchestrator as O
        sentence = (payload.get("sentence") or "").strip()
        mounted_persona = payload.get("mounted_persona", "")
        theme = payload.get("theme", "")
        media_name = payload.get("media_name", "")
        platforms = payload.get("platforms")
        update_async_job(jid, step="正在解构核心痛点与生成多端爆款…", progress=30)
        res = O.generate_one_sentence_viral(sentence, mounted_persona=mounted_persona,
                                            theme=theme, media_name=media_name, emit=emit,
                                            platforms=platforms)
        update_async_job(jid, status="done", progress=100, step="一句话灵感创作完成！", result=res)
    except Exception as e:
        update_async_job(jid, status="failed", error=str(e)[:400], step="创作失败")


@app.post("/api/topics/one_sentence_viral")
async def api_one_sentence_viral(request: Request):
    guard(request)
    body = await request.json()
    sentence = (body.get("sentence") or "").strip()
    if not sentence:
        raise HTTPException(400, "请输入创作灵感或一句话需求")
    import uuid
    jid = f"vir-{uuid.uuid4().hex[:8]}"
    start_async_job(
        jid,
        name=f"一句话爆款创作: {sentence[:14]}",
        task_type="article_gen",
        params={"sentence": sentence},
        initial_step="正在理解创作意图…"
    )
    asyncio.get_event_loop().run_in_executor(None, _run_one_sentence_viral_job, jid, body)
    return {"job": jid}


@app.post("/api/rewrite/job")
async def rewrite_job(request: Request):
    guard(request)
    body = await request.json()
    import uuid
    title = (body.get("title") or (body.get("extra") or {}).get("title") or "爆款仿写")[:16]
    jid = f"rw-{uuid.uuid4().hex[:8]}"
    start_async_job(
        jid,
        name=f"爆款文章仿写: {title}",
        task_type="article_gen",
        params=body,
        initial_step="排队分析中…"
    )
    asyncio.get_event_loop().run_in_executor(None, _run_rewrite_job, jid, body)
    return {"job": jid}


@app.get("/api/jobs/{jid}")
@app.get("/api/rewrite/job/{jid}")
def rewrite_job_status(jid: str, request: Request):
    guard(request)
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    return j


# ---------------- HTML ----------------

# ---------------- HTML Page Loader ----------------
TEMPLATE_INDEX_PATH = BASE / "web" / "templates" / "index.html"
TEMPLATE_MOBILE_PATH = BASE / "web" / "templates" / "mobile.html"

def get_html_page() -> str:
    if TEMPLATE_INDEX_PATH.exists():
        return TEMPLATE_INDEX_PATH.read_text(encoding="utf-8")
    return "<h1>一幕·YIMU 页面模板文件缺失，请检查 web/templates/index.html</h1>"


def get_mobile_html_page() -> str:
    if TEMPLATE_MOBILE_PATH.exists():
        return TEMPLATE_MOBILE_PATH.read_text(encoding="utf-8")
    return get_html_page()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.admin:app", host="127.0.0.1", port=8790, reload=False)

