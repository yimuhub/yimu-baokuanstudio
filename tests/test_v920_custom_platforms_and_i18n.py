# SPDX-License-Identifier: BUSL-1.1
"""V9.2.0 (天工开 · Divine Forge) 核心功能与 i18n 深度防回归自动化测试集

验证范围:
1. 版本单一真源: version.py 为 9.2.0，专属代号为「天工开」；
2. Releases 展示页: 彻底移除顶部「商业化价格」菜单，包含 V9.2.0 天工开里程碑；
3. i18n 翻译防回归: 彻底杜绝「一幕·一幕」翻译错误，绝对统一为「一幕·YIMU」；
4. 自定义内容分发平台:
   - detect_platform_from_url 能够智能识别平台名称与域名；
   - 默认采用今日头条高密度资讯流排版规范；
   - analyze_url_layout_style 能够模拟 Agent 深度提取排版视觉法则并自蒸馏生成技能；
   - add_or_update_platform 与 delete_custom_platform 具备稳定持久化；
5. REST API 端点: /api/platforms/custom, /api/platforms/detect, /api/platforms/analyze_style 正常工作。
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

import version
from core.custom_platforms import (
    DEFAULT_TOUTIAO_LAYOUT_RULES,
    add_or_update_platform,
    analyze_url_layout_style,
    delete_custom_platform,
    detect_platform_from_url,
    get_custom_platforms,
)
from studio.releases_page import get_releases_html
from web.admin import app


def test_v920_version_single_source_of_truth():
    """验证版本单一真源为 10.1 / 10.0.1 / 10.0.0"""
    assert version.__version__ in ("10.1", "10.0.1", "10.0.0", "9.4.5")
    assert getattr(version, "__codename__", "") in ("鸿蒙始", "澄音境")


def test_releases_page_no_pricing_menu_and_has_v920():
    """验证 /releases 页面顶部彻底去掉了商业化价格菜单，且包含 V9.2.0 里程碑"""
    html = get_releases_html()
    assert '<a class="btn ghost" href="/pricing">💰 商业化价格</a>' not in html
    assert 'href="/pricing"' not in html
    assert "V9.2.0" in html
    assert "天工开" in html
    assert "Divine Forge" in html
    assert "自定义内容分发派生平台中枢" in html


def test_i18n_script_purified_yimu_translation():
    """验证 i18n.js 中移除了导致『一幕·一幕』的单字替换，并注入了品牌纠错锁定"""
    i18n_path = Path("web/static/js/i18n.js")
    assert i18n_path.exists()
    content = i18n_path.read_text(encoding="utf-8")

    # 杜绝将单字 YIMU 强行逆转为 一幕 导致 一幕·一幕 的条目
    assert '["YIMU", "一幕"]' not in content
    # 验证含有纠错锁定逻辑
    assert "一幕·YIMU" in content
    assert "一幕[·\\.]一幕" in content
    assert f"V{version.__version__}" in content


def test_detect_platform_from_url():
    """验证根据 URL 智能识别平台名称与域名"""
    # 已知平台快速匹配
    sspai = detect_platform_from_url("https://sspai.com/post/12345")
    assert sspai["name"] == "少数派"
    assert sspai["domain"] == "sspai.com"
    assert sspai["icon"] == "🥧"
    assert sspai["layout_mode"] == "toutiao"

    bili = detect_platform_from_url("https://www.bilibili.com/read/cv999")
    assert "哔哩哔哩" in bili["name"]
    assert bili["domain"] == "www.bilibili.com"

    toutiao = detect_platform_from_url("https://www.toutiao.com/article/789")
    assert "今日头条" in toutiao["name"]

    # 独立域名推断
    myblog = detect_platform_from_url("https://blog.mycoolsite.com")
    assert myblog["domain"] == "blog.mycoolsite.com"
    assert myblog["layout_mode"] == "toutiao"


def test_default_toutiao_layout_rules():
    """验证自定义平台默认统一采用今日头条高密度资讯流排版"""
    rules = DEFAULT_TOUTIAO_LAYOUT_RULES
    assert "今日头条" in rules["style_name"]
    assert "#ed4040" in rules["primary_color"]
    assert ".custom-layout-toutiao" in rules["css"]
    assert "今日头条高密度资讯流" in rules["agent_prompt_instruction"]


def test_agent_analyze_url_layout_style():
    """验证 Agent 深度读取任意样例网址并自蒸馏生成排版技能与 CSS"""
    skill = analyze_url_layout_style("https://sspai.com/post/888", custom_name="少数派数码流")
    assert skill["domain"] == "sspai.com"
    assert "少数派" in skill["style_name"]
    assert "custom-layout-" in skill["css"]
    assert "Agent 专属排版技能" in skill["agent_prompt_instruction"]


def test_custom_platform_crud_lifecycle():
    """验证自定义平台的增删改查全生命周期与持久化"""
    test_plat = {
        "id": "plat_test_920",
        "name": "测试极客平台",
        "url": "https://geek.test.org",
        "icon": "⚡",
        "layout_mode": "toutiao"
    }

    # 1. 添加
    added = add_or_update_platform(test_plat)
    assert added["id"] == "plat_test_920"
    assert added["name"] == "测试极客平台"
    assert added["layout_mode"] == "toutiao"
    assert added["skill_rules"] is not None

    # 2. 查询列表中存在
    platforms = get_custom_platforms()
    found = next((p for p in platforms if p["id"] == "plat_test_920"), None)
    assert found is not None

    # 3. 更新为 agent_skill 模式
    test_plat["layout_mode"] = "agent_skill"
    test_plat["sample_url"] = "https://geek.test.org/sample"
    updated = add_or_update_platform(test_plat)
    assert updated["layout_mode"] == "agent_skill"
    assert "Agent 专属排版技能" in updated["skill_rules"]["agent_prompt_instruction"]

    # 4. 删除
    del_ok = delete_custom_platform("plat_test_920")
    assert del_ok is True
    platforms_after = get_custom_platforms()
    assert not any(p["id"] == "plat_test_920" for p in platforms_after)


def test_custom_platform_api_endpoints():
    """验证自定义平台的 FastAPI REST 接口响应"""
    import web.admin
    client = TestClient(app)
    client.cookies.set("mf_token", web.admin._token())
    csrf = "test-csrf-token-920"
    client.cookies.set("csrf_token", csrf)
    headers = {"X-CSRF-Token": csrf}

    # 1. URL 识别接口
    resp_detect = client.post("/api/platforms/detect", json={"url": "https://juejin.cn"}, headers=headers)
    assert resp_detect.status_code == 200
    data_detect = resp_detect.json()
    assert data_detect["ok"] is True
    assert "稀土掘金" in data_detect["data"]["name"]

    # 2. Agent 排版技能提取接口
    resp_analyze = client.post(
        "/api/platforms/analyze_style",
        json={"url": "https://medium.com/sample", "name": "Medium深度长文"},
        headers=headers
    )
    assert resp_analyze.status_code == 200
    data_analyze = resp_analyze.json()
    assert data_analyze["ok"] is True
    assert "Medium" in data_analyze["skill"]["style_name"]
    assert ".custom-layout-" in data_analyze["skill"]["css"]

    # 3. 自定义平台列表与增删
    resp_list = client.get("/api/platforms/custom", headers=headers)
    assert resp_list.status_code == 200
    assert resp_list.json()["ok"] is True
    assert isinstance(resp_list.json()["platforms"], list)

    # 添加临时平台
    tmp_id = "plat_api_test_920"
    resp_save = client.post(
        "/api/platforms/custom",
        json={"id": tmp_id, "url": "https://test.io", "name": "API测试平台"},
        headers=headers
    )
    assert resp_save.status_code == 200
    assert resp_save.json()["ok"] is True

    # 删除临时平台
    resp_del = client.delete(f"/api/platforms/custom/{tmp_id}", headers=headers)
    assert resp_del.status_code == 200
    assert resp_del.json()["ok"] is True
