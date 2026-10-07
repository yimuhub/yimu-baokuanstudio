# SPDX-License-Identifier: BUSL-1.1
"""Hacker News 采集器（移植自项目 A global_.HackerNewsCollector）。

走 Algolia 聚合接口一次拿全（不逐条请求）。
"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class HackerNewsCollector(PlatformCollector):
    name = "hackernews"
    display_name = "Hacker News"
    category = "global"

    URL = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"
    ITEM = "https://news.ycombinator.com/item?id="

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL)
        hits = data.get("hits") if isinstance(data, dict) else None
        if not isinstance(hits, list):
            return []
        items: list[HotItem] = []
        for idx, hit in enumerate(hits, 1):
            if not isinstance(hit, dict):
                continue
            title = strip_html(hit.get("title") or "")
            if not title:
                continue
            object_id = str(hit.get("objectID") or "").strip()
            url = (hit.get("url") or "").strip() or (self.ITEM + object_id if object_id else "")
            points = to_int(hit.get("points"))
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=url, author=(hit.get("author") or "").strip(),
                body=strip_html(hit.get("story_text") or hit.get("comment_text") or ""),
                rank=idx, likes=points,
                comments=to_int(hit.get("num_comments")),
                hot_raw=float(points),
            ))
        return items
