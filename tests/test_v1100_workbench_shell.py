# SPDX-License-Identifier: BUSL-1.1
"""V11.0.0（长风谣 · Longwind Ballad）三栏工作台外壳专项门禁测试。

验收口径：
1. 版本单一真源步进至 11.0.0，代号「长风谣 / Longwind Ballad」，序列状态同步消耗。
2. 主界面具备左功能栏 / 中主台 / 右资产台三列结构与两条拖拽手柄。
3. 右栏四个资产页全部绑定真实只读接口，不允许出现静态假数据。
4. 经典版可双向往返：`?legacy=1` 进入，`yimu.shell.mode` + 返程浮标返回。
5. 业务零改动：7 个业务面板、8 个一级导航、既有脚本顺序全部保留。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import version

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "web/templates/index.html"
SHELL_JS = ROOT / "web/static/js/workbench-shell.js"


@pytest.fixture(scope="module")
def html() -> str:
    from web.admin import get_html_page

    return get_html_page()


@pytest.fixture(scope="module")
def shell_js() -> str:
    return SHELL_JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 版本真源


def test_v1100_version_and_codename():
    """版本单一真源已跨代步进至 11.0.0（长风谣）。"""
    assert version.__version__ == "11.0.0"
    assert version.__codename__ == "长风谣"
    assert version.__codename_en__ == "Longwind Ballad"
    assert version.get_version() == "11.0.0"
    info = version.get_version_info()
    assert info["codename"] == "长风谣"
    assert info["codename_en"] == "Longwind Ballad"


def test_v1100_packaging_and_locales_in_sync():
    """pyproject 与中英语言包版本号同步，不允许版本漂移。"""
    assert 'version = "11.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    zh = json.loads((ROOT / "web/static/locales/zh-CN.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "web/static/locales/en-US.json").read_text(encoding="utf-8"))
    assert zh["version"] == "11.0.0"
    assert en["version"] == "11.0.0"
    assert zh["codename"] == "长风谣"
    assert en["codename"] == "Longwind Ballad"


def test_v1100_codename_sequence_state():
    """代号序列状态已消耗「长风谣」，下一个应为「沧海吟」。"""
    state = json.loads((ROOT / "release-codenames.json").read_text(encoding="utf-8"))
    assert state["current_version"] == "11.0.0"
    assert state["current_codename_zh"] == "长风谣"
    assert state["sequence"][state["next_index"]]["zh"] == "沧海吟"
    assert state["history"][-1]["version"] == "v11.0.0"


# ---------------------------------------------------------------- 三栏外壳


def test_v1100_three_pane_markup(html):
    """三栏容器与两条拖拽手柄就位，且右栏四页签完整。"""
    assert 'id="assetsPanel"' in html
    assert 'class="assets"' in html
    assert 'id="assetsTabs"' in html
    for tab in ("doc", "img", "video", "data"):
        assert f'data-at="{tab}"' in html, f"缺少右栏页签 {tab}"
    # 手柄由脚本创建（经典版不留多余节点），因此断言脚本侧
    js = SHELL_JS.read_text(encoding="utf-8")
    assert "rz rz-l" in js
    assert "rz rz-r" in js
    assert "MIN_MAIN" in js


def test_v1100_shell_css_contract():
    """三栏布局由 CSS 变量驱动，且窄屏必须回落经典版。"""
    css = TEMPLATE.read_text(encoding="utf-8")
    assert "body[data-shell=\"v2\"]" in css
    assert "--railw: 248px" in css
    assert "--panelw: 400px" in css
    assert "grid-template-columns: var(--railw) minmax(0, 1fr) var(--panelw)" in css
    assert "@media (max-width: 1279px)" in css
    # 专注态
    assert 'body[data-shell="v2"][data-focus="on"]' in css
    # 灯箱
    assert ".a-lb.on" in css


def test_v1100_layout_decided_before_paint(html):
    """布局形态必须由首屏内联脚本决定，避免经典版用户看到三栏闪烁。"""
    body_idx = html.find("<body>")
    assert body_idx > 0
    head_seg = html[body_idx: body_idx + 1400]
    assert "data-shell" in head_seg
    assert "legacy" in head_seg and "classic" in head_seg
    assert "yimu.shell.mode" in head_seg
    # <body> 本身不得写死 data-shell="v2"
    assert not re.search(r"<body[^>]*data-shell=", html)


def test_v1100_shell_script_loaded_last(html):
    """外壳脚本在业务脚本之后加载（依赖全局 S / curDraft / api）。"""
    shell_pos = html.find("/static/js/workbench-shell.js")
    assert shell_pos > 0
    assert shell_pos > html.find("async function api(path")
    assert shell_pos < html.rfind("</body>")


# ---------------------------------------------------------------- 右栏真实数据


def test_v1100_assets_bind_real_endpoints(shell_js):
    """右栏四页必须是真实接口，不允许写死演示数据。"""
    for ep in (
        "/api/drafts/",
        "/history",
        "/api/video/tasks",
        "/api/assets/library",
        "/api/tasks",
        "/restore",
    ):
        assert ep in shell_js, f"右栏未接入 {ep}"
    # 不允许出现「示例/演示」类静态假数据
    for fake in ("示例稿件", "演示数据", "mockData", "fakeData"):
        assert fake not in shell_js


def test_v1100_assets_follow_selection(shell_js):
    """选稿联动 + 全局刷新联动 + 专注态 + 灯箱 均需存在。"""
    assert "function activeDraftId" in shell_js
    assert "selectDraft" in shell_js
    assert "function setFocus" in shell_js
    assert "function openLB" in shell_js
    assert "__shellWrapped" in shell_js  # 业务函数可安全包裹


def test_v1100_shell_never_breaks_business(shell_js):
    """外壳对业务函数的包裹必须吞掉自身异常，不能反向阻断业务。"""
    assert "外壳永不阻断业务" in shell_js
    # 非 v2 布局直接退出，不注册任何监听
    assert 'getAttribute(\'data-shell\') !== \'v2\'' in shell_js or \
           'getAttribute("data-shell") !== "v2"' in shell_js


def test_v1100_classic_round_trip(html):
    """经典版入口与返程浮标同时存在。"""
    assert 'id="assetsClassic"' in html
    assert 'id="shell-classic-pill"' in html
    assert 'id="shell-fab"' in html


# ---------------------------------------------------------------- 业务零改动


def test_v1100_all_business_panels_preserved(html):
    """七个业务面板与八个一级导航一个都不能少。"""
    for pid in ("dashboard", "inspire", "drafts", "studio", "console", "profile", "pricing"):
        assert f'id="p-{pid}"' in html, f"面板 p-{pid} 丢失"
    assert html.count('class="nav-item') >= 8
    assert 'id="p-lite-mode"' in html


def test_v1100_header_overflow_menu(shell_js):
    """顶栏自动收敛：容器变窄时把动作收进「更多」，不可直接删除功能。"""
    assert "buildHeaderOverflow" in shell_js
    assert "hdr-menu" in shell_js
    assert "HDR_ORDER" in shell_js
    # 溢出判断不能用 scrollWidth（flex-end 溢出在左侧，scrollWidth 统计不到）
    assert "justify-content:flex-end" in shell_js or "flex-end" in shell_js


def test_v1100_width_persistence(shell_js):
    """栏宽记忆与复位。"""
    assert "yimu.shell.w" in shell_js
    assert "localStorage" in shell_js
    assert "resetWidths" in shell_js
