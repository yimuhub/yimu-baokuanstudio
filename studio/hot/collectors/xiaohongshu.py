# SPDX-License-Identifier: BUSL-1.1
"""小红书采集器（移植自项目 A wechat_xhs.XiaohongshuCollector）。

无公开热榜 API，需要 Web 端登录 Cookie（环境变量 XHS_COOKIE）。
未配置时抛 NotConfiguredError → pipeline 记 skipped。
⭐ Cookie 只从环境变量读取。
"""

from __future__ import annotations

import os

from ..base import NotConfiguredError, PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class XiaohongshuCollector(PlatformCollector):
    name = "xiaohongshu"
    display_name = "小红书"
    category = "media"

    URL = "https://edith.xiaohongshu.com/api/sns/web/v1/homefeed"
    REFERER = "https://www.xiaohongshu.com/"

    def collect(self) -> list[HotItem]:
        cookie = os.environ.get("XHS_COOKIE", "").strip()
        if not cookie:
            raise NotConfiguredError("小红书：请设置环境变量 XHS_COOKIE（Web 端登录 Cookie）")
        http = HttpClient()
        data = http.get_json(
            self.URL, referer=self.REFERER, headers={"Cookie": cookie},
        )
        root = data.get("data") if isinstance(data, dict) else None
        rows = root.get("items") if isinstance(root, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            note = row.get("note_card") if isinstance(row.get("note_card"), dict) else {}
            title = strip_html(note.get("title") or note.get("desc") or "")
            if not title:
                continue
            note_id = str(note.get("note_id") or "").strip()
            interact = note.get("interact_info") if isinstance(note.get("interact_info"), dict) else {}
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title,
                url=f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else "",
                rank=idx, likes=to_int(interact.get("liked_count")),
                collects=to_int(interact.get("collected_count")),
                comments=to_int(interact.get("comment_count")),
            ))
        return items
