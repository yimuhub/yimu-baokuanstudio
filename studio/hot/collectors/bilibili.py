# SPDX-License-Identifier: BUSL-1.1
"""B站排行采集器（移植自项目 A cn_community.BilibiliCollector）。

反爬要点：先 warmup 拿 buvid3 指纹 cookie，否则接口返回 code=-352；
排行接口被风控时改用「热门」接口。
"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class BilibiliCollector(PlatformCollector):
    name = "bilibili"
    display_name = "B站排行"
    category = "community"

    URL = "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all"
    FALLBACK_URL = "https://api.bilibili.com/x/web-interface/popular?ps=50&pn=1"
    REFERER = "https://www.bilibili.com/"
    VIDEO = "https://www.bilibili.com/video/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        http.warmup("https://www.bilibili.com/", referer=self.REFERER)
        data = http.get_json(self.URL, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        rows = root.get("list") if isinstance(root, dict) else None
        if not isinstance(rows, list):
            data = http.get_json(self.FALLBACK_URL, referer=self.REFERER)
            root = data.get("data") if isinstance(data, dict) else None
            rows = root.get("list") if isinstance(root, dict) else None
            if not isinstance(rows, list):
                return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = strip_html(row.get("title") or "")
            if not title:
                continue
            bvid = str(row.get("bvid") or "").strip()
            url = (row.get("short_link_v2") or "").strip() or (self.VIDEO + bvid if bvid else "")
            owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
            stat = row.get("stat") if isinstance(row.get("stat"), dict) else {}
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=url, author=(owner.get("name") or "").strip(),
                body=strip_html(row.get("desc") or ""), rank=idx,
                views=to_int(stat.get("view")), likes=to_int(stat.get("like")),
                comments=to_int(stat.get("reply")), collects=to_int(stat.get("favorite")),
                hot_raw=float(to_int(stat.get("view"))),
            ))
        return items
