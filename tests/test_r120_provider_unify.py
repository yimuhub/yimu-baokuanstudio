# SPDX-License-Identifier: BUSL-1.1
"""R12 供应商三层能力统一回归：解析链能力匹配 / 保存激活分离。

背景（2026-11-08 供应商能力复查）：
- 三层定位：L3 用户 BYOK（免扣费）/ L2 运营层上游供应商（驱动全站 Agent）/ L1 网关转售。
- 矛盾 1：保存任意供应商即静默激活 → 新增第二家供应商时悄悄抢占主通道。
- 矛盾 2：用户 BYOK 无能力匹配，劫持运营为 Agent 显式路由的模型（跨供应商发模型名必 404）。

验收标准：
- U-1 保存默认不激活：新配置供应商不改变 gw.provider_id（首次配置兜底除外）。
- U-2 显式 is_set_active=True 才接管全局。
- U-3 BYOK：无显式模型 → 用户 Key + 用户默认模型。
- U-4 BYOK 能力内（预设池/自定义聚合）→ 用户 Key 服务显式模型。
- U-5 BYOK 能力外（如运营 agnes-* 网关模型）→ 回落平台通道，不被劫持。
"""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-r120")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")

from core import llm  # noqa: E402


@pytest.fixture()
def gw_isolated(tmp_path, monkeypatch):
    """隔离 config.yaml / .env。"""
    monkeypatch.setattr(llm, "BASE", tmp_path)
    (tmp_path / "config.yaml").write_text("gateway: {}\n", encoding="utf-8")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    # auth 库隔离(users 表由 core.db SCHEMA 建表)
    from core import db as core_db
    monkeypatch.setattr(core_db, "DB_PATH", tmp_path / "auth.db")
    monkeypatch.setattr(core_db, "DATA", tmp_path)
    core_db._INITIALIZED_DB_PATHS.clear()
    core_db.conn().close()
    # 隔离 config 缓存(如有)
    if hasattr(llm, "_CFG_CACHE"):
        monkeypatch.setattr(llm, "_CFG_CACHE", {})
    return tmp_path


class TestSaveActivateSeparation:
    def test_save_default_does_not_activate(self, gw_isolated):
        """U-1: 配置第二家供应商,主通道不被抢占。"""
        llm.save_provider_config("deepseek", "https://api.deepseek.com", "sk-first", "deepseek-chat",
                                 is_set_active=True)
        cfg = llm.load_config()
        assert cfg["gateway"]["provider_id"] == "deepseek"
        # 新增第二家:默认不激活
        llm.save_provider_config("openai", "https://api.openai.com/v1", "sk-second", "gpt-4o")
        cfg = llm.load_config()
        assert cfg["gateway"]["provider_id"] == "deepseek", "保存≠激活:主通道不得被静默抢占"
        # 但第二家的专属 Key 必须已入库(供交叉路由)
        assert os.environ.get("MEDIAFLOW_KEY_OPENAI") or "sk-second" in (gw_isolated / ".env").read_text(encoding="utf-8")

    def test_explicit_activate_takes_over(self, gw_isolated):
        """U-2: 显式 is_set_active=True 才接管。"""
        llm.save_provider_config("deepseek", "https://api.deepseek.com", "sk-a", "deepseek-chat",
                                 is_set_active=True)
        llm.save_provider_config("openai", "https://api.openai.com/v1", "sk-b", "gpt-4o",
                                 is_set_active=True)
        assert llm.load_config()["gateway"]["provider_id"] == "openai"

    def test_first_save_bootstraps_active(self, gw_isolated):
        """首次配置兜底:系统无活动供应商时,首个保存即生效。"""
        llm.save_provider_config("kimi", "https://api.moonshot.cn", "sk-k", "moonshot-v1")
        assert llm.load_config()["gateway"]["provider_id"] == "kimi"


class TestByokCapabilityMatch:
    def test_byok_serves_default_model(self, gw_isolated, monkeypatch):
        """U-3: 无显式模型 → 用户 Key + 用户默认模型。"""
        import core.auth as auth
        monkeypatch.setattr(auth, "DB_PATH", gw_isolated / "auth.db")
        monkeypatch.setattr(auth, "DATA", gw_isolated)
        uid = auth.register_user("byok1", "pw123456")["user"]["id"]
        auth.save_user_api_key(uid, provider="deepseek", api_key="sk-user-key",
                               model_id="deepseek-chat")
        base, key, model, pid = llm.resolve_llm_endpoint(user_id=uid)
        assert key == "sk-user-key" and pid == "deepseek"

    def test_byok_capability_inside_serves_explicit(self, gw_isolated, monkeypatch):
        """U-4: 显式模型在用户供应商预设池内 → 用户 Key 服务。"""
        import core.auth as auth
        monkeypatch.setattr(auth, "DB_PATH", gw_isolated / "auth.db")
        monkeypatch.setattr(auth, "DATA", gw_isolated)
        uid = auth.register_user("byok2", "pw123456")["user"]["id"]
        auth.save_user_api_key(uid, provider="deepseek", api_key="sk-user-key")
        base, key, model, pid = llm.resolve_llm_endpoint("deepseek-reasoner", user_id=uid)
        assert key == "sk-user-key" and model == "deepseek-reasoner"

    def test_byok_custom_passthrough(self, gw_isolated, monkeypatch):
        """U-4b: custom 聚合供应商透传任意模型(聚合网关假设)。"""
        import core.auth as auth
        monkeypatch.setattr(auth, "DB_PATH", gw_isolated / "auth.db")
        monkeypatch.setattr(auth, "DATA", gw_isolated)
        uid = auth.register_user("byok3", "pw123456")["user"]["id"]
        auth.save_user_api_key(uid, provider="custom", api_key="sk-agg",
                               base_url="https://agg.example.com/v1")
        base, key, model, pid = llm.resolve_llm_endpoint("any-model-x", user_id=uid)
        assert key == "sk-agg" and pid == "custom"

    def test_byok_outside_capability_falls_back(self, gw_isolated, monkeypatch):
        """U-5: 运营指定 agnes-* 网关模型,用户 BYOK deepseek 不得劫持。"""
        import core.auth as auth
        monkeypatch.setattr(auth, "DB_PATH", gw_isolated / "auth.db")
        monkeypatch.setattr(auth, "DATA", gw_isolated)
        uid = auth.register_user("byok4", "pw123456")["user"]["id"]
        auth.save_user_api_key(uid, provider="deepseek", api_key="sk-user-key",
                               model_id="deepseek-chat")
        # 运营层:活动供应商是自定义网关(能力含 agnes-image)
        llm.save_provider_config("apipool", "http://127.0.0.1:8787/v1", "sk-op",
                                 "agnes-image-2.5-flash", is_set_active=True)
        base, key, model, pid = llm.resolve_llm_endpoint("agnes-image-2.5-flash", user_id=uid)
        assert pid != "deepseek" and key != "sk-user-key", "BYOK 不得劫持运营显式路由的网关模型"
