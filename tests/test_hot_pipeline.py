# SPDX-License-Identifier: BUSL-1.1
"""热榜采集 pipeline 测试（移植自项目 A 的失败隔离思想）。

⭐ 硬规则：单个平台抛错绝不影响其他平台；collect_all 永远返回汇总不抛错。
"""

from __future__ import annotations

import pytest

from studio.hot import pipeline as pipeline_mod
from studio.hot.base import PlatformCollector, _REGISTRY, register
from studio.hot.models import HotItem
from studio.hot.normalize import dedup, normalize
from studio.hot.trends import summarize_trend


@register
class _GoodCollector(PlatformCollector):
    name = "test_good"
    display_name = "测试好平台"

    def collect(self):
        return [
            HotItem(platform="test_good", platform_name="测试好平台", title="热榜一", rank=1, hot_raw=9000),
            HotItem(platform="test_good", platform_name="测试好平台", title="热榜二", rank=2, hot_raw=1000),
        ]


@register
class _BadCollector(PlatformCollector):
    name = "test_bad"
    display_name = "测试坏平台"

    def collect(self):
        raise ConnectionError("模拟平台反爬/超时")


def test_failure_isolation_single_platform_error():
    """⭐ 单平台抛错：其他平台照常产出，汇总里记 error，不抛错。"""
    result = pipeline_mod.collect_all(platforms=["test_good", "test_bad"], max_workers=2)
    assert result["ok_count"] == 1
    assert result["fail_count"] == 1
    assert result["detail"]["test_good"]["count"] == 2
    assert "ConnectionError" in result["detail"]["test_bad"]["error"]
    assert result["new_count"] == 2  # 好平台的两条都在


def test_all_platforms_fail_still_returns_summary():
    """⭐ 全挂也不抛错：返回空汇总。"""
    result = pipeline_mod.collect_all(platforms=["test_bad"], max_workers=1)
    assert result["ok_count"] == 0 and result["fail_count"] == 1
    assert result["items"] == []


def test_unknown_platform_rejected():
    with pytest.raises(ValueError, match="未知平台"):
        pipeline_mod.collect_all(platforms=["no_such_platform"])


def test_normalize_cross_platform_comparable():
    """跨平台归一化：分数量级在 0-100，头部更高。"""
    items = [
        HotItem(platform="weibo", platform_name="微博", title="A", hot_raw=100000),
        HotItem(platform="weibo", platform_name="微博", title="B", hot_raw=100),
        HotItem(platform="douyin", platform_name="抖音", title="C", hot_raw=5000000),
    ]
    normalize(items)
    scores = {it.title: it.hot_score for it in items}
    assert all(0 < s <= 100 for s in scores.values())
    assert scores["A"] > scores["B"]  # 同平台内保序


def test_dedup_keeps_highest_score():
    """去重：同 url 多平台上榜只留 hot_score 最高的一条。"""
    items = [
        HotItem(platform="weibo", platform_name="微博", title="同题", url="https://x/1", hot_score=60),
        HotItem(platform="douyin", platform_name="抖音", title="同题", url="https://x/1", hot_score=88),
    ]
    out = dedup(items)
    assert len(out) == 1 and out[0].platform == "douyin"


def test_trend_summary_rules():
    assert summarize_trend([10, 11, 10, 30, 32, 31])["trend"] == "rising"
    assert summarize_trend([30, 32, 31, 10, 11, 10])["trend"] == "cooling"
    assert summarize_trend([20, 21, 20, 21, 20, 21])["trend"] == "steady"
    assert summarize_trend([10, 20])["trend"] == "unknown"


def test_registry_covers_test_platforms():
    assert "test_good" in _REGISTRY and "test_bad" in _REGISTRY
