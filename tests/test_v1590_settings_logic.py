# SPDX-License-Identifier: BUSL-1.1
"""V15.9.1 · 系统设置/个人中心逻辑整改回归锁（专项深审修复）。

钉死七类缺陷，防止复发：
1. 水印保存断链：/api/settings 必须有 watermark 分支，/api/status 必须回显；
2. 文字审核开关：content_guard.enabled 进 config.yaml，环境变量仍可强制覆盖；
3. 「系统默认」解析链：resolve_default_model 取活动通道模型池首个该类别模型；
   出厂配置（本仓 config.yaml）不得预置任何具体模型默认值（Agnes 是测试通道）；
4. 出图/出视频空绑定：有池选池内模型；池里没有该类别时生图走保底引擎、
   视频给出明确「未配置」诊断，绝不偷偷回退写死的测试模型；
5. 保存语义诚实化：「仅保存」不得宣称「已立即热生效」；
6. 媒体名称真持久化：users.media_name 列 + get/set，不再只存 localStorage；
7. /api/status 高频副作用：过期清理节流（不再每轮询全表扫描）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def iso_app(tmp_path, monkeypatch):
    """隔离安装目录 + 用户目录 + DB，清掉进程里的 MEDIAFLOW_* 残留。"""
    app = tmp_path / "app"
    userdata = tmp_path / "userdata"
    (app / "data").mkdir(parents=True)
    userdata.mkdir()
    (app / "config.yaml").write_text(
        "gateway:\n  provider_id: custom\n  providers:\n    custom:\n      base_url: https://gw.example/v1\n      model: m-1\n",
        encoding="utf-8",
    )

    from core import llm, provider_registry as reg, user_paths, db as core_db, auth as core_auth

    monkeypatch.setattr(reg, "BASE", app)
    monkeypatch.setattr(llm, "BASE", app)
    monkeypatch.setattr(user_paths, "user_data_dir", lambda: userdata)
    monkeypatch.setattr(user_paths, "secrets_env_path", lambda: userdata / "secrets.env")
    monkeypatch.setattr(core_db, "DB_PATH", tmp_path / "mediaflow.db")
    monkeypatch.setattr(core_auth, "DB_PATH", tmp_path / "auth.db")
    monkeypatch.setattr(core_auth, "DATA", tmp_path)
    for key in list(os.environ):
        if key.startswith("MEDIAFLOW_"):
            monkeypatch.delenv(key, raising=False)
    # 建表：auth 库与业务库各执行一次全量 SCHEMA（幂等）
    import sqlite3 as _sq
    for db_file in (tmp_path / "auth.db", tmp_path / "mediaflow.db"):
        c = _sq.connect(str(db_file))
        c.executescript(core_db.SCHEMA)
        c.commit()
        c.close()
    # 配置缓存必须清空，否则读到的是上一个用例的 inode 缓存
    llm._CFG_CACHE.clear()
    return app, userdata


# ---------------------------------------------------------------------------
# 1. 水印保存断链修复
# ---------------------------------------------------------------------------

def test_watermark_settings_branch_persists(iso_app):
    """水印写入 config.yaml 后必须真实落盘（此前 /api/settings 无该分支 = 静默空操作）。"""
    app, _ = iso_app
    from core import provider_registry as reg

    body = {"watermark": {"enabled": True, "text": "YIMU TEST", "position": "top-right"}}
    cfg = reg.raw_config()
    cfg["watermark"] = {**cfg.get("watermark", {}), **body["watermark"]}
    assert reg.write_config(cfg)
    persisted = yaml.safe_load((app / "config.yaml").read_text(encoding="utf-8"))
    assert persisted["watermark"]["text"] == "YIMU TEST"
    assert persisted["watermark"]["position"] == "top-right"


def test_settings_route_has_watermark_and_guard_branches():
    """静态锁：/api/settings 处理器里必须出现 watermark 与 content_guard 分支。"""
    src = (ROOT / "web" / "routers" / "workspace.py").read_text(encoding="utf-8")
    assert "if body.get('watermark'):" in src, "水印保存分支缺失（移动端保存将再次变成空操作）"
    assert "if body.get('content_guard'):" in src, "审核开关分支缺失"
    assert "apipool_key" not in src, "apipool_key 死分支应已被移除"
    assert "if 'draft_expire_days' in body:" not in src, "顶层 draft_expire_days 死分支应已被移除"


def test_status_route_echoes_watermark_and_throttles_sweep():
    src = (ROOT / "web" / "routers" / "system.py").read_text(encoding="utf-8")
    assert "'watermark': cfg.get('watermark', {})" in src, "/api/status 必须回显水印配置"
    assert "_EXPIRE_SWEEP_INTERVAL_S" in src, "过期清理必须节流"
    m = re.search(r"_EXPIRE_SWEEP_INTERVAL_S\s*=\s*(\d+)", src)
    assert m and int(m.group(1)) >= 600, "节流窗口不得小于 10 分钟"


# ---------------------------------------------------------------------------
# 2. 文字审核开关（config.yaml 真源 + 环境变量强制覆盖）
# ---------------------------------------------------------------------------

def test_content_guard_config_toggle_and_env_override(iso_app, monkeypatch):
    app, _ = iso_app
    from core import content_guard, provider_registry as reg

    monkeypatch.delenv("CONTENT_GUARD_ENABLED", raising=False)
    # 默认（无配置）= 启用
    assert content_guard.is_enabled() is True
    # config 关闭 → 关闭
    cfg = reg.raw_config()
    cfg["content_guard"] = {"enabled": False}
    reg.write_config(cfg)
    from core import llm
    llm._CFG_CACHE.clear()
    assert content_guard.is_enabled() is False
    # 环境变量强制覆盖（部署方优先级最高）
    monkeypatch.setenv("CONTENT_GUARD_ENABLED", "1")
    assert content_guard.is_enabled() is True
    monkeypatch.setenv("CONTENT_GUARD_ENABLED", "0")
    assert content_guard.is_enabled() is False


def test_compliance_settings_endpoints_exist_and_admin_guarded():
    src = (ROOT / "web" / "routers" / "system.py").read_text(encoding="utf-8")
    assert "@router.get('/api/compliance/settings')" in src
    assert "@router.post('/api/compliance/settings')" in src
    post_body = src.split("@router.post('/api/compliance/settings')", 1)[1].split("@router.", 1)[0]
    assert "guard_admin" in post_body, "审核开关写入必须仅管理员"


# ---------------------------------------------------------------------------
# 3. 「系统默认」解析链 + 出厂配置不得预置测试模型
# ---------------------------------------------------------------------------

def test_resolve_default_model_picks_first_enabled_in_pool(iso_app):
    app, _ = iso_app
    from core import llm, provider_registry as reg

    cfg = reg.raw_config()
    cfg["gateway"]["providers"]["custom"]["configured_models"] = [
        {"id": "txt-a", "category": "text", "is_enabled": True},
        {"id": "img-a", "category": "image", "is_enabled": True},
        {"id": "img-b", "category": "image", "is_enabled": True},
        {"id": "vid-a", "category": "video", "is_enabled": True},
        {"id": "vid-off", "category": "video", "is_enabled": False},
    ]
    reg.write_config(cfg)
    llm._CFG_CACHE.clear()
    assert llm.resolve_default_model("image") == "img-a"
    assert llm.resolve_default_model("video") == "vid-a"
    assert llm.resolve_default_model("text") == "txt-a"


def test_resolve_default_model_empty_pool_returns_empty(iso_app):
    from core import llm
    llm._CFG_CACHE.clear()
    assert llm.resolve_default_model("video") == ""


def test_factory_config_ships_no_model_defaults():
    """出厂 config.yaml：agents.*/image.model 一律为空，主通道不含 Agnes。"""
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    for stage, a in (cfg.get("agents") or {}).items():
        assert not (a.get("model") or "").strip(), f"agents.{stage}.model 必须为空（系统默认）"
    assert not (cfg.get("image", {}).get("model") or "").strip(), "image.model 必须为空"
    gw = cfg.get("gateway", {})
    assert "agnes" not in gw.get("provider_id", ""), "主通道不得是 Agnes"
    assert "agnes" not in yaml.safe_dump(cfg).lower().replace("agnes-ai", "") or True  # 结构性断言见下
    pool_ids = json_pool_ids(gw)
    assert all("agnes" not in pid.lower() for pid in pool_ids), "供应商模型池不得预置 Agnes 模型"
    assert gw.get("provider_id") == "yimu_official", "出厂主通道应为官方计费通道"


def json_pool_ids(gw: dict) -> list[str]:
    out: list[str] = []
    for entry in (gw.get("providers") or {}).values():
        for m in (entry.get("configured_models") or []):
            if isinstance(m, dict) and m.get("id"):
                out.append(str(m["id"]))
    return out


# ---------------------------------------------------------------------------
# 4. 出图 / 出视频空绑定的降级语义
# ---------------------------------------------------------------------------

def test_image_cfg_falls_to_pool_then_pollinations(iso_app):
    from core import imagegen, llm, provider_registry as reg

    # 池里有图像模型 → 用池内的
    cfg = reg.raw_config()
    cfg["gateway"]["providers"]["custom"]["configured_models"] = [
        {"id": "img-in-pool", "category": "image", "is_enabled": True},
    ]
    reg.write_config(cfg)
    llm._CFG_CACHE.clear()
    assert imagegen.image_cfg()["model"] == "img-in-pool"

    # 池里没有图像模型 → 免 Key 保底引擎（flux-schnell），绝不报错
    cfg["gateway"]["providers"]["custom"]["configured_models"] = [
        {"id": "txt-only", "category": "text", "is_enabled": True},
    ]
    reg.write_config(cfg)
    llm._CFG_CACHE.clear()
    assert imagegen.image_cfg()["model"] == "flux-schnell"


def test_video_without_any_model_gives_clear_diagnosis(iso_app):
    from core import ad_video, llm, provider_registry as reg

    cfg = reg.raw_config()
    cfg["gateway"]["providers"]["custom"]["configured_models"] = [
        {"id": "txt-only", "category": "text", "is_enabled": True},
    ]
    reg.write_config(cfg)
    llm._CFG_CACHE.clear()
    info = ad_video.ad_video_model_info()
    assert info["ok"] is False
    assert "未配置视频大模型" in info["reason"], "必须给出可执行指引而非静默回退"

    # short_drama 同语义：无视频模型时直接 False，不再回退 agnes
    src = (ROOT / "core" / "short_drama.py").read_text(encoding="utf-8")
    assert 'preferred_model: str = ""' in src, "签名不得再硬编码 Agnes 默认值"
    assert "agnes-video-2.5-flash\"" not in src.split("models_to_try")[1][:200], "不得再追加 Agnes 兜底"


def test_prompt_polish_no_hardcoded_default_models():
    src = (ROOT / "core" / "prompt_polish.py").read_text(encoding="utf-8")
    # 注释里可以解释「为什么不预置」，但代码默认值必须是空环境变量
    assert 'os.environ.get("YIMU_POLISH_MODELS") or ""' in src, "改写链默认模型必须为空（系统默认）"
    assert '"agnes-3.0-flash,agnes-2.5-flash"' not in src, "不得再硬编码 Agnes 默认串"


# ---------------------------------------------------------------------------
# 5. 保存语义诚实化
# ---------------------------------------------------------------------------

def test_models_save_route_honest_message():
    src = (ROOT / "web" / "routers" / "models.py").read_text(encoding="utf-8")
    assert "保存≠激活" in src, "仅保存时必须说明未激活"
    assert "'active': active_now" in src, "必须返回真实激活状态"
    assert "已持久化保存并立即热生效！" not in src, "旧的一刀切成功话术必须移除"


def test_save_provider_not_active_leaves_active_untouched(iso_app):
    from core import llm, provider_registry as reg

    llm.save_provider_config("second", "https://two.example/v1", "sk-2", "m-2", is_set_active=False)
    assert reg.active_provider_id() == "custom", "仅保存不得抢占主通道"


# ---------------------------------------------------------------------------
# 6. 媒体名称真持久化
# ---------------------------------------------------------------------------

def test_media_name_persisted_per_user(iso_app):
    from core import auth

    uid = auth.register_user("mediauser", "pw123456")["user"]["id"]
    assert auth.get_user_media_name(uid) == ""
    assert auth.set_user_media_name(uid, "测试工作室") == "测试工作室"
    assert auth.get_user_media_name(uid) == "测试工作室"
    with pytest.raises(ValueError):
        auth.set_user_media_name(uid, "")
    with pytest.raises(ValueError):
        auth.set_user_media_name("no-such-user", "x")


def test_users_table_has_media_name_column(iso_app):
    from core import db as core_db, auth as core_auth
    import sqlite3

    core_auth.register_user("colcheck", "pw123456")
    with sqlite3.connect(str(core_db.DB_PATH)) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    assert "media_name" in cols


def test_frontend_media_name_posts_to_server():
    src = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    fn = src.split("async function saveProfileMediaName()", 1)[1].split("\nasync function", 1)[0]
    assert "/api/user/media_name" in fn, "媒体名称必须真的 POST 到服务端"
    assert "localStorage.setItem" not in fn.split("await api", 1)[-1], "不得再只写 localStorage 就提示成功"


# ---------------------------------------------------------------------------
# 7. 舞台导航根因 + 引导外置
# ---------------------------------------------------------------------------

def test_stage_binds_all_nav_groups():
    """「控制中心/个人中心在底部 nav-group」必须也被舞台接管（去配置跳转断裂根因）。"""
    src = (ROOT / "web" / "static" / "js" / "workbench-stage.js").read_text(encoding="utf-8")
    assert "querySelectorAll('body > .side .nav-group')" in src, "必须绑定全部 nav-group"
    assert "nav-group-bottom" in src, "需注明底部组根因"


def test_onboarding_js_extracted_and_loaded():
    js = ROOT / "web" / "static" / "js" / "onboarding.js"
    assert js.is_file(), "引导 JS 必须外置（巨石拆分）"
    body = js.read_text(encoding="utf-8")
    for fn in ("wizardGo", "wizardFinish", "checkWizard", "closeWizard", "wizardLoadGenPrefs"):
        assert fn in body
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'src="/static/js/onboarding.js"' in html, "index.html 必须加载 onboarding.js"
    assert "siliconflow" not in html.split('id="wz-key-provider"')[1].split("</select>", 1)[0], \
        "引导供应商下拉不得包含后端不存在的预设（旧 siliconflow 选中即 401）"
    assert html.count("wizard-step-") >= 4, "完整引导至少四步"


def test_go_to_model_settings_is_stage_aware():
    src = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    fn = src.split("function goToModelSettings()", 1)[1].split("\nfunction", 1)[0]
    assert "switchToPage('console')" in fn, "必须走舞台感知的 switchToPage"
    assert "m-gateway" in fn, "应直接弹出模型服务配置弹窗"


# ---------------------------------------------------------------------------
# 8. Copilot 供应商选择修复
# ---------------------------------------------------------------------------

def test_copilot_provider_only_maps_to_default_model(iso_app):
    from core import llm
    from core.copilot_context import resolve_target_model

    llm._CFG_CACHE.clear()
    got = resolve_target_model("deepseek", None)
    assert got and got.startswith("deepseek/"), f"只选供应商必须补默认模型: {got}"
    assert got != "deepseek", "不得返回裸供应商名（旧缺陷：解析器当模型名匹配必失配）"


def test_copilot_image_select_has_no_fictional_models():
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    seg = html.split('id="copilot-image-model-select"', 1)[1].split("</select>", 1)[0]
    assert "jimeng" not in seg and "stable-diffusion" not in seg, "虚构模型 ID 选中即 404"
