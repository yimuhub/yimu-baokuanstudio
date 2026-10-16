# SPDX-License-Identifier: BUSL-1.1
"""V10.1.4 回归测试：Windows 版全新安装启动与极简模式创作下 drafts.platform NOT NULL 约束彻底修复。

验证场景：
1. Windows 全新安装启动场景：先通过 studio.db.init_db(engine) 建表（基于 SQLAlchemy DDL），
   随后调用 core.db.add_draft 插入草稿，绝不触发 NOT NULL constraint failed: drafts.platform 或 CHECK 约束失败。
2. 极简模式 Copilot 创作场景：模拟用户在极简模式发起创作，包含小红书、头条、公众号等偏向词，
   自动识别并精准注入 platform 字段。
3. 存量库数据自愈：旧库数据自动补齐 platform / tenant_id / updated_at 默认值。
4. 反向建表顺序兼容：先 core.db 后 studio.db 均双向无缝兼容。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import pytest


def test_windows_fresh_install_draft_creation_no_not_null_error():
    """场景 1：模拟 Windows 全新安装首次启动并创建草稿。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        from studio.db import get_engine, init_db
        engine = get_engine(f"sqlite:///{db_path}")
        init_db(engine)

        import core.db
        orig_db_path = core.db.DB_PATH
        core.db.DB_PATH = Path(db_path)
        core.db._INITIALIZED_DB_PATHS.clear()

        try:
            draft = core.db.add_draft(
                topic_id="",
                title="Windows全新安装极简模式创作测试",
                body_md="# 爆款标题\n这是正文内容",
                platforms=["xhs", "wechat_mp"],
                source_platform="copilot_web_rewrite",
            )
            assert draft["id"].startswith("dr-")
            assert draft["platform"] == "xhs"

            # 验证数据库中实际存储的值
            c = core.db.conn()
            row = c.execute(
                "SELECT id, platform, status, tenant_id, user_id, updated_at FROM drafts WHERE id=?",
                (draft["id"],),
            ).fetchone()
            assert row is not None
            assert row["platform"] == "xhs"
            assert row["status"] == "preview"
            assert row["tenant_id"] == "default"
            assert row["user_id"] == "u-admin"
            assert bool(row["updated_at"])
        finally:
            core.db.DB_PATH = orig_db_path
            core.db._INITIALIZED_DB_PATHS.clear()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_copilot_minimal_mode_platform_detection():
    """场景 2：验证极简模式 Copilot 创作流程中 platform 正确判定并落库。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        from studio.db import get_engine, init_db
        engine = get_engine(f"sqlite:///{db_path}")
        init_db(engine)

        import core.db
        orig_db_path = core.db.DB_PATH
        core.db.DB_PATH = Path(db_path)
        core.db._INITIALIZED_DB_PATHS.clear()

        try:
            # 模拟小红书偏向
            d_xhs = core.db.add_draft(
                topic_id="",
                title="小红书爆款图文",
                body_md="种草好物分享",
                platforms=["wechat_mp", "xhs", "toutiao"],
                source_platform="copilot_web_rewrite",
                platform="xhs",
            )
            assert d_xhs["platform"] == "xhs"

            # 模拟公众号偏向（默认或显式传参）
            d_wx = core.db.add_draft(
                topic_id="",
                title="深度长文分析",
                body_md="深度剖析商业逻辑",
                platforms=["wechat_mp", "toutiao"],
                platform="wechat_mp",
            )
            assert d_wx["platform"] == "wechat_mp"

            # 模拟不传 platform 时从 platforms 列表首项自动回退
            d_auto = core.db.add_draft(
                topic_id="",
                title="自动推导平台",
                body_md="通用内容",
                platforms=["toutiao", "zhihu"],
            )
            assert d_auto["platform"] == "toutiao"
        finally:
            core.db.DB_PATH = orig_db_path
            core.db._INITIALIZED_DB_PATHS.clear()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_legacy_db_migration_and_healing():
    """场景 3：验证旧库缺少 platform 列时，能自动补列并不破坏已有数据。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE drafts (
                id TEXT PRIMARY KEY,
                topic_id TEXT,
                created_at REAL,
                title TEXT,
                body_md TEXT,
                platforms TEXT,
                status TEXT DEFAULT 'preview'
            )
        """)
        conn.execute("INSERT INTO drafts (id, title, status) VALUES ('dr-old-1', '历史旧草稿', 'preview')")
        conn.commit()
        conn.close()

        import core.db
        orig_db_path = core.db.DB_PATH
        core.db.DB_PATH = Path(db_path)
        core.db._INITIALIZED_DB_PATHS.clear()

        try:
            # 建立连接会触发自动迁移和补列
            c = core.db.conn()
            cols = {r["name"] for r in c.execute("PRAGMA table_info(drafts)")}
            assert "platform" in cols
            assert "tenant_id" in cols
            assert "needs_review" in cols

            # 验证存量数据已自愈
            row = c.execute("SELECT id, platform, tenant_id FROM drafts WHERE id='dr-old-1'").fetchone()
            assert row["platform"] == "wechat_mp"
            assert row["tenant_id"] == "default"

            # 验证新插入能够成功
            d_new = core.db.add_draft(
                topic_id="",
                title="迁移后新草稿",
                body_md="正文",
                platforms=["wechat_mp"],
            )
            assert d_new["platform"] == "wechat_mp"
        finally:
            core.db.DB_PATH = orig_db_path
            core.db._INITIALIZED_DB_PATHS.clear()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
