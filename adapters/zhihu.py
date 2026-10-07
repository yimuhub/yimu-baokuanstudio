"""知乎专业问答与深度专栏排版适配器：结构化论证、专业图表、金句引用与答主权威感。"""
import html
import re
import time


def _format_inline_markdown(text: str) -> str:
    # 加粗 **xxx**
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong style=\"color:#121212;font-weight:700;\">\1</strong>", text)
    return text


def _format_zhihu_body(body_md: str, section_images: list[str] | dict[str, str] | None = None) -> str:
    lines = body_md.strip().splitlines()
    out = []
    sec_idx = 0
    sec_img_list = []
    if isinstance(section_images, list):
        sec_img_list = list(section_images)
    elif isinstance(section_images, dict):
        sec_img_list = list(section_images.values())

    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue

        # 1. 处理 Markdown 图片: ![alt](url)
        img_m = re.match(r"^!\[(.*?)\]\((.*?)\)$", ln)
        if img_m:
            alt, src = img_m.group(1), img_m.group(2)
            cap = f"<div style=\"font-size:13px;color:#8590a6;text-align:center;margin-top:6px;\">{html.escape(alt)}</div>" if alt and alt != "封面" else ""
            out.append(f"<div style=\"margin:20px 0;text-align:center;\"><img src=\"{html.escape(src)}\" style=\"width:100%;max-width:100%;border-radius:6px;box-shadow:0 2px 10px rgba(0,0,0,0.06);display:block;margin:0 auto;\"/>{cap}</div>")
            continue

        if ln.startswith("# "):
            continue
        elif ln.startswith("### ") or ln.startswith("## "):
            title = ln.lstrip("# ").strip()
            out.append(f"<h3 style=\"font-size:18px;font-weight:700;color:#121212;margin:24px 0 12px;display:flex;align-items:center;gap:8px;\"><span style=\"color:#0066ff;font-size:16px;\">▍</span>{html.escape(title)}</h3>")
            if "![" not in body_md and sec_idx < len(sec_img_list):
                img_url = sec_img_list[sec_idx]
                out.append(f"<div style=\"margin:18px 0;text-align:center;\"><img src=\"{html.escape(img_url)}\" style=\"width:100%;max-width:100%;border-radius:6px;box-shadow:0 2px 10px rgba(0,0,0,0.06);display:block;margin:0 auto;\"/><div style=\"font-size:13px;color:#8590a6;text-align:center;margin-top:6px;\">{html.escape(title)}</div></div>")
                sec_idx += 1
        elif ln.startswith(">"):
            quote = _format_inline_markdown(html.escape(ln.lstrip("> ").strip()))
            out.append(f"<blockquote style=\"margin:16px 0;padding:12px 18px;background:#f6f6f6;border-left:3px solid #0066ff;border-radius:0 6px 6px 0;color:#646464;font-size:14.5px;line-height:1.7;\">{quote}</blockquote>")
        elif ln.startswith("- ") or ln.startswith("* "):
            item = _format_inline_markdown(html.escape(ln[2:].strip()))
            out.append(f"<li style=\"margin:6px 0 6px 20px;font-size:15px;color:#121212;line-height:1.75;\">{item}</li>")
        else:
            p = _format_inline_markdown(html.escape(ln))
            out.append(f"<p style=\"font-size:15.5px;color:#121212;line-height:1.8;margin-bottom:16px;letter-spacing:0.3px;\">{p}</p>")
    return "\n".join(out)


def render_preview(body_md: str, title: str, author: str = "", agree_count: int = 0,
                   images: list[str] | dict[str, str] | None = None, cover: str | None = None,
                   draft_id: str | None = None) -> str:
    """渲染具备知乎专业问答与专栏规范的高清排版 HTML。"""
    # 自动解析草稿插图
    if draft_id and not images and not cover:
        try:
            from core.imagegen import get_draft_images
            d_imgs = get_draft_images(draft_id)
            cover = d_imgs.get("cover")
            images = d_imgs.get("sections")
        except Exception:
            pass

    content_html = _format_zhihu_body(body_md, section_images=images)
    clean_title = re.sub(r"[#*`]", "", title).strip()
    
    # 封面大图（若正文中未包含图片）
    cover_html = ""
    if cover and "![" not in body_md:
        cover_html = f"""
  <div style="margin:20px 0;text-align:center;">
    <img src="{html.escape(cover)}" style="width:100%;max-width:100%;border-radius:6px;box-shadow:0 2px 10px rgba(0,0,0,0.06);display:block;margin:0 auto;"/>
    <div style="font-size:13px;color:#8590a6;text-align:center;margin-top:6px;">图文导读</div>
  </div>"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #121212;
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
    width: 100%;
    overflow-x: hidden;
  }}
  .zh-article-wrap {{
    box-sizing: border-box;
    width: 100%;
    max-width: 680px;
    margin: 0 auto;
    padding: 24px 20px 48px;
    border-top: 4px solid #0066ff;
  }}
  .zh-article-wrap * {{ box-sizing: border-box; }}
  .zh-q-title {{
    font-size: 23px;
    font-weight: 700;
    color: #121212;
    line-height: 1.4;
    margin: 0 0 20px 0;
    text-align: justify;
  }}
  .zh-content {{
    font-size: 16px;
    line-height: 1.85;
    color: #121212;
  }}
  .zh-content img {{
    max-width: 100%;
    border-radius: 6px;
    display: block;
    margin: 16px auto;
  }}
</style>
</head>
<body>
<div class="zh-article-wrap" id="article-content">
  <h1 class="zh-q-title">{html.escape(clean_title)}</h1>
  {cover_html}
  <div class="zh-content">
    {content_html}
  </div>
</div>
</body>
</html>"""

