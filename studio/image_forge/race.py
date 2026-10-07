# SPDX-License-Identifier: BUSL-1.1
"""赛马优选：多候选图按综合分确定性排序，选出优胜者。

⭐ 硬规则（确定性）：
- 综合分 = 0.6 × quality_score + 0.4 × fidelity_score，保留 2 位小数。
- 先按综合分降序；综合分相同按 url 升序决胜，保证同样输入同样名次。
- 空候选列表直接抛 BadRequest，绝不静默选出"空气冠军"。
"""

from __future__ import annotations

from studio.errors import BadRequest


def race_score(candidate: dict) -> float:
    """单候选综合分：0.6×质量分 + 0.4×保真分，保留 2 位小数。"""
    quality = float(candidate.get("quality_score") or 0.0)
    fidelity = float(candidate.get("fidelity_score") or 0.0)
    return round(0.6 * quality + 0.4 * fidelity, 2)


def race(candidates: list[dict]) -> dict:
    """赛马优选。

    Args:
        candidates: judge 后的候选 dict 列表
            （含 quality_score / fidelity_score / url 等）。

    Returns:
        {"winner": 最优项（含 "race_score" 综合分）,
         "ranking": [按名次排列的项，每项带 "rank" 和 "race_score"]}。

    Raises:
        BadRequest: 候选列表为空时。
    """
    if not candidates:
        raise BadRequest("没有候选图片参与赛马")

    scored: list[dict] = []
    for candidate in candidates:
        item = dict(candidate)
        item["race_score"] = race_score(candidate)
        scored.append(item)

    # 综合分降序；同分按 url 升序稳定决胜（确定性）
    scored.sort(key=lambda c: (-c["race_score"], str(c.get("url") or "")))

    ranking: list[dict] = []
    for rank, item in enumerate(scored, start=1):
        ranked = dict(item)
        ranked["rank"] = rank
        ranking.append(ranked)

    return {"winner": dict(scored[0]), "ranking": ranking}
