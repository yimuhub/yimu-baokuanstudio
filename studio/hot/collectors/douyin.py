# SPDX-License-Identifier: BUSL-1.1
"""抖音热榜采集器（移植自项目 A cn_hotlist.DouyinCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, to_int
from ..models import HotItem


@register
class DouyinCollector(PlatformCollector):
    name = "douyin"
    display_name = "抖音热榜"
    category = "hotlist"

    URL = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383"
    REFERER = "https://www.douyin.com/"
    HOT = "https://www.douyin.com/hot/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        rows = root.get("word_list") if isinstance(root, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = (row.get("word") or "").strip()
            if not title:
                continue
            sid = row.get("sentence_id") or ""
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title,
                url=(self.HOT + str(sid)) if sid not in (None, "") else "",
                rank=to_int(row.get("position")) or idx,
                views=to_int(row.get("video_count")),
                comments=to_int(row.get("discuss_video_count")),
                hot_raw=float(to_int(row.get("hot_value"))),
            ))
        return items
