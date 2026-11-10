# SPDX-License-Identifier: BUSL-1.1
"""V15.8 · 客户缺陷排查报告（F1–F6 / R1–R10 / S1–S8）全栈回归锁。

覆盖六条链路，防止只修 Windows 客户端而其它端回归：
1. 三平台启动链路：正常显示窗口、UTF-8、启动垫片、单实例 / 端口探测；
2. 敏感配置：用户目录 secrets.env + 0600，安装目录不留明文；
3. 默认通道空 Key 引导与 `GET /api/drafts` 统一列表契约；
4. 正文配图命名契约：占位符落库、按序号回写、标题文本只作 alt；
5. 六平台预览：含 preview-xhs.html、缺图降级、白名单、懒生成、质量闸；
6. 分享链接：只给真实产物签发，但老草稿有源产物时能自愈小红书预览。
"""
from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def v158_db(tmp_path, monkeypatch):
    """把 core.db 指向临时隔离库与临时 data 目录（绝不碰生产库）。"""
    from core import db as core_db

    monkeypatch.setattr(core_db, "DB_PATH", tmp_path / "v158_mediaflow.db")
    monkeypatch.setattr(core_db, "DATA", tmp_path)
    monkeypatch.setattr(core_db, "DRAFTS", tmp_path / "drafts", raising=False)
    return core_db


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# 1. 启动链路：R1 / R2 / R8 +「出厂日志为空」
# ---------------------------------------------------------------------------

def test_v158_windows_vbs_shows_window_and_uses_launcher():
    """R1：`0 = SW_HIDE` 会把 pywebview 主窗体一起隐藏 → 双击无反应。"""
    vbs = _read("一幕桌面客户端.vbs")
    assert ", 1, False" in vbs, "必须用 SW_SHOWNORMAL 启动"
    assert ", 0, False" not in vbs, "SW_HIDE 是 F1 的直接根因"
    assert "launch_desktop.py" in vbs
    assert "PYTHONIOENCODING" in vbs and "PYTHONUTF8" in vbs
    assert (ROOT / "app" / "launch_desktop.py").is_file()


def test_v158_builders_emit_the_same_fixed_launcher():
    """三平台打包模板不能继续生成旧的隐藏窗口 VBS。"""
    full = _read("scripts/build_full_bundle.py")
    legacy = _read("scripts/build_desktop_client.py")
    for src in (full, legacy):
        assert ", 1, False" in src
        assert ", 0, False" not in src
        assert "launch_desktop.py" in src
        assert "PYTHONIOENCODING" in src
    for rel in ("scripts/build_macos_dmg.sh", "scripts/build_linux_deb.sh",
                "一幕桌面客户端.command", "一幕桌面客户端_linux.sh"):
        src = _read(rel)
        assert "launch_desktop.py" in src, f"{rel} 未走统一启动垫片"
        assert "PYTHONIOENCODING" in src and "PYTHONUTF8" in src


def test_v158_desktop_has_log_shim_single_instance_and_port_probe():
    """R2 / R8：无控制台时日志留痕、重复双击不启第二个实例、端口被占用自动避让。"""
    import desktop

    for name in ("_setup_streams", "_StreamTee", "acquire_single_instance",
                 "release_single_instance", "activate_existing_window",
                 "probe_service", "select_free_port", "start_desktop_app"):
        assert hasattr(desktop, name), f"desktop.py 缺少 {name}"
    assert "free" in desktop.probe_service.__doc__
    assert "yimu" in desktop.probe_service.__doc__
    assert "foreign" in desktop.probe_service.__doc__


# ---------------------------------------------------------------------------
# 2. 敏感配置：R9 / F5 / S7
# ---------------------------------------------------------------------------

def test_v158_sensitive_keys_are_classified():
    from core import user_paths

    for key in ("ADMIN_PASSWORD", "YIMU_SECRET_KEY", "GITHUB_IMGBED_TOKEN",
                "MEDIAFLOW_KEY_DEEPSEEK", "MEDIAFLOW_APIPOOL_KEY", "YIMU_OFFICIAL_TOKEN"):
        assert user_paths.is_sensitive(key)
    assert not user_paths.is_sensitive("PORT")
    assert not user_paths.is_sensitive("WECHAT_THEME")


