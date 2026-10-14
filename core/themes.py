"""多主题排版引擎（借鉴 mdnice / md2wechat-skill 的行内样式方案）。

公众号：markdown → 微信兼容行内样式 HTML，5 套主题可换肤；
小红书：3 套卡片风格（奶油信息卡/极简蓝白/杂志棕金）。
"""
from __future__ import annotations
import html
import re

# ---------- 公众号主题 ----------
# 每主题一套行内样式：h1/h2/h3/p/li/quote/strong/img

WECHAT_THEMES = {
    "caozhou": {
        "name": "一幕·棕金（默认）",
        "accent": "#b3541e", "h1": "font-size:22px;text-align:center;color:#1a1a1a;margin-bottom:6px;",
        "meta": "text-align:center;color:#999;font-size:13px;margin-bottom:24px;",
        "h2": "margin:30px 0 14px;font-size:18px;color:#1a1a1a;border-left:4px solid #b3541e;padding-left:12px;",
        "h3": "margin:24px 0 12px;font-size:16px;color:#b3541e;font-weight:700;",
        "p": "margin:14px 0;font-size:15px;line-height:1.95;color:#3f3f3f;letter-spacing:.5px;",
        "li": "margin:8px 0;color:#3f3f3f;font-size:15px;line-height:1.8;",
        "quote": "border-left:3px solid #d98324;background:#faf5ec;padding:12px 16px;margin:16px 0;color:#6b5238;font-size:14px;border-radius:0 8px 8px 0;",
        "img": "width:100%;border-radius:12px;margin:18px 0;display:block;",
        "hr": "border:none;border-top:1px dashed #d8c9ae;margin:28px 0;",
    },
    "minimal": {
        "name": "极简黑白",
        "accent": "#111111", "h1": "font-size:21px;text-align:center;color:#111;letter-spacing:2px;",
        "meta": "text-align:center;color:#aaa;font-size:12px;margin-bottom:22px;letter-spacing:3px;",
        "h2": "margin:30px 0 14px;font-size:17px;color:#111;text-align:center;",
        "h3": "margin:22px 0 10px;font-size:15px;color:#333;font-weight:700;",
        "p": "margin:14px 0;font-size:15px;line-height:2;color:#2b2b2b;",
        "li": "margin:7px 0;color:#2b2b2b;font-size:15px;",
        "quote": "border-left:3px solid #111;background:#f7f7f7;padding:12px 16px;margin:16px 0;color:#555;font-size:14px;",
        "img": "width:100%;margin:18px 0;display:block;filter:grayscale(8%);",
        "hr": "border:none;border-top:1px solid #ddd;margin:26px auto;width:40%;",
    },
    "blue": {
        "name": "蓝色科技",
        "accent": "#2563eb", "h1": "font-size:22px;text-align:center;color:#0f172a;",
        "meta": "text-align:center;color:#64748b;font-size:13px;margin-bottom:24px;",
        "h2": "margin:30px 0 14px;font-size:18px;color:#0f172a;background:#eff6ff;padding:8px 14px;border-radius:8px;",
        "h3": "margin:22px 0 10px;font-size:16px;color:#2563eb;font-weight:700;",
        "p": "margin:14px 0;font-size:15px;line-height:1.9;color:#334155;",
        "li": "margin:7px 0;color:#334155;font-size:15px;",
        "quote": "border-left:3px solid #2563eb;background:#f0f7ff;padding:12px 16px;margin:16px 0;color:#1e40af;font-size:14px;",
        "img": "width:100%;border-radius:12px;margin:18px 0;display:block;box-shadow:0 4px 14px rgba(37,99,235,.12);",
        "hr": "border:none;border-top:1px solid #dbeafe;margin:26px 0;",
    },
    "fresh": {
        "name": "绿色清新",
        "accent": "#2e7d52", "h1": "font-size:22px;text-align:center;color:#1b3a2a;",
        "meta": "text-align:center;color:#8aa394;font-size:13px;margin-bottom:24px;",
        "h2": "margin:30px 0 14px;font-size:18px;color:#1b3a2a;border-bottom:2px solid #cfe7d8;padding-bottom:8px;",
        "h3": "margin:22px 0 10px;font-size:16px;color:#2e7d52;font-weight:700;",
        "p": "margin:14px 0;font-size:15px;line-height:1.95;color:#37493e;",
        "li": "margin:7px 0;color:#37493e;font-size:15px;",
        "quote": "border-left:3px solid #2e7d52;background:#f2faf5;padding:12px 16px;margin:16px 0;color:#2f5d43;font-size:14px;",
        "img": "width:100%;border-radius:14px;margin:18px 0;display:block;",
        "hr": "border:none;border-top:1px dashed #bcd9c6;margin:26px 0;",
    },
    "warm": {
        "name": "暖橙文艺",
        "accent": "#c2410c", "h1": "font-size:22px;text-align:center;color:#3b2412;",
        "meta": "text-align:center;color:#b08968;font-size:13px;margin-bottom:24px;font-style:italic;",
        "h2": "margin:30px 0 14px;font-size:18px;color:#7c3a12;",
        "h3": "margin:22px 0 10px;font-size:16px;color:#c2410c;font-weight:700;",
        "p": "margin:14px 0;font-size:15px;line-height:2;color:#5c4433;",
        "li": "margin:7px 0;color:#5c4433;font-size:15px;",
        "quote": "border-left:3px solid #e8a662;background:#fdf6ee;padding:12px 16px;margin:16px 0;color:#8a5a2e;font-size:14px;",
        "img": "width:100%;border-radius:16px;margin:18px 0;display:block;",
        "hr": "border:none;border-top:1px dashed #e3c9a8;margin:26px 0;",
    },
}

