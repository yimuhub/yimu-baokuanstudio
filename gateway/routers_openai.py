# SPDX-License-Identifier: BUSL-1.1
"""OpenAI 兼容路由：POST /v1/chat/completions、/v1/images/generations、
POST /v1/embeddings、GET /v1/models。

⭐ 关键规则（违反后果）：
- 每次成功调用必须：先原子扣会员额度 → 再调上游 → 写 ledger 两行；
  扣费失败直接 429（不调上游）；上游失败不退款但记 error 日志
  （V7.0 简化：预估与实际的差额不追补）。
- 未知模型 → 400；上游全部不可用 → 502（用户语言，hint 带 fallback 说明）。
- 计费优先用上游返回的 usage，没有则按 len(text)//4 估算。
- 用户可见 message / hint 必须使用用户语言，禁用内部黑话
  （词表见 tests/test_no_internal_jargon.py）。

上游寻址：UpstreamConfig.base_url 为 OpenAI 兼容地址前缀
（如 https://api.example.com/v1），程序自动拼接 /chat/completions 等路径；
api_key 在进程启动时从 api_key_env 读取进内存，绝不落盘。

模型路由的数据源：优先复用 B 的 core/llm.py（MODEL_PROVIDERS 等预设），
见 config.load_model_catalog；本文件只做网关侧的别名解析与能力匹配。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .circuit import CircuitBreaker
from .config import (
    GatewayError,
    UpstreamConfig,
    credits_for_tokens,
    estimate_tokens,
    new_request_id,
    ok_body,
)
from .deps import GatewayAuth, get_db, require_gateway_key
from .limits import (
    RateLimiter,
    charge_or_429,
    check_key_quota,
    check_rate_limit,
    write_ledger_rows,
)

log = logging.getLogger("yimu.gateway")

router = APIRouter(prefix="/v1", tags=["openai"])

# 模型别名：按能力自动选择可用上游
ALIAS_AUTO = "yimu-auto"


@dataclass
class UpstreamEntry:
    """上游运行期条目：配置 + 熔断器 + 内存中的密钥。"""

    cfg: UpstreamConfig
    breaker: CircuitBreaker
    api_key: str | None  # 启动时从环境变量读取；echo 上游为 None


@dataclass
class BillingPlan:
    """一次调用的计费计划（调用前根据预估生成）。"""

    est_input_tokens: int
    est_output_tokens: int
    input_rate: int
    output_rate: int
    est_credits: int


class UpstreamFailure(Exception):
    """上游调用失败（网络错误 / 非 2xx / 超时），携带是否超时标记。"""

    def __init__(self, message: str, timeout: bool = False) -> None:
        super().__init__(message)
        self.timeout = timeout


def _pool(request: Request) -> list[UpstreamEntry]:
    return request.app.state.upstream_pool


def _pricing(request: Request) -> dict[str, dict[str, int]]:
    return request.app.state.settings.pricing


def _catalog(request: Request) -> dict[str, dict[str, Any]]:
    """模型目录（来自 core/llm.py 预设或内置回退）：model_id → {capabilities, ...}。"""
    return request.app.state.model_catalog


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or new_request_id()


# ---------------------------------------------------------------------------
# 模型解析与上游选择
# ---------------------------------------------------------------------------


def _capabilities_of(request: Request, model: str) -> list[str]:
    """模型能力标签：优先取 core/llm.py 预设的 classify 结果，否则按名称推断。"""
    catalog = _catalog(request)
    if model in catalog:
        caps = catalog[model].get("capabilities") or []
        if caps:
            return list(caps)
    from .config import infer_capabilities

    return infer_capabilities(model)


def _resolve_candidates(
    request: Request, requested: str, need_capability: str
) -> tuple[str, list[UpstreamEntry]]:
    """解析模型名 → (实际模型名, 候选上游列表)。

    - yimu-auto：按能力自动选上游（取首个健康的、有对应能力模型的上游）。
    - 未知模型（无定价且无目录）→ 400。
    - 模型不支持所需能力 → 400。
    """
    pool = _pool(request)
    pricing = _pricing(request)
    catalog = _catalog(request)
    known = requested in pricing or requested in catalog
    if requested == ALIAS_AUTO:
        for entry in pool:
            if not entry.breaker.allow():
                continue
            for model in entry.cfg.models:
                if need_capability in _capabilities_of(request, model):
                    return model, [entry]
        raise GatewayError(
            "UPSTREAM_ERROR",
            "模型服务暂时不可用，请稍后重试",
            "已自动尝试其他可用通道；请稍后重试，或更换模型后再次尝试",
        )
    if not known:
        raise GatewayError(
            "BAD_REQUEST",
            f"不支持的模型：{requested}",
            "请通过 GET /v1/models 查看可用模型列表",
        )
    candidates = [e for e in pool if requested in e.cfg.models]
    if not candidates:
        # 模型已知（在目录中），但当前没有上游承载 → 502（非 400：模型本身合法）
        raise GatewayError(
            "UPSTREAM_ERROR",
            f"模型 {requested} 当前没有可用的服务通道",
            "请稍后重试，或通过 GET /v1/models 选择其他可用模型",
        )
    capable = [
        e for e in candidates if need_capability in _capabilities_of(request, requested)
    ]
    if not capable:
        raise GatewayError(
            "BAD_REQUEST",
            f"模型 {requested} 不支持本次调用类型",
            "请通过 GET /v1/models 查看各模型的能力标签后更换模型",
        )
    return requested, capable


def _pick_entry(candidates: list[UpstreamEntry]) -> UpstreamEntry:
    """选出首个熔断器放行的上游；全部熔断/下线 → 502。"""
    for entry in candidates:
        if entry.breaker.allow():
            return entry
    raise GatewayError(
        "UPSTREAM_ERROR",
        "模型服务暂时不可用，请稍后重试",
        "已自动尝试其他可用通道；请稍后重试，或更换模型后再次尝试",
    )


def _check_model_allowed(auth: GatewayAuth, model: str) -> None:
    """Key 的 allowed_models 白名单检查（为空表示不限制）。"""
    allowed = auth.key.allowed_models
    if allowed and model not in allowed and ALIAS_AUTO not in allowed:
        raise GatewayError(
            "FORBIDDEN",
            f"该 Key 未被授权调用模型 {model}",
            "请联系管理员为该 Key 开通此模型的调用权限",
        )


# ---------------------------------------------------------------------------
# 上游调用（含 echo 测试上游）
# ---------------------------------------------------------------------------


def _echo_chat(payload: dict) -> dict[str, Any]:
    """echo 上游：对 chat 返回固定格式的 choices（含 usage），仅用于测试链路。"""
    messages = payload.get("messages", [])
    last_user = ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            last_user = (
                content
                if isinstance(content, str)
                else json.dumps(content, ensure_ascii=False)
            )
            break
    text = f"测试通道已收到：{last_user[:200]}" if last_user else "测试通道已收到空消息"
    prompt_tokens = sum(
        estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages
    )
    completion_tokens = estimate_tokens(text)
    return {
        "id": f"chatcmpl-echo-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model", "yimu-chat"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _echo_images(payload: dict) -> dict[str, Any]:
    """echo 上游：图片生成返回固定 url 格式，仅用于测试链路。"""
    n = max(1, int(payload.get("n", 1)))
    prompt = str(payload.get("prompt", ""))
    return {
        "created": int(time.time()),
        "data": [
            {
                "url": f"echo://image/{uuid.uuid4().hex}",
                "revised_prompt": prompt,
            }
            for _ in range(n)
        ],
    }


def _echo_embeddings(payload: dict) -> dict[str, Any]:
    """echo 上游：embeddings 返回固定向量，仅用于测试链路。"""
    inputs = payload.get("input", "")
    items = inputs if isinstance(inputs, list) else [inputs]
    prompt_tokens = sum(estimate_tokens(str(t)) for t in items)
    vector = [round(0.1 * (i + 1), 4) for i in range(8)]
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": vector, "index": i}
            for i in range(len(items))
        ],
        "model": payload.get("model", "yimu-embed"),
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


def _call_upstream(entry: UpstreamEntry, path: str, payload: dict) -> dict[str, Any]:
    """调用上游 HTTP 接口；失败抛 UpstreamFailure（熔断器在外层记录）。"""
    cfg = entry.cfg
    if cfg.echo:
        if path == "/chat/completions":
            return _echo_chat(payload)
        if path == "/images/generations":
            return _echo_images(payload)
        if path == "/embeddings":
            return _echo_embeddings(payload)
        raise UpstreamFailure(f"echo 上游不支持路径 {path}")
    url = cfg.base_url.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    if entry.api_key:
        headers["Authorization"] = f"Bearer {entry.api_key}"
    try:
        with httpx.Client(timeout=cfg.timeout_sec) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise UpstreamFailure(f"上游请求超时（{cfg.id}）", timeout=True) from exc
    except httpx.HTTPError as exc:
        raise UpstreamFailure(f"上游连接失败（{cfg.id}）") from exc
    if resp.status_code != 200:
        raise UpstreamFailure(f"上游返回异常状态码 {resp.status_code}（{cfg.id}）")
    try:
        return resp.json()
    except ValueError as exc:
        raise UpstreamFailure(f"上游返回非 JSON（{cfg.id}）") from exc


def _stream_upstream(entry: UpstreamEntry, payload: dict):
    """流式调用上游：yield 原始 SSE 行；echo 上游按块切分文本。"""
    cfg = entry.cfg
    if cfg.echo:
        data = _echo_chat(payload)
        text = data["choices"][0]["message"]["content"]
        base = {
            "id": data["id"],
            "object": "chat.completion.chunk",
            "created": data["created"],
            "model": data["model"],
        }
        for i in range(0, len(text), 24):
            chunk = dict(base)
            chunk["choices"] = [
                {
                    "index": 0,
                    "delta": {"content": text[i : i + 24]},
                    "finish_reason": None,
                }
            ]
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        return
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if entry.api_key:
        headers["Authorization"] = f"Bearer {entry.api_key}"
    stream_payload = dict(payload)
    stream_payload["stream"] = True
    try:
        with httpx.Client(timeout=cfg.timeout_sec) as client:
            with client.stream(
                "POST", url, json=stream_payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    raise UpstreamFailure(
                        f"上游返回异常状态码 {resp.status_code}（{cfg.id}）"
                    )
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        yield line + "\n\n"
    except httpx.TimeoutException as exc:
        raise UpstreamFailure(f"上游请求超时（{cfg.id}）", timeout=True) from exc
    except httpx.HTTPError as exc:
        raise UpstreamFailure(f"上游连接失败（{cfg.id}）") from exc


# ---------------------------------------------------------------------------
# 计费流水线：预估 → 限速 → 配额 → 扣费 → 调用 → 记账
# ---------------------------------------------------------------------------


def _plan_billing(
    request: Request,
    db: Session,
    auth: GatewayAuth,
    model: str,
    est_input_tokens: int,
    est_output_tokens: int,
) -> BillingPlan:
    """⭐ 调用前流水线：白名单 → 限速 → 配额 → 原子扣费。

    顺序不可调换：扣费失败（429）时绝不调用上游，避免免费调用。
    V7.0 简化：按预估扣费，实际与预估的差额不追补。
    """
    _check_model_allowed(auth, model)
    pricing = _pricing(request)
    rates = pricing.get(model) or {"input_credits_per_1k": 2, "output_credits_per_1k": 4}
    plan = BillingPlan(
        est_input_tokens=est_input_tokens,
        est_output_tokens=est_output_tokens,
        input_rate=rates["input_credits_per_1k"],
        output_rate=rates["output_credits_per_1k"],
        est_credits=credits_for_tokens(est_input_tokens, rates["input_credits_per_1k"])
        + credits_for_tokens(est_output_tokens, rates["output_credits_per_1k"]),
    )
    rid = _request_id(request)
    limiter: RateLimiter = request.app.state.rate_limiter
    est_tokens = est_input_tokens + est_output_tokens
    check_rate_limit(limiter, auth.key, auth.tenant_id, db, est_tokens, rid)
    check_key_quota(db, auth.tenant_id, auth.key, plan.est_credits, rid)
    # ⭐ 先扣费再调上游
    charge_or_429(db, auth.tenant_id, auth.user_id, plan.est_credits)
    return plan


def _settle_call(
    request: Request,
    db: Session,
    auth: GatewayAuth,
    entry: UpstreamEntry,
    model: str,
    plan: BillingPlan,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    success: bool,
    error: str = "",
) -> None:
    """调用后结算：熔断器记录、限速窗口用实际值修正、ledger 记账。"""
    if success:
        entry.breaker.record_success()
    else:
        entry.breaker.record_failure(error)
        # ⭐ 上游失败不退款（V7.0 简化），但必须记 error 日志备查
        log.error(
            "上游调用失败 model=%s upstream=%s error=%s",
            model,
            entry.cfg.id,
            error,
        )
    limiter: RateLimiter = request.app.state.rate_limiter
    limiter.settle(
        auth.key.id,
        plan.est_input_tokens + plan.est_output_tokens,
        input_tokens + output_tokens,
    )
    if success:
        write_ledger_rows(
            db,
            auth.tenant_id,
            auth.key.id,
            model,
            input_tokens,
            output_tokens,
            plan.input_rate,
            plan.output_rate,
            latency_ms,
        )
        db.commit()


def _usage_or_estimate(resp: dict, est_in: int, est_out: int) -> tuple[int, int]:
    """优先用上游返回的 usage；没有则用预估值。"""
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if isinstance(usage, dict):
        prompt_t = usage.get("prompt_tokens")
        comp_t = usage.get("completion_tokens")
        if isinstance(prompt_t, int) and isinstance(comp_t, int):
            return prompt_t, comp_t
    return est_in, est_out


# ---------------------------------------------------------------------------
# POST /v1/chat/completions
# ---------------------------------------------------------------------------


def _estimate_chat_input(messages: list) -> int:
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
            text = (
                content
                if isinstance(content, str)
                else json.dumps(content, ensure_ascii=False)
            )
            total += estimate_tokens(text) + 4  # 每条消息附加角色/格式开销
    return max(1, total)


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    db: Session = Depends(get_db),
    auth: GatewayAuth = Depends(require_gateway_key),
):
    """OpenAI Chat Completions 兼容接口；stream=true 时返回 SSE 流。"""
    try:
        body = await request.json()
    except ValueError:
        raise GatewayError(
            "BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式"
        )
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")
    requested = str(body.get("model") or ALIAS_AUTO)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise GatewayError("BAD_REQUEST", "messages 不能为空", "请传入至少一条对话消息")
    model, candidates = _resolve_candidates(request, requested, "chat")

    max_tokens = body.get("max_tokens")
    if isinstance(max_tokens, int) and max_tokens > 0:
        est_out = max_tokens
    else:
        est_out = request.app.state.settings.default_output_estimate_tokens
    plan = _plan_billing(request, db, auth, model, _estimate_chat_input(messages), est_out)
    entry = _pick_entry(candidates)

    payload = dict(body)
    payload["model"] = model
    stream = bool(body.get("stream", False))
    started = time.monotonic()

    if not stream:
        try:
            resp = _call_upstream(entry, "/chat/completions", payload)
        except UpstreamFailure as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            _settle_call(
                request, db, auth, entry, model, plan,
                plan.est_input_tokens, 0, latency_ms, False, str(exc),
            )
            raise GatewayError(
                "TIMEOUT" if exc.timeout else "UPSTREAM_ERROR",
                "模型服务暂时不可用，请稍后重试",
                "已自动尝试其他可用通道；请稍后重试，或更换模型后再次尝试",
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        in_t, out_t = _usage_or_estimate(resp, plan.est_input_tokens, plan.est_output_tokens)
        # 补齐 OpenAI 必备字段，保证 SDK 零改迁移
        resp.setdefault("id", f"chatcmpl-{uuid.uuid4().hex[:12]}")
        resp.setdefault("object", "chat.completion")
        resp.setdefault("created", int(time.time()))
        resp["model"] = model
        resp["usage"] = {
            "prompt_tokens": in_t,
            "completion_tokens": out_t,
            "total_tokens": in_t + out_t,
        }
        _settle_call(request, db, auth, entry, model, plan, in_t, out_t, latency_ms, True)
        return resp

    # ---- 流式：SSE ----
    def event_stream():
        factory = request.app.state.session_factory
        sdb: Session = factory()
        chunks_text: list[str] = []
        usage_in = plan.est_input_tokens
        usage_out = 0
        failed: str | None = None
        try:
            for raw_line in _stream_upstream(entry, payload):
                yield raw_line
                if raw_line.startswith("data:") and "[DONE]" not in raw_line:
                    try:
                        chunk = json.loads(raw_line[len("data:") :].strip())
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if isinstance(content, str):
                            chunks_text.append(content)
                        usage = chunk.get("usage")
                        if isinstance(usage, dict):
                            if isinstance(usage.get("prompt_tokens"), int):
                                usage_in = usage["prompt_tokens"]
                            if isinstance(usage.get("completion_tokens"), int):
                                usage_out = usage["completion_tokens"]
                    except (ValueError, KeyError, IndexError, TypeError):
                        pass
            yield "data: [DONE]\n\n"
        except UpstreamFailure as exc:
            failed = str(exc)
            yield (
                "data: "
                + json.dumps({"error": "模型服务暂时不可用，请稍后重试"}, ensure_ascii=False)
                + "\n\n"
            )
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            try:
                if failed is None:
                    out_t = usage_out or estimate_tokens("".join(chunks_text))
                    _settle_call(
                        request, sdb, auth, entry, model, plan,
                        usage_in, out_t, latency_ms, True,
                    )
                else:
                    _settle_call(
                        request, sdb, auth, entry, model, plan,
                        usage_in, 0, latency_ms, False, failed,
                    )
            finally:
                sdb.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# POST /v1/images/generations
# ---------------------------------------------------------------------------


@router.post("/images/generations")
async def images_generations(
    request: Request,
    db: Session = Depends(get_db),
    auth: GatewayAuth = Depends(require_gateway_key),
):
    """OpenAI Images Generations 兼容接口；n>4 → 400。"""
    try:
        body = await request.json()
    except ValueError:
        raise GatewayError(
            "BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式"
        )
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise GatewayError("BAD_REQUEST", "prompt 不能为空", "请传入图片描述文本")
    n = body.get("n", 1)
    if not isinstance(n, int) or n < 1:
        raise GatewayError("BAD_REQUEST", "n 必须为正整数", "请传入 1~4 之间的整数")
    if n > 4:
        raise GatewayError("BAD_REQUEST", "单次最多生成 4 张图片", "如需更多请分多次调用")
    requested = str(body.get("model") or "yimu-image")
    model, candidates = _resolve_candidates(request, requested, "images")

    settings = request.app.state.settings
    est_out = n * settings.image_output_tokens_per_image
    plan = _plan_billing(request, db, auth, model, estimate_tokens(prompt), est_out)
    entry = _pick_entry(candidates)

    payload = {"model": model, "prompt": prompt, "n": n}
    for k in ("size", "style", "quality", "response_format"):
        if body.get(k) is not None:
            payload[k] = body[k]
    started = time.monotonic()
    try:
        resp = _call_upstream(entry, "/images/generations", payload)
    except UpstreamFailure as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        _settle_call(
            request, db, auth, entry, model, plan,
            plan.est_input_tokens, 0, latency_ms, False, str(exc),
        )
        raise GatewayError(
            "TIMEOUT" if exc.timeout else "UPSTREAM_ERROR",
            "图片服务暂时不可用，请稍后重试",
            "已自动尝试其他可用通道；请稍后重试，或更换模型后再次尝试",
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    in_t, out_t = _usage_or_estimate(resp, plan.est_input_tokens, est_out)
    resp.setdefault("created", int(time.time()))
    if not isinstance(resp.get("data"), list):
        resp["data"] = []
    _settle_call(request, db, auth, entry, model, plan, in_t, out_t, latency_ms, True)
    return resp


# ---------------------------------------------------------------------------
# POST /v1/embeddings
# ---------------------------------------------------------------------------


@router.post("/embeddings")
async def embeddings(
    request: Request,
    db: Session = Depends(get_db),
    auth: GatewayAuth = Depends(require_gateway_key),
):
    """OpenAI Embeddings 兼容接口。"""
    try:
        body = await request.json()
    except ValueError:
        raise GatewayError(
            "BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式"
        )
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")
    inputs = body.get("input")
    if (
        inputs is None
        or (isinstance(inputs, str) and not inputs.strip())
        or (isinstance(inputs, list) and not inputs)
    ):
        raise GatewayError("BAD_REQUEST", "input 不能为空", "请传入要计算向量的文本")
    requested = str(body.get("model") or "yimu-embed")
    model, candidates = _resolve_candidates(request, requested, "embeddings")

    items = inputs if isinstance(inputs, list) else [inputs]
    est_in = sum(estimate_tokens(str(t)) for t in items)
    plan = _plan_billing(request, db, auth, model, est_in, 0)
    entry = _pick_entry(candidates)

    payload = {"model": model, "input": inputs}
    started = time.monotonic()
    try:
        resp = _call_upstream(entry, "/embeddings", payload)
    except UpstreamFailure as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        _settle_call(
            request, db, auth, entry, model, plan,
            plan.est_input_tokens, 0, latency_ms, False, str(exc),
        )
        raise GatewayError(
            "TIMEOUT" if exc.timeout else "UPSTREAM_ERROR",
            "向量服务暂时不可用，请稍后重试",
            "已自动尝试其他可用通道；请稍后重试，或更换模型后再次尝试",
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    in_t, _ = _usage_or_estimate(resp, plan.est_input_tokens, 0)
    resp.setdefault("object", "list")
    resp["model"] = model
    resp["usage"] = {"prompt_tokens": in_t, "total_tokens": in_t}
    _settle_call(request, db, auth, entry, model, plan, in_t, 0, latency_ms, True)
    return resp


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------


@router.get("/models")
async def list_models(
    request: Request,
    auth: GatewayAuth = Depends(require_gateway_key),
):
    """可用模型列表（含别名、能力标签、单价）。"""
    pricing = _pricing(request)
    catalog = _catalog(request)
    model_ids = sorted(set(pricing.keys()) | set(catalog.keys()))
    items = []
    for model_id in model_ids:
        rates = pricing.get(model_id) or {"input_credits_per_1k": 2, "output_credits_per_1k": 4}
        caps = _capabilities_of(request, model_id)
        items.append(
            {
                "id": model_id,
                "object": "model",
                "capabilities": caps,
                "pricing": {
                    "input_credits_per_1k": rates["input_credits_per_1k"],
                    "output_credits_per_1k": rates["output_credits_per_1k"],
                },
            }
        )
    return ok_body({"data": items})
