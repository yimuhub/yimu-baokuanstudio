# SPDX-License-Identifier: BUSL-1.1
"""百度热搜采集器（移植自项目 A cn_hotlist.BaiduCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html
from ..models import HotItem


@register
class BaiduCollector(PlatformCollector):
    name = "baidu"
    display_name = "百度热搜"
    category = "hotlist"

    URL = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
    REFERER = "https://top.baidu.com/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        cards = root.get("cards") if isinstance(root, dict) else None
        if not isinstance(cards, list):
            return []
        entries: list[dict] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            layer = card.get("content")
            if not isinstance(layer, list):
                continue
            for block in layer:
                if not isinstance(block, dict):
                    continue
                inner = block.get("content")
                if isinstance(inner, list):
                    entries.extend(x for x in inner if isinstance(x, dict))
                else:
                    entries.append(block)
        items: list[HotItem] = []
        for idx, row in enumerate(entries, 1):
            title = (row.get("word") or "").strip()
            if not title:
                continue
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(row.get("url") or "").strip(),
                body=strip_html(row.get("desc") or ""), rank=idx,
            ))
        return items
