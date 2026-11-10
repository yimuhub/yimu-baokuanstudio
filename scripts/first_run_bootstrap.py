# SPDX-License-Identifier: BUSL-1.1
"""全功能离线分发包的首次启动自举（First-run bootstrap）。

设计约束
--------
1. **只用标准库**：本模块在 ``desktop.py`` 最开头执行，此时 ``runtime/site-packages``
   还没进 ``sys.path``，任何第三方 import 都会直接失败。
2. **绝不覆盖用户配置**：用户后来在设置页填的自定义 API Key、管理员口令、配额数据
   一律原样保留；本模块只补缺失项。
3. **全程离线**：官方凭证只在**构建期**由 CI 从 Secrets 注入为结构化文件
   ``app/.bootstrap/official_credential.json``；客户机启动时不发任何网络请求，
   也不再向官方网关申领设备试用凭证。没有随包凭证时服务照常启动，
   界面给出明确的配置引导。

bundle 布局（由 scripts/build_full_bundle.py 生成）::

    YIMU-Studio/
      app/            <- 全部源码，BASE = app/
        core/ studio/ web/ ... config.yaml .env
        data/         <- 用户数据 / 出厂配额
      runtime/        <- 自带 Python + site-packages（全量依赖）
      chromium/       <- 内置 Chrome for Testing
      一幕桌面客户端.*
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import user_paths  # noqa: E402  —— 纯标准库，启动期可安全导入

APP = Path(__file__).resolve().parent.parent
BUNDLE = APP.parent
RUNTIME_SITE = BUNDLE / "runtime" / "site-packages"
CHROMIUM_MARKER = BUNDLE / "chromium" / "EXECUTABLE"
DATA = APP / "data"
ENV_PATH = APP / ".env"

#: 出厂赠送额度。不复制开发机上的 billing.json（那里面是 999999 和测试用户记录）。
FACTORY_TRIAL_CREDITS = 200000
#: 随包官方凭证（构建期由 scripts/build_full_bundle.py 生成，仓库里绝不存明文）。
CREDENTIAL_FILE = ".bootstrap/official_credential.json"
#: 记录上一次自举所属的包标识，用于「全新版本升级后重新生成配额」。
FACTORY_STATE_FILE = "factory_state.json"
_PLACEHOLDERS = {"", "test_key", "test", "your-api-key", "your_api_key", "sk-xxx", "xxx", "changeme", "placeholder"}


def ensure_dir(p: Path) -> None:
    if not p.is_dir():
        p.mkdir(parents=True)


def _log(msg: str) -> None:
    print(f"[首次启动] {msg}", flush=True)


def write_boot_log(summary: dict) -> None:
    """出厂即建日志目录，并在启动时立即写入带时间戳的版本 / 路径记录（6.6）。"""
    try:
        try:
            import version
            ver = version.__version__
        except Exception:
            ver = "unknown"
        entry = json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "version": ver,
            "platform": sys.platform,
            "app_dir": str(APP),
            "bundle_dir": str(BUNDLE),
            "secrets_file": str(user_paths.secrets_env_path()),
            **summary,
        }, ensure_ascii=False)
        for p in (APP / "logs" / "bootstrap.log", DATA / "logs" / "bootstrap.log"):
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except OSError:
                continue
    except Exception:
        pass


def activate_runtime() -> bool:
    """把自带解释器与预装依赖挂进当前进程。

    开发模式（仓库根目录直接跑）没有 ``runtime/``，直接返回 False，
    desktop.py 继续用原来的环境，行为完全不变。
    """
    if not RUNTIME_SITE.is_dir():
        return False
    p = str(RUNTIME_SITE)
    if p not in sys.path:
        sys.path.insert(0, p)
    os.environ.setdefault("YIMU_BUNDLE_ROOT", str(BUNDLE))
    os.environ.setdefault("YIMU_RUNTIME_MODE", "bundled")
    if CHROMIUM_MARKER.is_file():
        try:
            rel = CHROMIUM_MARKER.read_text(encoding="utf-8").strip()
            exe = (BUNDLE / "chromium" / rel).resolve()
            if exe.is_file():
                os.environ.setdefault("YIMU_CHROMIUM_PATH", str(exe))
        except Exception:
            pass
    return True


def _read_env() -> dict:
    """安装目录 .env + 用户目录 secrets.env + 进程环境变量。"""
    return user_paths.merge_env(ENV_PATH)


def _write_env(values: dict) -> None:
    """只补缺失项；敏感项写入用户目录 secrets.env（0600），安装目录不留明文。"""
    env = _read_env()
    changed = False
    for k, v in values.items():
        if not env.get(k):
            env[k] = v
            changed = True
    if not changed:
        return

    secret_path = user_paths.secrets_env_path()
    secrets_map = user_paths.read_env_file(secret_path)
    for k, v in env.items():
        if user_paths.is_sensitive(k):
            secrets_map.setdefault(k, v)
    secrets_written = user_paths.write_env_file(secret_path, secrets_map)

    # 用户目录不可写时回退到安装目录，绝不丢密钥
    plain = {k: v for k, v in env.items()
             if not user_paths.is_sensitive(k) or not secrets_written}
    lines = [
        "# 一幕·YIMU 爆款工作室 本地配置（首次启动自动生成，可手动修改）",
        "# 密钥与管理员口令已迁至用户数据目录 secrets.env（0600），本文件不再存放明文。",
        "# 在「设置 → 模型服务」里填入自己的 API Key 后，官方通道会被自动覆盖。",
    ]
    lines.extend(f"{k}={v}" for k, v in plain.items())
    try:
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(ENV_PATH, 0o600)
    except OSError as e:
        _log(f"本地配置写入跳过: {e}")


def read_official_credential() -> dict:
    """读取构建期随包注入的结构化官方凭证；不存在/损坏时返回空字典。

    该文件由 ``scripts/build_full_bundle.py`` 生成，内含 key、bundle_id、
    版本、签发时间与出厂额度。仓库里绝不存放可扣费的真实 Key。
    """
    p = APP / CREDENTIAL_FILE
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != 1:
        return {}
    key = str(data.get("key") or "").strip()
    if not key or key.lower() in _PLACEHOLDERS:
        return {}
    return data


def read_bundle_id() -> str:
    """从包根 MANIFEST.json 读取本次构建的包标识（用于升级后重新生成配额）。"""
    try:
        m = json.loads((BUNDLE / "MANIFEST.json").read_text(encoding="utf-8") or "{}")
        return str(m.get("bundle_id") or "") if isinstance(m, dict) else ""
    except (OSError, ValueError):
        return ""


def resolve_official_key() -> tuple[str, str]:
    """按优先级解析内置官方凭证，返回 ``(key, source)``；**全程不联网**。

    1. 随包结构化凭证 ``app/.bootstrap/official_credential.json`` → ``bundle``；
    2. 进程环境变量 ``YIMU_OFFICIAL_BOOTSTRAP_KEY``（开发/自测用）→ ``env``；
    3. 都没有 → ``unset``，服务照常启动，界面提示管理员配置官方凭证或用户填自备 Key。

    ⭐ V15.8.1：移除了运行期的设备试用凭证联网申领。客户机首次启动
    不再依赖官方网关在线，也不会因断网多等 6 秒；是否提供官方通道完全由构建期决定。
    """
    packed = read_official_credential()
    if packed:
        return str(packed["key"]).strip(), "bundle"
    k = os.environ.get("YIMU_OFFICIAL_BOOTSTRAP_KEY", "").strip()
    if k and k.lower() not in _PLACEHOLDERS:
        return k, "env"
    return "", "unset"


def reset_factory_quota(bundle_id: str = "") -> bool:
    """生成/刷新出厂配额，返回「是否因全新版本包而重新生成」。

    - 首次安装：文件缺失 → 写入一份不含开发机余额与测试记录的干净配额；
    - 升级到全新构建（``bundle_id`` 变化）：免费体验次数与 LLM 用量计数清零，
      赠送额度补足到 ``FACTORY_TRIAL_CREDITS``；
      **用户的草稿、话题、兑换码、消费历史、自定义 Key、管理员口令一律不动**，
      引导完成标记 ``user_onboarding_done.json`` 也不重置（不反复弹 Wizard）。
    """
    ensure_dir(DATA)
    for sub in ("topics", "drafts", "cards", "logs", "runs"):
        ensure_dir(DATA / sub)
    ensure_dir(APP / "logs")
    ensure_dir(APP / "runs")

    factory = {
        "billing.json": {
            "tier": "free",
            "balance": FACTORY_TRIAL_CREDITS,
            "total_consumed": 0,
            "history": [],
            "cdkeys": {},
        },
        "free_demo_calls.json": {},
        "llm_usage.json": {},
        "user_onboarding_done.json": {},
    }
    for name, value in factory.items():
        p = DATA / name
        if not p.exists():
            p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_path = DATA / FACTORY_STATE_FILE
    try:
        prev = json.loads(state_path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        prev = {}
    if not isinstance(prev, dict):
        prev = {}
    old_id = str(prev.get("bundle_id") or "")
    regenerated = bool(bundle_id and old_id and old_id != bundle_id)
    if regenerated:
        for name in ("free_demo_calls.json", "llm_usage.json"):
            (DATA / name).write_text("{}\n", encoding="utf-8")
        bp = DATA / "billing.json"
        try:
            b = json.loads(bp.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            b = {}
        if isinstance(b, dict):
            try:
                cur = float(b.get("balance") or 0)
            except (TypeError, ValueError):
                cur = 0.0
            b["balance"] = max(cur, float(FACTORY_TRIAL_CREDITS))
            bp.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _log(f"检测到全新版本包（{old_id} → {bundle_id}），出厂额度与体验次数已重新生成")
    if bundle_id and old_id != bundle_id:
        try:
            state_path.write_text(json.dumps({
                "bundle_id": bundle_id,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "factory_credits": FACTORY_TRIAL_CREDITS,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            _log(f"包标识记录写入跳过: {e}")

    db = DATA / "mediaflow.db"
    if not db.exists():
        try:
            sqlite3.connect(str(db)).close()
        except Exception as e:
            _log(f"数据库占位创建跳过: {e}")
    return regenerated


def bootstrap() -> dict:
    """桌面启动器在任何第三方 import 之前调用一次。返回自检摘要（供 CI 离线冒烟读取）。"""
    started = time.time()
    bundled = activate_runtime()
    bundle_id = read_bundle_id()
    quota_regenerated = reset_factory_quota(bundle_id)
    # 旧版本把密钥明文写在随包分发的 .env 里；升级时自动迁出到用户目录。
    migrated = user_paths.migrate_legacy_secrets(ENV_PATH)
    env = _read_env()

    # 用户已经在设置页填过自己的 Key → 一个字节都不动
    user_key = env.get("MEDIAFLOW_KEY_YIMU_OFFICIAL") or env.get("MEDIAFLOW_APIPOOL_KEY") or ""
    key_source = "user" if user_key.strip().lower() not in _PLACEHOLDERS else ""
    seed: dict = {
        "YIMU_SECRET_KEY": secrets.token_urlsafe(32),
        "ADMIN_PASSWORD": secrets.token_urlsafe(16),
        "YIMU_DB_URL": "sqlite:///./data/mediaflow.db",
    }
    if not key_source:
        key, source = resolve_official_key()
        if key:
            seed["MEDIAFLOW_KEY_YIMU_OFFICIAL"] = key
            seed["MEDIAFLOW_APIPOOL_KEY"] = key
            key_source = source
    _write_env(seed)

    summary = {
        "bundled_runtime": bundled,
        "site_packages": str(RUNTIME_SITE),
        "chromium": os.environ.get("YIMU_CHROMIUM_PATH", ""),
        "official_key_source": key_source,
        "official_credential_present": bool(read_official_credential()),
        "bundle_id": bundle_id,
        "quota_regenerated": quota_regenerated,
        "factory_credits": FACTORY_TRIAL_CREDITS,
        "data_dir": str(DATA),
        "secrets_file": str(user_paths.secrets_env_path()),
        "migrated_secrets": migrated,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
    write_boot_log(summary)
    if bundled:
        if key_source in ("bundle", "env", "user"):
            _log(f"自带运行时已激活 · 官方通道: {key_source}")
        else:
            _log("自带运行时已激活 · 官方凭证未随包提供："
                 "请管理员在构建期配置 YIMU_OFFICIAL_BOOTSTRAP_KEY，"
                 "或在「设置 → 模型服务」填入自己的 API Key（客户端不联网申领）")
    return summary


if __name__ == "__main__":
    print(json.dumps(bootstrap(), ensure_ascii=False, indent=2))
