# SPDX-License-Identifier: BUSL-1.1
"""文章创作与 80+ 分质量门禁统一管线（消除极简模式与工作台模式的重复代码）。"""
from __future__ import annotations

from typing import Any

PASSING_SCORE_THRESHOLD: float = 80.0


def normalize_score_100(raw_score: float | int | None) -> float:
    """统一将任意 10 分制（如 7.3）或百分制分数归一化为标准 0~100 分制。"""
    val = float(raw_score or 0.0)
    if 0.0 < val <= 10.5:
        return round(val * 10.0, 1)
    return round(max(0.0, min(100.0, val)), 1)


class ArticleQualityGate:
    """80 分质量门禁：低于 80 分自动触发定向反馈重写，确保交付成稿 >= 80 分。"""

    def __init__(self, threshold: float = PASSING_SCORE_THRESHOLD, max_rounds: int = 2) -> None:
        self.threshold = threshold
        self.max_rounds = max_rounds

    def evaluate_and_polish(self, draft_id: str, platform: str = "wechat_mp") -> dict[str, Any]:
        from core import db, judge

        score_res = judge.judge_draft(draft_id, platform=platform)
        cur_sc = normalize_score_100(score_res.get("total"))
        rounds = 0
        while cur_sc < self.threshold and rounds < self.max_rounds:
            rounds += 1
            rewritten = judge.rewrite_with_feedback(draft_id, score_res)
            if not rewritten or len(rewritten.strip()) <= 80:
                break
            db.update_draft_body(draft_id, rewritten.strip())
            score_res = judge.judge_draft(draft_id, platform=platform, min_score=cur_sc)
            cur_sc = normalize_score_100(score_res.get("total"))
        score_res["total"] = cur_sc
        score_res["grade"] = judge.grade(cur_sc)
        score_res["rewrite_rounds"] = rounds
        return score_res
