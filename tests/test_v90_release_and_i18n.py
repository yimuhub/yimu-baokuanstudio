"""V9.0.0 (万象生 / Infinite Worlds) 全新版本发布与 i18n 国际化引擎质量门禁。

验证目标：
1. 单一真源 version.__version__ == "9.0.0"，__codename__ == "万象生"；
2. README.md 为纯英文国际化规范，与 README_ZH.md 双向互链；
3. RELEASES.md 具备完备的 V9.0.0 里程碑发布说明；
4. 前端引入 web/static/js/i18n.js，具备完整中英双语字典与切换函数；
5. PC 端 index.html 与移动端 mobile.html 均集成中英文即时切换按钮；
6. 杜绝任何旧版本号（8.3.33、V8.3.33、8.3.2、V8.2）残留。
"""
from pathlib import Path
import pytest
import version


def test_v90_version_single_source_of_truth():
    """验证 9.3.0 版本单一真源"""
    assert version.__version__ == "9.3.0"
    assert version.__codename__ == "万象融"
    assert "Cross-Platform" in version.__slogan_en__

    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
    readme_en = Path("README.md").read_text(encoding="utf-8")
    readme_zh = Path("README_ZH.md").read_text(encoding="utf-8")
    releases_md = Path("RELEASES.md").read_text(encoding="utf-8")
    license_txt = Path("LICENSE").read_text(encoding="utf-8")

    assert "V9.3.0" in index_html
    assert "9.3.0" in index_html
    assert "V9.3.0" in mobile_html
    assert "version-9.3.0" in readme_en
    assert "version-9.3.0" in readme_zh
    assert "V9.3.0" in license_txt
    assert "Licensor:            yimu.hyipf.com" in license_txt
    assert "The Licensed Work is (c) 2026 yimu.hyipf.com" in license_txt


def test_v90_releases_showcase_page_and_api():
    """验证版本更新展示页 (/releases) 与 API (/api/releases) 正常提供服务"""
    from fastapi.testclient import TestClient
    from web.admin import app

    client = TestClient(app)

    # 1. /releases 页面
    r = client.get("/releases")
    assert r.status_code == 200
    assert "V9.3.0" in r.text or "V9.2.0" in r.text
    assert "yimu.hyipf.com" in r.text
    assert "核心版本差异演进矩阵" in r.text

    # 2. /admin/releases 兼容页面
    r_admin = client.get("/admin/releases")
    assert r_admin.status_code == 200
    assert "V9.3.0" in r_admin.text or "V9.2.0" in r_admin.text

    # 3. /api/releases 数据接口
    r_api = client.get("/api/releases")
    assert r_api.status_code == 200
    d = r_api.json()
    assert d.get("ok") is True
    assert d.get("current_version") == "9.3.0"
    assert d.get("licensor") == "yimu.hyipf.com"
    assert len(d.get("releases", [])) >= 4

    # 4. 前端入口可见性
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
    assert 'href="/releases"' in index_html
    assert 'href="/releases"' in mobile_html


def test_v90_clean_no_legacy_versions():
    """验证 index.html 与 mobile.html 中无旧版残留"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")

    for legacy in ["9.0.0", "V9.0.0", "8.3.33", "V8.3.33", "V8.3.2", "V8.2"]:
        assert legacy not in index_html, f"Legacy version '{legacy}' still found in index.html"
        assert legacy not in mobile_html, f"Legacy version '{legacy}' still found in mobile.html"


def test_v90_i18n_assets_and_integration():
    """验证 i18n 国际化引擎及在各端的集成"""
    i18n_js_path = Path("web/static/js/i18n.js")
    assert i18n_js_path.exists(), "web/static/js/i18n.js must exist"
    i18n_code = i18n_js_path.read_text(encoding="utf-8")

    assert "zh:" in i18n_code
    assert "en:" in i18n_code
    assert "applyLanguage" in i18n_code
    assert "toggleLanguage" in i18n_code
    assert "yimu_lang" in i18n_code

    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")

    # 1. PC 端引入 i18n 脚本且具备切换按钮
    assert "/static/js/i18n.js" in index_html
    assert "btn-lang-toggle" in index_html
    assert "toggleLanguage()" in index_html

    # 2. 移动端引入 i18n 脚本且具备切换按钮
    assert "/static/js/i18n.js" in mobile_html
    assert "mobile-lang-text" in mobile_html
    assert "toggleLanguage()" in mobile_html


def test_v90_bilingual_readmes_interlinked():
    """验证纯英文 README.md 与中文 README_ZH.md 互链与内容完整性"""
    readme_en = Path("README.md").read_text(encoding="utf-8")
    readme_zh = Path("README_ZH.md").read_text(encoding="utf-8")

    # 英文 README 具备纯英文主体与中文链接
    assert "YIMU Studio" in readme_en
    assert "Why YIMU Studio?" in readme_en
    assert "Cinematic Storyboarding" in readme_en
    assert "README_ZH.md" in readme_en

    # 中文 README 具备英文链接
    assert "一幕·YIMU 爆款工作室" in readme_zh
    assert "README.md" in readme_zh
    assert "RELEASES.md" in readme_zh


def test_v91_deep_i18n_subviews_and_menu_purity():
    """验证 V9.1 二级子页面、子标签与菜单级 100% 深度双语纯净性机制"""
    i18n_js_path = Path("web/static/js/i18n.js")
    i18n_dict_path = Path("web/static/js/i18n_dict.json")
    index_html_path = Path("web/templates/index.html")

    assert i18n_js_path.exists()
    assert i18n_dict_path.exists()

    i18n_code = i18n_js_path.read_text(encoding="utf-8")
    index_html = index_html_path.read_text(encoding="utf-8")

    # 1. 词库规模与全量内嵌检查（至少 1700+ 条全量 UI 词条）
    import json
    with open(i18n_dict_path, "r", encoding="utf-8") as f:
        dict_data = json.load(f)
    assert len(dict_data) >= 1700, f"Expected at least 1700 terms in dictionary, got {len(dict_data)}"
    assert "EXACT_MAP" in i18n_code
    assert "REVERSE_MAP" in i18n_code
    assert "PHRASE_LIST" in i18n_code

    # 2. 一级导航语言感知与标题英文切换
    assert "titles_en" in index_html
    assert "titles_zh" in index_html
    assert "Dashboard" in index_html
    assert "Media Studio" in index_html
    assert "Control Center" in index_html
    assert "Profile Center" in index_html

    # 3. 二级子页面 (subTab) 语言联动翻译钩子
    assert "function switchSubTab" in index_html
    assert "YIMU_I18N.translateNode" in index_html


    # 4. 递归翻译节点支持 (TEXT_NODE 与常用属性)
    assert "translateDOMNode" in i18n_code
    assert "placeholder" in i18n_code
    assert "aria-label" in i18n_code
    assert "title" in i18n_code

