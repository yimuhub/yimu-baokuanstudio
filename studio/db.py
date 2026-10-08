# SPDX-License-Identifier: BUSL-1.1
"""数据库连接与初始化：get_engine / init_db 最小可用实现。

双部署：
- 本地：SQLite，``sqlite:///./data/yimu.db``（文件路径可配置）
- 云端：PostgreSQL，``postgresql+psycopg2://...``（依赖 ``psycopg2-binary``）

模型定义见 ``studio/db_models.py``；设计文档见 ``docs/SCHEMA.md``。
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .db_models import Base


def get_engine(db_url: str, *, echo: bool = False, pool_size: int = 5) -> Engine:
    """根据 db_url 创建 Engine，SQLite / PostgreSQL 双兼容。

    Args:
        db_url: SQLAlchemy 数据库 URL。
            本地示例：``sqlite:///./data/yimu.db``
            云端示例：``postgresql+psycopg2://user:pass@host:5432/yimu``
        echo: 是否打印 SQL（调试用）。
        pool_size: PG 连接池大小；SQLite 不使用连接池参数。
    """
    if db_url.startswith("sqlite"):
        # SQLite：单文件，关闭线程检查以适配 FastAPI 多线程；
        # WAL 模式提升并发读性能（init_db 中设置）。
        return create_engine(
            db_url,
            echo=echo,
            connect_args={"check_same_thread": False},
        )
    return create_engine(db_url, echo=echo, pool_size=pool_size, max_overflow=10)


def init_db(engine: Engine) -> None:
    """建表（幂等）：按 db_models.Base 的元数据创建全部 14 张表。

    说明：
    - 仅用于开发/测试与首次部署；生产环境的 schema 演进
      后续由 Alembic 迁移脚本管理（WS-A 契约冻结后接入）。
    - SQLite 下开启 WAL 模式与外键约束。
    """
    if engine.url.drivername == "sqlite":
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON;")
    Base.metadata.create_all(engine)
    _migrate_missing_columns(engine)


def _migrate_missing_columns(engine: Engine) -> None:
    """旧库列迁移：为已有表补上模型中新增的列（幂等，仅 SQLite）。"""
    if engine.url.drivername != "sqlite":
        return
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.schema import CreateColumn

    insp = sa_inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            try:
                existing = {c["name"] for c in insp.get_columns(table.name)}
            except Exception:
                continue
            for col in table.columns:
                if col.name in existing:
                    continue
                col_sql = str(CreateColumn(col).compile(bind=engine)).strip()
                try:
                    ddl = f"ALTER TABLE {table.name} ADD COLUMN " + col_sql.split("ADD COLUMN", 1)[1].strip()
                except IndexError:
                    ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(dialect=engine.dialect)}"
                try:
                    conn.exec_driver_sql(ddl)
                except Exception:
                    pass  # 列已存在或类型冲突时跳过（幂等）


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    """返回线程安全的 Session 工厂（FastAPI 依赖注入用）。"""
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
