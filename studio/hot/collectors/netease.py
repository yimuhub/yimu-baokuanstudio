# SPDX-License-Identifier: BUSL-1.1
"""网易新闻采集器（移植自项目 A cn_news.NeteaseCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, abs_url, strip_html
from ..models import HotItem


@register
class NeteaseCollector(PlatformCollector):
    name = "netease"
    display_name = "网易新闻"
    category = "news"

    URL = "https://m.163.com/fe/api/hot/news/flow"
    REFERER = "https://m.163.com/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        rows = root.get("list") if isinstance(root, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = strip_html(row.get("title") or "")
            if not title:
                continue
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=abs_url(self.REFERER, row.get("url") or ""),
                author=(row.get("source") or "").strip(), rank=idx,
            ))
        return items
