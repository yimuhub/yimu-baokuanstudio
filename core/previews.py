# SPDX-License-Identifier: BUSL-1.1
"""分平台预览产物的统一编译入口（V15.8 · 客户报告 R6 / R7 / S3 / S4）。

修复的三个事实：
1. 全仓库十余处 ``preview-*.html`` 写盘点只覆盖 5 个平台，**从未写
   ``preview-xhs.html``**，而 ``/preview/{did}/xhs`` 与分享页都按同一命名读文件
   → 小红书预览与分享链接必然 404；
2. ``recompile_previews`` 被 ``drafts.py`` / ``assets.py`` import，但函数根本
   不存在，异常被 ``except: pass`` 吞掉，图片替换后的预览重编译从未执行；
3. 预览编译把正文里的 Markdown 图片原样转成 ``<img>``，不检查文件是否存在，
   死链一路传到浏览器。

统一策略：
- 所有平台（含 xhs）由 :func:`build_all_previews` 一处编译；
- :func:`ensure_preview` 供预览 / 分享路由懒生成，老草稿打开即自愈；
- 编译前先走 ``core.image_contract.normalize`` 修正正文配图，并对剩余本地链接
  做存在性校验（渲染层另有占位块兜底）。
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

from adapters.base import save_preview
from core import db, image_contract

logger = logging.getLogger("yimu.previews")

#: 前端平台条、预览路由、分享共用的六平台（含小红书）
PREVIEW_PLATFORMS = ("wechat_mp", "xhs", "toutiao", "zhihu", "weibo", "twitter")


def _render_xhs(ddir: Path, draft_id: str, title: str, body_md: str) -> str:
    """小红书预览：成套卡片画报 + 笔记正文。

    卡片用 base64 内嵌，保证匿名分享页（``/s/{token}``）也能显示，
    不依赖需要登录态的 ``/card/{did}/...`` 路由。
    """
    from core.text_purity import purify_body

    note = ""
    xhs_md = ddir / "xhs.md"
    if xhs_md.is_file():
        note = xhs_md.read_text(encoding="utf-8", errors="ignore")
    if not note.strip():
        note = body_md
    note = purify_body(note)

    cards_html = []
    try:
        for i, p in enumerate(sorted(ddir.glob("card-*.png"))[:9]):
            data = base64.b64encode(p.read_bytes()).decode("ascii")
            cards_html.append(
                f'<figure class="card"><img src="data:image/png;base64,{data}" '
                f'alt="小红书卡片 {i + 1}"><figcaption>{i + 1} / '
                f'{min(len(list(ddir.glob("card-*.png"))), 9)}</figcaption></figure>'
            )
    except OSError as e:
        logger.warning("[previews] draft=%s 卡片读取失败: %s", draft_id, e)
    if not cards_html:
        cards_html.append(
            '<div class="empty">成套卡片尚未生成，可在工作台点击「生成小红书卡片」后刷新本页。</div>'
        )
    import html
    esc_title = html.escape(title or "")
    esc_note = html.escape(note or "")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc_title} · 小红书预览</title>
<style>
  body{{margin:0;background:#f6f7f9;color:#1f2329;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
  .wrap{{max-width:960px;margin:0 auto;padding:28px 20px 60px}}
  h1{{font-size:22px;line-height:1.5;margin:0 0 8px}}
  .badge{{display:inline-block;background:#ff2442;color:#fff;border-radius:20px;padding:3px 12px;font-size:12px;margin-bottom:20px}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:28px}}
  .card{{margin:0;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 6px 22px rgba(0,0,0,.08)}}
  .card img{{width:100%;display:block}}
  figcaption{{text-align:center;font-size:12px;color:#8a9099;padding:8px 0 12px}}
  .note{{background:#fff;border-radius:14px;padding:22px 26px;white-space:pre-wrap;line-height:1.9;font-size:15px;box-shadow:0 6px 22px rgba(0,0,0,.05)}}
  .empty{{padding:40px;text-align:center;color:#8a9099;background:#fff;border-radius:14px}}
</style></head><body><div class="wrap">
<h1>{esc_title}</h1><span class="badge">小红书 · 成套卡片</span>
<div class="cards">{''.join(cards_html)}</div>
<div class="note">{esc_note}</div>
</div></body></html>"""


