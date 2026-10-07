"""小红书适配器：竖版轮播卡片组（一期出卡片图 + 文案，二期接 Playwright 发布）。"""
from .base import PLATFORMS  # noqa: F401  保持包结构一致
from core.render_card import card_html, render_draft_cards
from pathlib import Path


def prepare_cards(draft_dir: Path, title: str, sections: list[tuple[str, list[str]]]) -> list[str]:
    """生成封面+内容卡 png（未装 playwright 则生成 html 供后台预览）。"""
    made = render_draft_cards(draft_dir, title, sections)
    if not made:  # 降级：把卡片 HTML 存下来供预览
        (draft_dir / "preview-xhs.html").write_text(
            card_html(title, ["（未安装 playwright，仅预览）"]), encoding="utf-8")
    return made


def render_preview(body_md: str, title: str) -> str:
    from adapters.wechat_mp import render_preview as _rp
    return _rp(body_md, title)
