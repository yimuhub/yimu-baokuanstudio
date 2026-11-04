# SPDX-License-Identifier: BUSL-1.1
"""V11.2 三栏工作台「原型对齐」专项门禁。

锁死左栏 / 中栏 / 右栏动作条与 ui-v2 原型的一致性，
防止后续改动把注入块、作用域或业务接线改掉。

1. 外壳增强脚本存在并在模板中挂载
2. 左栏四块齐全：新建创作 / 二级树 / 最近产出 / 底部图标条
3. 中栏三块齐全：标题副行 / 胶囊条 / 圆角输入框与圆形发送
4. 右栏动作条三键齐全，且接的是既有业务函数
5. 所有增强样式都收在 body[data-shell="v2"] 之下，经典版不受影响
6. 注入块全部经由既有业务函数，不复制一套逻辑
7. 中英双语键齐全，不出现半中半英
8. 内联 SVG 有明确尺寸（否则按 300×150 撑开）
9. 代码里不得残留调试开关
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "web/templates/index.html"
RAIL_JS = REPO_ROOT / "web/static/js/workbench-rail.js"
SHELL_JS = REPO_ROOT / "web/static/js/workbench-shell.js"


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _rail() -> str:
    return RAIL_JS.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 1. 文件与挂载
# --------------------------------------------------------------------------
def test_rail_script_exists_and_mounted():
    """增强脚本存在，且在主模板中排在 shell 脚本之后加载。"""
    assert RAIL_JS.exists(), "缺少 web/static/js/workbench-rail.js"
    html = _template()
    assert '/static/js/workbench-shell.js' in html
    assert '/static/js/workbench-rail.js' in html
    assert html.index("workbench-shell.js") < html.index("workbench-rail.js"), (
        "增强脚本必须在 shell 脚本之后加载，才能复用其已建好的三栏骨架"
    )


def test_rail_script_has_no_debug_leftovers():
    """不得残留临时调试开关或演示自动点击。"""
    js = _rail()
    for marker in ("TEMP-DEBUG", "TEMP-DEMO", "TEMP-PROBE", "TEMP-EN"):
        assert marker not in js, f"残留调试代码: {marker}"
    assert "__en=1" not in js
    assert "document.title = 'DBG" not in js


# --------------------------------------------------------------------------
# 2. 左栏
# --------------------------------------------------------------------------
def test_rail_left_column_blocks():
    """左栏四块齐全：新建创作、二级树、最近产出、底部图标条。"""
    js = _rail()
    for token in (
        "rail-new",
        "rail-subs",
        "rail-sub",
        "rail-head",
        "rail-list",
        "rail-item",
        "rail-icobtn",
        "rail-chev",
    ):
        assert token in js, f"左栏缺少注入块: {token}"

    # 新建创作按钮接既有入口
    assert "newLiteDraft" in js
    # 最近产出点击接既有选稿函数
    assert "selectDraft" in js


def test_rail_sub_tree_uses_real_sub_tabs():
    """二级树必须指向真实存在的子标签 id，不能是死链。"""
    js = _rail()
    html = _template()
    targets = set(re.findall(r"sp: '([a-z]+)::(sp-[a-z-]+)'", js))
    assert targets, "二级树没有任何真实子标签目标"
    for panel, sp_id in targets:
        assert f'id="{sp_id}"' in html, f"二级树指向了不存在的子视图: {sp_id}"
        # 页面里的两种写法都允许：带空格或不带空格
        pattern = rf"switchSubTab\(\s*'{panel}'\s*,\s*'{sp_id}'\s*\)"
        assert re.search(pattern, html), f"子视图 {sp_id} 没有对应的 switchSubTab 入口"


def test_rail_new_button_uses_business_entry():
    """新建创作按钮必须调既有业务函数，不允许自己实现清空逻辑。"""
    js = _rail()
    assert "newLiteDraft" in js
    assert "openNewDraftModal" in js
    # 不允许自己写清空草稿的实现
    assert "fetch('/api/drafts" not in js
    assert "innerHTML = ''" not in js


# --------------------------------------------------------------------------
# 3. 中栏
# --------------------------------------------------------------------------
def test_rail_center_column_blocks():
    """中栏三块齐全：标题副行、胶囊条、圆角输入框与圆形发送。"""
    js = _rail()
    assert "rail-headsub" in js
    assert "rail-subbar" in js
    assert "composer-v11-box" in js
    assert "composer-v11-wrap" in js
    assert "rail-send" in js

    css = _template()
    assert 'body[data-shell="v2"] .main-wrapper .rail-subbar' in css
    assert 'body[data-shell="v2"] #btn-copilot-send.rail-send' in css


def test_rail_subbar_built_from_real_chips():
    """胶囊条必须由页面上真实存在的快捷芯片派生，点击仍走原芯片。"""
    js = _rail()
    html = _template()
    assert "copilot-chip" in js
    assert html.count("copilot-chip") > 0, "页面里已没有快捷芯片，胶囊条会失去数据源"
    assert "chip.click()" in js, "胶囊点击必须转发到原芯片，避免逻辑分叉"


def test_rail_empty_guide_only_when_idle():
    """功能引导卡只在对话为空时出现，一旦开聊自动撤掉。"""
    js = _rail()
    assert "rail-guide" in js
    assert "syncEmptyGuide" in js
    assert "msgs > 1" in js, "需要在有真实对话后撤掉引导卡"


# --------------------------------------------------------------------------
# 4. 右栏动作条
# --------------------------------------------------------------------------
def test_assets_action_bar_wired_to_business():
    """右栏动作条的复制 / 导出 / 发布三键必须接既有业务函数。"""
    js = _rail()
    assert "assets-acts" in js
    for fn in ("copyLiteCurrentRichContent", "dlXhsZip", "openPublishModal"):
        assert fn in js, f"动作条未接业务函数: {fn}"

    assert "data-act=\"copy\"" in js
    assert "data-act=\"export\"" in js
    assert "data-act=\"publish\"" in js


# --------------------------------------------------------------------------
# 5. 作用域隔离
# --------------------------------------------------------------------------
def test_enhancement_css_scoped_to_v2():
    """V11.2 的每条选择器都必须挂在 body[data-shell="v2"] 之下。"""
    html = _template()
    start = html.find("V11.2 · 与 ui-v2 原型对齐")
    assert start > 0, "缺少 V11.2 样式块"
    end = html.find("</style>", start)
    block = html[start:end]
    assert block.strip(), "V11.2 样式块为空"

    # 去掉注释与 @media 行后，检查顶层选择器前缀
    body = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    offenders = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("@") or s in ("}", "{") or s.startswith("}"):
            continue
        if "{" not in s:
            continue
        sel = s.split("{", 1)[0].strip().rstrip(",")
        if not sel:
            continue
        for one in sel.split(","):
            one = one.strip()
            if not one:
                continue
            if not one.startswith('body[data-shell="v2"]'):
                offenders.append(one)
    assert not offenders, f"以下选择器越出了 v2 作用域: {offenders[:5]}"


def test_classic_mode_untouched():
    """经典版入口与回落逻辑仍然存在，且增强块在经典版被隐藏。"""
    html = _template()
    assert "yimu.shell.mode" in html
    assert "?legacy=1" in html or "legacy" in html
    assert 'id="shell-classic-pill"' in html
    # 窄屏兜底：增强块在小屏收起
    assert "@media (max-width: 1279px)" in html


# --------------------------------------------------------------------------
# 6. 注入 SV G 尺寸
# --------------------------------------------------------------------------
def test_inline_svg_has_explicit_size():
    """注入的内联 SVG 必须有明确尺寸，否则浏览器按 300×150 撑开。"""
    css = _template()
    for sel in (
        'body[data-shell="v2"] > .side .rail-chev svg',
        'body[data-shell="v2"] > .side .rail-icobtn svg',
        'body[data-shell="v2"] .assets-acts .btn svg',
        'body[data-shell="v2"] .rail-guide .rg-card .ic svg',
    ):
        assert sel in css, f"缺少尺寸规则: {sel}"


# --------------------------------------------------------------------------
# 7. 双语
# --------------------------------------------------------------------------
def test_rail_bilingual_strings():
    """注入块的固定文案必须中英成对，避免英文模式残留中文。"""
    js = _rail()
    assert "function t(zh, en)" in js or "function t(zh,en)" in js
    assert "PAGE_SUB_EN" in js
    assert "SB_EN" in js
    assert "isEn()" in js
    assert "applyLang" in js, "缺少语言切换后的就地刷新"

    # 关键文案的英文对照不可缺
    for en in ("New draft", "Recent", "Copy", "Export", "Publish"):
        assert en in js, f"缺少英文文案: {en}"


def test_rail_i18n_dict_untouched_keys():
    """词典里的 shell_* 键保持完整（右栏同批交付的文案不能丢）。"""
    raw = (REPO_ROOT / "web/static/js/i18n_dict.json").read_text(encoding="utf-8")
    d = json.loads(raw)
    for key in ("资产台", "成稿", "图片", "视频", "数据", "⛶ 放大", "🕰 经典版"):
        assert key in d, f"词典缺少 {key}"
