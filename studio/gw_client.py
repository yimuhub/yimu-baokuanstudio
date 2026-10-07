# SPDX-License-Identifier: BUSL-1.1
"""YIMU Gateway dogfooding SDK：工作室自身的所有模型调用都经网关发出。

用法::

    from studio.gw_client import YIMUClient

    client = YIMUClient()  # base_url / api_key 读环境变量
    result = client.chat("deepseek-chat", [{"role": "user", "content": "你好"}])

配置（环境变量，优先级低于构造参数）：
- ``YIMU_GATEWAY_URL``：网关地址，默认 ``http://127.0.0.1:8791``。
- ``YIMU_GATEWAY_KEY``：网关 API Key。

错误体遵循 docs/CONTRACT.md §2.2 统一错误体：
``{"ok": false, "code": ..., "message": ..., "hint": ..., "request_id": ...}``，
按 code / HTTP 状态映射为对应的异常类型。

⭐ 关键规则：
1. api_key 永不出现在日志、异常信息、请求 URL 中；
   排查时只显示前缀（如 ``yimu_sk_ab12***``）。
2. 异常 message 面向用户：中文一句话，禁止内部黑话；
   429（额度/限速超限）异常额外携带 ``retry_after`` 与 ``credits_left``，
   供上游做重试等待与剩余额度展示。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterator

import httpx

__all__ = [
    "YIMUGatewayError",
    "BadRequest",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "QuotaExceeded",
    "UpstreamError",
    "InternalError",
    "YIMUClient",
]

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8791"
DEFAULT_TIMEOUT_SEC = 60.0


class YIMUGatewayError(Exception):
    """网关 SDK 异常基类。

    属性：
    - ``code``：网关错误体中的 code（如 ``QUOTA_EXCEEDED``）。
    - ``http_status``：HTTP 状态码。
    - ``hint``：网关给出的可操作下一步（可能为空）。
    - ``request_id``：网关请求 id，便于对账排查。
    message 永远是给人看的中文一句话，不含任何密钥。
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "INTERNAL",
        http_status: int = 500,
        hint: str = "",
        request_id: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.hint = hint
        self.request_id = request_id


class BadRequest(YIMUGatewayError):
    """400：请求参数不正确。"""


class Unauthorized(YIMUGatewayError):
    """401：未登录 / Key 无效。"""


class Forbidden(YIMUGatewayError):
    """403：无权限 / 租户隔离拦截。"""


class NotFound(YIMUGatewayError):
    """404：请求的资源不存在。"""


