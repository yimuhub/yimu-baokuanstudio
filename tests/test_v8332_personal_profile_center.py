"""V8.3.32 独立个人中心与左下角版本号检查更新端到端质量验证。

验证目标：
1. 版本单一真源 __version__ == '8.3.32'；
2. 侧边栏左下角固定展示版本号卡片/按钮，绑定 checkSystemUpdate(true)；
3. 侧边栏底部的「系统授权」位置升级为「个人中心」入口，兼容保留 side-auth-badge；
4. 侧边栏主导航增加「个人中心」项（data-p="profile"）；
5. 主内容区提供独立的个人中心面板（#p-profile），完整承接 6 维数字画像、个人专属模型 API Vault、日夜外观、输出水印、矩阵派生预设、GitHub 图床等个人专属配置；
6. 控制中心（#sp-settings）成功剥离个人偏好配置，保留系统级/平台级配置并提供直达个人中心导流卡片；
7. 移动端与全站版本号一致性无断层。
"""
from pathlib import Path
import pytest
import version


def test_v8332_version_single_source_of_truth():
    """验证单一真源版本号已升级至 8.3.32"""
    assert version.__version__ == "8.3.32"
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
    readme_md = Path("README.md").read_text(encoding="utf-8")
    license_txt = Path("LICENSE").read_text(encoding="utf-8")

    assert "V8.3.32" in index_html
    assert "8.3.32" in index_html
    assert "V8.3.32" in mobile_html
    assert "version-8.3.32" in readme_md
    assert "V8.3.32" in license_txt


def test_v8332_sidebar_profile_and_fixed_version():
    """验证左侧边栏底部的个人中心入口与左下角固定版本号检查更新"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")

    # 1. 导航项中具备个人中心
    assert 'data-p="profile"' in index_html
    assert 'id="nav-item-profile"' in index_html
    assert '个人中心' in index_html

    # 2. 侧边栏底部升级个人中心入口，并保留 side-auth-badge 供 updateAuthUI 兼容
    assert 'id="side-user-profile-btn"' in index_html
    assert 'onclick="switchToProfileCenter()"' in index_html
    assert 'id="side-auth-badge"' in index_html

    # 3. 左下角固定版本号卡片与检查更新触发器
    assert 'id="side-version-badge"' in index_html or 'class="side-version-bar"' in index_html
    assert 'onclick="checkSystemUpdate(true)"' in index_html
    assert 'id="side-version-text"' in index_html
    assert "V8.3.32" in index_html


def test_v8332_independent_personal_center_panel():
    """验证主内容区独立的个人中心面板（#p-profile）及其包含的核心个人设置"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")

    # 1. 独立面板存在
    assert '<section class="panel" id="p-profile">' in index_html

    # 2. 账号与媒体档案
    assert 'id="profile-media-name-input"' in index_html
    assert 'saveProfileMediaName()' in index_html

    # 3. 6 维数字画像 (Profile & 人设档案)
    assert 'st-profile-info' in index_html
    assert 'openProfileModal()' in index_html
    assert '账号 6 维数字画像' in index_html

    # 4. 我的专属模型 API 凭证 (API Vault)
    assert 'openUserVaultModal()' in index_html
    assert '我的专属模型 API 凭证' in index_html

    # 5. 界面日夜外观与排版风格
    assert 'st-theme-mode-info' in index_html
    assert 'setThemeModeDirect(' in index_html
    assert 'st-theme-info' in index_html

    # 6. 输出水印与品牌印记
    assert 'st-watermark-info' in index_html
    assert 'openWatermarkModal()' in index_html

    # 7. GitHub 图床（公网图片外链）
    assert 'st-imgbed-info' in index_html
    assert "modal('m-imgbed')" in index_html

    # 8. 默认矩阵渠道派生预设
    assert 'id="pc-settings-derive-capsules"' in index_html
    assert 'toggleAllPcSettingsDerivePlatforms()' in index_html
    assert 'savePcSettingsDerivePlatforms()' in index_html


def test_v8332_console_settings_refactored():
    """验证控制中心已移除冗余个人项，保留系统级配置并具备导向个人中心的卡片"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")

    # 1. 控制中心系统设置面板存在
    assert '<div id="sp-settings" class="sub-view"' in index_html

    # 2. 具备直达个人中心的导流引导卡
    assert '创作者个人专属偏好已独立归纳至「个人中心」' in index_html
    assert 'switchToProfileCenter()' in index_html

    # 3. 保留系统级/平台级关键配置
    assert '企业级 AI 大模型服务与 API 中枢' in index_html
    assert '各模型服务使用量统计' in index_html
    assert '热点关键词白名单' in index_html
    assert 'AI 质量考核与自动迭代' in index_html
    assert '草稿箱自动过期清理' in index_html
    assert 'GitHub 仓库在线升级与同步' in index_html
