# SPDX-License-Identifier: BUSL-1.1
"""趋势快照：同一话题在多天的热度变化（移植自项目 A app/trend.py 思想）。

快照 = 每次 collect_all 的按天聚合；trends() 输出话题的升温/退烧/平稳判断。
存储走 V7 统一 DB（后续 WS-D 落表时接 async_tasks/专用表），本模块只做纯计算。
"""

from __future__ import annotations


def summarize_trend(daily_scores: list[float]) -> dict:
    """输入某话题连续多天的 hot_score（旧→新），输出趋势判断。

    规则：近 3 天均值 vs 前 3 天均值，涨幅 ≥20% 为升温，跌幅 ≥20% 为退烧，否则平稳。
    数据不足 4 天 → 趋势未知。
    """
    n = len(daily_scores)
    if n < 4:
        return {"trend": "unknown", "change_pct": 0.0, "days": n}
    recent = daily_scores[-3:]
    prev = daily_scores[-6:-3] if n >= 6 else daily_scores[:-3]
    avg_recent = sum(recent) / len(recent)
    avg_prev = sum(prev) / len(prev) if prev else 0.0
    if avg_prev <= 0:
        change = 100.0 if avg_recent > 0 else 0.0
    else:
        change = (avg_recent - avg_prev) / avg_prev * 100
    if change >= 20:
        trend = "rising"  # 升温
    elif change <= -20:
        trend = "cooling"  # 退烧
    else:
        trend = "steady"  # 平稳
    return {"trend": trend, "change_pct": round(change, 1), "days": n}
