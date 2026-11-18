# SPDX-License-Identifier: BUSL-1.1
"""设置入口去重 + 被隐藏弹窗修复（V15.9.4）。

用户原话：「现在依旧是有多个设置重复的地方，就比如说生图的设置，还有写作的一些
默认设置，包括现在这几个不同供应商的 API 设置依旧好像有冲突。针对一个小白客户
来说，这个设置太难。」

排查后确认这不是"样式问题"，而是四个实打实的功能缺陷叠加：

1. **生图模型三套状态各自为政**：`yimu_studio_image_model`、`yimu_copilot_image_model`
   与后端 `config.image.model` 互不同步。在一处换了模型，另一处还是旧值，
   用户看到的就是"两边打架、不知道哪个算数"。
2. **`getImageModel()` 会自己调自己**：三个键都为空时（首装 / 清缓存后）无限递归
   到栈溢出，被 try/catch 吞掉后静默返回空串，表现为"设置莫名其妙丢了"。
3. **两个全屏弹窗被写进了 `#lite-drafts-modal` 内部**，而后者默认 `display:none`，
   于是「Agent 配置」点了完全没反应、长任务没有执行中进度窗。
4. **设置页里同一件事有两套说法**：顶部的「3 个 API 入口」说明卡 + 页面里的三层架构
   总览 + 个人中心的 API Vault 卡片，三处并列。

本文件只锁"结构不变量"——这些都是模板/前端源码层面的约定，用字符串断言即可，
不需要起浏览器：

- 设置页必须有「三件事」状态总览（每件事只有一个入口按钮）；
- 系统维护必须收进折叠区，不再平铺；
- 生图模型在 Agent 弹窗里必须是只读回显，不许再出现第二个 `<select>`；
- `getImageModel()` 里不许出现递归调用；
- 被隐藏的弹窗必须被搬出 `#lite-drafts-modal`。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "web" / "templates" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    assert TPL.exists(), f"模板缺失: {TPL}"
    return TPL.read_text(encoding="utf-8")


# ── 1. 生图模型单一真源 ──────────────────────────────────────────────

def test_image_model_has_single_source_functions(html: str) -> None:
    """必须存在 getImageModel / setImageModel，且只认一个键。"""
    assert "function getImageModel()" in html
    assert "function setImageModel(" in html
    assert "const IMAGE_MODEL_KEY = 'yimu_image_model';" in html


def test_get_image_model_does_not_recurse(html: str) -> None:
    """`getImageModel` 函数体内不允许再出现 `getImageModel(` 调用。

    旧实现写成 ``localStorage.getItem('yimu_copilot_image_model') || getImageModel() || ''``，
    三个键皆空时无限递归；这里用词法切片把函数体抠出来单独检查。
    """
    start = html.index("function getImageModel()")
    # 函数体到下一个顶层 `function ` 声明为止
    end = html.index("\nfunction ", start + 10)
    body = html[start:end]
    calls = re.findall(r"getImageModel\s*\(", body)
    # 第一次出现是函数自身的声明 `function getImageModel()`
    assert len(calls) == 1, f"getImageModel 体内出现自调用，存在栈溢出风险: {calls}"


def test_image_model_legacy_keys_are_migrated(html: str) -> None:
    """两个旧键必须仍在迁移列表里，否则老用户升级后模型选择会丢。"""
    assert "'yimu_studio_image_model'" in html
    assert "'yimu_copilot_image_model'" in html
    assert "IMAGE_MODEL_LEGACY_KEYS" in html


def test_no_stray_image_model_select_in_copilot_modal(html: str) -> None:
    """Agent 弹窗里不许再有第二个生图模型下拉框——只读回显 + 跳转按钮。"""
    assert 'id="copilot-image-model-select"' not in html, (
        "Agent 配置弹窗里又出现了生图模型下拉框：这会和「系统设置 → AI 配图设置」"
        "形成第二个入口，正是用户抱怨的“设置重复/互相打架”。"
    )
    assert 'id="copilot-image-model-readout"' in html


def test_save_image_cfg_writes_both_sides(html: str) -> None:
    """保存「AI 配图设置」必须同时写后端与前端真源，否则两处显示不一致。"""
    start = html.index("async function saveImageCfg()")
    end = html.index("\nasync function ", start + 10)
    body = html[start:end]
    # V15.9.6：生图默认改由能力线（gateway.capability_defaults.image）承载，
    # 保存时先写后端默认、再回写前端单一真源——两者都必须有。
    assert "setImageModel(" in body, "saveImageCfg 没有回写前端单一真源"
    assert "/api/models/provider/set_default" in body, "saveImageCfg 没有写入能力线默认"


def test_save_copilot_settings_does_not_clobber_image_model(html: str) -> None:
    """保存 Agent 配置不得把已选生图模型冲成 __default__。"""
    start = html.index("function saveCopilotSettings()")
    end = html.index("\nfunction ", start + 10)
    body = html[start:end]
    assert "setImageModel(imgModel)" not in body, (
        "保存 Agent 配置时仍在用下拉框的值改写生图模型；下拉框已移除，"
        "这里会把用户选好的模型清空。"
    )


# ── 2. 被隐藏的全屏弹窗 ─────────────────────────────────────────────

def test_fixed_modals_are_reparented(html: str) -> None:
    """两个被误嵌进 #lite-drafts-modal 的全屏弹窗必须在运行时搬出来。"""
    assert "function reparentFixedModals()" in html
    for mid in ("agent-task-progress-modal", "copilot-settings-modal"):
        assert f"'{mid}'" in html
    # 两个打开函数都要有兜底调用，避免 DOMContentLoaded 时序问题
    for fn in ("async function openCopilotSettingsModal()", "function openAgentTaskModal("):
        assert fn in html
    assert html.count("reparentFixedModals()") >= 3


