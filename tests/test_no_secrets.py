# SPDX-License-Identifier: BUSL-1.1
"""密钥扫描：拦截硬编码密钥嫌疑，禁止 .env 落盘。

- 扫描仓库全部文本文件（排除 .git/、__pycache__/、虚拟环境等目录）。
- 正则命中「密钥嫌疑」即 fail；确需豁免的写 tests/allowlist.txt（路径片段 : 行正则片段）。
- 仓库内出现名为 .env 的文件即 fail——密钥只走环境变量与密钥管理服务。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_TXT = Path(__file__).resolve().parent / "allowlist.txt"

# （名称， 正则）：命中即视为硬编码嫌疑。
# 注意：正则使用 r-string + 单反斜杠写法（如 password\s*=）；已验证模式行不会自我命中。
SUSPICIOUS_PATTERNS = [
    ("疑似 API 密钥（sk- 开头）", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("疑似 api_key 硬编码", re.compile(r"api_key\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE)),
    ("疑似 password 硬编码", re.compile(r"password\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE)),
    ("疑似 SECRET_KEY 硬编码", re.compile(r"SECRET_KEY\s*=\s*['\"][^'\"]+")),
    ("疑似 AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("疑似 GitHub Token", re.compile(r"ghp_[A-Za-z0-9]{36,}")),
]

EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", ".env", "node_modules", ".pytest_cache", ".eggs", "dist", "build"}
# 常见二进制扩展名：跳过不读
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".tar", ".gz",
    ".mp3", ".wav", ".mp4", ".mov", ".woff", ".woff2", ".ttf", ".pyc",
}


def _load_allowlist() -> list[tuple[str, re.Pattern | None]]:
    """解析 tests/allowlist.txt → [(路径片段, 行正则或 None)]。"""
    entries = []
    if not ALLOWLIST_TXT.exists():
        return entries
    for line in ALLOWLIST_TXT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            path_part, _, pattern_part = line.partition(":")
            entries.append((path_part.strip(), re.compile(pattern_part.strip())))
        else:
            entries.append((line, None))
    return entries


def _is_allowlisted(rel_path: str, line_text: str, allowlist: list[tuple[str, re.Pattern | None]]) -> bool:
    for path_part, pattern in allowlist:
        if path_part and path_part not in rel_path:
            continue
        if pattern is None or pattern.search(line_text):
            return True
    return False


def _iter_text_files():
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if set(path.parts) & EXCLUDE_DIRS:
            continue
        if path.suffix.lower() in SKIP_EXTENSIONS:
            continue
        yield path


def find_suspicious() -> list[str]:
    """返回所有未豁免的密钥嫌疑描述。"""
    allowlist = _load_allowlist()
    findings = []
    for path in _iter_text_files():
        rel = str(path.relative_to(REPO_ROOT))
        try:
            lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except (UnicodeDecodeError, OSError, ValueError):
            continue
        for lineno, line in enumerate(lines, start=1):
            for name, pattern in SUSPICIOUS_PATTERNS:
                if pattern.search(line) and not _is_allowlisted(rel, line, allowlist):
                    findings.append(f"{rel}:{lineno}: {name}")
    return findings


def find_dotenv_files() -> list[str]:
    """返回仓库内所有名为 .env 的文件（.git 除外）。"""
    found = []
    for path in sorted(REPO_ROOT.rglob(".env")):
        if ".git" in path.parts:
            continue
        found.append(str(path.relative_to(REPO_ROOT)))
    return found


def test_no_dotenv_file():
    """⭐ 仓库内不允许出现被 git 跟踪或非 gitignore 的 .env 文件。"""
    dotenv_files = find_dotenv_files()
    tracked = []
    for f in dotenv_files:
        p = REPO_ROOT / f
        # 如果已被 git 跟踪，直接认定违规
        r = subprocess.run(["git", "ls-files", str(p)], cwd=REPO_ROOT, capture_output=True, text=True)
        if r.stdout.strip():
            tracked.append(f)
    assert not tracked, "git 仓库中发现被跟踪的 .env 文件，请从版本库删除并改用环境变量注入：\n" + "\n".join(tracked)


def test_no_hardcoded_secrets():
    """⭐ 无硬编码密钥嫌疑；误报请走 tests/allowlist.txt 豁免。"""
    findings = find_suspicious()
    assert not findings, (
        "发现硬编码密钥嫌疑，请改为从环境变量读取，误报请在 tests/allowlist.txt 中豁免：\n"
        + "\n".join(findings)
    )
