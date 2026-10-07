# SPDX-License-Identifier: BUSL-1.1
"""YIMU Gateway 配置层：上游、定价、统一错误体，全部来自环境变量。

⭐ 关键规则（违反后果）：
- 密钥只走环境变量读取，绝不硬编码、绝不落盘、绝不打印到日志；
  否则密钥泄露会导致他人盗用上游额度，直接产生资损。
- key_hash 永不返回前端（见 deps.key_public_dict）；明文 Key 只在发放接口返回一次。
- 用户可见文案（message / hint）使用用户语言，禁用内部黑话（见 tests/test_no_internal_jargon.py 词表）。

环境变量：
- YIMU_DB_URL：数据库 URL，默认 ``sqlite:///./data/yimu.db``
- YIMU_UPSTREAMS：JSON 数组，每项 ``{id, base_url, api_key_env, models:[...], timeout_sec}``
  （api_key 从 ``api_key_env`` 命名的环境变量读取）
- YIMU_PRICING：JSON，覆盖默认定价 ``{model: {input_credits_per_1k, output_credits_per_1k}}``
- YIMU_ADMIN_KEY：网关管理接口的备用管理员密钥（无 studio session 时使用）
- YIMU_UPSTREAM_ECHO=1：启用本地 echo 上游，仅用于测试链路，不对外宣传
- YIMU_GW_IMAGE_OUTPUT_TOKENS：单张图片折算的输出 tokens（默认 1024）
"""
from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# 统一错误体：code → HTTP 状态码（与 docs/CONTRACT.md §2.2 一致）
# ---------------------------------------------------------------------------

CODE_HTTP: dict[str, int] = {
    "OK": 200,
    "BAD_REQUEST": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "QUOTA_EXCEEDED": 429,
    "UPSTREAM_ERROR": 502,
    "TIMEOUT": 504,
    "INTERNAL": 500,
}


