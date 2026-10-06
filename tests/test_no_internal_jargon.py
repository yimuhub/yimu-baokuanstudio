# SPDX-License-Identifier: BUSL-1.1
"""术语检查：面向用户的文案不得出现内部黑话。

扫描范围：web/、studio/、gateway/ 下的 .py / .html / .js / .md 文件。
tests/ 自身豁免（本文件的词表不算违规）。
大小写不敏感。命中任一禁用词即 fail，并列出文件与词。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ⭐ 面向用户文案禁用词表（内部黑话 / 未完成痕迹 / 占位文本）
BANNED_WORDS = [
    "供应商",
    "闸门",
    "降级",
    "mock",
    "dummy",
    "占位",
    "主库",
    "TODO",
    "FIXME",
    "lorem",
]

SCAN_DIRS = ("web", "studio", "gateway")
SCAN_EXTENSIONS = {".py", ".html", ".js", ".md"}


def _scan_file(path: Path) -> list[str]:
    """返回该文件中命中的禁用词（去重，保持词表顺序）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # 二进制 / 不可读文件跳过
    lowered = text.lower()
    return [word for word in BANNED_WORDS if word.lower() in lowered]


def find_violations() -> list[str]:
    """扫描并返回所有违规描述；无违规返回空列表。"""
    violations = []
    for dirname in SCAN_DIRS:
        root = REPO_ROOT / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SCAN_EXTENSIONS:
                continue
            hits = _scan_file(path)
            for word in hits:
                violations.append(f"{path.relative_to(REPO_ROOT)}: 含禁用词「{word}」")
    return violations


def test_no_internal_jargon():
    """⭐ 用户看到的文案里不许出现内部黑话。"""
    violations = find_violations()
    assert not violations, (
        "发现面向用户的内部黑话 / 未完成痕迹，请改写为用户语言：\n" + "\n".join(violations)
    )
