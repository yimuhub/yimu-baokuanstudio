# SPDX-License-Identifier: BUSL-1.1
"""热榜条目数据模型（对齐项目 A app/storage.py 的入库字段）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class HotItem:
    """单条热榜。hot_raw 为平台原始热度值；hot_score 为跨平台归一化分（0-100）。"""

    platform: str  # 平台码，如 weibo
    platform_name: str  # 平台中文名，如 微博
    title: str
    url: str = ""
    rank: int = 0  # 平台榜单排名（1 起；0=无排名）
    hot_raw: float = 0.0  # 平台原始热度（阅读量/热度值，口径各平台不同）
    views: int = 0
    likes: int = 0
    collects: int = 0
    comments: int = 0
    hot_score: float = 0.0  # 归一化后分数，由 normalize 填充
    extra: dict = field(default_factory=dict)

    def dedup_key(self) -> str:
        """去重键：url 优先，否则 平台+标题。"""
        if self.url:
            return f"url:{self.url.strip().lower()}"
        return f"title:{self.platform}:{self.title.strip()}"

    def to_dict(self) -> dict:
        return asdict(self)
