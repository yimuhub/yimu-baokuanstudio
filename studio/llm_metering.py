"""LLM 双轨制计量：官方通道扣费 + 全模型服务使用量统计。

双轨制：
- 一幕·YIMU 官方（yimu_official）：计费通道，按 Token 折算 credits 扣会员额度。
- 其他所有模型服务：自备 Key 通道，不扣额度，仅做使用量统计。

使用量统计存 ``data/llm_usage.json``（JSON 文件）。
额度扣减走 ``studio.membership.service.deduct_credits``（原子扣减）。

⭐ R2-1/R2-2 计价口径：credits 换算统一走 ``studio.pricing.credits_for_call``
   （per-1k 口径），与网关 ``/v1`` 路径共用同一份单价表，
   因此「同一模型走llm_metering 与走 /v1」两条路径扣减的 credits 完全一致。
   禁止在本模块把 total_tokens 直接当 credits 扣（那是历史 bug，差 250~500 倍）。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import pricing

log = logging.getLogger(__name__)

_USAGE_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_usage.json"

OFFICIAL_PROVIDER_ID = "yimu_official"

_TENANT_ID = "default"


def _read_usage() -> dict:
    try:
        if _USAGE_PATH.exists():
            data = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:  # noqa: BLE001
        log.warning("[llm_metering] 读取用量统计失败: %s", exc)
    return {}


def _write_usage(data: dict) -> None:
    try:
        _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _USAGE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_USAGE_PATH)
    except Exception as exc:  # noqa: BLE001
        log.warning("[llm_metering] 写入用量统计失败: %s", exc)


class InsufficientCreditsError(RuntimeError):
    """官方通道额度不足。"""


def estimate_tokens(text: str) -> int:
    """无 usage 返回时的 Token 估算（兜底，避免 0 token 导致漏扣费）。

    启发式：中文约 1.6 字/token，英文约 4 字符/token，混合文本取 len//2。
    估算偏保守（略高），宁可多扣不漏扣。
    """
    if not text:
        return 0
    # CJK 字符按 0.6 token/字，非 CJK 按 0.25 token/字符
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff" or "\uac00" <= ch <= "\ud7af")
    non_cjk = len(text) - cjk
    return max(1, int(cjk * 0.6 + non_cjk * 0.25))


def record_llm_call(
    provider_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    user_id: str | None = None,
    prompt_text: str = "",
    completion_text: str = "",
) -> dict:
    """记录一次 LLM 调用。

    所有 provider 都记使用量统计；仅 yimu_official 且 user_id 非空时扣会员额度。

    当 API 未返回 usage（total_tokens=0）时，用文本估算兜底，避免漏扣费。
    估算值会在统计中标记 estimated=True。

    返回 {"metered": bool, "deducted": int, "left": int, "estimated": bool}。
    deducted 是 **credits 点数**（R2-2 起不再是 token 数）。
    额度不足时抛 InsufficientCreditsError。
    """
    provider_id = (provider_id or "").strip() or "unknown"
    model = (model or "").strip() or "unknown"
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    total_tokens = max(0, int(total_tokens or 0))
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    # usage 缺失时用文本估算兜底（避免 0 token 漏扣费）
    estimated = False
    if total_tokens == 0 and (prompt_text or completion_text):
        if prompt_tokens == 0 and prompt_text:
            prompt_tokens = estimate_tokens(prompt_text)
        if completion_tokens == 0 and completion_text:
            completion_tokens = estimate_tokens(completion_text)
        total_tokens = prompt_tokens + completion_tokens
        estimated = total_tokens > 0
        if estimated:
            log.info("[llm_metering] API 未返回 usage，已用文本估算: prompt=%d completion=%d total=%d",
                     prompt_tokens, completion_tokens, total_tokens)

    # 1) 使用量统计（所有 provider）
    data = _read_usage()
    entry = data.get(provider_id) or {
        "provider_id": provider_id,
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "last_used": "",
        "last_model": "",
        "deducted_total": 0,
    }
    entry["calls"] = int(entry.get("calls", 0)) + 1
    entry["prompt_tokens"] = int(entry.get("prompt_tokens", 0)) + prompt_tokens
    entry["completion_tokens"] = int(entry.get("completion_tokens", 0)) + completion_tokens
    entry["total_tokens"] = int(entry.get("total_tokens", 0)) + total_tokens
    entry["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")
    entry["last_model"] = model

    # 2) 官方通道扣费
    metered = provider_id == OFFICIAL_PROVIDER_ID
    deducted = 0
    left = -1
    # ⭐ R2-2：credits 必须走 per-1k 口径换算，**禁止直接把 total_tokens 当credits 扣**。
    #   历史实现是 deduct_credits(..., total_tokens)，即「1 token = 1 credit」，
    #   与网关 /v1 路径（per-1k）差250~500 倍，同一份额度两条路径价值完全不同。
    #   现统一调studio.pricing.credits_for_call——网关侧 write_ledger_rows
    #   也调同一个函数，因此同一模型同一 token 数必然扣出同样的 credits。
    in_credits, out_credits = pricing.credits_for_call(
        model, prompt_tokens, completion_tokens
    )
    credits_cost = in_credits + out_credits
    if metered:
        if not user_id:
            log.warning("[llm_metering] 官方通道调用缺少 user_id，本次仅记统计未扣费")
        elif credits_cost > 0:
            try:
                from studio.membership import capabilities as _caps
                from studio.membership import service as _svc

                _db = _caps.get_db_session()
                try:
                    _tier = _caps.get_user_tier(_db, tenant_id=_TENANT_ID, user_id=str(user_id))
                    # admin 恒为 studio 档，get_user_tier 已处理
                    ok, left = _svc.deduct_credits(_db, _TENANT_ID, str(user_id), credits_cost)
                    if not ok:
                        raise InsufficientCreditsError(
                            f"会员额度不足：本次需 {credits_cost} 点算力（{model}，"
                            f"输入 {prompt_tokens} + 输出 {completion_tokens} tokens），"
                            f"剩余额度 {left} 点，请升级会员或更换自备 Key 通道"
                        )
                    deducted = credits_cost
                    entry["deducted_total"] = int(entry.get("deducted_total", 0)) + credits_cost
                    log.info(
                        "[llm_metering] 官方通道扣费 user=%s tier=%s model=%s "
                        "in=%d out=%d tokens=%d credits=%d left=%d",
                        user_id, _tier, model,
                        prompt_tokens, completion_tokens, total_tokens, credits_cost, left,
                    )
                finally:
                    _db.close()
            except InsufficientCreditsError:
                raise
            except Exception as exc:  # noqa: BLE001
                # 计费系统异常时不阻塞主功能（切换为仅记统计），打日志
                log.warning("[llm_metering] 官方通道扣费异常，已切换为仅记统计: %s", exc)

    data[provider_id] = entry
    _write_usage(data)
    return {"metered": metered, "deducted": deducted, "left": left, "estimated": estimated}


def get_provider_usage() -> dict:
    """返回各 provider 的使用量统计。

    {provider_id: {calls, total_tokens, prompt_tokens, completion_tokens,
                  last_used, last_model, deducted_total, metered}}
    """
    data = _read_usage()
    out = {}
    for pid, entry in data.items():
        out[pid] = {
            "provider_id": pid,
            "calls": int(entry.get("calls", 0)),
            "prompt_tokens": int(entry.get("prompt_tokens", 0)),
            "completion_tokens": int(entry.get("completion_tokens", 0)),
            "total_tokens": int(entry.get("total_tokens", 0)),
            "last_used": entry.get("last_used", ""),
            "last_model": entry.get("last_model", ""),
            "deducted_total": int(entry.get("deducted_total", 0)),
            "metered": pid == OFFICIAL_PROVIDER_ID,
        }
    return out


def get_yimu_official_summary(user_id: str | None = None) -> dict:
    """官方通道消费汇总（供账本页/统计卡片展示）。"""
    data = _read_usage()
    entry = data.get(OFFICIAL_PROVIDER_ID) or {}
    summary = {
        "provider_id": OFFICIAL_PROVIDER_ID,
        "calls": int(entry.get("calls", 0)),
        "total_tokens": int(entry.get("total_tokens", 0)),
        "deducted_total": int(entry.get("deducted_total", 0)),
        "last_used": entry.get("last_used", ""),
    }
    if user_id:
        try:
            from studio.membership import capabilities as _caps
            from studio.membership import service as _svc

            _db = _caps.get_db_session()
            try:
                _tier = _caps.get_user_tier(_db, tenant_id=_TENANT_ID, user_id=str(user_id))
                m = (
                    _db.query(_svc.Membership)
                    .filter(
                        _svc.Membership.tenant_id == _TENANT_ID,
                        _svc.Membership.user_id == str(user_id),
                    )
                    .first()
                )
                summary["tier"] = _tier
                summary["tier_display"] = _caps.tier_display_name(_tier)
                summary["credits_left"] = _svc.credits_left(m) if m else 0
                summary["credits_total"] = int(m.credits_total) if m else 0
                summary["credits_used"] = int(m.credits_used) if m else 0
            finally:
                _db.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("[llm_metering] 获取官方通道汇总失败: %s", exc)
    return summary
