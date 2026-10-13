# SPDX-License-Identifier: BUSL-1.1
"""7.1 可见性回归护栏。

为什么需要这个文件
------------------
2026-10-09 用户反馈「7.1 的功能都看不到」。核查后确认：
34 项改动全部真实落地且测试通过，但——

1. 新能力全挂在二级路径（``/pricing``、``/admin/metrics`` …），
   而首页是升级前的旧版式，**没有任何指向它们的入口**；
2. 顶栏与移动端把版本号**写死**为 ``V7``，升到 7.1.0 后用户看到的仍是 V7。

也就是说：功能做了，但从用户视角等于没做。本文件把「可见性」变成可断言的契约，
防止后续迭代再次把入口删掉或把版本号写回去。

判据原则：**断言「入口存在」而不是断言「样式好看」**——
UI 改版不应让这些测试变红，但「删掉入口 / 写死版本号」必须变红。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
INDEX = BASE / "web" / "templates" / "index.html"
MOBILE = BASE / "web" / "templates" / "mobile.html"
CONTRACT = BASE / "docs" / "CONTRACT.md"


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def mobile_html() -> str:
    return MOBILE.read_text(encoding="utf-8")


class TestTopbarEntry:
    """PC 顶栏与全站必须具备商业化与价格套餐的入口。"""

    def test_has_price_entry(self, index_html: str):
        """价格页与套餐入口：商业化套餐与价格中心可到达。"""
        assert 'href="/pricing"' in index_html, (
            "首页缺少价格页入口 href=\"/pricing\"——"
            "商业化价格与套餐用户无法到达，等同功能未上线"
        )


class TestVersionNotHardcoded:
    """版本号必须从接口读，不能写死。"""

    def test_pc_badge_reads_api(self, index_html: str):
        """PC 顶栏版本号从 /api/version 读取。"""
        assert 'id="nav-ver-text"' in index_html, (
            "缺少版本号占位元素 #nav-ver-text，无法显示真实版本"
        )
        assert "/api/version" in index_html, "PC 端未从 /api/version 读取真实版本"

    def test_mobile_badge_reads_api(self, mobile_html: str):
        """移动端徽章不得再写死 V7。"""
        assert 'id="mobile-ver-badge"' in mobile_html, (
            "移动端版本徽章缺少 id=\"mobile-ver-badge\"，无法绑定真实版本"
        )
        assert "/api/version" in mobile_html, "移动端未从 /api/version 读取真实版本"

    def test_mobile_not_hardcoded_v7(self, mobile_html: str):
        """移动端徽章不能是写死的 V7 文本。

        7.1.0 已发布，写死 V7 会让用户以为还是旧版——这正是本次反馈的现象之一。
        """
        m = re.search(r'id="mobile-ver-badge"[^>]*>\s*([^<]+?)\s*<', mobile_html)
        assert m, "找不到移动端版本徽章"
        text = m.group(1).strip()
        assert text != "V7", (
            f"移动端版本徽章仍写死为 {text!r}——7.1.0 已发布，"
            "应由 /api/version 填充，写死会让用户误判版本"
        )

    @pytest.mark.parametrize(
        "template_attr, fixture_name",
        [("index_html", "index_html"), ("mobile_html", "mobile_html")],
    )
    def test_version_parses_two_segments(self, request, template_attr: str, fixture_name: str):
        """版本号要解析成「7.1」两段，不是只取「7」。

        回归记录：曾写成 `split('.')[0]`，导致 `7.1.0` 被截成 `7`，
        顶栏显示「🆕7」，用户看不到小版本号。
        """
        html = request.getfixturevalue(fixture_name)
        assert re.search(r"split\('\.'\)", html), "未找到版本号解析代码"
        assert "slice(0, 2).join('.')" in html, (
            "版本号解析未取两段——`split('.')[0]` 会把 7.1.0 截成 7，"
            "顶栏只显示大版本号"
        )


class TestMobileEntry:
    """移动端商业化与套餐价格入口。"""

    def test_mobile_has_price_entry(self, mobile_html: str):
        assert 'href="/pricing"' in mobile_html, "移动端缺少价格页入口"