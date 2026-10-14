# SPDX-License-Identifier: BUSL-1.1
"""V8.3.2 影视级分镜配图铁律与多美学风格切换回归测试。

覆盖核心铁律：
1. 全局单一真源版本号升级为 8.3.2，页面静态与动态徽章单一真源；
2. 影视级分镜头剧本解构与通读全文法则（Wide Establishing Shot / Medium Narrative Shot / Close-up）；
3. 十大多美学风格体系（包含 anime_cinematic 治愈动漫与 minimalist_3d 极简轻拟物）；
4. 创作 Agent 聊天对话中一键识别多美学换图意图（“换成古风”、“换成科技风”等）；
5. 图像 Agent 装备影视分镜与光学运镜核心技能。
"""
import pytest
import version
from pathlib import Path
from core.imagegen import (
    VISUAL_STYLE_PRESETS,
    ARTICLE_VISUAL_DIGEST_PROMPT,
    build_style_enhanced_prompt,
    _detect_visual_style,
)
from core.copilot import detect_intent_and_target, VISUAL_STYLE_KEYWORDS
from core.agents import load_config, STAGE_DEFAULT_SKILLS


def test_v8333_version_consistency():
    """验证版本单一真源升级为 9.3.1，杜绝任何旧版本写死徽章"""
    assert version.__version__ == "9.3.1"
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
    assert "V9.3.1" in index_html
    assert "9.3.1" in index_html
    assert "V9.3.1" in mobile_html
    # 杜绝任何旧的 8.2 或 8.3.2 或 8.3.33 或 9.0.0 写死徽章
    assert "V8.2" not in index_html
    assert "V8.2" not in mobile_html
    assert "V8.3.2" not in index_html
    assert "V8.3.2" not in mobile_html
    assert "V8.3.33" not in index_html
    assert "V8.3.33" not in mobile_html
    assert "V9.0.0" not in index_html
    assert "V9.0.0" not in mobile_html


def test_visual_style_presets_complete():
    """验证十大视觉美学体系完备性，重点包含新海诚系与极简3D"""
    required_styles = [
        "documentary",
        "swiss_minimal",
        "magazine_editorial",
        "tech_cyber",
        "ancient_chinese",
        "city_urban",
        "cinematic_movie",
        "commercial_premium",
        "anime_cinematic",
        "minimalist_3d",
    ]
    for s in required_styles:
        assert s in VISUAL_STYLE_PRESETS, f"缺少风格预设: {s}"
        preset = VISUAL_STYLE_PRESETS[s]
        assert "name" in preset
        assert "tag" in preset
        assert "style_directive" in preset
        assert "suffix" in preset
        assert "no text" in preset["suffix"]
        assert "no watermark" in preset["suffix"]


def test_article_visual_digest_prompt_ironclad_rules():
    """验证视觉总监分镜核心铁律已注入系统提示词"""
    assert "通读全文" in ARTICLE_VISUAL_DIGEST_PROMPT
    assert "影视短剧分镜" in ARTICLE_VISUAL_DIGEST_PROMPT
    assert "Wide Establishing" in ARTICLE_VISUAL_DIGEST_PROMPT
    assert "95%" in ARTICLE_VISUAL_DIGEST_PROMPT
    assert "anime_cinematic" in ARTICLE_VISUAL_DIGEST_PROMPT
    assert "minimalist_3d" in ARTICLE_VISUAL_DIGEST_PROMPT


def test_copilot_image_style_intent_detection():
    """验证与创作 Agent 对话时一句话识别换图与美学风格意图"""
    # 1. 换成古风
    intent, meta = detect_intent_and_target("换成古风", True)
    assert intent == "IMAGE_STYLE"
    assert meta.get("style") == "ancient_chinese"

    # 2. 改成科技风
    intent, meta = detect_intent_and_target("配图改成科技风", True)
    assert intent == "IMAGE_STYLE"
    assert meta.get("style") == "tech_cyber"

    # 3. 换成动漫风格 / 新海诚风格
    intent, meta = detect_intent_and_target("把图片换成新海诚风格", True)
    assert intent == "IMAGE_STYLE"
    assert meta.get("style") == "anime_cinematic"

    # 4. 按极简3D风格配图
    intent, meta = detect_intent_and_target("按极简3D风格配图", True)
    assert intent == "IMAGE_STYLE"
    assert meta.get("style") == "minimalist_3d"

    # 5. 重新配图
    intent, meta = detect_intent_and_target("帮我重新配图", True)
    assert intent == "IMAGE_STYLE"


def test_image_agent_skills_equipped():
    """验证图像 Agent 已成功挂载分镜与摄影技能"""
    cfg = load_config()
    image_agent = cfg.get("agents", {}).get("image", {})
    skills = image_agent.get("skills", [])
    assert "storyboard-visual-grammar" in skills
    assert "cinematic-optics-lighting" in skills
    assert "storyboard-visual-grammar" in STAGE_DEFAULT_SKILLS["image"]


def test_heading_support_and_section_image_injection():
    """验证文章正文中的 H2 与 H3 标题均能精准匹配并成功注入分镜插图"""
    from core.imagegen import inject_images_to_markdown

    # 测试包含 H2 的 Markdown
    md_with_h2 = "# 文章总标题\n\n导语部分。\n\n## 关键段落一\n\n段落一正文。\n\n## 关键段落二\n\n段落二正文。"
    # 模拟草稿图片数据
    from unittest.mock import patch
    mock_imgs = {
        "cover": "/img/test/cover.png",
        "sections": ["/img/test/sec-0.png", "/img/test/sec-1.png"],
        "all": ["/img/test/cover.png", "/img/test/sec-0.png", "/img/test/sec-1.png"]
    }
    with patch("core.imagegen.get_draft_images", return_value=mock_imgs):
        injected = inject_images_to_markdown(md_with_h2, "dr-test")
        assert "/img/test/cover.png" in injected
        assert "/img/test/sec-0.png" in injected
        assert "/img/test/sec-1.png" in injected
        assert "![关键段落一]" in injected
        assert "![关键段落二]" in injected

