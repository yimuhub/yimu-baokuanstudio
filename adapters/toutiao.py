"""今日头条专属排版适配器：原生头条排版规范、两句一断黄金短律、红标导读卡与互动投票模块。"""
from __future__ import annotations
import html
import re
import time


def _format_inline_markdown(text: str) -> str:
    """解析行内 Markdown 语法：加粗、行内代码等。"""
    # 替换加粗 **xxx**
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong style='color:#111;font-weight:700;background:rgba(248,89,89,0.08);padding:1px 4px;border-radius:3px;'>\1</strong>", text)
    return text


def _strip_frontmatter(text: str) -> str:
    """剥离 YAML frontmatter（--- ... --- 开头块）与代码围栏块（``` ... ```）。"""
    # 剥离 YAML frontmatter
    text = re.sub(r"^\s*---[\s\S]*?---\s*\n?", "", text, count=1)
    return text


def _format_toutiao_paragraphs(body_md: str, section_images: list[str] | dict[str, str] | None = None) -> str:
    """将正文解构为符合头条快速滑屏阅读习惯的短律节奏（支持配图卡片与黄金短律）。"""
    body_md = _strip_frontmatter(body_md)
    lines = body_md.strip().splitlines()
    out_lines = []
    sec_idx = 0
    sec_img_list = []
    in_code_fence = False  # 跳过代码围栏块
    if isinstance(section_images, list):
        sec_img_list = list(section_images)
    elif isinstance(section_images, dict):
        sec_img_list = list(section_images.values())

    for ln in lines:
        ln_stripped = ln.strip()
        # 代码围栏开关
        if ln_stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        ln = ln_stripped
        if not ln:
            continue
        # 跳过 Obsidian/GitHub callout 元标记行（[!NOTE] 等）
        if re.match(r"^\[![\w\s]+\]", ln):
            continue

        # 1. 处理 Markdown 图片: ![alt](url)
        img_m = re.match(r"^!\[(.*?)\]\((.*?)\)$", ln)
        if img_m:
            alt, src = img_m.group(1), img_m.group(2)
            cap = f"<div style='font-size:12.5px;color:#888;text-align:center;margin-top:6px;'>{html.escape(alt)}</div>" if alt and alt != "封面" else ""
            out_lines.append(f"<div style='margin:20px 0;text-align:center;'><img src='{html.escape(src)}' style='width:100%;max-width:100%;border-radius:8px;box-shadow:0 4px 14px rgba(0,0,0,0.06);display:block;margin:0 auto;'/>{cap}</div>")
            continue

        # 2. 处理标题
        if ln.startswith("# "):
            continue
        elif ln.startswith("### "):
            sub = html.escape(ln[4:].strip())
            out_lines.append(f"<h3 style='font-size:18px;font-weight:700;color:#222;margin:24px 0 12px;display:flex;align-items:center;gap:8px;'><span style='width:4px;height:18px;background:#f85959;border-radius:2px;display:inline-block;'></span>{sub}</h3>")
            # 自动注入小节配图（若正文无嵌入图片且有可用小节图）
            if "![" not in body_md and sec_idx < len(sec_img_list):
                img_url = sec_img_list[sec_idx]
                out_lines.append(f"<div style='margin:18px 0;text-align:center;'><img src='{html.escape(img_url)}' style='width:100%;max-width:100%;border-radius:8px;box-shadow:0 4px 14px rgba(0,0,0,0.06);display:block;margin:0 auto;'><div style='font-size:12.5px;color:#888;text-align:center;margin-top:6px;'>{sub}</div></div>")
                sec_idx += 1
        elif ln.startswith("## "):
            sub = html.escape(ln[3:].strip())
            out_lines.append(f"<h2 style='font-size:20px;font-weight:800;color:#111;margin:28px 0 14px;display:flex;align-items:center;gap:8px;'><span style='width:5px;height:20px;background:#e23838;border-radius:2px;display:inline-block;'></span>{sub}</h2>")
        elif ln.startswith(">"):
            q = _format_inline_markdown(html.escape(ln.lstrip("> ").strip()))
            out_lines.append(f"<div style='background:#fdf6f6;border-left:4px solid #f85959;border-radius:0 8px 8px 0;padding:12px 16px;margin:16px 0;font-size:15px;color:#444;line-height:1.7;font-style:italic;'>“{q}”</div>")
        elif ln.startswith("- ") or ln.startswith("* "):
            item = _format_inline_markdown(html.escape(ln[2:].strip()))
            out_lines.append(f"<div style='display:flex;align-items:flex-start;gap:8px;margin:8px 0;font-size:16px;color:#333;line-height:1.7;'><span style='color:#f85959;font-weight:bold;'>•</span><span>{item}</span></div>")
        else:
            sentences = re.split(r"(?<=[。！？!?])\s*", ln)
            chunk = []
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                chunk.append(s)
                if len(chunk) >= 2 or len("".join(chunk)) >= 55:
                    p_text = _format_inline_markdown(html.escape(" ".join(chunk)))
                    out_lines.append(f"<p style='font-size:17px;color:#222;line-height:1.85;margin:0 0 16px 0;letter-spacing:0.5px;text-align:justify;'>{p_text}</p>")
                    chunk = []
            if chunk:
                p_text = _format_inline_markdown(html.escape(" ".join(chunk)))
                out_lines.append(f"<p style='font-size:17px;color:#222;line-height:1.85;margin:0 0 16px 0;letter-spacing:0.5px;text-align:justify;'>{p_text}</p>")

    return "\n".join(out_lines)


