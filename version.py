# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。

版本线规范（v15.0.0 起，见 VERSION_POLICY.md）：
主版本锁定 V15，日常迭代一律在 15.x.y 内做小版本递增；
主版本跳升仅限开发者书面申请并修订本规范。
"""

__version__ = "15.3.0"
__codename__ = "九霄阔"
__codename_en__ = "Broad Ninth Heaven"
__slogan__ = "一念起 一幕开 万象生 · 三栏外壳交互大修：导航减肥、一键折叠、工作台全屏、去重清障"
__slogan_cn__ = "一念起 一幕开 万象生 · 三栏外壳交互大修：导航减肥、一键折叠、工作台全屏、去重清障"
__slogan_en__ = "One Thought. One Scene. Infinite Worlds · Shell UX overhaul: lean nav, rail collapse, fullscreen workbench"


def get_version() -> str:
    """获取当前系统版本号（单一真源）。"""
    return __version__


def get_version_info() -> dict:
    """获取系统版本元数据字典。"""
    return {
        "version": __version__,
        "codename": __codename__,
        "codename_en": __codename_en__,
        "slogan": __slogan__,
        "slogan_cn": __slogan_cn__,
        "slogan_en": __slogan_en__,
    }
