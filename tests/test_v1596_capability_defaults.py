# SPDX-License-Identifier: BUSL-1.1
"""V15.9.6：文字 / 生图 / 生视频三条能力线可以各用一家通道。

客户场景：主通道是一家只有文本模型的中转（A），另存了一家有生图/生视频
模型的通道（B）。旧实现只有一个「设为主网关」，且「系统默认」只在活动
通道的模型池里找，于是 B 家的生图/生视频模型**永远选不到**。
"""
from __future__ import annotations

import os
import shutil

import pytest
import yaml


@pytest.fixture()
def iso_app(tmp_path, monkeypatch):
    app = tmp_path / "app"
    userdata = tmp_path / "userdata"
    (app / "data").mkdir(parents=True)
    userdata.mkdir()
    (app / "config.yaml").write_text(
        "gateway:\n  provider_id: provA\n  providers:\n    provA:\n"
        "      base_url: https://a.example/v1\n      model: text-a\n",
        encoding="utf-8",
    )

    from core import llm, provider_registry as reg, user_paths

    monkeypatch.setattr(reg, "BASE", app)
    monkeypatch.setattr(llm, "BASE", app)
    monkeypatch.setattr(user_paths, "user_data_dir", lambda: userdata)
    monkeypatch.setattr(user_paths, "secrets_env_path", lambda: userdata / "secrets.env")
    for key in list(os.environ):
        if key.startswith("MEDIAFLOW_"):
            monkeypatch.delenv(key, raising=False)
    llm._CFG_CACHE.clear()
    yield app, userdata
    shutil.rmtree(tmp_path, ignore_errors=True)


def _seed(reg, llm, *, a_models, b_models, c_models=None):
    cfg = reg.raw_config()
    gw = cfg.setdefault("gateway", {})
    gw.setdefault("providers", {})["provA"] = {
        "base_url": "https://a.example/v1",
        "model": (a_models[0]["id"] if a_models else "text-a"),
        "configured_models": a_models,
    }
    gw["providers"]["provB"] = {
        "base_url": "https://b.example/v1",
        "model": (b_models[0]["id"] if b_models else ""),
        "configured_models": b_models,
    }
    if c_models is not None:
        gw["providers"]["provC"] = {
            "base_url": "https://c.example/v1",
            "model": (c_models[0]["id"] if c_models else ""),
            "configured_models": c_models,
        }
    assert reg.write_config(cfg)
    reg.set_key("provB", "sk-prov-b")
    if c_models is not None:
        reg.set_key("provC", "sk-prov-c")
    llm._CFG_CACHE.clear()


TEXT_A = [{"id": "text-a", "category": "text", "is_enabled": True}]
IMG_B = [{"id": "img-b", "category": "image", "is_enabled": True}]
VID_C = [{"id": "kling-v2", "category": "video", "is_enabled": True}]


def test_auto_image_default_crosses_provider(iso_app):
    """A 只有文本模型时，生图默认必须落到 B 家，而不是回落到「没有」。"""
    from core import llm, provider_registry as reg

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B)
    spec = llm.resolve_capability_default("image")
    assert spec["provider_id"] == "provB"
    assert spec["model"] == "img-b"
    assert spec["source"] == "auto"
    assert llm.resolve_default_model("image") == "provB/img-b"

    base, key, model, pid = llm.resolve_llm_endpoint("provB/img-b")
    assert (base, key, model, pid) == ("https://b.example/v1", "sk-prov-b", "img-b", "provB")


def test_auto_video_default_crosses_provider(iso_app):
    from core import llm, provider_registry as reg

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B, c_models=VID_C)
    spec = llm.resolve_capability_default("video")
    assert (spec["provider_id"], spec["model"]) == ("provC", "kling-v2")
    assert llm.resolve_default_model("video") == "provC/kling-v2"


def test_explicit_image_default_wins_over_active_pool(iso_app):
    """活动通道自己也有生图模型时，用户显式指定的别家仍然优先。"""
    from core import llm, provider_registry as reg

    _seed(reg, llm,
          a_models=TEXT_A + [{"id": "img-a", "category": "image", "is_enabled": True}],
          b_models=IMG_B)
    assert llm.resolve_capability_default("image")["model"] == "img-a"

    assert reg.set_capability_default("image", "provB", "img-b")
    llm._CFG_CACHE.clear()
    spec = llm.resolve_capability_default("image")
    assert (spec["provider_id"], spec["model"], spec["source"]) == ("provB", "img-b", "explicit")
    assert llm.resolve_default_model("image") == "provB/img-b"


