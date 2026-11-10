# SPDX-License-Identifier: BUSL-1.1
"""一次性启用 / 关闭「内置官方凭证」硬门禁（管理员工具，仅标准库）。

机制已经随代码落地，但**真实 Key 由仓库所有者保管、绝不进仓库**：
本脚本只把 Key 写入 GitHub Actions Secret，并把门禁开关置 1，
之后每次三平台打包都会把凭证注入安装包，客户机零配置即可使用官方通道。

用法::

    # 启用（key.txt 里只放一行真实 Key，不要提交到仓库）
    python scripts/set_official_key.py --key-file /path/to/key.txt --repo yimuhub/yimu-baokuanstudio

    # 临时关闭门禁（Secret 保留，允许产出不含 Key 的包）
    python scripts/set_official_key.py --disable --repo yimuhub/yimu-baokuanstudio

⚠ 主库是公开仓库、Release 安装包任何人可下载，随包 Key 一定能被解包提取。
务必使用**专用、限额、可轮换**的官方推广 Key，定期轮换；不要放主账号密钥。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SECRET_NAME = "YIMU_OFFICIAL_BOOTSTRAP_KEY"
VARIABLE_NAME = "YIMU_REQUIRE_OFFICIAL_KEY"
PLACEHOLDERS = {"", "test", "test_key", "your-api-key", "your_api_key",
                "sk-xxx", "xxx", "changeme", "placeholder"}


def _gh(args: list[str], *, stdin: str | None = None) -> None:
    try:
        subprocess.run(["gh", *args], input=stdin, text=True, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit("未找到 gh CLI，请先安装 GitHub CLI 并执行 gh auth login")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"gh 命令失败: {e.stderr.strip()[-500:] or e}")


def _read_key(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"凭证文件不存在: {path}")
    raw = path.read_text(encoding="utf-8", errors="ignore").strip()
    # 兼容 `YIMU_OFFICIAL_BOOTSTRAP_KEY=xxx` 写法，但只取等号右边
    if "=" in raw.splitlines()[0] and "\n" not in raw:
        raw = raw.split("=", 1)[1].strip().strip('"').strip("'")
    if raw.lower() in PLACEHOLDERS:
        raise SystemExit("凭证为空或仍是占位符，拒绝写入")
    if "\n" in raw:
        raise SystemExit("凭证文件只能包含一行 Key")
    return raw


def main() -> None:
    ap = argparse.ArgumentParser(description="配置内置官方凭证（GitHub Secrets / Variables）")
    ap.add_argument("--key-file", type=Path, help="只含一行真实官方 Key 的本地文件")
    ap.add_argument("--repo", default="yimuhub/yimu-baokuanstudio", help="目标仓库 owner/name")
    ap.add_argument("--disable", action="store_true", help="关闭强制门禁（保留 Secret）")
    args = ap.parse_args()

    if args.disable:
        _gh(["variable", "set", VARIABLE_NAME, "--repo", args.repo, "--body", "0"])
        print(f"已关闭 {VARIABLE_NAME}；后续构建允许产出 official_key_source=unset 的包。")
        return

    if not args.key_file:
        raise SystemExit("启用时必须有 --key-file（真实 Key 不通过命令行参数传递，避免进 shell history）")
    key = _read_key(args.key_file)
    _gh(["secret", "set", SECRET_NAME, "--repo", args.repo], stdin=key + "\n")
    _gh(["variable", "set", VARIABLE_NAME, "--repo", args.repo, "--body", "1"])
    print(f"已写入 Secret {SECRET_NAME} 并开启 {VARIABLE_NAME}=1。")
    print("下一次 tag 触发的打包会把凭证注入三平台安装包；客户机启动不再联网申领。")
    print("⚠ 公开 Release 里的 Key 可被提取：请确认它是限额、可轮换的专用推广 Key。")


if __name__ == "__main__":
    sys.exit(main())
