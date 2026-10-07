# SPDX-License-Identifier: BUSL-1.1
"""统一错误体与成功体构造器（V7 全仓通用，WS-C 先行落地精简版）。

⭐ 硬规则：
- 所有对外 API 的成功/失败响应都走这里组装，错误体固定为
  {"ok","code","message","hint","request_id"}，见 docs/CONTRACT.md §2.2。
- message 必须是给人看的中文一句话，禁止内部黑话
  （见 tests/test_no_internal_jargon.py 词表）。
- request_id 每次自动生成，便于链路排查。
"""

from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import HTTPException


class Code:
    """错误码常量（与 docs/CONTRACT.md §2.2 对齐）。"""

    OK = "OK"
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    TIMEOUT = "TIMEOUT"
    INTERNAL = "INTERNAL"


def new_request_id() -> str:
    """生成链路请求 id（32 位十六进制）。"""
    return uuid.uuid4().hex


def ok(data: dict | None = None, request_id: str | None = None) -> dict:
    """组装成功响应体。"""
    return {
        "ok": True,
        "code": Code.OK,
        "data": data or {},
        "request_id": request_id or new_request_id(),
    }


def err(
    code: str,
    message: str,
    hint: str = "",
    request_id: str | None = None,
) -> dict:
    """组装统一错误体。"""
    return {
        "ok": False,
        "code": code,
        "message": message,
        "hint": hint,
        "request_id": request_id or new_request_id(),
    }


class YimuError(Exception):
    """业务异常基类：携带 code/message/hint，路由层统一转错误体。"""

    def __init__(
        self,
        code: str = Code.INTERNAL,
        message: str = "系统开小差了，请稍后再试",
        hint: str = "",
        status: int = 500,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.status = status

    def body(self, request_id: str | None = None) -> dict:
        """转为统一错误体。"""
        return err(self.code, self.message, self.hint, request_id)


class UpstreamNotReady(YimuError):
    """⭐ 上游图片服务未就绪：必须显式报错，禁止静默返回假成功。"""

    def __init__(
        self,
        message: str = "图片服务暂时不可用，请稍后再试",
        hint: str = "可联系管理员检查图片服务配置",
    ) -> None:
        super().__init__(Code.UPSTREAM_ERROR, message, hint, status=502)


class BadRequest(YimuError):
    """参数错误（400）。"""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(Code.BAD_REQUEST, message, hint, status=400)


# 错误码 → HTTP 状态码（供 raise_err；与 docs/CONTRACT.md §2.2 对齐）
_CODE_HTTP = {
    Code.OK: 200,
    Code.BAD_REQUEST: 400,
    Code.UNAUTHORIZED: 401,
    Code.FORBIDDEN: 403,
    Code.NOT_FOUND: 404,
    Code.CONFLICT: 409,
    Code.QUOTA_EXCEEDED: 429,
    Code.UPSTREAM_ERROR: 502,
    Code.TIMEOUT: 504,
    Code.INTERNAL: 500,
}


def raise_err(
    code: str,
    message: str,
    hint: str = "",
    request_id: str | None = None,
) -> NoReturn:
    """抛统一错误体的 HTTPException（供依赖 / 服务层 raise）。

    调用方可加 app 级异常处理器，把 ``exc.detail``（即错误体 dict）
    原样作为响应体返回，鉴权依赖抛出的错误与路由错误体格式完全一致。
    """
    raise HTTPException(
        status_code=_CODE_HTTP.get(code, 500),
        detail=err(code, message, hint, request_id),
    )
