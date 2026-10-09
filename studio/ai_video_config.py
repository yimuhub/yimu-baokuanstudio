"""AI 短视频生成配置：分段时长 / 段间间隔 / 并行数 / 默认视频模型。

存储：项目根 data/ai_video_config.json（JSON 文件）。
"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "ai_video_config.json"

_DEFAULTS = {
    "segment_seconds": 8,      # 每段时长（秒），视频大模型单次生成上限
    "interval_seconds": 2,     # 段间间隔（秒），防限流
    "max_parallel": 1,         # 并行数：1=逐个排队，>1=多路并行
    "video_model": "",         # 默认视频模型（空=用 ad_video stage 配置）
}


def _read_file() -> dict:
    try:
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:  # noqa: BLE001
        log.warning("[ai_video_config] 读取配置失败: %s", exc)
    return {}


def get_config() -> dict:
    """返回完整配置（默认值 + 文件覆盖）。"""
    cfg = dict(_DEFAULTS)
    cfg.update(_read_file())
    # 合法性兜底
    try:
        cfg["segment_seconds"] = max(4, min(int(cfg["segment_seconds"]), 30))
    except Exception:
        cfg["segment_seconds"] = 8
    try:
        cfg["interval_seconds"] = max(0, min(int(cfg["interval_seconds"]), 60))
    except Exception:
        cfg["interval_seconds"] = 2
    try:
        cfg["max_parallel"] = max(1, min(int(cfg["max_parallel"]), 4))
    except Exception:
        cfg["max_parallel"] = 1
    return cfg


def save_config(patch: dict) -> dict:
    """合并保存配置，返回完整配置。"""
    data = _read_file()
    for k in _DEFAULTS:
        if k in patch:
            data[k] = patch[k]
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001
        log.warning("[ai_video_config] 保存配置失败: %s", exc)
    return get_config()
