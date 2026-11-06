# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。"""

__version__ = "13.0.0"
__codename__ = "梅雪镜"
__codename_en__ = "Plum-Snow Mirror"
__slogan__ = "梅映雪窗 镜里成章 · 全功能离线安装包 自带运行时 全量依赖 内置浏览器 出厂配额 · 左栏恒定 中栏恒定对话 功能全在右栏展开 全屏查看 · Win/macOS/Linux 安装即用"
__slogan_cn__ = "梅映雪窗 镜里成章 · 全功能离线安装包 自带运行时 全量依赖 内置浏览器 出厂配额 · 左栏恒定 中栏恒定对话 功能全在右栏展开 全屏查看 · Win/macOS/Linux 安装即用"
__slogan_en__ = "Plum Blossom at the Snow Window, Every Page a Mirror · Fully self-contained offline installer: bundled Python, all dependencies, built-in Chromium, fresh factory quota · Fixed Rail, Fixed Chat, Every Feature on the Right · Install and run on Win/macOS/Linux"


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
