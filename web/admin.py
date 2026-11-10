# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 爆款工作室（FastAPI :8790）。

面板：搜索仿写 / 选题 / 草稿工作台 / 发布 / 设置。
v2：仿写按钮禁用态+进度、toast、草稿左右分栏工作区、手机壳预览、评分Tab、
    重新评分/定向重写、多主题排版、AI 配图、考核配置。
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import re
import json
import sys
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Optional, List, Dict, Any

# 模块级 logger：历史上 advideo / aivideo 两处 except 里写了不存在的 `log`，
# NameError 会把真实异常顶掉，前端只看到 500 而没有原因。这里补上真实对象。
logger = logging.getLogger("yimu.web")

# ⭐ Windows 兼容：控制台默认编码是 cp936，任何 print 里的 emoji / 生僻字都会抛
#    UnicodeEncodeError。这类 print 夹在长链路（改写、生成）中间，会让业务看起来
#    "莫名其妙失败"，而同一段代码在 macOS/Linux 上跑得好好的。
#    统一把标准流切到 UTF-8 + replace，让编码问题不再伪装成业务 bug。
for _stream_name in ("stdout", "stderr"):
    try:
        _stream = getattr(sys, _stream_name, None)
        _enc = (getattr(_stream, "encoding", "") or "").lower().replace("-", "").replace("_", "")
        if _stream is not None and hasattr(_stream, "reconfigure") and _enc != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import version                                       # noqa: E402

