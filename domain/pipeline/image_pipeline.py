# SPDX-License-Identifier: BUSL-1.1
"""统一视觉配图注入与微信公众号 HTML 去重防连贴管线。"""
from __future__ import annotations

from core.layouter import _dedupe_wechat_html_images as dedupe_wechat_html_images


def inject_markdown_images_clean(body_md: str, draft_id: str) -> str:
    """将已生成的封面图和章节配图注入 Markdown（延迟加载 imagegen，解耦顶层网络库依赖）。"""
    from core.imagegen import inject_images_to_markdown

    return inject_images_to_markdown(body_md, draft_id)


__all__ = ["inject_markdown_images_clean", "dedupe_wechat_html_images"]
