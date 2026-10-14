"""公众号适配器：主题化排版（core/themes 5 套主题）+ AI 配图 + 草稿箱 API。"""
from __future__ import annotations
import re
import time

import httpx

from core.llm import load_env
from core.themes import DEFAULT_THEME
from core.layouter import render as layout_render


def render_preview(body_md: str, title: str, theme: str = DEFAULT_THEME,
                   images: dict | None = None, cover: str | None = None, **kwargs) -> str:
    """微信兼容行内样式 HTML（主题化 + 可插 AI 配图 + 全链路防重复）。"""
    return layout_render(body_md, title=title, theme=theme, images=images, cover=cover, **kwargs)


def _access_token() -> str:
    env = load_env()
    appid, secret = env.get("WECHAT_MP_APPID"), env.get("WECHAT_MP_SECRET")
    if not (appid and secret):
        raise RuntimeError("未配置 WECHAT_MP_APPID/SECRET（.env），请用 manual 模式")
    r = httpx.get("https://api.weixin.qq.com/cgi-bin/token",
                  params={"grant_type": "client_credential", "appid": appid,
                          "secret": secret}, timeout=20)
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"获取 access_token 失败: {data}")
    return data["access_token"]


def push_draft(title: str, body_md: str, theme: str = DEFAULT_THEME) -> dict:
    """进公众号草稿箱。成功返回 {"media_id": ...}。"""
    token = _access_token()
    html_str = render_preview(body_md, title, theme=theme)
    # 注：正式启用前需先走 /cgi-bin/media/uploadimg 传图并替换正文图片链接
    r = httpx.post(f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}",
                   json={"articles": [{"title": title[:64], "content": html_str,
                                       "need_open_comment": 1}]}, timeout=30)
    data = r.json()
    if data.get("errcode"):
        raise RuntimeError(f"草稿箱接口报错: {data}")
    return {"media_id": data["media_id"]}


def upload_image(img_path) -> str:
    """上传本地图片到公众号素材库（uploadimg，永久图文内链）。

    需认证号+IP白名单；成功返回微信 CDN url，失败抛异常。
    """
    token = _access_token()
    with open(img_path, "rb") as f:
        r = httpx.post(
            f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={token}",
            files={"media": (img_path.split("/")[-1], f, "image/png")}, timeout=60)
    data = r.json()
    if data.get("errcode"):
        raise RuntimeError(f"uploadimg 失败: {data}")
    return data["url"]


def clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
