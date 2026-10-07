# SPDX-License-Identifier: BUSL-1.1
"""36氪热榜采集器（移植自项目 A cn_media.Kr36Collector）。

接口需要 POST JSON；真正字段藏在 templateMaterial 里。
"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class Kr36Collector(PlatformCollector):
    name = "36kr"
    display_name = "36氪热榜"
    category = "media"

    URL = "https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot"
    REFERER = "https://36kr.com/"
    POST = "https://36kr.com/p/"
    PAYLOAD = {"partner_id": "wap", "param": {"siteId": 1, "platformId": 2}, "timestamp": 0}

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.post_json(self.URL, self.PAYLOAD, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        rows = root.get("hotRankList") if isinstance(root, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            mat = row.get("templateMaterial")
            if not isinstance(mat, dict):
                mat = {}
            item_id = str(row.get("itemId") or mat.get("itemId") or "").strip()
            title = strip_html(mat.get("widgetTitle") or mat.get("title") or "")
            if not title:
                continue
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(self.POST + item_id) if item_id else "",
                author=(mat.get("authorName") or "").strip(),
                body=strip_html(mat.get("summary") or mat.get("widgetSummary") or ""),
                rank=idx, views=to_int(mat.get("statRead")),
                likes=to_int(mat.get("statPraise")),
                comments=to_int(mat.get("statComment")),
                collects=to_int(mat.get("statCollect")),
                hot_raw=float(to_int(mat.get("statRead"))),
            ))
        return items
