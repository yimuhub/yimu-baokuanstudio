# SPDX-License-Identifier: BUSL-1.1
"""IT之家采集器（移植自项目 A cn_media.IthomeCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, abs_url, strip_html, to_int
from ..models import HotItem


@register
class IthomeCollector(PlatformCollector):
    name = "ithome"
    display_name = "IT之家"
    category = "media"

    URL = "https://api.ithome.com/json/newslist/news"
    SITE = "https://www.ithome.com/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL)
        rows = data.get("newslist") if isinstance(data, dict) else None
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
                title=title, url=abs_url(self.SITE, row.get("url") or ""),
                body=strip_html(row.get("description") or ""), rank=idx,
                views=to_int(row.get("hitcount")),
                comments=to_int(row.get("commentcount")),
                hot_raw=float(to_int(row.get("hitcount"))),
            ))
        return items
