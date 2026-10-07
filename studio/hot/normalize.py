# SPDX-License-Identifier: BUSL-1.1
"""跨平台热度归一化与去重（移植自项目 A 的 hot_score 思想）。

各平台热度口径不同（微博热度值 vs 抖音播放量），直接比大小没有意义。
归一化策略：平台内按排名/原始值转 0-100 分，再乘平台权重，得到可比的 hot_score。
"""

from __future__ import annotations

import math

from .models import HotItem

# 平台权重：用户体量与爆款参考价值的经验系数（V7.1 可调，调参需同步更新测试期望）
PLATFORM_WEIGHTS: dict[str, float] = {
    "weibo": 1.0,
    "douyin": 1.0,
    "toutiao": 1.0,
    "baidu": 1.0,
    "xiaohongshu": 0.95,
    "bilibili": 0.9,
    "zhihu": 0.9,
    "wechat": 0.9,
    "weixin": 0.85,
    "qqnews": 0.85,
    "kuaishou": 0.85,
    "youtube": 0.9,
    "netease": 0.8,
    "sina": 0.8,
    "juejin": 0.75,
    "csdn": 0.75,
    "ithome": 0.75,
    "sspai": 0.75,
    "36kr": 0.75,
    "ifanr": 0.7,
    "tieba": 0.7,
    "douban": 0.7,
    "thepaper": 0.7,
    "wallstreetcn": 0.7,
    "hackernews": 0.7,
    "github": 0.7,
    "solidot": 0.65,
}
DEFAULT_WEIGHT = 0.8


def normalize(items: list[HotItem]) -> list[HotItem]:
    """平台内归一化：同一平台的条目按 hot_raw 排名映射到 0-100，再乘权重。

    hot_raw 全为 0 的平台（如只有排名）退化为按 rank 倒序给分。
    原地写入 hot_score 并返回原列表。
    """
    by_platform: dict[str, list[HotItem]] = {}
    for it in items:
        by_platform.setdefault(it.platform, []).append(it)
    for platform, group in by_platform.items():
        weight = PLATFORM_WEIGHTS.get(platform, DEFAULT_WEIGHT)
        raws = [it.hot_raw for it in group]
        if any(r > 0 for r in raws):
            lo, hi = min(raws), max(raws)
            span = hi - lo
            for it in group:
                ratio = (it.hot_raw - lo) / span if span > 0 else 1.0
                # 对数压缩：头部热度断层时不至于拉爆分差
                it.hot_score = round(100 * weight * (0.3 + 0.7 * math.log1p(9 * ratio) / math.log1p(9)), 1)
        else:
            # 无原始值：按 rank 给分（rank=1 → 100）
            ranked = sorted(group, key=lambda x: (x.rank or 10**9))
            n = len(ranked)
            for i, it in enumerate(ranked):
                it.hot_score = round(100 * weight * (n - i) / n, 1)
    return items


def dedup(items: list[HotItem]) -> list[HotItem]:
    """跨平台去重：同一内容多平台上榜只保留 hot_score 最高的一条。"""
    best: dict[str, HotItem] = {}
    for it in items:
        key = it.dedup_key()
        if key not in best or it.hot_score > best[key].hot_score:
            best[key] = it
    return list(best.values())


def top(items: list[HotItem], limit: int = 50) -> list[HotItem]:
    """按 hot_score 取前 N。"""
    return sorted(items, key=lambda x: x.hot_score, reverse=True)[:limit]
