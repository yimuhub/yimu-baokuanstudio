# SPDX-License-Identifier: BUSL-1.1
"""V8/P0-A：兼容历史多编码时间戳的 ORM 时间列类型。

背景
----
``users`` 表被 V6（``core/auth.py``，裸 sqlite3，``created_at REAL``）与
V7（``studio/db_models.py``，SQLAlchemy ORM，``DateTime``）双层共用。
历史写入混过三种编码：Unix 秒 float（``1791556270.4``）、ISO 字符串
（``'2026-10-08 03:21:27'``）。ORM 的 DateTime 结果处理器按
``datetime.fromisoformat`` 解析，命中 float 行直接
``TypeError: fromisoformat: argument must be str`` → 按 created_at 排序的
所有接口 500（/api/admin/users、账单默认用户查询等，实测 15 个测试失败同源）。

设计
----
- ``impl = String``：存储类型声明为 TEXT。
  * SQLite：列实际是 REAL/VARCHAR 混存都能读回原值（SQLite 动态类型），
    且 String 没有 str_to_datetime 结果处理器 → 不再崩溃。
  * PostgreSQL：VARCHAR 存 ISO 字符串，应用层统一写 UTC ISO，字典序=时间序。
- 写侧 ``process_bind_param``：datetime → ISO-8601（UTC 带时区），保证新写入
  永远统一编码（与 V6 层 ``core/auth._iso_now()`` 对齐）。
- 读侧 ``process_result_value``：float/int → fromtimestamp(UTC)；
  ISO 字符串 → fromisoformat（补 UTC 时区）；数字字符串兜底按时间戳解析。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class FlexibleDateTime(TypeDecorator):
    """读时兼容 float 时间戳与 ISO 字符串，写时统一 ISO-8601 UTC。"""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        # int/float：按 unix 秒转 ISO（防御性兜底）
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        # ① 存量 float（REAL 列）/ int
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        s = str(value).strip()
        if not s:
            return None
        # ② ISO-8601 字符串（主流路径）
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        # ③ 纯数字字符串（历史 '1791556270.4' 存成 TEXT 的形态）
        try:
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