DEFAULT_THEME = "caozhou"


def _inline_md(text: str, st: dict) -> str:
    """行内元素：**粗体**、`code`、[链接](url)。"""
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*",
                  rf"<strong style='color:{st['accent']};font-weight:700;'>\1</strong>", text)
    text = re.sub(r"`(.+?)`",
                  "<code style='background:#f3ede2;padding:1px 6px;border-radius:4px;font-size:13px;'>\\1</code>",
                  text)
    return text


def clean_markdown_body(text: str) -> str:
    """全面清洗大模型生成的 Markdown 正文，彻底剥离思考标签、代码块围栏与 YAML frontmatter。"""
    if not text:
        return ""
    # 剥离思考标签 <think>...</think>
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    # 剥离开头的 YAML frontmatter
    text = re.sub(r"^\s*---[\s\S]*?---\s*\n?", "", text)
    # 剥离外层包裹的 ```markdown / ```html / ```
    text = re.sub(r"^\s*```(?:markdown|md|html)?\s*\n", "", text, flags=re.I)
    text = re.sub(r"\n\s*```\s*$", "", text)
    return text.strip()


def list_themes() -> dict[str, dict]:
    """返回所有已注册的公众号主题。"""
    return dict(WECHAT_THEMES)


def get_theme(theme_key: str) -> dict:
    """按标识获取公众号主题，回退至默认主题。"""
    return WECHAT_THEMES.get(theme_key, WECHAT_THEMES[DEFAULT_THEME])


def _dedupe_wechat_html_images(html_str: str) -> str:
    """对公众号 HTML 中的 <img> 进行 URL 全局去重与冗余空标签清理。"""
    if not html_str or "<img" not in html_str:
        return html_str
    seen_srcs = set()
    img_pattern = re.compile(r"(<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"][^>]*/?>)", re.I)
    tokens = img_pattern.split(html_str)
    out = [tokens[0]]
    i = 1
    while i < len(tokens):
        full_img = tokens[i]
        src = tokens[i + 1]
        after_text = tokens[i + 2] if (i + 2) < len(tokens) else ""
        norm_src = (src or "").split("?")[0].strip().rstrip("/")
        if norm_src and norm_src not in seen_srcs:
            seen_srcs.add(norm_src)
            out.append(full_img)
        out.append(after_text)
        i += 3
    res = "".join(out)
    return re.sub(r"<p\b[^>]*>\s*</p>", "", res)


