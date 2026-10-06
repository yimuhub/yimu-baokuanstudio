# SPDX-License-Identifier: BUSL-1.1
"""pre-commit 钩子：所有 .py 文件必须含 SPDX-License-Identifier: BUSL-1.1。

pre-commit 会把待检查的文件名作为参数传入；无参数时扫描全仓库（排除 .git 等目录）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SPDX_LINE = "SPDX-License-Identifier: BUSL-1.1"
# 只检查文件前 N 行，避免全文扫描大文件
HEADER_LINES = 10
_EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".eggs"}


def files_missing_header(paths: list[str]) -> list[str]:
    """返回缺少 SPDX 头的 .py 文件列表。"""
    bad = []
    for raw in paths:
        path = Path(raw)
        if path.suffix != ".py" or not path.is_file():
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:HEADER_LINES]
        except OSError:
            continue
        if not any(SPDX_LINE in line for line in head):
            bad.append(str(path))
    return bad


def main(argv: list[str] | None = None) -> int:
    args = [a for a in (argv if argv is not None else sys.argv[1:]) if a.endswith(".py")]
    if args:
        candidates = args
    else:
        candidates = [str(p) for p in Path(".").rglob("*.py") if not (set(p.parts) & _EXCLUDE_DIRS)]
    bad = files_missing_header(candidates)
    if bad:
        print("❌ 以下 .py 文件缺少 SPDX 文件头（前 %d 行须含 %s）：" % (HEADER_LINES, SPDX_LINE))
        for item in bad:
            print(f"  - {item}")
        print("请在文件头添加：# SPDX-License-Identifier: BUSL-1.1")
        return 1
    print(f"✅ SPDX 文件头检查通过（{len(candidates)} 个 .py 文件）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
