# SPDX-License-Identifier: BUSL-1.1
"""进程间稳定的本地密钥存储（会话签名 / API Key Vault 同源）。

问题
----
历史上 `web/admin.py` 的管理会话密钥与 `core/auth.py` 的签名密钥都是
**进程启动时随机生成**（`secrets.token_hex(32)`）。带来三个真实故障：

1. 每次重启 / 升级，全员登录态失效（Cookie 验签失败）——用户以为是 bug；
2. 一旦 `uvicorn --workers 2`，A worker 签发的 Cookie 到 B worker 就是 401，
   服务端**无法水平扩容**；
3. API Key Vault 的加密密钥与签名密钥同源，重启后已存的自备 Key 解不开
   （`decrypt_key` 抛错 → 用户看到「Key 无效」，实际是密钥换了）。

方案
----
密钥落盘到 `data/.secrets/<name>`（0600 权限，目录已被 .gitignore 的
`data/*` 覆盖），首次生成后**所有进程、所有重启共用同一份**。
优先级：环境变量 `YIMU_<NAME>` > 磁盘文件 > 进程内随机（只读文件系统兜底）。

⚠️ 明确不做的事：不把密钥写进 `config.yaml`（会随仓库分发）、
   不写进 `os.environ`（污染子进程）、不打日志。
"""
from __future__ import annotations

import os
import logging
import secrets
from pathlib import Path

logger = logging.getLogger("yimu.secret")

BASE = Path(__file__).resolve().parent.parent
SECRET_DIR = BASE / "data" / ".secrets"

#: 磁盘不可写时的兜底（与历史行为一致：本次进程内有效）
_FALLBACK = secrets.token_hex(32)

#: 生成的最小长度，短于此视为文件损坏并重新生成
_MIN_LEN = 32

#: 已提示过的弱密钥环境变量名（避免每次取密钥都刷日志）
_WARNED_WEAK: set[str] = set()


def _warn_weak_env(env_var: str, value: str) -> None:
    """环境变量密钥过短时提示一次。只警告，不覆盖——那是运维的显式选择。"""
    if len(value) >= _MIN_LEN or env_var in _WARNED_WEAK:
        return
    _WARNED_WEAK.add(env_var)
    logger.warning(
        "%s 只有 %d 个字符，低于建议的 %d；生产环境请换成 `openssl rand -hex 32` 的随机值。",
        env_var, len(value), _MIN_LEN,
    )


def _read(path: Path) -> str:
    try:
        val = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    return val if len(val) >= _MIN_LEN else ""


def _write_exclusive(path: Path, value: str) -> bool:
    """原子创建（O_EXCL）：并发启动的多个 worker 只有一个能写成。

    Returns: True 表示本次写入成功；False 表示已被别的进程抢先生成。
    """
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError:
        return False
    return True


def get_secret(name: str, *, env_var: str = "") -> str:
    """取（或首次生成）名为 ``name`` 的持久密钥。

    Args:
        name: 文件名，如 ``"session"``、``"admin_session"``。
        env_var: 可选的环境变量名；配置了则**优先生效**（便于容器化部署
                 注入同一份密钥，而不依赖持久卷）。

    ⚠️ 环境变量只要非空就采纳，**不设长度下限**。
       原因：`studio/auth.py` 也是「非空即用」，两处口径必须完全一致。
       历史故障：本函数曾要求环境变量 ≥32 字符，而测试/自建部署里
       `YIMU_SECRET_KEY=test-secret-xxx` 只有十几位 → 这里静默忽略、回落到磁盘密钥，
       `core.auth` 用磁盘密钥签发，`studio.auth` 用环境变量验签 → 令牌永远验不过。
       弱密钥由 `_warn_weak_env()` 打警告提示，不静默改写运维的显式配置。
    """
    if env_var:
        env = (os.environ.get(env_var) or "").strip()
        if env:
            _warn_weak_env(env_var, env)
            return env

    path = SECRET_DIR / name
    val = _read(path)
    if val:
        return val

    try:
        SECRET_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _FALLBACK

    new_val = secrets.token_hex(32)
    if _write_exclusive(path, new_val):
        return new_val

    # 竞态：别的进程刚写完，读它的
    val = _read(path)
    if val:
        return val
    # 文件存在但内容不合法（被截断/手工改坏）：覆盖重写
    try:
        path.write_text(new_val, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return new_val
    except OSError:
        return _FALLBACK


def session_secret() -> str:
    """认证签名密钥（JWT 式 token 的 HMAC key）。"""
    return get_secret("session", env_var="YIMU_SECRET_KEY")


def admin_session_secret() -> str:
    """单机管理会话密钥（`mf_token` Cookie 的派生源）。"""
    return get_secret("admin_session", env_var="YIMU_ADMIN_SESSION_SECRET")
