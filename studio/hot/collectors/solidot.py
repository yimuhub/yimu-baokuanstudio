# SPDX-License-Identifier: BUSL-1.1
"""奇客Solidot采集器（移植自项目 A cn_media.SolidotCollector）。

走 RSS（index.rss），纯标准库 xml 解析。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html
from ..models import HotItem


@register
class SolidotCollector(PlatformCollector):
    name = "solidot"
    display_name = "奇客Solidot"
    category = "media"

    URL = "https://www.solidot.org/index.rss"

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        xml_text = http.get_text(self.URL)
        root = ET.fromstring(xml_text)
        items: list[HotItem] = []
        for idx, node in enumerate(root.findall(".//item"), 1):
            def _txt(tag: str) -> str:
                ch = node.find(tag)
                return (ch.text or "").strip() if ch is not None and ch.text else ""

            title = strip_html(_txt("title"))
            if not title:
                continue
            link = _txt("link")
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=link,
                body=strip_html(_txt("description")), rank=idx,
            ))
        return items
