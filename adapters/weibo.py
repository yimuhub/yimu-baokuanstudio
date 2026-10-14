"""微博 / 即刻快讯排版适配器：短平快爆点、话题标签、情绪张力与碎片化阅读适配。"""
from __future__ import annotations
import html
import re
import time


def render_preview(body_md: str, title: str, author: str = "热点观察台", topic_tags: list = None,
                   images: list[str] | dict[str, str] | None = None, cover: str | None = None,
                   draft_id: str | None = None) -> str:
    """渲染微博/即刻快讯排版（自适应图文九宫格、话题标签与精炼爆点）。"""
    topic_tags = topic_tags or ["热点观察", "干货分享", "趋势解读"]
    
    # 1. 提取所有可用图片
    all_img_urls = []
    if "![" in body_md:
        all_img_urls.extend([src for _, src in re.findall(r"!\[(.*?)\]\((.*?)\)", body_md)])

    if cover and cover not in all_img_urls:
        all_img_urls.append(cover)

    if isinstance(images, list):
        for u in images:
            if u not in all_img_urls:
                all_img_urls.append(u)
    elif isinstance(images, dict):
        for u in images.values():
            if u not in all_img_urls:
                all_img_urls.append(u)

    if draft_id and not all_img_urls:
        try:
            from core.imagegen import get_draft_images
            d_imgs = get_draft_images(draft_id)
            for u in d_imgs.get("all", []):
                if u not in all_img_urls:
                    all_img_urls.append(u)
        except Exception:
            pass

    # 2. 提炼适合微博传播的正文段落（去重与呼吸感）
    paras = []
    for p in body_md.splitlines():
        p = p.strip()
        if not p or p.startswith("#") or p.startswith("[!"):
            continue
        paras.append(p)

    summary_text = "\n\n".join(paras[:6]) if paras else body_md[:400]
    
    # 解析加粗
    summary_html = html.escape(summary_text)
    summary_html = re.sub(r"\*\*(.*?)\*\*", r"<strong style=\"color:#eb7350;font-weight:700;\">\1</strong>", summary_html)
    content_formatted = summary_html.replace("\n\n", "<br><br>").replace("\n", "<br>")

    # 话题标签
    tags_html = " ".join(f"<span style=\"color:#eb7350;font-weight:600;margin-right:8px;\">#{html.escape(t)}#</span>" for t in topic_tags)

    # 3. 微博九宫格/多图排版（自适应 1~9 张）
    images_html = ""
    if all_img_urls:
        disp_imgs = all_img_urls[:9]
        n = len(disp_imgs)
        if n == 1:
            images_html = f"""
            <div style="margin-top:16px;border-radius:10px;overflow:hidden;background:#f5f5f5;max-width:480px;">
              <img src="{html.escape(disp_imgs[0])}" style="width:100%;max-height:340px;object-fit:cover;display:block;border-radius:10px;"/>
            </div>"""
        else:
            cols = 2 if n in (2, 4) else 3
            imgs_list = [f"<div style=\"aspect-ratio:1;border-radius:8px;overflow:hidden;background:#f5f5f5;\"><img src=\"{html.escape(src)}\" style=\"width:100%;height:100%;object-fit:cover;display:block;\"/></div>" for src in disp_imgs]
            images_html = f"<div style=\"display:grid;grid-template-columns:repeat({cols}, 1fr);gap:8px;margin-top:16px;max-width:520px;\">{''.join(imgs_list)}</div>"

    clean_title = re.sub(r"[#*`]", "", title).strip()

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
    color: #333333;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    width: 100%;
    overflow-x: hidden;
  }}
  .wb-article-wrap {{
    box-sizing: border-box;
    width: 100%;
    max-width: 600px;
    margin: 0 auto;
    padding: 24px 18px 48px;
    border-top: 4px solid #ff8200;
  }}
  .wb-article-wrap * {{ box-sizing: border-box; }}
  .wb-title {{
    font-size: 19px;
    font-weight: 800;
    color: #eb7350;
    margin-bottom: 14px;
    line-height: 1.45;
  }}
  .wb-body {{
    font-size: 15.5px;
    line-height: 1.85;
    color: #222;
    letter-spacing: 0.3px;
  }}
  .wb-body img {{
    max-width: 100%;
    border-radius: 6px;
  }}
</style>
</head>
<body>
<div class="wb-article-wrap" id="article-content">
  <div class="wb-title">#{html.escape(clean_title)}#</div>
  
  <div class="wb-body">
    {tags_html}<br><br>
    {content_formatted}
    {images_html}
  </div>
</div>
</body>
</html>"""


