# SPDX-License-Identifier: BUSL-1.1
"""澎湃新闻采集器（移植自项目 A cn_news.ThepaperCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class ThepaperCollector(PlatformCollector):
    name = "thepaper"
    display_name = "澎湃新闻"
    category = "news"

    URL = "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar"
    REFERER = "https://www.thepaper.cn/"
    DETAIL = "https://www.thepaper.cn/newsDetail_forward_"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        rows = root.get("hotNews") if isinstance(root, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = strip_html(row.get("name") or "")
            if not title:
                continue
            cont_id = str(row.get("contId") or "").strip()
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(self.DETAIL + cont_id) if cont_id else "",
                rank=idx, likes=to_int(row.get("praiseTimes")),
                hot_raw=float(to_int(row.get("interactionNum"))),
            ))
        return items
