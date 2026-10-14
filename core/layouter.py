"""排版 Agent：调 themes 渲染公众号 HTML，处理封面图/章节配图嵌入（内置防重复与防连贴守卫）。"""
from __future__ import annotations
import re
from core.themes import md_to_wechat_html, list_themes, get_theme


def render(body_md: str, title: str = "", theme: str = "amber",
           meta: str = "深度原创", images: dict | None = None,
           cover: str | None = None) -> str:
    """body_md + 主题 + 可选章节配图 → 完整可粘贴公众号 HTML（自动去重防堆叠）。"""
    has_inline_md_imgs = bool(body_md and re.search(r'!\[[^\]]*\]\([^)]+\)', body_md))
    effective_images = None if has_inline_md_imgs else (dict(images) if images else None)
    html = md_to_wechat_html(body_md, title=title, theme_key=theme,
                             meta=meta, images=effective_images)
    html = _materialize_images(html)
    if cover and not has_inline_md_imgs:
        norm_cover = cover.split("?")[0].strip()
        if norm_cover not in html:
            html = _inject_cover(html, cover)
    html = _dedupe_wechat_html_images(html)
    return html


def _inject_cover(html: str, cover_url: str) -> str:
    """把封面图塞在第一段（导语）之后，若已存在则不重复注入。"""
    norm_cover = (cover_url or "").split("?")[0].strip()
    if not norm_cover or norm_cover in html:
        return html
    img_html = (f"<img src='{cover_url}' "
                f"style='width:100%;border-radius:10px;margin:14px 0 18px;display:block'/>")
    idx = html.find("</p>")
    if idx != -1:
        return html[:idx + 4] + img_html + html[idx + 4:]
    return img_html + html


def _materialize_images(html: str) -> str:
    """把正文中形如 [配图：xxx] 的占位符替换为柔和提示块（若真有 url 则变 img）。"""
    def repl(m):
        desc = m.group(1).strip()
        if desc.startswith("http://") or desc.startswith("https://") or desc.startswith("/"):
            return (f"<img src='{desc}' style='width:100%;border-radius:8px;"
                    f"margin:14px 0;display:block'/>")
        return ""
    return re.sub(r"\[(?:配图
ert{}图
ert{}image)[:：]\s*([^\]]+)\]", repl, html)


def _dedupe_wechat_html_images(html: str) -> str:
    """对最终公众号 HTML 中的 <img> 进行 URL 去重与连续相邻 <img> 防堆叠过滤。"""
    if not html or "<img" not in html:
        return html
    seen_srcs = set()
    img_pattern = re.compile(r"(<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"][^>]*/?>)", re.I)
    tokens = img_pattern.split(html)
    # split 结果: [text0, full_img1, src1, text1, full_img2, src2, text2, ...]
    out = [tokens[0]]
    last_was_img = False
    i = 1
    while i < len(tokens):
        full_img = tokens[i]
        src = tokens[i + 1]
        after_text = tokens[i + 2] if (i + 2) < len(tokens) else ""
        norm_src = (src or "").split("?")[0].strip()
        if norm_src and norm_src not in seen_srcs and not last_was_img:
            seen_srcs.add(norm_src)
            out.append(full_img)
            last_was_img = True
        # 检查 after_text 是否包含实质正文段落（去掉纯空白或空标签后仍有文字）
        plain_after = re.sub(r"<[^>]+>", "", after_text).strip()
        if len(plain_after) >= 8:
            last_was_img = False
        out.append(after_text)
        i += 3
    return "".join(out)
