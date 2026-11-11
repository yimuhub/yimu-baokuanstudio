# SPDX-License-Identifier: BUSL-1.1
"""供应商配置与密钥的**单一真源**（Single Source of Truth）。

为什么要这个模块（v15.8.3 客户缺陷）
------------------------------------
Windows 客户端在「设置 → 模型服务」填好 API 地址与密钥，点「一句话生成爆款」
仍然报「大模型全链路调用失败」。根因不是密钥错，而是**同一件事被存了两份、
读的又是另一份**：

* 密钥：``save_provider_config`` 写进**安装目录** ``.env``，而 ``load_env()``
  的优先级是「进程环境变量 > 用户目录 secrets.env > 安装目录 .env」。
  首次启动的迁移早已把旧 Key 搬进 secrets.env，于是用户新填的 Key 写到了
  **优先级更低**的位置——旧的占位值 ``test_key`` 永远赢。
* 端点：新地址写进 ``gateway.providers.<pid>.base_url``，而解析器读的是
  ``gateway.base_url`` 这份**出厂快照**。两者一旦分家，请求就带着新 Key
  打向老地址。

本模块把「写在哪、从哪读」收成一处：
1. **供应商池** ``gateway.providers`` 是唯一存储；``gateway.base_url`` /
   ``model`` / ``configured_models`` / ``agent_routing`` 不再是独立事实，
   而是由**活动供应商派生**出来的只读视图（``derive_view``）。
2. **密钥只写用户目录** ``secrets.env``（0600），与 ``load_env()`` 的
   优先级方向一致；安装目录 ``.env`` 只作为旧版本兼容读取源。
3. **占位值一律视为「没有 Key」**（``test_key`` / ``your-api-key`` 等），
   避免「配置了示例值」被误判成「已配置」，把用户卡死在必然 401 的通道上。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent

#: 视为「没填」的占位值。命中即当没有 Key，绝不用它发请求。
PLACEHOLDER_KEYS = frozenset({
    "", "test_key", "testkey", "test", "your-api-key", "your_api_key",
    "sk-xxx", "sk-xxxx", "xxx", "changeme", "placeholder", "none", "null",
    "yourkey", "your-key", "api_key", "apikey", "sk-",
})

#: 派生视图字段：旧代码直接读 gateway.xxx，这里保证它永远等于活动供应商的值。
DERIVED_FIELDS = ("base_url", "model", "configured_models", "agent_routing")


# ---------------------------------------------------------------------------
# 文件落点
# ---------------------------------------------------------------------------

def config_path() -> Path:
    """主配置文件；安装目录不可写时的回退位置（load_config 会覆盖叠加）。"""
    return BASE / "config.yaml"


def writable_config_path() -> Path:
    """真正用于写入的配置文件。

    安装到 ``Program Files`` 一类只读位置时，写 ``config.yaml`` 会 OSError；
    此时退到 ``data/config.local.yaml``——``load_config()`` 本来就会把它
    叠加在主配置之上，所以读写仍然自洽。
    """
    main = config_path()
    try:
        if main.exists():
            return main if os.access(main, os.W_OK) else BASE / "data" / "config.local.yaml"
        return main if os.access(main.parent, os.W_OK) else BASE / "data" / "config.local.yaml"
    except OSError:
        return main


def install_env_path() -> Path:
    """安装目录 .env：仅作为旧版本兼容读取源，新写入不再落这里。"""
    return BASE / ".env"


# ---------------------------------------------------------------------------
# 读配置
# ---------------------------------------------------------------------------

def raw_config() -> dict:
    """读配置文件（不做任何归一化，写盘前用这个）。"""
    cfg: dict[str, Any] = {}
    f = config_path()
    if f.exists():
        try:
            with open(f, encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError) as e:
            logger.warning("[registry] 读取 %s 失败：%s", f, e)
            cfg = {}
    local = BASE / "data" / "config.local.yaml"
    if local.exists():
        try:
            with open(local, encoding="utf-8") as fh:
                local_cfg = yaml.safe_load(fh) or {}
            if isinstance(local_cfg, dict):
                for k, v in local_cfg.items():
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k].update(v)
                    else:
                        cfg[k] = v
        except (OSError, yaml.YAMLError) as e:
            logger.warning("[registry] 读取 %s 失败：%s", local, e)
    return cfg if isinstance(cfg, dict) else {}


def write_config(cfg: dict) -> bool:
    """把归一化后的配置落盘；失败不抛异常，返回 False。"""
    target = writable_config_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, allow_unicode=True)
        tmp.replace(target)
        return True
    except OSError as e:
        logger.error("[registry] 写入配置失败 %s：%s", target, e)
        return False


# ---------------------------------------------------------------------------
# 归一化：把「双份存储」折叠成一份
# ---------------------------------------------------------------------------

def _pool(gw: dict) -> dict:
    p = gw.get("providers")
    if not isinstance(p, dict):
        p = {}
        gw["providers"] = p
    return p


def normalize(cfg: dict, *, presets: dict | None = None) -> tuple[dict, bool]:
    """把配置折叠成单一真源，返回 ``(cfg, 是否需要回写)``。

    1. 旧版把活动通道的 base_url/model 同时写在 ``gateway`` 顶层与
       ``providers[active]``。以 **providers 池为准**折叠（池是用户最近一次
       保存的地方，也是 UI 展示的地方）；池里没有时用顶层值补进池。
    2. 折叠后删除顶层冗余字段，之后 ``gateway`` 只保留 ``provider_id``
       与供应商池，其余字段由 :func:`derive_view` 现算。
    """
    gw = cfg.get("gateway")
    if not isinstance(gw, dict):
        gw = {}
        cfg["gateway"] = gw
    pool = _pool(gw)
    active = str(gw.get("provider_id") or "").strip() or "deepseek"
    gw["provider_id"] = active

    dirty = False
    entry = pool.get(active)
    if not isinstance(entry, dict):
        entry = {}
        pool[active] = entry
        dirty = True

    # 顶层旧字段 -> 池（仅当池里缺该字段时才搬，避免覆盖用户最近保存的值）
    for field in DERIVED_FIELDS:
        legacy = gw.get(field)
        if legacy in (None, "", [], {}):
            continue
        if entry.get(field) in (None, "", [], {}):
            entry[field] = legacy
            dirty = True

    # 预设兜底：池里连 base_url 都没有时，用内置预设补齐（不落盘，只在视图里补）
    if presets:
        preset = presets.get(active) or {}
        if not entry.get("base_url") and preset.get("base_url"):
            entry["base_url"] = preset["base_url"]
            dirty = True
        if not entry.get("model") and preset.get("default_model"):
            entry["model"] = preset["default_model"]
            dirty = True

    # 删除顶层冗余字段：它们从此只是派生视图
    for field in DERIVED_FIELDS:
        if field in gw:
            gw.pop(field, None)
            dirty = True

    return cfg, dirty


def derive_view(cfg: dict, *, presets: dict | None = None) -> dict:
    """原地生成派生视图，让所有读 ``gateway.base_url`` 的老代码拿到正确值。

    这是**兼容层**：调用点无需改造即可受益；新代码请直接用访问器。
    """
    gw = cfg.get("gateway")
    if not isinstance(gw, dict):
        return cfg
    pool = gw.get("providers") if isinstance(gw.get("providers"), dict) else {}
    active = str(gw.get("provider_id") or "").strip() or "deepseek"
    entry = pool.get(active) if isinstance(pool.get(active), dict) else {}
    preset = (presets or {}).get(active) or {}

    gw["provider_id"] = active
    gw["base_url"] = str(entry.get("base_url") or preset.get("base_url") or "").rstrip("/")
    gw["model"] = entry.get("model") or preset.get("default_model") or "deepseek-chat"

    models = entry.get("configured_models")
    if not models and presets:
        models = [
            {"id": m, "name": m, "is_enabled": True}
            for m in (preset.get("models") or [])
        ]
    gw["configured_models"] = models or []

    gw["agent_routing"] = entry.get("agent_routing") or {}
    return cfg


def migrate(*, presets: dict | None = None) -> bool:
    """执行一次折叠迁移并回写；已归一化则什么都不做。"""
    cfg = raw_config()
    cfg, dirty = normalize(cfg, presets=presets)
    if not dirty:
        return False
    ok = write_config(cfg)
    if ok:
        logger.info("[registry] 配置已折叠为单一真源（供应商池为准）")
    return ok


# ---------------------------------------------------------------------------
# 供应商访问器
# ---------------------------------------------------------------------------

def active_provider_id(cfg: dict | None = None) -> str:
    cfg = cfg if cfg is not None else raw_config()
    gw = cfg.get("gateway") or {}
    return str(gw.get("provider_id") or "").strip() or "deepseek"


def provider_entry(pid: str, cfg: dict | None = None) -> dict:
    """取供应商池里的条目（不存在返回空字典，绝不返回 None）。"""
    cfg = cfg if cfg is not None else raw_config()
    pool = (cfg.get("gateway") or {}).get("providers") or {}
    entry = pool.get(pid)
    return entry if isinstance(entry, dict) else {}


def save_provider(pid: str, *, base_url: str | None = None, model: str | None = None,
                  configured_models: list | None = None, agent_routing: dict | None = None,
                  name: str | None = None, activate: bool = False) -> bool:
    """写供应商池；``activate`` 为真时同时把它设为活动通道。

    注意：写池**不需要**同步任何顶层快照——``derive_view`` 会现算。
    这正是修复「改了地址但解析器仍用老地址」的关键。
    """
    pid = (pid or "").strip()
    if not pid:
        return False
    cfg = raw_config()
    cfg, _ = normalize(cfg)
    gw = cfg.setdefault("gateway", {})
    pool = _pool(gw)

    entry = pool.setdefault(pid, {})
    if not isinstance(entry, dict):
        entry = {}
        pool[pid] = entry
    if name:
        entry["name"] = name.strip()
    if base_url is not None:
        entry["base_url"] = (base_url or "").strip().rstrip("/")
    if model is not None:
        entry["model"] = (model or "").strip()
    if configured_models is not None:
        entry["configured_models"] = configured_models
    elif model:
        # 用户选了新模型但没提交模型清单时，保证该模型出现在本通道的清单里，
        # 否则下拉框会继续显示旧快照里的别家模型，看起来像「保存没生效」。
        cur = entry.get("configured_models")
        ids = [str(m.get("id") if isinstance(m, dict) else m) for m in (cur or [])]
        if model and model not in ids:
            entry["configured_models"] = list(cur or []) + [
                {"id": model, "name": model, "category": "text", "is_enabled": True}
            ]
    if agent_routing is not None:
        entry["agent_routing"] = agent_routing

    if activate:
        gw["provider_id"] = pid

    # 曾删除过的供应商重新配置时移出黑名单
    deleted = set(gw.get("deleted_providers") or [])
    if pid in deleted:
        deleted.discard(pid)
        gw["deleted_providers"] = sorted(deleted)

    return write_config(cfg)


def set_active(pid: str) -> bool:
    pid = (pid or "").strip()
    if not pid:
        return False
    cfg = raw_config()
    cfg, _ = normalize(cfg)
    cfg.setdefault("gateway", {})["provider_id"] = pid
    return write_config(cfg)


def delete_provider(pid: str) -> bool:
    cfg = raw_config()
    cfg, _ = normalize(cfg)
    gw = cfg.setdefault("gateway", {})
    pool = _pool(gw)
    if pid not in pool:
        return False
    pool.pop(pid, None)
    deleted = set(gw.get("deleted_providers") or [])
    deleted.add(pid)
    gw["deleted_providers"] = sorted(deleted)
    if str(gw.get("provider_id") or "") == pid:
        # 活动通道被删：清空，让解析器给出明确的「尚未配置」而不是沿用已删地址
        gw["provider_id"] = ""
    return write_config(cfg)


# ---------------------------------------------------------------------------
# 密钥：只落用户目录
# ---------------------------------------------------------------------------

def is_placeholder(key: Any) -> bool:
    """是否是「没填」的占位值（含空串）。"""
    return str(key or "").strip().lower() in PLACEHOLDER_KEYS


def env() -> dict[str, str]:
    """合并后的配置视图：进程环境变量 > 用户 secrets.env > 安装目录 .env。"""
    try:
        from core.user_paths import merge_env
        return merge_env(install_env_path())
    except Exception as e:  # 配置读取失败绝不能让服务起不来
        logger.warning("[registry] 合并配置失败，退回进程环境变量：%s", e)
        return dict(os.environ)


def key_for(pid: str, *, allow_global: bool = True) -> str:
    """取该供应商可用的 Key；占位值/空值一律返回空串。

    ``allow_global``：是否允许回退到全局 Key（``MEDIAFLOW_APIPOOL_KEY``）。
    仅当该供应商**就是**当前活动通道时才应回退，避免 A 通道的 Key 被发往 B 通道。
    """
    pid = (pid or "").strip()
    if not pid:
        return ""
    e = env()
    candidates = [e.get(f"MEDIAFLOW_KEY_{pid.upper()}")]
    if allow_global:
        candidates.append(e.get("MEDIAFLOW_APIPOOL_KEY"))
    for k in candidates:
        k = str(k or "").strip()
        if k and not is_placeholder(k):
            return k
    return ""


def global_key() -> str:
    """全局键位 ``MEDIAFLOW_APIPOOL_KEY``（官方/平台通道使用），占位值视为空。"""
    k = str(env().get("MEDIAFLOW_APIPOOL_KEY") or "").strip()
    return "" if is_placeholder(k) else k


def set_key(pid: str, api_key: str, *, also_global: bool = False) -> bool:
    """把 Key 写入**用户目录** secrets.env（0600），并立即刷新进程环境变量。

    只写这一个位置——因为它正是 ``env()`` 里优先级更高、真正会生效的位置。
    """
    key = str(api_key or "").strip()
    if not key:
        return False
    from core.user_paths import read_env_file, secrets_env_path, write_env_file
    path = secrets_env_path()
    values = read_env_file(path)
    values[f"MEDIAFLOW_KEY_{pid.upper()}"] = key
    if also_global:
        values["MEDIAFLOW_APIPOOL_KEY"] = key
    ok = write_env_file(path, values)
    # 同进程立即生效，避免「保存后要重启」
    os.environ[f"MEDIAFLOW_KEY_{pid.upper()}"] = key
    if also_global:
        os.environ["MEDIAFLOW_APIPOOL_KEY"] = key
    if ok:
        _strip_install_env(f"MEDIAFLOW_KEY_{pid.upper()}")
        if also_global:
            _strip_install_env("MEDIAFLOW_APIPOOL_KEY")
    return ok


def clear_key(pid: str) -> bool:
    """删除该供应商的 Key（用户目录与安装目录同时清理）。"""
    from core.user_paths import read_env_file, secrets_env_path, write_env_file
    path = secrets_env_path()
    values = read_env_file(path)
    k = f"MEDIAFLOW_KEY_{pid.upper()}"
    if values.pop(k, None) is None:
        return False
    ok = write_env_file(path, values)
    os.environ.pop(k, None)
    _strip_install_env(k)
    return ok


def _strip_install_env(key_name: str) -> None:
    """清掉旧版遗留在安装目录 .env 的同名明文，防止它以后又「赢回来」。"""
    p = install_env_path()
    try:
        if not p.exists():
            return
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        kept = [ln for ln in lines if not ln.strip().startswith(f"{key_name}=")]
        if len(kept) != len(lines):
            p.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8")
    except OSError:
        pass
