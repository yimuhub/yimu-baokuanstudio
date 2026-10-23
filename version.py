# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。"""

__version__ = "10.2.0"
__codename__ = "鸿蒙始"
__codename_en__ = "Primordial Dawn"
__slogan__ = "一念起 一幕开 万象生 · 全平台独立桌面客户端，零环境配置开箱即用"
__slogan_cn__ = "一念起 一幕开 万象生 · 全平台独立桌面客户端，零环境配置开箱即用"
__slogan_en__ = "One Thought. One Scene. Infinite Worlds · Zero-Config Standalone Desktop Client for Win, Mac & Linux"


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
