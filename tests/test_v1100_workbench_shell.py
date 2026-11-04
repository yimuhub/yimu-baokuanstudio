# SPDX-License-Identifier: BUSL-1.1
"""V11 三栏工作台外壳专项门禁测试（版本与代号以 release-codenames.json 为准）。

验收口径：
1. 版本单一真源与代号序列状态互洽，pyproject / 语言包不得漂移。
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
    """版本单一真源与代号序列状态必须互洽（不硬编码具体版本号，避免补丁版漂移）。"""
    state = json.loads((ROOT / "release-codenames.json").read_text(encoding="utf-8"))
    assert version.__version__.startswith(("11.", "12.")), version.__version__
    assert version.__version__ == state["current_version"]
    assert version.__codename__ == state["current_codename_zh"]
    assert version.__codename_en__ == state["current_codename_en"]
    assert version.__codename_en__  # 英文代号不得为空
    info = version.get_version_info()
    assert info["version"] == version.__version__
    assert info["codename"] == version.__codename__
    assert info["codename_en"] == version.__codename_en__


def test_v1100_packaging_and_locales_in_sync():
    """pyproject 与中英语言包版本号必须跟 version.py 完全一致，不允许版本漂移。"""
    ver = version.__version__
    assert f'version = "{ver}"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    zh = json.loads((ROOT / "web/static/locales/zh-CN.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "web/static/locales/en-US.json").read_text(encoding="utf-8"))
    assert zh["version"] == ver
    assert en["version"] == ver
    assert zh["codename"] == version.__codename__
    assert en["codename"] == version.__codename_en__


def test_v1100_codename_sequence_state():
    """代号序列已消耗当前版本，history 末条与 current 一致，未越界。"""
    state = json.loads((ROOT / "release-codenames.json").read_text(encoding="utf-8"))
    assert state["current_version"] == version.__version__
    assert state["current_codename_zh"] == version.__codename__
    assert state["next_index"] < len(state["sequence"]), "代号序列已耗尽，需续批"
    # 当前代号必须是 history 最后一条，且与 next_index 指向的下一个不同
    last = state["history"][-1]
    assert last["version"] == "v" + state["current_version"]
    assert last["zh"] == state["current_codename_zh"]
    assert state["sequence"][state["next_index"]]["zh"] != state["current_codename_zh"]
    # 序列内不得有重复代号
    zh_seq = [c["zh"] for c in state["sequence"]]
    assert len(zh_seq) == len(set(zh_seq)), "代号序列出现重复"


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