def _render_platform(platform: str, *, body_md: str, title: str, draft_id: str,
                     ddir: Path, images: dict, cover: str | None, theme: str) -> str:
    from core.layouter import render as layout_render
    if platform == "wechat_mp":
        return layout_render(body_md, title, theme=theme, images=images, cover=cover)
    if platform == "xhs":
        return _render_xhs(ddir, draft_id, title, body_md)
    if platform == "toutiao":
        from adapters import toutiao
        return toutiao.render_preview(body_md, title, images=images, cover=cover, draft_id=draft_id)
    if platform == "zhihu":
        from adapters import zhihu
        return zhihu.render_preview(body_md, title, images=images, cover=cover, draft_id=draft_id)
    if platform == "weibo":
        from adapters import weibo
        return weibo.render_preview(body_md, title, images=images, cover=cover, draft_id=draft_id)
    if platform == "twitter":
        from adapters import twitter
        tw = ddir / "twitter.md"
        text = tw.read_text(encoding="utf-8", errors="ignore") if tw.is_file() else ""
        if not text.strip():
            text = f"🔥 {title}\n\n{body_md[:360]}"
        return twitter.render_twitter_html(text, title)
    raise ValueError(f"不支持的预览平台: {platform}")


def build_all_previews(draft_id: str, *, body_md: str | None = None,
                       platforms: tuple | list | None = None,
                       title: str | None = None) -> dict:
    """统一编译（默认六平台），并在编译前修正正文配图契约。"""
    d = db.get_draft(draft_id)
    if not d:
        return {"ok": False, "error": "草稿不存在", "platforms": []}
    ddir = db.draft_dir(draft_id)
    body, report = image_contract.normalize(
        body_md if body_md is not None else (d.get("body_md") or ""), draft_id, ddir
    )
    if body != (d.get("body_md") or ""):
        # 直接写库：normalize 输出已符合契约，避免 to_storage 二次改写
        c = db.conn()
        c.execute("UPDATE drafts SET body_md=? WHERE id=?", (body, draft_id))
        c.commit()
        c.close()
    title = title or d.get("title") or ""
    imgs = image_contract.disk_images(draft_id, ddir)
    images = {u.rsplit("/", 1)[-1]: u for u in imgs["sections"]}
    cover = imgs["cover"] or None
    try:
        from core.llm import load_config
        theme = load_config().get("creation", {}).get("wechat_theme", "caozhou")
    except Exception:
        theme = "caozhou"

    written, errors = [], {}
    for platform in (platforms or PREVIEW_PLATFORMS):
        try:
            html = _render_platform(platform, body_md=body, title=title, draft_id=draft_id,
                                    ddir=ddir, images=images, cover=cover, theme=theme)
            save_preview(ddir, platform, html)
            written.append(platform)
        except Exception as e:
            errors[platform] = str(e)
            logger.warning("[previews] draft=%s 平台 %s 编译失败: %s", draft_id, platform, e)

    missing = image_contract.validate(body, draft_id, ddir)
    if missing or report.get("removed"):
        logger.warning("[previews] draft=%s 配图缺失已降级: %s / 移除=%d",
                       draft_id, missing[:5], report.get("removed", 0))
    return {"ok": not errors, "platforms": written, "errors": errors,
            "images": report, "missing": missing}


def ensure_preview(draft_id: str, platform: str) -> Path | None:
    """预览路由 / 分享页的懒生成入口；老草稿打开时自动补齐产物。"""
    if platform not in PREVIEW_PLATFORMS:
        return None
    f = db.draft_dir(draft_id) / f"preview-{platform}.html"
    if f.is_file():
        return f
    try:
        build_all_previews(draft_id, platforms=(platform,))
    except Exception as e:
        logger.warning("[previews] draft=%s 懒生成 %s 失败: %s", draft_id, platform, e)
    return f if f.is_file() else None


def recompile_previews(draft_id: str) -> dict:
    """图片上传 / 替换后重编译全部预览。

    历史上 ``web/routers/drafts.py`` 与 ``assets.py`` 都 import 了本函数，
    但它从未存在，``try/except: pass`` 把 ImportError 静默吞掉，
    导致替换图片后预览一直是旧内容。
    """
    return build_all_previews(draft_id)