def test_v158_merge_env_priority_and_migration(tmp_path, monkeypatch):
    """进程环境变量 > 用户 secrets.env > 安装目录 .env；旧明文自动迁出。"""
    from core import user_paths

    user_dir = tmp_path / "userdata"
    monkeypatch.setattr(user_paths, "user_data_dir", lambda: user_dir)
    install_env = tmp_path / "app" / ".env"
    install_env.parent.mkdir(parents=True)
    install_env.write_text(
        "PORT=8790\nADMIN_PASSWORD=weak-secret\nYIMU_SECRET_KEY=sk-legacy\n"
        "MEDIAFLOW_KEY_X=abc\n",
        encoding="utf-8",
    )

    moved = user_paths.migrate_legacy_secrets(install_env)
    assert moved == 3, "三个敏感项都要迁出安装目录"
    left = install_env.read_text(encoding="utf-8")
    assert "PORT=8790" in left
    assert "weak-secret" not in left and "sk-legacy" not in left and "MEDIAFLOW_KEY_X" not in left
    secrets_path = user_paths.secrets_env_path()
    assert secrets_path.is_file()
    assert stat.S_IMODE(secrets_path.stat().st_mode) == 0o600
    assert "weak-secret" in secrets_path.read_text(encoding="utf-8")

    merged = user_paths.merge_env(install_env, environ={"PORT": "9999"})
    assert merged["PORT"] == "9999", "进程环境变量优先级最高"
    assert merged["ADMIN_PASSWORD"] == "weak-secret", "用户 secrets.env 仍可读取"


def test_v158_load_env_uses_user_secrets(tmp_path, monkeypatch):
    """全站配置读取真源必须委托新的合并逻辑，而不是只读安装目录 .env。"""
    from core import llm, user_paths

    monkeypatch.setattr(user_paths, "user_data_dir", lambda: tmp_path / "ud")
    monkeypatch.setenv("YIMU_V158_PROBE", "from-process")
    env = llm.load_env()
    assert env.get("YIMU_V158_PROBE") == "from-process"
    assert isinstance(env, dict)


# ---------------------------------------------------------------------------
# 3. 默认通道 + 草稿列表：R10 / F6 / 报告 6.3 / S8
# ---------------------------------------------------------------------------

def test_v158_status_exposes_empty_key_hint():
    src = _read("web/routers/system.py")
    assert "active_key_set" in src and "key_hint" in src
    assert "设置 → 模型服务" in src
    assert "官方试用凭证" in src
    llm_src = _read("core/llm.py")
    assert "secrets.env" in llm_src
    assert "尚未配置密钥" in llm_src


def test_v158_drafts_list_route_is_registered_and_documented():
    """F6：GET /api/drafts 过去 404；现在路由、契约文档两处都要在。"""
    from web import admin  # noqa: F401  先加载主应用，避免 drafts 路由模块循环导入
    from web.routers import drafts

    hit = [r for r in drafts.router.routes
           if getattr(r, "path", "") == "/api/drafts"
           and "GET" in (getattr(r, "methods", None) or set())]
    assert hit, "web.routers.drafts 必须注册 GET /api/drafts"
    assert "thumbnail" in _read("web/routers/drafts.py")
    assert "preview_urls" in _read("web/routers/drafts.py")
    assert "- `GET /api/drafts`" in _read("docs/CONTRACT.md")


# ---------------------------------------------------------------------------
# 4. 正文配图命名契约：R3 / R4 / R5 / S1 / S2 / S5
# ---------------------------------------------------------------------------

def test_v158_storage_normalize_blocks_fabricated_filenames():
    from core.image_contract import storage_normalize

    out = storage_normalize(
        "正文\n\n![流程图](workflow.png)\n\n![对照](kb-compare.png)\n\n"
        "![封面](/img/dr-1/cover.png)\n\n![外链](https://example.com/a.png)\n"
    )
    assert "{{IMG:1}}" in out and "{{IMG:2}}" in out
    assert "workflow.png" not in out and "kb-compare.png" not in out
    assert "/img/dr-1/cover.png" in out, "合规真实地址必须保留"
    assert "https://example.com/a.png" in out, "外部图片不受契约约束"
    text = _read("core/text_purity.py")
    assert "storage_normalize" in text, "to_storage 落库前必须过契约闸"
    assert "PROMPT_RULE" in _read("core/copilot.py"), "提示词要禁止模型编文件名"


