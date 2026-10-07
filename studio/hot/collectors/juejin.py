# SPDX-License-Identifier: BUSL-1.1
"""掘金热榜采集器（移植自项目 A cn_community.JuejinCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class JuejinCollector(PlatformCollector):
    name = "juejin"
    display_name = "掘金热榜"
    category = "community"

    URL = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"
    REFERER = "https://juejin.cn/"
    POST = "https://juejin.cn/post/"

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
            content = row.get("content") if isinstance(row.get("content"), dict) else {}
            counter = row.get("content_counter") if isinstance(row.get("content_counter"), dict) else {}
            author = row.get("author") if isinstance(row.get("author"), dict) else {}
            title = strip_html(content.get("title") or "")
            if not title:
                continue
            cid = str(content.get("content_id") or "").strip()
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(self.POST + cid) if cid else "",
                author=(author.get("name") or "").strip(),
                body=strip_html(content.get("brief") or ""), rank=idx,
                views=to_int(counter.get("view")), likes=to_int(counter.get("like")),
                comments=to_int(counter.get("comment_count")),
                collects=to_int(counter.get("collect")),
                hot_raw=float(to_int(counter.get("hot_rank"))),
            ))
        return items
