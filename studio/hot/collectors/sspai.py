# SPDX-License-Identifier: BUSL-1.1
"""少数派采集器（移植自项目 A cn_media.SspaiCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class SspaiCollector(PlatformCollector):
    name = "sspai"
    display_name = "少数派"
    category = "media"

    URL = "https://sspai.com/api/v1/article/index/page/get?limit=20&offset=0"
    REFERER = "https://sspai.com/"
    POST = "https://sspai.com/post/"
    CDN = "https://cdn.sspai.com/"

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
            title = strip_html(row.get("title") or "")
            if not title:
                continue
            aid = str(row.get("id") or "").strip()
            author_raw = row.get("author")
            if isinstance(author_raw, dict):
                author = (author_raw.get("nickname") or "").strip()
            elif isinstance(author_raw, str):
                author = author_raw.strip()
            else:
                author = ""
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(self.POST + aid) if aid else "",
                author=author, body=strip_html(row.get("summary") or ""),
                rank=idx, views=to_int(row.get("view_count")),
                likes=to_int(row.get("like_count")),
                comments=to_int(row.get("comment_count")),
                hot_raw=float(to_int(row.get("view_count"))),
            ))
        return items
