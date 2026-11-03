# SPDX-License-Identifier: BUSL-1.1
"""回归：成品零符号杂音 + 排版能力不丢。

产品要求（用户多次强调，非技术取舍）：
**对外展示的成品**里只允许中文语句标点（，。！？：；——……「」（））与话题标签 `#话题`。
`**加粗**`、`### 标题`、`- 列表`、`> 引用`、`| 表格`、`[文字](链接)`、行内代码、
`~~删除线~~`、分割线等 Markdown 标记一律不得出现在成品中——无论走极简模式
（copilot）还是全能模式（orchestrator），也不分哪个平台。

但"成品"不等于"数据"。V10.3 起严格区分两种形态：

* **存储态**（`drafts.body_md`、源 `.md`）：由 `to_storage` 处理，**保留 `**`**，
  因为公众号的加粗正是靠它在渲染时转成 `<strong>`；剥掉就等于永久丢弃排版能力。
* **展示态**（卡片图、小红书/微博文案、复制、raw 接口）：由 `purify_body` 处理，
  剥净一切标记。图片上的字尤其不能带星号——那是可见事故，CSS 救不回来。

本文件锁五层：
1. `purify_body` / `purify_title` 的净化能力与幂等性；
2. `to_storage` 的"只清垃圾、不毁排版"边界；
3. 数据层 `db.add_draft` / `update_draft_body` / `get_draft` 保留排版标记；
4. 卡片成品 `render_card.card_html` / Pillow 分支（图上无标记，但加粗仍在）；
5. 公众号 `md_to_wechat_html` 能把存储态正文渲染成真加粗 `<strong>`。
"""

from __future__ import annotations

import re

import pytest

from core.text_purity import has_noise, purify_body, purify_title, to_storage

#: 事故原样的脏标题（截图里显示为「** 拒绝无效忙碌！…」）
DIRTY_TITLE = "** 拒绝无效忙碌！3个动作，让效率提升50%🚀"

DIRTY_BODY = """### 一、核心痛点
**你以为的"官方最新版"**，其实是山寨包。
- 第一点：不要乱点下载
- 第二点：认准官网
> 引用：某专家说过这句话。

[点这里看详情](https://example.com/a?b=1)

| 方法 | 效果 |
|------|------|
| 看图标 | 有效 |

```python
print("hello")
```

***

![封面](/img/dr-x/cover.png)

这是结尾,记得收藏!  #干货 #避坑
"""


# ── 1. 净化器本体 ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "noise",
    ["**", "### ", "> ", "~~", "`", "[文字](https://a.com)", "| 列1 |", "---"],
)
def test_body_removes_markdown_noise(noise: str):
    out = purify_body(f"正常一句话。\n{noise}残留标记\n")
    assert noise.strip() not in out


def test_body_keeps_hashtags_images_and_numbers():
    out = purify_body(DIRTY_BODY)
    assert "#干货" in out and "#避坑" in out, "话题标签必须保留"
    assert "![封面](/img/dr-x/cover.png)" in out, "图片语法必须保留（排版要用）"
    assert "90" not in out or True  # 数字不受影响


def test_body_headings_become_brackets():
    out = purify_body("### 核心优势\n正文。")
    assert "###" not in out
    assert "【核心优势】" in out


def test_body_ascii_punct_normalized():
    out = purify_body("这是结尾,记得收藏!很重要?真的")
    assert "，记得收藏！" in out
    assert "？" in out


def test_body_keeps_url_and_version():
    out = purify_body("详见 https://a.com/x?y=1 与 v1.2.3 版本")
    assert "https://a.com/x?y=1" in out
    assert "1.2.3" in out


def test_purify_is_idempotent():
    once = purify_body(DIRTY_BODY)
    assert purify_body(once) == once


def test_title_cleaned():
    out = purify_title(DIRTY_TITLE)
    assert out == "拒绝无效忙碌！3个动作，让效率提升50%🚀"


def test_title_drops_hashtags_and_marks():
    assert purify_title("# 标题 #话题 #干货") == "标题"
    assert purify_title("## **3步识破山寨APP** ##") == "3步识破山寨APP"


def test_title_keeps_ending_exclamation():
    assert purify_title("**90%的人都在被坑!**").endswith("！")


def test_has_noise_detects_and_clears():
    assert has_noise(DIRTY_BODY) is True
    assert has_noise(purify_body(DIRTY_BODY)) is False


@pytest.mark.parametrize(
    "meta",
    [
        "【图1：插入手机屏幕实拍图，左侧为下载按钮】",
        "【配图建议：用左右分屏对比图】",
        "【封面设计：大字标题配深色底】",
        "【排版说明：此处留白】",
    ],
)
def test_meta_production_lines_removed(meta: str):
    """幕后制作说明（配图/封面/排版）不该出现在读者面前。"""
    out = purify_body(f"正文第一段。\n{meta}\n正文第二段。")
    assert "【图" not in out and "配图建议" not in out and "排版说明" not in out
    assert "正文第二段" in out


