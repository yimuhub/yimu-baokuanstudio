# SPDX-License-Identifier: BUSL-1.1
"""腾讯新闻热点采集器（移植自项目 A cn_news.QqnewsCollector）。

接口字段随条目类型浮动，缺失的一律留空，不编造。
"""

from __future__ import annotations

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class QqnewsCollector(PlatformCollector):
    name = "qqnews"
    display_name = "腾讯新闻热点"
    category = "news"

    URL = "https://i.news.qq.com/gw/event/hot_ranking_list?page_size=50"
    REFERER = "https://news.qq.com/"
    DETAIL = "https://new.qq.com/rain/a/"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        data = http.get_json(self.URL, referer=self.REFERER)
        idlist = data.get("idlist") if isinstance(data, dict) else None
        if not isinstance(idlist, list) or not idlist:
            return []
        first = idlist[0]
        rows = first.get("newslist") if isinstance(first, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            title = strip_html(row.get("title") or "")
            if not title:
                continue
            news_id = str(row.get("id") or "").strip()
            url = (row.get("surl") or row.get("url") or "").strip() or (
                self.DETAIL + news_id if news_id else "")
            hot_event = row.get("hotEvent") if isinstance(row.get("hotEvent"), dict) else {}
            hot = hot_event.get("hotScore")
            if hot in (None, ""):
                hot = row.get("hotScore")
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=url,
                author=(row.get("source") or row.get("chlname") or "").strip(),
                body=strip_html(row.get("abstract") or row.get("nlpAbstract") or ""),
                rank=idx, views=to_int(row.get("readCount")),
                likes=to_int(row.get("likeInfo")),
                comments=to_int(row.get("commentNum") or row.get("comments")),
                shares=to_int(row.get("shareCount")),
                collects=to_int(row.get("collect_count")),
                hot_raw=float(to_int(hot)),
            ))
        return items
