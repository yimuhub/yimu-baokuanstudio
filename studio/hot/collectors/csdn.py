# SPDX-License-Identifier: BUSL-1.1
"""CSDN热榜采集器（移植自项目 A cn_community.CsdnCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class CsdnCollector(PlatformCollector):
    name = "csdn"
    display_name = "CSDN热榜"
    category = "community"

    URL = "https://blog.csdn.net/phoenix/web/blog/hot-rank?page=0&pageSize=25"
    REFERER = "https://blog.csdn.net/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = strip_html(row.get("articleTitle") or "")
            if not title:
                continue
            score = row.get("hotRankScore")
            try:
                hot_raw = float(score) if score not in (None, "") else 0.0
            except (TypeError, ValueError):
                hot_raw = float(to_int(score))
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(row.get("articleDetailUrl") or "").strip(),
                author=(row.get("nickName") or "").strip(), rank=idx,
                views=to_int(row.get("viewCount")),
                comments=to_int(row.get("commentCount")),
                collects=to_int(row.get("favorCount")),
                hot_raw=hot_raw,
            ))
        return items
