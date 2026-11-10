# SPDX-License-Identifier: BUSL-1.1
"""统一的敏感配置初始化 / 迁移工具（纯标准库，三平台启动脚本共用）。

替代历史上散落在 ``一键启动.bat`` / ``.command`` / ``_linux.sh`` /
``服务器一键部署.sh`` 里各自写 ``.env`` 明文的逻辑。

行为：
1. 把旧 ``.env`` 里的敏感项迁到用户数据目录 ``secrets.env``（0600）；
2. 缺失或弱口令时生成随机 ``YIMU_SECRET_KEY`` / ``ADMIN_PASSWORD``；
3. 安装目录 ``.env`` 只保留非敏感配置，随包分发也不泄露密钥；
4. ``--show`` 时才打印一次管理员口令（供首次安装引导）。

用法： ``python scripts/init_secrets.py [--show] [--env <安装目录 .env 路径>]``
"""
from __future__ import annotations

import secrets as _secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import user_paths  # noqa: E402

WEAK = {"", "local-admin", "admin", "123456", "yimu-888888"}


def init(env_path: Path | None = None) -> dict:
    env_path = env_path or (ROOT / ".env")
    migrated = user_paths.migrate_legacy_secrets(env_path)
    path = user_paths.secrets_env_path()
    vals = user_paths.read_env_file(path)
    generated = []
    for key, factory in (
        ("YIMU_SECRET_KEY", lambda: _secrets.token_urlsafe(32)),
        ("ADMIN_PASSWORD", lambda: _secrets.token_urlsafe(16)),
    ):
        current = (vals.get(key) or "").strip()
        if current.lower() in WEAK:
            vals[key] = factory()
            generated.append(key)
    ok = user_paths.write_env_file(path, vals)
    return {
        "path": str(path),
        "ok": ok,
        "migrated": migrated,
        "generated": generated,
        "admin_password": vals.get("ADMIN_PASSWORD", ""),
    }


def main(argv: list[str]) -> int:
    env_path = None
    if "--env" in argv:
        i = argv.index("--env")
        if i + 1 < len(argv):
            env_path = Path(argv[i + 1])
    result = init(env_path)
    if not result["ok"]:
        print(f"[secrets] 写入失败: {result['path']}（请检查用户目录权限）")
        return 1
    print(f"[secrets] 已就绪: {result['path']} "
          f"(迁移 {result['migrated']} 项 / 新生成 {', '.join(result['generated']) or '无'})")
    if "--show" in argv:
        print(f"[secrets] 管理员口令: {result['admin_password']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