import yaml                                          # noqa: E402
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402
from fastapi.responses import (FileResponse, HTMLResponse,   # noqa: E402
                               JSONResponse, Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles          # noqa: E402
from fastapi.routing import APIRoute                # noqa: E402

from core import db, judge, orchestrator             # noqa: E402
from core import diagnostics as diag                 # noqa: E402

# ⭐ 诊断日志尽早安装：此后任何 logger.exception、线程/进程未捕获异常、
#    HTTP 4xx/5xx 都会自动留档，用户可在「设置 → 系统诊断日志」一键复制。
diag.install()
from core.llm import load_config, load_env           # noqa: E402
import os as _os
for _k, _v in load_env().items():
    _os.environ.setdefault(_k, _v)
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
# R4-8：CSRF 防护 + 安全响应头（CSP / X-Frame-Options / Referrer-Policy 等）。
# 注意中间件顺序：Starlette 按注册**逆序**执行，靠后注册的先跑（ outermost）。
# 这里把 CSRF 注册在后 → CSRF 在最外层；SecurityHeaders 在内层包住业务路由。
# ⚠️ 但这样 CSRF 自己返回的 403 不会经过 SecurityHeaders。
# 因此改为：SecurityHeaders 在外层（保证任何响应—including 403—都带头），
# CSRF 在内层（被外层包住，403 也会被外层补上安全头）。
from core.security_middleware import (  # noqa: E402
    CSRFMiddleware, SecurityHeadersMiddleware,
)

app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# R3-9 草稿归属隔离（fail-closed）
# ---------------------------------------------------------------------------
#
# ⚠️ 为什么要做成「路由类」而不是逐个端点加校验：
#   全仓有 **80+ 个路由**带 {did} 路径参数（/api/drafts/{did}/...、
#   /img/{did}/{name}、/card/{did}/{name}、/video/drama/{did}/... 等）。
#   逐个改必然漏——而漏一个就等于越权仍可利用（实测确认
#   drafts.user_id 全库为空串，任何登录用户拿到 did 即可读他人稿件与图片）。
#   做成路由基类后，**新增路由自动受保护**，不存在「忘了加」的可能。
#
# ⭐ 为什么用APIRoute 子类而不是 HTTP 中间件：
#   Starlette 的中间件在**路由匹配之前**执行，此时 scope 里还没有
#   "route"/"path_params"，拿不到 did。路由类包裹的是 handler，
#   执行时 path_params 已就绪，是唯一能可靠读到 did 的位置。
#
# 判定逻辑：
#   1. 路由路径含 {did} → 取出 did；
#   2. 取当前登录用户（复用 R1 的 get_current_user，内含 is_active 校验，
#      因此**封禁用户会被这里与 guard 双重拦住**）；
#   3. 非管理员 → 必须 db.is_draft_owner(draft, user_id)，否则 404。
#
# ⚠️ 有意放行的例外（否则会打断公网分享功能）：
#   - /s/{token} 分享页及其二维码/海报：地址里**只有令牌、没有 did**，
#     令牌→稿件映射只存在于服务端库，无法靠改 did 越权（R5-5 已验证）。
#     分享页里引用的图片改为 /s/{token}/img/... 令牌路由（见 share_media），
#     因此 /img/{did}/... 不再需要对外公开。
#   - /preview/{did}/{platform} **不再豁免**：它只是把本地文件吐出来，
#     与分享链路无关（分享页由 /s/{token} 直接读文件渲染）。
#     历史上把它列进豁免前缀等于「知道 did 就能读他人排版稿」。
# R11：DraftOwnerRoute 抽出至 web/draft_guard.py（独立稳定模块，
# 类身份跨 importlib.reload 不变；v14 强化语义已并入该模块）。
from web.draft_guard import DraftOwnerRoute, DID_OWNER_EXEMPT_PREFIXES as _DID_OWNER_EXEMPT_PREFIXES  # noqa: E402,F401

# 必须在**任何路由注册之前**设置 route_class，否则已注册的路由不会走新类
app.router.route_class = DraftOwnerRoute
# R4-5 安全收窄：此前把整个 data/ 目录挂成 HTTP 可访问
#（`GET /static-img/data/video_config.json` 可直接下载到含 pexels_api_key 明文的配置）。
# 全仓核查结论：/static-img 的**唯一**真实使用点是富文本编辑器上传回显
#（web/admin.py editor_upload_file → /static-img/editor_uploads/{name}）。
# 草稿配图/卡片全部走显式路由 /img/{did}/{name}、/card/{did}/{name}
# （FileResponse，不经过静态挂载），因此这里只挂 editor_uploads 一个子目录，
# 直链 /static-img/editor_uploads/xxx.png 保持可用，其余 data/ 内容一律 404。
_STATIC_UPLOAD_DIR = BASE / "data" / "editor_uploads"
_STATIC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static-img/editor_uploads", StaticFiles(directory=str(_STATIC_UPLOAD_DIR)), name="img")
# V14 对话附件：只有图片需要回显，单独挂一个目录（文档类附件只在内存里解析，不落盘）
_COPILOT_UPLOAD_DIR = BASE / "data" / "copilot_uploads"
_COPILOT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static-img/copilot_uploads", StaticFiles(directory=str(_COPILOT_UPLOAD_DIR)), name="copilot_img")
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
import secrets as _secrets  # noqa: E402
from core import secret_store as _secret_store  # noqa: E402
from core.db import DB_PATH as _MAIN_DB_PATH  # noqa: E402
_os.environ.setdefault("YIMU_DB_URL", "sqlite:///" + str(_MAIN_DB_PATH))
# studio.auth 在 import 期就要求 YIMU_SECRET_KEY，因此这里必须供给。
# ⚠️ 必须用**持久化**密钥（data/.secrets/session），不能再用启动时随机：
#    随机值会让每次重启都换签名密钥（全员掉线 + 已存 API Key 解不开），
#    且多 worker 之间互不认对方的 token。
if not _os.environ.get("YIMU_SECRET_KEY"):
    _os.environ["YIMU_SECRET_KEY"] = _secret_store.session_secret()
from studio.membership_router import router as membership_router  # noqa: E402
app.include_router(membership_router)
from app.routers import architecture_router  # noqa: E402
app.include_router(architecture_router)

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
            # ⭐ R2-5：生图要真扣 memberships 额度，必须带上调用者身份
            "user_id": str((user or {}).get("id") or ""),
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


def _draft_table_health() -> str:
    """把 draft_history 的真实列写进启动日志。

    改写失败最常见的原因是这张表缺列（旧库 / studio 建表版本），
    启动时记一次，导出日志第一屏就能看出来。
    """
    try:
        c = db.conn()
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(draft_history)")]
        finally:
            c.close()
        return ",".join(cols) or "表不存在"
    except Exception as e:
        return f"探测失败({e})"


@app.on_event("startup")
async def on_startup():
    # ⭐ 诊断日志：接管 asyncio 未处理异常，并把启动现场（环境快照）记一条，
    #    这样即使用户什么也没做，导出日志也能看到跑在什么环境上。
    try:
        diag.install_asyncio(asyncio.get_event_loop())
        # 只记一行；完整环境快照在导出文本的开头，不必重复一遍
        diag.record("system", "startup", status="ok",
                    detail=f"服务已启动 · 版本 {version.__version__}",
                    draft_tables=_draft_table_health())
    except Exception:
        pass
    try:
        from core.db import auto_heal_all_sqlite_databases
        auto_heal_all_sqlite_databases()
    except Exception as e:
        print(f"[Startup] SQLite数据库自愈轻微提示: {e}")
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
    # ⭐ 管理口令状态告警：未配置 ADMIN_PASSWORD 时管理接口不开放（fail-closed）
    _warn_admin_password_state()
    # ⭐ V8/P1-F：主生成链路 Key 示例检测（不阻断，仅醒目告警）
    _warn_main_chain_keys()

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


# ⭐ 诊断日志的 HTTP 采集层：任何 /api/ 失败与超慢请求都留档。
#   注册在 idempotent_posts 之后 → Starlette 逆序执行，本中间件在最外层，
#   因此连 idempotent_posts 自己抛的异常也能捕获。
_DIAG_THROTTLE: dict = {}


@app.middleware("http")
async def diagnostics_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    method = request.method
    path = request.url.path
    try:
        resp = await call_next(request)
    except Exception as exc:
        dt = time.perf_counter() - t0
        diag.capture_exc("http", f"{method} {path}", exc, elapsed=dt,
                         query=str(request.url.query or "")[:200])
        raise
    dt = time.perf_counter() - t0
    if path.startswith("/api/") and (resp.status_code >= 400 or dt > 8):
        # 同一接口同一状态码 5 秒内只记一次，避免前端轮询把缓冲区刷爆
        key = (path, resp.status_code)
        now = time.time()
        if now - _DIAG_THROTTLE.get(key, 0) > 5:
            _DIAG_THROTTLE[key] = now
            for k in [k for k, v in _DIAG_THROTTLE.items() if now - v > 60]:
                _DIAG_THROTTLE.pop(k, None)
            diag.http_event(method, path, resp.status_code, dt,
                            detail="慢请求（超过 8 秒）" if resp.status_code < 400 else "")
    return resp


# ---------------------------------------------------------------------------
# ⭐ 单机管理口令与 loopback 免密通行（fail-closed）
#
# 历史包袱（已下线，不得回退）：
#   _token() = sha256("mf|" + ADMIN_PASSWORD or缺省 "local-admin")
#   loopback 判定 = ADMIN_PASSWORD == "local-admin"
# 两者叠在一起的后果：.env 里没有 ADMIN_PASSWORD 时，_token() 退化成常量，
# 任何人算一次 sha256 就能伪造 mf_token Cookie 直接拿超级管理员；
# 而 loopback 免密分支因此恒为真，等于本机任何进程都是超管。
#
# 现在的规则：
#   1) ADMIN_PASSWORD 未配置 → 不签发任何管理 Cookie、拒绝管理员口令登录、
#      loopback 也不免密（没有口令就没有"默认口令"可免），并在启动时明确告警。
#   2) mf_token 改为进程内随机密钥签发，重启即失效，外部无法预测或伪造。
#   3) loopback 免密仅在已配置 ADMIN_PASSWORD 时保留，保证本地开发
#      （一键启动.command 会生成随机口令）开箱可用。
# ---------------------------------------------------------------------------

#: 管理会话密钥：**持久化**到 data/.secrets/admin_session（0600），
#: 重启/升级/多 worker 均复用同一份，外部仍不可预测。
#: ⚠️ 不要改回 token_hex(32) 的进程内随机：那会让每次重启全员掉线，
#:    且 --workers 2 时 A worker 签发的 Cookie 到 B worker 直接 401。
_MF_SESSION_SECRET = _secret_store.admin_session_secret()

#: 历史默认弱口令：即使 .env 里真的写了它，也不当作"已配置口令"处理
_WEAK_DEFAULT_PASSWORD = "local-admin"

#: ⭐ V8/P0-B：历史硬编码弱口令清单——命中任意一个一律视为「未配置」，
#: 堵住"123456/admin"全网超管后门（见 web/admin.py 登录路由 730 行）。
#: 仅列真正被历史代码显式接受的值；本地随机生成的强口令不受影响。
_WEAK_PASSWORDS = frozenset({"local-admin", "admin", "123456"})

_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def _admin_password() -> Optional[str]:
    """读取已配置的管理员口令；未配置或为历史弱口令时返回 None（fail-closed）。

    ⭐ V8/P0-B：历史实现把未配置回落到 _WEAK_DEFAULT_PASSWORD("local-admin")，
    且 730 行登录路由还硬放行 "123456"/"admin"，等于全网弱口令超管后门。
    现改为：未配置或命中弱口令清单一律视为「未配置」→ 不发管理 Cookie、
    拒绝管理员口令登录、loopback 不免密。
    """
    pwd = (load_env().get("ADMIN_PASSWORD") or "").strip()
    if not pwd:
        return None
    if pwd == _WEAK_DEFAULT_PASSWORD or pwd in _WEAK_PASSWORDS:
        return None
    return pwd


def _loopback_admin_allowed() -> bool:
    """loopback 免密放行：仅当已配置强口令时为 True（fail-closed）。

    ⭐ V8/P0-B：历史实现恒 True（本机任何进程=超管）。现与 _admin_password
    联动：未配置/弱口令 → False，本机不免密、get_current_user 返回 None。
    ⭐ R15.7 访问模式开关：YIMU_MULTIUSER=1 时关闭本机免密——转化为
       「多用户注册/登录」形态（家庭/团队/对外试用），注册流不再被覆盖。
    """
    if (_os.environ.get("YIMU_MULTIUSER") or "").strip().lower() in ("1", "true", "yes"):
        return False
    return _admin_password() is not None


def _warn_admin_password_state() -> None:
    """服务启动时打印管理口令配置状态（未配置即明确告警）。"""
    if _admin_password() is None:
        print(
            "[安全提示] 未配置 ADMIN_PASSWORD：管理员口令登录与本机免密通行均已关闭，"
            "管理相关接口需要登录会话。请设置 ADMIN_PASSWORD 环境变量"
            "（本地可运行「一键启动.command」或「一键启动.bat」自动生成随机口令）。"
        )
    else:
        print(
            "[安全提示] 已配置 ADMIN_PASSWORD：本机（loopback）访问将自动获得管理员权限，"
            "请勿将服务监听在 0.0.0.0 或公网。"
        )


#: ⭐ V8/P1-F：示例 API Key 识别集（与 gateway/main.py 保持一致）。
#: 命中即判定「主生成链路开箱不可用」，启动时醒目告警引导用户填 Key。
_PLACEHOLDER_API_KEYS = frozenset(
    {"", "test_key", "test", "your-api-key", "your_api_key", "sk-xxx", "xxx", "changeme", "placeholder"}
)


def _warn_main_chain_keys() -> None:
    """⭐ V8/P1-F：检查当前激活 provider 的 Key 是否为示例值。

    历史上 .env 里官方通道写成 "test_key" 示例，导致「一句话生成爆款」主链路
    开箱即 401，新手用户第一分钟就卡死。这里在启动时检测并给出中文引导，
    不阻断启动（真实 Key 用户完全不受影响）。
    """
    try:
        cfg = load_config()
        gw = cfg.get("gateway", {})
        active_pid = str(gw.get("provider_id", "")).strip()
        env = load_env()
        if not active_pid:
            return
        key = (env.get(f"MEDIAFLOW_KEY_{active_pid.upper()}") or env.get("MEDIAFLOW_APIPOOL_KEY") or "").strip()
        if key.lower() in _PLACEHOLDER_API_KEYS:
            shown = key if key else "空"
            print(
                f"[提示] 当前激活 AI 通道「{active_pid}」的 Key 还是示例值（{shown}），"
                "「一句话生成」主链路会鉴权失败。请在「设置 → 模型服务」填入该通道的"
                "真实 API Key（密钥保存在用户目录 secrets.env），或联网后自动领取官方"
                "试用凭证、或切换到已配置真实 Key 的通道。"
            )
    except Exception as e:  # 检测失败绝不阻断启动
        print(f"[提示] 主链路 Key 检测跳过: {e}")


def _token() -> str:
    """签发单机管理 Cookie 的值：由进程内随机密钥派生，外部不可预测。"""
    return hashlib.sha256(
        f"mf|{_MF_SESSION_SECRET}|{_admin_password() or 'no-password'}".encode()
    ).hexdigest()


def _is_loopback(request: Request) -> bool:
    """请求是否来自本机回环地址（若带反向代理转发头 X-Forwarded-For / X-Real-IP 且非回环，拒绝免密）。"""
    client_ip = request.client.host if request.client else ""
    if client_ip not in _LOOPBACK_HOSTS:
        return False
    headers = getattr(request, "headers", None) or {}
    xff = (headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    xri = (headers.get("x-real-ip") or headers.get("X-Real-Ip") or "").strip()
    if xff and xff not in _LOOPBACK_HOSTS:
        return False
    if xri and xri not in _LOOPBACK_HOSTS:
        return False
    return True


def _auto_admin_cookie(request: Request) -> dict:
    """本机免密通行时可直接下发的管理用户；否则空 dict。"""
    if _is_loopback(request) and _loopback_admin_allowed():
        return {"id": "u-admin", "username": "admin", "role": "admin", "plan": "enterprise"}
    return {}


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
                u.setdefault("avatar_url", "/static/img/default-avatar.png")
                return u

    # 2. 兼容旧单机模式全局 Token（进程内随机签发，外部不可伪造）
    if request.cookies.get("mf_token") == _token():
        return {"id": "u-admin", "username": "admin", "role": "admin", "plan": "enterprise", "avatar_url": "/static/img/default-avatar.png"}

    # 3. 本地 loopback 自动免密通行（映射为系统超级管理员）
    #    ⭐ fail-closed：未配置 ADMIN_PASSWORD 时不通行（原本恒为真）
    adm = _auto_admin_cookie(request)
    if adm and isinstance(adm, dict):
        adm.setdefault("avatar_url", "/static/img/default-avatar.png")
    return adm or None


def authed(request: Request) -> bool:
    return get_current_user(request) is not None


#: R5-6：当前请求的用户上下文（ContextVar）。
#: 为什么需要：require_credits(action, count, desc) 全仓 30+ 处调用，
#: 若为了埋点加 request 参数会改动所有调用点并与 R1 的既有测试冲突。
#: 改为在唯一的鉴权入口 guard() 里写入，require_credits 读取时
#: 若为空则退化为「无用户」，埋点仍记事件但不归属到人。
_CURRENT_USER: ContextVar = ContextVar("yimu_current_user", default=None)


def guard(request: Request) -> dict:
    u = get_current_user(request)
    if not u:
        raise HTTPException(401, "未登录或登录态已失效，请先登录")
    _CURRENT_USER.set(u)
    # 让 db 层知道"谁在请求"：活动工作区/工作区列表要按用户隔离，
    # 否则 A 切工作区会让 B 的草稿箱跟着换（见 core/db.py:set_request_user）。
    try:
        db.set_request_user(str((u or {}).get("id") or ""))
    except Exception:
        pass
    return u


def guard_admin(request: Request) -> dict:
    """管理员鉴权：已登录但角色不是 admin/owner → 403。

    ⭐ 与 guard 的区别：guard 只验"是不是有人登录"，
       管理类接口（发卡密、改配置等）必须再验角色，
       否则任何普通登录用户都能调用（参考 web/gateway_ui.py:_require_admin）。
    """
    u = guard(request)
    if (u or {}).get("role") not in ("admin", "owner"):
        raise HTTPException(403, "需要管理员权限，请使用管理员账号登录后重试")
    return u


#: 额度不足时给用户看的动作中文名（用于组装引导文案，避免开发者黑话）
_ACTION_LABELS = {
    "rewrite": "AI 仿写",
    "score": "质量评分",
    "refine_single": "单点润色",
    "refine_batch": "批量润色",
    "furnace_round": "内容打磨",
    "xhs_card_layout": "卡片排版",
    "drama_decompose": "短剧分镜解构",
    "drama_image": "图片生成",
    "drama_tts": "配音合成",
    "drama_render": "短剧成片渲染",
    "deep_distill": "深度蒸馏",
    "draft_create": "新建草稿",
}


#: 自备 Key 也**不能**免额度的动作：算力不在用户 Key 上。
#: drama_render = 本机 ffmpeg 渲染；drama_tts = 平台侧配音引擎。
#: 其余动作（改写/评分/润色/生图）确实消耗用户自己的模型额度，可免。
_BYOK_NEVER_FREE_ACTIONS = frozenset({"drama_render", "drama_tts"})


def require_credits(action: str, count: int = 1, desc: str = "") -> bool:
    """⭐ 扣算力额度并校验结果：余额不足直接抛 402，调用方必须 return。

    背景：全部扣费点此前都写成裸调用 ``billing.check_and_deduct(...)``，
    返回值被丢弃——余额不足时业务照样执行，等于额度形同虚设。
    现在统一走本函数：扣费成功返回 True，失败抛 HTTPException(402)
    并带上可读的升级引导文案，路由层因此不会执行后续业务动作。

    ⭐ R2-3：账本收敛到 memberships + ledger（不再是 core/billing 的 JSON 单例）。
       历史问题：``_load_data/_save_data`` 是**全局单例**，多用户共用一个
       billing.json —— A 充值会被 B 的写入覆盖，且余额不区分用户。
       现按当前登录用户（guard() 写入的 _CURRENT_USER）扣 memberships.credits_used，
       明细进ledger 表，逐笔可对账。
       ⚠️ 无登录上下文时（如后台线程直接调用）退化为单机 u-admin，
          与历史行为一致，但不再写 JSON。

    Raises:
        HTTPException: 402 额度不足（含所需额度与当前余额）。
    """
    from core import billing
    from studio import billing_adapter
    from studio import pricing

    unit = pricing.ACTION_COSTS.get(action, 500)
    need = unit * max(1, count)

    user = _CURRENT_USER.get() or {}
    user_id = str(user.get("id") or "")

    # ⭐ V10.0.0：当用户已配置并启用自备 API Key（BYOK）时，兑现「自备 Key 不扣会员额度」承诺
    # 🔴 但必须排除「根本不走用户 Key」的动作：短剧渲染跑在本机 ffmpeg、
    #    TTS 走平台侧引擎——这些对平台是真金白银的成本，
    #    原实现只要填了自己的 Key 就全免，等于把自毁开关交给用户。
    #    判定口径：动作的算力是否真的由用户 Key 承担。
    if user_id and action not in _BYOK_NEVER_FREE_ACTIONS:
        try:
            from core import auth as _core_auth
            _u_cfg = _core_auth.get_active_user_llm_config(user_id)
            if _u_cfg and _u_cfg.get("plain_api_key"):
                return True
        except Exception:
            pass

    ok = False
    balance = 0
    try:
        db = billing_adapter._web_session()
        try:
            if not user_id:
                # 无登录上下文：退化为单机默认用户，保持旧行为不中断业务
                tenant, u_row = billing_adapter.get_default_billing_user(db)
                tenant_id = tenant.id if tenant is not None else billing_adapter.WEB_TENANT_NAME
                user_id = u_row.id if u_row is not None else "u-admin"
            else:
                # ⭐ 按 (tenant_id, user_id) 精确定位 memberships 行。
                #   ⚠️ tenant_id **不能直接信 core.auth 返回的值**：
                #      core.auth 的 users 行 tenant_id 可能是字符串 'default'
                #      （core/db.py 的 schema 默认值），而 studio 侧真实租户 id
                #      是 uuid（studio.auth.ensure_default_tenant 生成）——
                #      两者不一致会查不到 memberships 行，表现为
                #      「明明有额度却一直提示不足」。
                #   正确做法：以 **studio 侧 users 行** 里的 tenant_id 为准
                #   （同一张 users 表，studio 侧那行是计费用的权威来源）。
                from studio.db_models import User as _StudioUser

                row = (
                    db.query(_StudioUser.tenant_id)
                    .filter(_StudioUser.id == user_id)
                    .first()
                )
                if row and row[0]:
                    tenant_id = str(row[0])
                else:
                    tenant, _ = billing_adapter.get_default_billing_user(db)
                    tenant_id = (
                        tenant.id if tenant is not None
                        else billing_adapter.WEB_TENANT_NAME
                    )
            ok = billing_adapter.check_and_deduct(
                db, tenant_id, user_id, action, count, desc
            )
            balance = billing_adapter.get_billing_status(db, tenant_id, user_id)["balance"]
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        # 扣费模块异常时按失败处理，宁可拦住也不放过（不抛 500 打扰用户）
        print(f"[计费] 扣费异常，按余额不足处理: action={action} err={e}")
        ok = False
    if ok:
        return True

    label = _ACTION_LABELS.get(action, "该功能")
    # R5-3/R5-6：撞上额度墙时留痕 + 触发召回通知。
    # 这是最有效的付费转化触点——用户已经想用而用不了，此时的召回
    # 转化率远高于日常推送。事件记录失败绝不影响 402 本身。
    _on_quota_blocked(action, label, need, balance)
    # R3-4：把「还差多少 + 买哪个档」直接写进 402 文案。
    # ⭐ 与 R5-3 的召回通知**不冲突**：那边发邮件（user_notify），这边只改
    #   HTTP 响应文案，两条通道互不触发。
    # ⭐ 额度数字全部取自 pricing 真源，不在此处硬编码。
    from studio import pricing as _pricing

    _up = _pricing.upsell_options(need_credits=need, balance=balance)
    _sug = "、".join(
        f"{o['name']}（{o['price_yuan']:.0f} 元 / {o['credits']:,} 点）"
        for o in _up["options"] if o["covers_action"]
    ) or "请前往价格页查看可用套餐"
    raise HTTPException(
        402,
        f"算力额度不足：{label}本次需要 {need:,} 点，你的账户还剩 {balance:,} 点，"
        f"还差 {_up['shortfall']:,} 点。"
        f"可升级套餐（{_sug}），或前往 /pricing 查看全部套餐与权益说明；"
        f"已有卡密的用户也可在「设置 - 会员与额度」直接兑换卡密充值。"
        f"（一条完整短剧约需 {_pricing.FULL_DRAMA_CREDITS:,} 点，"
        f"Free 档额度不足以跑完一条，请知悉）",
    )


# ---------------------------------------------------------------------------
# R3-9：草稿归属校验
# ---------------------------------------------------------------------------
#
# ⚠️ 安全背景（实测）：drafts.user_id 曾全库为空串，且所有内容读取路由
#   （/img/{did}/{name}、/card/{did}/{name}、/api/drafts/{did} 等）都只按
#   did 取数据、不校验归属 → **任何登录用户拿到任意 did 即可读取他人稿件
#   与图片直链**。这里统一收口：所有对外暴露草稿内容的端点都必须过
#   _assert_draft_owner()，管理员放行用于排障与合规复核。

def _is_admin_user(user: dict | None) -> bool:
    """是否管理员/运营角色（可跨用户访问草稿）。"""
    return (user or {}).get("role") in ("admin", "owner")


def _assert_draft_owner(request: Request, did: str) -> dict:
    """校验当前用户对该草稿的归属权，无权则抛 404。

    Returns:
        草稿 dict（归属校验通过）。

    ⚠️ 刻意返回 **404 而非 403**：403 等于确认「该 id 存在」，
       反而给了遍历 did 探测的口子；404 对越权者与不存在者表现一致。
       异常语义与历史（did 不存在也是 404）保持统一，前端无需改分支。
    """
    u = guard(request)
    d = db.get_draft(did)
    if not db.is_draft_owner(d, _current_user_id(u), is_admin=_is_admin_user(u)):
        raise HTTPException(404, "草稿不存在或无权访问")
    return d


def _on_quota_blocked(action: str, label: str, need: int, balance: int) -> None:
    """额度不足的副作用：埋点 + 召回通知（24h 节流，失败静默）。

    独立成函数是为了不把主流程的 402 逻辑撑大，也便于测试单独调用。
    """
    try:
        from core import analytics
        user = _CURRENT_USER.get() or {}
        uid = str((user or {}).get("id") or "")
        analytics.track("quota_blocked", uid,
                        {"action": action, "label": label,
                         "need": need, "balance": balance})
        if not uid:
            return
        email = str((user or {}).get("email") or "")
        from core import user_notify
        title, body = user_notify.quota_recall_body(label, need, balance)
        user_notify.deliver(uid, email, title, body, kind="quota_recall")
    except Exception as e:
        print(f"[召回] 额度墙通知触发异常（已忽略）: {e}")


def _tier_quota_check(user: dict, capability: str) -> tuple:
    """会员配额检查（V7 Free / V7 Pro / V7 Studio 三档）。

    返回 (allowed, reason, tier)。

    🔴 租户修复：原来写死 ``tenant_id="default"``，而 studio 侧真实租户是 uuid，
       于是 get_user_tier 永远查不到会员行 → 一律返回 free，
       付费用户的热榜次数/单次发布平台数/赛马权限全被按免费档限流
       （用户侧表现为「我明明买了却说额度不足」）。
       现在统一走 _web_tenant_id() 解析真实租户。
    """
    try:
        from studio.membership import capabilities as _caps

        _db = _caps.get_db_session()
        try:
            _uid = str((user or {}).get("id") or "")
            _tenant = _web_tenant_id(_db, _uid)
            _tier = _caps.get_user_tier(_db, tenant_id=_tenant, user_id=_uid)
            _allowed, _reason = _caps.check_and_consume(
                _db, tenant_id=_tenant, user_id=_uid,
                tier=_tier, capability=capability,
            )
            return _allowed, _reason, _tier
        finally:
            _db.close()
    except Exception as e:
        # 配额是体验限制，不是资金校验：数据库抖动时不阻断主功能。
        # 但**不得升级为 pro**（那等于一抖库就把免费用户全解锁），
        # 取值退回用户档案里的档位，缺省 free。
        print(f"[配额] 检查失败，本次不限制（按保守档位回退）: {e}")
        return True, "", str((user or {}).get("plan") or "free")


def _tier_capability_limit(user: dict, capability: str):
    """取用户某能力的配置值。

    🔴 异常时**不再返回 -1（不限）**：那等于一抖库免费用户就拿到不限次数。
       改为退回 free 档的限额（纯函数，不依赖数据库）。
    """
    tier = "free"
    try:
        from studio.membership import capabilities as _caps

        _db = _caps.get_db_session()
        try:
            _uid = str((user or {}).get("id") or "")
            _tenant = _web_tenant_id(_db, _uid)
            tier = _caps.get_user_tier(_db, tenant_id=_tenant, user_id=_uid)
            return _caps.capability_limit(tier, capability)
        finally:
            _db.close()
    except Exception as e:
        print(f"[配额] 限额查询失败，按 free 档回退: {e}")
        try:
            from studio.membership import capabilities as _caps2

            return _caps2.capability_limit(tier, capability)
        except Exception:
            return 1


def write_env(key: str, value: str):
    """写配置项；密钥类一律落到用户目录 secrets.env（0600），不落在安装目录。"""
    try:
        from core.user_paths import (
            is_sensitive, read_env_file, secrets_env_path, write_env_file,
        )
        if is_sensitive(key):
            path = secrets_env_path()
            secrets = read_env_file(path)
            secrets[key] = value
            if write_env_file(path, secrets):
                # 清掉旧版遗留在安装目录 .env 里的同名明文
                old = ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines() if ENV_PATH.exists() else []
                cleaned = [ln for ln in old if not ln.strip().startswith(f"{key}=")]
                if len(cleaned) != len(old):
                    ENV_PATH.write_text("\n".join(cleaned).rstrip("\n") + "\n", encoding="utf-8")
                return
    except Exception:
        pass  # 用户目录不可写时回退到历史行为，不让设置页保存失败
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
    try:
        _os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass


# ---------------- V6 多用户 SaaS 认证与个人 API 保险箱 ----------------
















# 兼容旧路径




def _wiz_done(user_id: str) -> bool:
    """检查某用户是否已跳过/完成首次引导（持久化在 user_onboarding_done.json）。"""
    if not user_id:
        return False
    p = ENV_PATH.parent / "data" / "user_onboarding_done.json"
    try:
        import json as _json
        data = _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return bool(data.get(user_id, {}).get("done", False))
    except Exception:  # noqa: BLE001
        return False






# ⭐ C-4：版本号单一真源，读 version.py；读取失败才回退（绝不手写版本号）。
try:
    from version import __version__ as APP_VERSION
except Exception:
    APP_VERSION = "10.1"


def get_app_version() -> str:
    """动态提取版本单一真源（version.py），热重载避免旧缓存。"""
    global APP_VERSION
    try:
        import importlib
        import version
        importlib.reload(version)
        APP_VERSION = version.__version__
        return APP_VERSION
    except Exception:
        try:
            from version import __version__
            APP_VERSION = __version__
            return APP_VERSION
        except Exception:
            return APP_VERSION or "10.1"


def get_app_version_info() -> dict:
    """提取版本元信息字典（单一真源）。"""
    try:
        import importlib
        import version
        importlib.reload(version)
        if hasattr(version, "get_version_info"):
            return version.get_version_info()
        return {
            "version": version.__version__,
            "codename": getattr(version, "__codename__", "山岳赋"),
            "codename_en": getattr(version, "__codename_en__", "Longwind Ballad"),
            "slogan": getattr(version, "__slogan__", ""),
            "slogan_cn": getattr(version, "__slogan_cn__", ""),
            "slogan_en": getattr(version, "__slogan_en__", ""),
        }
    except Exception:
        return {"version": get_app_version()}


def render_dynamic_html(raw_html: str) -> str:
    """全站页面动态版本注入器：
    统一将模板中的版本动态变量与历史写死版本替换为当前单一真源，并注入版本同步组件。
    """
    if not raw_html:
        return raw_html
    cur_ver = get_app_version()
    full_ver = f"V{cur_ver}"

    rendered = raw_html
    # 1. 动态变量替换
    rendered = rendered.replace("{{ APP_VERSION }}", cur_ver)
    rendered = rendered.replace("{{APP_VERSION}}", cur_ver)
    rendered = rendered.replace("{{ APP_VERSION_FULL }}", full_ver)
    rendered = rendered.replace("{{APP_VERSION_FULL}}", full_ver)
    rendered = rendered.replace("{{ VERSION }}", cur_ver)
    rendered = rendered.replace("{{VERSION}}", cur_ver)

    # 2. 注入 <meta name="app-version">
    meta_tag = f'<meta name="app-version" content="{cur_ver}">'
    if '<meta name="app-version"' in rendered:
        rendered = re.sub(r'<meta\s+name=["\']app-version["\']\s+content=["\'][^"\']*["\']>', meta_tag, rendered)
    elif "<head>" in rendered:
        rendered = rendered.replace("<head>", f"<head>\n<meta name=\"app-version\" content=\"{cur_ver}\">", 1)
    elif "<HEAD>" in rendered:
        rendered = rendered.replace("<HEAD>", f"<HEAD>\n<meta name=\"app-version\" content=\"{cur_ver}\">", 1)

    # 3. 注入动态同步脚本 /static/js/version-sync.js
    script_tag = '<script src="/static/js/version-sync.js"></script>'
    if 'src="/static/js/version-sync.js"' not in rendered and "src='/static/js/version-sync.js'" not in rendered:
        if "</head>" in rendered:
            rendered = rendered.replace("</head>", f"  {script_tag}\n</head>", 1)
        elif "</body>" in rendered:
            rendered = rendered.replace("</body>", f"  {script_tag}\n</body>", 1)

    return rendered












# ---------------- R4 内容安全闸管理接口 ----------------



















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




# ---------------- topics ----------------















# ---------------- 公众号图文编辑器 ----------------











































# ---------------- search & rewrite ----------------















# ---------------- drafts ----------------
















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















# ---------------- 创作者习惯自主进化自学习中枢 ----------------







# ---------------- 每日工单 & 服务健康 ----------------



def notify_ok():
    from core import notify as N
    return N.configured()






def _unload_legacy_launchd() -> None:
    """卸载 R5 之前遗留的 launchd 工单任务（幂等，云端/Linux 上直接跳过）。"""
    try:
        if not sys.platform.startswith("darwin"):
            return
        plist = Path.home() / "Library/LaunchAgents/com.czmj.mediaflow-ticket.plist"
        if not plist.exists():
            return
        import subprocess as sp

        sp.run(["launchctl", "unload", str(plist)], capture_output=True, timeout=10)
        plist.unlink(missing_ok=True)
    except Exception:
        pass




# ---------------------------------------------------------------------------
# R5-6 运营看板：5 步漏斗指标
# ---------------------------------------------------------------------------







HEALTH_SERVICES = [
    {"name": "apipool", "label": "apipool 模型池", "port": 8787, "path": "/health",
     "repair": "kickstart:com.czmj.apipool"},
    {"name": "exporter", "label": "公众号对标库", "port": 8791, "path": "/",
     "repair": "kickstart:com.czmj.wae"},
    {"name": "xhsmcp", "label": "小红书数据源", "port": 18060, "path": "/mcp",
     "repair": "restart_xhsmcp"},
]













































# ===================== 🎥 AI 短视频生成（视频大模型分段生成） =====================







































# ---------------- 商业化计费 & Token 算力中台 ----------------









# ===================================================================
# R3 变现通路线：价格页 / 下单收款 / 额度引导 / 发放 / 退款 / 用户 / 审计
# ===================================================================
#
# ⭐ 全部新路由的鉴权约定：
#   - 用户自助的（价格页、下单、查自己的订单）→ guard()（登录即可）
#   - 涉及资金与权限的（发放额度、退款、封禁、查审计、订单管理）→ guard_admin()
#   R1 已在 admin.py 建立 guard/guard_admin，此处一律复用，**不另造鉴权**。
#
# ⭐ 租户口径：与 require_credits 完全一致——以 **studio侧 users 行**的 tenant_id
#   为准（core.auth 返回的 tenant_id 可能是字符串 'default'，与 studio 的 uuid
#   租户不一致会查不到 memberships）。抽成 _web_tenant_id() 供全批次复用。

def _web_tenant_id(db, user_id: str, user_dict: dict | None = None) -> str:
    """解析当前用户所在 studio 租户 id，并在缺失时自动对齐/补齐 studio 用户与会员账本行。"""
    from studio import billing_adapter
    from studio.auth import ensure_default_tenant
    from studio.db_models import Tenant as _StudioTenant, User as _StudioUser
    from studio.membership.service import ensure_membership

    uid = str(user_id or "")
    if uid:
        u_row = db.query(_StudioUser).filter(_StudioUser.id == uid).first()
        if u_row is not None and u_row.tenant_id:
            # 检查该 tenant_id 是否真实存在于 tenants 表；若为 core.auth 默认写的 'default' 字符串则对齐到真实租户
            t_exists = db.query(_StudioTenant).filter(_StudioTenant.id == str(u_row.tenant_id)).first()
            if t_exists is not None:
                return str(u_row.tenant_id)
            t_def = ensure_default_tenant(db)
            u_row.tenant_id = t_def.id
            db.commit()
            ensure_membership(db, t_def.id, uid)
            db.commit()
            return str(t_def.id)
        # 若当前登录用户（如本机免密 u-admin）尚未在 studio users 表落行，自动补齐以打通下单与账本链路
        try:
            t_def = ensure_default_tenant(db)
            u_info = user_dict or _CURRENT_USER.get() or {}
            role = str(u_info.get("role") or ("admin" if uid == "u-admin" else "user"))
            uname = str(u_info.get("username") or uid)
            db.add(_StudioUser(
                id=uid,
                tenant_id=t_def.id,
                username=uname,
                email=str(u_info.get("email") or ""),
                password_hash="x",
                salt="x",
                role=role,
                is_active=True,
            ))
            db.commit()
            ensure_membership(db, t_def.id, uid)
            db.commit()
            return str(t_def.id)
        except Exception:
            db.rollback()

    tenant, _u = billing_adapter.get_default_billing_user(db)
    if tenant is not None:
        return str(tenant.id)
    try:
        t_def = ensure_default_tenant(db)
        db.commit()
        return str(t_def.id)
    except Exception:
        db.rollback()
        return billing_adapter.WEB_TENANT_NAME


def _r3_session():
    """R3 各路由统一取 studio DB session（调用方负责 close）。"""
    from studio import billing_adapter

    return billing_adapter._web_session()


def _current_user_id(u: dict | None) -> str:
    """从 guard() 返回的用户 dict 里取 id。"""
    return str((u or {}).get("id") or "")


# ---------------- R3-1 价格页 ----------------

















# ---------------- R10 在线支付闭环 ----------------











# ---------------- R3-2 下单收款 ----------------















# ---------------- R3-4 额度墙付费引导 ----------------



# ---------------- R3-5 额度发放（HTTP 入口） ----------------



# ---------------- R3-6 退款 ----------------



# ---------------- R3-7 用户列表与封禁 ----------------















# ---------------- R3-8 审计日志 ----------------







# ---------------- 8大名家音色与深度蒸馏中台 ----------------





# ---------------- 全 AI 短剧流水线工坊 ----------------
































# ---------------- 8 步全 AI 短剧工业级流水线 API ----------------







































# ----------------- 小红书专属历史版本回溯路由 -----------------



























# ---------------- 借鉴 Easel: 6 维账号数字画像与爆款归因复盘 (Profile & Postmortem) ----------------










































# ===================== ⚡ 异步算力任务队列 API =====================









# ===================== 🌊 SSE 实时流式打字机 API =====================


# ===================== 💬 v4.0 极简模式：爆款创作 Copilot API =====================







# ===================== 📎 V14 对话附件与提示词优化 =====================







# ===================== 📦 批量矩阵生产 API =====================



# ===================== 🌟 全局 IP 角色资产库 API =====================











# ===================== 🏢 多品牌工作区 API =====================













# ===================== 🎬 短剧非线性单镜头精修与母带快速重混 API =====================







# ===================== 📅 内容排期日历与定时发布 API =====================








# ===================== 🏷️ 优雅品牌水印设置 API =====================





# ===================== ✍️ 一幕·YIMU Editor 富文本编辑 API =====================
















# ---------------------------------------------------------------------------
# R5-5 裂变产物分享：公网链接 + 二维码 + 海报
# ---------------------------------------------------------------------------
# ⭐ 归属校验说明：这些路由的地址里**只有随机令牌、没有 did**，
#   令牌→稿件的映射只在服务端库里。因此无法通过「改 did」拿到
#   他人稿件——请求里根本不存在 did 参数。
























# ---------------- settings ----------------



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
                         analysis=parsed.get("ANALYSIS", ""),
                         user_id=str(payload.get("_owner_user_id") or ""))
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
        diag.capture_exc("rewrite", "rewrite_job", e, job_id=jid,
                         platform=payload.get("platform"), text_len=len(payload.get("text") or ""),
                         has_url=bool(payload.get("url")))
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
        image_style = str(payload.get("image_style") or "").strip()
        update_async_job(jid, step="正在解构核心痛点与生成多端爆款…", progress=30)
        res = O.generate_one_sentence_viral(sentence, mounted_persona=mounted_persona,
                                            theme=theme, media_name=media_name, emit=emit,
                                            platforms=platforms,
                                            user_id=str(payload.get("_owner_user_id") or ""),
                                            image_style=image_style)
        update_async_job(jid, status="done", progress=100, step="一句话灵感创作完成！", result=res)
    except Exception as e:
        update_async_job(jid, status="failed", error=str(e)[:400], step="创作失败")








# ---------------- 系统诊断日志 ----------------
# 用户场景：Windows 上「改写失败」，但拿不到服务端控制台。
# 这三个接口把失败现场变成可复制文本，用户粘给开发者即可定位。







# ---------------- HTML ----------------

# ---------------- HTML Page Loader ----------------
TEMPLATE_INDEX_PATH = BASE / "web" / "templates" / "index.html"
TEMPLATE_MOBILE_PATH = BASE / "web" / "templates" / "mobile.html"

def get_html_page() -> str:
    if TEMPLATE_INDEX_PATH.exists():
        return render_dynamic_html(TEMPLATE_INDEX_PATH.read_text(encoding="utf-8"))
    return "<h1>一幕·YIMU 页面模板文件缺失，请检查 web/templates/index.html</h1>"


def get_mobile_html_page() -> str:
    if TEMPLATE_MOBILE_PATH.exists():
        return render_dynamic_html(TEMPLATE_MOBILE_PATH.read_text(encoding="utf-8"))
    return get_html_page()


# R5-6 运营漏斗看板页面（自包含HTML，前端拉/api/admin/metrics渲染）
# 不用前端框架：与项目「无构建步骤」的现状一致，双击即可用。
_METRICS_PAGE_HTML = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>运营看板 · 一幕 YIMU V{{ APP_VERSION }}</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;background:#0f1220;color:#e8ecf8;
      font-family:PingFang SC,Microsoft YaHei,sans-serif}
 .wrap{max-width:1080px;margin:0 auto;padding:28px 20px 60px}
 h1{font-size:22px;margin:0 0 4px}
 .sub{color:#7d88b0;font-size:13px;margin-bottom:20px}
 .bar{display:flex;gap:8px;align-items:center;margin-bottom:20px;flex-wrap:wrap}
 button{background:#232a44;color:#cfd6ea;border:1px solid #313a5c;
        border-radius:8px;padding:6px 14px;font-size:13px;cursor:pointer}
 button.on{background:#4f7cff;border-color:#4f7cff;color:#fff}
 .card{background:#171b2e;border:1px solid #262d47;border-radius:14px;
       padding:20px;margin-bottom:18px}
 .card h2{font-size:15px;margin:0 0 14px;color:#9fb0e0;font-weight:600}
 .step{margin-bottom:16px}
 .row{display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px}
 .row b{color:#fff}
 .barwrap{height:22px;background:#0f1220;border-radius:11px;overflow:hidden}
 .fill{height:100%;background:linear-gradient(90deg,#4f7cff,#7c5cff);
       border-radius:11px;transition:width .4s}
 .pct{color:#8b93a7;font-size:12px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #262d47}
 th{color:#7d88b0;font-weight:500}
 .tag{padding:2px 8px;border-radius:6px;font-size:12px}
 .healthy{background:#16351f;color:#5fd08a}
 .degraded{background:#3a2f14;color:#e0b45f}
 .cooldown{background:#3a1a1a;color:#ef7b7b}
 .empty{color:#6b7699;font-size:13px;padding:10px 0}
</style></head><body>
<div class="wrap">
  <h1>运营看板</h1>
  <div class="sub">口径：累计触达的去重用户数（非严格同会话序列），后段可能出现反超。</div>
  <div class="bar">
    <span style="font-size:13px;color:#7d88b0">时间窗</span>
    <button class="on" onclick="load(7,this)">近 7 天</button>
    <button onclick="load(30,this)">近 30 天</button>
    <button onclick="load(0,this)">全部</button>
    <button onclick="load()">刷新</button>
  </div>
  <div class="card"><h2>收入看板（R10 新增：GMV / MRR / ARPU）</h2><div id="revenue"><div class="empty">加载中…</div></div></div>
  <div class="card"><h2>转化漏斗</h2><div id="funnel"><div class="empty">加载中…</div></div></div>
  <div class="card"><h2>续费提醒（7/3/1 天节点）</h2><div id="expiring"><div class="empty">加载中…</div></div></div>
  <div class="card"><h2>账号健康（自动发布）</h2><div id="health"><div class="empty">加载中…</div></div></div>
  <div class="card"><h2>每日工单定时</h2><div id="ticket"><div class="empty">加载中…</div></div></div>
  <div class="card"><h2>最近事件</h2><div id="events"><div class="empty">加载中…</div></div></div>
</div>
<script>
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const H={'Content-Type':'application/json'};
function csrf(){const m=document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);return m?m[1]:'';}

async function load(days,btn){
  if(days!==undefined&&btn){document.querySelectorAll('.bar button').forEach(b=>b.classList.remove('on'));btn.classList.add('on');}
  let r;
  try{
    r=await fetch('/api/admin/metrics'+(days!==undefined?'?days='+days:''),{credentials:'same-origin',headers:H});
    if(r.status===401||r.status===403){document.getElementById('funnel').innerHTML='<div class="empty">需要管理员登录后才能查看运营数据。</div>';['health','ticket','events'].forEach(i=>document.getElementById(i).innerHTML='');return;}
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    renderFunnel(d.funnel);renderHealth(d.account_health||[]);
    renderTicket(d.ticket||{});renderEvents(d.recent_events||[]);
    renderRevenue(d.revenue||{});renderExpiring(d.expiring_memberships||[]);
  }catch(e){
    document.getElementById('funnel').innerHTML='<div class="empty">看板数据加载失败：'+esc(e.message)+'</div>';
  }
}

function renderRevenue(rv){
  const el=document.getElementById('revenue');
  if(!rv||rv.ok===false){el.innerHTML='<div class="empty">'+esc((rv&&rv.error)||'收入数据不可用')+'</div>';return;}
  const planRows=Object.keys(rv.by_plan||{}).map(function(p){
    const x=rv.by_plan[p];
    return '<tr><td>'+esc(p.toUpperCase())+'</td><td>'+x.orders+' 单</td><td>¥'+(x.gmv_cents/100).toFixed(2)+'</td></tr>';
  }).join('')||'<tr><td colspan="3" class="empty">暂无已收款订单</td></tr>';
  el.innerHTML=
    '<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:12px">'+
    '<div style="flex:1;min-width:120px;background:#10142a;border-radius:10px;padding:12px"><div style="font-size:12px;color:#7d88b0">累计实收 GMV</div><div style="font-size:22px;font-weight:700;color:#5fd08a">¥'+Number(rv.gmv_yuan||0).toFixed(2)+'</div></div>'+
    '<div style="flex:1;min-width:120px;background:#10142a;border-radius:10px;padding:12px"><div style="font-size:12px;color:#7d88b0">MRR（月度经常性收入）</div><div style="font-size:22px;font-weight:700;color:#7c9cff">¥'+Number(rv.mrr_yuan||0).toFixed(2)+'</div></div>'+
    '<div style="flex:1;min-width:120px;background:#10142a;border-radius:10px;padding:12px"><div style="font-size:12px;color:#7d88b0">ARPU（'+rv.days+'天）</div><div style="font-size:22px;font-weight:700;color:#e0b45f">¥'+Number(rv.arpu_yuan||0).toFixed(2)+'</div></div>'+
    '<div style="flex:1;min-width:120px;background:#10142a;border-radius:10px;padding:12px"><div style="font-size:12px;color:#7d88b0">付费转化率</div><div style="font-size:22px;font-weight:700;color:#fff">'+(rv.pay_conversion*100).toFixed(1)+'%</div><div style="font-size:11px;color:#6b7699">'+rv.paid_orders+'/'+rv.total_orders+' 单</div></div>'+
    '</div>'+
    '<table><tr><th>套餐</th><th>订单</th><th>实收</th></tr>'+planRows+'</table>'+
    (rv.refund_cents>0?'<div style="font-size:12px;color:#ef7b7b;margin-top:8px">⚠️ 累计退款 ¥'+Number(rv.refund_yuan||0).toFixed(2)+' · 净收入 ¥'+Number(rv.net_yuan||0).toFixed(2)+'</div>':'');
}

function renderExpiring(list){
  const el=document.getElementById('expiring');
  if(!list.length){el.innerHTML='<div class="empty">未来 7 天没有到期的付费会员。</div>'+
    '<button style="margin-top:8px" onclick="sendRenewal()">手动触发续费提醒（7/3/1 天节点）</button>';return;}
  el.innerHTML='<table><tr><th>用户</th><th>套餐</th><th>到期日</th><th>剩余</th></tr>'+
    list.map(function(x){return '<tr><td>'+esc(x.username)+'</td><td>'+esc(String(x.tier).toUpperCase())+'</td><td>'+
      esc(String(x.period_end).slice(0,10))+'</td><td><span class="tag '+(x.days_left<=3?'cooldown':'degraded')+'">'+x.days_left+' 天</span></td></tr>';}).join('')+'</table>'+
    '<button style="margin-top:8px" onclick="sendRenewal()">发送续费提醒（24h 节流）</button>';
}

async function sendRenewal(){
  try{
    const r=await fetch('/api/admin/renewal-reminders/send',{method:'POST',credentials:'same-origin',headers:H,body:'{}'});
    const d=await r.json();
    if(r.ok&&d.ok){alert('已检查 '+d.checked+' 人：发送 '+d.sent+' 封，节流/待发 '+d.skipped+' 封');load();}
    else{alert('发送失败：'+((d.detail&&d.detail.message)||'请重试'));}
  }catch(e){alert('发送异常：'+e.message);}
}

function renderFunnel(fn){
  const steps=(fn&&fn.steps)||[];
  if(!steps.length){document.getElementById('funnel').innerHTML='<div class="empty">暂无数据</div>';return;}
  const top=Math.max.apply(null,steps.map(s=>s.users).concat([1]));
  document.getElementById('funnel').innerHTML=steps.map(s=>{
    const w=Math.round(s.users/top*100);
    const delta=s.step===1?'起始':('较上一步 '+s.rate_from_prev+'%');
    return '<div class="step"><div class="row"><span>'+s.step+'. '+esc(s.label)+
      ' <span class="pct">'+esc(delta)+'</span></span><span><b>'+s.users+'</b> 人 · '+
      s.total+' 次</span></div><div class="barwrap"><div class="fill" style="width:'+w+'%"></div></div></div>';
  }).join('');
}

function renderHealth(list){
  if(!list.length){document.getElementById('health').innerHTML='<div class="empty">暂无账号记录（尚未发生自动发布）</div>';return;}
  const L={'healthy':'正常','degraded':'波动','cooldown':'冷却中'};
  document.getElementById('health').innerHTML='<table><tr><th>账号</th><th>平台</th><th>状态</th><th>连续失败</th></tr>'+
    list.map(h=>'<tr><td>'+esc(h.account_key)+'</td><td>'+esc(h.platform)+
      '</td><td><span class="tag '+esc(h.status)+'">'+esc(L[h.status]||h.status)+
      '</span></td><td>'+esc(h.consecutive_failures)+'</td></tr>').join('')+'</table>';
}

function renderTicket(t){
  document.getElementById('ticket').innerHTML=
    '<table><tr><th>已启用</th><th>每日时间</th><th>今日已执行</th><th>调度线程</th></tr><tr><td>'+
    (t.enabled?'是':'否')+'</td><td>'+esc(t.time)+'</td><td>'+
    (t.ran_today?esc(t.ran_today):'否')+'</td><td>'+
    (t.daemon_running?'运行中':'未运行')+'</td></tr></table>';
}

function renderEvents(list){
  if(!list.length){document.getElementById('events').innerHTML='<div class="empty">暂无事件</div>';return;}
  document.getElementById('events').innerHTML='<table><tr><th>时间</th><th>事件</th><th>用户</th></tr>'+
    list.map(e=>'<tr><td>'+esc(new Date(e.created_at*1000).toLocaleString())+'</td><td>'+
      esc(e.event)+'</td><td>'+esc(e.user_id||'—')+'</td></tr>').join('')+'</table>';
}
load();
</script></body></html>"""


# R3-1 价格页（自包含 HTML，拉 /api/pricing + /api/billing/order 渲染）
# ⭐ 诚实性要求：Free 档跑不完一条完整短剧（3000 < 12000 credits），
#   页面必须如实标注，不得为了转化率把 Free 写成「够跑一条」。
_PRICING_PAGE_HTML = (BASE / "web/templates/pages/pricing.html").read_text(encoding="utf-8") if (BASE / "web/templates/pages/pricing.html").exists() else ""


# R3-7 用户管理页（管理员）：搜索 + 封禁/解封
_USERS_PAGE_HTML = (BASE / "web/templates/pages/users_admin.html").read_text(encoding="utf-8") if (BASE / "web/templates/pages/users_admin.html").exists() else ""


# R3-8 审计日志查询页（管理员）
_AUDIT_PAGE_HTML = (BASE / "web/templates/pages/audit_admin.html").read_text(encoding="utf-8") if (BASE / "web/templates/pages/audit_admin.html").exists() else ""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.admin:app", host="127.0.0.1", port=8790, reload=False)



# =========================================================================
# R11 巨石拆分:路由域已整体迁出至 web/routers/,此处统一挂载。
# ⭐ 必须放在模块最底部:router 模块 import web.admin 时本模块已完整定义。
# =========================================================================
from web.routers import admin_users as _r_admin_users  # noqa: E402
from web.routers import assets as _r_assets  # noqa: E402
from web.routers import auth as _r_auth  # noqa: E402
from web.routers import billing as _r_billing  # noqa: E402
from web.routers import drafts as _r_drafts  # noqa: E402
from web.routers import files as _r_files  # noqa: E402
from web.routers import media as _r_media  # noqa: E402
from web.routers import models as _r_models  # noqa: E402
from web.routers import ops as _r_ops  # noqa: E402
from web.routers import pages as _r_pages  # noqa: E402
from web.routers import skills as _r_skills  # noqa: E402
from web.routers import system as _r_system  # noqa: E402
from web.routers import tasks as _r_tasks  # noqa: E402
from web.routers import tools as _r_tools  # noqa: E402
from web.routers import topics as _r_topics  # noqa: E402
from web.routers import workspace as _r_workspace  # noqa: E402
app.include_router(_r_admin_users.router)
app.include_router(_r_assets.router)
app.include_router(_r_auth.router)
app.include_router(_r_billing.router)
app.include_router(_r_drafts.router)
app.include_router(_r_files.router)
app.include_router(_r_media.router)
app.include_router(_r_models.router)
app.include_router(_r_ops.router)
app.include_router(_r_pages.router)
app.include_router(_r_skills.router)
app.include_router(_r_system.router)
app.include_router(_r_tasks.router)
app.include_router(_r_tools.router)
app.include_router(_r_topics.router)
app.include_router(_r_workspace.router)
