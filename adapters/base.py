"""平台适配器接口与通用工具。"""
import re
from pathlib import Path

PLATFORMS = ["wechat_mp", "xhs", "toutiao"]
NAMES = {"wechat_mp": "公众号", "xhs": "小红书", "toutiao": "今日头条"}

#: 预览 / 分享路由承认的六平台（含小红书），与前端平台切换条一致
SUPPORTED_PREVIEW_PLATFORMS = ("wechat_mp", "xhs", "toutiao", "zhihu", "weibo", "twitter")
#: 平台标识白名单：防止把任意字符串拼进文件名造成路径穿越
_SAFE_PLATFORM_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def image_is_missing(src: str) -> bool:
    """编译期存在性校验：本地图片不存在返回 True；外链 / 无法判断返回 False。"""
    try:
        from core.image_contract import local_image_exists
        return local_image_exists(src) is False
    except Exception:
        return False


def safe_image_urls(urls) -> list:
    """过滤掉指向不存在文件的本地图片地址（S4：不把裂图交给浏览器）。"""
    return [u for u in (urls or []) if not image_is_missing(u)]


def save_preview(draft_dir: Path, platform: str, html_str: str) -> str:
    """把某平台的排版预览写成 html，返回文件名。

    V15.8：平台标识必须合法，避免 ``preview-../../x.html`` 之类的路径穿越。
    """
    if not _SAFE_PLATFORM_RE.match(platform or ""):
        raise ValueError(f"非法的预览平台标识: {platform!r}")
    name = f"preview-{platform}.html"
    (draft_dir / name).write_text(html_str, encoding="utf-8")
    return name
