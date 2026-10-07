# SPDX-License-Identifier: BUSL-1.1
"""新浪新闻采集器（移植自项目 A cn_news.SinaCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, abs_url, strip_html
from ..models import HotItem


@register
class SinaCollector(PlatformCollector):
    name = "sina"
    display_name = "新浪新闻"
    category = "news"

    URL = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2510&num=30"
    REFERER = "https://news.sina.com.cn/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        result = data.get("result") if isinstance(data, dict) else None
        rows = result.get("data") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = strip_html(row.get("title") or "") or strip_html(row.get("stitle") or "")
            if not title:
                continue
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=abs_url(self.REFERER, row.get("url") or ""),
                author=(row.get("author") or "").strip(),
                body=strip_html(row.get("wapsummary") or ""), rank=idx,
            ))
        return items
