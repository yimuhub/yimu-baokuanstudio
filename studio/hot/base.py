# SPDX-License-Identifier: BUSL-1.1
"""平台采集器插件接口（移植自项目 A app/collectors/base.py 的设计）。

每个平台一个模块（如 collectors/weibo.py），实现 PlatformCollector；
pipeline 只依赖本接口 —— 加新平台 = 加一个文件 + 注册一行。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import HotItem


class NotConfiguredError(Exception):
    """平台需要外部配置（如 RSS feed / 登录 Cookie / API Key）但未提供。

    pipeline 捕获后记为 skipped（未配置），不算失败，不影响其他平台。
    """


class PlatformCollector(ABC):
    """平台适配器基类。"""

    #: 平台码（全局唯一，如 "weibo"）
    name: str = ""
    #: 中文名（如 "微博"）
    display_name: str = ""
    #: 分组：hotlist / community / media / news / global
    category: str = "misc"
    #: 是否启用（False 则 collect_all 跳过）
    enabled: bool = True

    @abstractmethod
    def collect(self) -> list[HotItem]:
        """采集本平台当前热榜。抛错由 pipeline 捕获隔离，单个平台失败不影响其他平台。"""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} {self.name}>"


# 注册表：平台码 → 采集器类。collectors/*.py  import 后调用 register。
_REGISTRY: dict[str, type[PlatformCollector]] = {}


def register(cls: type[PlatformCollector]) -> type[PlatformCollector]:
    """类装饰器：@register 把采集器记入注册表。"""
    assert cls.name, f"{cls.__name__} 必须设置 name（平台码）"
    _REGISTRY[cls.name] = cls
    return cls


def platform_catalog() -> list[dict]:
    """平台清单（对齐 A 的 hot.py platforms 命令）。"""
    from . import collectors  # noqa: F401 触发各平台模块注册

    return [
        {"name": name, "display_name": cls.display_name}
        for name, cls in sorted(_REGISTRY.items())
    ]


def get_collector(name: str) -> PlatformCollector:
    """按平台码取采集器实例；未知平台抛 KeyError。"""
    from . import collectors  # noqa: F401

    return _REGISTRY[name]()
