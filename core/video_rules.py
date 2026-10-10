# SPDX-License-Identifier: BUSL-1.1
"""视频模型能力表加载 + 参数钳制（data/video_model_rules.json）。

客户在 config.yaml 注册新视频模型后，只需在能力表里加一条规则（match 关键字 +
时长档位/画幅/禁用字段/轮询参数），`core/ad_video._call_video_model` 会自动按该
模型的要求构造请求体——未知模型走 default 规则（不钳制，保持旧行为）。

规则结构说明见 docs/VIDEO_MODELS.md §5。本模块纯函数、无网络、无 I/O 依赖
（文件缺失/损坏时降级为空规则表，不影响生成主流程）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("yimu.video_rules")

_RULES_FILE = Path(__file__).resolve().parent.parent / "data" / "video_model_rules.json"
_cache: dict | None = None


def load_rules() -> dict:
    """读能力表（带缓存；文件缺失/损坏时返回空规则表并告警，不抛异常）。"""
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_RULES_FILE.read_text(encoding="utf-8"))
            if not isinstance(_cache, dict) or "rules" not in _cache:
                _cache = {"rules": []}
        except Exception as exc:  # noqa: BLE001
            log.warning("[video_rules] 能力表读取失败（%s），按无规则处理: %s",
                        _RULES_FILE, exc)
            _cache = {"rules": []}
    return _cache


def clear_cache() -> None:
    """测试/热更用：清缓存下次重读。"""
    global _cache
    _cache = None


def match_rule(model: str) -> dict | None:
    """按模型名小写关键字包含匹配，规则数组顺序即优先级（越具体越靠前）。

    命中返回规则 dict；未命中返回 None（调用方走 default 行为）。
    """
    m = (model or "").lower()
    if not m:
        return None
    for r in load_rules().get("rules", []):
        keys = [str(k).lower() for k in r.get("match", [])]
        if any(k and k in m for k in keys):
            return r
    return None


def clamp_duration(duration_s: int, rule: dict | None) -> int | None:
    """按规则钳制时长。

    - drop_field：该模型不吃时长字段（如 Agnes Flash 固定 5s）→ 返回 None（不传）
    - durations_s 有值：取距目标最近的允许档（如 Sora 5s→4s、Kling 8s→10s）
    - duration_range_s：越界收到区间内（如万相 30s→15s、2s 以下→2s）
    - 无规则/无限制：原样返回
    """
    if not rule:
        return duration_s
    if rule.get("duration_clamp") == "drop_field":
        return None
    allowed = rule.get("durations_s")
    if allowed:
        return min(allowed, key=lambda x: abs(x - duration_s))
    lo, hi = rule.get("duration_range_s") or (None, None)
    if lo is not None and duration_s < lo:
        return lo
    if hi is not None and duration_s > hi:
        return hi
    return duration_s


def aspect_payload(rule: dict | None, aspect: str) -> dict:
    """画幅参数构造。

    规则指定 aspect_field（如 Sora 用 size 传 "720x1280"）时按规则映射；
    否则沿用通用格式 {aspect_ratio + size(1080 档)}。返回可直接 merge 进请求体
    的 dict。
    """
    if rule and rule.get("aspect_field") == "size" and rule.get("aspect_values"):
        vals = rule["aspect_values"]
        size = vals.get(aspect) or ("720x1280" if aspect == "9:16" else "1280x720")
        return {"size": size}
    return {
        "aspect_ratio": aspect,
        "size": "1080x1920" if aspect == "9:16" else "1920x1080",
    }


def duration_field(rule: dict | None) -> str:
    """时长字段名（Sora 用 seconds，Veo 用 durationSeconds，默认 duration）。"""
    return (rule or {}).get("duration_field", "duration")


def extra_headers(rule: dict | None) -> dict:
    """规则要求的附加请求头（如 DashScope 必带 X-DashScope-Async: enable）。"""
    h = (rule or {}).get("required_headers") or {}
    return {str(k): str(v) for k, v in h.items()} if isinstance(h, dict) else {}


def poll_params(rule: dict | None) -> tuple[int, int]:
    """轮询参数 (间隔秒, 总次数)，缺省 5s/120 次（=10 分钟，与 Agnes 现行为一致）。"""
    iv = int((rule or {}).get("poll_interval_s") or 5)
    to = int((rule or {}).get("poll_timeout_s") or 600)
    iv = max(1, iv)
    polls = max(1, to // iv)
    return iv, polls
