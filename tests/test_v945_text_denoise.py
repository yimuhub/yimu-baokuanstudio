"""V9.4.5 正文去噪引擎与排版规范化专项验收测试集。

验证范围：
1. 全局版本单一真源为 9.4.5，代号为「澄音境」 (Pristine Rhythm)；
2. 彻底剔除正文中的 ***、---、___、* * * 等粗糙分割线；
3. 规范化星号标记：***加粗斜体*** 降噪为标准的 **加粗**，清理孤立与残余的 *** 符号；
4. 规范化标题与小节标记：
   - 杜绝正文充斥 ### / ## / #### 等粗糙 Markdown 符号；
   - 带有中文序号的小节平滑转换为自然编号；普通小节转换为【小节标题】；
5. 严格限定 # 符号边界：
   - 仅且只能保留合法的文末话题标签（#自媒体 #AI爆款）与成对社媒话题（#话题#）；
   - 正文混杂的孤立无意义 #（如 关于#AI、第#1点）进行无损去噪；
   - 保护 URL 锚点与代码块内的注释；
6. 微信公众号排版引擎 (md_to_wechat_html) 原生自适应【小节标题】与中文序号小节，
   生成对应 h3 样式并精准配对小节图片；
7. 编排器 (clean_generated_markdown / clean_xhs_text) 接入去噪守卫。
"""
from __future__ import annotations

import re
from pathlib import Path
import pytest
import version
from core.text_denoise import (
    denoise_body_text,
    is_section_heading,
    extract_section_title,
    extract_section_headings,
)
from core.themes import md_to_wechat_html, clean_markdown_body
from core.orchestrator import clean_generated_markdown, clean_xhs_text
from core.imagegen import inject_images_to_markdown


def test_v945_version_single_source_of_truth():
    """验证全局版本单一真源为 9.4.5 澄音境 (Pristine Rhythm)"""
    assert version.__version__ in ("10.0.0", "9.4.5")
    assert version.__codename__ in ("鸿蒙始", "澄音境")
    assert version.__codename_en__ in ("Primordial Dawn", "Pristine Rhythm")
    assert any(k in version.__slogan_cn__ for k in ("鸿蒙开元", "素简澄澈"))
    assert any(k in version.__slogan_en__ for k in ("Primordial Dawn", "Pristine Rhythm"))

    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
    readme_en = Path("README.md").read_text(encoding="utf-8")
    readme_zh = Path("README_ZH.md").read_text(encoding="utf-8")
    releases_md = Path("RELEASES.md").read_text(encoding="utf-8")
    license_txt = Path("LICENSE").read_text(encoding="utf-8")

    assert any(v in index_html for v in ("V10.0.0", "V9.4.5"))
    assert any(v in mobile_html for v in ("V10.0.0", "V9.4.5"))
    assert any(v in readme_en for v in ("version-10.0.0", "version-9.4.5"))
    assert any(v in readme_zh for v in ("version-10.0.0", "version-9.4.5"))
    assert any(v in releases_md for v in ("Version 10.0.0", "Version 9.4.5"))
    assert any(v in license_txt for v in ("V10.0.0", "V9.4.5"))


def test_denoise_dividers_removal():
    """验证 ***、---、___、* * * 等独占一行的分割线被彻底剔除"""
    sample = (
        "第一段内容。\n"
        "***\n"
        "第二段内容。\n"
        "---\n"
        "第三段内容。\n"
        "___\n"
        "第四段内容。\n"
        "* * *\n"
        "第五段内容。\n"
    )
    cleaned = denoise_body_text(sample)
    assert "***" not in cleaned
    assert "---" not in cleaned
    assert "___" not in cleaned
    assert "* * *" not in cleaned
    assert "第一段内容。" in cleaned
    assert "第五段内容。" in cleaned


def test_denoise_asterisks():
    """验证 ***文本*** 降级为 **文本**，并清理孤立 *** 符号"""
    sample = (
        "这里是普通文字，这里是 ***加粗重点一***，必须要牢记。\n"
        "这里是普通的 **常规加粗** 内容。\n"
        "这里有个孤立的 *** 符号杂质。\n"
    )
    cleaned = denoise_body_text(sample)
    assert "***" not in cleaned
    assert "**加粗重点一**" in cleaned
    assert "**常规加粗**" in cleaned
    assert "孤立的  符号杂质" in cleaned or "孤立的 符号杂质" in cleaned


def test_denoise_headings():
    """验证 ### / ## 标题符号降噪为自然序号或【小节标题】"""
    sample = (
        "### 为什么值得看\n"
        "这是前言引子。\n\n"
        "### 一、核心逻辑深度剖析\n"
        "这是第一节正文。\n\n"
        "## 1. 实战避坑指南\n"
        "这是第二节正文。\n\n"
        "#### 细节操作要点\n"
        "这是细节正文。\n\n"
        "### 【总结展望】\n"
        "这是结尾。\n"
    )
    cleaned = denoise_body_text(sample)
    # 彻底杜绝 ### 与 ## 标题符号
    assert "###" not in cleaned
    assert "##" not in cleaned
    # 验证平滑转换
    assert "【为什么值得看】" in cleaned
    assert "一、核心逻辑深度剖析" in cleaned
    assert "【1. 实战避坑指南】" in cleaned
    assert "【细节操作要点】" in cleaned
    assert "【总结展望】" in cleaned