def test_v158_normalize_maps_placeholders_to_real_sec_by_index(tmp_path):
    from core import image_contract as ic

    ddir = tmp_path / "dr-v158"
    (ddir / "img").mkdir(parents=True)
    for name in ("cover.png", "sec-0.png", "sec-1.png"):
        (ddir / "img" / name).write_bytes(b"png")
    body = ("# 标题\n\n![封面]({{IMG:cover}})\n\n## 甲\n正文甲\n\n"
            "![流程](workflow.png)\n\n## 乙\n正文乙\n\n![对照]({{IMG:2}})\n")
    out, report = ic.normalize(body, "dr-v158", ddir)
    assert "{{IMG:" not in out and "workflow.png" not in out
    assert "/img/dr-v158/cover.png" in out
    assert "/img/dr-v158/sec-0.png" in out and "/img/dr-v158/sec-1.png" in out
    assert report["fixed"] >= 3
    assert ic.validate(out, "dr-v158", ddir) == []


def test_v158_injection_is_index_based_with_readable_alt():
    """R5：位置按序号，标题文本只作 alt；提示词标题体系不同也不会插错。"""
    from core.imagegen import inject_images_to_markdown

    md = "# 文章总标题\n\n导语。\n\n## 关键段落一\n\n段落一。\n\n## 关键段落二\n\n段落二。"
    imgs = {"cover": "/img/test/cover.png",
            "sections": ["/img/test/sec-0.png", "/img/test/sec-1.png"],
            "all": ["/img/test/cover.png", "/img/test/sec-0.png", "/img/test/sec-1.png"]}
    with patch("core.imagegen.get_draft_images", return_value=imgs):
        out = inject_images_to_markdown(md, "dr-test")
    for url in imgs["all"]:
        assert url in out, f"{url} 未注入"
    assert "![关键段落一]" in out and "![关键段落二]" in out
    assert out.index("/img/test/sec-0.png") < out.index("/img/test/sec-1.png")


def test_v158_validate_strict_catches_missing_local_image(tmp_path):
    from core import image_contract as ic

    ddir = tmp_path / "dr-empty"
    (ddir / "img").mkdir(parents=True)  # 资源目录存在但图片没生成 → 确定是死链
    src = "/img/dr-v158/cover.png"
    # ddir 里的 id 与链接 id 不同时按只读推算；这里直接校验 strict 语义
    assert ic.local_image_exists(src, ddir, strict=True) is False
    assert ic.validate("![封面](/img/dr-v158/cover.png)", "dr-v158", ddir) != []
    # 渲染期：资源目录不存在 → 无法判定，不能把合成/外部渲染的图片误删
    assert ic.local_image_exists("/img/synthetic-xyz/cover.png") is None


# ---------------------------------------------------------------------------
# 5. 六平台预览：R6 / R7 / S3 / S4
# ---------------------------------------------------------------------------

def test_v158_preview_platform_contract_and_safe_filename():
    from adapters.base import SUPPORTED_PREVIEW_PLATFORMS, save_preview
    from core.previews import PREVIEW_PLATFORMS

    assert set(PREVIEW_PLATFORMS) == {"wechat_mp", "xhs", "toutiao", "zhihu", "weibo", "twitter"}
    assert set(SUPPORTED_PREVIEW_PLATFORMS) == set(PREVIEW_PLATFORMS)
    with pytest.raises(ValueError):
        save_preview(Path("/tmp"), "../evil", "<html></html>")


def test_v158_build_all_previews_writes_xhs_and_lazy_heals(v158_db):
    from core import previews

    d = v158_db.add_draft("t-v158", "V15.8 回归稿件", "## 小节\n正文", ["wechat_mp"])
    did = d["id"]
    ddir = v158_db.draft_dir(did)
    (ddir / "xhs.md").write_text("# 标题\n\n小红书笔记正文", encoding="utf-8")
    built = previews.build_all_previews(did, platforms=("wechat_mp", "xhs"))
    assert "xhs" in built["platforms"] and "wechat_mp" in built["platforms"]
    xhs_html = (ddir / "preview-xhs.html").read_text(encoding="utf-8")
    assert "小红书" in xhs_html and "小红书笔记正文" in xhs_html

    (ddir / "preview-toutiao.html").unlink(missing_ok=True)
    assert previews.ensure_preview(did, "toutiao") is not None, "老草稿打开应懒生成缺失预览"
    assert (ddir / "preview-toutiao.html").is_file()
    from core.imagegen import recompile_previews
    assert callable(recompile_previews), "历史上被 import 却不存在的函数已补齐"


