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
    """PC 顶栏必须常驻7.1 新增能力的入口。"""

    def test_has_price_entry(self, index_html: str):
        """价格页入口：R3-1 做的价格页如果没入口，等于没做。"""
        assert 'href="/pricing"' in index_html, (
            "首页顶栏缺少价格页入口 href=\"/pricing\"——"
            "R3-1 的价格页用户无法到达，等同功能未上线"
        )

    def test_has_releases_entry(self, index_html: str):
        """7.1 升级总览入口：本次升级的可见性总入口。"""
        assert 'href="/admin/releases"' in index_html, (
            "首页顶栏缺少升级总览入口 href=\"/admin/releases\""
        )

    def test_entry_has_tooltip_explaining_it(self, index_html: str):
        """入口要有说明，否则用户不知道点进去看什么。"""
        assert "升级总览" in index_html, "7.1 入口缺少「升级总览」说明文案"

    def test_release_entry_is_visually_distinct(self, index_html: str):
        """入口用主色高亮，不应与旁边「刷新状态」长得一样被忽略。"""
        seg = index_html[max(0, index_html.find('id="nav-release-entry"') - 260):][:520]
        assert "nav-release-entry" in seg, "无法定位 7.1 入口标记"
        assert "var(--primary)" in seg, (
            "7.1 入口未使用主色高亮，用户容易当作普通按钮忽略"
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
    """移动端也要能直达 7.1 新能力。"""

    def test_mobile_has_price_entry(self, mobile_html: str):
        assert 'href="/pricing"' in mobile_html, "移动端缺少价格页入口"

    def test_mobile_has_releases_entry(self, mobile_html: str):
        assert 'href="/admin/releases"' in mobile_html, "移动端缺少 7.1 升级总览入口"


class TestContractRegistration:
    """契约必须登记，避免 test_contract_lock 漂移。"""

    def test_releases_route_registered(self):
        """`/admin/releases` 必须登记进 CONTRACT.md。"""
        text = CONTRACT.read_text(encoding="utf-8")
        assert '`GET /admin/releases`' in text, (
            "/admin/releases 未登记进 docs/CONTRACT.md，"
            "会导致 tests/test_contract_lock.py 双向锁死失败"
        )


class TestReleasesPageModule:
    """总览页模块本身。"""

    def test_module_exists(self):
        assert (BASE / "studio" / "releases_page.py").is_file(), (
            "缺少 studio/releases_page.py"
        )

    def test_renders_without_error(self):
        """页面渲染不抛异常，且 5 个批次都在。"""
        from studio.releases_page import _RELEASES, _render_releases_page

        codes = [r["code"] for r in _RELEASES]
        assert codes == ["R1", "R2", "R3", "R4", "R5"], f"批次不全：{codes}"
        html = _render_releases_page()
        assert "__VERSION__" not in html, "版本占位符未被替换"
        assert "__PORTS__" not in html, "入口占位符未被替换"
        assert "__RELEASES__" not in html, "批次占位符未被替换"
        assert "7.1" in html

    def test_mentions_key_honest_disclosures(self):
        """总览页必须写清三件需要用户知道的事，不能只报喜。"""
        from studio.releases_page import _render_releases_page

        html = _render_releases_page()
        for kw in ("商户", "Free", "PUBLIC_BASE_URL"):
            assert kw in html, f"总览页未披露关键事项：{kw}"

    def test_lists_all_ports(self):
        """8 个可点入口都要在。"""
        from studio.releases_page import _PORTS, _render_releases_page

        html = _render_releases_page()
        for _icon, _name, path, _desc, _c in _PORTS:
            assert f'href="{path}"' in html, f"总览页缺少入口：{path}"