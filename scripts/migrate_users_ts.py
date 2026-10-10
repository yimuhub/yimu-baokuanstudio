# SPDX-License-Identifier: BUSL-1.1
"""V8/P0-A：把历史以 Unix 时间戳（REAL）落库的时间列洗成 ISO-8601 字符串。

背景
----
``users`` 等表被 V6（裸 sqlite3，``created_at REAL``）与 V7（ORM，ISO 字符串）
双层共用，历史数据里时间列混存 Unix 秒 float 与 ISO 字符串。ORM 的
``FlexibleDateTime``（studio/flex_datetime.py）读侧已能兼容两种编码，不再 500；
但排序（``ORDER BY created_at``）在 SQLite 里对 REAL 与 TEXT 混存按类型优先级
（TEXT < REAL < ...）分组，float 行会整块排在 ISO 行之后，时间序被破坏。

本脚本做一次性规范化：把所有「数值型」时间列值转成 UTC ISO-8601，
让排序语义正确、编码全表统一。

幂等 & 安全
----------
- 只对「能被 float() 解析且量级像 unix 秒（1e8 < v < 4e9）」的值改写，
  已是 ISO 字符串的跳过 → 重复运行无副作用。
- 仅改 users 表的时间列（P0 主因表）；其它表如需同类处理按需追加。
- 运行前请自行备份数据库（铁律）。停服务状态下执行最稳妥。

用法
----
    .venv/bin/python scripts/migrate_users_ts.py
    # 可选：YIMU_DB=data/mediaflow.db 指定库文件（默认自动探测 data/ 下）
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
# P0 主因表的时间列（users 被 V6/V7 双层共用的列）
_TS_COLUMNS = ("created_at", "last_login")
# Unix 秒合理区间（约 2001-09 ~ 2056-05），避免误伤小数字
_MIN, _MAX = 1e8, 4e9


def _candidate_db_files() -> list[Path]:
    """候选库文件：环境变量优先，其次 data/ 下所有 *.db。"""
    env = os.environ.get("YIMU_DB", "").strip()
    if env:
        return [Path(env)]
    return sorted(DATA_DIR.glob("*.db"))


def _to_iso(value) -> str | None:
    """数值型时间值 → UTC ISO 字符串；非数值或超区返回 None（不改）。"""
    if value is None:
        return None
    if isinstance(value, str):
        # 已是字符串：若是纯数字字符串也转，否则（ISO）保持
        s = value.strip()
        try:
            f = float(s)
        except ValueError:
            return None
    else:
        f = float(value)
    if not (_MIN < f < _MAX):
        return None
    return datetime.fromtimestamp(f, tz=timezone.utc).isoformat()


def migrate_one(db_path: Path) -> int:
    """规范化单个库文件的 users 时间列，返回改写行数。"""
    if not db_path.exists():
        print(f"  · {db_path.name}: 不存在，跳过")
        return 0
    if not db_path.is_file():
        return 0
    con = sqlite3.connect(str(db_path))
    try:
        # 确认 users 表存在且有时间列
        cols = {r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()}
        if not cols:
            print(f"  · {db_path.name}: 无 users 表，跳过")
            return 0
        rows = con.execute("SELECT id FROM users").fetchall()
        changed = 0
        for (uid,) in rows:
            for col in _TS_COLUMNS:
                if col not in cols:
                    continue
                val = con.execute(f"SELECT {col} FROM users WHERE id=?", (uid,)).fetchone()[0]
                iso = _to_iso(val)
                if iso is not None:
                    con.execute(f"UPDATE users SET {col}=? WHERE id=?", (iso, uid))
                    changed += 1
        con.commit()
        print(f"  ✓ {db_path.name}: 改写 {changed} 处时间值（users {len(rows)} 行）")
        return changed
    finally:
        con.close()


def main() -> int:
    print("V8/P0-A users 时间列规范化（float→ISO-8601 UTC）")
    files = _candidate_db_files()
    if not files:
        print("  · 未找到候选库文件（data/*.db），无可操作；如库在别处请用 YIMU_DB=路径 指定。")
        return 0
    total = 0
    for f in files:
        total += migrate_one(f)
    print(f"完成：共改写 {total} 处。可安全重跑（幂等，已规范化的值会被跳过）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
