# SPDX-License-Identifier: BUSL-1.1
"""pytest 全局 fixtures：测试数据库隔离与生产库守卫。

⭐ 硬规则（工程文化基线，完整版见 docs/CONVENTIONS.md）：
1. 每个测试 session 使用独立的临时 SQLite 库；``YIMU_TEST_DB`` 环境变量指向它。
2. 任何指向疑似生产库路径的连接请求都会直接抛错退出——测试绝不碰真库。
3. 金丝雀种子数据（tests/seed/）只读；探针只写临时目录。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

# ⭐ 生产库路径标记：命中任一标记即视为生产库，直接拦截。
# 覆盖：本地默认 data/ 目录库、云端生产库名、账本 / runs 产物目录。
_PROD_PATH_MARKERS = (
    "prod",
    "production",
    "生产",
    "主库",
    "data/yimu.db",
    "yimu.db",
    "ledger.db",
    "runs/",
    "runs\\",
)

_TEST_DB_ENV = "YIMU_TEST_DB"


def assert_test_db_isolated(db_path: str) -> str:
    """⭐ 守卫：断言给定路径是测试库而非生产库；否则直接抛错。

    被测代码在打开数据库连接前应调用本函数（或 require_test_db_url）。
    """
    if not db_path:
        raise RuntimeError("数据库路径为空：测试必须显式使用隔离的测试库（见 conftest.db_session）。")
    normalized = str(db_path).lower().replace("\\", "/")
    for marker in _PROD_PATH_MARKERS:
        if marker in normalized:
            raise RuntimeError(
                "⛔ 已拦截：数据库路径疑似生产库（命中标记 %r）：%s\n"
                "测试绝不碰真库。请使用 conftest 提供的 test_db_path / db_url / db_session fixture。"
                % (marker, db_path)
            )
    return db_path


def make_test_db(prefix: str = "yimu_test_") -> tuple[str, str]:
    """在系统临时目录创建一个隔离测试库，返回 (db_path, db_url)。

    供 tests/probes.py 等独立脚本使用；同样受生产库守卫保护。
    """
    fd, db_path = tempfile.mkstemp(prefix=prefix, suffix=".db")
    os.close(fd)
    assert_test_db_isolated(db_path)
    os.environ[_TEST_DB_ENV] = db_path
    return db_path, f"sqlite:///{db_path}"


def require_test_db_url() -> str:
    """供被测代码 / 探针调用：返回测试库 URL；环境未隔离则抛错。"""
    url = os.environ.get(_TEST_DB_ENV, "")
    if not url:
        raise RuntimeError(
            "YIMU_TEST_DB 未设置：测试必须在隔离库上运行，"
            "请先调用 conftest.make_test_db() 或使用 db_url fixture 建库。"
        )
    path = url[len("sqlite:///") :] if url.startswith("sqlite:///") else url
    assert_test_db_isolated(path)
    return url


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """⭐ 每个测试 session 一份独立临时库；YIMU_TEST_DB 环境变量指向它。"""
    db_path = tmp_path_factory.mktemp("yimu_db") / "yimu_test.db"
    assert_test_db_isolated(str(db_path))
    os.environ[_TEST_DB_ENV] = str(db_path)
    return str(db_path)


@pytest.fixture(scope="session")
def db_url(test_db_path):
    """SQLAlchemy 风格的测试库 URL（sqlite:///…）。"""
    assert_test_db_isolated(test_db_path)
    return f"sqlite:///{test_db_path}"


@pytest.fixture()
def db_session(test_db_path, db_url):
    """隔离库会话。

    优先走项目自带的 studio.db（真实 schema，含 init_db 建表）；
    若 studio.db 尚不可用，则退回标准库 sqlite3 连接。
    两种路径都经过生产库守卫。
    """
    assert_test_db_isolated(test_db_path)
    try:
        from sqlalchemy.orm import sessionmaker

        from studio.db import get_engine, init_db
    except ImportError:
        conn = sqlite3.connect(test_db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
        return
    engine = get_engine(db_url)
    init_db(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
