# SPDX-License-Identifier: BUSL-1.1
"""豆瓣热门电影采集器（移植自项目 A cn_news.DoubanCollector）。

热度口径：评分数（rating_count）→ hot_raw。
"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class DoubanCollector(PlatformCollector):
    name = "douban"
    display_name = "豆瓣热门电影"
    category = "news"

    URL = "https://m.douban.com/rexxar/api/v2/subject_collection/movie_showing/items?start=0&count=18"
    REFERER = "https://m.douban.com/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        rows = data.get("subject_collection_items") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = strip_html(row.get("title") or "")
            if not title:
                continue
            rating = row.get("rating") if isinstance(row.get("rating"), dict) else {}
            rating_count = to_int(rating.get("count"))
            names: list[str] = []
            for key in ("directors", "actors"):
                arr = row.get(key)
                if isinstance(arr, list):
                    names.extend(str(x).strip() for x in arr if str(x).strip())
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(row.get("url") or "").strip(),
                author=" / ".join(names[:3]),
                body=strip_html(row.get("card_subtitle") or ""), rank=idx,
                hot_raw=float(rating_count),
            ))
        return items
