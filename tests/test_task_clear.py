# SPDX-License-Identifier: BUSL-1.1
"""任务清理测试：clear_tasks 按状态/天数删除，不碰 running/queued。"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from core import task_queue


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """隔离 core/db.py 的 SQLite 库到临时文件。"""
    p = tmp_path / "test_tasks.db"
    monkeypatch.setattr(db, "DB_PATH", p)
    return p


def _seed(tmp_db, age_days: float, status: str, tid: str):
    """插入一条指定状态/年龄的任务。"""
    t = db.create_persistent_task(tid, f"任务-{tid}", "video_render")
    db.update_persistent_task(tid, status=status)
    # 回拨 updated_at 到 N 天前
    old_ts = time.time() - age_days * 86400
    c = db.conn()
    c.execute("UPDATE async_tasks SET updated_at=?, created_at=? WHERE id=?",
              (old_ts, old_ts, tid))
    c.commit()
    c.close()
    return tid


def test_clear_failed_old(tmp_db):
    """8 天前的 failed 被删，1 天前的 failed 保留。"""
    _seed(tmp_db, 8, "failed", "t-old-fail")
    _seed(tmp_db, 1, "failed", "t-new-fail")
    r = task_queue.clear_tasks("failed", 7)
    assert r["deleted"] == 1
    assert db.get_persistent_task("t-old-fail") is None
    assert db.get_persistent_task("t-new-fail") is not None


def test_clear_completed_days_options(tmp_db):
    """1/3/5/7 天档位：4 天前的 completed，days=3 删除、days=5 保留。"""
    _seed(tmp_db, 4, "completed", "t-c1")
    r = task_queue.clear_tasks("completed", 5)
    assert r["deleted"] == 0
    r = task_queue.clear_tasks("completed", 3)
    assert r["deleted"] == 1
    assert db.get_persistent_task("t-c1") is None


def test_never_delete_running_or_queued(tmp_db):
    """running/queued 永不删除，即使很老。"""
    _seed(tmp_db, 30, "running", "t-run")
    _seed(tmp_db, 30, "queued", "t-que")
    _seed(tmp_db, 30, "failed", "t-f")
    r = task_queue.clear_tasks("failed", 7)
    assert r["deleted"] == 1
    assert db.get_persistent_task("t-run") is not None
    assert db.get_persistent_task("t-que") is not None


def test_invalid_days_defaults_to_7(tmp_db):
    """非法 days 按 7 处理。"""
    _seed(tmp_db, 8, "failed", "t-x1")
    _seed(tmp_db, 1, "failed", "t-x2")
    r = task_queue.clear_tasks("failed", 99)
    assert r["days"] == 7
    assert r["deleted"] == 1
    r = task_queue.clear_tasks("failed", "abc")
    assert r["days"] == 7


def test_invalid_status_defaults_to_failed(tmp_db):
    """非法 status 按 failed 处理。"""
    _seed(tmp_db, 8, "failed", "t-y1")
    _seed(tmp_db, 8, "completed", "t-y2")
    r = task_queue.clear_tasks("bogus", 7)
    assert r["status"] == "failed"
    assert r["deleted"] == 1
    assert db.get_persistent_task("t-y2") is not None


def test_clear_all_covers_terminal_states(tmp_db):
    """all 清理全部终态（completed/failed/cancelled/interrupted）。"""
    _seed(tmp_db, 10, "completed", "t-a1")
    _seed(tmp_db, 10, "failed", "t-a2")
    _seed(tmp_db, 10, "cancelled", "t-a3")
    _seed(tmp_db, 10, "interrupted", "t-a4")
    _seed(tmp_db, 10, "running", "t-a5")
    r = task_queue.clear_tasks("all", 7)
    assert r["deleted"] == 4
    assert db.get_persistent_task("t-a5") is not None


def test_memory_snapshot_cleaned(tmp_db):
    """内存中的终态任务快照同步清理。"""
    task = task_queue._global_task_manager.submit(
        "mem-clean", "video_render", lambda: None, params={})
    tid = task.id
    # 等待执行完成（lambda 立即返回）
    time.sleep(0.5)
    t = task_queue._global_task_manager._tasks.get(tid)
    assert t is not None and t.status == "completed"
    # 回拨内存与 DB 时间为 8 天前（submit 已持久化，直接 UPDATE）
    old_ts = time.time() - 8 * 86400
    t.completed_at = old_ts
    t.created_at = old_ts
    c = db.conn()
    c.execute("UPDATE async_tasks SET updated_at=?, created_at=? WHERE id=?",
              (old_ts, old_ts, tid))
    c.commit()
    c.close()
    r = task_queue.clear_tasks("completed", 7)
    assert r["deleted"] == 1
    assert tid not in task_queue._global_task_manager._tasks
    assert db.get_persistent_task(tid) is None