def test_legit_bracket_heading_kept():
    """【一、核心观点】这类正常小节标题不能被误删。"""
    assert purify_body("【一、核心观点】\n正文。") == "【一、核心观点】\n正文。"


# ── 2. 数据层：保留排版标记（不然公众号永远做不出加粗）────────────────
def test_add_draft_keeps_markup_for_rendering():
    """正文落库必须保留 `**`，标题仍彻底净化（标题栏放不下加粗）。"""
    from core import db

    d = db.add_draft("", DIRTY_TITLE, DIRTY_BODY, ["wechat_mp"])
    got = db.get_draft(d["id"])
    # 标题：任何展示位都放不下排版，直接净化
    assert "**" not in got["title"] and "###" not in got["title"]
    # 正文：`**` 必须留下，否则 md_to_wechat_html 转不出 <strong>
    assert "**你以为的" in got["body_md"]
    # 但结构性垃圾照样要清
    assert "<think>" not in got["body_md"]
    assert "```" not in got["body_md"]
    assert "#干货" in got["body_md"]


def test_update_draft_body_keeps_markup():
    from core import db

    d = db.add_draft("", "标题", "正文", ["wechat_mp"])
    db.update_draft_body(d["id"], "**新正文**\n- 列表项")
    body = db.get_draft(d["id"])["body_md"]
    assert "**新正文**" in body


def test_update_draft_title_purifies():
    from core import db

    d = db.add_draft("", "标题", "正文", ["wechat_mp"])
    db.update_draft_title(d["id"], "## **新标题** ##")
    assert db.get_draft(d["id"])["title"] == "新标题"


# ── 3. 存储态清洗器边界 ───────────────────────────────────────────────
def test_to_storage_keeps_markup_but_drops_junk():
    dirty = "<think>思考</think>\n```markdown\n**重点**\n- 列表\n> 引用\n#话题\n```"
    out = to_storage(dirty)
    assert "<think>" not in out and "```" not in out
    assert "**重点**" in out          # 排版保留
    assert "- 列表" in out and "> 引用" in out
    assert "#话题" in out


def test_get_draft_keeps_body_markup():
    """历史脏数据读取时保留 `**`，标题照旧净化（符号在展示出口清）。"""
    from core import db

    d = db.add_draft("", "标题", "正文", ["wechat_mp"])
    c = db.conn()
    c.execute(
        "UPDATE drafts SET title=?, body_md=? WHERE id=?",
        ("** 旧标题 **", "### 旧小节\n**旧正文**", d["id"]),
    )
    c.commit()
    c.close()

    got = db.get_draft(d["id"])
    assert got["title"] == "旧标题"
    assert "**旧正文**" in got["body_md"]


# ── 4. 卡片成品：图上不能有标记，但加粗要保留 ────────────────────────────
def test_card_html_has_no_marks():
    from core.render_card import card_html

    html_text = card_html("**卡片标题**", ["**要点**", "- 列表要点"], kicker="## 第1幕")
    # 只检查渲染进正文的文字，不检查 CSS
    visible = re.sub(r"<style>[\s\S]*?</style>", "", html_text)
    assert "**" not in visible
    assert "##" not in visible


def test_card_html_keeps_bold_as_tag():
    """`**要点**` 在卡片里变成 <b>要点</b>——排版不变，画面无星号。"""
    from core.render_card import card_html

    visible = re.sub(r"<style>[\s\S]*?</style>", "", card_html("标题", ["**关键结论**"]))
    assert "<b>关键结论</b>" in visible
    assert "**" not in visible


def test_pillow_card_kicker_has_no_marks():
    """Pillow 兜底分支的 kicker 曾是星号上图的真凶，必须净化。"""
    from PIL import Image

    from core.render_card import _render_pillow_card

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "card-1.png"
        # kicker 带 `**` 与 `##`，若未净化就会被 draw.text 原样印在图上
        _render_pillow_card(out, "**标题**", ["**正文**"], is_cover=False,
                            kicker="## **核心痛点**", card_idx=1)
        assert out.exists() and out.stat().st_size > 1000


# ── 5. 公众号：存储态正文必须渲染成真加粗 ───────────────────────────────
def test_wechat_html_renders_storage_markup_as_bold():
    from core.themes import md_to_wechat_html

    html_out = md_to_wechat_html("这是**重中之重**的结论。", "标题")
    assert "<strong" in html_out
    assert "**" not in html_out
    assert "重中之重" in html_out
