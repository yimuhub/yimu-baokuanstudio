# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。"""

__version__ = "11.1.0"
__codename__ = "山岳赋"
__codename_en__ = "Mountain Hymn"
__slogan__ = "山高可攀 岳峙成章 · 左栏、中栏、右栏逐项对齐原型，功能一字未减 · 原生安装包 Win/macOS/Linux 开箱即用"
__slogan_cn__ = "山高可攀 岳峙成章 · 左栏、中栏、右栏逐项对齐原型，功能一字未减 · 原生安装包 Win/macOS/Linux 开箱即用"
__slogan_en__ = "Summit and Verse. · Every Pane Now Matches the Prototype, With Zero Feature Loss"


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
