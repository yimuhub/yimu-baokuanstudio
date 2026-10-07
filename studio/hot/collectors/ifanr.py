# SPDX-License-Identifier: BUSL-1.1
"""爱范儿采集器（移植自项目 A cn_media.IfanrCollector）。"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class IfanrCollector(PlatformCollector):
    name = "ifanr"
    display_name = "爱范儿"
    category = "media"

    URL = "https://sso.ifanr.com/api/v5/wp/buzz/?limit=20&offset=0"
    REFERER = "https://www.ifanr.com/"
    POST = "https://www.ifanr.com/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        rows = data.get("objects") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = strip_html(row.get("post_title") or "")
            if not title:
                continue
            pid = str(row.get("post_id") or "").strip()
            url = (row.get("buzz_original_url") or "").strip() or (self.POST + pid if pid else "")
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=url,
                body=strip_html(row.get("post_content") or ""), rank=idx,
                likes=to_int(row.get("like_count")),
                comments=to_int(row.get("comment_count")),
            ))
        return items
