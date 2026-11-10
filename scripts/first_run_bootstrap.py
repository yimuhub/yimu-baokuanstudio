# SPDX-License-Identifier: BUSL-1.1
"""全功能离线分发包的首次启动自举（First-run bootstrap）。

设计约束
--------
1. **只用标准库**：本模块在 ``desktop.py`` 最开头执行，此时 ``runtime/site-packages``
   还没进 ``sys.path``，任何第三方 import 都会直接失败。
2. **绝不覆盖用户配置**：用户后来在设置页填的自定义 API Key、管理员口令、配额数据
   一律原样保留；本模块只补缺失项。
3. **断网可运行**：官方凭证的联网申领是「尽力而为」，超时或失败静默降级，
   不影响服务启动；用户随时可以在设置页填自己的 Key。

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

import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time
import urllib.request
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

OFFICIAL_GATEWAY = "https://gateway.yimu.studio/v1"
#: 出厂赠送额度。不复制开发机上的 billing.json（那里面是 999999 和测试用户记录）。
FACTORY_TRIAL_CREDITS = 200000
#: 官方试用凭证申领超时（秒）。断网时最多耽误这么久，且只在首次启动发生一次。
CLAIM_TIMEOUT = 6.0
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


def _machine_id() -> str:
    """稳定的匿名设备指纹，仅用于官方试用额度去重，不含任何个人信息。"""
    import platform
    import uuid
    raw = f"{platform.node()}|{uuid.getnode()}|{platform.system()}|{platform.machine()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def resolve_official_key() -> tuple[str, str]:
    """按优先级解析内置官方凭证，返回 ``(key, source)``。

    1. 构建期随包注入的凭证（GitHub Secrets → ``app/.bootstrap/official_key``）；
    2. 进程环境变量 ``YIMU_OFFICIAL_BOOTSTRAP_KEY``；
    3. 官方网关按设备签发的试用凭证（联网尽力而为）；
    4. 都没有 → 返回空串，服务照常启动，界面提示可在设置页填自己的 Key。

    注意：仓库里**绝不**明文存放可扣费的真实 Key。正式发行版由 CI 从 Secrets 注入。
    """
    packed = APP / ".bootstrap" / "official_key"
    if packed.is_file():
        k = packed.read_text(encoding="utf-8", errors="ignore").strip()
        if k and k.lower() not in _PLACEHOLDERS:
            return k, "bundle"
    k = os.environ.get("YIMU_OFFICIAL_BOOTSTRAP_KEY", "").strip()
    if k and k.lower() not in _PLACEHOLDERS:
        return k, "env"
    if os.environ.get("YIMU_SKIP_TRIAL_CLAIM") == "1":
        return "", "none"
    try:
        req = urllib.request.Request(
            OFFICIAL_GATEWAY.rstrip("/") + "/trial/claim",
            data=json.dumps({
                "machine_id": _machine_id(),
                "product": "yimu-studio",
                "channel": "desktop-offline",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=CLAIM_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
        claimed = str(payload.get("api_key") or payload.get("key") or "").strip()
        if claimed and claimed.lower() not in _PLACEHOLDERS:
            return claimed, "trial"
    except Exception:
        pass
    return "", "none"


def reset_factory_quota() -> None:
    """生成一份全新的出厂配额，不携带开发机的余额、消费记录和测试用户。

    只在文件缺失时写入，用户使用过程中产生的数据永远不会被重置。
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

    db = DATA / "mediaflow.db"
    if not db.exists():
        try:
            sqlite3.connect(str(db)).close()
        except Exception as e:
            _log(f"数据库占位创建跳过: {e}")


def bootstrap() -> dict:
    """桌面启动器在任何第三方 import 之前调用一次。返回自检摘要（供 CI 离线冒烟读取）。"""
    started = time.time()
    bundled = activate_runtime()
    reset_factory_quota()
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
        "factory_credits": FACTORY_TRIAL_CREDITS,
        "data_dir": str(DATA),
        "secrets_file": str(user_paths.secrets_env_path()),
        "migrated_secrets": migrated,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
    write_boot_log(summary)
    if bundled:
        _log(f"自带运行时已激活 · 官方通道: {key_source or '待激活（可在设置页填自定义 Key）'}")
    return summary


if __name__ == "__main__":
    print(json.dumps(bootstrap(), ensure_ascii=False, indent=2))
