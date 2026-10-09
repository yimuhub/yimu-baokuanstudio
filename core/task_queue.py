"""轻量级本地异步任务队列与算力解耦引擎 (Task Queue & Compute Decoupler)。

为生图、短剧渲染、视频剪辑、批量配图、TTS 等重型算力任务提供线程安全的异步调度，
支持任务排队、实时百分比进度反馈、主动取消、失败重试与历史追踪。
"""
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from core import db

logger = logging.getLogger(__name__)


@dataclass
class Task:
    id: str
    name: str
    task_type: str
    target_id: str = ""
    status: str = "queued"  # queued, running, completed, failed, cancelled, interrupted
    progress: int = 0       # 0 - 100
    message: str = "任务已提交排队中..."
    params: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    current_step: int = 0
    total_steps: int = 1
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    _cancel_flag: bool = field(default=False, repr=False)

    def update_progress(self, percent: int, msg: str = ""):
        """任务执行中实时汇报进度 (0-100) 并持久化写入数据库。"""
        self.progress = max(0, min(100, int(percent)))
        if msg:
            self.message = msg
        try:
            db.update_persistent_task(self.id, progress=self.progress, message=self.message)
        except Exception as e:
            logger.debug(f"[TaskQueue] 持久化进度失败: {e}")
        logger.debug(f"[Task:{self.id}] 进度: {self.progress}% - {self.message}")

    def checkpoint(self, step: int, total_steps: int = 1, msg: str = ""):
        """记录工业级管道断点快照 (Checkpoint)，便于长耗时断点续跑。"""
        self.current_step = step
        self.total_steps = max(1, total_steps)
        self.progress = max(0, min(100, int((step / self.total_steps) * 100)))
        if msg:
            self.message = msg
        try:
            db.update_persistent_task(self.id, progress=self.progress, message=self.message, current_step=step)
        except Exception as e:
            logger.debug(f"[TaskQueue] 持久化断点快照失败: {e}")

    def is_cancelled(self) -> bool:
        """检查任务是否已被用户请求取消。"""
        return self._cancel_flag

    def cancel(self):
        """标记任务取消并持久化状态。"""
        self._cancel_flag = True
        self.status = "cancelled"
        self.message = "用户已主动取消任务"
        self.completed_at = time.time()
        try:
            db.update_persistent_task(self.id, status="cancelled", message=self.message)
        except Exception as e:
            logger.debug(f"[TaskQueue] 持久化取消状态失败: {e}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_cancel_flag", None)
        d["created_at_fmt"] = datetime.fromtimestamp(self.created_at).strftime("%Y-%m-%d %H:%M:%S")
        d["duration_s"] = round(
            (self.completed_at or time.time()) - (self.started_at or self.created_at), 1
        )
        return d


