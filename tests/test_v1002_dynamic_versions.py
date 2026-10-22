# SPDX-License-Identifier: BUSL-1.1
"""V10.1 全端全页面动态版本单一真源专项门禁测试。

核心验证：
1. 全站版本单一真源步进至 10.1（鸿蒙始 · Primordial Dawn）。
2. 所有前端页面（PC 端首页、移动端、独立定价页、运营看板、用户管理、审计日志等）全部动态从单一真源提取版本号。
3. 原始模板文件不再写死静态旧版本，杜绝因漏改或缓存导致的版本漂移。
4. 前端独立动态版本库 (web/static/js/version-sync.js) 具备全局管理与自执行能力。
5. 后端 API (/api/version, /health, /api/releases) 均以动态单一真源提供服务。
"""
from __future__ import annotations

import re
from pathlib import Path
from fastapi.testclient import TestClient

import version
from web.admin import app, get_html_page, get_mobile_html_page, get_app_version, render_dynamic_html

ROOT = Path(__file__).resolve().parent.parent


def test_v1002_version_single_source_of_truth():
    """验证版本单一真源为当前版本。"""
    assert version.__version__ == "10.1.9"
    assert version.__codename__ == "鸿蒙始"
    assert hasattr(version, "get_version")
    assert version.get_version() == "10.1.9"

    info = version.get_version_info()
    assert info.get("version") == "10.1.9"
    assert info.get("codename") == "鸿蒙始"

    # pyproject.toml
    pyproject_toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "10.1.9"' in pyproject_toml

    # locales
    zh_locale = (ROOT / "web/static/locales/zh-CN.json").read_text(encoding="utf-8")
    en_locale = (ROOT / "web/static/locales/en-US.json").read_text(encoding="utf-8")
    assert '"version": "10.1.9"' in zh_locale
    assert '"version": "10.1.9"' in en_locale


def test_v1002_all_pages_render_dynamic_version():
    """验证所有页面输出的 HTML 均动态包含当前单一真源版本号及 meta 标识。"""
    client = TestClient(app)
    cur = version.__version__
    full = f"V{cur}"

    # 1. PC 端首页
    resp_index = client.get("/")
    assert resp_index.status_code == 200
    html_index = resp_index.text
    assert f'<meta name="app-version" content="{cur}">' in html_index
    assert f'一幕·YIMU 爆款工作室 {full}' in html_index
    assert 'src="/static/js/version-sync.js"' in html_index
    assert full in html_index

    # 2. 移动端
    resp_mobile = client.get("/m")
    assert resp_mobile.status_code == 200
    html_mobile = resp_mobile.text
    assert f'<meta name="app-version" content="{cur}">' in html_mobile
    assert f'<title>一幕·YIMU 移动工作室 {full}</title>' in html_mobile
    assert 'src="/static/js/version-sync.js"' in html_mobile
    assert full in html_mobile

    # 3. 定价页
    resp_pricing = client.get("/pricing")
    assert resp_pricing.status_code == 200
    html_pricing = resp_pricing.text
    assert f'<meta name="app-version" content="{cur}">' in html_pricing
    assert f'<title>套餐与价格 · 一幕·YIMU 爆款工作室 {full}</title>' in html_pricing
    assert 'src="/static/js/version-sync.js"' in html_pricing
    assert full in html_pricing

    # 4. 发布历史展示页
    resp_releases = client.get("/releases")
    assert resp_releases.status_code == 200
    assert full in resp_releases.text


def test_v1002_api_endpoints_version_consistency():
    """验证各 API 接口返回的版本强一致性。"""
    client = TestClient(app)
    cur = version.__version__

    # /api/version
    r_ver = client.get("/api/version")
    assert r_ver.status_code == 200
    d_ver = r_ver.json()
    assert d_ver.get("version") == cur
    assert d_ver.get("details", {}).get("codename") == version.__codename__

    # /health & /api/health
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json().get("version") == cur

    r_api_health = client.get("/api/health")
    assert r_api_health.status_code == 200
    assert r_api_health.json().get("version") == cur

    # /api/releases
    r_rel = client.get("/api/releases")
    assert r_rel.status_code == 200
    d_rel = r_rel.json()
    assert d_rel.get("current_version") == cur
    assert d_rel.get("releases", [])[0].get("version") in (cur, "10.1", "10.0.1")


def test_v1002_version_sync_js_module_integrity():
    """验证前端动态版本库 version-sync.js 模块完整性与功能完备性。"""
    js_path = ROOT / "web/static/js/version-sync.js"
    assert js_path.exists(), "必须存在 web/static/js/version-sync.js"
    js_content = js_path.read_text(encoding="utf-8")

    assert "window.AppVersion = AppVersion" in js_content
    assert "normalize:" in js_content
    assert "apply:" in js_content
    assert "sync:" in js_content
    assert "init:" in js_content
    assert "meta[name=\"app-version\"]" in js_content
    assert "data-app-version" in js_content
    assert ".version-badge" in js_content


def test_v1002_no_hardcoded_version_floor():
    """验证 index.html 中不再硬编码 floorVer 保护，全部由 AppVersion / 单一真源驱动。"""
    idx_raw = (ROOT / "web/templates/index.html").read_text(encoding="utf-8")
    assert "const floorVer = '10.0.1';" not in idx_raw
    assert "const floorVer = '10.1';" not in idx_raw
    assert "floorVer" not in idx_raw
