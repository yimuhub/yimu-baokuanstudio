# SPDX-License-Identifier: BUSL-1.1
"""华尔街见闻采集器（移植自项目 A cn_news.WallstreetcnCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class WallstreetcnCollector(PlatformCollector):
    name = "wallstreetcn"
    display_name = "华尔街见闻"
    category = "news"

    URL = "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=30"
    REFERER = "https://wallstreetcn.com/"
    LIVE = "https://wallstreetcn.com/livenews/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        rows = root.get("items") if isinstance(root, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            content_text = strip_html(row.get("content_text") or "")
            title = strip_html(row.get("title") or "") or strip_html(row.get("highlight_title") or "")
            if not title:
                title = content_text[:60]
            if not title:
                continue
            live_id = str(row.get("id") or "").strip()
            url = (row.get("uri") or "").strip() or (self.LIVE + live_id if live_id else "")
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=url, body=content_text, rank=idx,
                comments=to_int(row.get("comment_count")),
            ))
        return items
