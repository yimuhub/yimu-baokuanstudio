# SPDX-License-Identifier: BUSL-1.1
"""R10 小白体验回归：术语减负与首次体验保障的前端静态护栏。

验收标准（对应审查报告 P1「小白术语减负」+ P0「首篇体验保障」）：
- NX-1 控制中心存在「3 个 API 入口」小白说明卡，且三个入口均有悬停解释
- NX-2 说明卡带「小白点这里配置」直达入口（不是死胡同）
- NX-3 首次引导 Wizard 明示「首篇完整体验券」权益
- NX-4 默认系统模式为极简（lite）——小白落地页是对话式界面而非大屏
- NX-5 小红书发布排队文案含可行动指引（防「卡片图 N 张，待发布」式黑话）
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "web" / "templates" / "index.html"
ORCH = REPO_ROOT / "core" / "orchestrator.py"


class TestNoviceTermReduction:
    def test_key_guide_card_exists_with_action(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert 'id="key-guide-card"' in html, "缺少 Key 入口小白说明卡"
        assert "小白点这里配置" in html, "说明卡必须有直达配置入口"
        # 三个入口的通俗解释都要在卡里
        for kw in ("系统与 API 配置", "我的 API", "API 网关服务"):
            assert kw in html

    def test_key_entries_have_hover_hints(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        # 系统与 API 配置 / API 网关服务 sub-tab 悬停提示
        assert re.search(r'data-sp="sp-settings"[^>]*title="', html)
        assert re.search(r'data-sp="sp-gateway"[^>]*title="', html)
        # 顶部「我的API」入口提示须包含「可跳过/新手」类安抚词
        m = re.search(r'openUserVaultModal\(\)"[^>]*title="([^"]+)"', html)
        assert m and ("跳过" in m.group(1) or "无需" in m.group(1) or "新手" in m.group(1))


class TestFirstPieceFrontend:
    def test_wizard_mentions_first_piece_voucher(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "首篇完整体验券" in html, "首次引导必须明示首篇完整体验权益"

    def test_default_system_mode_is_lite(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "localStorage.getItem('yimu_system_mode') || 'lite'" in html


class TestXhsQueueCopy:
    def test_xhs_queue_copy_is_actionable(self):
        src = ORCH.read_text(encoding="utf-8")
        assert "自动发布组件未安装" in src, "小红书缺组件时必须明示"
        assert "一键复制图文" in src, "必须给出替代动作（复制图文发布）"
        # 旧的黑话文案不应保留
        assert "张，待发布" not in src