class GatewayError(Exception):
    """网关业务异常：由全局异常处理器转为统一错误体。

    Attributes:
        code: 错误码（见 CODE_HTTP）。
        message: 给用户看的中文一句话（用户语言，无内部黑话）。
        hint: 可操作的下一步。
        extra: 附加字段（如 429 的 retry_after / credits_left）。
    """

    def __init__(
        self,
        code: str,
        message: str,
        hint: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.extra = extra or {}


def new_request_id() -> str:
    """生成请求追踪 id（32 位十六进制）。"""
    return uuid.uuid4().hex


def err_body(
    code: str,
    message: str,
    hint: str = "",
    request_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """构造统一错误体（含成功体 {"ok": true} 的反面）。"""
    body: dict[str, Any] = {
        "ok": False,
        "code": code,
        "message": message,
        "hint": hint or "",
        "request_id": request_id or new_request_id(),
    }
    body.update(extra)
    return body


def ok_body(data: Any) -> dict[str, Any]:
    """构造统一成功体。"""
    return {"ok": True, "data": data}


async def gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
    """GatewayError → 统一错误体（带 request_id）。"""
    rid = getattr(request.state, "request_id", None) or new_request_id()
    return JSONResponse(
        status_code=CODE_HTTP.get(exc.code, 500),
        content=err_body(exc.code, exc.message, exc.hint, rid, **exc.extra),
    )


# ---------------------------------------------------------------------------
# 定价：每 1k tokens 的 credits 点数（整数）
# ---------------------------------------------------------------------------

DEFAULT_PRICING: dict[str, dict[str, int]] = {
    # 网关别名与内置测试模型
    "yimu-auto": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-chat": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-embed": {"input_credits_per_1k": 1, "output_credits_per_1k": 0},
    "yimu-image": {"input_credits_per_1k": 2, "output_credits_per_1k": 50},
    # 常见上游模型（可通过 YIMU_PRICING 覆盖）
    "gpt-4o": {"input_credits_per_1k": 5, "output_credits_per_1k": 15},
    "gpt-4o-mini": {"input_credits_per_1k": 1, "output_credits_per_1k": 2},
    "deepseek-chat": {"input_credits_per_1k": 2, "output_credits_per_1k": 3},
    "deepseek-reasoner": {"input_credits_per_1k": 4, "output_credits_per_1k": 8},
    "qwen-max": {"input_credits_per_1k": 4, "output_credits_per_1k": 12},
    "glm-4": {"input_credits_per_1k": 5, "output_credits_per_1k": 5},
    "doubao-pro-32k": {"input_credits_per_1k": 2, "output_credits_per_1k": 6},
    "claude-3-5-sonnet": {"input_credits_per_1k": 6, "output_credits_per_1k": 30},
}


def load_pricing() -> dict[str, dict[str, int]]:
    """合并默认定价与 YIMU_PRICING 环境变量覆盖。"""
    pricing = {k: dict(v) for k, v in DEFAULT_PRICING.items()}
    raw = os.environ.get("YIMU_PRICING", "").strip()
    if raw:
        try:
            override = json.loads(raw)
            for model, rates in override.items():
                pricing[model] = {
                    "input_credits_per_1k": int(rates.get("input_credits_per_1k", 0)),
                    "output_credits_per_1k": int(rates.get("output_credits_per_1k", 0)),
                }
        except (ValueError, AttributeError, TypeError):
            pass  # 环境变量格式错误时沿用默认定价，不阻断启动
    return pricing


def estimate_tokens(text: str) -> int:
    """tokens 粗估：无上游 usage 时使用（中文约 1 token ≈ 2 字，英文约 4 字符）。"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def credits_for_tokens(tokens: int, per_1k: int) -> int:
    """⭐ 计费换算：credits = ceil(tokens/1000 × 单价)，至少 1 点（0 tokens 则为 0）。

    ledger.cost_cents 与 credits 1:1 对应（整数，杜绝浮点误差）。
    """
    if tokens <= 0 or per_1k <= 0:
        return 0
    return max(1, math.ceil(tokens / 1000 * per_1k))


# ---------------------------------------------------------------------------
# 上游配置
# ---------------------------------------------------------------------------


def infer_capabilities(model_name: str) -> list[str]:
    """按模型名推断能力标签：chat / vision / images / embeddings。"""
    name = model_name.lower()
    if "embed" in name:
        return ["embeddings"]
    if "image" in name or "dall" in name or "draw" in name or "生图" in name:
        return ["images"]
    caps = ["chat"]
    if "vision" in name or "vl" in name or "4o" in name:
        caps.append("vision")
    return caps


@dataclass
class UpstreamConfig:
    """单个上游配置。api_key 在运行时从 api_key_env 读取，绝不落盘。"""

    id: str
    base_url: str
    api_key_env: str
    models: list[str] = field(default_factory=list)
    timeout_sec: float = 30.0
    capabilities: dict[str, list[str]] = field(default_factory=dict)
    echo: bool = False  # 本地 echo 上游（测试链路专用）

    def capability_of(self, model: str) -> list[str]:
        if model in self.capabilities:
            return self.capabilities[model]
        return infer_capabilities(model)


def _echo_upstream() -> UpstreamConfig:
    """本地 echo 上游：返回固定格式的应答，仅用于测试链路。"""
    return UpstreamConfig(
        id="echo",
        base_url="echo://local",
        api_key_env="",
        models=["yimu-auto", "yimu-chat", "yimu-embed", "yimu-image"],
        timeout_sec=5.0,
        capabilities={
            "yimu-auto": ["chat"],
            "yimu-chat": ["chat", "vision"],
            "yimu-embed": ["embeddings"],
            "yimu-image": ["images"],
        },
        echo=True,
    )


def load_upstreams() -> list[UpstreamConfig]:
    """从 YIMU_UPSTREAMS 解析上游列表；YIMU_UPSTREAM_ECHO=1 时追加 echo 上游。"""
    upstreams: list[UpstreamConfig] = []
    raw = os.environ.get("YIMU_UPSTREAMS", "").strip()
    if raw:
        try:
            items = json.loads(raw)
            for item in items:
                upstreams.append(
                    UpstreamConfig(
                        id=str(item.get("id", "")),
                        base_url=str(item.get("base_url", "")),
                        api_key_env=str(item.get("api_key_env", "")),
                        models=[str(m) for m in item.get("models", [])],
                        timeout_sec=float(item.get("timeout_sec", 30)),
                        capabilities={
                            str(k): [str(c) for c in v]
                            for k, v in (item.get("capabilities") or {}).items()
                        },
                    )
                )
        except (ValueError, AttributeError, TypeError):
            pass  # 格式错误时忽略该配置，不阻断启动（调用时将返回 502）
    upstreams = [u for u in upstreams if u.id and u.base_url and u.models]
    if os.environ.get("YIMU_UPSTREAM_ECHO", "") == "1":
        upstreams.append(_echo_upstream())
    return upstreams


# ---------------------------------------------------------------------------
# 模型目录：复用 B 的 core/llm.py 预设（V7 战略调整：移植 B 基线，不自建模型清单表）
#
# 集成方式（过渡期）：用 importlib 从绝对路径加载 core/llm.py；
#   集成完成后改为：from core.llm import MODEL_PROVIDERS, classify_model, get_configured_models
# 防御性：try/except 包住一切，失败时回退到内置最小表，不阻断网关启动。
# 注意：只复用「模型清单与分类」，不复制 B 的密钥读取逻辑；
#   上游 API Key 仍只从网关自己的环境变量（YIMU_UPSTREAMS.api_key_env）读取。
# ---------------------------------------------------------------------------

# core/llm.py 位置（过渡期绝对路径；可用 YIMU_CORE_LLM_PATH 覆盖）
_DEFAULT_CORE_LLM_PATH = "/home/hatch/workspace/yimu-v7-port/core/llm.py"

# B 的 classify_model 返回值 → 网关能力标签
_CATEGORY_CAPABILITIES: dict[str, list[str]] = {
    "text": ["chat"],
    "image": ["images"],
    "video": ["video"],
}

# 内置最小回退表：core/llm.py 不可用时使用（网关别名 + echo 模型）
_FALLBACK_CATALOG: dict[str, dict[str, Any]] = {
    "yimu-chat": {"capabilities": ["chat", "vision"], "provider_id": "yimu"},
    "yimu-embed": {"capabilities": ["embeddings"], "provider_id": "yimu"},
    "yimu-image": {"capabilities": ["images"], "provider_id": "yimu"},
    "deepseek-chat": {"capabilities": ["chat"], "provider_id": "deepseek"},
    "gpt-4o": {"capabilities": ["chat", "vision"], "provider_id": "openai"},
    "gpt-4o-mini": {"capabilities": ["chat"], "provider_id": "openai"},
}


def _load_core_llm_module():
    """防御性加载 B 的 core/llm.py 模块；失败返回 None。"""
    import importlib.util

    path = os.environ.get("YIMU_CORE_LLM_PATH", _DEFAULT_CORE_LLM_PATH)
    try:
        if not path or not os.path.isfile(path):
            return None
        spec = importlib.util.spec_from_file_location("yimu_core_llm", path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None  # 缺依赖 / 文件结构变化时静默回退


def load_model_catalog() -> dict[str, dict[str, Any]]:
    """构建模型目录：model_id → {"capabilities": [...], "provider_id": ...}。

    数据源：
    1. B 的 core/llm.py：MODEL_PROVIDERS（13 预设）+ classify_model 分类
       + get_configured_models()（用户已配置的模型清单）；
    2. 失败时回退到内置最小表。
    网关用它做：yimu-auto 别名选择、未知模型 400 判定、GET /v1/models 能力标签。
    """
    catalog: dict[str, dict[str, Any]] = {}
    mod = _load_core_llm_module()
    if mod is not None:
        try:
            providers = getattr(mod, "MODEL_PROVIDERS", None) or {}
            classify = getattr(mod, "classify_model", None)
            for pid, pinfo in providers.items():
                if not isinstance(pinfo, dict):
                    continue
                for model in pinfo.get("models", []) or []:
                    category = classify(model) if callable(classify) else "text"
                    caps = list(_CATEGORY_CAPABILITIES.get(category, ["chat"]))
                    # classify_model 只分 text/image/video；embedding 与 vision 按名补充
                    for extra in infer_capabilities(str(model)):
                        if extra not in caps:
                            caps.append(extra)
                    catalog[str(model)] = {
                        "capabilities": caps,
                        "provider_id": str(pid),
                    }
            get_models = getattr(mod, "get_configured_models", None)
            if callable(get_models):
                for m in get_models() or []:
                    if not isinstance(m, dict) or not m.get("is_enabled", True):
                        continue
                    mid = m.get("id")
                    if not mid or mid in catalog:
                        continue
                    category = m.get("category") or (
                        classify(mid) if callable(classify) else "text"
                    )
                    catalog[str(mid)] = {
                        "capabilities": list(
                            _CATEGORY_CAPABILITIES.get(category, ["chat"])
                        ),
                        "provider_id": "configured",
                    }
        except Exception:
            catalog = {}  # 预设结构变化时整体回退
    if not catalog:
        catalog = {k: dict(v) for k, v in _FALLBACK_CATALOG.items()}
    # 网关内置别名永远可用（走网关自己的上游路由）
    catalog.setdefault(
        "yimu-auto", {"capabilities": ["chat"], "provider_id": "yimu"}
    )
    for alias, caps in (
        ("yimu-chat", ["chat", "vision"]),
        ("yimu-embed", ["embeddings"]),
        ("yimu-image", ["images"]),
    ):
        catalog.setdefault(alias, {"capabilities": list(caps), "provider_id": "yimu"})
    return catalog


@dataclass
class GatewaySettings:
    """网关运行时设置（全部来自环境变量）。"""

    db_url: str
    upstreams: list[UpstreamConfig]
    pricing: dict[str, dict[str, int]]
    admin_key: str
    image_output_tokens_per_image: int = 1024
    default_output_estimate_tokens: int = 1024
    circuit_fail_threshold: int = 3
    circuit_open_seconds: float = 30.0


def load_settings() -> GatewaySettings:
    """读取全部环境变量，组装网关设置。"""
    return GatewaySettings(
        db_url=os.environ.get("YIMU_DB_URL", "sqlite:///./data/yimu.db"),
        upstreams=load_upstreams(),
        pricing=load_pricing(),
        admin_key=os.environ.get("YIMU_ADMIN_KEY", ""),
        image_output_tokens_per_image=int(
            os.environ.get("YIMU_GW_IMAGE_OUTPUT_TOKENS", "1024")
        ),
        circuit_fail_threshold=int(os.environ.get("YIMU_GW_CIRCUIT_FAILS", "3") or 3),
        circuit_open_seconds=float(os.environ.get("YIMU_GW_CIRCUIT_OPEN_SEC", "30") or 30),
    )
