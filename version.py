# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。"""

__version__ = "11.0.1"
__codename__ = "沧海吟"
__codename_en__ = "Oceanic Ode"
__slogan__ = "一栏起 一屏收 万物各归位 · 三栏工作台重构，对话、创作、资产同屏并行 · 原生安装包 Win/macOS/Linux 开箱即用"
__slogan_cn__ = "一栏起 一屏收 万物各归位 · 三栏工作台重构，对话、创作、资产同屏并行 · 原生安装包 Win/macOS/Linux 开箱即用"
__slogan_en__ = "One Rail. One Canvas. Everything in Place. · The Three-Pane Workbench: Chat, Craft and Assets on One Screen"


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
