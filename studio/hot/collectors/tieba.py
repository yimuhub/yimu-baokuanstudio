# SPDX-License-Identifier: BUSL-1.1
"""贴吧热议采集器（移植自项目 A cn_hotlist.TiebaCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class TiebaCollector(PlatformCollector):
    name = "tieba"
    display_name = "贴吧热议"
    category = "hotlist"

    URL = "https://tieba.baidu.com/hottopic/browse/topicList"
    REFERER = "https://tieba.baidu.com/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        root = data.get("data") if isinstance(data, dict) else None
        bang = root.get("bang_topic") if isinstance(root, dict) else None
        rows = bang.get("topic_list") if isinstance(bang, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = (row.get("topic_name") or "").strip()
            if not title:
                continue
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(row.get("topic_url") or "").strip(),
                body=strip_html(row.get("topic_desc") or ""),
                rank=to_int(row.get("idx_num")) or idx,
                hot_raw=float(to_int(row.get("discuss_num"))),
            ))
        return items
