# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。

版本线规范（v15.0.0 起，见 VERSION_POLICY.md）：
主版本锁定 V15，日常迭代一律在 15.x.y 内做小版本递增；
主版本跳升仅限开发者书面申请并修订本规范。
"""

__version__ = "15.4.0"
__codename__ = "四海晏"
__codename_en__ = "Four Seas at Peace"
__slogan__ = "一念起 一幕开 万象生 · 工作台工具条 2.0：19 钮归 6，收纳有序，核心内容大面积呈现"
__slogan_cn__ = "一念起 一幕开 万象生 · 工作台工具条 2.0：19 钮归 6，收纳有序，核心内容大面积呈现"
__slogan_en__ = "One Thought. One Scene. Infinite Worlds · Toolbar 2.0: 19 buttons into 6 + menus, content first"


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
