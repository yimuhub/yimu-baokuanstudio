# SPDX-License-Identifier: BUSL-1.1
"""文章评分归一工具（v15.9.10 去重后的唯一保留项）。

历史说明：本模块曾包含 ``ArticleQualityGate``「80 分质量门禁」，但全仓
零调用——真正的成稿门禁在 core/judge + web 路由链路内完成。为避免同一
能力第三套实现继续制造审查噪音，该死类已删除；仅保留被测试与契约引用的
``normalize_score_100``。
"""
from __future__ import annotations


def normalize_score_100(raw_score: float | int | None) -> float:
    """统一将任意 10 分制（如 7.3）或百分制分数归一化为标准 0~100 分制。"""
    val = float(raw_score or 0.0)
    if 0.0 < val <= 10.5:
        return round(val * 10.0, 1)
    return round(max(0.0, min(100.0, val)), 1)
