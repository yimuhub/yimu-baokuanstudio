# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。"""

__version__ = "14.0.0"
__codename__ = "兰心曲"
__codename_en__ = "Orchid Melody"
__slogan__ = "兰心谱曲 落笔成章 · 全功能离线安装包 自带运行时 全量依赖 内置浏览器 出厂配额 · 亮暗双主题视觉统一 附件直传 模型直选 提示词一键优化 · Win/macOS/Linux 安装即用"
__slogan_cn__ = "兰心谱曲 落笔成章 · 全功能离线安装包 自带运行时 全量依赖 内置浏览器 出厂配额 · 亮暗双主题视觉统一 附件直传 模型直选 提示词一键优化 · Win/macOS/Linux 安装即用"
__slogan_en__ = "Orchid Heart Composing, Every Stroke a Song · Fully self-contained offline installer: bundled Python, all dependencies, built-in Chromium, fresh factory quota · Unified light/dark visuals, direct attachments, model picker, one-click prompt polish · Install and run on Win/macOS/Linux"


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
