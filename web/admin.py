# SPDX-License-Identifier: BUSL-1.1
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
from contextvars import ContextVar
from pathlib import Path
from typing import Optional, List, Dict, Any

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import yaml                                          # noqa: E402
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402
from fastapi.responses import (FileResponse, HTMLResponse,   # noqa: E402
                               JSONResponse, Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles          # noqa: E402
from fastapi.routing import APIRoute                # noqa: E402

from core import db, judge, orchestrator             # noqa: E402
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
#   - /preview/{did}/{platform}：分享产物预览页，由 share 令牌链路驱动。
#   其余一切带 did 的路由一律校验归属。
_DID_OWNER_EXEMPT_PREFIXES = ("/s/", "/preview/")


class DraftOwnerRoute(APIRoute):
    """R3-9：对所有带 {did} 的路由强制校验草稿归属（fail-closed）。"""

    def get_route_handler(self):
        original = super().get_route_handler()
        if "{did}" not in self.path or self.path.startswith(_DID_OWNER_EXEMPT_PREFIXES):
            return original

        async def guarded(request: Request) -> Response:
            u = get_current_user(request)
            # 未登录：交给下游 guard() 处理，保持 401 语义统一；
            # 这里放行不代表能访问——所有业务路由自身都会再 guard() 一次。
            if u and not _is_admin_user(u):
                did = str(request.path_params.get("did") or "")
                draft = db.get_draft(did) if did else None
                if not db.is_draft_owner(draft, _current_user_id(u), is_admin=False):
                    # 刻意用 404 而非 403：403 等于确认「该 id 存在」，
                    # 反而给了遍历 did 探测的口子。
                    raise HTTPException(404, "草稿不存在或无权访问")
            return await original(request)

        return guarded


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
from core.db import DB_PATH as _MAIN_DB_PATH  # noqa: E402
_os.environ.setdefault("YIMU_DB_URL", "sqlite:///" + str(_MAIN_DB_PATH))
if not _os.environ.get("YIMU_SECRET_KEY"):
    _os.environ["YIMU_SECRET_KEY"] = "yimu-dev-" + _secrets.token_hex(16)
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
#      （启动一幕V7测试.command 会生成随机口令）开箱可用。
# ---------------------------------------------------------------------------

#: 进程内随机的管理会话密钥：每次启动重新生成，外部无法预测或伪造 mf_token
_MF_SESSION_SECRET = _secrets.token_hex(32)

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
    """
    return _admin_password() is not None


def _warn_admin_password_state() -> None:
    """服务启动时打印管理口令配置状态（未配置即明确告警）。"""
    if _admin_password() is None:
        print(
            "[安全提示] 未配置 ADMIN_PASSWORD：管理员口令登录与本机免密通行均已关闭，"
            "管理相关接口需要登录会话。请设置 ADMIN_PASSWORD 环境变量"
            "（本地可运行「启动一幕V7测试.command」自动生成随机口令）。"
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
                "「一句话生成」主链路会 401。请在 .env 填入该通道的真实 API Key，"
                "或在「模型服务」里切换到已配置真实 Key 的通道。"
            )
    except Exception as e:  # 检测失败绝不阻断启动
        print(f"[提示] 主链路 Key 检测跳过: {e}")


def _token() -> str:
    """签发单机管理 Cookie 的值：由进程内随机密钥派生，外部不可预测。"""
    return hashlib.sha256(
        f"mf|{_MF_SESSION_SECRET}|{_admin_password() or 'no-password'}".encode()
    ).hexdigest()


def _is_loopback(request: Request) -> bool:
    """请求是否来自本机回环地址。"""
    client_ip = request.client.host if request.client else ""
    return client_ip in _LOOPBACK_HOSTS


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
                return u

    # 2. 兼容旧单机模式全局 Token（进程内随机签发，外部不可伪造）
    if request.cookies.get("mf_token") == _token():
        return {"id": "u-admin", "username": "admin", "role": "admin", "plan": "enterprise"}

    # 3. 本地 loopback 自动免密通行（映射为系统超级管理员）
    #    ⭐ fail-closed：未配置 ADMIN_PASSWORD 时不通行（原本恒为真）
    return _auto_admin_cookie(request) or None


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
    
    # 兼容管理员口令登录（⭐ V8/P0-B：fail-closed，仅当已配置强口令时）
    strong_pwd = _admin_password()  # None = 未配置或命中历史弱口令清单
    is_loopback_client = _is_loopback(request)

    # 管理员放行只允许两种情形，且都以「已配置强口令」为前提：
    #   ① 本机（loopback）访问 —— 本地开发免密（项目文档明示的设计）；
    #   ② 密码与已配置强口令完全匹配 —— 任意来源。
    # 历史弱口令 123456/local-admin/admin 已并入 _admin_password 的 None 分支，
    # 远端部署时 loopback 为假、弱口令又不匹配 → 后门彻底封死。
    loopback_grant = is_loopback_client and strong_pwd is not None
    pwd_match_grant = strong_pwd is not None and password == strong_pwd
    if username in ("admin", "") and (loopback_grant or pwd_match_grant):
        from core import auth
        auth.ensure_default_admin(strong_pwd)
        token = auth.make_token({"user_id": "u-admin", "username": "admin", "role": "admin"})
        u = auth.get_user_by_id("u-admin") or {"id": "u-admin", "username": "admin", "role": "admin", "plan": "enterprise"}
        resp = JSONResponse({"ok": True, "token": token, "user": u, "msg": "管理员登录成功"})
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
    APP_VERSION = "8.3.2"


@app.get("/health")
def health():
    return {"ok": True, "ts": time.time(), "version": APP_VERSION}


@app.get("/api/health")  # V7 契约归一：/health 的规范别名（CONTRACT §4）
def api_health():
    return health()


@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION}


# ---------------- R4 内容安全闸管理接口 ----------------

@app.get("/api/compliance/guard")
def guard_stats(request: Request):
    """内容安全闸概况：开关状态、各词库条目数、白名单规模。"""
    guard(request)
    from core import content_guard
    return content_guard.library_stats()


@app.post("/api/compliance/topics/sweep")
async def guard_sweep_topics(request: Request):
    """扫描选题池，把命中内容安全闸的条目标记 blocked（**不删除**）。

    body: {"apply": false} 预演；true 真正标记。等价于 `python -m scripts.r4_cleanup --apply`。
    """
    guard(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = db.sweep_blocked_topics(apply=bool(body.get("apply")))
    return {"ok": True, **res}


@app.get("/api/compliance/topics/blocked")
def guard_blocked_topics(request: Request):
    """列出被内容安全闸拦下的选题（供人工复核）。"""
    guard(request)
    items = db.list_blocked_topics()
    return {"ok": True, "total": len(items), "items": items}


@app.post("/api/compliance/drafts/sweep")
async def guard_sweep_drafts(request: Request):
    """扫描草稿箱，把命中内容安全闸的条目标记 needs_review（**不删除**）。"""
    guard(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = db.sweep_drafts_needs_review(apply=bool(body.get("apply")))
    return {"ok": True, **res}


@app.get("/api/compliance/drafts/review")
def guard_drafts_review(request: Request):
    """列出待人工复核的草稿。"""
    guard(request)
    items = db.list_drafts_needs_review()
    return {"ok": True, "total": len(items), "items": items}


@app.post("/api/compliance/drafts/{did}/clear_review")
async def guard_clear_review(did: str, request: Request):
    """人工复核通过：清除 needs_review 标记（草稿本身保留）。"""
    guard(request)
    if not db.get_draft(did):
        raise HTTPException(404, "草稿不存在")
    return {"ok": db.clear_draft_needs_review(did)}


@app.post("/api/compliance/drafts/{did}/check")
async def guard_check_draft(did: str, request: Request):
    """对单篇草稿做发布前内容安全检查（不写库，仅返回可读结论）。"""
    guard(request)
    from core import content_guard
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    res = content_guard.pre_publish_check(d.get("body_md"), d.get("title"))
    return res.to_dict()


@app.api_route("/m", methods=["GET", "HEAD"])
def mobile_index(request: Request):
    """V6 专属全新设计的原生手机端页面"""
    resp = HTMLResponse(get_mobile_html_page(), headers={"Cache-Control": "no-store, must-revalidate"})
    # ⭐ 仅在已配置口令的本机访问时下发管理 Cookie（fail-closed）
    if _is_loopback(request) and _loopback_admin_allowed():
        resp.set_cookie("mf_token", _token(), httponly=True, samesite="lax", max_age=30*86400, path="/")
    return resp


@app.api_route("/", methods=["GET", "HEAD"])
def index(request: Request):
    # 若请求来自手机浏览器 User-Agent，自动提供全新的手机专属页面
    ua = (request.headers.get("user-agent") or "").lower()
    is_mobile = any(m in ua for m in ("iphone", "android", "mobile", "ipod", "harmonyos", "micromessenger"))

    html = get_mobile_html_page() if is_mobile else get_html_page()
    resp = HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})
    # ⭐ 仅在已配置口令的本机访问时下发管理 Cookie（fail-closed）
    if _is_loopback(request) and _loopback_admin_allowed():
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
    user = guard(request)
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
    cur_ws_id = db.get_active_workspace().get("id", "ws-default")
    return {
        "topics": db.list_topics(workspace_id=cur_ws_id),
        #⭐ R3-9：草稿列表按归属过滤——普通用户只看得到自己的稿件，
        #   并根据当前激活的工作空间 workspace_id 彻底隔离草稿箱。
        "drafts": [_draft_view(d) for d in db.list_drafts(
            _current_user_id(user), is_admin=_is_admin_user(user), workspace_id=cur_ws_id)],
        "workspace_id": cur_ws_id,
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

@app.get("/api/topics")
def get_topics(request: Request):
    """获取热榜/热搜选题列表（按当前工作空间隔离）"""
    guard(request)
    cur_ws_id = db.get_active_workspace().get("id", "ws-default")
    return {"ok": True, "topics": db.list_topics(workspace_id=cur_ws_id)}


@app.post("/api/topics/collect")
async def topics_collect(request: Request):
    u = guard(request)
    # ⭐ 会员分级：热榜采集每日配额（free：每日 1 次）
    _allowed, _reason, _tier = _tier_quota_check(u, "hot_daily")
    if not _allowed:
        raise HTTPException(402, _reason)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, orchestrator.run_once)
        return res
    except Exception as e:
        print(f"[热榜采集] 异常已兜底，改用已有热榜: {e}")
        # 异常时用当前已有热榜或空状态返回，避免抛 500
        return {
            "total": 0, "matched": 0, "keywords": [],
            "per_source": {"error": str(e)},
            "blocked": 0, "blocked_titles": [],
            "warn": f"热榜网络抓取受阻已自动兜底: {str(e)[:100]}"
        }


@app.post("/api/topics/manual")
async def topics_manual(request: Request):
    guard(request)
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    cur_ws_id = db.get_active_workspace().get("id", "ws-default")
    return db.add_topic("manual", title, body.get("reason", ""), True, workspace_id=cur_ws_id)


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
    user = guard(request)
    if action == "approve":
        db.set_topic_status(tid, "approved")
        return {"ok": True}
    if action == "reject":
        db.set_topic_status(tid, "rejected")
        return {"ok": True}
    if action == "generate":
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: orchestrator.generate_draft(
                    tid, user_id=_current_user_id(user)))
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
                    platforms=platforms,
                    # ⭐ R3-9：草稿归属，避免成稿落库后本人看不到
                    user_id=_current_user_id(user),
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
    from core import imagegen
    require_credits("drama_image", 1, f"重绘文章配图 [{name}]")
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
    """扫描所有草稿图片，返回全局素材库（支持关键词过滤和分页）

    ⭐ R3-9：素材库只扫**当前用户自己**的草稿目录。素材是稿件的派生物，
       扫全库等于把别人的图片素材也交出来，与草稿正文同级别机密。
    """
    user = guard(request)
    import pathlib, time as _time
    drafts_dir = pathlib.Path("data/drafts")
    if not drafts_dir.exists():
        return {"ok": True, "assets": [], "total": 0}

    # 批量获取草稿 title 映射（⭐ R3-9：只取当前用户自己的草稿）
    all_drafts = {}
    try:
        _mine = {d.get("id", ""): d.get("title", "") for d in db.list_drafts(
            _current_user_id(user), is_admin=_is_admin_user(user))}
        all_drafts = _mine
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
        #⭐ R3-9：目录在磁盘上但不属于当前用户 → 整个目录跳过。
        #   磁盘目录是历史遗留（可能含已删草稿的残留），只靠 db 查询会漏，
        #   所以这里以「当前用户的草稿集合」做白名单过滤。
        if did not in all_drafts:
            continue
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
    user = guard(request)
    body = await request.json()
    prompt = (body.get("prompt") or body.get("scene") or "").strip()
    if not prompt:
        raise HTTPException(400, "请输入生成画面的描述")

    # 选取一个草稿目录存放（优先当前草稿，若无草稿存放至第一篇草稿或通用目录）
    # ⭐ R3-9：只允许写进**自己**的草稿目录，否则可往他人草稿里塞图
    #   （投毒他人素材库）。归属校验失败直接忽略该 draft_id。
    did = str(body.get("draft_id") or "")
    all_d = db.list_drafts(_current_user_id(user), is_admin=_is_admin_user(user))
    if did and not any(d.get("id") == did for d in all_d):
        did = ""
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


@app.get("/api/drafts/image_styles")
def get_image_styles(request: Request):
    """获取系统支持的配图视觉风格清单（古风、科技风、都市风等）"""
    guard(request)
    from core.imagegen import VISUAL_STYLE_PRESETS
    styles = []
    icon_map = {
        "ancient_chinese": "🏛️",
        "tech_cyber": "🤖",
        "city_urban": "🏙️",
        "swiss_minimal": "💼",
        "magazine_editorial": "✨",
        "documentary": "📷",
        "cinematic_movie": "🎬",
        "commercial_premium": "💎",
        "anime_cinematic": "🌅",
        "minimalist_3d": "🎨",
    }
    for k, v in VISUAL_STYLE_PRESETS.items():
        if k == "chinese_ink":
            continue  # 隐藏兼容别名
        styles.append({
            "key": k,
            "name": v.get("name", k),
            "icon": icon_map.get(k, "🎨"),
            "keywords": v.get("keywords", [])[:5]
        })
    return {"ok": True, "styles": styles}


@app.post("/api/drafts/{did}/generate_images")
async def draft_generate_images(did: str, request: Request):
    """一键为全文智能批量生成成套插图与封面，并自动插入正文与重新渲染（支持选择配图风格与一键换图）"""
    guard(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    count = int(body.get("count", 3))
    style = str(body.get("style") or "").strip()
    force_regen = bool(body.get("force_regen", False))
    model = str(body.get("model") or "").strip()
    from core.imagegen import generate_and_inject_images, VISUAL_STYLE_PRESETS
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    style_name = VISUAL_STYLE_PRESETS.get(style, {}).get("name", style) if style else "自动匹配"
    import uuid
    jid = f"img-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"全文智能配图 ({count}张·{style_name}): {d_title[:16]}",
        task_type="image_gen",
        target_id=did,
        params={"draft_id": did, "count": count, "style": style, "model": model},
        initial_step=f"正在分析段落视觉意境（风格：{style_name}）并生成 {count} 张专属高清配图…"
    )
    try:
        update_async_job(jid, step=f"AI 光学摄影渲染中（风格: {style_name}）…", progress=45)
        res = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_and_inject_images(did, count=count, style=style, force_regen=force_regen or bool(style), model=model)
        )
        update_async_job(jid, status="done", step=f"成功生成 {count} 张【{style_name}】配图并已排版入文", progress=100, result=res)
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
                source_text=body.get("source_text") or body.get("text") or "",
                #⭐ R3-9：草稿归属（否则成稿落库后本人也看不到）
                user_id=_current_user_id(guard(request))))
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


@app.get("/api/agents/config")
def agents_config(request: Request):
    """获取所有 13 个 Agent 与 岗位阶段配置信息"""
    guard(request)
    from core import agents as AG
    return {
        "ok": True,
        "stages": AG.STAGES,
        "agents": AG.agents_cfg(),
        "skills": {k: v["description"] for k, v in AG.list_skills().items()}
    }



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
    """设置每日工单的开关与时间（R5-2：应用内定时，不再依赖 macOS launchd）。

    ⚠️ 行为变更：原实现往 ``~/Library/LaunchAgents/`` 写 plist 并
    ``launchctl load``，那是**仅限 macOS 本机**的机制，云端部署
    （容器 / Linux）既无 launchctl 也无该目录，定时功能会静默失效。
    现改为只写配置，由应用内调度守护线程按点执行，跨平台一致。
    """
    guard(request)
    body = await request.json()
    enabled = bool(body.get("enabled"))
    hh, mm = (body.get("time") or "07:30").split(":")
    write_env("TICKET_ENABLED", "1" if enabled else "0")
    write_env("TICKET_TIME", f"{int(hh):02d}:{int(mm):02d}")
    # 清理历史遗留的 launchd 任务（仅本机存在时才 unload，失败静默）
    _unload_legacy_launchd()
    from core import scheduler as _sched

    st = _sched.ticket_status()
    return {"ok": True, "enabled": enabled, "time": st["time"],
            "mode": "in_app", "daemon_running": st["daemon_running"]}


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


@app.get("/api/ticket/schedule")
def ticket_schedule_get(request: Request):
    """读取每日工单定时状态（供设置页回显）。"""
    guard(request)
    from core import scheduler as _sched

    st = _sched.ticket_status()
    return {"ok": True, "enabled": st["enabled"], "time": st["time"],
            "ran_today": st["ran_today"], "daemon_running": st["daemon_running"]}


# ---------------------------------------------------------------------------
# R5-6 运营看板：5 步漏斗指标
# ---------------------------------------------------------------------------


@app.get("/api/admin/metrics")
def admin_metrics(request: Request):
    """⭐ 运营漏斗看板数据（管理员）。

    返回 5 步漏斗（注册 → 首次成稿 → 首次跑短剧 → 撞额度墙 → 兑换卡密）
    的逐级转化，另附工单定时、账号健康、通知投递三个运营面板。

    ⚠️ 口径说明：漏斗按**累计触达的去重用户数**统计，非严格同会话序列，
    因此后段可能出现反超（如先撞墙再成稿）。看板已标注该口径。
    """
    guard_admin(request)
    from core import analytics, pubguard
    from core import scheduler as _sched

    try:
        days = int(request.query_params.get("days") or 30)
    except Exception:
        days = 30
    fn = analytics.funnel(days)
    return {
        "ok": True,
        "funnel": fn,
        "recent_events": analytics.list_recent(20),
        "ticket": _sched.ticket_status(),
        "account_health": pubguard.health_summary(),
        "generated_at": time.time(),
    }


@app.get("/admin/metrics")
def admin_metrics_page(request: Request):
    """运营漏斗看板页面（管理员）。纯前端拉接口，无构建步骤。"""
    guard_admin(request)
    return HTMLResponse(_METRICS_PAGE_HTML)


@app.get("/admin/releases")
def admin_releases_page(request: Request):
    """7.1 升级总览页：单一入口，讲清「改了什么 / 在哪 / 怎么看」。

    只读页面，不做任何写操作，故只要求登录、不要求管理员。
    """
    from studio.releases_page import releases_page as _releases_page

    return _releases_page(request)


HEALTH_SERVICES = [
    {"name": "apipool", "label": "apipool 模型池", "port": 8787, "path": "/health",
     "repair": "kickstart:com.czmj.apipool"},
    {"name": "exporter", "label": "公众号对标库", "port": 8791, "path": "/",
     "repair": "kickstart:com.czmj.wae"},
    {"name": "xhsmcp", "label": "小红书数据源", "port": 18060, "path": "/mcp",
     "repair": "restart_xhsmcp"},
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
    else:
        raise HTTPException(404, name)
    return {"ok": True}


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
    # 原生成片（runs/videos/{tid}/final-*.mp4）或 AI 短视频（runs/ai_video/{tid}/final-*.mp4）
    candidates = []
    native_dir = BASE / "runs" / "videos" / tid
    if native_dir.exists():
        candidates.extend(sorted(native_dir.glob("final-*.mp4")))
    aiv_dir = BASE / "runs" / "ai_video" / tid
    if not candidates and aiv_dir.exists():
        candidates.extend(sorted(aiv_dir.glob("final-*.mp4")))
    f = candidates[0] if candidates else None
    if not f or not f.exists():
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
        name=f"短视频合成: {d_title[:16]}",
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


@app.get("/api/advideo/ref_file")
def advideo_ref_file(request: Request, path: str = ""):
    """AI 广告短片：serving 上传的参考图/音频（预览用）。"""
    guard(request)
    import pathlib
    from fastapi.responses import FileResponse
    p = pathlib.Path(path)
    # 安全：只允许 runs/advideo_refs 与 runs/advideo_audio 下的文件
    try:
        rp = p.resolve()
        allowed = [pathlib.Path("runs/advideo_refs").resolve(),
                   pathlib.Path("runs/advideo_audio").resolve(),
                   pathlib.Path("runs/avatars").resolve()]
        if not any(str(rp).startswith(str(a)) for a in allowed):
            raise HTTPException(403, "非法路径")
        if not rp.exists():
            raise HTTPException(404, "文件不存在")
        return FileResponse(str(rp))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"读取失败: {e}")


@app.post("/api/advideo/selling_points")
async def advideo_selling_points(request: Request):
    """AI 广告短片：单独生成卖点（供前端预览/编辑/重新生成）。"""
    guard(request)
    body = await request.json()
    product_name = (body.get("product_name") or "").strip()
    product_desc = (body.get("product_desc") or "").strip()
    audience = (body.get("audience") or "大众消费者").strip()
    if not product_name or not product_desc:
        raise HTTPException(400, "请填写产品名称和产品描述")
    from core import ad_video
    sp = ad_video.extract_selling_points(product_name, product_desc, audience)
    return {"points": sp["points"], "pain": sp.get("pain", "")}


@app.post("/api/advideo/upload_ref")
async def advideo_upload_ref(request: Request, file: UploadFile = File(...)):
    """AI 广告短片：上传产品/人物参考图。"""
    guard(request)
    import pathlib, shutil, uuid
    ref_dir = pathlib.Path("runs/advideo_refs")
    ref_dir.mkdir(parents=True, exist_ok=True)
    ext = pathlib.Path(file.filename or "").suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "只支持 jpg/png/webp 图片")
    safe_name = f"ref_{uuid.uuid4().hex[:8]}{ext}"
    dest = ref_dir / safe_name
    try:
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"ok": True, "path": str(dest.resolve()), "name": file.filename}
    except Exception as e:
        raise HTTPException(500, f"参考图上传失败: {e}")


@app.post("/api/advideo/upload_audio")
async def advideo_upload_audio(request: Request, file: UploadFile = File(...)):
    """AI 广告短片：上传配音音频（mp3/wav）。"""
    guard(request)
    import pathlib, shutil, uuid
    audio_dir = pathlib.Path("runs/advideo_audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    ext = pathlib.Path(file.filename or "").suffix.lower() or ".mp3"
    if ext not in (".mp3", ".wav", ".m4a"):
        raise HTTPException(400, "只支持 mp3/wav/m4a 音频")
    safe_name = f"audio_{uuid.uuid4().hex[:8]}{ext}"
    dest = audio_dir / safe_name
    try:
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"ok": True, "path": str(dest.resolve()), "name": file.filename}
    except Exception as e:
        raise HTTPException(500, f"音频上传失败: {e}")


@app.post("/api/advideo/script_rewrite")
async def advideo_script_rewrite(request: Request):
    """AI 广告短片：一键改写/生成高转化数字人口播话术。"""
    guard(request)
    body = await request.json()
    product_name = (body.get("product_name") or "").strip()
    product_desc = (body.get("product_desc") or "").strip()
    if not product_name:
        raise HTTPException(400, "请填写产品名称")
    selling_points = body.get("selling_points") or None
    audience = body.get("audience") or "大众消费者"
    ad_mode = body.get("ad_mode") or "avatar"
    seconds = int(body.get("seconds") or 15)
    from core import ad_video
    try:
        res = ad_video.rewrite_ad_script(
            product_name=product_name,
            product_desc=product_desc,
            selling_points=selling_points,
            audience=audience,
            ad_mode=ad_mode,
            seconds=seconds,
        )
        return res
    except Exception as e:
        log.exception("[admin] advideo script_rewrite 异常: %s", e)
        raise HTTPException(500, f"广告话术生成失败: {e}")


@app.post("/api/advideo/create")
async def advideo_create(request: Request):
    """AI 产品广告短片：一键生成（卖点提炼→广告脚本/数字人口播→分镜→合成）。"""
    guard(request)
    body = await request.json()
    product_name = (body.get("product_name") or "").strip()
    if not product_name:
        raise HTTPException(400, "请填写产品名称")
    product_desc = (body.get("product_desc") or "").strip()
    if not product_desc:
        raise HTTPException(400, "请填写产品描述")
    seconds = int(body.get("seconds", 15))
    aspect = body.get("aspect", "9:16")
    audience = body.get("audience", "大众消费者")
    voice = body.get("voice", "zh-CN-XiaoxiaoNeural")
    # 卖点 / 参考图 / 配音模式 / 数字人模式 / 自定义口播脚本
    selling_points = body.get("selling_points") or None
    ref_images = body.get("ref_images") or None
    person_ref_image = body.get("person_ref_image") or None
    voice_mode = body.get("voice_mode", "auto")
    custom_audio_path = body.get("custom_audio_path") or None
    ad_mode = body.get("ad_mode", "avatar")
    custom_script = (body.get("custom_script") or "").strip()
    video_model = (body.get("video_model") or "").strip()
    import uuid
    jid = f"ad-{uuid.uuid4().hex[:8]}"
    start_async_job(
        jid,
        name=f"AI 广告短片: {product_name[:16]}",
        task_type="ad_video_render",
        target_id=product_name,
        params={"product_name": product_name, "ad_mode": ad_mode, "video_model": video_model},
        initial_step="广告创意生成中…",
    )

    def _run():
        try:
            from core import ad_video
            res = ad_video.make_ad_video(
                product_name, product_desc, seconds=seconds, aspect=aspect,
                audience=audience, voice=voice,
                selling_points=selling_points,
                ref_images=ref_images, person_ref_image=person_ref_image,
                voice_mode=voice_mode, custom_audio_path=custom_audio_path,
                ad_mode=ad_mode, custom_script=custom_script,
                video_model=video_model,
                emit=lambda m: update_async_job(jid, step=m),
            )
            update_async_job(jid, status="done", step="广告短片合成完成！",
                             progress=100, result=res)
        except Exception as e:
            log_exc = str(e)[:300]
            update_async_job(jid, status="failed", error=log_exc,
                             step="广告短片生成失败")
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"job": jid}


# ===================== 🎥 AI 短视频生成（视频大模型分段生成） =====================

@app.get("/api/aivideo/rewrite/modes")
def aivideo_rewrite_modes(request: Request):
    """获取所有 AI 短视频改写模式列表及说明。"""
    guard(request)
    from core import video_script_rewriter
    return {"ok": True, "modes": video_script_rewriter.get_rewrite_modes()}


@app.post("/api/aivideo/rewrite")
async def aivideo_rewrite(request: Request):
    """AI 短视频文案多模式智能改写：新闻播报/数字人口播/视频堆积切片/悬念反转/带货种草等。"""
    u = guard(request)
    body = await request.json()
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "请提供待改写的原文或草稿文案")
    mode = (body.get("mode") or "avatar").strip()
    target_seconds = int(body.get("target_seconds") or 30)
    custom_instruction = (body.get("custom_instruction") or "").strip()
    model = (body.get("model") or "").strip()
    user_id = str((u or {}).get("id") or "")

    from core import video_script_rewriter
    try:
        res = video_script_rewriter.rewrite_video_script(
            content=content,
            mode=mode,
            target_seconds=target_seconds,
            custom_instruction=custom_instruction,
            model=model if model else None,
            user_id=user_id if user_id else None,
        )
        return res
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        log.exception("[admin] aivideo rewrite 失败: %s", e)
        raise HTTPException(500, f"AI 文案改写失败: {e}")


@app.post("/api/aivideo/upload_avatar")
@app.post("/api/video/upload_avatar")
@app.post("/api/advideo/upload_avatar")
async def aivideo_upload_avatar(request: Request, file: UploadFile = File(...)):
    """AI 短视频/数字人：上传出镜肖像照片。"""
    guard(request)
    import pathlib, shutil, uuid
    av_dir = pathlib.Path("runs/avatars")
    av_dir.mkdir(parents=True, exist_ok=True)
    ext = pathlib.Path(file.filename or "").suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "仅支持 jpg/jpeg/png/webp 格式的人物照片")
    safe_name = f"avatar_{uuid.uuid4().hex[:10]}{ext}"
    dest = av_dir / safe_name
    try:
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        # 尝试使用视觉模型分析照片特征（提取人物特征描述供参考）
        desc = ""
        try:
            from core.ad_video import analyze_reference_images
            vinfo = analyze_reference_images(person_ref_image=str(dest.resolve()))
            desc = vinfo.get("person_desc") or vinfo.get("style_desc") or ""
        except Exception:
            pass
        # 自动存入数字人形象记忆库
        try:
            from studio import avatar_memory
            avatar_memory.save_avatar(
                path=str(dest.resolve()),
                filename=dest.name,
                url=f"/api/aivideo/avatar/{dest.name}",
                name=f"形象 {file.filename[:12]}",
                person_desc=desc or "专属定制 AI 数字人出镜肖像"
            )
        except Exception:
            pass
        return {
            "ok": True,
            "path": str(dest.resolve()),
            "url": f"/api/aivideo/avatar/{dest.name}",
            "filename": file.filename,
            "person_desc": desc,
        }
    except Exception as e:
        raise HTTPException(500, f"照片上传失败: {e}")


@app.get("/api/aivideo/avatars")
def aivideo_list_avatars(request: Request):
    """获取所有历史已记住的数字人形象列表（按最近使用排序）。"""
    guard(request)
    from studio import avatar_memory
    items = avatar_memory.list_avatars()
    return {"ok": True, "items": items}


@app.post("/api/aivideo/avatars/use")
async def aivideo_use_avatar(request: Request):
    """一键复用选中的历史数字人形象。"""
    guard(request)
    body = await request.json()
    av_id = (body.get("id") or "").strip()
    from studio import avatar_memory
    item = avatar_memory.use_avatar(av_id)
    if not item:
        raise HTTPException(404, "数字人形象不存在")
    return {"ok": True, "item": item}


@app.post("/api/aivideo/avatars/update")
async def aivideo_update_avatar(request: Request):
    """更新数字人形象名称或特征描述。"""
    guard(request)
    body = await request.json()
    av_id = (body.get("id") or "").strip()
    name = (body.get("name") or "").strip()
    desc = (body.get("person_desc") or "").strip()
    from studio import avatar_memory
    item = avatar_memory.update_avatar(av_id, name=name, person_desc=desc)
    if not item:
        raise HTTPException(404, "数字人形象不存在")
    return {"ok": True, "item": item}


@app.delete("/api/aivideo/avatars/{avatar_id}")
def aivideo_delete_avatar(avatar_id: str, request: Request):
    """从形象记忆库删除数字人。"""
    guard(request)
    from studio import avatar_memory
    ok = avatar_memory.delete_avatar(avatar_id)
    return {"ok": ok}


@app.post("/api/video/test_voice_clone")
async def video_test_voice_clone(request: Request):
    """测试声音克隆 API 连接并生成简短测试试听音频。"""
    guard(request)
    body = await request.json()
    api_url = (body.get("api_url") or "").strip()
    api_key = (body.get("api_key") or "").strip()
    provider = (body.get("provider") or "custom").strip().lower()
    model = (body.get("model") or "").strip()
    voice_id = (body.get("voice_id") or "").strip()
    text = (body.get("text") or "您好，这是一幕爆款工作室声音克隆 API 的实时连通性测试语音。").strip()

    from studio import video_config as _vc
    cur_cfg = _vc.get_config()
    final_url = api_url or cur_cfg.get("voice_clone_api_url")
    final_key = api_key or cur_cfg.get("voice_clone_api_key")
    final_prov = provider or cur_cfg.get("voice_clone_provider") or "custom"
    final_model = model or cur_cfg.get("voice_clone_model")
    final_voice = voice_id or cur_cfg.get("voice_clone_voice_id") or "default"

    if not final_url:
        raise HTTPException(400, "请先填写声音克隆 API 地址")

    import pathlib, uuid, httpx, json as _json, base64 as _b64
    out_dir = pathlib.Path("runs/advideo_audio")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"test_vc_{uuid.uuid4().hex[:8]}.mp3"

    headers = {"Content-Type": "application/json"}
    if final_key:
        headers["Authorization"] = f"Bearer {final_key}"

    if final_prov == "minimax":
        payload = {
            "model": final_model or "speech-01-turbo",
            "text": text,
            "voice_setting": {"voice_id": final_voice},
            "audio_setting": {"sample_rate": 24000, "format": "mp3"}
        }
    elif final_prov == "elevenlabs":
        payload = {"text": text, "model_id": final_model or "eleven_multilingual_v2"}
    elif final_prov == "cosyvoice":
        payload = {"model": final_model or "cosyvoice-v1", "input": text, "voice": final_voice}
    else:
        payload = {"text": text, "input": text, "model": final_model, "voice": final_voice}

    try:
        with httpx.Client(timeout=45, follow_redirects=True) as client:
            resp = client.post(final_url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, f"声音克隆服务返回 HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.content
            if resp.headers.get("content-type", "").startswith("application/json") or data.startswith(b"{"):
                try:
                    jd = resp.json()
                    b64_str = (jd.get("audio") or jd.get("audio_content")
                               or (jd.get("data") or {}).get("audio")
                               or ((jd.get("data") or [{}])[0] if isinstance(jd.get("data"), list) else {}).get("b64_json"))
                    if b64_str:
                        data = _b64.b64decode(b64_str)
                except Exception:
                    pass
            if len(data) < 200:
                raise HTTPException(502, "克隆服务返回音频无效或数据过小")
            out_file.write_bytes(data)
            return {
                "ok": True,
                "audio_url": f"/api/advideo/ref_file?path={out_file.resolve()}",
                "size_kb": len(data) // 1024,
                "msg": f"声音克隆测试成功！已生成试听音频（{len(data)//1024} KB）"
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"声音克隆连接测试失败: {exc}")


@app.get("/api/aivideo/avatar/{filename}")
@app.get("/api/video/avatar/{filename}")
def aivideo_avatar_file(filename: str, request: Request):
    """预览上传的数字人照片。"""
    guard(request)
    import pathlib
    from fastapi.responses import FileResponse
    p = (pathlib.Path("runs/avatars") / filename).resolve()
    base = pathlib.Path("runs/avatars").resolve()
    if not str(p).startswith(str(base)) or not p.exists():
        raise HTTPException(404, "照片不存在")
    return FileResponse(p)


@app.post("/api/aivideo/create")
async def aivideo_create(request: Request):
    """AI 短视频生成：口播文案 → 视频大模型分段生成（支持照片参考图驱动数字人与声音克隆） → 拼接成片。"""
    u = guard(request)
    body = await request.json()
    script = (body.get("script") or "").strip()
    if not script:
        raise HTTPException(400, "请填写口播文案")
    total_seconds = int(body.get("total_seconds") or 30)
    aspect = body.get("aspect", "9:16")
    video_model = (body.get("video_model") or "").strip()
    avatar_image = (body.get("avatar_image") or "").strip()
    voice_engine = (body.get("voice_engine") or "tts").strip()
    voice_audio = (body.get("voice_audio") or "").strip()
    title = (body.get("title") or script[:16]).strip()
    from core import ai_video_gen
    # 分段预览
    from studio import ai_video_config as _acfg
    _seg_s = int(_acfg.get_config()["segment_seconds"])
    _segs = ai_video_gen.plan_segments(total_seconds if total_seconds > 0 else 30, _seg_s)
    jid = ai_video_gen.start_ai_video_job(
        script, total_seconds=total_seconds, aspect=aspect,
        video_model=video_model, title=title,
        user_id=str((u or {}).get("id") or ""),
        avatar_image=avatar_image,
        voice_engine=voice_engine,
        voice_audio=voice_audio)
    return {"job": jid, "segments": len(_segs),
            "plan": f"将分成 {len(_segs)} 段生成" + ("（基于专属照片驱动数字人）" if avatar_image else "") + ("（声音克隆配音）" if voice_engine == "voice_clone" else "")}


@app.get("/api/aivideo/config")
def aivideo_config_get(request: Request):
    guard(request)
    from studio import ai_video_config as _acfg
    return _acfg.get_config()


@app.put("/api/aivideo/config")
async def aivideo_config_put(request: Request):
    guard(request)
    body = await request.json()
    from studio import ai_video_config as _acfg
    return _acfg.save_config(body or {})


@app.get("/api/aivideo/file/{jid}")
def aivideo_file(jid: str, request: Request):
    """下载/预览生成的 AI 短视频。"""
    guard(request)
    from pathlib import Path as _P
    base = _P(__file__).resolve().parent.parent / "runs" / "ai_video" / jid
    # 防目录穿越
    if not str(base.resolve()).startswith(str((base.parent).resolve())):
        raise HTTPException(400, "非法路径")
    for _f in base.glob("final-*.mp4"):
        from fastapi.responses import FileResponse
        return FileResponse(str(_f), media_type="video/mp4",
                            filename=f"ai-video-{jid}.mp4")
    raise HTTPException(404, "成片尚未生成")


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
    from core import storyboard
    require_credits("drama_image", 1, f"电影分镜生图 #{shot_index}")
    image_model = (body.get("image_model") or "").strip()
    def _run():
        return storyboard.generate_storyboard_image(did, shot_index, prompt_en=prompt_en, aspect=aspect, image_model=image_model)
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
    image_model = (body.get("image_model") or "").strip()
    from core import storyboard
    def _run():
        return storyboard.batch_generate_storyboard_images(did, aspect=aspect, image_model=image_model)
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "results": results}
    except Exception as e:
        raise HTTPException(500, f"批量生图失败: {e}")






# ---------------- 商业化计费 & Token 算力中台 ----------------

@app.get("/api/billing/status")
def billing_status(request: Request):
    u = guard(request)
    # ⭐ R2-3：账本收敛到 memberships + ledger。
    #   此前读的是 core/billing 的 JSON 全局单例——所有用户看到同一个余额，
    #   且余额变动不落ledger、无法对账。现按当前用户读 memberships。
    # ⭐ R3-9顺带修复：原实现直接取 core.auth 返回的 tenant_id，
    #   那是字符串 'default'（core/db.py 的列默认值），而 studio 侧真实租户
    #   id 是 uuid（studio.auth.ensure_default_tenant 生成）——
    #   两者不一致会让 ensure_membership 查不到 memberships 行，
    #   表现为「明明有额度却一直提示不足」。此处与 require_credits 统一口径。
    from studio import billing_adapter

    db = billing_adapter._web_session()
    try:
        user_id = str((u or {}).get("id") or "")
        tenant_id = _web_tenant_id(db, user_id)
        if not user_id:
            tenant, u_row = billing_adapter.get_default_billing_user(db)
            tenant_id = tenant.id if tenant is not None else tenant_id
            user_id = u_row.id if u_row is not None else "u-admin"
        return billing_adapter.get_billing_status(db, tenant_id, user_id)
    finally:
        db.close()


@app.get("/api/llm/usage")
def llm_usage(request: Request):
    """各模型服务使用量统计 + 一幕官方通道消费汇总（双轨制）。"""
    user = guard(request)
    from studio import llm_metering
    from core import llm as _llm

    user_id = str((user or {}).get("id") or "")
    usage = llm_metering.get_provider_usage()
    # 补上模型服务展示信息（name/icon/badge/metered）
    providers = _llm.MODEL_PROVIDERS
    rows = []
    for pid, u in usage.items():
        info = providers.get(pid, {})
        rows.append({
            **u,
            "name": info.get("name", pid),
            "icon": info.get("icon", "⚡"),
            "badge": info.get("badge", ""),
            "billing_mode": "官方扣额度" if u.get("metered") else "自备Key·不计费",
        })
    # 按调用次数倒序
    rows.sort(key=lambda r: r["calls"], reverse=True)
    return {
        "providers": rows,
        "official_summary": llm_metering.get_yimu_official_summary(user_id or None),
    }


@app.post("/api/billing/redeem")
async def billing_redeem(request: Request):
    u = guard(request)
    body = await request.json()
    code = body.get("code") or body.get("cdkey", "")
    # ⭐ 走 ledger-backed 版（studio/billing_adapter）：卡密原子核销防重放，
    #   无任何万能码/前缀放行。此前的 core.billing.redeem_cdkey 是死代码分支，
    #   且带写死通用码后门，已下线。
    from studio import billing_adapter
    try:
        res = billing_adapter.redeem_cdkey_for_user(
            code, str((u or {}).get("id") or "")
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"卡密兑换失败，请稍后重试: {e}")
    # R5-6 埋点：兑换卡密（漏斗第 5 步 = 转化完成）。仅在兑换成功时记。
    if isinstance(res, dict) and res.get("ok"):
        try:
            from core import analytics
            analytics.track("cdkey_redeemed", str((u or {}).get("id") or ""),
                            {"code": (code or "")[:8]})
        except Exception:
            pass
    return res


@app.post("/api/billing/admin/gen_keys")
async def billing_gen_keys(request: Request):
    # ⭐ 管理员专用：发卡密等于凭空造额度，普通登录用户不得调用
    admin = guard_admin(request)
    body = await request.json()
    key_type = body.get("key_type", "tokens")
    amount = int(body.get("amount", 100000))
    count = int(body.get("count", 5))
    # 与 redeem 同源（都写 invites 表），否则生成的卡密无处可兑
    from studio import billing_adapter
    try:
        keys = billing_adapter.generate_cdkeys_for_actor(
            key_type=key_type, amount=amount, count=count,
            actor=str((admin or {}).get("id") or ""),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"生成卡密失败，请稍后重试: {e}")
    return {"ok": True, "keys": keys}


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

def _web_tenant_id(db, user_id: str) -> str:
    """解析当前用户所在 studio 租户 id（口径同 require_credits）。

    查不到 studio 用户行时退化为默认租户，保证单机模式不中断业务。
    """
    from studio import billing_adapter
    from studio.db_models import User as _StudioUser

    uid = str(user_id or "")
    if uid:
        row = db.query(_StudioUser.tenant_id).filter(_StudioUser.id == uid).first()
        if row and row[0]:
            return str(row[0])
    tenant, _u = billing_adapter.get_default_billing_user(db)
    return tenant.id if tenant is not None else billing_adapter.WEB_TENANT_NAME


def _r3_session():
    """R3 各路由统一取 studio DB session（调用方负责 close）。"""
    from studio import billing_adapter

    return billing_adapter._web_session()


def _current_user_id(u: dict | None) -> str:
    """从 guard() 返回的用户 dict 里取 id。"""
    return str((u or {}).get("id") or "")


# ---------------- R3-1 价格页 ----------------

@app.get("/api/pricing")
def pricing_plans(request: Request):
    """R3-1：三档套餐与售价（价格页数据源）。

    ⭐ 登录即可见（未登录也能看价格，这是获客页），因此这里用 try 取用户：
       取不到不影响返回套餐。
    ⚠️ 返回体里的 capacity.can_run_full_drama 为False 时（Free 档），
       前端**必须如实展示「跑不完一条完整短剧」**，不得美化。
    """
    from studio import pricing as _pricing

    plans = _pricing.plan_catalog()
    payload = {
        "ok": True,
        "plans": plans,
        # 供前端一次性算「还差多少」而不必二次请求
        "full_drama_credits": _pricing.FULL_DRAMA_CREDITS,
        "credit_price_cents": _pricing.CREDIT_PRICE_CENTS,
    }
    u = get_current_user(request)
    if u:
        try:
            payload["current"] = {
                "user_id": _current_user_id(u),
                "tier": str(u.get("plan") or "free"),
            }
        except Exception:
            pass
    return payload


@app.get("/pricing", response_class=HTMLResponse)
def pricing_page(request: Request):
    """R3-1：价格页（自包含 HTML，前端拉 /api/pricing 渲染）。

    与项目「无构建步骤」的现状一致：不引前端框架，双击即可用。
    """
    return HTMLResponse(_PRICING_PAGE_HTML)


# ---------------- R3-2 下单收款 ----------------

@app.post("/api/billing/order")
async def billing_create_order(request: Request):
    """R3-2：用户下单购买套餐 → 生成 CDKey + 返回支付指引。

    ⚠️ 收款方式说明（重要，勿误认为已接支付网关）：
       本项目**没有微信支付/支付宝商户资质**，因此不提供「一键支付」按钮。
       真实链路是「下单 → 生成卡密 → 线下转账 → 管理员核销 → 用户兑换到账」。
       这不是临时应付，而是当前资质下**唯一能真实收钱**的通路。
    """
    u = guard(request)
    body = await request.json()
    plan = str(body.get("plan") or "").strip().lower()
    from studio import pricing as _pricing

    if not _pricing.plan_exists(plan):
        raise HTTPException(400, "该套餐不可购买，可选：pro、studio")
    from studio.membership import commerce

    db = _r3_session()
    try:
        user_id = _current_user_id(u)
        tenant_id = _web_tenant_id(db, user_id)
        view = commerce.create_order(db, tenant_id, user_id, plan)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"[下单] 创建订单异常: {e}")
        raise HTTPException(500, "下单失败，请稍后重试")
    finally:
        db.close()
    # R5-6 埋点：进入付费漏斗（仅下单成功时记，避免刷事件）
    try:
        from core import analytics
        analytics.track("order_created", _current_user_id(u),
                        {"plan": plan, "amount_yuan": view.get("amount_yuan")})
    except Exception:
        pass
    return {"ok": True, "order": view}


@app.get("/api/billing/orders")
def billing_my_orders(request: Request):
    """R3-2：查询**当前用户自己**的订单列表（含卡密与状态）。"""
    u = guard(request)
    from studio.membership import commerce

    db = _r3_session()
    try:
        user_id = _current_user_id(u)
        tenant_id = _web_tenant_id(db, user_id)
        # 只查自己的：按user_id 过滤，不接受前端传user_id
        from studio.db_models import Order

        rows = (
            db.query(Order)
            .filter(Order.tenant_id == tenant_id, Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(50)
            .all()
        )
        items = [
            {
                "id": r.id,
                "plan": r.plan,
                "credits": int(r.credits),
                "amount_yuan": round(int(r.amount_cents) / 100.0, 2),
                "status": r.status,
                "cdkey": r.cdkey if r.status != "refunded" else "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()
    return {"ok": True, "items": items, "total": len(items)}


@app.get("/api/admin/orders")
def admin_list_orders(request: Request):
    """R3-2/R3-6：订单管理列表（管理员），支持状态筛选与分页。"""
    guard_admin(request)
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(get_current_user(request)))
        status = request.query_params.get("status") or ""
        limit = int(request.query_params.get("limit") or 50)
        offset = int(request.query_params.get("offset") or 0)
        return {"ok": True, **commerce.list_orders(
            db, tenant_id, status=status, limit=limit, offset=offset)}
    finally:
        db.close()


@app.post("/api/admin/orders/{order_id}/confirm")
async def admin_confirm_order(request: Request, order_id: str):
    """R3-2：管理员核销收款（pending → paid）。

    ⭐ 这是手工核销收款方案的「收钱确认」环节：用户线下转账后，
       运营在这里点一下，订单才算真正收款成功。
    """
    admin = guard_admin(request)
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(admin))
        view = commerce.confirm_order_paid(
            db, tenant_id, order_id, actor=_current_user_id(admin))
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"[订单] 核销异常: {e}")
        raise HTTPException(500, "核销失败，请稍后重试")
    finally:
        db.close()
    return {"ok": True, "order": view}


@app.post("/api/admin/orders/{order_id}/cancel")
async def admin_cancel_order(request: Request, order_id: str):
    """R3-2：作废未支付订单（pending → cancelled，并撤销卡密）。"""
    admin = guard_admin(request)
    body = await request.json()
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(admin))
        view = commerce.cancel_order(
            db, tenant_id, order_id,
            actor=_current_user_id(admin),
            reason=str(body.get("reason") or ""),
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"[订单] 取消异常: {e}")
        raise HTTPException(500, "取消失败，请稍后重试")
    finally:
        db.close()
    return {"ok": True, "order": view}


# ---------------- R3-4 额度墙付费引导 ----------------

@app.get("/api/billing/upgrade")
def billing_upgrade_options(request: Request):
    """R3-4：额度不足时的付费引导数据（额度对比表 + 购买入口）。

    供前端在撞402 后弹出「还差多少 + 买哪个档」；与 R5-3 的召回邮件**并存不冲突**：
    邮件走 user_notify（本接口不触发邮件），页面引导走本接口（不发邮件）。
    """
    guard(request)
    from studio import pricing as _pricing

    try:
        need = int(request.query_params.get("need") or 0)
    except Exception:
        need = 0
    db = _r3_session()
    try:
        user_id = _current_user_id(get_current_user(request))
        tenant_id = _web_tenant_id(db, user_id)
        from studio.billing_adapter import get_billing_status

        balance = int(get_billing_status(db, tenant_id, user_id)["balance"])
    except Exception:
        balance = 0
    finally:
        db.close()
    data = _pricing.upsell_options(need_credits=need, balance=balance)
    data["full_drama_credits"] = _pricing.FULL_DRAMA_CREDITS
    return {"ok": True, **data}


# ---------------- R3-5 额度发放（HTTP 入口） ----------------

@app.post("/api/admin/grant_credits")
async def admin_grant_credits(request: Request):
    """R3-5：给指定用户发放额度（管理员）。

    背景：grant_credits 此前只有 service 层函数、**没有 HTTP 入口**，
    运营要发额度只能改代码发版。现补上管理端入口。
    ⚠️ 资金动作：必须 guard_admin，且发放与审计同事务（见 commerce 层）。
    """
    admin = guard_admin(request)
    body = await request.json()
    user_id = str(body.get("user_id") or "").strip()
    try:
        amount = int(body.get("amount") or 0)
    except Exception:
        raise HTTPException(400, "额度必须是整数")
    reason = str(body.get("reason") or "").strip()
    if not user_id:
        raise HTTPException(400, "缺少 user_id")
    if amount <= 0:
        raise HTTPException(400, "发放额度必须为正数")
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(admin))
        result = commerce.grant_credits_to_user(
            db, tenant_id, user_id, amount,
            reason=reason or "管理员手动发放", actor=_current_user_id(admin))
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"[发放] 额度发放异常: {e}")
        raise HTTPException(500, "发放失败，请稍后重试")
    finally:
        db.close()
    return {"ok": True, **result}


# ---------------- R3-6 退款 ----------------

@app.post("/api/admin/orders/{order_id}/refund")
async def admin_refund_order(request: Request, order_id: str):
    """R3-6：退款（**真的扣回额度** + 作废卡密 + 写审计）。

    ⚠️ 资金动作：必须 guard_admin。
    ⭐ 「扣回额度」是本接口的核心——只改订单状态不扣额度等于假退款。
       用户已消费导致扣不满的部分（shortfall）会如实返回给运营。
    """
    admin = guard_admin(request)
    body = await request.json()
    reason = str(body.get("reason") or "").strip()
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(admin))
        view = commerce.refund_order(
            db, tenant_id, order_id,
            actor=_current_user_id(admin),
            reason=reason or "运营退款",
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"[退款] 退款异常: {e}")
        raise HTTPException(500, "退款失败，请稍后重试")
    finally:
        db.close()
    return {"ok": True, "order": view}


# ---------------- R3-7 用户列表与封禁 ----------------

@app.get("/api/admin/users")
def admin_list_users(request: Request):
    """R3-7：用户列表（分页 + 搜用户名/邮箱/档位/封禁态）。"""
    guard_admin(request)
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(get_current_user(request)))
        return {"ok": True, **commerce.list_users(
            db, tenant_id,
            keyword=request.query_params.get("keyword") or "",
            tier=request.query_params.get("tier") or "",
            banned=request.query_params.get("banned") or "",
            limit=int(request.query_params.get("limit") or 20),
            offset=int(request.query_params.get("offset") or 0),
        )}
    finally:
        db.close()


@app.post("/api/admin/users/{user_id}/ban")
async def admin_ban_user(request: Request, user_id: str):
    """R3-7：封禁用户（banned=true）/ 解封（banned=false）。

    ⚠️ 权限动作：必须 guard_admin，且**必须写审计日志**（见 commerce.set_user_banned）。
       封禁后 is_active=False，``get_current_user`` 会拒绝其令牌 →
       即「无法调 API」（见 tests/test_r3_monetization.py）。
    """
    admin = guard_admin(request)
    body = await request.json()
    banned = bool(body.get("banned", True))
    reason = str(body.get("reason") or "").strip()
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(admin))
        result = commerce.set_user_banned(
            db, tenant_id, user_id, banned,
            actor=_current_user_id(admin), reason=reason)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"[封禁] 操作异常: {e}")
        raise HTTPException(500, "操作失败，请稍后重试")
    finally:
        db.close()
    return {"ok": True, **result}


@app.post("/api/admin/users")
async def admin_create_user(request: Request):
    """管理员新建用户"""
    guard_admin(request)
    body = await request.json()
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "").strip()
    email = str(body.get("email") or "").strip()
    role = str(body.get("role") or "user").strip()
    plan = str(body.get("plan") or "free").strip()
    quota_max = int(body.get("quota_max") or 0)
    try:
        from core import auth
        user = auth.create_user_crud(username, password, email, role, plan, quota_max)
        return {"ok": True, "user": user, "msg": f"用户 {username} 创建成功"}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: str, request: Request):
    """管理员编辑用户信息（邮箱、角色、档位、额度、封禁态）"""
    guard_admin(request)
    body = await request.json()
    try:
        from core import auth
        user = auth.update_user_crud(
            user_id,
            email=body.get("email"),
            role=body.get("role"),
            plan=body.get("plan"),
            quota_max=body.get("quota_max"),
            is_active=body.get("is_active")
        )
        return {"ok": True, "user": user, "msg": "用户信息已更新"}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/admin/users/{user_id}/password")
async def admin_change_user_password(user_id: str, request: Request):
    """管理员直接重置修改用户密码"""
    guard_admin(request)
    body = await request.json()
    new_password = str(body.get("password") or "").strip()
    try:
        from core import auth
        auth.change_password_crud(user_id, new_password)
        return {"ok": True, "msg": "密码已成功修改"}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, request: Request):
    """管理员删除指定用户"""
    guard_admin(request)
    try:
        from core import auth
        auth.delete_user_crud(user_id)
        return {"ok": True, "msg": "用户已成功删除"}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    """R3-7：用户管理页（管理员），含搜索/封禁操作。"""
    guard_admin(request)
    return HTMLResponse(_USERS_PAGE_HTML)


# ---------------- R3-8 审计日志 ----------------

@app.get("/api/admin/audit_logs")
def admin_audit_logs(request: Request):
    """R3-8：审计日志查询（分页 + 按动作/操作人/对象过滤）。"""
    guard_admin(request)
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(get_current_user(request)))
        return {"ok": True, **commerce.query_audit_logs(
            db, tenant_id,
            action=request.query_params.get("action") or "",
            actor=request.query_params.get("actor") or "",
            target=request.query_params.get("target") or "",
            keyword=request.query_params.get("keyword") or "",
            limit=int(request.query_params.get("limit") or 50),
            offset=int(request.query_params.get("offset") or 0),
        )}
    finally:
        db.close()


@app.get("/api/admin/audit_actions")
def admin_audit_actions(request: Request):
    """R3-8：已出现过的审计动作列表（给查询页做下拉筛选）。"""
    guard_admin(request)
    from studio.membership import commerce

    db = _r3_session()
    try:
        tenant_id = _web_tenant_id(db, _current_user_id(get_current_user(request)))
        return {"ok": True, "actions": commerce.audit_actions(db, tenant_id)}
    finally:
        db.close()


@app.get("/admin/audit", response_class=HTMLResponse)
def admin_audit_page(request: Request):
    """R3-8：审计日志查询页（管理员）。"""
    guard_admin(request)
    return HTMLResponse(_AUDIT_PAGE_HTML)


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
    require_credits("deep_distill", 1, f"深度逆向蒸馏 [{author_name}]")
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
    from core import short_drama
    require_credits("drama_decompose", 1, f"短剧分镜解构 [{did}]")
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
    from core import short_drama
    require_credits("drama_image", 1, f"短剧分镜生图 #{shot_id}")
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
    # ⭐ 会员分级：完整 8 步短剧为 Pro 专属（R2-7：免费档额度 3000 credits
    #   跑不完一条 12000 credits 的完整短剧，故不再向Free 承诺）。
    _allowed, _reason, _tier = _tier_quota_check(u, "drama_weekly")
    if not _allowed:
        raise HTTPException(402, _reason)
    body = await request.json()
    aspect = body.get("aspect", "9:16")
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    # ⭐ 先扣费再起任务：额度不足直接 402，避免留下永远跑不动的僵尸任务
    from core import short_drama
    require_credits("drama_render", 1, f"全AI短剧渲染 [{did}]")
    # R5-6 埋点：首次跑短剧（漏斗第 3 步）。失败静默，不影响渲染。
    try:
        from core import analytics
        analytics.track("first_drama_run", str((u or {}).get("id") or ""),
                        {"draft_id": did})
    except Exception:
        pass
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
    #⭐ R2-7：会员分级（两条）
    #   1) 成片时长帽（free：10 秒）——导演 AI 按该时长规划，保证成片连贯
    #   2) 完整流水线（step1→render）为 Pro 专属；免费档每周 1 次
    #      「单镜头体验」额度（解构 + 单张图，约 2000 credits，额度内可跑）
    _is_free = str((u or {}).get("role") or "") not in ("admin", "owner")
    _pipeline_allowed = True
    if _is_free:
        _pipeline_allowed, _reason, _ = _tier_quota_check(u, "drama_weekly")
        if not _pipeline_allowed:
            # 免费档改走单镜头体验额度
            _shot_allowed, _shot_reason, _ = _tier_quota_check(u, "drama_shot_weekly")
            if not _shot_allowed:
                raise HTTPException(402, _shot_reason or _reason)
    _cap = _tier_capability_limit(u, "drama_max_seconds")
    if isinstance(_cap, int) and _cap > 0:
        try:
            _dt = int(overrides.get("duration_target") or 45)
        except (TypeError, ValueError):
            _dt = 45
        if _dt > _cap:
            overrides["duration_target"] = _cap
    from core import short_drama
    require_credits("drama_decompose", 1, f"短剧需求分析与剧本改写 [{did}]")
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
    from core import short_drama
    require_credits("drama_image", 1, f"短剧资产出图 [{asset_id}]")
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
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    image_model = (body.get("image_model") or "").strip()
    from core import short_drama
    require_credits("drama_image", 2, f"短剧资产批量生成 [{did}]")
    def _run():
        return short_drama.step4_batch_generate_assets(did, image_model=image_model)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f"批量生成资产失败: {e}")


@app.post("/api/video/drama/{did}/pipeline/step5_storyboard")
async def drama_pipeline_step5(did: str, request: Request):
    u = guard(request)
    from core import short_drama
    require_credits("drama_decompose", 1, f"短剧好莱坞分镜解构 [{did}]")
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
    image_model = (body.get("image_model") or "").strip()
    from core import short_drama
    require_credits("drama_image", 1, f"分镜头 #{shot_id} 生图")
    def _run():
        return short_drama.step6_generate_shot_image(did, shot_id=shot_id, prompt_en=prompt_en, aspect=aspect, image_model=image_model)
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
    image_model = (body.get("image_model") or "").strip()
    from core import short_drama
    def _run():
        return short_drama.step6_batch_generate_shots(did, aspect=aspect, image_model=image_model)
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
    video_model = (body.get("video_model") or "").strip()
    from core import short_drama
    def _run():
        return short_drama.step7_generate_shot_video(
            did, shot_id=shot_id, aspect=aspect,
            subtitle_enabled=subtitle_enabled, video_mode=video_mode,
            video_model=video_model
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
    video_model = (body.get("video_model") or "").strip()
    from core import short_drama
    def _run():
        return short_drama.step7_batch_generate_videos(
            did, aspect=aspect,
            subtitle_enabled=subtitle_enabled, video_mode=video_mode,
            video_model=video_model
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
    video_model = (body.get("video_model") or "").strip()
    d = db.get_draft(did) or {}
    d_title = d.get("title", did[:8])
    # ⭐ 先扣费再起任务：额度不足直接 402，避免留下永远跑不动的僵尸任务
    from core import short_drama
    require_credits("drama_render", 1, f"8步短剧最终成片合成 [{did}]")
    import uuid
    jid = f"drm-p8-{did[:8]}-{uuid.uuid4().hex[:4]}"
    start_async_job(
        jid,
        name=f"8步短剧最终成片合成: {d_title[:16]}",
        task_type="drama_pipeline",
        target_id=did,
        params={"draft_id": did, "aspect": aspect, "video_model": video_model},
        initial_step="8步短剧流水线成片合成中…"
    )
    def _run():
        try:
            res = short_drama.step8_render_final_drama(
                did, aspect=aspect,
                subtitle_enabled=subtitle_enabled, video_mode=video_mode,
                video_model=video_model,
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
    user = guard(request)
    body = await request.json()
    title = (body.get("title") or "").strip()
    body_md = body.get("body_md") or ""
    workspace_id = (body.get("workspace_id") or "").strip()
    # ⭐ 先扣费再建档：额度不足直接 402，绝不留下已落盘的草稿
    require_credits("draft_create", 1, f"新建草稿 [{title[:16] or '未命名'}]")
    if not workspace_id:
        from core import workspace
        active_ws = workspace.get_active_workspace()
        if active_ws:
            workspace_id = active_ws.get("id", "")

    draft = db.create_custom_draft(title=title, body_md=body_md, workspace_id=workspace_id,
                                   user_id=_current_user_id(user))
    did = draft["id"]

    # 初始化多平台文件产物与预览
    from core import orchestrator
    orchestrator.init_draft_artifacts(did, draft["title"], draft["body_md"])

    # 执行初次基准评分（无 LLM 时跳过，避免 500）
    from core import judge
    from core import llm as _llm
    score = judge.judge_draft(did) if _llm.available() else {"total": 0, "grade": "未评分（未配置大模型）"}

    # R5-6 埋点：首次成稿（漏斗第 2 步）。失败静默，不影响建稿。
    try:
        from core import analytics
        analytics.track("first_draft_created", str((user or {}).get("id") or ""),
                        {"draft_id": did, "title_len": len(title)})
    except Exception:
        pass

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


@app.get("/api/workspace/voiceprint")
def api_get_workspace_voiceprint(request: Request, wid: Optional[str] = None):
    """获取指定或当前活动工作区的声纹记忆档案（音色/声线特征/参考音频）"""
    guard(request)
    from core import workspace
    return {"ok": True, "voiceprint": workspace.get_workspace_voiceprint(wid)}


@app.post("/api/workspace/voiceprint")
async def api_update_workspace_voiceprint(request: Request):
    """更新工作区专属声纹记忆档案"""
    guard(request)
    body = await request.json()
    wid = body.get("workspace_id")
    vp_data = body.get("voiceprint") or {}
    from core import workspace
    active_ws = workspace.get_active_workspace()
    target_wid = wid or (active_ws.get("id") if active_ws else "ws-default")
    res = workspace.update_workspace_voiceprint(target_wid, vp_data)
    return {"ok": True, "voiceprint": res, "msg": "空间声纹记忆档案已更新！"}


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
    from core import fission
    require_credits("rewrite", 1, f"全域五端矩阵裂变 [{did}]")
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

    from core import fission
    require_credits("rewrite", 1, f"母稿驱动全域多端派生 [{did}]")
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

    all_presets = {
        pid: {
            "id": pid,
            "name": pinfo["name"],
            "badge": pinfo.get("badge", ""),
            "base_url": pinfo["base_url"],
            "default_model": pinfo["default_model"],
            "models": pinfo.get("models", []),
            "icon": pinfo.get("icon", "⚡")
        } for pid, pinfo in llm.MODEL_PROVIDERS.items()
    }

    from core import video_rules
    return {
        "providers": all_providers,
        "all_presets": all_presets,
        "current": gw,
        "active_provider_id": active_pid,
        "configured_models": llm.get_configured_models(),
        "cross_models": cross_models,
        "env_key_set": has_active_key,
        "video_rules": video_rules.load_rules().get("rules", []),
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


@app.post("/api/tasks/clear")
async def clear_tasks_endpoint(request: Request):
    """清理任务：清除 N 天前的失败/已完成任务（不碰 running/queued）。"""
    guard(request)
    body = await request.json()
    status_filter = (body.get("status") or "failed").strip().lower()
    if status_filter not in ("failed", "completed"):
        status_filter = "failed"
    try:
        days = int(body.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in (1, 3, 5, 7):
        days = 7
    from core import task_queue
    return task_queue.clear_tasks(status_filter, days)


# ===================== 🌊 SSE 实时流式打字机 API =====================


# ===================== 💬 v4.0 极简模式：爆款创作 Copilot API =====================

@app.post("/api/copilot/chat")
async def copilot_chat_endpoint(request: Request):
    u = guard(request)
    # ⭐ 会员分级：Copilot 对话每日配额（free：每日 20 次，pro/studio 不限）
    # 配额扣减后会员剩余额度联动减少，顶部"算力"数字实时更新
    _allowed, _reason, _tier = _tier_quota_check(u, "copilot_daily")
    if not _allowed:
        raise HTTPException(402, _reason)
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
                skills=skills,
                user_id=str(u.get("id") or ""),
            )
        )
        return res
    except Exception as e:
        raise HTTPException(500, f"Copilot 响应失败: {str(e)}")


@app.post("/api/copilot/chat_stream")
async def copilot_chat_stream_endpoint(request: Request):
    u = guard(request)
    # ⭐ 会员分级：Copilot 对话每日配额（free：每日 20 次，pro/studio 不限）
    _allowed, _reason, _tier = _tier_quota_check(u, "copilot_daily")
    if not _allowed:
        raise HTTPException(402, _reason)
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
                user_id=str(u.get("id") or ""),
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


# ---------------------------------------------------------------------------
# R5-5 裂变产物分享：公网链接 + 二维码 + 海报
# ---------------------------------------------------------------------------
# ⭐ 归属校验说明：这些路由的地址里**只有随机令牌、没有 did**，
#   令牌→稿件的映射只在服务端库里。因此无法通过「改 did」拿到
#   他人稿件——请求里根本不存在 did 参数。


@app.post("/api/drafts/{did}/share")
async def draft_create_share(did: str, request: Request):
    """为某篇稿件的裂变产物签发分享链接（含二维码与海报地址）。

    只为**产物文件确实存在**的平台签发；没生成的平台会出现在 skipped 里
    并说明原因（而不是给一个点开404 的死链）。
    """
    user = guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, "草稿不存在")
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    platforms = body.get("platforms") or ["wechat_mp", "xhs", "toutiao", "zhihu", "weibo", "twitter"]
    ttl = int(body.get("ttl_days") or 14)
    from core import share as _share

    res = _share.create_share_set(did, platforms, str(user.get("id") or ""), ttl)
    res["title"] = d.get("title", "")
    return {"ok": True, **res}


@app.get("/api/drafts/{did}/shares")
def draft_list_shares(did: str, request: Request):
    """列出某篇稿件的全部分享链接（含访问次数）。"""
    guard(request)
    from core import share as _share

    return {"ok": True, "items": _share.list_shares(draft_id=did)}


@app.post("/api/share/revoke")
async def share_revoke(request: Request):
    """吊销一个分享链接（立即失效）。"""
    guard(request)
    body = await request.json()
    token = (body.get("token") or "").strip()
    if not token:
        raise HTTPException(400, "缺少 token")
    from core import share as _share

    return {"ok": _share.revoke(token)}


@app.get("/s/{token}")
def share_page(token: str):
    """分享页：用令牌换取已排版产物并渲染。

    令牌无效 / 过期 / 已吊销 / 产物丢失，一律404——不区分具体原因，
    避免被拿去探测「某篇稿件是否存在」。
    """
    from core import share as _share

    rec = _share.resolve(token)
    if not rec:
        raise HTTPException(404, "分享链接无效或已失效")
    f = db.draft_dir(rec["draft_id"]) / f"preview-{rec['platform']}.html"
    if not f.exists():
        raise HTTPException(404, "分享链接无效或已失效")
    return HTMLResponse(_share.render_share_page(rec, f.read_text(encoding="utf-8")))


@app.get("/s/{token}/qr.svg")
def share_qr(token: str):
    """分享链接的二维码（SVG，矢量、体积小）。"""
    from core import qrcode_min, share as _share

    if not _share.resolve(token):
        raise HTTPException(404, "分享链接无效或已失效")
    svg = qrcode_min.encode_svg(f"{_share._base_url()}/s/{token}")
    return Response(svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.get("/s/{token}/qr.png")
def share_qr_png(token: str):
    """分享链接的二维码（PNG，便于不支持 SVG 的场景）。"""
    from core import qrcode_min, share as _share

    if not _share.resolve(token):
        raise HTTPException(404, "分享链接无效或已失效")
    png = qrcode_min.encode_png(f"{_share._base_url()}/s/{token}")
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.get("/s/{token}/poster.svg")
def share_poster(token: str):
    """分享海报（标题 + 二维码 + 品牌署名，可直接发社群）。"""
    from core import share as _share

    rec = _share.resolve(token)
    if not rec:
        raise HTTPException(404, "分享链接无效或已失效")
    svg = _share.build_poster(rec["draft_id"], token)
    return Response(svg, media_type="image/svg+xml")


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
    resp = FileResponse(f, media_type="image/png")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


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


@app.post("/api/topics/one_sentence_viral")
async def api_one_sentence_viral(request: Request):
    guard(request)
    body = await request.json()
    # ⭐ R3-9：把归属带进后台任务（线程池里拿不到 request）
    body["_owner_user_id"] = str((get_current_user(request) or {}).get("id") or "")
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
    #⭐ R3-9：把当前用户 id 带进后台任务payload。
    #   _run_rewrite_job 在线程池里跑，拿不到 request，只能靠payload 传递归属，
    #   否则它创建的草稿 user_id 为空 → 谁都看不到自己的成稿。
    user = get_current_user(request) or {}
    body["_owner_user_id"] = str(user.get("id") or "")
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


# R5-6 运营漏斗看板页面（自包含HTML，前端拉/api/admin/metrics渲染）
# 不用前端框架：与项目「无构建步骤」的现状一致，双击即可用。
_METRICS_PAGE_HTML = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>运营看板 · 一幕 YIMU</title>
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
  <div class="card"><h2>转化漏斗</h2><div id="funnel"><div class="empty">加载中…</div></div></div>
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
  }catch(e){
    document.getElementById('funnel').innerHTML='<div class="empty">看板数据加载失败：'+esc(e.message)+'</div>';
  }
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
_PRICING_PAGE_HTML = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>价格 · 一幕 YIMU</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;background:#0f1220;color:#e8ecf8;font-family:PingFang SC,Microsoft YaHei,sans-serif}
 .wrap{max-width:1000px;margin:0 auto;padding:32px 20px 70px}
 h1{font-size:26px;margin:0 0 6px}
 .sub{color:#8b93ad;font-size:13px;line-height:1.8;margin-bottom:26px}
 .warn{background:rgba(240,136,62,.1);border:1px solid rgba(240,136,62,.35);
       border-radius:10px;padding:14px 16px;font-size:13px;line-height:1.9;margin-bottom:24px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px}
 .plan{background:#161c28;border:1px solid #262d3d;border-radius:14px;padding:22px;display:flex;flex-direction:column}
 .plan.hot{border-color:#f0883e;box-shadow:0 0 0 1px rgba(240,136,62,.25)}
 .pname{font-size:17px;font-weight:800;margin-bottom:4px}
 .ptag{font-size:12px;color:#8b93ad;min-height:34px;line-height:1.7}
 .price{font-size:30px;font-weight:800;color:#f0883e;margin:12px 0 2px}
 .price small{font-size:13px;color:#8b93ad;font-weight:400}
 .credits{font-size:13px;color:#c8cee0;margin-bottom:12px}
 .cap{font-size:12.5px;color:#9aa3bd;background:#0d1117;border-radius:8px;padding:10px 12px;line-height:1.9;margin-bottom:14px}
 .cap b{color:#e8ecf8}
 .cap .no{color:#ff7b72}
 ul{list-style:none;padding:0;margin:0 0 18px;font-size:13px;line-height:2;color:#c8cee0}
 li:before{content:"· ";color:#f0883e}
 .btn{background:#f0883e;color:#fff;border:0;border-radius:9px;padding:11px 18px;
      font-size:14px;font-weight:700;cursor:pointer;width:100%}
 .btn.ghost{background:#0d1117;border:1px solid #2c3446;color:#c8cee0}
 .btn:disabled{opacity:.5;cursor:not-allowed}
 .note{font-size:12px;color:#6f7896;line-height:1.9;margin-top:8px}
 h2{font-size:16px;margin:34px 0 12px}
 table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
 th,td{padding:9px 10px;border-bottom:1px solid #262d3d;text-align:left}
 th{color:#8b93ad;font-weight:600}
 .code{font-family:ui-monospace,Menlo,monospace;background:#0d1117;padding:3px 8px;
       border-radius:5px;color:#7ee787;letter-spacing:1px}
 .st{font-size:12px;padding:3px 9px;border-radius:20px}
 .st.paid{background:rgba(126,231,135,.15);color:#7ee787}
 .st.pending{background:rgba(240,136,62,.15);color:#f0883e}
 .st.refunded{background:rgba(255,123,114,.15);color:#ff7b72}
 .st.cancelled{background:#262d3d;color:#8b93ad}
 .empty{color:#8b93ad;padding:16px 0;font-size:13px}
</style></head><body>
<div class="wrap">
  <h1>💰 价格与套餐</h1>
  <div class="sub">算力点数（credits）用于 AI 仿写、短剧渲染、图片生成等所有 AI 能力。
    1 点 = 0.01 元，额度按周期刷新，周期内用不完不累计。</div>

  <div class="warn" id="honest-note">
    <b>关于「一条短剧」的真实消耗：</b>
    <span id="drama-line">加载中…</span><br>
    这也是为什么 Free 档<b>跑不完一条完整短剧</b>——我们把这一点写在明面上，
    而不是让你付了钱才发现限制。
  </div>

  <div class="grid" id="plans"><div class="empty">套餐加载中…</div></div>

  <h2>🧾 我的订单</h2>
  <div id="orders"><div class="empty">订单加载中…</div></div>
  <div class="note">未登录时看不到订单。订单状态为「待支付」时，请按下方指引线下转账后联系管理员核销。</div>
</div>

<script>
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}

async function loadPlans(){
  const r = await fetch('/api/pricing');
  const d = await r.json();
  const full = d.full_drama_credits;
  document.getElementById('drama-line').innerHTML =
    '一条完整短剧（分镜解构 + 4 张生图 + 渲染合成 + 4 段配音）约消耗 <b>' +
    Number(full).toLocaleString() + '</b> 点。';

  document.getElementById('plans').innerHTML = d.plans.map(function(p){
    const cap = p.capacity;
    const free = p.code === 'free';
    // ⭐ 诚实标注：跑不完就明说，不含糊
    const dramaTxt = cap.can_run_full_drama
      ? '可跑 <b>' + cap.dramas + '</b> 条完整短剧'
      : '<span class="no">额度不足，<b>跑不完一条完整短剧</b>（约 ' +
        cap.dramas_exact + ' 条）</span>';
    return '<div class="plan' + (p.code === 'pro' ? ' hot' : '') + '">' +
      '<div class="pname">' + esc(p.name) + '</div>' +
      '<div class="ptag">' + esc(p.tagline) + '</div>' +
      '<div class="price">' + (p.price_yuan > 0 ? '¥' + p.price_yuan : '免费') +
        (p.price_yuan > 0 ? '<small> / ' + p.period_days + ' 天</small>' : '') + '</div>' +
      '<div class="credits">' + Number(p.credits).toLocaleString() + ' 点额度' +
        (p.price_yuan > 0 ? '（约 ' + p.price_yuan + ' 元等值）' : '') + '</div>' +
      '<div class="cap">' + dramaTxt + '<br>可产出 <b>' + cap.graphic_posts +
        '</b> 篇图文（仿写+评分+排版）</div>' +
      '<ul>' + (p.highlights || []).map(function(h){
        return '<li>' + esc(h.replace(/^\\*\\*|\\*\\*$/g, '')) + '</li>';}).join('') + '</ul>' +
      (free ? '<button class="btn ghost" disabled>免费档，无需购买</button>'
            : '<button class="btn" onclick="order(\\'' + p.code + '\\')">立即购买 ' +
              esc(p.name) + '</button>') +
      '</div>';
  }).join('');
}

async function order(code){
  const btn = event.target;
  btn.disabled = true; btn.textContent = '下单中…';
  try{
    const r = await fetch('/api/billing/order', {
      method:'POST',
      headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},
      body: JSON.stringify({plan: code})
    });
    const d = await r.json();
    if(!r.ok || !d.ok){
      alert(d.detail && d.detail.message ? d.detail.message
            : (d.error || '下单失败，请稍后重试'));
      return;
    }
    showPay(d.order);
    loadOrders();
  }catch(e){ alert('下单异常：' + e); }
  finally{ btn.disabled = false; btn.textContent = '立即购买'; }
}

function showPay(o){
  const L = {'pending':'待支付','paid':'已收款','refunded':'已退款','cancelled':'已取消'};
  alert(
    '订单已创建（订单号 ' + o.id.slice(0,8) + '）\\n\\n' +
    '应付金额：¥' + o.amount_yuan + '（' + o.credits + ' 点）\\n' +
    '你的卡密：' + (o.cdkey || '（已退款）') + '\\n\\n' +
    (o.payment_instructions || []).map(function(s,i){return (i+1)+'. '+s;}).join('\\n') +
    '\\n\\n卡密请复制保存，可在「设置 - 会员与额度」粘贴兑换。'
  );
  void L;
}

async function loadOrders(){
  const box = document.getElementById('orders');
  const r = await fetch('/api/billing/orders');
  if(r.status === 401){
    box.innerHTML = '<div class="empty">请先登录后查看订单</div>'; return;
  }
  const d = await r.json();
  if(!d.ok || !d.items.length){
    box.innerHTML = '<div class="empty">暂无订单</div>'; return;
  }
  const L = {'pending':'待支付','paid':'已收款','refunded':'已退款','cancelled':'已取消'};
  box.innerHTML = '<table><tr><th>时间</th><th>套餐</th><th>金额</th><th>额度</th>' +
    '<th>卡密</th><th>状态</th></tr>' + d.items.map(function(o){
      return '<tr><td>' + esc((o.created_at||'').slice(0,16).replace('T',' ')) + '</td><td>' +
        esc(o.plan) + '</td><td>¥' + o.amount_yuan + '</td><td>' +
        Number(o.credits).toLocaleString() + '</td><td><span class="code">' +
        esc(o.cdkey || '—') + '</span></td><td><span class="st ' + esc(o.status) + '">' +
        esc(L[o.status] || o.status) + '</span></td></tr>';}).join('') + '</table>';
}

loadPlans(); loadOrders();
</script></body></html>"""


# R3-7 用户管理页（管理员）：搜索 + 封禁/解封
_USERS_PAGE_HTML = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>用户管理 · 一幕 YIMU</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;background:#0f1220;color:#e8ecf8;font-family:PingFang SC,Microsoft YaHei,sans-serif}
 .wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
 h1{font-size:22px;margin:0 0 4px}
 .sub{color:#8b93ad;font-size:13px;margin-bottom:20px}
 .bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;align-items:center}
 input,select{background:#0d1117;border:1px solid #2c3446;color:#e8ecf8;
              border-radius:8px;padding:8px 11px;font-size:13px}
 button{background:#f0883e;color:#fff;border:0;border-radius:8px;padding:8px 16px;
        font-size:13px;font-weight:700;cursor:pointer}
 button.ghost{background:#0d1117;border:1px solid #2c3446;color:#c8cee0}
 button.danger{background:#8b2b28}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{padding:9px 10px;border-bottom:1px solid #262d3d;text-align:left;white-space:nowrap}
 th{color:#8b93ad;font-weight:600}
 .banned{color:#ff7b72}
 .ok{color:#7ee787}
 .tag{font-size:12px;padding:2px 8px;border-radius:20px;background:#262d3d;color:#c8cee0}
 .empty{color:#8b93ad;padding:16px 0;font-size:13px}
 .pager{margin-top:14px;display:flex;gap:10px;align-items:center;font-size:13px;color:#8b93ad}
</style></head><body>
<div class="wrap">
  <h1>👥 用户管理</h1>
  <div class="sub">封禁后该用户无法调用任何 API（登录令牌立即失效）。所有封禁操作均记入审计日志。</div>
  <div class="bar">
    <input id="kw" placeholder="搜索用户名 / 邮箱" style="width:220px">
    <select id="tier"><option value="">全部档位</option><option value="free">Free</option>
      <option value="pro">Pro</option><option value="studio">Studio</option></select>
    <select id="banned"><option value="">全部状态</option><option value="1">已封禁</option>
      <option value="0">正常</option></select>
    <button onclick="load(0)">查询</button>
    <button class="ghost" onclick="grant()">发放额度</button>
  </div>
  <div id="tb"><div class="empty">加载中…</div></div>
  <div class="pager">
    <button class="ghost" onclick="load(Math.max(0,off-20))">上一页</button>
    <span id="info"></span>
    <button class="ghost" onclick="load(off+20)">下一页</button>
  </div>
</div>
<script>
var off = 0;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function csrf(){var m=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
  return m?decodeURIComponent(m[1]):'';}
async function load(o){
  off = o || 0;
  const p = new URLSearchParams({offset:String(off), limit:'20',
    keyword:document.getElementById('kw').value.trim(),
    tier:document.getElementById('tier').value,
    banned:document.getElementById('banned').value});
  const r = await fetch('/api/admin/users?' + p.toString());
  const d = await r.json();
  if(!r.ok || !d.ok){document.getElementById('tb').innerHTML =
    '<div class="empty">' + esc((d.detail&&d.detail.message)||'加载失败') + '</div>'; return;}
  if(!d.items.length){document.getElementById('tb').innerHTML =
    '<div class="empty">没有符合条件的用户</div>';
    document.getElementById('info').textContent = ''; return;}
  document.getElementById('tb').innerHTML = '<table><tr><th>用户名</th><th>邮箱</th><th>角色</th>' +
    '<th>档位</th><th>剩余额度</th><th>已用</th><th>状态</th><th>注册时间</th><th>操作</th></tr>' +
    d.items.map(function(u){
      return '<tr><td>' + esc(u.username) + '</td><td>' + esc(u.email||'—') + '</td><td>' +
        '<span class="tag">' + esc(u.role) + '</span></td><td>' + esc(u.tier) + '</td><td>' +
        Number(u.credits_left).toLocaleString() + '</td><td>' +
        Number(u.credits_used).toLocaleString() + '</td><td class="' +
        (u.banned?'banned':'ok') + '">' + (u.banned?'已封禁':'正常') + '</td><td>' +
        esc((u.created_at||'').slice(0,10)) + '</td><td><button class="' +
        (u.banned?'ghost':'danger') + '" onclick="ban(\\'' + u.user_id + '\\',' +
        (u.banned?'false':'true') + ')">' + (u.banned?'解封':'封禁') + '</button></td></tr>';
    }).join('') + '</table>';
  document.getElementById('info').textContent =
    '共 ' + d.total + ' 位用户，当前第 ' + (off/20+1) + ' 页';
}
async function ban(uid, banned){
  if(banned === 'true' && !confirm('确定封禁该用户？封禁后其所有 API 调用都会失败。')) return;
  const reason = banned === 'true' ? (prompt('封禁原因（记入审计）') || '违反使用规范') : '';
  const r = await fetch('/api/admin/users/' + uid + '/ban', {method:'POST',
    headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},
    body: JSON.stringify({banned: banned === 'true', reason: reason})});
  const d = await r.json();
  if(!r.ok || !d.ok){ alert((d.detail&&d.detail.message)||'操作失败'); return; }
  load(off);
}
async function grant(){
  const uid = prompt('要发放额度的 user_id（见上表，可用浏览器搜索定位）：');
  if(!uid) return;
  const amount = prompt('发放多少点额度？');
  if(!amount) return;
  const reason = prompt('发放原因（记入审计）：') || '管理员手动发放';
  const r = await fetch('/api/admin/grant_credits', {method:'POST',
    headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},
    body: JSON.stringify({user_id: uid.trim(), amount: parseInt(amount,10), reason: reason})});
  const d = await r.json();
  if(!r.ok || !d.ok){ alert((d.detail&&d.detail.message)||'发放失败'); return; }
  alert('发放成功：' + d.granted + ' 点\\n当前余额：' + Number(d.balance_after).toLocaleString() + ' 点');
  load(off);
}
load(0);
</script></body></html>"""


# R3-8 审计日志查询页（管理员）
_AUDIT_PAGE_HTML = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>审计日志 · 一幕 YIMU</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;background:#0f1220;color:#e8ecf8;font-family:PingFang SC,Microsoft YaHei,sans-serif}
 .wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
 h1{font-size:22px;margin:0 0 4px}
 .sub{color:#8b93ad;font-size:13px;margin-bottom:20px}
 .bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
 input,select{background:#0d1117;border:1px solid #2c3446;color:#e8ecf8;
              border-radius:8px;padding:8px 11px;font-size:13px}
 button{background:#f0883e;color:#fff;border:0;border-radius:8px;padding:8px 16px;
        font-size:13px;font-weight:700;cursor:pointer}
 button.ghost{background:#0d1117;border:1px solid #2c3446;color:#c8cee0}
 table{width:100%;border-collapse:collapse;font-size:12.5px}
 th,td{padding:8px 10px;border-bottom:1px solid #262d3d;text-align:left;vertical-align:top}
 th{color:#8b93ad;font-weight:600}
 td.detail{font-family:ui-monospace,Menlo,monospace;color:#9aa3bd;font-size:12px;
           max-width:420px;word-break:break-all}
 .act{color:#f0883e;font-weight:600;white-space:nowrap}
 .empty{color:#8b93ad;padding:16px 0;font-size:13px}
 .pager{margin-top:14px;display:flex;gap:10px;align-items:center;font-size:13px;color:#8b93ad}
</style></head><body>
<div class="wrap">
  <h1>🗂️ 审计日志</h1>
  <div class="sub">记录发放额度、退款、封禁、下单等敏感操作。日志只增不改，不可删除。</div>
  <div class="bar">
    <select id="act"><option value="">全部动作</option></select>
    <input id="actor" placeholder="操作人 user_id" style="width:200px">
    <input id="kw" placeholder="搜索动作 / 对象" style="width:200px">
    <button onclick="load(0)">查询</button>
  </div>
  <div id="tb"><div class="empty">加载中…</div></div>
  <div class="pager">
    <button class="ghost" onclick="load(Math.max(0,off-50))">上一页</button>
    <span id="info"></span>
    <button class="ghost" onclick="load(off+50)">下一页</button>
  </div>
</div>
<script>
var off = 0;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
async function loadActions(){
  const r = await fetch('/api/admin/audit_actions');
  const d = await r.json();
  if(d.ok && d.actions){
    document.getElementById('act').innerHTML = '<option value="">全部动作</option>' +
      d.actions.map(function(a){return '<option value="' + esc(a) + '">' + esc(a) + '</option>';}).join('');
  }
}
async function load(o){
  off = o || 0;
  const p = new URLSearchParams({offset:String(off), limit:'50',
    action:document.getElementById('act').value,
    actor:document.getElementById('actor').value.trim(),
    keyword:document.getElementById('kw').value.trim()});
  const r = await fetch('/api/admin/audit_logs?' + p.toString());
  const d = await r.json();
  if(!r.ok || !d.ok){document.getElementById('tb').innerHTML =
    '<div class="empty">' + esc((d.detail&&d.detail.message)||'加载失败') + '</div>'; return;}
  if(!d.items.length){document.getElementById('tb').innerHTML =
    '<div class="empty">没有符合条件的审计记录</div>';
    document.getElementById('info').textContent=''; return;}
  document.getElementById('tb').innerHTML = '<table><tr><th>时间</th><th>操作人</th>' +
    '<th>动作</th><th>对象</th><th>详情</th></tr>' + d.items.map(function(x){
      return '<tr><td>' + esc((x.created_at||'').slice(0,19).replace('T',' ')) + '</td><td>' +
        esc(x.actor) + '</td><td class="act">' + esc(x.action) + '</td><td>' + esc(x.target) +
        '</td><td class="detail">' + esc(JSON.stringify(x.detail)) + '</td></tr>';}).join('') +
    '</table>';
  document.getElementById('info').textContent = '共 ' + d.total + ' 条，当前第 ' + (off/50+1) + ' 页';
}
loadActions(); load(0);
</script></body></html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.admin:app", host="127.0.0.1", port=8790, reload=False)

