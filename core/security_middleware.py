# SPDX-License-Identifier: BUSL-1.1
"""R4-8 安全中间件：CSRF 防护（Double Submit Cookie）+ 安全响应头。

为什么需要
----------
全仓此前 ``csrf`` 零命中，Cookie 是 ``samesite=lax``。lax 只阻止**跨站**发 Cookie，
但 ``lax`` 允许「同站不同源」与部分导航场景，且本系统的状态变更接口
（``POST /api/drafts/{id}/publish``、``DELETE /api/user/vault/keys/{kid}`` 等）
**完全依赖 Cookie 鉴权**。攻击者诱导用户浏览器发起 POST，即可让系统向
小红书/公众号真实发布内容——责任在公司（Licensor）不在用户。

设计：区分「浏览器表单」与「API 调用」
------------------------------------
本项目同时服务两类客户端：

1. **浏览器页面**（index.html / mobile.html）：靠 Cookie 鉴权 → **必须带 CSRF token**
2. **API 客户端**（网关 SDK、curl、外部脚本）：靠 ``Authorization: Bearer`` 鉴权
   → Bearer 凭据不会由浏览器自动附带，天然免疫 CSRF，**不要求 token**

判定顺序（任一命中即放行）：

- 安全方法（GET/HEAD/OPTIONS）
- 请求带 ``Authorization`` 头 → 视为 API 客户端
- 请求无会话 Cookie（且无跨站 Origin/Referer）→ 无 Cookie 鉴权可滥用，交给下游 ``guard()`` 拒绝
- 环境变量 ``CSRF_PROTECTION_ENABLED=0`` 可整体关闭（应急回滚）

其余情况一律要求：Cookie ``csrf_token`` 与请求头 ``X-CSRF-Token`` 一致，
并叠加 ``Origin`` 同源校验作为纵深防御。
"""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

BASE = Path(__file__).resolve().parent.parent

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# 放行的路径前缀：登录/注册本身不需要 CSRF（否则用户无法登录），
# 且这些接口不依赖已有会话 Cookie 造成危害。
CSRF_EXEMPT_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/status",
)

# 出站 API 域名（前端需直连的第三方），用于 CSP connect-src
CSP_CONNECT_SRC = [
    "'self'",
    "https://api.anthropic.com",
    "https://api.deepseek.com",
    "https://api.openai.com",
    "https://api.siliconflow.cn",
    "https://dashscope.aliyuncs.com",
    "https://generativelanguage.googleapis.com",
    "https://pixabay.com",
    "https://www.pexels.com",
]

# ⚠️ 关于 CSP 的诚实说明：
# index.html 有约 19000 行内联 <script> 与大量 onclick 内联事件处理器，
# 若用 nonce/hash 严格化需重写整个前端（工程量与回归风险都不可接受）。
# 因此 script-src / style-src 保留 'unsafe-inline'，
# CSP 在此主要提供 object-src/frame-ancestors/base-uri/form-action 等
# 注入面收敛 + 按需 HTTPS 升级，**不等于**完整 XSS 防护。
CSP_BASE_DIRECTIVES = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    "media-src 'self' blob:",
    "connect-src " + " ".join(CSP_CONNECT_SRC),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
]

CSP = "; ".join([*CSP_BASE_DIRECTIVES, "upgrade-insecure-requests"])


def _csp_for_request(request) -> str:
    """根据请求协议生成 CSP：仅在 HTTPS 下启用 upgrade-insecure-requests，防止公网纯 HTTP 部署静态资源加载报错。"""
    scheme = getattr(getattr(request, "url", None), "scheme", "http")
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if scheme == "https" or forwarded_proto == "https":
        return CSP
    return "; ".join(CSP_BASE_DIRECTIVES)


def csrf_enabled() -> bool:
    """CSRF 防护总开关（CSRF_PROTECTION_ENABLED，默认开启）。"""
    return os.environ.get("CSRF_PROTECTION_ENABLED", "1").strip().lower() not in {
        "0", "false", "off", "no", "disabled",
    }


def ensure_csrf_cookie(response: Response, request=None) -> str:
    """确保响应带 csrf_token Cookie，返回其值（若请求已有合法 token 则复用，防止多标签页/预览 iframe 互相覆盖）。"""
    token = response.headers.get("X-CSRF-Token-Issued")
    if not token and request is not None:
        existing = (request.cookies.get(CSRF_COOKIE) or "").strip()
        if len(existing) >= 16:
            token = existing
    if not token:
        token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, token, httponly=False, samesite="lax", path="/", max_age=30 * 86400,
    )
    response.headers["X-CSRF-Token-Issued"] = token
    return token


def _same_origin(request) -> bool:
    """校验 Origin / Referer 是否与本服务同源（无 Origin 视为非浏览器，跳过）。"""
    origin = request.headers.get("origin")
    host = request.headers.get("host", "")
    if origin:
        return origin.split("://")[-1] == host
    referer = request.headers.get("referer")
    if referer:
        return referer.split("://")[-1].split("/")[0] == host
    return True  # 非浏览器客户端（无 Origin/Referer）不在此约束范围


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """给所有响应附加安全头 + 为 HTML 页面下发 CSRF Cookie。"""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("Content-Security-Policy", _csp_for_request(request))
        # 页面 HTML 下发 CSRF Cookie，前端 JS 读取后放入 X-CSRF-Token 头
        ctype = response.headers.get("content-type", "")
        if "text/html" in ctype:
            ensure_csrf_cookie(response, request=request)
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double Submit Cookie CSRF 校验。"""

    async def dispatch(self, request, call_next):
        if request.method.upper() not in SAFE_METHODS and _needs_csrf(request):
            cookie_token = request.cookies.get(CSRF_COOKIE, "")
            header_token = request.headers.get(CSRF_HEADER, "") or \
                request.headers.get("x-csrf-token", "")
            ok = bool(cookie_token) and hmac.compare_digest(cookie_token, header_token)
            if ok and not _same_origin(request):
                ok = False
            if not ok:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "CSRF 校验未通过：请求缺少有效的 X-CSRF-Token 头，"
                                  "或来源跨站。该操作已拒绝执行。"
                    },
                )
        return await call_next(request)


def _needs_csrf(request) -> bool:
    """判定该请求是否需要 CSRF 校验（区分浏览器表单与 API 客户端）。"""
    if not csrf_enabled():
        return False
    path = request.url.path
    if any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES):
        return False
    # ① 显式 Bearer 凭据 = API 客户端（SDK/curl），不会被浏览器跨站自动附带
    if request.headers.get("authorization", "").strip():
        return False
    # ② 若携带跨站 Origin/Referer，即使无 Cookie（如本机 loopback 免密场景）也强制要求 CSRF 校验，防止 Drive-by Localhost CSRF
    if (request.headers.get("origin") or request.headers.get("referer")) and not _same_origin(request):
        return True
    # ③ 无会话 Cookie（含 V6 mf_v6_token/mf_token 与 V7 yimu_session）= 交给下游 guard() 判 401
    if not (
        request.cookies.get("mf_v6_token")
        or request.cookies.get("mf_token")
        or request.cookies.get("yimu_session")
    ):
        return False
    # ④ 其余（浏览器页面 Cookie 鉴权）一律要求 token
    return True
