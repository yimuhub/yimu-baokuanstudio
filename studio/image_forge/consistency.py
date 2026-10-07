# SPDX-License-Identifier: BUSL-1.1
"""人物一致性抽查：对接人物特征锚点（发色/瞳色/服装/配饰）的抽查工具。

⭐ 硬规则：
- 本模块只做"抽查判定"，不修图、不写库、不调用外部服务；判定结果只给人看，
  不得作为自动扣费或自动下线的依据。
- match=None 表示"未检出"（观察值缺失）：不算通过也不算失败。把未检出判成失败
  会误伤合格人物（用户会看到无故的"不一致"警告）；把未检出判成通过会放过真实
  翻车。passed 的唯一判据是"没有明确 mismatch"。
"""

from __future__ import annotations

# 锚点顺序固定：发色 → 瞳色 → 服装 → 配饰（输出顺序稳定可预期）
_ANCHOR_ORDER: tuple[str, ...] = ("hair", "eyes", "outfit", "accessories")

# 锚点中文名（用于生成检查方法描述）
_ANCHOR_NAMES: dict[str, str] = {
    "hair": "发色",
    "eyes": "瞳色",
    "outfit": "服装",
    "accessories": "配饰",
}

# 每锚点的检查方法（中文一句话）
_CHECK_METHODS: dict[str, str] = {
    "hair": "看图中人物发色（含深浅、挑染特征）是否与期望值一致。",
    "eyes": "看图中人物瞳色（含美瞳、特殊瞳色）是否与期望值一致。",
    "outfit": "看图中人物服装的款式与颜色是否与期望值一致。",
    "accessories": "看图中人物配饰（帽子、眼镜、饰品等）是否出现在期望位置且样式一致。",
}


def _anchors_of(character: dict) -> dict:
    """取人物特征锚点字典；缺失则视为空。"""
    anchors = (character or {}).get("feature_anchors") or {}
    return anchors if isinstance(anchors, dict) else {}


def _anchor_items(character: dict) -> list[tuple[str, str]]:
    """返回 (锚点, 期望值) 列表：按固定顺序，跳过缺失/空白的锚点。

    ⭐ 缺失锚点必须跳过：没有期望值就无法判定，硬凑一个检查项
    只会产出无意义的"通过"，误导人工复核。
    """
    anchors = _anchors_of(character)
    ordered = [key for key in _ANCHOR_ORDER if key in anchors]
    ordered += sorted(key for key in anchors if key not in _ANCHOR_ORDER)
    items: list[tuple[str, str]] = []
    for key in ordered:
        expected = anchors[key]
        if expected is None or (isinstance(expected, str) and not expected.strip()):
            continue
        items.append((key, expected))
    return items


def build_checklist(character: dict) -> list[dict]:
    """为人物生成一致性检查清单。

    character 形如 {"name": str, "feature_anchors": {"hair":.., "eyes":.., "outfit":.., "accessories":..}}。
    返回每项 {"anchor": 锚点名, "expected": 期望值, "check": 检查方法中文一句话}；
    缺失的锚点跳过。
    """
    checklist: list[dict] = []
    for key, expected in _anchor_items(character):
        name = _ANCHOR_NAMES.get(key, key)
        checklist.append(
            {
                "anchor": key,
                "expected": expected,
                "check": f"核验{name}：{_CHECK_METHODS.get(key, '看图中该特征是否与期望值一致。')}",
            }
        )
    return checklist


def check_consistency(character: dict, image_report: dict) -> dict:
    """抽查判定：人物特征锚点 vs 图片观察报告。

    image_report 形如 {"hair": 观察值 | None, ...}。
    返回 {"passed": bool, "items": [...], "mismatches": [锚点名...]}，
    items 每项 {"anchor","expected","observed","match": True|False|None}。

    ⭐ observed 为 None 时 match=None（未检出）：不算通过也不算失败；
    passed = 无明确 mismatch（mismatches 为空）。
    """
    report = image_report or {}
    items: list[dict] = []
    mismatches: list[str] = []
    for key, expected in _anchor_items(character):
        observed = report.get(key)
        if observed is None or (isinstance(observed, str) and not observed.strip()):
            match: bool | None = None  # 未检出：不判对错
        else:
            match = observed == expected
            if match is False:
                mismatches.append(key)
        items.append(
            {"anchor": key, "expected": expected, "observed": observed, "match": match}
        )
    return {"passed": not mismatches, "items": items, "mismatches": mismatches}
