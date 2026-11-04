# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。"""

__version__ = "11.1.1"
__codename__ = "江河曲"
__codename_en__ = "River Rhapsody"
__slogan__ = "江流不息 河山入曲 · 品牌主色与左 / 中 / 右三栏细节全面修补，实机截图逐像素校准 · 原生安装包 Win/macOS/Linux 开箱即用"
__slogan_cn__ = "江流不息 河山入曲 · 品牌主色与左 / 中 / 右三栏细节全面修补，实机截图逐像素校准 · 原生安装包 Win/macOS/Linux 开箱即用"
__slogan_en__ = "Rivers Flow, Verses Follow. · Brand Color and Triple-Pane Details Recalibrated Against Real Screenshots"


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
