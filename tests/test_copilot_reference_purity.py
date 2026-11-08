# SPDX-License-Identifier: BUSL-1.1
"""回归：极简模式不得把检索垃圾当"创作依据"，也不得把内部技能标识漏给用户。

线上事故（2026-11-01）：极简模式按「帮我写一篇高赞小红书干货种草笔记」创作，
回复里列出了三条参考源——《扒开让我 蜜桃视频/网站最新版下载…2265安卓网》
《我用🎵蹭同桌的🎵官方版下载…》《靠谱软件官方版…》，并且把
`viral-formulas / de-ai / contrarian-insight / title-forge` 这些英文 slug 直接展示。
成稿更被带偏，通篇写"山寨 APP""高速下载""官方最新版"——因为提示词把这些垃圾
称作"唯一事实与依据蓝本"。

本文件锁三件事：
1. 检索层 `_accept_reference` 必须挡住下载站/站群/软色情标题与主题无关结果；
2. 技能展示名必须是中文，不得是英文 slug；
3. `copilot` 不得再无条件宣称"已基于全网真实高浏览量爆款文章"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.copilot import skill_display_name
from core.search import _accept_reference

REPO_ROOT = Path(__file__).resolve().parent.parent
KEYWORD = "高赞小红书干货种草"

#: 事故原样的三条标题（百度广告位/站群混入）
INCIDENT_TITLES = [
    "扒开让我 蜜桃视频/网站最新版下载-扒开我 蜜桃视频/网站2025最新版V.1.3.76.1-安卓版-2265安卓网",
    "我用🎵蹭同桌的🎵官方版下载-我用🎵蹭同桌的🎵2026免费版v.53.34.28.722 安卓版-2265安卓网",
    "靠谱软件官方版-靠谱软件2026免费版v.48.29.362.186 安卓版-2265安卓网",
]

LEGIT_REFS = [
    ("小红书「高赞」笔记投放指南!有人借此实现千万销售额", "https://example.com/a", "小红书 高赞 笔记 投放 种草"),
    ("小红书种草怎么做? - 知乎", "https://example.com/b", "小红书 种草 方法论 干货"),
    ("写作干货|小红书种草月赚3000+", "https://example.com/c", "小红书 种草 干货 变现"),
]


@pytest.mark.parametrize("title", INCIDENT_TITLES)
def test_download_farm_titles_are_rejected(title: str):
    """事故原样的下载站标题必须被过滤，绝不能当成"真实爆款文章"。"""
    assert _accept_reference(title, "", title, KEYWORD) is False


@pytest.mark.parametrize("title,url,snippet", LEGIT_REFS)
def test_legit_references_are_kept(title: str, url: str, snippet: str):
    """同题正常内容不能被误杀——闸门宁严但不能把好料一起挡掉。"""
    assert _accept_reference(title, url, snippet, KEYWORD) is True


def test_unrelated_content_is_rejected():
    """与主题毫无交集的条目（哪怕不像垃圾）也不该进参考源。"""
    assert _accept_reference(
        "大衣哥被举报停演：当举报变成暗器", "https://example.com/x", "娱乐新闻", KEYWORD
    ) is False


def test_spam_host_is_rejected_even_with_good_title():
    """标题看着正常、但落在下载站域名上的，同样不可信。"""
    assert _accept_reference(
        "小红书种草怎么做", "https://www.2265.com/soft/123.html", "小红书 种草", KEYWORD
    ) is False


@pytest.mark.parametrize(
    "skill_id",
    ["title-forge", "de-ai", "viral-formulas", "contrarian-insight"],
)
def test_skill_display_name_is_chinese(skill_id: str):
    """技能展示名必须是中文，绝不能把英文 slug 漏给用户。"""
    from core import agents

    sk = agents.list_skills().get(skill_id)
    assert sk, f"技能库缺少 {skill_id}"
    disp = skill_display_name(sk)
    assert any("\u4e00" <= ch <= "\u9fa5" for ch in disp), f"{skill_id} 展示名不是中文：{disp}"
    assert "-" not in disp and "_" not in disp, f"{skill_id} 展示名仍像内部标识：{disp}"


def test_copilot_no_longer_claims_fake_sources():
    """回复文案不得无条件宣称"已基于全网真实高浏览量爆款文章"。"""
    src = (REPO_ROOT / "core" / "copilot.py").read_text(encoding="utf-8")
    assert "已基于全网真实高浏览量爆款文章" not in src
    # 技能名不得再直接取 frontmatter 的 slug
    assert 'skills_applied_names.append(sk_obj["name"])' not in src
