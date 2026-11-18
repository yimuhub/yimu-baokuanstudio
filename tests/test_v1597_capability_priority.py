# SPDX-License-Identifier: BUSL-1.1
"""V15.9.7：能力线默认统一收口——「显式默认 > 通道内路由」四链同序回归锁。

钉死四类双源冲突，防止复发：
1. 生图/生视频四条消费链（workbench 单次指定 / image_cfg / ad_video / short_drama）
   排序一致：单次指定 > 阶段绑定 > 能力线显式默认 > 通道内路由 > 自动；
   移动端/旧弹窗残留的 agent_routing 不得压过 PC「设为生图默认」。
2. 单次显式指定永远是最高——调用方明确传的模型不被配置覆盖（ad_video 与
   short_drama 此前排序相反）。
3. 对话兜底：文字请求解析到图像/视频模型时，回退「文字能力线默认」而非预设。
4. 预设目录可见性：自动挑选落到「用户从未保存过清单」的预设模型时，
   resolve_capability_default 必须带 preset_only 标记（计费可见性）。
5. 幽灵供应商：全部通道删除后，/api/settings 网关表单写入必须被拒绝。
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


TEXT_A = [{"id": "text-a", "category": "text", "is_enabled": True}]
IMG_B = [{"id": "img-b", "category": "image", "is_enabled": True}]
VID_C = [{"id": "kling-v2", "category": "video", "is_enabled": True}]


def _seed(reg, llm, *, with_routing=False):
    cfg = reg.raw_config()
    gw = cfg.setdefault("gateway", {})
    gw.setdefault("providers", {})["provA"] = {
        "base_url": "https://a.example/v1", "model": "text-a",
        "configured_models": TEXT_A,
    }
    gw["providers"]["provB"] = {
        "base_url": "https://b.example/v1", "model": "img-b",
        "configured_models": IMG_B,
    }
    gw["providers"]["provC"] = {
        "base_url": "https://c.example/v1", "model": "vid-c",
        "configured_models": VID_C,
    }
    if with_routing:
        # 模拟移动端/旧弹窗写进通道池的遗留路由绑定
        gw["agent_routing"] = {"image": "img-stale", "video": "kling-stale"}
    assert reg.write_config(cfg)
    reg.set_key("provB", "sk-b")
    reg.set_key("provC", "sk-c")
    llm._CFG_CACHE.clear()


# ---------------------------------------------------------------------------
# 1. 能力线显式默认 > 通道内路由
# ---------------------------------------------------------------------------

def test_capability_explicit_beats_stale_routing_image(iso_app):
    """PC「设为生图默认」后，移动端/旧弹窗残留的 agent_routing.image 不得压过它。"""
    from core import imagegen, llm, provider_registry as reg

    _seed(reg, llm, with_routing=True)
    llm.set_provider_default("provB", "image")
    cfg = imagegen.image_cfg()
    assert cfg["model"] == "provB/img-b", \
        f"能力线显式默认被通道路由盖掉: {cfg['model']}（双源冲突复现）"


def test_routing_still_works_without_capability_default(iso_app):
    """没设能力线默认时，通道内路由仍然生效（兼容语义保留）。"""
    from core import imagegen, llm, provider_registry as reg

    _seed(reg, llm, with_routing=True)
    cfg = imagegen.image_cfg()
    assert cfg["model"] == "img-stale"


def test_image_stage_binding_beats_capability_default(iso_app):
    """Agent 配置页单阶段绑定（更具体）优先于能力线显式默认。"""
    from core import imagegen, llm, provider_registry as reg

    _seed(reg, llm)
    llm.set_provider_default("provB", "image")
    cfg = reg.raw_config()
    cfg.setdefault("agents", {})["image"] = {"model": "agent-img-x"}
    reg.write_config(cfg)
    llm._CFG_CACHE.clear()
    assert imagegen.image_cfg()["model"] == "agent-img-x"


# ---------------------------------------------------------------------------
# 2. 视频线四链同序：单次指定 > 阶段绑定 > 显式默认 > 通道路由
# ---------------------------------------------------------------------------

def test_video_explicit_beats_stale_routing(iso_app):
    from core import ad_video, llm, provider_registry as reg

    _seed(reg, llm, with_routing=True)
    llm.set_provider_default("provC", "video")
    info = ad_video.ad_video_model_info()
    assert info["ok"] and info["model"] == "kling-v2", \
        f"生视频默认被通道路由盖掉: {info}"


def test_short_drama_override_beats_routing(iso_app):
    """调用方单次指定的模型优先于通道内路由（与 ad_video 链排序一致）。"""
    from core import llm, provider_registry as reg, short_drama

    _seed(reg, llm, with_routing=True)
    # 短剧链：入参 preferred_model 必须压过 routing 里的 vid-stale
    import inspect
    src = inspect.getsource(short_drama.generate_ai_video_clip)
    assert "preferred_model" in src
    # 解析顺序断言（源码级锁：override 在 cap_explicit/routing 之前参与 or 链首位）
    seg = src.split("active_preferred = ", 1)[1].split("if not active_preferred", 1)[0]
    assert seg.index("(preferred_model") < seg.index("cap_explicit"), \
        "单次指定必须排在能力线默认之前"
    assert seg.index("cap_explicit") < seg.index("routed_video_m"), \
        "能力线默认必须排在通道路由之前"


def test_ad_video_override_beats_routing(iso_app):
    from core import ad_video, llm, provider_registry as reg

    _seed(reg, llm, with_routing=True)
    llm.set_provider_default("provC", "video")
    info = ad_video.ad_video_model_info("provC/kling-v2-pro")
    assert info["ok"] and info["model"] == "kling-v2-pro", \
        f"单次指定被默认配置覆盖: {info}"


# ---------------------------------------------------------------------------
# 3. 对话兜底回退到文字能力线，而非预设 default
# ---------------------------------------------------------------------------

def test_chat_text_guard_prefers_capability_default(iso_app, monkeypatch):
    """文字请求解析到图像模型时，回退目标必须是文字能力线解析结果。"""
    from core import llm, provider_registry as reg

    _seed(reg, llm)
    llm.set_provider_default("provB", "image")
    # 构造：文字能力线 = provA/text-a；给 chat 传一个图像模型名
    # —— 防串台护栏必须回退到 text-a（或能力线结果），而不是 provB 预设
    cap_text = llm.resolve_capability_default("text")
    assert cap_text.get("model") in ("text-a",), f"文字能力线解析异常: {cap_text}"
    # 源码级锁：兜底块必须调用 resolve_capability_default("text")
    repo_llm = __import__("pathlib").Path(__file__).resolve().parent.parent / "core" / "llm.py"
    text = repo_llm.read_text(encoding="utf-8")
    seg = text.split('if classify_model(target_model) in ("image", "video"):', 1)[1].split("\n\n", 1)[0]
    assert 'resolve_capability_default("text")' in seg, "对话兜底必须先问文字能力线"


# ---------------------------------------------------------------------------
# 4. 预设目录可见性（preset_only）
# ---------------------------------------------------------------------------

def test_capability_auto_marks_preset_only(iso_app):
    """自动挑选落到「从未保存过清单」的预设模型时，必须带 preset_only=True。"""
    from core import llm, provider_registry as reg

    _seed(reg, llm)
    # provB/provC 清单是用户保存的 → 走到它们时 preset_only=False
    cap = llm.resolve_capability_default("image")
    assert cap.get("preset_only") is False, f"已保存清单被误标为预设: {cap}"
    # 只留预设通道（openai 有预设含图像模型）且给它 Key → auto 落预设 → True
    cfg = reg.raw_config()
    cfg["gateway"]["providers"] = {"provA": cfg["gateway"]["providers"]["provA"]}
    cfg["gateway"]["capability_defaults"] = {}
    reg.write_config(cfg)
    reg.set_key("openai", "sk-oai")
    llm._CFG_CACHE.clear()
    cap2 = llm.resolve_capability_default("image")
    assert cap2.get("preset_only") is True, f"预设目录模型必须标注 preset_only: {cap2}"
    assert cap2.get("provider_id") == "openai"


# ---------------------------------------------------------------------------
# 5. 幽灵供应商防护
# ---------------------------------------------------------------------------

def test_settings_gateway_write_rejected_when_no_providers(iso_app):
    """全部通道删除后（active 为空），网关表单写入必须明确拒绝而非落空键。"""
    import asyncio
    from core import llm, provider_registry as reg
    from web import admin as _a
    from web.routers import workspace as ws

    _seed(reg, llm)
    # 删光所有通道 → active 变空
    for pid in ("provA", "provB", "provC"):
        reg.delete_provider(pid)
    llm._CFG_CACHE.clear()
    assert _reg_active(reg) == ""

    class _Req:
        async def json(self):
            return {"gateway": {"base_url": "https://x.example/v1", "model": "m-1"}}

    async def _call():
        return await ws.settings(_Req())

    orig = _a.guard_admin
    _a.guard_admin = lambda request: {"id": "u-admin", "role": "admin"}
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(Exception) as ei:
            loop.run_until_complete(_call())
        assert "模型服务" in str(ei.value), f"必须给出「先添加模型服务」提示: {ei.value}"
    finally:
        loop.close()
        _a.guard_admin = orig
    # 池里不得出现空键幽灵条目
    cfg = reg.raw_config()
    assert "" not in (cfg.get("gateway", {}).get("providers") or {}), "幽灵供应商落池"


def _reg_active(reg) -> str:
    return str(reg.raw_config().get("gateway", {}).get("provider_id") or "").strip()


# ---------------------------------------------------------------------------
# 6. 文字线兜底不再硬编码出厂预设
# ---------------------------------------------------------------------------

def test_model_for_falls_to_capability_line(iso_app):
    from core import agents, llm, provider_registry as reg

    _seed(reg, llm)
    cfg = reg.raw_config()
    cfg["gateway"]["providers"]["provA"]["model"] = ""
    cfg["gateway"]["model"] = ""
    reg.write_config(cfg)
    llm._CFG_CACHE.clear()
    m = agents.model_for("write")
    assert m in ("text-a", "provA/text-a"), f"文字线兜底异常: {m}"
    repo = __import__("pathlib").Path(__file__).resolve().parent.parent / "core" / "agents.py"
    assert 'return "deepseek-chat"' not in repo.read_text(encoding="utf-8"), \
        "不得再硬编码出厂预设模型"
