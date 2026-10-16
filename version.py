# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。"""

__version__ = "10.1.4"
__codename__ = "鸿蒙始"
__codename_en__ = "Primordial Dawn"
__slogan__ = "一念起 一幕开 万象生 · 鸿蒙开元，全端动态版本与定价单一真源"
__slogan_cn__ = "一念起 一幕开 万象生 · 鸿蒙开元，全端动态版本与定价单一真源"
__slogan_en__ = "One Thought. One Scene. Infinite Worlds · Dynamic Version & Pricing Single Source of Truth"


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
