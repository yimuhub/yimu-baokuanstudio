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
import time
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

#: 三条能力线。文字、生图、生视频可以各自落在**不同**的供应商上——
#: 一家只有文本模型的中转，不该把整站的生图/生视频也锁死在它身上。
CAPABILITY_CATEGORIES = ("text", "image", "video")
CAPABILITY_LABELS = {"text": "文字", "image": "生图", "video": "生视频"}


# ---------------------------------------------------------------------------
# 文件落点
# ---------------------------------------------------------------------------

def config_path() -> Path:
    """主配置文件；安装目录不可写时的回退位置（load_config 会覆盖叠加）。"""
    return BASE / "config.yaml"


def writable_config_path() -> Path:
    """真正用于写入的配置文件：**优先用户覆盖层** ``data/config.local.yaml``。

    为什么要改（V15.9.5）：``config.yaml`` 是**出厂样本**，跟着仓库走；用户在
    设置页做的每一次改动（删除通道、改水印、换风格）以前都直接写回它，于是

    * 开发机的工作区永远是脏的，``git pull`` 天天冲突；
    * 更新器为了能拉代码会先 ``git checkout -- config.yaml`` 再还原，稍有不慎
      用户删掉的通道就"复活"了；
    * 「出厂配置不得预置模型」这类门禁读到的是开发机被改过的文件，直接变红。

    ``data/`` 本来就被 git 忽略，``raw_config()`` 也早就把它叠加在主配置之上，
    所以用户状态落这里既不影响出厂样本，也不会被更新流程动到。
    安装目录连 ``data/`` 都不可写时（极少见），退回安装目录的 ``config.yaml``。
    """
    override = BASE / "data" / "config.local.yaml"
    try:
        if override.exists():
            return override if os.access(override, os.W_OK) else config_path()
        if os.access(override.parent, os.W_OK) or os.access(BASE, os.W_OK):
            return override
        return config_path()
    except OSError:
        return config_path()


def install_env_path() -> Path:
    """安装目录 .env：仅作为旧版本兼容读取源，新写入不再落这里。"""
    return BASE / ".env"


# ---------------------------------------------------------------------------
# 读配置
# ---------------------------------------------------------------------------

def _read_yaml_file(path: Path) -> dict:
    """安全读取单个 YAML；解析失败抛 RuntimeError（不静默吞掉）。"""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"配置文件 {path} 内容不是有效的键值结构（解析结果为 {type(data).__name__}）")
    return data


def _load_yaml_with_bak(path: Path, bak: Path) -> dict:
    """读 YAML；坏文件回退上次好配置（.bak），bak 也没有则抛异常让启动失败。

    🔴 v15.9.8 整改：旧实现 YAML 解析失败时静默返回空配置——``config.local.yaml``
    是供应商池/密钥配置的唯一真源，解析失败即「密钥全消失」，全站通道按空跑，
    用户只会看到「所有模型服务都没了」却查不到原因。现在：
      1. 解析失败 → 把坏文件改名 ``<原名>.corrupt-<时间戳>`` 保留现场（便于
         人工恢复；不直接覆盖 .bak，避免把最后一次好配置也弄丢）；
      2. 尝试读 .bak（write_config 每次写入前的自动备份）→ log.error；
      3. .bak 也没有/也坏 → 抛显性异常让启动失败。**密钥全消失优于静默空跑**：
         宁可启动报错让人来修，也不能带着空配置假装一切正常。
    """
    try:
        return _read_yaml_file(path)
    except Exception as primary_err:
        corrupt = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            path.replace(corrupt)
            logger.error(
                "[registry] 配置文件解析失败已改名保留现场: %s → %s（原因：%s）",
                path, corrupt, primary_err)
        except OSError:
            logger.error("[registry] 配置文件解析失败且无法改名保留现场: %s（原因：%s）",
                         path, primary_err)
        if bak.exists():
            try:
                data = _read_yaml_file(bak)
                logger.error(
                    "[registry] 已回退到上次好配置 %s（当前配置损坏，"
                    "找回最新内容请查看 %s）", bak, corrupt)
                return data
            except Exception as bak_err:
                logger.error("[registry] 备份配置 %s 也无法解析: %s", bak, bak_err)
        raise RuntimeError(
            f"配置文件 {path} 损坏且无可用备份（{bak}），拒绝以空配置启动。"
            f"坏文件已保留在 {corrupt}，请修复后重启；"
            "密钥全消失优于静默空跑。") from primary_err


