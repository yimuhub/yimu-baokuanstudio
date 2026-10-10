"""视频合成配置中心：素材 API Key / 字幕开关 / 声音引擎。

存储：项目根 data/video_config.json（JSON 文件，不在 git 敏感扫描范围内，
key 只存本地）。

优先级：配置文件 > 环境变量（``PEXELS_API_KEY`` / ``PIXABAY_API_KEY``）。

R4-5 安全调整
-------------
``data/`` 目录下曾以明文存放 pexels_api_key，且历史上 data/ 整目录被挂成
HTTP 可访问（``/static-img/data/video_config.json`` 可直接下载），构成密钥泄露。
现在：

1. 静态挂载已收窄到 ``data/editor_uploads``（见 ``web/admin.py``），data/ 不可再被下载；
2. key 的**推荐存储位置改为 .env / 进程环境变量**，``get_*_key()`` 走
   ``core.llm.load_env()``（.env 文件 + os.environ 合并），与全项目其他密钥
   （``MEDIAFLOW_APIPOOL_KEY`` 等）读取方式一致；
3. 配置文件里的 key 仅作为兼容兜底保留（老用户升级不断档），新写入会提示迁移。
"""
import json
import logging
import os
from pathlib import Path

from core.llm import load_env

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "video_config.json"

VOICE_ENGINES = ("tts", "voice_clone", "local_model")

MATERIAL_MODES = ("stock_only", "ai_only", "mixed")

_DEFAULTS = {
    "pexels_api_key": "",
    "pixabay_api_key": "",
    "subtitle_enabled": True,
    "voice_engine": "tts",
    "voice_clone_provider": "custom",
    "voice_clone_api_url": "",
    "voice_clone_api_key": "",
    "voice_clone_model": "",
    "voice_clone_voice_id": "",
    "voice_clone_prompt_audio": "",
    "local_model_path": "",
    "material_mode": "mixed",
}


def _read_file() -> dict:
    try:
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_config] 读取配置失败: %s", exc)
    return {}


def get_config() -> dict:
    """返回完整配置（合并默认值，不含掩码）。"""
    cfg = dict(_DEFAULTS)
    cfg.update({k: v for k, v in _read_file().items() if k in _DEFAULTS})
    # 类型兜底
    if cfg.get("voice_engine") not in VOICE_ENGINES:
        cfg["voice_engine"] = "tts"
    if cfg.get("material_mode") not in MATERIAL_MODES:
        cfg["material_mode"] = "mixed"
    cfg["subtitle_enabled"] = bool(cfg.get("subtitle_enabled", True))
    return cfg


def save_config(patch: dict) -> dict:
    """增量更新配置，只接受已知字段，返回更新后的完整配置。"""
    if not isinstance(patch, dict):
        raise ValueError("配置补丁必须是 JSON 对象")
    current = _read_file()
    for k, v in patch.items():
        if k not in _DEFAULTS:
            continue  # 未知字段直接忽略
        if k == "voice_engine" and v not in VOICE_ENGINES:
            raise ValueError(f"voice_engine 非法：{v}（可选 {VOICE_ENGINES}）")
        if k == "material_mode" and v not in MATERIAL_MODES:
            raise ValueError(f"material_mode 非法：{v}（可选 {MATERIAL_MODES}）")
        current[k] = v
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("[video_config] 配置已更新: %s", sorted(patch.keys()))
    return get_config()


def mask_key(key: str) -> str:
    """掩码显示：abc***xyz；空返回空；太短全掩码。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}***{key[-3:]}"


def get_masked_config() -> dict:
    """返回给前端的配置（key 做掩码）。

    R4-5：key 迁到 .env 后，配置文件里为空，但前端仍需知道「是否已配置」，
    否则设置页会误显示为未配置、诱导用户重复填写。因此掩码取实际生效值
    （含 .env），并用 ``*_source`` 标注来源（config / env）。
    """
    cfg = get_config()
    env = load_env()
    pexels = cfg["pexels_api_key"].strip() or env.get("PEXELS_API_KEY", "").strip()
    pixabay = cfg["pixabay_api_key"].strip() or env.get("PIXABAY_API_KEY", "").strip()
    cfg["pexels_api_key"] = mask_key(pexels)
    cfg["pixabay_api_key"] = mask_key(pixabay)
    cfg["voice_clone_api_key"] = mask_key(cfg["voice_clone_api_key"])
    cfg["pexels_api_key_source"] = "config" if _raw("pexels_api_key") else ("env" if pexels else "none")
    cfg["pixabay_api_key_source"] = "config" if _raw("pixabay_api_key") else ("env" if pixabay else "none")
    return cfg


def _raw(field: str) -> str:
    """取配置文件中该 key 字段的原始值（用于判断来源，不做掩码）。"""
    return (_read_file().get(field) or "").strip()


def get_pexels_key() -> str:
    """配置优先，环境变量/.env 兜底。

    R4-5：用 ``load_env()`` 同时读取 .env 文件与进程环境变量，
    与项目内其他密钥（MEDIAFLOW_APIPOOL_KEY 等）保持一致的读取方式。
    """
    return get_config()["pexels_api_key"].strip() or load_env().get("PEXELS_API_KEY", "").strip()


def get_pixabay_key() -> str:
    """配置优先，环境变量/.env 兜底（同 get_pexels_key）。"""
    return get_config()["pixabay_api_key"].strip() or load_env().get("PIXABAY_API_KEY", "").strip()


def get_subtitle_enabled() -> bool:
    return bool(get_config().get("subtitle_enabled", True))


def get_voice_engine() -> str:
    eng = get_config().get("voice_engine", "tts")
    return eng if eng in VOICE_ENGINES else "tts"


def get_material_mode() -> str:
    """素材模式：stock_only / ai_only / mixed（默认）。"""
    m = get_config().get("material_mode", "mixed")
    return m if m in MATERIAL_MODES else "mixed"


def delete_key(provider: str) -> dict:
    """删除指定 provider 的 key（provider: pexels / pixabay）。"""
    field = {"pexels": "pexels_api_key", "pixabay": "pixabay_api_key"}.get(provider)
    if not field:
        raise ValueError(f"未知 provider：{provider}（可选 pexels / pixabay）")
    return save_config({field: ""})
