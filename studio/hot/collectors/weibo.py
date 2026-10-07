# SPDX-License-Identifier: BUSL-1.1
"""微博热搜采集器（移植自项目 A cn_hotlist.WeiboCollector）。"""

from __future__ import annotations

from urllib.parse import urlencode

from ..base import PlatformCollector, register
from ..http import HttpClient, to_int
from ..models import HotItem


@register
class WeiboCollector(PlatformCollector):
    name = "weibo"
    display_name = "微博热搜"
    category = "hotlist"

    URL = "https://weibo.com/ajax/side/hotSearch"
    REFERER = "https://weibo.com/"
    SEARCH = "https://s.weibo.com/weibo?"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        rows = root.get("realtime") if isinstance(root, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            word = (row.get("word") or "").strip() or (row.get("word_scheme") or "").strip()
            if not word:
                continue
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=word,
                url=self.SEARCH + urlencode({"q": "#" + word + "#"}),
                body=(row.get("note") or "").strip(),
                rank=to_int(row.get("rank")) or idx,
                hot_raw=float(to_int(row.get("num"))),
            ))
        return items
