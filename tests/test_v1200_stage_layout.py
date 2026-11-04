"""V12.0.0 · 右栏舞台布局的回归锁

交互模型：左栏恒定 / 中栏恒定对话 / 点左侧功能在右栏打开 / 右栏可全屏。
这组断言只锁「结构契约」，不重复测业务逻辑：
  · 舞台脚本必须挂载、必须在 rail 之后、必须只在 v2 下工作
  · 7 个功能页必须都有舞台元数据，且与左栏 data-p 完全一致
  · 主区里的功能面板必须被 CSS 收进舞台，中栏必须常显
  · 全屏必须抬高层叠上下文（否则会被左栏盖住）
  · 新增样式必须全部挂在 body[data-shell="v2"] 之下
  · 全站不得再出现紫色系主色
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
TPL = BASE / "web/templates/index.html"
STAGE_JS = BASE / "web/static/js/workbench-stage.js"

# 除「极简模式」外的 7 个功能页：这些必须在右栏打开
STAGE_PAGES = ["dashboard", "inspire", "drafts", "studio", "console", "pricing", "profile"]


@pytest.fixture(scope="module")
def html() -> str:
    return TPL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js() -> str:
    return STAGE_JS.read_text(encoding="utf-8")


def _v12_block(html: str) -> str:
    start = html.find("V12 · 右栏舞台")
    assert start > 0, "缺少 V12 样式块"
    end = html.find("</style>", start)
    assert end > start
    return html[start:end]


def test_stage_script_exists(js: str) -> None:
    assert STAGE_JS.exists()
    assert len(js.splitlines()) > 200, "舞台脚本过短，疑似被截断"


def test_stage_script_mounted_after_rail(html: str) -> None:
    rail = html.find('<script src="/static/js/workbench-rail.js"></script>')
    stage = html.find('<script src="/static/js/workbench-stage.js"></script>')
    assert rail > 0, "缺少左栏脚本"
    assert stage > 0, "缺少舞台脚本"
    assert stage > rail, "舞台脚本必须在左栏脚本之后加载"


def test_stage_script_only_runs_on_v2(js: str) -> None:
    assert 'data-shell' in js and 'v2' in js, "舞台脚本必须自检 v2 外壳"
    assert "function isV2" in js
    # 初始化入口必须先判 isV2 再建节点
    boot = js[js.find("function boot()"):]
    head = boot[:400]
    assert "isV2()" in head, "boot 必须先判断 v2，否则经典版会多出节点"


def test_stage_has_no_debug_residue(js: str, html: str) -> None:
    for bad in ("PROBE_TMP", "console.log", "debugger"):
        assert bad not in js, f"舞台脚本残留调试代码：{bad}"
    assert "PROBE_TMP" not in html, "模板残留探针脚本"


@pytest.mark.parametrize("page", STAGE_PAGES)
def test_every_stage_page_has_meta(page: str, js: str, html: str) -> None:
    # PAGES 表里有这一页
    assert re.search(rf"\b{page}\s*:\s*\{{", js), f"PAGES 缺少 {page}"
    # 页面对应的面板 id 存在
    assert f'id="p-{page}"' in html, f"模板缺少 #p-{page}"
    # 左栏 nav 项存在
    assert f'data-p="{page}"' in html, f"左栏缺少 data-p={page}"


def test_stage_pages_match_nav(js: str) -> None:
    m = re.search(r"var PAGES = \{(.*?)\n  \};", js, re.S)
    assert m, "未找到 PAGES 定义"
    keys = set(re.findall(r"(\w+)\s*:\s*\{", m.group(1)))
    assert keys == set(STAGE_PAGES), f"PAGES 与预期不一致：{sorted(keys)}"


def test_lite_mode_is_permanent(html: str) -> None:
    block = _v12_block(html)
    assert 'body[data-shell="v2"] #p-lite-mode' in block
    assert "display: flex !important" in block, "中栏必须被强制为 flex，不受业务切换影响"


def test_feature_panels_hidden_from_main(html: str) -> None:
    block = _v12_block(html)
    # 主区直系的功能面板全部隐藏（舞台里的不在 main 下，不受影响）
    assert 'body[data-shell="v2"] .main-wrapper > main > .panel' in block
    assert "display: none !important" in block


def test_stage_container_and_controls_exist(html: str, js: str) -> None:
    for ident in ("workStage", "stageBody", "stageNm", "stageSb", "stageFull", "stageClose", "stageBack"):
        assert ident in js, f"舞台脚本缺少 #{ident}"
    # 舞台由 JS 注入，模板里不应写死（否则经典版会多一个空节点）
    assert 'id="workStage"' not in html, "舞台容器应由脚本注入，不要写死在模板"


def test_fullscreen_raises_stacking_context(html: str) -> None:
    block = _v12_block(html)
    assert '[data-stage-full="1"]' in block
    assert "position: fixed" in block
    # .assets 自身是层叠上下文（z-index: 20），不一起抬高会被左栏盖住
    assert 'body[data-shell="v2"][data-stage-full="1"] > .assets' in block
    assert "z-index: 9500" in block


def test_stage_css_scoped_to_v2(html: str) -> None:
    block = re.sub(r"/\*.*?\*/", "", _v12_block(html), flags=re.S)
    offenders = []
    for line in block.splitlines():
        t = line.strip()
        if not t or t.startswith("@") or t in ("{", "}") or t.startswith("}") or "{" not in t:
            continue
        sel = t.split("{", 1)[0].strip().rstrip(",")
        for one in sel.split(","):
            one = one.strip()
            if one and not one.startswith('body[data-shell="v2"]'):
                offenders.append(one)
    assert not offenders, f"以下选择器越出了 v2 作用域: {offenders[:6]}"


def test_no_purple_left(html: str) -> None:
    """V12 把全站主色收敛到品牌橙，紫色系不允许再出现。"""
    purple = ("#8b5cf6", "#a855f7", "#7c3aed", "#6366f1", "#a371f7", "#d946ef", "#9333ea", "#8957e5")
    css = (BASE / "web/static/css/modern_studio.css").read_text(encoding="utf-8")
    tokens = (BASE / "web/static/css/design-tokens.css").read_text(encoding="utf-8")
    for src, name in ((html, "index.html"), (css, "modern_studio.css"), (tokens, "design-tokens.css")):
        low = src.lower()
        for c in purple:
            assert c in ("",) or low.count(c) == 0, f"{name} 仍残留紫色 {c}"


def test_stage_tip_matches_dictionary(html: str) -> None:
    """中栏底部提示必须能被英文化，否则英文模式会漏中文。"""
    dict_map = json.loads((BASE / "web/static/js/i18n_dict.json").read_text(encoding="utf-8"))
    m = re.search(r'<span id="lite-tip">(.*?)</span>', html, re.S)
    assert m, "中栏提示缺少 #lite-tip"
    text = m.group(1).strip()
    assert text in dict_map, "中栏提示未进 i18n 词典，英文模式会残留中文"
    assert re.search(r"[\u4e00-\u9fa5]", dict_map[text]) is None, "词典译文不能含中文"


def test_rail_accordion_closes_others(html: str) -> None:
    """左栏二级树：切页时只保留一个展开，避免把「最近产出」顶出视口。"""
    rail = (BASE / "web/static/js/workbench-rail.js").read_text(encoding="utf-8")
    seg = rail[rail.find("导航点击后刷新选中态与二级展开"):]
    seg = seg[:1400]
    assert ".rail-subs.on" in seg, "缺少关闭其它二级树的逻辑"
    assert "classList.remove('on')" in seg


def test_business_switch_is_routed_to_stage(js: str) -> None:
    """舞台开着时，业务里的 switchToPage 必须改走舞台，不能切到看不见的主区。"""
    assert "switchToPage" in js
    assert "__stageWrapped" in js


def test_page_enter_loaders_wired(html: str) -> None:
    """进页必须拉真数据：订阅 / 工作台 / 控制中心 / 大屏 都要有进页钩子。

    此前只有影音工坊与个人中心挂了钩子，其余页面进页停在「加载中」。
    """
    seg = html[html.find("const pageLoaders = {"):][:700]
    assert seg, "缺少进页加载钩子表 pageLoaders"
    for key in ("dashboard", "drafts", "console", "pricing"):
        assert key in seg, f"进页钩子缺少 {key}"
    for fn in ("loadIntegratedPricingPanel", "renderDraftList", "loadTicketStatus", "healthLoad"):
        assert fn in html, f"进页加载函数 {fn} 不存在"
        assert fn in seg, f"进页钩子未挂 {fn}"


def test_switch_page_runs_business_before_move(js: str) -> None:
    """改道舞台前必须先让业务函数跑完（挂钩子、拉数据、切子视图），再搬面板。"""
    seg = js[js.find("function patchSwitchPage"):][:900]
    assert "orig.apply(this, arguments)" in seg
    idx_orig = seg.find("orig.apply(this, arguments)")
    idx_open = seg.find("open(key);")
    assert idx_open > idx_orig, "必须先调用原 switchToPage，再打开舞台"

    # 同一页重复触发不重复搬运，否则滚动位置与焦点会被冲掉
    oseg = js[js.find("function open(key)"):][:600]
    assert "current === key" in oseg, "缺少同页复用判断"
