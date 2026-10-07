# SPDX-License-Identifier: BUSL-1.1
"""微信公众号采集器（移植自项目 A wechat_xhs.WeixinMpCollector）。

无公开热榜 API，走 RSS 聚合 feed（Wechat2RSS / WeWe-RSS）。
未配置 WECHAT_RSS_FEEDS 时抛 NotConfiguredError → pipeline 记 skipped。
"""

from __future__ import annotations

import os
import re

from ..base import NotConfiguredError, PlatformCollector, register
from ..http import HttpClient, strip_html
from ..models import HotItem


def _xml_tag(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, re.S | re.I)
    return m.group(1).strip() if m else ""


@register
class WeixinCollector(PlatformCollector):
    name = "weixin"
    display_name = "微信公众号"
    category = "media"

    FEEDS_ENV = "WECHAT_RSS_FEEDS"

    def collect(self) -> list[HotItem]:
        feeds = [f.strip() for f in os.environ.get(self.FEEDS_ENV, "").split(",") if f.strip()]
        if not feeds:
            raise NotConfiguredError(
                f"微信公众号：请设置环境变量 {self.FEEDS_ENV}=<feed_url1,feed_url2>"
            )
        http = HttpClient()
        items: list[HotItem] = []
        rank = 0
        for feed_url in feeds:
            try:
                raw = http.get_text(feed_url)
            except Exception:  # noqa: BLE001 — 单个 feed 失败跳过
                continue
            for m in re.finditer(r"<(?:item|entry)\b[^>]*>(.*?)</(?:item|entry)>", raw, re.S | re.I):
                block = m.group(1)
                title = strip_html(_xml_tag(block, "title"))
                if not title:
                    continue
                rank += 1
                items.append(HotItem(
                    platform=self.name, platform_name=self.display_name,
                    title=title, url=_xml_tag(block, "link"),
                    body=strip_html(_xml_tag(block, "description") or _xml_tag(block, "summary")),
                    rank=rank,
                ))
        return items
