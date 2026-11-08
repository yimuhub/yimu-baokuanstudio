"""小红书适配器：竖版轮播卡片组（一期出卡片图 + 文案，二期接 Playwright 发布）。"""
from .base import PLATFORMS  # noqa: F401  保持包结构一致
from core.render_card import card_html, render_draft_cards
from pathlib import Path




def render_preview(body_md: str, title: str) -> str:
    from adapters.wechat_mp import render_preview as _rp
    return _rp(body_md, title)
