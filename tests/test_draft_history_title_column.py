# SPDX-License-Identifier: BUSL-1.1
"""回归：draft_history 缺 title 列时，初始化迁移必须自愈。

历史根因：core/db.py 的 add_history 会往 draft_history 写 title 列，但建表语句是后加的，
旧库（尤其由 studio 侧 SQLAlchemy 建出的库）draft_history 只有 version、没有 title，
CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，于是「外科手术定点精修 / 批量切除」一调用
add_history 就 500（no column named title）。同时 studio 侧把 version 建为 NOT NULL，
而 add_history 不写 version，因此补完 title 后会紧接着报 NOT NULL constraint failed。

本测试覆盖两套真实 schema：
  - studio 风格：有 version(NOT NULL)、无 title（最常见的故障库）
  - core 风格：无 version、无 title（core 侧建表分支）
并验证：① conn() 初始化后 draft_history 自动补齐 title；② add_history 不再抛错且能读写 title。
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

import core.db as db


@pytest.fixture
def isolated_db(monkeypatch):
    """把 core.db 指向一个全新的临时库，并清掉初始化缓存，确保迁移重新执行。"""
    tmp = Path(tempfile.mkdtemp()) / "heal.db"
    monkeypatch.setattr(db, "DB_PATH", tmp)
    db._INITIALIZED_DB_PATHS.clear()
    yield tmp
    db._INITIALIZED_DB_PATHS.clear()


def _recreate_as_studio_style(tmp: Path) -> None:
    """把 draft_history 重建成 studio 风格：有 version(NOT NULL)、无 title。"""
    c = sqlite3.connect(str(tmp))
    c.execute("DROP TABLE IF EXISTS draft_history")
    c.execute(
        """
        CREATE TABLE draft_history (
            id TEXT PRIMARY KEY,
            draft_id TEXT,
            version INTEGER NOT NULL,
            body_md TEXT,
            score REAL,
            created_at REAL,
            tenant_id TEXT DEFAULT 'default'
        )
        """
    )
    c.commit()
    c.close()


def _recreate_as_core_style(tmp: Path) -> None:
    """把 draft_history 重建成 core 侧建表分支：无 version、无 title。"""
    c = sqlite3.connect(str(tmp))
    c.execute("DROP TABLE IF EXISTS draft_history")
    c.execute(
        """
        CREATE TABLE draft_history (
            id TEXT PRIMARY KEY,
            draft_id TEXT,
            created_at REAL,
            body_md TEXT,
            score REAL,
            tenant_id TEXT DEFAULT 'default'
        )
        """
    )
    c.commit()
    c.close()


def test_draft_history_title_column_auto_heals_studio_style(isolated_db):
    tmp = isolated_db
    # 1) 让 core 先把其余表（drafts / tenants / workspaces ...）建齐
    db.conn()
    # 2) 把 draft_history 重建成「studio 风格」（version NOT NULL、无 title）
    _recreate_as_studio_style(tmp)
    cols_before = {r[1] for r in sqlite3.connect(str(tmp)).execute(
        "PRAGMA table_info(draft_history)")}
    assert "title" not in cols_before

    # 3) 重新初始化：迁移应自愈补回 title
    db._INITIALIZED_DB_PATHS.clear()
    db.conn()
    cols_after = {r[1] for r in sqlite3.connect(str(tmp)).execute(
        "PRAGMA table_info(draft_history)")}
    assert "title" in cols_after

    # 4) add_history 在「version NOT NULL」的老库上不再抛错，且能读写 title
    db.add_history("d1", "标题A", "# 正文A", 80.0)
    hist = db.list_history("d1")
    assert len(hist) == 1
    assert hist[0]["title"] == "标题A"


def test_add_history_works_without_version_column(isolated_db):
    """core 自建表（无 version 列）也应能写入，覆盖另一套 schema。"""
    tmp = isolated_db
    db.conn()
    _recreate_as_core_style(tmp)
    db._INITIALIZED_DB_PATHS.clear()
    db.conn()
    db.add_history("d2", "标题B", "# 正文B", 85.0)
    assert db.list_history("d2")[0]["title"] == "标题B"
