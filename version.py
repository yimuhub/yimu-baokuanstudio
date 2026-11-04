# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。"""

__version__ = "12.0.0"
__codename__ = "松涛境"
__codename_en__ = "Pinewave Realm"
__slogan__ = "松风入座 涛自成章 · 左栏恒定 中栏恒定对话 功能全在右栏展开 全屏查看 · 原生安装包 Win/macOS/Linux 开箱即用"
__slogan_cn__ = "松风入座 涛自成章 · 左栏恒定 中栏恒定对话 功能全在右栏展开 全屏查看 · 原生安装包 Win/macOS/Linux 开箱即用"
__slogan_en__ = "Pines in the Wind, Chapters in the Waves · Fixed Rail, Fixed Chat, Every Feature Opens on the Right — Full Screen Ready"


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
