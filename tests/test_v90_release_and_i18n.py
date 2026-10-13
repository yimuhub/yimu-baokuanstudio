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
    """验证 9.0.0 版本单一真源"""
    assert version.__version__ == "9.0.0"
    assert version.__codename__ == "万象生"
    assert "Infinite Worlds" in version.__slogan_en__

    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
    readme_en = Path("README.md").read_text(encoding="utf-8")
    readme_zh = Path("README_ZH.md").read_text(encoding="utf-8")
    releases_md = Path("RELEASES.md").read_text(encoding="utf-8")
    license_txt = Path("LICENSE").read_text(encoding="utf-8")

    assert "V9.0.0" in index_html
    assert "9.0.0" in index_html
    assert "V9.0.0" in mobile_html
    assert "version-9.0.0" in readme_en
    assert "version-9.0.0" in readme_zh
    assert "Version 9.0.0" in releases_md
    assert "V9.0.0" in license_txt


def test_v90_clean_no_legacy_versions():
    """验证 index.html 与 mobile.html 中无旧版残留"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")

    for legacy in ["8.3.33", "V8.3.33", "V8.3.2", "V8.2"]:
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
