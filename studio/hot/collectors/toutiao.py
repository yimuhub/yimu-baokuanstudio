# SPDX-License-Identifier: BUSL-1.1
"""今日头条热榜采集器（移植自项目 A cn_hotlist.ToutiaoCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class ToutiaoCollector(PlatformCollector):
    name = "toutiao"
    display_name = "今日头条"
    category = "hotlist"

    URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
    REFERER = "https://www.toutiao.com/"

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
            title = (row.get("Title") or "").strip()
            if not title:
                continue
            hot = row.get("HotValue")
            try:
                hot_raw = float(hot) if hot not in (None, "") else 0.0
            except (TypeError, ValueError):
                hot_raw = float(to_int(hot))
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(row.get("Url") or "").strip(),
                rank=idx, hot_raw=hot_raw,
            ))
        return items