def test_denoise_hashtag_boundary_rules():
    """验证 # 符号仅限文末标签与成对话题，正文内混杂的孤立 # 彻底去除"""
    sample = (
        "今天在讨论关于#人工智能在2026年 的前沿发展，第#1条建议是跟上趋势。\n"
        "欢迎大家参与 #热点聚焦# 话题讨论！\n"
        "详情参考 https://example.com/guide#chapter-1 文档。\n"
        "这是最后总结。\n\n"
        "#自媒体 #AI爆款 #写作干货\n"
    )
    cleaned = denoise_body_text(sample)
    # 正文中混杂的关于#人工智能 -> 关于人工智能；第#1条 -> 第1条
    assert "关于人工智能在2026年" in cleaned
    assert "第1条建议" in cleaned
    assert "关于#人工智能" not in cleaned
    assert "第#1条" not in cleaned
    # 成对社交话题保留
    assert "#热点聚焦#" in cleaned
    # URL 锚点保留
    assert "https://example.com/guide#chapter-1" in cleaned
    # 文末标签完整保留
    assert "#自媒体 #AI爆款 #写作干货" in cleaned


def test_denoise_code_block_protection():
    """验证代码块内的 Python 注释等 # 不会被误杀"""
    sample = (
        "下面是一段示例代码：\n"
        "```python\n"
        "# 这是 Python 注释\n"
        "x = 100 # 行尾注释\n"
        "```\n"
        "关于#测试 的正文说明。\n"
    )
    cleaned = denoise_body_text(sample)
    assert "# 这是 Python 注释" in cleaned
    assert "x = 100 # 行尾注释" in cleaned
    assert "关于测试 的正文说明" in cleaned
    assert "关于#测试" not in cleaned


def test_extract_section_headings():
    """验证统一小节提取函数正确解析自然序号、方头括号与 Markdown 小节"""
    sample = (
        "【导读与核心背景】\n"
        "导语内容。\n\n"
        "一、第一大破局点\n"
        "- 要点一\n"
        "- 要点二\n\n"
        "【2. 关键落地步骤】\n"
        "步骤正文段落。\n\n"
        "【总结收尾】\n"
        "尾部内容。 #自媒体 #干货\n"
    )
    secs = extract_section_headings(sample)
    titles = [t for t, _ in secs]
    assert "【导读与核心背景】" in titles
    assert "一、第一大破局点" in titles
    assert "【2. 关键落地步骤】" in titles
    assert "【总结收尾】" in titles


def test_wechat_html_typesetting_with_denoised_text():
    """验证微信公众号排版引擎 (md_to_wechat_html) 正确将【小节标题】与序号识别为 h3 并注入插图"""
    sample = (
        "【为什么值得看】\n"
        "这是引言导语内容。\n\n"
        "一、核心逻辑深度拆解\n"
        "这是第一节的核心要点。\n\n"
        "【实战落地操作指南】\n"
        "这是实操内容。\n"
        "- 第一步\n"
        "- 第二步\n\n"
        "【写在最后】\n"
        "总结全篇。 #自媒体 #爆款指南\n"
    )
    images = {
        "为什么值得看": "/img/d-1/sec-0.png",
        "实战落地操作指南": "/img/d-1/sec-1.png",
    }
    html = md_to_wechat_html(sample, title="测试文章", images=images)
    # 验证 h3 标签渲染
    assert "<h3" in html
    assert "【为什么值得看】" in html or "为什么值得看" in html
    assert "一、核心逻辑深度拆解" in html
    # 验证图片正确插入且无重复
    assert "/img/d-1/sec-0.png" in html
    assert "/img/d-1/sec-1.png" in html
    assert html.count("/img/d-1/sec-0.png") == 1
    assert html.count("/img/d-1/sec-1.png") == 1
    # 验证文末标签保留
    assert "#自媒体 #爆款指南" in html
    # 验证无任何 ### 符号残留
    assert "###" not in html


def test_orchestrator_and_xhs_clean_pipeline():
    """验证编排器 clean_generated_markdown 与 clean_xhs_text 均已接入去噪引擎"""
    raw_markdown = (
        "<think>思考过程</think>\n"
        "```markdown\n"
        "### 核心痛点解析\n"
        "关于#行业发展 的分析。\n"
        "***\n"
        "***重中之重***：必须执行。\n"
        "#自媒体 #成长\n"
        "```"
    )
    cleaned = clean_generated_markdown(raw_markdown)
    assert "<think>" not in cleaned
    assert "```" not in cleaned
    assert "***" not in cleaned
    assert "###" not in cleaned
    assert "关于行业发展" in cleaned
    assert "【核心痛点解析】" in cleaned
    assert "**重中之重**" in cleaned
    assert "#自媒体 #成长" in cleaned

    xhs_output = clean_xhs_text(raw_markdown)
    assert "###" not in xhs_output
    assert "***" not in xhs_output
    assert "#自媒体" in xhs_output
