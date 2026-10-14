"""V9.1.1 全站双语切换、各级菜单、子页面与全量弹窗 100% 纯净度终极门禁测试。"""
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup, Comment
import pytest
import version


def test_v911_version_single_source():
    """验证版本单一真源全栈统一为 10.0.0"""
    assert version.__version__ == "10.0.0"
    assert version.__codename__ == "澄音境"

    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
    license_txt = Path("LICENSE").read_text(encoding="utf-8")
    readme_en = Path("README.md").read_text(encoding="utf-8")
    readme_zh = Path("README_ZH.md").read_text(encoding="utf-8")
    releases_md = Path("RELEASES.md").read_text(encoding="utf-8")

    assert "V10.0.0" in index_html
    assert "10.0.0" in index_html
    assert "V10.0.0" in mobile_html
    assert "V10.0.0" in license_txt
    assert "version-10.0.0" in readme_en
    assert "version-10.0.0" in readme_zh
    assert "Version 10.0.0" in releases_md


def test_v911_dictionary_and_runtime_assets():
    """验证 1,768+ 词条规模与 i18n.js 运行时完备性"""
    dict_path = Path("web/static/js/i18n_dict.json")
    js_path = Path("web/static/js/i18n.js")

    assert dict_path.exists()
    assert js_path.exists()

    with open(dict_path, "r", encoding="utf-8") as f:
        dict_data = json.load(f)

    assert len(dict_data) >= 1700, f"Expected >= 1700 terms, got {len(dict_data)}"

    js_code = js_path.read_text(encoding="utf-8")
    assert "EXACT_MAP" in js_code
    assert "REVERSE_MAP" in js_code
    assert "PHRASE_LIST" in js_code
    assert "REVERSE_PHRASE_LIST" in js_code
    assert "translateDOMNode" in js_code
    assert "applyLanguage" in js_code
    assert "toggleLanguage" in js_code
    assert "top_profile_6d" in js_code
    assert "top_my_api" in js_code


def test_v911_templates_zero_residual_chinese_in_english_mode():
    """验证 index.html 与 mobile.html 在英文模式下所有文本节点与属性 0 残留中文"""
    with open("web/static/js/i18n_dict.json", "r", encoding="utf-8") as f:
        dict_map = json.load(f)

    phrases = sorted(dict_map.items(), key=lambda x: len(x[0]), reverse=True)
    chinese_pattern = re.compile(r'[\u4e00-\u9fa5]')

    for fpath in ["web/templates/index.html", "web/templates/mobile.html"]:
        with open(fpath, encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        untranslated = []
        for tag in soup.find_all(True):
            if tag.name in ["script", "style", "code", "pre"]:
                continue
            for text in tag.find_all(string=True, recursive=False):
                if isinstance(text, Comment):
                    continue
                s = text.strip()
                if not s or not chinese_pattern.search(s):
                    continue
                if s in dict_map:
                    trans = dict_map[s]
                else:
                    t = s
                    for zh, en in phrases:
                        if zh in t:
                            t = t.replace(zh, en)
                    trans = t
                m = chinese_pattern.findall(trans)
                if m:
                    untranslated.append((s, trans, "".join(m), tag.name))

            for attr in ["placeholder", "title", "aria-label", "value"]:
                val = tag.get(attr)
                if val and isinstance(val, str):
                    s = val.strip()
                    if not s or not chinese_pattern.search(s):
                        continue
                    if s in dict_map:
                        trans = dict_map[s]
                    else:
                        t = s
                        for zh, en in phrases:
                            if zh in t:
                                t = t.replace(zh, en)
                        trans = t
                    m = chinese_pattern.findall(trans)
                    if m:
                        untranslated.append((s, trans, "".join(m), f"{tag.name}[{attr}]"))

        assert len(untranslated) == 0, f"Found {len(untranslated)} untranslated Chinese nodes in {fpath}: {untranslated[:5]}"


def test_v911_data_i18n_keys_validity():
    """验证两个页面中所有 data-i18n 属性键均存在于 I18N_DICT 中"""
    js_path = Path("web/static/js/i18n.js")
    js_code = js_path.read_text(encoding="utf-8")

    # 提取 I18N_DICT keys
    dict_zh_match = re.search(r'zh:\s*\{(.*?)\}\s*,\s*en:', js_code, re.DOTALL)
    assert dict_zh_match, "Could not extract I18N_DICT.zh"
    dict_zh_text = dict_zh_match.group(1)
    keys = set(re.findall(r'(\w+)\s*:', dict_zh_text))

    for fpath in ["web/templates/index.html", "web/templates/mobile.html"]:
        content = Path(fpath).read_text(encoding="utf-8")
        used_keys = re.findall(r'data-i18n="([^"]+)"', content)
        for k in used_keys:
            assert k in keys, f"data-i18n key '{k}' used in {fpath} is not defined in I18N_DICT"