class TaskManager:
    def __init__(self, max_workers: int = 3):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mediaflow-worker")

    def submit(self, name: str, task_type: str, fn: Callable[..., Any],
               params: Optional[dict] = None, *args, **kwargs) -> Task:
        """提交一个耗时任务到后台线程池执行，并持久化到 SQLite。"""
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        task = Task(
            id=task_id,
            name=name,
            task_type=task_type,
            params=params or {},
            created_at=time.time()
        )
        with self._lock:
            self._tasks[task_id] = task

        # 持久化到 SQLite 数据库
        try:
            target_id = (params or {}).get("draft_id", "")
            db.create_persistent_task(task_id, name, task_type, target_id=target_id, params=params)
        except Exception as e:
            logger.warning(f"[TaskQueue] 初始持久化任务失败: {e}")

        self._executor.submit(self._run_wrapper, task, fn, args, kwargs)
        logger.info(f"[TaskQueue] 提交新任务 [{task_id}] {name} ({task_type})")
        return task

    def _run_wrapper(self, task: Task, fn: Callable, args, kwargs):
        if task.is_cancelled():
            return

        task.status = "running"
        task.started_at = time.time()
        task.message = "任务执行中..."
        try:
            db.update_persistent_task(task.id, status="running", message=task.message)
        except Exception:
            pass

        try:
            # 执行目标函数，并注入 task 实例以便内部打点进度
            res = fn(task, *args, **kwargs) if "task" in fn.__code__.co_varnames else fn(*args, **kwargs)
            if not task.is_cancelled():
                task.status = "completed"
                task.progress = 100
                task.result = res
                task.message = "执行成功完成"
                task.completed_at = time.time()
                try:
                    db.update_persistent_task(task.id, status="completed", progress=100, message=task.message, result=res)
                except Exception:
                    pass
                logger.info(f"[TaskQueue] 任务 [{task.id}] 顺利完成")
        except Exception as e:
            if not task.is_cancelled():
                task.status = "failed"
                task.error = str(e)
                task.message = f"执行异常: {e}"
                task.completed_at = time.time()
                try:
                    db.update_persistent_task(task.id, status="failed", error=str(e), message=task.message)
                except Exception:
                    pass
                logger.error(f"[TaskQueue] 任务 [{task.id}] 失败: {e}", exc_info=True)

    def register_job(self, jid: str, name: str, task_type: str, target_id: str = "",
                     total_steps: int = 1, params: Optional[dict] = None) -> Task:
        """注册一个后台异步任务（如文章生成、改写提升、全域派生、配图、短剧等）到内存与持久化存储。"""
        task = Task(
            id=jid,
            name=name,
            task_type=task_type,
            target_id=target_id,
            status="running",
            progress=5,
            message="任务初始化排队中…",
            params=params or {},
            total_steps=total_steps,
            created_at=time.time(),
            started_at=time.time()
        )
        with self._lock:
            self._tasks[jid] = task

        try:
            db.create_persistent_task(jid, name, task_type, target_id=target_id,
                                      total_steps=total_steps, params=params)
            db.update_persistent_task(jid, status="running", progress=5, message=task.message)
        except Exception as e:
            logger.debug(f"[TaskQueue] 持久化注册任务失败: {e}")
        return task

    def update_job(self, jid: str, *, status: Optional[str] = None,
                   step: Optional[str] = None, progress: Optional[int] = None,
                   result: Optional[Any] = None, error: Optional[str] = None):
        """实时更新任务执行进度、步骤提示或完成结果。"""
        norm_status = status
        if status == "done":
            norm_status = "completed"

        with self._lock:
            t = self._tasks.get(jid)
            if t:
                if norm_status:
                    t.status = norm_status
                if step:
                    t.message = step
                if progress is not None:
                    t.progress = max(0, min(100, int(progress)))
                elif norm_status == "completed":
                    t.progress = 100
                if result is not None:
                    t.result = result
                if error:
                    t.error = error
                if norm_status in ("completed", "failed", "cancelled"):
                    t.completed_at = time.time()

        # 智能预估进度百分比
        calc_progress = progress
        if calc_progress is None and norm_status == "completed":
            calc_progress = 100
        elif calc_progress is None and step:
            s_low = step.lower()
            if any(w in s_low for w in ["完成", "就绪", "成功"]):
                calc_progress = 100
            elif any(w in s_low for w in ["压制", "渲染", "生成", "派生", "改写"]):
                calc_progress = 65
            elif any(w in s_low for w in ["分析", "解构", "读取", "提取"]):
                calc_progress = 25

        try:
            db.update_persistent_task(
                jid,
                status=norm_status,
                progress=calc_progress,
                message=step,
                result=result,
                error=error
            )
        except Exception as e:
            logger.debug(f"[TaskQueue] 同步更新持久化任务状态失败: {e}")

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                return t.to_dict()
        # 从数据库中回捞
        try:
            pt = db.get_persistent_task(task_id)
            if pt:
                pt["created_at_fmt"] = datetime.fromtimestamp(pt["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
                pt["duration_s"] = round(
                    (pt.get("completed_at") or time.time()) - (pt.get("started_at") or pt["created_at"]), 1
                )
                return pt
        except Exception:
            pass
        return None

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                if task.status in ("completed", "failed", "cancelled"):
                    return False
                task.cancel()
                logger.info(f"[TaskQueue] 内存任务 [{task_id}] 已取消")

        # 同步更新 web.admin.JOBS
        try:
            from web import admin
            if hasattr(admin, "JOBS") and task_id in admin.JOBS:
                admin.JOBS[task_id].update(status="failed", step="用户已取消", error="任务已由用户主动取消")
        except Exception:
            pass

        # 数据库取消
        try:
            db.update_persistent_task(task_id, status="cancelled", message="已在持久化队列中取消")
            return True
        except Exception:
            return False

    def list(self, limit: int = 50, active_only: bool = False) -> List[dict]:
        """全景聚合任务列表：聚合持久化数据库、内存任务队列以及全局 JOBS。"""
        db_tasks = db.list_persistent_tasks(limit=limit)
        active_mem = {}
        with self._lock:
            for tid, t in self._tasks.items():
                active_mem[tid] = t.to_dict()

        # 动态探测 web.admin.JOBS 中的任务
        try:
            from web import admin
            if hasattr(admin, "JOBS"):
                for jid, job in admin.JOBS.items():
                    if jid not in active_mem:
                        st = job.get("status", "running")
                        if st == "done":
                            st = "completed"
                        step = job.get("step", "")
                        pct = 100 if st == "completed" else (15 if "排队" in step else 60)
                        
                        # 智能推导任务类型和名称
                        t_name = job.get("name") or "异步处理任务"
                        t_type = job.get("task_type") or "general_task"
                        if jid.startswith("fiss-"):
                            t_type = "omni_fission"
                            t_name = t_name if t_name != "异步处理任务" else "全域五端矩阵裂变"
                        elif jid.startswith("derive-"):
                            t_type = "omni_derive"
                            t_name = t_name if t_name != "异步处理任务" else "母稿驱动全域派生"
                        elif jid.startswith("upg-") or "改写" in step:
                            t_type = "ai_rewrite"
                            t_name = t_name if t_name != "异步处理任务" else "AI 深度改写提升"
                        elif "排版" in step:
                            t_type = "article_layout"
                            t_name = t_name if t_name != "异步处理任务" else "智能排版美化"
                        elif "配图" in step or "生图" in step:
                            t_type = "image_gen"
                            t_name = t_name if t_name != "异步处理任务" else "AI 智能生图配图"
                        elif "短剧" in step or "视频" in step:
                            t_type = "video_render"
                            t_name = t_name if t_name != "异步处理任务" else "视频与短剧渲染"
                        elif "写作" in step:
                            t_type = "article_gen"
                            t_name = t_name if t_name != "异步处理任务" else "爆款文章智能生成"

                        active_mem[jid] = {
                            "id": jid,
                            "name": t_name,
                            "task_type": t_type,
                            "target_id": job.get("target_id") or "",
                            "status": st,
                            "progress": pct,
                            "message": step or "处理中...",
                            "result": job.get("result"),
                            "error": job.get("error"),
                            "created_at": job.get("created_at", time.time()),
                            "created_at_fmt": datetime.fromtimestamp(job.get("created_at", time.time())).strftime("%Y-%m-%d %H:%M:%S"),
                            "duration_s": round(time.time() - job.get("created_at", time.time()), 1),
                        }
        except Exception as e:
            logger.debug(f"[TaskQueue] 聚合 JOBS 异常: {e}")

        merged = []
        seen = set()

        # 计算今天 00:00:00 对应的时间戳（当天分界线）
        now_dt = datetime.now()
        start_of_today = datetime(now_dt.year, now_dt.month, now_dt.day).timestamp()

        # 优先加入内存活跃任务
        for tid, tdict in active_mem.items():
            st = tdict.get("status")
            c_time = tdict.get("created_at", 0)
            
            # 若要求只查活跃中
            if active_only and st not in ("queued", "running"):
                continue
            
            # 规则：已完成的任务只保留当天的任务，超越当天的已完成任务自动归档不展示在监控列表中
            if st in ("completed", "done") and c_time < start_of_today:
                continue

            merged.append(tdict)
            seen.add(tid)

        # 补全历史持久化任务
        for pt in db_tasks:
            tid = pt["id"]
            if tid in seen:
                continue
            st = pt.get("status")
            c_time = pt.get("created_at", 0)

            if active_only and st not in ("queued", "running"):
                continue

            # 规则：已完成的任务只保留当天的任务，超越当天的已完成任务自动归档不展示在监控列表中
            if st in ("completed", "done") and c_time < start_of_today:
                continue

            pt["created_at_fmt"] = datetime.fromtimestamp(c_time).strftime("%Y-%m-%d %H:%M:%S") if c_time else ""
            pt["duration_s"] = round(
                (pt.get("completed_at") or time.time()) - (pt.get("started_at") or pt["created_at"]), 1
            )
            merged.append(pt)
            seen.add(tid)

        merged.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return merged[:limit]


# 全局单例管理器
_global_task_manager = TaskManager(max_workers=4)


def get_task_manager() -> TaskManager:
    return _global_task_manager


def register_job(jid: str, name: str, task_type: str, target_id: str = "",
                 total_steps: int = 1, params: Optional[dict] = None) -> Task:
    return _global_task_manager.register_job(jid, name, task_type, target_id=target_id,
                                            total_steps=total_steps, params=params)


def update_job(jid: str, *, status: Optional[str] = None,
               step: Optional[str] = None, progress: Optional[int] = None,
               result: Optional[Any] = None, error: Optional[str] = None):
    return _global_task_manager.update_job(jid, status=status, step=step,
                                          progress=progress, result=result, error=error)


def submit_task(name: str, task_type: str, fn: Callable[..., Any],
                params: Optional[dict] = None, *args, **kwargs) -> Task:
    return _global_task_manager.submit(name, task_type, fn, params=params, *args, **kwargs)


def get_task(task_id: str) -> Optional[dict]:
    return _global_task_manager.get(task_id)


def cancel_task(task_id: str) -> bool:
    return _global_task_manager.cancel(task_id)


def list_tasks(limit: int = 40, active_only: bool = False) -> List[dict]:
    return _global_task_manager.list(limit=limit, active_only=active_only)


# 终态（可安全清理），running/queued 永不删除
_TERMINAL_STATUSES = ("completed", "failed", "cancelled", "interrupted")

_STATUS_GROUPS = {
    "failed": ("failed",),
    "completed": ("completed",),
    "all": ("completed", "failed", "cancelled", "interrupted"),
}


def clear_tasks(status_filter: str = "failed", days: int = 7) -> dict:
    """清理指定状态且超过 N 天未更新的任务。

    status_filter: failed / completed / all（all=全部终态）
    days: 仅允许 1/3/5/7，其他值按 7 处理
    running/queued 状态的任务永不删除。
    返回 {"deleted": N, "status": ..., "days": ...}
    """
    status_filter = (status_filter or "failed").strip().lower()
    if status_filter not in _STATUS_GROUPS:
        status_filter = "failed"
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 7
    if days not in (1, 3, 5, 7):
        days = 7

    cutoff = time.time() - days * 86400
    statuses = list(_STATUS_GROUPS[status_filter])

    deleted = 0
    try:
        deleted = db.delete_old_tasks(statuses, cutoff)
    except Exception as e:
        logger.warning(f"[TaskQueue] 清理任务 DB 删除失败: {e}")

    # 同步清理内存中的终态任务快照（仅终态，不碰 running/queued）
    try:
        with _global_task_manager._lock:
            stale_ids = [
                tid for tid, t in _global_task_manager._tasks.items()
                if t.status in _TERMINAL_STATUSES
                and (t.completed_at or t.created_at or 0) < cutoff
            ]
            for tid in stale_ids:
                _global_task_manager._tasks.pop(tid, None)
    except Exception as e:
        logger.warning(f"[TaskQueue] 清理任务内存快照失败: {e}")

    logger.info(f"[TaskQueue] 已清理 {deleted} 个 {status_filter} 任务（{days} 天前）")
    return {"deleted": deleted, "status": status_filter, "days": days}

