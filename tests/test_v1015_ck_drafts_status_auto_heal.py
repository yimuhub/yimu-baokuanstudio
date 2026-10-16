# SPDX-License-Identifier: BUSL-1.1
"""测试 v10.1.5 drafts 表 ck_drafts_status CHECK 约束自动无损自愈机制。

场景：
用户在升级 v10.1.5 之前，本地 Windows 机器上的 data/mediaflow.db 在历史版本
已经被创建为带有 `CONSTRAINT ck_drafts_status CHECK (status IN ('draft','pending_review','published'))` 的 SQLite 表。
当使用极简模式创作时，core/db.py:add_draft 会尝试插入 status='preview' 的新草稿，
SQLite 底层直接抛出 `sqlite3.IntegrityError: CHECK constraint failed: ck_drafts_status`。

本测试验证：
1. 真实模拟老版本带 CHECK 约束的数据库；
2. 验证原有表会拒绝 'preview' 状态；
3. 系统通过 core.db 或 studio.db 启动自愈后，无损迁移老数据并彻底解除该约束；
4. 历史草稿 100% 完整保留，新草稿成功入库；
5. 极简模式创作与状态流转（preview / approved / published / failed）畅行无阻。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from core import db as core_db
from studio import db as studio_db


def _create_legacy_db_with_ck_constraint(db_path: Path) -> None:
    """创建模拟老版本带有 ck_drafts_status 严格约束的 SQLite 数据库。"""
    c = sqlite3.connect(db_path)
    c.execute("""
    CREATE TABLE users (
        id VARCHAR(32) PRIMARY KEY,
        username VARCHAR(64) NOT NULL,
        password_hash VARCHAR(256) NOT NULL,
        salt VARCHAR(64) NOT NULL
    );
    """)
    c.execute("INSERT INTO users VALUES ('u-admin', 'admin', 'hash', 'salt');")
    c.execute("""
    CREATE TABLE drafts (
        id VARCHAR(32) NOT NULL,
        user_id VARCHAR(32) DEFAULT '' NOT NULL,
        title VARCHAR(256) DEFAULT '' NOT NULL,
        body_md TEXT DEFAULT '' NOT NULL,
        platform VARCHAR(32) DEFAULT '' NOT NULL,
        status VARCHAR(16) DEFAULT 'draft' NOT NULL,
        score FLOAT,
        needs_review INTEGER DEFAULT 0 NOT NULL,
        guard_reason TEXT DEFAULT '' NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        tenant_id VARCHAR(32) DEFAULT 'default' NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_drafts_status CHECK (status IN ('draft', 'pending_review', 'published')),
        FOREIGN KEY(user_id) REFERENCES users (id)
    );
    """)
    c.execute("CREATE INDEX ix_drafts_tenant_status ON drafts (tenant_id, status);")

    # 插入 3 条老版本草稿
    for i in range(1, 4):
        c.execute(
            "INSERT INTO drafts (id, title, body_md, status, score) VALUES (?, ?, ?, ?, ?)",
            (f"legacy-d{i}", f"老草稿标题 {i}", f"老草稿正文内容 {i}", "draft", 90.0 + i),
        )
    c.commit()
    c.close()


def test_legacy_db_fails_without_healing(tmp_path: Path):
    """验证未自愈前，SQLite 确实会因 ck_drafts_status 崩溃。"""
    db_file = tmp_path / "legacy.db"
    _create_legacy_db_with_ck_constraint(db_file)

    c = sqlite3.connect(db_file)
    with pytest.raises(sqlite3.IntegrityError) as exc_info:
        c.execute(
            "INSERT INTO drafts (id, title, status) VALUES ('new-1', '测试草稿', 'preview')"
        )
    assert "ck_drafts_status" in str(exc_info.value)
    c.close()


def test_core_db_conn_and_add_draft_auto_heals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """验证 core.db 建连与 add_draft 能够全自动、无损自愈，彻底杜绝该报错。"""
    db_file = tmp_path / "mediaflow_test.db"
    _create_legacy_db_with_ck_constraint(db_file)

    # 替换 core_db.DB_PATH 和缓存
    monkeypatch.setattr(core_db, "DB_PATH", db_file)
    monkeypatch.setattr(core_db, "_INITIALIZED_DB_PATHS", {})

    # 调用 core_db.add_draft（极简模式创作入口）
    new_draft = core_db.add_draft(
        topic_id="tp-101",
        title="极简模式爆款草稿",
        body_md="# 爆款标题\n这是一篇极简模式生成的文章",
        platforms=["wechat_mp", "xhs"],
        user_id="u-admin",
    )

    # 1. 验证新草稿正常生成且 status 为 preview
    assert new_draft["title"] == "极简模式爆款草稿"
    assert new_draft["status"] == "preview"

    # 2. 验证存量老草稿 100% 完整保留
    c = sqlite3.connect(db_file)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM drafts ORDER BY id").fetchall()
    row_ids = [r["id"] for r in rows]
    assert "legacy-d1" in row_ids
    assert "legacy-d2" in row_ids
    assert "legacy-d3" in row_ids
    assert new_draft["id"] in row_ids

    # 3. 验证 SQLite 官方 DDL 中不再残留 ck_drafts_status
    table_sql = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='drafts'"
    ).fetchone()["sql"]
    assert "ck_drafts_status" not in table_sql

    # 4. 验证后续状态更新（approved / published / failed 等）全部畅行无阻
    core_db.set_draft_status(new_draft["id"], "approved")
    updated = core_db.get_draft(new_draft["id"])
    assert updated["status"] == "approved"

    c.close()


def test_studio_init_db_auto_heals_legacy_sqlite(tmp_path: Path):
    """验证 studio.db.init_db 在老版本 SQLite 库上也能自动自愈 ck_drafts_status。"""
    db_file = tmp_path / "studio_legacy.db"
    _create_legacy_db_with_ck_constraint(db_file)

    engine = studio_db.get_engine(f"sqlite:///{db_file}")
    studio_db.init_db(engine)

    # 验证自愈后可直接插入 preview 状态草稿
    c = sqlite3.connect(db_file)
    c.execute(
        "INSERT INTO drafts (id, title, status) VALUES ('d-studio-test', 'Studio测试', 'preview')"
    )
    c.commit()
    row = c.execute("SELECT status FROM drafts WHERE id='d-studio-test'").fetchone()
    assert row[0] == "preview"
    c.close()


def test_legacy_db_without_tenant_id_column_auto_heals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """验证历史极简表（缺失 tenant_id、platform 等列）也能完美无损自愈。"""
    db_file = tmp_path / "mediaflow_no_tenant.db"
    c = sqlite3.connect(db_file)
    # 创建极度精简的老表（完全没有 tenant_id、platform 等列）
    c.execute("""
    CREATE TABLE drafts (
        id TEXT PRIMARY KEY,
        title TEXT,
        body_md TEXT,
        status TEXT DEFAULT 'draft',
        CONSTRAINT ck_drafts_status CHECK (status IN ('draft', 'pending_review', 'published'))
    );
    """)
    c.execute("INSERT INTO drafts VALUES ('legacy-bare-1', '极简老草稿', '老正文', 'draft');")
    c.commit()
    c.close()

    monkeypatch.setattr(core_db, "DB_PATH", db_file)
    monkeypatch.setattr(core_db, "_INITIALIZED_DB_PATHS", {})

    # 通过 conn() 建连与 add_draft 写入 preview
    draft = core_db.add_draft(
        topic_id="",
        title="无 tenant_id 老库自愈后新稿",
        body_md="正文内容",
        platforms=["wechat_mp"],
        user_id="u-admin",
    )
    assert draft["status"] == "preview"

    # 验证老数据完整保留
    c = sqlite3.connect(db_file)
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT * FROM drafts WHERE id='legacy-bare-1'").fetchone()
    assert row is not None
    assert row["title"] == "极简老草稿"
    assert row["status"] == "draft"

    # 验证新字段均已补齐
    assert "tenant_id" in row.keys()
    assert row["tenant_id"] == "default"
    assert "platform" in row.keys()
    c.close()


def test_auto_heal_all_sqlite_databases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """验证 auto_heal_all_sqlite_databases 会批量扫描并自愈目录下所有 SQLite 库。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core_db, "DATA", data_dir)

    db1 = data_dir / "mediaflow.db"
    db2 = data_dir / "yimu.db"
    _create_legacy_db_with_ck_constraint(db1)
    _create_legacy_db_with_ck_constraint(db2)

    # 执行全局自愈
    core_db.auto_heal_all_sqlite_databases()

    # 验证两个库均已去除 ck_drafts_status
    for db in (db1, db2):
        c = sqlite3.connect(db)
        sql = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='drafts'").fetchone()[0]
        assert "ck_drafts_status" not in sql
        c.execute("INSERT INTO drafts (id, status) VALUES ('test-p', 'preview')")
        c.commit()
        c.close()