class QuotaExceeded(YIMUGatewayError):
    """429：额度或调用频率超限。

    额外属性：``retry_after``（建议等待秒数，可能为 None）、
    ``credits_left``（剩余额度，可能为 None）。
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        self.retry_after: Any = kwargs.pop("retry_after", None)
        self.credits_left: Any = kwargs.pop("credits_left", None)
        super().__init__(message, **kwargs)


class UpstreamError(YIMUGatewayError):
    """502：模型服务暂时不可用。"""


class InternalError(YIMUGatewayError):
    """500 及其他未预期错误。"""


# HTTP 状态 → 异常类型（网关契约 §2.2 / §3）
_STATUS_TO_ERROR: dict[int, type[YIMUGatewayError]] = {
    400: BadRequest,
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    429: QuotaExceeded,
    502: UpstreamError,
}

# 网关错误体 code → 异常类型（状态码缺失 / 代理改写状态码时的回退依据）
_CODE_TO_ERROR: dict[str, type[YIMUGatewayError]] = {
    "BAD_REQUEST": BadRequest,
    "UNAUTHORIZED": Unauthorized,
    "FORBIDDEN": Forbidden,
    "NOT_FOUND": NotFound,
    "QUOTA_EXCEEDED": QuotaExceeded,
    "UPSTREAM_ERROR": UpstreamError,
    "TIMEOUT": UpstreamError,
    "INTERNAL": InternalError,
}


def _mask_key(api_key: str | None) -> str:
    """⭐ 脱敏：只显示 key 前缀，其余打码；未设置时返回提示文本。"""
    if not api_key:
        return "<未设置>"
    prefix = api_key[:10]
    return f"{prefix}***"


class YIMUClient:
    """YIMU Gateway 同步客户端。

    ``base_url`` 缺省时读 ``YIMU_GATEWAY_URL`` 环境变量，再缺省用本地默认地址；
    ``api_key`` 缺省时读 ``YIMU_GATEWAY_KEY`` 环境变量。
    ``timeout`` 为单次请求超时秒数（默认 60），流式请求同样适用。
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        resolved_url = base_url or os.environ.get(
            "YIMU_GATEWAY_URL", DEFAULT_BASE_URL
        )
        self.base_url = resolved_url.rstrip("/")
        resolved_key = api_key or os.environ.get("YIMU_GATEWAY_KEY")
        self._api_key = resolved_key
        self.timeout = timeout
        log.debug("YIMUClient 初始化：网关地址=%s，Key=%s", self.base_url, _mask_key(resolved_key))

    # -- 内部工具 ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _parse_error_body(self, response: httpx.Response) -> dict[str, Any]:
        """尽量解析网关错误体；解析失败返回空 dict（不抛错）。"""
        try:
            body = response.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}

    def _raise_for_status(self, response: httpx.Response) -> None:
        """按网关错误体 code / HTTP 状态抛对应异常；2xx 直接返回。"""
        if response.status_code < 400:
            return
        body = self._parse_error_body(response)
        code = str(body.get("code") or "")
        message = str(body.get("message") or "").strip()
        hint = str(body.get("hint") or "")
        request_id = str(body.get("request_id") or "")
        exc_cls = _STATUS_TO_ERROR.get(response.status_code) or _CODE_TO_ERROR.get(
            code, InternalError
        )
        if not message:
            message = self._default_message(response.status_code)
        kwargs: dict[str, Any] = {
            "code": code or "INTERNAL",
            "http_status": response.status_code,
            "hint": hint,
            "request_id": request_id,
        }
        if exc_cls is QuotaExceeded:
            kwargs["retry_after"] = body.get("retry_after")
            kwargs["credits_left"] = body.get("credits_left")
        # ⭐ 异常信息里只带网关返回的 message / hint，绝不带 api_key
        raise exc_cls(message, **kwargs)

    @staticmethod
    def _default_message(status: int) -> str:
        """网关没给 message 时的用户语言兜底文案。"""
        return {
            400: "请求参数不正确，请检查后重试。",
            401: "登录已失效或密钥无效，请重新登录。",
            403: "没有权限执行该操作。",
            404: "请求的资源不存在。",
            429: "调用太频繁或额度已用完，请稍后再试。",
            502: "模型服务暂时不可用，请稍后重试。",
        }.get(status, "系统开小差了，请稍后重试。")

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """非流式 POST：返回解析后的 JSON dict。"""
        url = f"{self.base_url}{path}"
        try:
            response = httpx.post(
                url, headers=self._headers(), json=payload, timeout=self.timeout
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                "请求超时，请稍后重试。",
                code="TIMEOUT",
                http_status=504,
            ) from exc
        except httpx.RequestError as exc:
            raise UpstreamError(
                "无法连接到网关服务，请确认服务已启动。",
                code="UPSTREAM_ERROR",
                http_status=502,
            ) from exc
        self._raise_for_status(response)
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}

    def _iter_sse(self, path: str, payload: dict[str, Any]) -> Iterator[dict]:
        """流式 POST：解析 SSE ``data:`` 行，遇到 ``[DONE]`` 结束。"""
        url = f"{self.base_url}{path}"
        try:
            with httpx.stream(
                "POST",
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            ) as response:
                self._raise_for_status(response)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    if not data:
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        log.warning("跳过无法解析的 SSE 数据行")
                        continue
                    yield chunk if isinstance(chunk, dict) else {"data": chunk}
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                "请求超时，请稍后重试。",
                code="TIMEOUT",
                http_status=504,
            ) from exc
        except httpx.RequestError as exc:
            # _raise_for_status 已抛出的网关异常直接透出，不重复包装
            if isinstance(exc, YIMUGatewayError):
                raise
            raise UpstreamError(
                "无法连接到网关服务，请确认服务已启动。",
                code="UPSTREAM_ERROR",
                http_status=502,
            ) from exc

    # -- 公开 API ------------------------------------------------------------

    def chat(
        self, model: str, messages: list[dict], stream: bool = False, **kwargs: Any
    ) -> dict | Iterator[dict]:
        """对话补全。

        ``stream=False`` 返回完整响应 dict（OpenAI Chat Completions 格式）；
        ``stream=True`` 返回按 SSE 切分的数据块迭代器，``[DONE]`` 后自动结束。
        其余参数（如 ``temperature`` / ``max_tokens``）经 ``**kwargs`` 透传。
        """
        payload: dict[str, Any] = {"model": model, "messages": messages}
        payload.update(kwargs)
        if stream:
            payload["stream"] = True
            return self._iter_sse("/v1/chat/completions", payload)
        return self._post("/v1/chat/completions", payload)

    def images(
        self,
        model: str,
        prompt: str,
        n: int = 1,
        size: str = "1024x1024",
        style: str = "",
    ) -> dict:
        """文生图：返回 ``{created, data: [{url, revised_prompt}]}``（OpenAI 格式）。"""
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "size": size,
        }
        if style:
            payload["style"] = style
        return self._post("/v1/images/generations", payload)

    def embeddings(self, model: str, input: str | list[str]) -> dict:
        """文本向量：返回 OpenAI 格式的 embeddings 响应。"""
        return self._post("/v1/embeddings", {"model": model, "input": input})

    def models(self) -> dict:
        """网关可用模型列表（含别名、能力标签、单价）。"""
        url = f"{self.base_url}/v1/models"
        try:
            response = httpx.get(
                url, headers=self._headers(), timeout=self.timeout
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                "请求超时，请稍后重试。",
                code="TIMEOUT",
                http_status=504,
            ) from exc
        except httpx.RequestError as exc:
            raise UpstreamError(
                "无法连接到网关服务，请确认服务已启动。",
                code="UPSTREAM_ERROR",
                http_status=502,
            ) from exc
        self._raise_for_status(response)
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}

    def masked_key(self) -> str:
        """返回脱敏后的 Key 前缀（日志 / 排查用，绝不返回完整 Key）。"""
        return _mask_key(self._api_key)
