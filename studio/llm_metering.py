"""LLM 双轨制计量：官方通道扣费 + 全模型服务使用量统计。

双轨制：
- 一幕·YIMU 官方（yimu_official）：计费通道，按 Token 折算 credits 扣会员额度。
- 其他所有模型服务：自备 Key 通道，不扣额度，仅做使用量统计。

⭐ V9.3.2 / V9.4.0 免费体验额度（官方通道免费体验模式）：
  free 档用户每日前 pricing.FREE_DEMO_DAILY_CALLS 次官方通道调用
  （且 completion_tokens ≤ pricing.FREE_DEMO_MAX_OUTPUT_TOKENS）走
  "免费体验"：只记统计、不扣会员额度。耗尽后回落正常扣费，
  额度不足照常抛 InsufficientCreditsError。
  新增进程内线程安全锁（_METERING_LOCK）与历史自然日自动清理，防止并发竞态与 JSON 无限膨胀。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import pricing

log = logging.getLogger(__name__)

_USAGE_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_usage.json"

OFFICIAL_PROVIDER_ID = "yimu_official"

_TENANT_ID = "default"

#: 免费体验计数持久化文件（按 用户+自然日 记录已用次数；重启不丢失、跨请求累计）。
_DEMO_PATH = Path(__file__).resolve().parent.parent / "data" / "free_demo_calls.json"

#: 进程内可重入互斥锁，保护 JSON 账本/免费计数并发读写原子性
_METERING_LOCK = threading.RLock()


def _read_demo() -> dict:
    with _METERING_LOCK:
        try:
            if _DEMO_PATH.exists():
                data = json.loads(_DEMO_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as exc:  # noqa: BLE001
            log.warning("[llm_metering] 读取免费体验计数失败: %s", exc)
        return {}


def _write_demo(data: dict) -> None:
    with _METERING_LOCK:
        try:
            _DEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _DEMO_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(_DEMO_PATH)
        except Exception as exc:  # noqa: BLE001
            log.warning("[llm_metering] 写入免费体验计数失败: %s", exc)


def _today_key() -> str:
    """自然日键（UTC+8 与 README 面向市场一致；0 点自动重置）。"""
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


def consume_free_demo_call(user_id: str, completion_tokens: int) -> dict:
    """⭐ 免费体验额度检查与扣减（官方通道 · free 档，带并发锁保护）。"""
    result = {"eligible": False, "left_today": 0, "reason": ""}
    if not user_id:
        result["reason"] = "no_user"
        return result
    try:
        from studio.membership import capabilities as _caps

        tier = None
        try:
            _db = _caps.get_db_session()
            try:
                tier = _caps.get_user_tier(_db, tenant_id=_TENANT_ID, user_id=str(user_id))
            finally:
                _db.close()
        except Exception:
            tier = None
        if tier is None:
            tier = "free"
        if tier != "free":
            result["reason"] = f"tier_{tier}"
            return result
        if int(completion_tokens or 0) > pricing.FREE_DEMO_MAX_OUTPUT_TOKENS:
            result["reason"] = "too_long_output"
            return result
    except Exception as exc:  # noqa: BLE001
        log.warning("[llm_metering] 免费体验档位判定失败，回落正常扣费: %s", exc)
        result["reason"] = "tier_check_failed"
        return result

    with _METERING_LOCK:
        day = _today_key()
        data = _read_demo()
        raw_entry = data.get(str(user_id)) or {}
        # 仅保留近 7 个自然日的键，防止 JSON 文件随时间无限膨胀
        entry = {k: v for k, v in raw_entry.items() if k >= day or len(raw_entry) <= 7}
        if len(entry) > 7:
            sorted_days = sorted(entry.keys())[-7:]
            entry = {k: entry[k] for k in sorted_days}
        used = int(entry.get(day, 0))
        limit = pricing.FREE_DEMO_DAILY_CALLS
        if used >= limit:
            result["reason"] = "quota_exhausted"
            result["left_today"] = 0
            return result

        entry[day] = used + 1
        data[str(user_id)] = entry
        _write_demo(data)
        result["eligible"] = True
        result["left_today"] = max(limit - used - 1, 0)
        log.info(
            "[llm_metering] 免费体验额度 user=%s day=%s used=%d/%d out_tokens=%d",
            user_id, day, used + 1, limit, completion_tokens,
        )
        return result


def free_demo_left_today(user_id: str) -> int:
    """今日剩余免费体验次数（供 UI 展示；异常按 0 处理，绝不阻塞主链路）。"""
    if not user_id:
        return 0
    day = _today_key()
    entry = _read_demo().get(str(user_id)) or {}
    used = int(entry.get(day, 0))
    return max(pricing.FREE_DEMO_DAILY_CALLS - used, 0)


def can_use_free_demo(user_id: str) -> bool:
    """调用前预检：判断该 free 用户今日是否仍保有官方通道免费体验次数。"""
    if not user_id:
        return False
    return free_demo_left_today(user_id) > 0


def _read_usage() -> dict:
    with _METERING_LOCK:
        try:
            if _USAGE_PATH.exists():
                data = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as exc:  # noqa: BLE001
            log.warning("[llm_metering] 读取用量统计失败: %s", exc)
        return {}


def _write_usage(data: dict) -> None:
    with _METERING_LOCK:
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
    """无 usage 返回时的 Token 估算（兜底，避免 0 token 导致漏扣费）。"""
    if not text:
        return 0
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
    """记录一次 LLM 调用（带并发锁保护）。"""
    provider_id = (provider_id or "").strip() or "unknown"
    model = (model or "").strip() or "unknown"
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    total_tokens = max(0, int(total_tokens or 0))
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

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

    with _METERING_LOCK:
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
        in_credits, out_credits = pricing.credits_for_call(
            model, prompt_tokens, completion_tokens
        )
        credits_cost = in_credits + out_credits
        free_demo = False
        free_demo_left = 0
        if metered:
            demo = consume_free_demo_call(user_id, completion_tokens)
            if demo.get("eligible"):
                free_demo = True
                free_demo_left = int(demo.get("left_today", 0))
                entry.setdefault("free_demo_calls", 0)
                entry["free_demo_calls"] = int(entry.get("free_demo_calls", 0)) + 1
        if metered and not free_demo:
            if not user_id:
                log.warning("[llm_metering] 官方通道调用缺少 user_id，本次仅记统计未扣费")
            elif credits_cost > 0:
                try:
                    from studio.membership import capabilities as _caps
                    from studio.membership import service as _svc

                    _db = _caps.get_db_session()
                    try:
                        _tier = _caps.get_user_tier(_db, tenant_id=_TENANT_ID, user_id=str(user_id))
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
                    log.warning("[llm_metering] 官方通道扣费异常，已切换为仅记统计: %s", exc)

        data[provider_id] = entry
        _write_usage(data)
        return {
            "metered": metered,
            "deducted": deducted,
            "left": left,
            "estimated": estimated,
            "free_demo": free_demo,
            "free_demo_left": free_demo_left,
        }


def get_provider_usage() -> dict:
    """返回各 provider 的使用量统计。"""
    data = _read_usage()
    out = {}
    for pid, entry in data.items():
        if not isinstance(entry, dict):
            continue
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
        "free_demo_calls": int(entry.get("free_demo_calls", 0)),
        "last_used": entry.get("last_used", ""),
    }
    summary["free_demo_daily_calls"] = pricing.FREE_DEMO_DAILY_CALLS
    summary["free_demo_left_today"] = free_demo_left_today(str(user_id)) if user_id else 0
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
