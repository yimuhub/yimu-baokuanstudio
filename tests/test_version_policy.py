# SPDX-License-Identifier: BUSL-1.1
"""版本线锁定门禁（依据 VERSION_POLICY.md，v15.0.0 起生效）。

规则（用户裁定，2026-11-08）：
- 主版本锁定 V15，日常迭代一律在 15.x.y 内小版本递增；
- 主版本跳升仅限开发者书面修订 VERSION_POLICY.md 后进行。

本测试把该裁定固化为 CI 门禁：
1. version.py 主版本必须与 VERSION_POLICY.md 声明的锁定主版本一致；
2. 代号登记簿 current_version 必须与 version.py 一致（防多工作区漂移）；
3. VERSION_POLICY.md 必须存在且包含「主版本锁定」字样（防止规范被静默删除）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import version

REPO = Path(__file__).resolve().parent.parent


def _locked_major() -> int:
    """从 VERSION_POLICY.md 解析锁定的主版本号。"""
    text = (REPO / "VERSION_POLICY.md").read_text(encoding="utf-8")
    m = re.search(r"主版本锁定\s*\*{0,2}V(\d+)", text)
    assert m, "VERSION_POLICY.md 缺少「主版本锁定 VN」声明，规范文件被破坏？"
    return int(m.group(1))


def test_policy_doc_exists_and_binding():
    text = (REPO / "VERSION_POLICY.md").read_text(encoding="utf-8")
    assert "主版本锁定" in text
    assert "15.x.y" in text, "策略必须声明小版本迭代段"


def test_version_matches_locked_major():
    locked = _locked_major()
    cur = version.__version__
    assert cur.startswith(f"{locked}."), (
        f"版本 {cur} 违反 VERSION_POLICY.md 的主版本锁定 V{locked}。"
        "如确需主版本跳升，请先书面修订 VERSION_POLICY.md 第二节，再同步更新本测试。"
    )
    assert re.match(r"^\d+(\.\d+){1,3}$", cur)


def test_codename_registry_in_sync_with_version():
    """代号登记簿 current_version 必须与 version.py 一致（防多工作区各发各的）。"""
    state = json.loads((REPO / "release-codenames.json").read_text(encoding="utf-8"))
    assert state["current_version"] == version.__version__, (
        f"release-codenames.json 的 current_version={state['current_version']} 与 "
        f"version.py={version.__version__} 不一致——存在未同步的工作区，先 git pull 对齐再发版。"
    )
    assert state["current_codename_zh"] == version.__codename__
    nxt = state["next_index"]
    assert 0 <= nxt < len(state["sequence"]), "next_index 越界，代号序列需扩容"