def raw_config() -> dict:
    """读配置文件（不做任何归一化，写盘前用这个）。"""
    cfg: dict[str, Any] = {}
    f = config_path()
    if f.exists():
        cfg = _load_yaml_with_bak(f, BASE / "data" / "config.local.yaml.bak")
    local = BASE / "data" / "config.local.yaml"
    if local.exists():
        local_cfg = _load_yaml_with_bak(local, BASE / "data" / "config.local.yaml.bak")
        for k, v in local_cfg.items():
            # 覆盖层是**整段快照**（write_config 每次写的是完整配置），
            # 所以这里整段替换而不是逐键合并：逐键合并会让主配置里
            # 已被清理掉的旧字段（如 gateway.base_url）在每次读取时
            # 又冒回来，normalize 于是永远「不干净」，回写也不再幂等。
            cfg[k] = v
    return cfg if isinstance(cfg, dict) else {}


def write_config(cfg: dict) -> bool:
    """把归一化后的配置落盘；失败不抛异常，返回 False。

    v15.9.8：写盘前先把**当前**配置原子复制一份到 ``<target>.bak``——
    一旦新写入的内容有问题（半截盘/坏 YAML），raw_config 下次读取能回退到
    这份上次好配置，而不是静默空配置（见 _load_yaml_with_bak）。
    """
    target = writable_config_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # ① 写前备份当前好配置（原子：tmp 写完再 replace）
        if target.exists():
            bak = target.with_suffix(target.suffix + ".bak")
            try:
                bak_tmp = bak.with_suffix(bak.suffix + ".tmp")
                bak_tmp.write_bytes(target.read_bytes())
                bak_tmp.replace(bak)
            except OSError as e:
                # 备份失败不阻断写入（好配置仍在 target 上），但要留痕
                logger.error("[registry] 写前备份 %s 失败：%s", bak, e)
        # ② 原子替换主文件
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


def _deleted_set(gw: dict) -> set[str]:
    """已删除（拉黑）的供应商 ID 集合；脏数据一律忽略。"""
    return {str(p).strip() for p in (gw.get("deleted_providers") or []) if str(p).strip()}


def _pick_replacement(pool: dict, deleted: set[str]) -> str:
    """活动通道被删后挑替补：优先「有地址的」，其次任意未删的，都没有就返回空串。

    为什么不能返回 ``"deepseek"``：那会把刚被用户删掉的通道原地复活——
    用户删完刷新，列表里又冒出一家空的 DeepSeek，看起来就是「删不掉」。
    """
    live = [pid for pid in pool.keys() if pid not in deleted]
    for pid in live:
        entry = pool.get(pid)
        if isinstance(entry, dict) and str(entry.get("base_url") or "").strip():
            return pid
    return live[0] if live else ""