def test_v158_missing_image_degrades_to_placeholder_not_broken_img(tmp_path, monkeypatch):
    from core import db as core_db
    from core.themes import md_to_wechat_html

    monkeypatch.setattr(core_db, "DATA", tmp_path)
    did = "dr-v158-missing"
    (tmp_path / "drafts" / did / "img").mkdir(parents=True)
    html = md_to_wechat_html(f"正文\n\n![配图](/img/{did}/sec-0.png)\n", "标题")
    assert "配图缺失，已跳过" in html
    assert f"/img/{did}/sec-0.png" not in html, "不能把死链原样交给浏览器"


def test_v158_quality_gate_blocks_missing_images(v158_db):
    from core import artifacts

    d = v158_db.add_draft("t-v158", "缺图稿件", "![封面]({{IMG:cover}})", ["wechat_mp"])
    did = d["id"]
    ddir = v158_db.draft_dir(did)
    (ddir / "img").mkdir(parents=True, exist_ok=True)
    gate = artifacts.quality_gate(did)
    assert gate["ok"] is False and gate["missing"]
    assert "生成配图" in gate["hint"]


# ---------------------------------------------------------------------------
# 6. 分享链接：F3 / R7，且不放宽「只给真实产物发链接」
# ---------------------------------------------------------------------------

def test_v158_share_set_still_skips_platforms_without_artifacts(v158_db):
    from core import share

    d = v158_db.add_draft("t-v158", "只有公众号产物", "正文", ["wechat_mp"])
    did = d["id"]
    (v158_db.draft_dir(did) / "preview-wechat_mp.html").write_text("<html></html>", encoding="utf-8")
    res = share.create_share_set(did, ["wechat_mp", "xhs", "toutiao"], "u-a")
    assert len(res["links"]) == 1 and res["links"][0]["platform"] == "wechat_mp"
    assert {s["platform"] for s in res["skipped"]} == {"xhs", "toutiao"}
    assert not (v158_db.draft_dir(did) / "preview-xhs.html").exists()


def test_v158_share_set_self_heals_xhs_when_source_exists(v158_db):
    """老草稿有 xhs.md / 卡片但漏写 HTML 时，签发前自动补产物。"""
    from core import share

    d = v158_db.add_draft("t-v158", "小红书已产出", "正文", ["xhs"])
    did = d["id"]
    ddir = v158_db.draft_dir(did)
    (ddir / "xhs.md").write_text("# 标题\n\n笔记正文", encoding="utf-8")
    (ddir / "preview-wechat_mp.html").write_text("<html></html>", encoding="utf-8")
    res = share.create_share_set(did, ["wechat_mp", "xhs"], "u-a")
    assert {x["platform"] for x in res["links"]} == {"wechat_mp", "xhs"}
    assert (ddir / "preview-xhs.html").is_file()


# ---------------------------------------------------------------------------
# 7. 建库迁移幂等：CI 曾偶发 duplicate column name: tenant_id
#    （PRAGMA 读到旧 schema，另一连接抢先补列，本连接 ALTER 抛错）
# ---------------------------------------------------------------------------

def test_v158_tenant_migration_tolerates_concurrent_alter(tmp_path):
    import sqlite3
    from core import db as core_db

    path = tmp_path / "race.db"
    real = sqlite3.connect(path)
    real.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY)")
    real.commit()
    real.row_factory = sqlite3.Row
    rival = sqlite3.connect(path)

    class _RacingConn:
        """在 ALTER 落库前，模拟另一条连接抢先补上 tenant_id。"""

        def __init__(self, conn, other):
            self._conn, self._other = conn, other

        def execute(self, sql, *args):
            if sql.startswith("ALTER TABLE") and "tenant_id" in sql:
                self._other.execute(sql)
                self._other.commit()
            return self._conn.execute(sql, *args)

    try:
        racing = _RacingConn(real, rival)
        core_db._ensure_tenant_columns(racing)  # 修复前这里直接抛 OperationalError
        assert "tenant_id" in {r["name"] for r in real.execute("PRAGMA table_info(jobs)")}
        core_db._ensure_tenant_columns(racing)  # 二次调用同样幂等
    finally:
        real.close()
        rival.close()


def test_v158_both_migration_paths_use_idempotent_helper():
    src = _read("core/db.py")
    assert src.count("_ensure_tenant_columns(c)") == 2, \
        "conn() 首次建库与快速路径必须共用同一个幂等补列实现"
    assert "duplicate column" in src, "并发补列冲突必须按「已完成」处理"
