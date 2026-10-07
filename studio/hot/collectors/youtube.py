# SPDX-License-Identifier: BUSL-1.1
"""YouTube 采集器（移植自项目 A global_youtube）。

数据源优先级：Data API v3（YOUTUBE_API_KEY）→ yt-dlp → RSS（YOUTUBE_RSS_FEEDS）。
未配置任何可用源时抛 NotConfiguredError，pipeline 记为 skipped，不影响其他平台。
⭐ Key 只从环境变量读取。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from ..base import NotConfiguredError, PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class YoutubeCollector(PlatformCollector):
    name = "youtube"
    display_name = "YouTube"
    category = "global"

    def collect(self) -> list[HotItem]:
        api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if api_key:
            return self._via_api(api_key)
        if shutil.which("yt-dlp"):
            return self._via_ytdlp()
        feeds = [f.strip() for f in os.environ.get("YOUTUBE_RSS_FEEDS", "").split(",") if f.strip()]
        if feeds:
            return self._via_rss(feeds)
        raise NotConfiguredError(
            "YouTube：未配置可用数据源（YOUTUBE_API_KEY / yt-dlp / YOUTUBE_RSS_FEEDS 任选其一）"
        )

    def _via_api(self, api_key: str) -> list[HotItem]:
        http = HttpClient()
        region = os.environ.get("YOUTUBE_REGION", "US")
        max_results = os.environ.get("YOUTUBE_MAX_RESULTS", "25")
        url = ("https://www.googleapis.com/youtube/v3/videos"
               f"?part=snippet,statistics&chart=mostPopular&regionCode={region}"
               f"&maxResults={max_results}&key={api_key}")
        data = http.get_json(url)
        rows = data.get("items") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            snippet = row.get("snippet") if isinstance(row.get("snippet"), dict) else {}
            stats = row.get("statistics") if isinstance(row.get("statistics"), dict) else {}
            title = strip_html(snippet.get("title") or "")
            if not title:
                continue
            vid = str(row.get("id") or "").strip()
            views = to_int(stats.get("viewCount"))
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=f"https://www.youtube.com/watch?v={vid}" if vid else "",
                author=strip_html(snippet.get("channelTitle") or ""),
                body=strip_html(snippet.get("description") or "")[:300],
                rank=idx, views=views, likes=to_int(stats.get("likeCount")),
                comments=to_int(stats.get("commentCount")),
                hot_raw=float(views),
            ))
        return items

    def _via_ytdlp(self) -> list[HotItem]:
        proc = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", "%(title)s\t%(id)s\t%(view_count)s",
             "https://www.youtube.com/feed/trending"],
            capture_output=True, text=True, timeout=60,
        )
        items: list[HotItem] = []
        for idx, line in enumerate(proc.stdout.splitlines(), 1):
            parts = line.split("\t")
            if len(parts) < 2 or not parts[0].strip():
                continue
            vid = parts[1].strip()
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=parts[0].strip(),
                url=f"https://www.youtube.com/watch?v={vid}",
                rank=idx, views=to_int(parts[2] if len(parts) > 2 else 0),
                hot_raw=float(to_int(parts[2] if len(parts) > 2 else 0)),
            ))
        return items

    def _via_rss(self, feeds: list[str]) -> list[HotItem]:
        import xml.etree.ElementTree as ET

        http = HttpClient()
        items: list[HotItem] = []
        rank = 0
        for feed_url in feeds:
            try:
                xml_text = http.get_text(feed_url)
            except Exception:  # noqa: BLE001 — 单个 feed 失败跳过
                continue
            try:
                root = ET.fromstring(xml_text)
            except ET.ParseError:
                continue
            ns = {"yt": "http://www.youtube.com/xml/schemas/2015",
                  "media": "http://search.yahoo.com/mrss/"}
            for entry in root.findall("entry") or root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title_el = entry.find("title")
                title = strip_html(title_el.text if title_el is not None else "")
                if not title:
                    continue
                vid_el = entry.find("yt:videoId", ns)
                vid = vid_el.text.strip() if vid_el is not None and vid_el.text else ""
                rank += 1
                items.append(HotItem(
                    platform=self.name, platform_name=self.display_name,
                    title=title,
                    url=f"https://www.youtube.com/watch?v={vid}" if vid else "",
                    rank=rank,
                ))
        return items