def md_to_wechat_html(body_md: str, title: str, theme: str = DEFAULT_THEME,
                      meta: str = "一幕·YIMU 爆款工作室", images: dict | None = None,
                      theme_key: str | None = None, cover: str | None = None,
                      **kwargs) -> str:
    """markdown → 微信兼容行内样式 HTML（内置全链路图片防重复与防连贴守卫）。"""
    actual_theme = theme_key or theme or DEFAULT_THEME
    body_md = clean_markdown_body(body_md)
    st = WECHAT_THEMES.get(actual_theme, WECHAT_THEMES[DEFAULT_THEME])

    # 提取正文中已包含的所有图片 URL（防重复注入）
    seen_img_urls: set[str] = set()
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)|<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", body_md, re.I):
        u = (m.group(1) or m.group(2) or "").strip()
        if u:
            seen_img_urls.add(u.split("?")[0].strip().rstrip("/"))

    effective_images: dict[str, str] = {}
    if images:
        for k, v in images.items():
            if not v:
                continue
            norm_v = v.split("?")[0].strip().rstrip("/")
            # 如果该图片已经在 Markdown 正文中显式包含，则绝不在段落中再次重复注入
            if norm_v not in seen_img_urls:
                effective_images[k] = v

    out, in_list, cur_section = [], False, None
    in_code_fence = False
    emitted_srcs: set[str] = set()

    for ln in body_md.strip().splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        # 跳过 Obsidian/GitHub callout 元标记行（[!NOTE] 等）
        if re.match(r"^\[![\w\s]+\]", s):
            continue
        if s.startswith("### "):
            if in_list:
                out.append("</ul>"); in_list = False
            cur_section = s[4:].strip()
            out.append(f"<h3 style='{st['h3']}'>{_inline_md(cur_section, st)}</h3>")
        elif s.startswith("## "):
            if in_list:
                out.append("</ul>"); in_list = False
            cur_section = s[3:].strip()
            out.append(f"<h2 style='{st['h2']}'>{_inline_md(cur_section, st)}</h2>")
        elif s.startswith("# "):
            if in_list:
                out.append("</ul>"); in_list = False
            cur_section = s[2:].strip()
            out.append(f"<h2 style='{st['h2']}'>{_inline_md(cur_section, st)}</h2>")
        elif s.startswith("- ") or s.startswith("• "):
            if not in_list:
                out.append("<ul style='padding-left:22px;margin:10px 0;'>"); in_list = True
            out.append(f"<li style='{st['li']}'>{_inline_md(s[2:], st)}</li>")
        elif s.startswith("> "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<blockquote style='{st['quote']}'>{_inline_md(s[2:], st)}</blockquote>")
        elif s == "---":
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<hr style='{st['hr']}'/>")
        elif s.startswith("![") or s.startswith("<img"):
            if in_list:
                out.append("</ul>"); in_list = False
            img_src = ""
            if s.startswith("!["):
                m = re.search(r"\((.+?)\)", s)
                if m:
                    img_src = m.group(1).strip()
            elif "<img" in s:
                m = re.search(r"""src=['"]([^'"]+)['"]""", s, re.I)
                if m:
                    img_src = m.group(1).strip()
            if img_src:
                norm_s = img_src.split("?")[0].strip().rstrip("/")
                if norm_s not in emitted_srcs:
                    emitted_srcs.add(norm_s)
                    out.append(f"<img src='{img_src}' style='{st['img']}'/>")
        else:
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<p style='{st['p']}'>{_inline_md(s, st)}</p>")
            if effective_images and cur_section in effective_images:
                sec_img = effective_images.pop(cur_section)
                norm_sec = sec_img.split("?")[0].strip().rstrip("/")
                if norm_sec not in emitted_srcs:
                    emitted_srcs.add(norm_sec)
                    out.append(f"<img src='{sec_img}' style='{st['img']}'/>")

    if in_list:
        out.append("</ul>")
    body = "".join(out)

    # 封面图智能补充注入（仅当文章正文尚未包含封面时才在导语后插入）
    if cover:
        norm_cov = cover.split("?")[0].strip().rstrip("/")
        if norm_cov not in emitted_srcs and norm_cov not in body:
            emitted_srcs.add(norm_cov)
            cov_html = f"<img src='{cover}' style='{st['img']}'/>"
            p_idx = body.find("</p>")
            if p_idx != -1:
                body = body[:p_idx + 4] + cov_html + body[p_idx + 4:]
            else:
                body = cov_html + body

    final_html = (f"<!doctype html><meta charset='utf-8'>"
                  f"<div style='max-width:677px;margin:0 auto;padding:26px 24px;"
                  f"font-family:-apple-system,'PingFang SC',sans-serif;background:#fff;"
                  f"border-top:4px solid {st['accent']};'>"
                  f"<h1 style='{st['h1']}'>{html.escape(title)}</h1>"
                  f"<p style='{st['meta']}'>{html.escape(meta)} · {__import__('time').strftime('%Y-%m-%d')}</p>"
                  f"{body}</div>")

    return _dedupe_wechat_html_images(final_html)


# ---------- 小红书卡片风格 ----------

XHS_CARD_STYLES = {
    "magazine": {
        "name": "棕金杂志（推荐·经典排版）",
        "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Serif SC',serif; background:#f4f1ea; }
.card { width:1080px; height:1440px; padding:88px 80px; display:flex; flex-direction:column;
        background:linear-gradient(160deg,#fdfbf7 0%,#f6efe3 100%); position:relative; overflow:hidden; }
.card::before { content:''; position:absolute; top:0; left:0; right:0; height:14px;
        background:linear-gradient(90deg,#b3541e,#d98324,#b3541e); }
.kicker { font-size:30px; letter-spacing:8px; color:#b3541e; font-weight:600; margin-bottom:36px; }
.title { font-size:78px; line-height:1.28; color:#2b2018; font-weight:700; margin-bottom:44px; }
.divider { width:120px; height:6px; background:#b3541e; margin-bottom:44px; }
.body { font-size:36px; line-height:1.9; color:#4a3b2c; flex:1; }
.body p { margin-bottom:30px; }
.body b { color:#b3541e; }
.footer { display:flex; justify-content:space-between; align-items:center;
          font-size:26px; color:#8a7a66; border-top:2px solid #e3d9c8; padding-top:32px; }
.badge { background:#b3541e; color:#fff; padding:8px 26px; border-radius:999px; font-size:26px; }
.cover .title { font-size:92px; }""",
        "accent": "#b3541e",
    },
    "ai_visual_dark": {
        "name": "✨ AI 电影画报（暗色质感视觉）",
        "accent": "#FF2442",
        "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Sans SC',sans-serif; background:#0b0f19; }
.card { width:1080px; height:1440px; padding:80px 72px; display:flex; flex-direction:column;
        background:#0b0f19; color:#f8fafc; position:relative; overflow:hidden; }
.visual-bg-img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; z-index:1; filter:brightness(0.85) contrast(1.08); }
.scrim-dark { position:absolute; inset:0; z-index:2;
             background:linear-gradient(180deg, rgba(8,11,18,0.36) 0%, rgba(8,11,18,0.56) 35%, rgba(8,11,18,0.76) 75%, rgba(8,11,18,0.86) 100%); }
.visual-content { position:relative; z-index:3; display:flex; flex-direction:column; height:100%; }
.kicker { font-size:26px; font-weight:700; color:#fff; background:rgba(255,36,66,0.95); backdrop-filter:blur(12px);
          padding:8px 24px; border-radius:999px; margin-bottom:36px; align-self:flex-start; letter-spacing:4px;
          box-shadow:0 4px 16px rgba(255,36,66,0.35); }
.title { font-size:78px; line-height:1.24; font-weight:900; color:#ffffff; margin-bottom:36px;
         text-shadow:0 4px 28px rgba(0,0,0,0.98), 0 2px 8px rgba(0,0,0,0.9); }
.divider { width:140px; height:6px; background:#ff2442; border-radius:3px; margin-bottom:36px; }
.body { font-size:36px; line-height:1.85; color:#ffffff; flex:1; }
.body p { margin-bottom:24px; background:rgba(12,18,32,0.65); backdrop-filter:blur(16px);
          border:1.5px solid rgba(255,255,255,0.25); border-radius:20px; padding:24px 30px;
          box-shadow:0 8px 32px rgba(0,0,0,0.5); text-shadow:0 2px 6px rgba(0,0,0,0.9); }
.body b { color:#ff6b4a; font-weight:800; }
.footer { display:flex; justify-content:space-between; align-items:center; font-size:26px; color:#cbd5e1;
          border-top:1px solid rgba(255,255,255,0.25); padding-top:28px; margin-top:auto;
          text-shadow:0 2px 4px rgba(0,0,0,0.8); }
.badge { background:linear-gradient(135deg,#ff2442,#ff6b4a); color:#fff; padding:8px 26px;
         border-radius:999px; font-size:26px; font-weight:700; box-shadow:0 4px 16px rgba(255,36,66,0.4); }
.cover .title { font-size:94px; line-height:1.18; }""",
    },
    "ai_visual_light": {
        "name": "✨ AI 暖光画报（浅色优雅视觉）",
        "accent": "#B3541E",
        "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Noto Serif SC','Songti SC','PingFang SC',serif; background:#fdfbf7; }
.card { width:1080px; height:1440px; padding:80px 72px; display:flex; flex-direction:column;
        background:#fdfbf7; color:#2b2018; position:relative; overflow:hidden; }
.visual-bg-img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; z-index:1; filter:brightness(0.95); }
.scrim-light { position:absolute; inset:0; z-index:2;
              background:linear-gradient(180deg, rgba(253,251,247,0.55) 0%, rgba(253,251,247,0.75) 35%, rgba(253,251,247,0.88) 75%, rgba(253,251,247,0.95) 100%); }
.visual-content { position:relative; z-index:3; display:flex; flex-direction:column; height:100%; }
.kicker { font-size:26px; font-weight:700; color:#fff; background:#b3541e;
          padding:8px 24px; border-radius:8px; margin-bottom:36px; align-self:flex-start; letter-spacing:4px; }
.title { font-size:78px; line-height:1.25; font-weight:800; color:#2b2018; margin-bottom:36px;
         text-shadow:0 2px 8px rgba(255,255,255,0.8); }
.divider { width:120px; height:6px; background:#b3541e; margin-bottom:36px; }
.body { font-size:36px; line-height:1.85; color:#4a3b2c; flex:1; }
.body p { margin-bottom:24px; background:rgba(255,255,255,0.75); backdrop-filter:blur(14px);
          border:1px solid rgba(234,221,207,0.9); border-radius:20px; padding:22px 28px;
          box-shadow:0 8px 24px rgba(180,120,80,0.12); }
.body b { color:#b3541e; font-weight:800; }
.footer { display:flex; justify-content:space-between; align-items:center; font-size:26px; color:#8a7a66;
          border-top:2px solid #e3d9c8; padding-top:28px; margin-top:auto; }
.badge { background:#b3541e; color:#fff; padding:8px 26px; border-radius:999px; font-size:26px; font-weight:700; }
.cover .title { font-size:92px; line-height:1.18; }""",
    },
    "ai_visual_split": {
        "name": "✨ AI 杂志画报（全幅磨砂融合）",
        "accent": "#FF2442",
        "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Sans SC',sans-serif; background:#0b0f19; }
.card { width:1080px; height:1440px; padding:80px 72px; display:flex; flex-direction:column;
        background:#0b0f19; color:#f8fafc; position:relative; overflow:hidden; }
.visual-bg-img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; z-index:1; filter:brightness(0.85) contrast(1.08); }
.scrim-dark { position:absolute; inset:0; z-index:2;
             background:linear-gradient(180deg, rgba(8,11,18,0.36) 0%, rgba(8,11,18,0.56) 35%, rgba(8,11,18,0.76) 75%, rgba(8,11,18,0.86) 100%); }
.visual-content { position:relative; z-index:3; display:flex; flex-direction:column; height:100%; }
.kicker { font-size:26px; font-weight:700; color:#fff; background:rgba(255,36,66,0.95); backdrop-filter:blur(12px);
          padding:8px 24px; border-radius:999px; margin-bottom:36px; align-self:flex-start; letter-spacing:4px;
          box-shadow:0 4px 16px rgba(255,36,66,0.35); }
.title { font-size:78px; line-height:1.24; font-weight:900; color:#ffffff; margin-bottom:36px;
         text-shadow:0 4px 28px rgba(0,0,0,0.98), 0 2px 8px rgba(0,0,0,0.9); }
.divider { width:140px; height:6px; background:#ff2442; border-radius:3px; margin-bottom:36px; }
.body { font-size:36px; line-height:1.85; color:#ffffff; flex:1; }
.body p { margin-bottom:24px; background:rgba(12,18,32,0.65); backdrop-filter:blur(16px);
          border:1.5px solid rgba(255,255,255,0.25); border-radius:20px; padding:24px 30px;
          box-shadow:0 8px 32px rgba(0,0,0,0.5); text-shadow:0 2px 6px rgba(0,0,0,0.9); }
.body b { color:#ff6b4a; font-weight:800; }
.footer { display:flex; justify-content:space-between; align-items:center; font-size:26px; color:#cbd5e1;
          border-top:1px solid rgba(255,255,255,0.25); padding-top:28px; margin-top:auto;
          text-shadow:0 2px 4px rgba(0,0,0,0.8); }
.badge { background:linear-gradient(135deg,#ff2442,#ff6b4a); color:#fff; padding:8px 26px;
         border-radius:999px; font-size:26px; font-weight:700; box-shadow:0 4px 16px rgba(255,36,66,0.4); }
.cover .title { font-size:94px; line-height:1.18; }""",
    },
    "cyber_neon": {
        "name": "赛博霓虹（科技极客）",
        "accent": "#00F0FF",
        "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Sans SC',sans-serif; background:#05070d; }
.card { width:1080px; height:1440px; padding:88px 76px; display:flex; flex-direction:column;
        background:#05070d; color:#e2e8f0; border:4px solid #00f0ff; box-shadow:inset 0 0 40px rgba(0,240,255,0.15); overflow:hidden; }
.kicker { font-size:28px; letter-spacing:8px; color:#00f0ff; font-weight:800; margin-bottom:40px; text-shadow:0 0 16px rgba(0,240,255,0.6); }
.title { font-size:86px; line-height:1.2; font-weight:900; color:#ffffff; margin-bottom:44px; text-shadow:0 0 20px rgba(0,240,255,0.4); }
.divider { width:160px; height:6px; background:linear-gradient(90deg,#00f0ff,#ff007f); margin-bottom:44px; }
.body { font-size:36px; line-height:1.85; flex:1; }
.body p { margin-bottom:28px; background:rgba(15,23,42,0.8); border:1px solid rgba(0,240,255,0.3); border-radius:14px; padding:22px 28px; }
.body b { color:#00f0ff; font-weight:800; }
.footer { display:flex; justify-content:space-between; font-size:26px; color:#64748b; border-top:1px solid #1e293b; padding-top:28px; margin-top:auto; }
.badge { background:#ff007f; color:#fff; padding:8px 26px; border-radius:4px; font-size:26px; font-weight:800; }
.cover .title { font-size:110px; }""",
    },
    "editorial_clean": {
        "name": "极简画廊（艺术大字）",
        "accent": "#000000",
        "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Noto Serif SC','Songti SC',serif; background:#FBF9F5; }
.card { width:1080px; height:1440px; padding:110px 96px; display:flex; flex-direction:column;
        background:#FBF9F5; color:#111111; }
.kicker { font-size:26px; letter-spacing:10px; color:#777777; margin-bottom:52px; }
.title { font-size:94px; line-height:1.2; font-weight:400; color:#111111; margin-bottom:48px; }
.divider { width:60px; height:4px; background:#111111; margin-bottom:48px; }
.body { font-size:36px; line-height:2.0; flex:1; color:#333333; }
.body p { margin-bottom:34px; }
.body b { color:#111111; font-weight:700; }
.footer { display:flex; justify-content:space-between; font-size:26px; color:#777777; border-top:2px solid #111111; padding-top:30px; margin-top:auto; }
.badge { border:2px solid #111111; color:#111111; padding:6px 24px; font-size:24px; }
.cover .title { font-size:120px; }""",
    },
    "cream": {
        "name": "奶油信息卡",
        "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC',sans-serif; background:#fff8f0; }
.card { width:1080px; height:1440px; padding:90px 84px; display:flex; flex-direction:column;
        background:#fffdf9; border-radius:48px; box-shadow:0 20px 60px rgba(210,160,120,.18);
        border:2px solid #ffe8d2; overflow:hidden; }
.kicker { font-size:28px; color:#e8965a; background:#fff1e3; display:inline-block;
          padding:10px 30px; border-radius:999px; margin-bottom:40px; align-self:flex-start; }
.title { font-size:74px; line-height:1.3; color:#5a3825; font-weight:800; margin-bottom:40px; }
.body { font-size:35px; line-height:1.9; color:#7a5c48; flex:1; }
.body p { margin-bottom:28px; background:#fff6ec; border-radius:20px; padding:20px 26px; }
.footer { font-size:26px; color:#c9a88d; text-align:center; }
.cover .title { font-size:88px; }""",
        "accent": "#e8965a",
    },
    "blueprint": {
        "name": "极简蓝白文档卡",
        "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC',sans-serif; background:#eef3f8; }
.card { width:1080px; height:1440px; padding:90px 84px; display:flex; flex-direction:column;
        background:#ffffff; border-top:16px solid #2563eb; overflow:hidden; }
.kicker { font-size:28px; letter-spacing:6px; color:#2563eb; font-weight:700; margin-bottom:40px; }
.title { font-size:76px; line-height:1.3; color:#0f172a; font-weight:800; margin-bottom:36px; }
.body { font-size:35px; line-height:1.85; color:#334155; flex:1; }
.body p { margin-bottom:28px; padding-left:26px; border-left:6px solid #dbeafe; }
.footer { display:flex; justify-content:space-between; font-size:26px; color:#94a3b8;
          border-top:1px solid #e2e8f0; padding-top:30px; }
.cover .title { font-size:90px; }""",
        "accent": "#2563eb",
    },
}

XHS_CARD_STYLES["warmeditorial"] = {
    "name": "暖纸编辑感（borrowed: card-layout/warm-editorial）",
    "accent": "#B85C44",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Noto Serif SC','Songti SC',serif; background:#EFE9DC; }
.card { width:1080px; height:1440px; padding:100px 90px; display:flex; flex-direction:column;
        background:#EFE9DC; color:#1F1B16; }
.kicker { font-size:28px; letter-spacing:6px; color:#B85C44; margin-bottom:44px; }
.title { font-size:96px; line-height:1.15; font-weight:400; color:#1F1B16; margin-bottom:48px; }
.divider { width:88px; height:5px; background:#B85C44; margin-bottom:48px; }
.body { font-size:38px; line-height:1.85; flex:1; }
.body p { margin-bottom:36px; }
.body b { color:#B85C44; font-weight:400; }
.footer { display:flex; justify-content:space-between; font-size:27px; color:#B85C44;
          border-top:2px solid #1F1B16; padding-top:30px; letter-spacing:.05em; }
.badge { border:2px solid #B85C44; color:#B85C44; padding:6px 24px; border-radius:999px; font-size:26px; }
.cover .title { font-size:128px; line-height:1.08; }""",
}
XHS_CARD_STYLES["boldposter"] = {
    "name": "大字报（borrowed: card-layout/bold-poster）",
    "accent": "#F5D300",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Sans SC',sans-serif; background:#141414; }
.card { width:1080px; height:1440px; padding:96px 84px; display:flex; flex-direction:column;
        background:#141414; color:#F2F0EA; }
.kicker { font-size:30px; letter-spacing:8px; color:#F5D300; font-weight:700; margin-bottom:44px; }
.title { font-size:110px; line-height:1.12; font-weight:800; margin-bottom:48px; }
.divider { width:100%; height:3px; background:#F5D300; margin-bottom:44px; }
.body { font-size:40px; line-height:1.8; flex:1; }
.body p { margin-bottom:34px; }
.body b { color:#F5D300; font-weight:700; }
.footer { display:flex; justify-content:space-between; font-size:26px; color:#8a8a8a;
          border-top:1px solid #333; padding-top:30px; }
.badge { background:#F5D300; color:#141414; padding:8px 26px; border-radius:999px; font-size:26px; font-weight:700; }
.cover .title { font-size:150px; line-height:1.05; }""",
}
XHS_CARD_STYLES["bauhaus"] = {
    "name": "包豪斯（borrowed: card-layout/bauhaus）",
    "accent": "#E2412B",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Sans SC',sans-serif; background:#EFE9DC; }
.card { width:1080px; height:1440px; padding:90px 80px; display:flex; flex-direction:column;
        background:#EFE9DC; color:#1A1A1A; border-top:28px solid #E2412B;
        border-bottom:28px solid #2B57C4; }
.kicker { font-size:28px; letter-spacing:8px; font-weight:700; color:#2B57C4; margin-bottom:44px; }
.title { font-size:100px; line-height:1.15; font-weight:800; margin-bottom:48px; }
.divider { width:160px; height:22px; background:#F2C200; margin-bottom:48px; }
.body { font-size:38px; line-height:1.8; flex:1; }
.body p { margin-bottom:32px; }
.body b { color:#E2412B; font-weight:700; }
.footer { display:flex; justify-content:space-between; font-size:26px; color:#1A1A1A; font-weight:700;
          border-top:4px solid #1A1A1A; padding-top:28px; }
.badge { background:#E2412B; color:#fff; padding:8px 26px; border-radius:0; font-size:26px; font-weight:700; }
.cover .title { font-size:130px; }""",
}
XHS_CARD_STYLES["memphis"] = {
    "name": "孟菲斯撞色（borrowed: card-layout/memphis）",
    "accent": "#FF6B4A",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Sans SC',sans-serif; background:#F7F2E7; }
.card { width:1080px; height:1440px; padding:90px 80px; display:flex; flex-direction:column;
        background:#F7F2E7; color:#1C1C1C; position:relative; overflow:hidden; }
.card::before { content:''; position:absolute; top:-60px; right:-60px; width:260px; height:260px;
                border-radius:50%; background:#27C2B0; opacity:.9; }
.card::after { content:''; position:absolute; bottom:-40px; left:-40px; width:200px; height:200px;
               background:#FFD23F; transform:rotate(18deg); }
.kicker { font-size:28px; font-weight:700; color:#FF6FB5; letter-spacing:6px; margin-bottom:44px; position:relative; z-index:2; }
.title { font-size:92px; line-height:1.2; font-weight:800; margin-bottom:48px; position:relative; z-index:2; }
.divider { width:140px; height:12px; background:#FF6B4A; border-radius:99px; margin-bottom:48px; position:relative; z-index:2; }
.body { font-size:38px; line-height:1.8; flex:1; position:relative; z-index:2; }
.body p { margin-bottom:30px; }
.body b { color:#27C2B0; font-weight:700; }
.footer { display:flex; justify-content:space-between; font-size:26px; color:#1C1C1C; font-weight:700;
          border-top:3px dashed #FF6FB5; padding-top:28px; position:relative; z-index:2; }
.badge { background:#FFD23F; color:#1C1C1C; padding:8px 26px; border-radius:999px; font-size:26px; font-weight:700; }
.cover .title { font-size:120px; }""",
}
XHS_CARD_STYLES["minimalquiet"] = {
    "name": "极简安静（borrowed: card-layout/minimal-quiet）",
    "accent": "#9A6B4F",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Sans SC',sans-serif; background:#FAF8F3; }
.card { width:1080px; height:1440px; padding:120px 100px; display:flex; flex-direction:column;
        background:#FAF8F3; color:#2A2A28; }
.kicker { font-size:26px; letter-spacing:10px; color:#B4AEA2; margin-bottom:60px; }
.title { font-size:76px; line-height:1.3; font-weight:600; margin-bottom:40px; }
.divider { width:44px; height:3px; background:#9A6B4F; margin-bottom:60px; }
.body { font-size:34px; line-height:2.1; flex:1; color:#55524C; }
.body p { margin-bottom:36px; }
.body b { color:#9A6B4F; font-weight:600; }
.footer { font-size:24px; color:#B4AEA2; border-top:1px solid #E5E0D6; padding-top:30px;
          display:flex; justify-content:space-between; }
.badge { border:1px solid #9A6B4F; color:#9A6B4F; padding:6px 22px; border-radius:0; font-size:24px; }
.cover .title { font-size:96px; line-height:1.25; }""",
}
XHS_CARD_STYLES["neobrutalism"] = {
    "name": "新粗野主义（borrowed: card-layout/neo-brutalism）",
    "accent": "#FFD23F",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Noto Sans SC',sans-serif; background:#F4EFDF; }
.card { width:1080px; height:1440px; padding:90px 80px; display:flex; flex-direction:column;
        background:#F4EFDF; color:#111; }
.kicker { display:inline-block; font-size:28px; font-weight:800; background:#4ECDC4; color:#111;
          padding:10px 28px; border:4px solid #111; box-shadow:8px 8px 0 #111; margin-bottom:48px;
          align-self:flex-start; }
.title { font-size:94px; line-height:1.18; font-weight:900; margin-bottom:52px; }
.divider { width:120px; height:0; border-bottom:6px solid #111; margin-bottom:52px; }
.body { font-size:38px; line-height:1.85; flex:1; }
.body p { margin-bottom:32px; background:#fff; border:4px solid #111; box-shadow:10px 10px 0 #111;
          padding:22px 26px; }
.body b { background:#FFD23F; padding:0 8px; font-weight:800; }
.footer { display:flex; justify-content:space-between; font-size:26px; font-weight:800;
          border-top:4px solid #111; padding-top:28px; }
.badge { background:#FF5CA8; color:#111; border:4px solid #111; padding:6px 24px; font-size:26px; font-weight:800; }
.cover .title { font-size:122px; }""",
}
XHS_CARD_STYLES["swissgrid"] = {
    "name": "瑞士网格（borrowed: card-layout/swiss-grid）",
    "accent": "#E2231A",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Helvetica Neue','PingFang SC','Noto Sans SC',sans-serif; background:#F2F0EA; }
.card { width:1080px; height:1440px; padding:96px 90px; display:flex; flex-direction:column;
        background:#F2F0EA; color:#141414; }
.kicker { font-size:28px; font-weight:700; letter-spacing:4px; color:#141414;
          border-bottom:3px solid #141414; padding-bottom:20px; margin-bottom:52px; }
.title { font-size:104px; line-height:1.12; font-weight:800; margin-bottom:52px; }
.title b { color:#E2231A; }
.divider { width:64px; height:8px; background:#E2231A; margin-bottom:52px; }
.body { font-size:36px; line-height:1.85; flex:1; }
.body p { margin-bottom:32px; padding-top:24px; border-top:2px solid #141414; }
.body b { color:#E2231A; font-weight:800; }
.footer { display:flex; justify-content:space-between; font-size:26px; font-weight:700;
          border-top:3px solid #141414; padding-top:28px; }
.badge { background:#E2231A; color:#fff; padding:8px 26px; font-size:26px; font-weight:700; }
.cover .title { font-size:126px; }""",
}
XHS_CARD_STYLES["typewriter"] = {
    "name": "打字机备忘（borrowed: card-layout/typewriter-memo）",
    "accent": "#B23A2E",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Courier New','PingFang SC',monospace; background:#F1ECDD; }
.card { width:1080px; height:1440px; padding:100px 90px; display:flex; flex-direction:column;
        background:repeating-linear-gradient(0deg,#F1ECDD,#F1ECDD 46px,#EAE4D3 47px);
        color:#2B2824; border:1px solid #C9C0A8; }
.kicker { font-size:28px; letter-spacing:4px; color:#9C9484; margin-bottom:48px; }
.title { font-size:84px; line-height:1.25; font-weight:700; margin-bottom:48px; }
.divider { width:110px; border-bottom:4px double #B23A2E; margin-bottom:48px; }
.body { font-size:36px; line-height:1.9; flex:1; letter-spacing:.5px; }
.body p { margin-bottom:32px; }
.body b { color:#B23A2E; font-weight:700; }
.footer { display:flex; justify-content:space-between; font-size:26px; color:#9C9484;
          border-top:2px dashed #B23A2E; padding-top:30px; }
.badge { border:3px solid #B23A2E; color:#B23A2E; padding:6px 22px; border-radius:8px;
         font-size:26px; font-weight:700; transform:rotate(-3deg); }
.cover .title { font-size:104px; }""",
}
XHS_CARD_STYLES["vintagecollage"] = {
    "name": "复古拼贴（borrowed: card-layout/vintage-collage）",
    "accent": "#D8F24A",
    "css": """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Songti SC','Noto Serif SC',serif; background:#F1EEE3; }
.card { width:1080px; height:1440px; padding:96px 88px; display:flex; flex-direction:column;
        background:#F1EEE3; color:#1A1A1A; }
.kicker { font-size:28px; letter-spacing:6px; color:#8A857A; margin-bottom:48px; }
.title { font-size:92px; line-height:1.22; font-weight:700; margin-bottom:48px; }
.divider { width:120px; height:16px; background:#D8F24A; margin-bottom:48px; }
.body { font-size:38px; line-height:1.9; flex:1; }
.body p { margin-bottom:34px; }
.body b { background:linear-gradient(transparent 55%, #D8F24A 55%); padding:0 6px; font-weight:700; }
.footer { display:flex; justify-content:space-between; font-size:26px; color:#8A857A;
          border-top:2px solid #8A857A; padding-top:28px; }
.badge { background:#1A1A1A; color:#F1EEE3; padding:8px 26px; font-size:26px; }
.cover .title { font-size:118px; }""",
}
DEFAULT_CARD_STYLE = "ai_visual_dark"
