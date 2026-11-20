# SPDX-License-Identifier: BUSL-1.1
"""跨平台用户数据目录与敏感配置落点（纯标准库，启动期可安全 import）。

背景（客户缺陷报告 F5 / R9）
--------------------------
离线分发版把 ``YIMU_SECRET_KEY`` 与 ``ADMIN_PASSWORD`` 明文写在安装目录
``app/.env`` 里，任何能读到安装目录的人都能直接取得管理口令。

修复策略
--------
1. 敏感项统一写入**用户目录** ``secrets.env``（0600），安装目录的 ``.env``
   只保留非敏感配置；
2. ``load_env()`` 合并顺序：进程环境变量 > 用户 secrets.env > 安装目录 .env，
   旧版本升级上来仍能读到原来的配置；
3. 首次启动自动把旧 ``.env`` 里的敏感项迁出，安装目录不再残留明文。

平台落点：
  Windows  ``%LOCALAPPDATA%\\YIMU-Studio``
  macOS    ``~/Library/Application Support/YIMU-Studio``
  Linux    ``$XDG_DATA_HOME/yimu-studio``（默认 ``~/.local/share/yimu-studio``）
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

#: 明确属于敏感项的环境键。
SENSITIVE_KEYS = frozenset({
    "YIMU_SECRET_KEY",
    "YIMU_ADMIN_SESSION_SECRET",
    "ADMIN_PASSWORD",
    "YIMU_ADMIN_PASSWORD",
    "GITHUB_IMGBED_TOKEN",
    "TENANT_SECRET",
})

#: 前缀匹配的敏感项（用户自备 API Key、官方通道凭证等）。
SENSITIVE_PREFIXES = ("MEDIAFLOW_KEY_", "MEDIAFLOW_APIPOOL_KEY", "YIMU_OFFICIAL_")


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "YIMU-Studio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "YIMU-Studio"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "yimu-studio"


def secrets_env_path() -> Path:
    return user_data_dir() / "secrets.env"


def is_sensitive(key: str) -> bool:
    k = (key or "").strip().upper()
    return k in SENSITIVE_KEYS or k.startswith(SENSITIVE_PREFIXES)


# ---------------------------------------------------------------------------
# ⭐ 进程内 env 文件缓存（v15.9.9 效率整改）
#
# why：merge_env 每次调用要读安装目录 .env + 用户 secrets.env 两个文件，而
# web 管理端鉴权（_admin_password）每个请求都走 merge_env——热路径上每请求
# 2 次磁盘 IO 纯属浪费。缓存以 (mtime_ns, size) 为指纹：文件未变直接回缓存；
# 写路径（write_env_file / migrate_legacy_secrets）主动失效对应条目。
# 返回值始终是副本，调用方改写返回 dict 不会污染缓存。
# ---------------------------------------------------------------------------
_ENV_FILE_CACHE: dict[str, tuple[tuple[int, int] | None, dict[str, str]]] = {}
_ENV_CACHE_LOCK = threading.Lock()


def _env_file_sig(path: Path) -> tuple[int, int] | None:
    """文件指纹：(mtime_ns, size)；文件不存在返回 None（同样是可缓存状态）。"""
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _invalidate_env_cache(path: Path) -> None:
    """写路径主动失效对应缓存条目（防同指纹下被外部原地改写的极端情况）。"""
    with _ENV_CACHE_LOCK:
        _ENV_FILE_CACHE.pop(str(path), None)


def read_env_file(path: Path) -> dict[str, str]:
    """解析 dotenv 文件；读取失败返回空字典，绝不抛异常。

    命中缓存条件：指纹与上次一致（含「文件不存在 → None」）。
    """
    key = str(path)
    sig = _env_file_sig(path)
    with _ENV_CACHE_LOCK:
        cached = _ENV_FILE_CACHE.get(key)
        if cached is not None and cached[0] == sig:
            return dict(cached[1])
    out: dict[str, str] = {}
    try:
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        return {}
    with _ENV_CACHE_LOCK:
        _ENV_FILE_CACHE[key] = (sig, dict(out))
    return out


def write_env_file(path: Path, values: dict[str, str]) -> bool:
    """写入 dotenv 并收紧到 0600；返回是否成功。写成功后主动失效缓存。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"{k}={v}" for k, v in values.items() if v) + "\n"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        _invalidate_env_cache(path)  # 写后失效：下一次读强制重解析
        return True
    except OSError:
        return False


def merge_env(install_env: Path, *, environ: dict | None = None) -> dict[str, str]:
    """配置合并真源：进程环境变量 > 用户 secrets.env > 安装目录 .env。

    两个 env 文件的读取走 read_env_file 的进程内 mtime 缓存（web 鉴权
    每请求都到这里），文件未变时不再重复磁盘 IO。
    """
    base = dict(environ if environ is not None else os.environ)
    explicit = set(base)
    file_vals = read_env_file(install_env)
    file_vals.update(read_env_file(secrets_env_path()))
    for k, v in file_vals.items():
        if k not in explicit:
            base[k] = v
    return base


def migrate_legacy_secrets(install_env: Path) -> int:
    """把旧 .env 中的敏感项搬到用户 secrets.env，并从安装目录移除明文。

    Returns: 迁移的键数量。
    """
    if not install_env.is_file():
        return 0
    try:
        lines = install_env.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return 0
    moved: dict[str, str] = {}
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, v = stripped.split("=", 1)
            if is_sensitive(k.strip()) and v.strip():
                moved[k.strip()] = v.strip()
                continue
        kept.append(line)
    if not moved:
        return 0
    secrets = read_env_file(secrets_env_path())
    for k, v in moved.items():
        secrets.setdefault(k, v)
    if not write_env_file(secrets_env_path(), secrets):
        return 0  # 用户目录不可写时保留原文件，绝不丢密钥
    try:
        install_env.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8")
        os.chmod(install_env, 0o600)
    except OSError:
        pass
    _invalidate_env_cache(install_env)  # 本函数绕过 write_env_file 直写安装目录 .env，需手动失效
    return len(moved)
