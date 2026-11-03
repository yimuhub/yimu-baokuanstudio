# SPDX-License-Identifier: BUSL-1.1
"""确保 .env 里有一个「可用」的管理员口令。

为什么需要这个脚本
------------------
后端对管理员口令是 fail-closed 的（`web/admin.py:_admin_password`）：

* 没有配置 ADMIN_PASSWORD → 不签发管理 Cookie、拒绝口令登录、本机免密也关闭；
* 配的是历史弱口令（local-admin / admin / 123456）→ 同样视为「未配置」。

于是「复制 .env.example 直接启动」会得到一个确定性死锁：前端自动登录被 400 拒绝，
用户被弹回登录框，只能用普通账号登录，然后所有管理功能 403。
Windows 一键启动脚本因此在这里补一个随机强口令并打印出来。

用法
----
    python scripts/ensure_admin_password.py [.env 路径]

行为：
  * 文件不存在 → 创建（只写 ADMIN_PASSWORD，其他项交给 .env.example）；
  * 已有非弱口令 → 原样保留，不打印口令（避免日志泄漏）；
  * 口令缺失/为弱口令 → 生成 16 字节 urlsafe 随机口令写入并打印一次。
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

#: 与 web/admin.py:_WEAK_PASSWORDS 保持一致
WEAK = {"", "local-admin", "admin", "123456"}
LINE_RE = re.compile(r"(?m)^ADMIN_PASSWORD=(.*)$")


def ensure(env_path: Path) -> tuple[str, bool]:
    """返回 (口令, 是否本次新生成)。"""
    text = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    match = LINE_RE.search(text)
    current = (match.group(1).strip() if match else "")

    if current.lower() not in WEAK:
        return current, False

    new_pwd = secrets.token_urlsafe(12)
    if match:
        text = LINE_RE.sub(f"ADMIN_PASSWORD={new_pwd}", text)
    else:
        text = text.rstrip("\n") + f"\nADMIN_PASSWORD={new_pwd}\n"
    env_path.write_text(text, encoding="utf-8")
    try:  # 收紧权限（Windows 上忽略）
        env_path.chmod(0o600)
    except OSError:
        pass
    return new_pwd, True


def main(argv: list[str]) -> int:
    env_path = Path(argv[1]) if len(argv) > 1 else Path(".env")
    try:
        pwd, created = ensure(env_path)
    except OSError as e:
        print(f"[提示] 无法写入 {env_path}：{e}（请检查目录权限）")
        return 1
    if created:
        print(f"[提示] 管理员口令: {pwd}  (已写入 {env_path}，请妥善保管)")
    else:
        print(f"[提示] 已存在可用管理员口令（{env_path}），未改动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
