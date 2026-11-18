# SPDX-License-Identifier: BUSL-1.1
"""V15.9.5 · 「所有模型服务都必须能删」回归锁。

客户缺陷：设置 → 模型服务里删掉了 7 家，剩下 OpenAI / Claude / Gemini / 智谱 GLM /
Kimi / Ollama / 百川 **怎么点删除都没反应**，卡片一直挂在列表里。

根因两条，都在 ``core/provider_registry.py``：

1. ``delete_provider()`` 第一行是 ``if pid not in pool: return False``。
   内置预设只有在用户**保存过**之后才进 ``gateway.providers`` 池；没保存过的
   （正是上面那 7 家）不在池里，于是删除被当成「不存在」直接返回 False，
   既不拉黑也不清池，列表照旧显示。
2. ``normalize()`` 无条件写 ``active = provider_id or "deepseek"`` 并顺手把
   ``pool[active]`` 补成空条目。活动通道一被删，下一轮读取就把它原地复活，
   于是「删掉 DeepSeek → 刷新又出现一家空 DeepSeek」。

本文件把「任意一家都能删」「删完不复活」「删完不假报 deepseek」「还能再加回来」
四件事钉死。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: 出厂形态：只有官方通道自己，其余 13 家都是「没保存过的内置预设」。
SHIPPED_CONFIG = """gateway:
  provider_id: yimu_official
  providers:
    yimu_official:
      name: 一幕·YIMU 官方
      base_url: https://gateway.yimu.studio/v1
      model: yimu-chat