def normalize(cfg: dict, *, presets: dict | None = None) -> tuple[dict, bool]:
    """把配置折叠成单一真源，返回 ``(cfg, 是否需要回写)``。

    1. 旧版把活动通道的 base_url/model 同时写在 ``gateway`` 顶层与
       ``providers[active]``。以 **providers 池为准**折叠（池是用户最近一次
       保存的地方，也是 UI 展示的地方）；池里没有时用顶层值补进池。
    2. 折叠后删除顶层冗余字段，之后 ``gateway`` 只保留 ``provider_id``
       与供应商池，其余字段由 :func:`derive_view` 现算。
    3. **已删除的通道不得再被选为活动通道**（v15.9.5）：旧实现在这里无条件
       ``active = provider_id or "deepseek"``，活动通道一被删就又把它补回池里，
       于是「删掉 DeepSeek → 刷新又出现一家空 DeepSeek」。
    """
    gw = cfg.get("gateway")
    if not isinstance(gw, dict):
        gw = {}
        cfg["gateway"] = gw
    pool = _pool(gw)
    deleted = _deleted_set(gw)

    # 被删掉的通道不该继续占着池子（旧版本残留的空条目会让人误以为「删了还在」）
    stale = [p for p in list(pool.keys()) if p in deleted]
    for pid in stale:
        pool.pop(pid, None)

    want = str(gw.get("provider_id") or "").strip()
    active = want
    if active and active in deleted:
        active = _pick_replacement(pool, deleted)
    elif not active:
        # 没有指定主通道时，从池里挑一家还在的；池空则保持空（不再硬塞 deepseek）
        active = _pick_replacement(pool, deleted)
    if active != want:
        gw["provider_id"] = active
    dirty = bool(stale) or active != want

    # 能力默认指向已删通道时一并清理，否则「删了还在被调用」会从文字线蔓延到生图/生视频。
    caps = gw.get("capability_defaults")
    if isinstance(caps, dict):
        for cat in list(caps.keys()):
            entry = caps.get(cat)
            pid = ""
            if isinstance(entry, dict):
                pid = str(entry.get("provider_id") or "").strip()
            elif isinstance(entry, str):
                pid = entry.strip()
            if not pid or pid in deleted or cat not in CAPABILITY_CATEGORIES:
                caps.pop(cat, None)
                dirty = True
        if not caps:
            gw.pop("capability_defaults", None)
            dirty = True

    entry = pool.get(active) if active else None
    if active and not isinstance(entry, dict):
        entry = {}
        pool[active] = entry
        dirty = True

    # 顶层旧字段 -> 池（仅当池里缺该字段时才搬，避免覆盖用户最近保存的值）
    if active:
        for field in DERIVED_FIELDS:
            legacy = gw.get(field)
            if legacy in (None, "", [], {}):
                continue
            if entry.get(field) in (None, "", [], {}):
                entry[field] = legacy
                dirty = True

    # 预设兜底：池里连 base_url 都没有时，用内置预设补齐（不落盘，只在视图里补）
    if active and presets:
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
    一家供应商都没有时（用户把它们全删了）派生值一律为空，让上游给出
    明确的「尚未配置」提示，而不是偷偷用某个已被删掉的通道的出厂地址。
    """
    gw = cfg.get("gateway")
    if not isinstance(gw, dict):
        return cfg
    pool = gw.get("providers") if isinstance(gw.get("providers"), dict) else {}
    active = str(gw.get("provider_id") or "").strip()
    entry = pool.get(active) if active and isinstance(pool.get(active), dict) else {}
    preset = ((presets or {}).get(active) or {}) if active else {}

    gw["provider_id"] = active
    gw["base_url"] = str(entry.get("base_url") or preset.get("base_url") or "").rstrip("/")
    gw["model"] = entry.get("model") or preset.get("default_model") or ""

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
    """当前活动供应商；一家都没配置时返回空串（不再假报 deepseek）。"""
    cfg = cfg if cfg is not None else raw_config()
    gw = cfg.get("gateway") or {}
    return str(gw.get("provider_id") or "").strip()


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
    gw = cfg.setdefault("gateway", {})
    # 已删除的通道不许被激活（否则列表里没有它，调用却还在用它）
    if pid in _deleted_set(gw):
        logger.warning("[registry] 拒绝把已删除的通道 %s 设为主通道", pid)
        return False
    gw["provider_id"] = pid
    return write_config(cfg)


def _capability_entry(raw: Any) -> dict:
    """把 capability_defaults 的一项规整为 ``{"provider_id": str, "model": str}``。"""
    if isinstance(raw, str):
        return {"provider_id": raw.strip(), "model": ""}
    if isinstance(raw, dict):
        return {
            "provider_id": str(raw.get("provider_id") or "").strip(),
            "model": str(raw.get("model") or "").strip(),
        }
    return {"provider_id": "", "model": ""}


def capability_defaults(cfg: dict | None = None) -> dict[str, dict]:
    """读取三条能力线的显式默认（未设置的能力不出现在结果里）。

    结构：``gateway.capability_defaults.{text|image|video} = {provider_id, model}``。
    ``provider_id`` 为空表示「自动」——由解析器在全部已配置通道里挑第一个
    该类别的可用模型，不再默认绑死文字主通道。
    """
    cfg = cfg if cfg is not None else raw_config()
    raw = ((cfg.get("gateway") or {}).get("capability_defaults") or {})
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for cat in CAPABILITY_CATEGORIES:
        entry = _capability_entry(raw.get(cat))
        if entry["provider_id"]:
            out[cat] = entry
    return out


def set_capability_default(category: str, provider_id: str, model: str = "") -> bool:
    """设置某条能力线的默认通道；``provider_id`` 为空 = 改回「自动」。

    文字线是例外：它同时写回 ``gateway.provider_id``，保持「主通道」这个老字段
    与新能力线是同一个事实，而不是两份可能分叉的默认值。
    """
    cat = (category or "").strip().lower()
    if cat not in CAPABILITY_CATEGORIES:
        return False
    pid = (provider_id or "").strip()
    model = (model or "").strip()
    cfg = raw_config()
    cfg, _ = normalize(cfg)
    gw = cfg.setdefault("gateway", {})
    pool = _pool(gw)

    if pid and pid in _deleted_set(gw):
        logger.warning("[registry] 拒绝把已删除的通道 %s 设为能力默认", pid)
        return False
    if pid and pid not in pool:
        # 允许「预设里存在但尚未落池」的通道（用户刚选官方预设还没保存）；
        # 真要落一个不存在的 ID，解析器也只会返回空，不如在这里明确拒绝。
        try:
            from core.llm import MODEL_PROVIDERS as _presets
        except Exception:  # noqa: BLE001
            _presets = {}
        if pid not in (_presets or {}):
            logger.warning("[registry] 未知通道 %s，拒绝设为能力默认", pid)
            return False

    if cat == "text":
        caps = gw.get("capability_defaults")
        if isinstance(caps, dict):
            caps.pop("text", None)
            if not caps:
                gw.pop("capability_defaults", None)
        if pid:
            gw["provider_id"] = pid
            if model:
                pool.setdefault(pid, {})["model"] = model
        return write_config(cfg)

    caps = gw.setdefault("capability_defaults", {})
    if not pid:
        caps.pop(cat, None)
    else:
        caps[cat] = {"provider_id": pid, "model": model}
    if not caps:
        gw.pop("capability_defaults", None)
    return write_config(cfg)


def clear_capability_default(category: str) -> bool:
    """清除某条能力线的显式默认，回到「自动跨通道选择」。"""
    return set_capability_default(category, "", "")


def delete_provider(pid: str) -> bool:
    """删除一家供应商：池里有就清池，没有就只拉黑。

    V15.9.5 客户缺陷：旧实现第一步是 ``if pid not in pool: return False``。
    内置预设（OpenAI / Claude / Gemini / 智谱 …）只要用户没保存过，就不在池里，
    于是点删除**毫无反应**——用户删掉 7 家能删的，剩下 7 家怎么点都还在。
    「所有必须全部都能删除」的要求下，删除语义改为：

    1. 在池里：清掉该条目，同时拉黑（防止 ``normalize`` 的预设兜底又把它补回来）；
    2. 不在池里：只拉黑——对内置预设同样生效，列表随即不再显示；
    3. 既不在池里、又已在黑名单：才算「无事可做」，返回 False。

    活动通道被删时立刻挑一个未删的替补（没有就置空），不再沿用已删地址。
    """
    pid = (pid or "").strip()
    if not pid:
        return False
    cfg = raw_config()
    cfg, _ = normalize(cfg)
    gw = cfg.setdefault("gateway", {})
    pool = _pool(gw)
    deleted = _deleted_set(gw)

    in_pool = pid in pool
    if not in_pool and pid in deleted:
        return False

    if in_pool:
        pool.pop(pid, None)
    deleted.add(pid)
    gw["deleted_providers"] = sorted(deleted)

    if str(gw.get("provider_id") or "") == pid:
        # 活动通道被删：换一家还在的；一家都不剩就置空，
        # 让解析器明确报「尚未配置」，而不是继续打已删地址。
        gw["provider_id"] = _pick_replacement(pool, deleted)

    # 生图/生视频默认若指向这家，一并清掉并回落到「自动」。
    # 只清指针不动其它通道——用户删的是一家，不是整条能力线。
    caps = gw.get("capability_defaults")
    if isinstance(caps, dict):
        for cat in list(caps.keys()):
            if _capability_entry(caps.get(cat)).get("provider_id") == pid:
                caps.pop(cat, None)
        if not caps:
            gw.pop("capability_defaults", None)
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


def key_persisted(pid: str) -> bool:
    """该通道的 Key 是否**真的落盘**到用户配置文件（不看进程内存态）。

    用于「保存成功」的诚实回报：只写进 ``os.environ`` 但没落盘的话，
    重启后就丢了，用户会以为配置没生效。
    """
    from core.user_paths import read_env_file, secrets_env_path
    vals = read_env_file(secrets_env_path())
    return bool(str(vals.get(f"MEDIAFLOW_KEY_{pid.upper()}") or "").strip())


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