def render_preview(body_md: str, title: str, author: str = "", topic_tag: str = "",
                   images: list[str] | dict[str, str] | None = None, cover: str | None = None,
                   draft_id: str | None = None) -> str:
    """渲染具备头条原生排版规范的高清排版 HTML（纯净创作者交付版，自动适配高清插图）。"""
    # 自动解析草稿插图
    if draft_id and not images and not cover:
        try:
            from core.imagegen import get_draft_images
            d_imgs = get_draft_images(draft_id)
            cover = d_imgs.get("cover")
            images = d_imgs.get("sections")
        except Exception:
            pass

    first_paras = [p.strip() for p in body_md.splitlines() if p.strip() and not p.startswith("#") and not p.startswith(">") and not p.startswith("[!")]
    lead_text = first_paras[0] if first_paras else ""
    if len(lead_text) > 130:
        lead_text = lead_text[:126] + "…"

    content_html = _format_toutiao_paragraphs(body_md, section_images=images)
    clean_title = re.sub(r"[#*`]", "", title).strip()

    lead_box_html = ""
    if lead_text:
        lead_box_html = f"""
  <div class="tt-lead-box">
    <div style="font-weight:700;color:#e23838;margin-bottom:4px;font-size:14px;display:flex;align-items:center;gap:4px;">
      <span>📌</span> 【核心看点】
    </div>
    <div style="font-size:15px;color:#444;line-height:1.7;">{html.escape(lead_text)}</div>
  </div>"""

    # 封面大图（若正文中未包含图片）
    cover_html = ""
    if cover and "![" not in body_md:
        cover_html = f"""
  <div style="margin:20px 0;text-align:center;">
    <img src="{html.escape(cover)}" style="width:100%;max-width:100%;border-radius:8px;box-shadow:0 4px 14px rgba(0,0,0,0.06);display:block;margin:0 auto;"/>
    <div style="font-size:12.5px;color:#888;text-align:center;margin-top:6px;">封面聚焦</div>
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
    color: #222222;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
    width: 100%;
    overflow-x: hidden;
  }}
  .tt-article-wrap {{
    box-sizing: border-box;
    width: 100%;
    max-width: 680px;
    margin: 0 auto;
    padding: 24px 20px 48px;
    border-top: 4px solid #e23838;
  }}
  .tt-article-wrap * {{ box-sizing: border-box; }}
  .tt-title {{
    font-size: 24px;
    font-weight: 800;
    line-height: 1.4;
    color: #1a1a1a;
    letter-spacing: -0.2px;
    margin: 0 0 20px 0;
    text-align: justify;
  }}
  .tt-lead-box {{
    background: #fdf6f6;
    border-left: 4px solid #e23838;
    border-radius: 0 8px 8px 0;
    padding: 14px 18px;
    margin-bottom: 24px;
  }}
  .tt-content {{
    font-size: 17px;
    line-height: 1.9;
    color: #222;
  }}
  .tt-content img {{
    max-width: 100%;
    border-radius: 8px;
    display: block;
    margin: 16px auto;
  }}
</style>
</head>
<body>
<div class="tt-article-wrap" id="article-content">
  <h1 class="tt-title">{html.escape(clean_title)}</h1>
  {lead_box_html}
  {cover_html}
  <div class="tt-content">
    {content_html}
  </div>
</div>
</body>
</html>
"""