"""


@pytest.fixture()
def install(tmp_path, monkeypatch):
    """隔离安装目录 / 用户目录 / 环境变量，返回 (app, userdata)。"""
    app = tmp_path / "app"
    userdata = tmp_path / "userdata"
    (app / "data").mkdir(parents=True)
    userdata.mkdir()

    from core import llm, provider_registry as reg, user_paths

    monkeypatch.setattr(reg, "BASE", app)
    monkeypatch.setattr(llm, "BASE", app)
    monkeypatch.setattr(user_paths, "user_data_dir", lambda: userdata)
    monkeypatch.setattr(user_paths, "secrets_env_path", lambda: userdata / "secrets.env")
    for k in list(os.environ):
        if k.startswith("MEDIAFLOW_"):
            monkeypatch.delenv(k, raising=False)
    llm._CFG_CACHE.clear()
    (app / "config.yaml").write_text(SHIPPED_CONFIG, encoding="utf-8")
    yield app, userdata
    llm._CFG_CACHE.clear()


def _ids() -> set[str]:
    from core import llm
    return set(llm.get_all_configured_providers().keys())


# ---------------------------------------------------------------------------
# 1. 核心缺陷：没保存过的内置预设也必须能删
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pid", ["openai", "claude", "gemini", "glm", "kimi", "ollama", "baichuan"])
def test_builtin_preset_never_saved_can_be_deleted(install, pid):
    """这 7 家正是客户删不掉的那批：出厂配置里根本没有它们的条目。"""
    from core import llm
    assert pid in _ids(), "前置：未保存的内置预设默认出现在列表里"
    assert llm.delete_provider(pid) is True, f"[{pid}] 删除必须成功，不能因为不在池里就返回 False"
    assert pid not in _ids(), f"[{pid}] 删除后不许再出现在列表里"


def test_delete_every_provider_leaves_empty_list(install):
    """「所有的必须全部都能删除」：把 14 家依次删光，列表必须真的空。"""
    from core import llm
    all_pids = list(llm.MODEL_PROVIDERS.keys())
    assert len(all_pids) >= 10

    for pid in all_pids:
        llm.delete_provider(pid)

    assert _ids() == set(), "全部删完后列表必须为空"
    gw = llm.load_config().get("gateway", {})
    assert gw.get("provider_id") == "", "一家都不剩时不该还挂着活动通道"
    assert gw.get("base_url") == "", "一家都不剩时不该还派生出一家已删通道的地址"
    assert gw.get("model") == ""


# ---------------------------------------------------------------------------
# 2. 删完不复活
# ---------------------------------------------------------------------------

def test_deleted_active_provider_is_not_resurrected(install):
    """删掉活动通道后，反复读配置不许把它补回池里（旧实现会补一个空条目）。"""
    from core import llm, provider_registry as reg

    assert llm.delete_provider("yimu_official") is True
    for _ in range(3):
        llm._CFG_CACHE.clear()
        cfg = llm.load_config()
        pool = cfg.get("gateway", {}).get("providers") or {}
        assert "yimu_official" not in pool, "已删除的通道被 normalize 复活了"

    raw = reg.raw_config()
    assert "yimu_official" in set(raw["gateway"].get("deleted_providers") or [])


def test_deleted_provider_not_selectable_by_router(install):
    """已删通道即使还有残留 Key，也不能被模型名路由选中。"""
    from core import llm, provider_registry as reg

    reg.set_key("openai", "sk-stale-key", also_global=False)
    llm.delete_provider("openai")
    llm._CFG_CACHE.clear()

    base, key, model, pid = llm.resolve_llm_endpoint("gpt-4o")
    assert pid != "openai", "已删除的通道仍被路由命中"
    assert "api.openai.com" not in (base or "")


def test_deleted_provider_cannot_be_set_active(install):
    from core import llm, provider_registry as reg

    llm.delete_provider("deepseek")
    assert reg.set_active("deepseek") is False
    assert llm.load_config()["gateway"].get("provider_id") != "deepseek"


# ---------------------------------------------------------------------------
# 3. 删了还能加回来
# ---------------------------------------------------------------------------

def test_deleted_provider_can_be_added_back(install):
    from core import llm

    assert llm.delete_provider("openai") is True
    assert "openai" not in _ids()

    assert llm.save_provider_config(
        "openai", "https://api.openai.com/v1", "sk-new-key", "gpt-4o", is_set_active=True
    )
    llm._CFG_CACHE.clear()
    assert "openai" in _ids(), "重新保存后必须从删除黑名单里移出"
    assert llm.load_config()["gateway"]["provider_id"] == "openai"


# ---------------------------------------------------------------------------
# 4. 删光了要说人话，而不是拼一个空地址去请求
# ---------------------------------------------------------------------------

def test_chat_raises_clear_error_when_nothing_left(install):
    from core import llm

    for pid in list(llm.MODEL_PROVIDERS.keys()):
        llm.delete_provider(pid)
    llm._CFG_CACHE.clear()

    with pytest.raises(RuntimeError) as ei:
        llm.chat([{"role": "user", "content": "hi"}], model="", timeout_s=5)
    msg = str(ei.value)
    assert "尚未配置任何模型服务" in msg
    assert "当前通道「」" not in msg, "报警文案不许出现空通道名"


def test_available_false_when_nothing_left(install):
    from core import llm

    for pid in list(llm.MODEL_PROVIDERS.keys()):
        llm.delete_provider(pid)
    llm._CFG_CACHE.clear()
    assert llm.available() is False


# ---------------------------------------------------------------------------
# 5. 接口如实回报（旧实现一律说「已成功删除」）
# ---------------------------------------------------------------------------

def test_delete_endpoint_reports_honestly(install, monkeypatch):
    """旧实现无论删没删掉都回「已成功删除」，用户被这句假话骗了很久。"""
    import asyncio

    from web.routers import models as mr

    monkeypatch.setattr(mr._a, "guard_admin", lambda request: None)

    class _Req:
        def __init__(self, payload):
            self._payload = payload

        async def json(self):
            return self._payload

    first = asyncio.run(mr.model_delete_provider(_Req({"provider_id": "gemini"})))
    assert first["ok"] is True

    again = asyncio.run(mr.model_delete_provider(_Req({"provider_id": "gemini"})))
    assert again["ok"] is False, "重复删除必须如实回报 False，不能假报成功"
    assert "无需删除" in again["msg"]

    batch = asyncio.run(mr.model_delete_provider(_Req({"provider_ids": ["openai", "openai"]})))
    assert batch["ok"] is True and batch["count"] == 1
    assert batch["missed"] == ["openai"], "重复项要如实列进 missed，不能算进成功数"