# ── 3. 设置页去重与降噪 ─────────────────────────────────────────────

def test_settings_hub_three_things_present(html: str) -> None:
    """设置页顶部必须有三件事状态总览，且每件事只有一个跳转按钮。"""
    for hid in ("set-hub-key", "set-hub-img", "set-hub-style"):
        assert f'id="{hid}"' in html
    for vid in ("set-hub-key-val", "set-hub-img-val", "set-hub-style-val"):
        assert f'id="{vid}"' in html
    assert "function renderSettingsHub()" in html
    # 必须在 refresh 链路上被调用，否则永远显示"加载中…"
    assert "renderSettingsHub();" in html


def test_advanced_settings_collapsed(html: str) -> None:
    """系统维护组必须收进 <details>，默认折叠。"""
    assert 'class="set20-adv"' in html
    seg_start = html.index('class="set20-adv"')
    seg = html[seg_start:seg_start + 200]
    assert "open" not in seg.split(">")[0], "高级设置被默认展开了，等于没折叠"


def test_duplicate_api_entry_banner_is_deemphasized(html: str) -> None:
    """「3 个 API 入口」说明卡不能再是平铺三列大卡，且进入设置页时要隐藏。"""
    assert 'id="key-guide-card"' in html
    assert "yimu_key_guide_off" in html
    assert "subId === 'sp-settings'" in html
    # 旧的大标题措辞应已消失（与新总览重复）
    assert "30 秒看懂 3 个「API」入口的区别" not in html


def test_unused_tier_css_removed_or_harmless(html: str) -> None:
    """三层架构总览的旧标记必须已经不在页面上（否则又是一套并列说明）。"""
    assert '<div class="set20-tier">' not in html


# ── 4. 浅色主题可读性 ───────────────────────────────────────────────

def test_light_theme_card_titles_have_contrast(html: str) -> None:
    """浅色主题下这些卡片标题原本写死 #fff（白底白字），必须有覆盖规则。"""
    assert '[data-theme="light"] .set20-card .tt' in html
    assert '[data-theme="light"] .set-hub .h b' in html


# ── 5. 弹窗数据健壮性 ───────────────────────────────────────────────

def test_voices_list_is_guarded(html: str) -> None:
    """音色接口返回非数组时不许让整个 Agent 弹窗抛异常打不开。"""
    assert "Array.isArray(cachedVoicesData)" in html
