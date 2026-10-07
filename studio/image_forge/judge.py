# SPDX-License-Identifier: BUSL-1.1
"""Aesthetic Judge：图片质量与保真的确定性启发式评分。

⭐ 硬规则：
- 纯本地启发式，不调用任何外部服务；同样输入必然得到同样输出（CI 可复现）。
- 缺字段时用保守默认值，绝不抛错（width / height 缺失按 512 处理）。
- 所有返回文案面向用户，禁用内部黑话（见 tests/test_no_internal_jargon.py）。
"""

from __future__ import annotations

_DEFAULT_SIDE = 512  # width / height 缺失时的保守默认值
_REF_PIXELS = 1_000_000  # 评分参照：约 100 万像素（1024×1024）


def _to_positive_int(value: object, default: int) -> int:
    """宽高解析：非正整数一律回落到保守默认值。"""
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _clamp_0_10(value: float) -> float:
    """分数钳制到 0–10 区间。"""
    return max(0.0, min(10.0, value))


def judge_image(image: dict) -> dict:
    """对单张图片做确定性启发式评分。

    Args:
        image: {"url", "prompt", "width", "height", "revised_prompt"}，
            缺字段时用保守默认值，不抛错。

    Returns:
        {"quality_score": 0–10（保留 1 位小数）,
         "fidelity_score": 0–10（保留 1 位小数）,
         "defects": [中文缺陷描述],
         "retouch_hints": [中文自动重修建议]}。
    """
    image = image or {}
    url = str(image.get("url") or "")
    prompt = str(image.get("prompt") or "").strip()
    revised = str(image.get("revised_prompt") or "").strip()
    width = _to_positive_int(image.get("width"), _DEFAULT_SIDE)
    height = _to_positive_int(image.get("height"), _DEFAULT_SIDE)

    defects: list[str] = []
    hints: list[str] = []

    # —— 质量分：分辨率占比 + 提示词完整度 + 上游改写信号
    pixels = width * height
    quality = 4.0 + 4.0 * min(pixels / _REF_PIXELS, 1.0)
    if len(prompt) >= 30:
        quality += 1.0
    elif len(prompt) >= 10:
        quality += 0.5
    if revised:
        quality += 0.5
    quality_score = round(_clamp_0_10(quality), 1)

    if pixels < _DEFAULT_SIDE * _DEFAULT_SIDE:
        defects.append("分辨率偏低（低于 512×512），画面细节可能不足")
        hints.append("建议提高分辨率重绘")
    aspect = width / height
    if aspect > 2.2 or aspect < 0.45:
        defects.append("画面长宽比特殊，构图可能不均衡")
        hints.append("建议按常用画幅裁剪或重新生成")
    if not prompt:
        defects.append("缺少生成提示词，无法判断画面意图")
        hints.append("建议补充完整提示词后重新评分")
    if not revised:
        defects.append("缺少上游改写提示词，画面质量依据不足")
        hints.append("建议检查生成链路是否输出了改写提示词")

    # —— 保真分：改写提示词与原始提示词的一致程度
    fidelity = 5.0
    if prompt and revised:
        ratio = len(revised) / len(prompt)
        if 0.5 <= ratio <= 2.0:
            fidelity += 2.0
        else:
            fidelity += 1.0
    elif prompt and not revised:
        fidelity -= 1.5
        defects.append("画面可能偏离提示词")
        hints.append("建议加强主体光影与构图一致性后重绘")
    if not prompt:
        fidelity -= 2.0
    fidelity_score = round(_clamp_0_10(fidelity), 1)

    if not defects:
        hints.append("当前画面暂无明显问题，可直接使用")

    return {
        "quality_score": quality_score,
        "fidelity_score": fidelity_score,
        "defects": defects,
        "retouch_hints": list(dict.fromkeys(hints)),  # 去重并保序
    }
