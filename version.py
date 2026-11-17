# SPDX-License-Identifier: BUSL-1.1
"""全局版本号定义（单一真源）。

版本线规范（v15.0.0 起，见 VERSION_POLICY.md）：
主版本锁定 V15，日常迭代一律在 15.x.y 内做小版本递增；
主版本跳升仅限开发者书面申请并修订本规范。
"""

__version__ = "15.9.2"
__codename__ = "万象衡"
__codename_en__ = "Balance of All Things"
__slogan__ = "一念起 一幕开 万象生 · 窗口启动加固：系统浏览器优先、内置内核兜底、启动存活探测与崩溃降级"
__slogan_cn__ = "一念起 一幕开 万象生 · 窗口启动加固：系统浏览器优先、内置内核兜底、启动存活探测与崩溃降级"
__slogan_en__ = "One Thought. One Scene. Infinite Worlds · Window launch hardening: system browser first, bundled kernel as fallback, liveness probe and crash degradation"


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
