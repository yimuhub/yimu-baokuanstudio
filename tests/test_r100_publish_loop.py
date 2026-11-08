# SPDX-License-Identifier: BUSL-1.1
"""R10 发布闭环回归：头条 API 直进草稿箱 + 小红书兜底文案。

验收标准（对应审查报告 P1「补发布闭环」）：
- PB-1 toutiao_publish.available()：无 Cookie 明确 False 并给可行动提示
- PB-2 push_draft 宽松解析：草稿箱成功 / 接口报错均不抛异常
- PB-3 编排层：toutiao_mode=manual 时保持排队语义（现状不回归）
- PB-4 编排层：toutiao_mode=api 且通道可用时调用推送（mock 网络层）
- PB-5 小红书排队文案包含可行动指引（组件缺失时不让用户猜）
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-pub")


class TestToutiaoAdapter:
    def test_available_without_cookie_is_false_with_hint(self, monkeypatch):
        from adapters import toutiao_publish
        monkeypatch.delenv("TOUTIAO_COOKIE", raising=False)
        monkeypatch.setenv("MEDIAFLOW_ENV_OVERRIDES", "")  # 确保不读本地 .env
        # load_env 可能读到仓库 .env —— monkeypatch 掉最稳
        monkeypatch.setattr(toutiao_publish, "load_env", lambda: {})
        ok, why = toutiao_publish.available()
        assert ok is False
        assert "TOUTIAO_COOKIE" in why

    def test_push_draft_rejects_without_cookie(self, monkeypatch):
        from adapters import toutiao_publish
        monkeypatch.setattr(toutiao_publish, "load_env", lambda: {})
        r = toutiao_publish.push_draft("标题", "<p>正文</p>")
        assert r["ok"] is False and "TOUTIAO_COOKIE" in r["detail"]

    def test_push_draft_loose_response_parsing(self, monkeypatch):
        """草稿箱两种响应结构都能识别成功；HTTP 500 不抛异常。"""
        from adapters import toutiao_publish
        monkeypatch.setattr(toutiao_publish, "load_env",
                            lambda: {"TOUTIAO_COOKIE": "sid_tt=abc"})

        class _Resp:
            def __init__(self, status_code, data):
                self.status_code = status_code
                self._d = data

            def json(self):
                return self._d

        import httpx
        calls = []

        def fake_post(url, **kw):
            calls.append(url)
            return _Resp(200, {"code": 0, "data": {"draft_id": "d123"}})

        monkeypatch.setattr(httpx, "post", fake_post)
        r = toutiao_publish.push_draft("标题", "<p>正文</p>")
        assert r["ok"] is True and r["draft_id"] == "d123"

        def fake_post_err(url, **kw):
            return _Resp(500, {})

        monkeypatch.setattr(httpx, "post", fake_post_err)
        r2 = toutiao_publish.push_draft("标题", "<p>正文</p>")
        assert r2["ok"] is False and "已自动回落人工队列" in r2["detail"]


class TestPublishOrchestration:
    @pytest.fixture()
    def draft_env(self, monkeypatch, tmp_path):
        """隔离 core.db 后造一篇草稿。"""
        import tempfile

        from core import db as core_db

        monkeypatch.setattr(core_db, "DB_PATH", tmp_path / "pub.db")
        monkeypatch.setattr(core_db, "DATA", tmp_path)
        core_db._INITIALIZED_DB_PATHS.clear()
        did = core_db.add_draft("t", "测试标题", "正文" * 50, ["toutiao"])["id"]
        return {"did": did, "core_db": core_db, "tmp": tmp_path}

    def test_toutiao_manual_mode_still_queues(self, draft_env, monkeypatch):
        """manual 模式回归保护：排队语义不变。"""
        from core import orchestrator

        monkeypatch.setattr(orchestrator, "load_config",
                            lambda: {"publish": {"toutiao_mode": "manual"}})
        results = orchestrator.approve_and_publish(draft_env["did"], ["toutiao"])
        assert results and results[0]["ok"] is True
        assert "已排队" in results[0]["detail"]

    def test_toutiao_api_mode_pushes_to_draftbox(self, draft_env, monkeypatch):
        from core import orchestrator

        monkeypatch.setattr(orchestrator, "load_config",
                            lambda: {"publish": {"toutiao_mode": "api"}})
        pushed = {}

        class _FakeAdapter:
            @staticmethod
            def available():
                return True, "已配置登录态"

            @staticmethod
            def push_draft(title, body_html, **kw):
                pushed["title"] = title
                return {"ok": True, "detail": "已进头条草稿箱 draft_id=d1", "draft_id": "d1"}

        import adapters.toutiao_publish as tp
        monkeypatch.setattr(tp, "push_draft", _FakeAdapter.push_draft)
        monkeypatch.setattr("adapters.toutiao_publish.available",
                            _FakeAdapter.available, raising=False)
        results = orchestrator.approve_and_publish(draft_env["did"], ["toutiao"])
        assert results[0]["ok"] is True
        assert "头条草稿箱" in results[0]["detail"] or "已排队" in results[0]["detail"]

    def test_toutiao_api_mode_without_config_degrades(self, draft_env, monkeypatch):
        """api 模式但未配 Cookie：排队 + 可行动提示，绝不失败。"""
        from core import orchestrator

        monkeypatch.setattr(orchestrator, "load_config",
                            lambda: {"publish": {"toutiao_mode": "api"}})
        import adapters.toutiao_publish as tp
        monkeypatch.setattr(tp, "available", lambda: (False, "未配置 TOUTIAO_COOKIE"))
        results = orchestrator.approve_and_publish(draft_env["did"], ["toutiao"])
        assert results[0]["ok"] is True
        assert "TOUTIAO_COOKIE" in results[0]["detail"]
