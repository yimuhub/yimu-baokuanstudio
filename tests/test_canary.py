# SPDX-License-Identifier: BUSL-1.1
"""数据金丝雀：用仓库自带最小种子数据验证关键纯函数。

⭐ 硬规则：
- 金丝雀数据只读：本模块每个测试前后自动校验 tests/seed/ 的哈希（autouse fixture），
  任何写入都会直接 fail。
- 测试不写生产库：纯函数签名中不接受 db 路径；需要落库的逻辑走 conftest.db_session。
- tests/seed/expected.json 是唯一真源；改算法必须同步更新 expected.json 与下方契约。

纯函数契约（WS-B~F 实现时必须遵守，签名与算法二者锁死）：
1. studio.promptforge.assemble_prompt(hotspot: dict, style: str) -> str
   hotspot 字段：id / title / keywords(list[str]) / angle / heat / platform
   算法：先用顿号拼接 keywords，再按模板组装三行文本
   （模板：【风格】标题 / 关键词：… / 切入角度：…，行间用换行分隔）。
2. studio.ledger.calc_cost(entries: list[dict]) -> dict
   每条 entry 含 cost_credits（int，单位：网关 credits）
   算法：返回 {"total_credits": 各条 cost_credits 之和, "count": 条目数}。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

SEED_DIR = Path(__file__).resolve().parent / "seed"
EXPECTED_JSON = SEED_DIR / "expected.json"
CANARY_STYLE = "纪实短评"  # 金丝雀固定风格，保证 expected.json 可复现


def _hash_seed_files() -> dict[str, str]:
    """计算 tests/seed/ 下全部文件的 sha256，用于只读校验。"""
    hashes = {}
    for path in sorted(SEED_DIR.glob("*.json")):
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


@pytest.fixture(autouse=True)
def _seed_files_must_stay_untouched():
    """⭐ 金丝雀只读守卫：每个测试前后校验种子文件哈希。"""
    before = _hash_seed_files()
    assert before, f"种子目录为空：{SEED_DIR}，请先放入种子 JSON。"
    yield
    after = _hash_seed_files()
    assert before == after, "⛔ 金丝雀数据被修改：tests/seed/ 下的文件在测试中被写入，测试只允许只读。"


def _load_seed(name: str) -> dict:
    """只读加载一枚种子 JSON。"""
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def _load_expected() -> dict:
    """只读加载期望输出。"""
    return json.loads(EXPECTED_JSON.read_text(encoding="utf-8"))


def test_promptforge_assemble_canary():
    """PromptForge prompt 组装：种子热点 → 输出与 expected.json 逐字一致。"""
    try:
        from studio.promptforge import assemble_prompt  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("骨架期：studio.promptforge.assemble_prompt 未实现，跳过金丝雀断言。")
    expected = _load_expected()["assemble_prompt"]
    for seed_name in ("hot_1.json", "hot_2.json"):
        hotspot = _load_seed(seed_name)
        key = f"{hotspot['id']}:{CANARY_STYLE}"
        assert assemble_prompt(hotspot, CANARY_STYLE) == expected[key], f"种子 {seed_name} 的 prompt 组装结果漂移"


def test_ledger_calc_cost_canary():
    """账本 cost 计算：种子草稿条目 → 合计与条数与 expected.json 一致。"""
    try:
        from studio.ledger import calc_cost  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("骨架期：studio.ledger.calc_cost 未实现，跳过金丝雀断言。")
    entries = [_load_seed(name) for name in ("draft_1.json", "draft_2.json", "draft_3.json")]
    assert calc_cost(entries) == _load_expected()["calc_cost"], "账本 cost 计算结果漂移"
