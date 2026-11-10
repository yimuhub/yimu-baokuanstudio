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


def read_env_file(path: Path) -> dict[str, str]:
    """解析 dotenv 文件；读取失败返回空字典，绝不抛异常。"""
    out: dict[str, str] = {}
    try:
        if not path.is_file():
            return out
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    except OSError:
        return {}
    return out


def write_env_file(path: Path, values: dict[str, str]) -> bool:
    """写入 dotenv 并收紧到 0600；返回是否成功。"""
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
        return True
    except OSError:
        return False


def merge_env(install_env: Path, *, environ: dict | None = None) -> dict[str, str]:
    """配置合并真源：进程环境变量 > 用户 secrets.env > 安装目录 .env。"""
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
    return len(moved)
