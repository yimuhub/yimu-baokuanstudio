# SPDX-License-Identifier: BUSL-1.1
"""YIMU Gateway 应用入口：FastAPI app 工厂 create_app() 与 uvicorn 启动。

⭐ 关键规则：
- 密钥只走环境变量；上游 api_key 在 create_app 时读入内存，绝不落盘、
  绝不进日志、绝不返回给前端（管理接口的上游列表已脱敏）。
- 全局异常全部转为统一错误体（含 request_id）；未预期异常 message 脱敏。
"""
from __future__ import annotations

import logging
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from studio.db import get_engine, get_session_factory, init_db

from .circuit import CircuitBreaker
from .config import (
    CODE_HTTP,
    GatewayError,
    err_body,
    gateway_error_handler,
    load_model_catalog,
    load_settings,
    new_request_id,
    ok_body,
)
from .limits import RateLimiter
from .routers_admin import router as admin_router
from .routers_openai import UpstreamEntry, router as openai_router

log = logging.getLogger("yimu.gateway")

# Starlette HTTP 状态码 → 网关错误码
_HTTP_TO_CODE = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "BAD_REQUEST",  # 方法不允许：归入 BAD_REQUEST，保持 10 码契约，不错标 500
    409: "CONFLICT",
    429: "QUOTA_EXCEEDED",
    502: "UPSTREAM_ERROR",
    504: "TIMEOUT",
}


def _build_upstream_pool(app: FastAPI) -> list[UpstreamEntry]:
    """组装上游运行期池：每个上游独立熔断器；密钥读入内存。"""
    settings = app.state.settings
    pool: list[UpstreamEntry] = []
    for cfg in settings.upstreams:
        # ⭐ 密钥只从环境变量读取，进内存，不落盘
        api_key = os.environ.get(cfg.api_key_env) if cfg.api_key_env else None
        pool.append(
            UpstreamEntry(
                cfg=cfg,
                breaker=CircuitBreaker(
                    cfg.id,
                    fail_threshold=settings.circuit_fail_threshold,
                    open_seconds=settings.circuit_open_seconds,
                ),
                api_key=api_key,
            )
        )
    return pool


def _ensure_sqlite_dir(db_url: str) -> None:
    """SQLite 文件型 URL：自动创建父目录，避免相对路径 data/ 不存在时启动失败。"""
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
        # 兼容 :memory: 与 URI 参数形式
        if path and not path.startswith(":memory:"):
            clean = path.split("?")[0]
            parent = os.path.dirname(os.path.abspath(clean))
            os.makedirs(parent, exist_ok=True)


def create_app() -> FastAPI:
    """构建 YIMU Gateway FastAPI 应用。"""
    settings = load_settings()
    _ensure_sqlite_dir(settings.db_url)
    engine = get_engine(settings.db_url)
    init_db(engine)

    app = FastAPI(title="YIMU Gateway", version="7.0.0-dev")
    app.state.settings = settings
    app.state.session_factory = get_session_factory(engine)
    app.state.rate_limiter = RateLimiter()
    # 模型目录：复用 B 的 core/llm.py 预设（失败时内置回退），见 config.load_model_catalog
    app.state.model_catalog = load_model_catalog()
    app.state.upstream_pool = _build_upstream_pool(app)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or new_request_id()
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(GatewayError)
    async def handle_gateway_error(request: Request, exc: GatewayError):
        return await gateway_error_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", None) or new_request_id()
        errors = exc.errors()
        hint = ""
        if errors:
            loc = ".".join(str(p) for p in errors[0].get("loc", []))
            hint = f"请检查参数 {loc}：{errors[0].get('msg', '')}" if loc else ""
        return JSONResponse(
            status_code=400,
            content=err_body("BAD_REQUEST", "请求参数有误", hint, rid),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        rid = getattr(request.state, "request_id", None) or new_request_id()
        code = _HTTP_TO_CODE.get(exc.status_code, "INTERNAL")
        message = str(exc.detail) if exc.detail else "请求处理失败"
        return JSONResponse(
            status_code=CODE_HTTP.get(code, 500),
            content=err_body(code, message, "", rid),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        # ⭐ 未预期异常：记日志，message 脱敏，不泄露内部细节
        rid = getattr(request.state, "request_id", None) or new_request_id()
        log.exception("未预期异常 request_id=%s", rid)
        return JSONResponse(
            status_code=500,
            content=err_body(
                "INTERNAL", "服务内部出现问题，请稍后重试", "如持续失败请联系管理员", rid
            ),
        )

    app.include_router(openai_router)
    app.include_router(admin_router)

    @app.get("/api/health", tags=["ops"])
    async def health():
        """存活探针：进程活着即 ok。"""
        return ok_body(
            {
                "status": "ok",
                "service": "yimu-gateway",
                "upstreams": len(app.state.upstream_pool),
            }
        )

    return app


# uvicorn 入口：uvicorn gateway.main:app --host 127.0.0.1 --port 8791
app = create_app()

if __name__ == "__main__":
    uvicorn.run("gateway.main:app", host="127.0.0.1", port=8791)