def test_set_provider_default_all_sets_each_capability(iso_app):
    """「全功能默认」逐条能力线设置，缺哪条就如实说缺哪条。"""
    from core import llm, provider_registry as reg

    _seed(reg, llm,
          a_models=TEXT_A,
          b_models=[{"id": "text-b", "category": "text", "is_enabled": True}] + IMG_B,
          c_models=VID_C)

    res = llm.set_provider_default("provB", scope="all")
    assert res["ok"] is True
    assert {a["category"] for a in res["applied"]} == {"text", "image"}
    assert res["missing"] == ["video"]
    assert "生视频" in res["msg"] and "没有" in res["msg"]

    llm._CFG_CACHE.clear()
    cfg = llm.load_config()
    assert cfg["gateway"]["provider_id"] == "provB"
    assert llm.resolve_default_model("image") == "img-b"
    # 视频默认没被 B 抢走，自动落到 C
    assert llm.resolve_default_model("video") == "provC/kling-v2"


def test_set_provider_default_image_only(iso_app):
    from core import llm, provider_registry as reg

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B)
    res = llm.set_provider_default("provB", scope="image")
    assert res["ok"] and res["applied"] == [{"category": "image", "model": "img-b"}]
    llm._CFG_CACHE.clear()
    # 文字主通道保持不变
    assert llm.load_config()["gateway"]["provider_id"] == "provA"


def test_clear_default_returns_to_auto(iso_app):
    from core import llm, provider_registry as reg

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B)
    assert reg.set_capability_default("image", "provB", "img-b")
    llm._CFG_CACHE.clear()
    assert llm.resolve_capability_default("image")["source"] == "explicit"

    assert reg.clear_capability_default("image")
    llm._CFG_CACHE.clear()
    assert llm.resolve_capability_default("image")["source"] == "auto"


def test_deleting_provider_clears_capability_pointer(iso_app):
    from core import llm, provider_registry as reg

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B)
    assert reg.set_capability_default("image", "provB", "img-b")
    llm._CFG_CACHE.clear()
    assert reg.delete_provider("provB")
    llm._CFG_CACHE.clear()

    assert "image" not in reg.capability_defaults()
    assert llm.resolve_capability_default("image") == {}


def test_image_cfg_uses_cross_provider_default(iso_app):
    from core import imagegen, llm, provider_registry as reg

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B)
    assert imagegen.image_cfg()["model"] == "provB/img-b"

    assert reg.set_capability_default("image", "", "")
    llm._CFG_CACHE.clear()
    # 清空后仍能自动跨通道挑到 B
    assert imagegen.image_cfg()["model"] == "provB/img-b"


def test_video_model_info_uses_other_provider(iso_app):
    from core import ad_video, llm, provider_registry as reg

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B, c_models=VID_C)
    info = ad_video.ad_video_model_info()
    assert info["ok"] is True
    assert info["provider_id"] == "provC"
    assert info["model"] == "kling-v2"
    assert info["base"] == "https://c.example/v1"


def test_set_default_endpoint_accepts_and_clears(iso_app, monkeypatch):
    import asyncio

    from core import llm, provider_registry as reg
    from web.routers import models as mr

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B)
    monkeypatch.setattr(mr._a, "guard_admin", lambda request: None)

    class _Req:
        def __init__(self, payload):
            self._payload = payload

        async def json(self):
            return self._payload

    res = asyncio.run(mr.model_set_default_provider(
        _Req({"provider_id": "provB", "scope": "image"})))
    assert res["ok"] and res["applied"][0]["model"] == "img-b"

    cleared = asyncio.run(mr.model_set_default_provider(
        _Req({"provider_id": "", "scope": "image"})))
    assert cleared["ok"] and "自动" in cleared["msg"]
    llm._CFG_CACHE.clear()
    assert "image" not in reg.capability_defaults()


def test_providers_endpoint_exposes_capabilities(iso_app, monkeypatch):
    from core import llm, provider_registry as reg
    from web.routers import models as mr

    _seed(reg, llm, a_models=TEXT_A, b_models=IMG_B)
    monkeypatch.setattr(mr._a, "guard", lambda request: None)
    monkeypatch.setattr(mr._a, "get_current_user", lambda request: None)

    class _Req:
        pass

    res = mr.get_model_providers(_Req())
    assert res["resolved_capabilities"]["image"]["provider_id"] == "provB"
    assert res["resolved_capabilities"]["text"]["provider_id"] == "provA"
    assert res["providers"]["provB"]["default_scopes"] == ["image"]
    assert res["providers"]["provA"]["default_scopes"] == ["text"]


def test_factory_config_has_no_capability_defaults():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    gw = cfg.get("gateway") or {}
    # 出厂样本不带任何能力默认：首次启动走「自动」，不偏袒某一家
    assert not (gw.get("capability_defaults") or {})
