"""平台适配器接口与通用工具。"""
from pathlib import Path

PLATFORMS = ["wechat_mp", "xhs", "toutiao"]
NAMES = {"wechat_mp": "公众号", "xhs": "小红书", "toutiao": "今日头条"}


def save_preview(draft_dir: Path, platform: str, html_str: str) -> str:
    """把某平台的排版预览写成 html，返回文件名。"""
    name = f"preview-{platform}.html"
    (draft_dir / name).write_text(html_str, encoding="utf-8")
    return name
