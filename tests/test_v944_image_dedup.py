"""V9.4.4 排版图片全局防重与单一真源验收测试集。

验证范围：
1. 全局版本单一真源为 9.4.4，代号为「澄澈镜」；
2. 极简模式（Copilot）成稿首次排版公众号图文零重复；
3. 选题矩阵与爆款工坊一键成稿首次排版公众号图文零重复；
4. core.layouter.render / core.themes.md_to_wechat_html 全链路防重与防堆叠；
5. _dedupe_markdown_images 与 _dedupe_wechat_html_images 过滤机制；
6. web.admin /api/drafts/{did}/raw/wechat_mp 历史缓存自动自愈去重；
7. adapters.wechat_mp.render_preview 统一收口验证。
"""
from __future__ import annotations

import re
import pytest
import version
from core.layouter import render as layout_render, _dedupe_wechat_html_images, _inject_cover
from core.themes import md_to_wechat_html
from core.imagegen import _dedupe_markdown_images, inject_images_to_markdown
from adapters import wechat_mp


def test_v944_version_single_source_of_truth():
    """验证全局版本号及代号为 V9.4.4 澄澈镜"""
    assert version.__version__ == "9.4.4"
    assert version.__codename__ == "澄澈镜"
    assert version.__codename_en__ == "Pristine Mirror"


def test_dedupe_markdown_images():
    """验证 Markdown 正文中连续相邻或重复出现的图片语法能被精准去重"""
    md_with_dups = (
        "# 标题\n\n"
        "导语内容。\n\n"
        "![小节1](/img/dr-123/sec-0.png)\n"
        "![小节1](/img/dr-123/sec-0.png)\n"
        "## 第二节\n"
        "第二节正文。\n\n"
        "![小节2](/img/dr-123/sec-1.png)\n"
        "![小节1](/img/dr-123/sec-0.png)\n"
    )
    cleaned = _dedupe_markdown_images(md_with_dups)
    urls = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", cleaned)
    assert len(urls) == len(set(urls)), f"Markdown 图片去重失败，包含重复: {urls}"
    assert urls == ["/img/dr-123/sec-0.png", "/img/dr-123/sec-1.png"]


def test_dedupe_wechat_html_images():
    """验证微信 HTML 中重复图片标签及空段落被彻底净化"""
    html_with_dups = (
        "<div>"
        "<p>第一段</p>"
        "<img src='/img/test/cov.png'/>"
        "<img src='/img/test/cov.png'/>"
        "<p>第二段</p>"
        "<img src='/img/test/sec-0.png?v=1'/>"
        "<p>第三段</p>"
        "<img src='/img/test/sec-0.png?v=2'/>"
        "<p> </p>"
        "</div>"
    )
    res = _dedupe_wechat_html_images(html_with_dups)
    srcs = re.findall(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", res, re.I)
    norm_srcs = [s.split("?")[0] for s in srcs]
    assert len(norm_srcs) == len(set(norm_srcs)), f"微信 HTML 存在重复图片: {norm_srcs}"
    assert len(norm_srcs) == 2
    assert "<p> </p>" not in res


def test_layout_render_no_duplicate_when_inline_and_dict_both_provided():
    """验证当正文已内嵌图片，且外部同时传入 images 字典和 cover 时，绝不发生双重渲染"""
    body = (
        "![封面](/img/d1/cover.png)\n\n"
        "引言导读。\n\n"
        "## 核心观点\n"
        "内容解析。\n\n"
        "![核心观点](/img/d1/sec-0.png)\n\n"
        "## 实操方案\n"
        "方案详情。\n\n"
        "![实操方案](/img/d1/sec-1.png)\n"
    )
    images_dict = {
        "核心观点": "/img/d1/sec-0.png",
        "实操方案": "/img/d1/sec-1.png",
        "额外补充": "/img/d1/sec-2.png"
    }
    cover = "/img/d1/cover.png"

    html = layout_render(body, "测试标题", theme="caozhou", images=images_dict, cover=cover)
    srcs = re.findall(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", html, re.I)
    norm_srcs = [s.split("?")[0] for s in srcs]

    # 每张图片严格只能出现 1 次
    assert len(norm_srcs) == len(set(norm_srcs)), f"渲染结果出现重复图片: {norm_srcs}"
    # 封面 + 2 个正文插图 = 3 张
    assert norm_srcs.count("/img/d1/cover.png") == 1
    assert norm_srcs.count("/img/d1/sec-0.png") == 1
    assert norm_srcs.count("/img/d1/sec-1.png") == 1


def test_wechat_mp_adapter_render_preview():
    """验证公众号适配器 render_preview 输出零重复"""
    body = "导语\n\n## 章节1\n正文1\n\n![章节1](/img/x/sec-0.png)\n"
    images = {"章节1": "/img/x/sec-0.png"}
    html = wechat_mp.render_preview(body, "标题", theme="emerald", images=images, cover="/img/x/cover.png")
    srcs = re.findall(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", html, re.I)
    norm_srcs = [s.split("?")[0] for s in srcs]
    assert len(norm_srcs) == len(set(norm_srcs))
    assert norm_srcs.count("/img/x/sec-0.png") == 1


def test_minimalist_mode_draft_raw_self_healing(tmp_path, monkeypatch):
    """验证草稿箱原始排版输出接口 (/api/drafts/{did}/raw/wechat_mp) 遇到脏缓存能自动自愈去重"""
    from fastapi.testclient import TestClient
    from web.admin import app
    from core import db

    client = TestClient(app)

    # 构造一篇临时草稿与包含双重重复图片的 preview-wechat_mp.html
    draft_id = "dr-test-dedup-944"
    ddir = db.draft_dir(draft_id)
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "img").mkdir(parents=True, exist_ok=True)

    c = db.conn()
    c.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
    c.execute("INSERT INTO drafts (id, topic_id, title, body_md, status) VALUES (?, '', ?, ?, 'ready')",
              (draft_id, "极简测试标题", "### 第一节\n正文第一节"))
    c.commit()
    c.close()

    # 写入带有重复图片的脏缓存文件
    dirty_html = (
        "<!doctype html><html><body>"
        "<p>导语</p>"
        "<img src='/img/dr-test-dedup-944/sec-0.png' style='width:100%'/>"
        "<img src='/img/dr-test-dedup-944/sec-0.png' style='width:100%'/>"
        "</body></html>"
    )
    (ddir / "preview-wechat_mp.html").write_text(dirty_html, encoding="utf-8")

    # 请求 raw wechat_mp 接口
    res = client.get(f"/api/drafts/{draft_id}/raw/wechat_mp")
    assert res.status_code == 200
    cleaned_html = res.json().get("html", "")
    srcs = re.findall(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", cleaned_html, re.I)
    norm_srcs = [s.split("?")[0] for s in srcs]
    assert len(norm_srcs) == 1, f"接口自愈去重失败，仍然包含重复: {norm_srcs}"
    assert norm_srcs == ["/img/dr-test-dedup-944/sec-0.png"]

    # 验证本地文件也被修复同步重写
    file_content = (ddir / "preview-wechat_mp.html").read_text(encoding="utf-8")
    assert file_content == cleaned_html
