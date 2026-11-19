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
    owner: str = ""         # 提交该任务的用户 id（/api/tasks 按用户隔离用）
    _cancel_flag: bool = field(default=False, repr=False)
    _cancel_callbacks: List[Callable[[], Any]] = field(default_factory=list, repr=False)

    def update_progress(self, percent: int, msg: str = ""):
        """任务执行中实时汇报进度 (0-100) 并持久化写入数据库。"""
        self.progress = max(0, min(100, int(percent)))
        if msg:
            self.message = msg
        try:
            db.update_persistent_task(self.id, progress=self.progress, message=self.message)
        except Exception as e:
            # why：进度写库失败原来只记 debug——断电/库锁住时前端会看到进度
            # 永远不动却查不到原因；warning 才能进导出日志（v15.9.8 整改）。
            logger.warning(f"[TaskQueue] 持久化进度失败: {e}")
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
            logger.warning(f"[TaskQueue] 持久化断点快照失败: {e}")

    def is_cancelled(self) -> bool:
        """检查任务是否已被用户请求取消。"""
        return self._cancel_flag

    def register_cancel(self, cb: Callable[[], Any]) -> None:
        """注册「取消联动」回调（如 video_native 注册的终止 ffmpeg 进程）。

        回调在 cancel() 被调用的线程里同步执行，必须自己兜异常、快速返回。
        """
        self._cancel_callbacks.append(cb)

    def cancel(self):
        """标记任务取消并持久化状态，同时触发已注册的取消联动回调。"""
        self._cancel_flag = True
        self.status = "cancelled"
        self.message = "用户已主动取消任务"
        self.completed_at = time.time()
        for cb in list(self._cancel_callbacks):
            try:
                cb()
            except Exception as e:
                # 联动失败不阻断取消本身：状态位已置位，轮询型实现会自行退出
                logger.warning(f"[TaskQueue] 任务 [{self.id}] 取消联动回调失败: {e}")
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


def _params_with_owner(params: Optional[dict], owner: str) -> Optional[dict]:
    """把任务归属者塞进持久化 params（``_owner`` 键）。

    why 不加 schema 列：async_tasks 表没有 owner 列，历史库要保证零迁移可用；
    塞进 params_json 读取端（get/list）再还原成顶层 ``owner`` 字段。
    """
    if not owner:
        return params
    merged = dict(params or {})
    merged.setdefault("_owner", str(owner))
    return merged


def _owner_from_params(pt: Optional[dict]) -> str:
    """从持久化任务行的 params_json 还原 owner（无则空串）。"""
    if not isinstance(pt, dict):
        return ""
    owner = pt.get("owner")
    if owner:
        return str(owner)
    params = pt.get("params")
    if isinstance(params, dict):
        return str(params.get("_owner") or "")
    return ""


class TaskManager:
    def __init__(self, max_workers: int = 3):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mediaflow-worker")

    def submit(self, name: str, task_type: str, fn: Callable[..., Any],
               params: Optional[dict] = None, *args, owner: str = "", **kwargs) -> Task:
        """提交一个耗时任务到后台线程池执行，并持久化到 SQLite。"""
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        task = Task(
            id=task_id,
            name=name,
            task_type=task_type,
            params=params or {},
            created_at=time.time(),
            owner=owner,
        )
        with self._lock:
            self._tasks[task_id] = task

        # 持久化到 SQLite 数据库
        try:
            target_id = (params or {}).get("draft_id", "")
            db.create_persistent_task(task_id, name, task_type, target_id=target_id,
                                      params=_params_with_owner(params, owner))
        except Exception as e:
            logger.warning(f"[TaskQueue] 初始持久化任务失败: {e}")

        self._executor.submit(self._run_wrapper, task, fn, args, kwargs)
        logger.info(f"[TaskQueue] 提交新任务 [{task_id}] {name} ({task_type})")
        return task

    @staticmethod
    def _invoke_fn(fn: Callable, task: Task, args, kwargs):
        """执行任务函数并尽力注入 task 实例（供内部打点进度/响应取消）。

        why 不再用 ``"task" in fn.__code__.co_varnames`` 字节码探测：
        ``functools.partial``、普通可调用对象没有 ``__code__``，原实现会直接
        AttributeError 让任务整单失败。改为——能拿到 __code__（普通函数/lambda）
        时沿用既有判定与「task 作第一个位置参数」的历史约定；拿不到时按
        ``task=`` 关键字试探，签名不收 task 的 TypeError 再回退无注入调用。
        """
        target = getattr(fn, "func", None) or fn  # functools.partial 取底层函数
        code = getattr(target, "__code__", None)
        if code is not None:
            if "task" in code.co_varnames:
                return fn(task, *args, **kwargs)
            return fn(*args, **kwargs)
        try:
            return fn(task=task, *args, **kwargs)
        except TypeError:
            # 该可调用对象不接收 task 形参：去掉注入按原参数调用
            return fn(*args, **kwargs)

    def _run_wrapper(self, task: Task, fn: Callable, args, kwargs):
        if task.is_cancelled():
            return

        task.status = "running"
        task.started_at = time.time()
        task.message = "任务执行中..."
        try:
            db.update_persistent_task(task.id, status="running", message=task.message)
        except Exception as e:
            logger.warning(f"[TaskQueue] 持久化 running 状态失败: {e}")

        try:
            # 执行目标函数，并注入 task 实例以便内部打点进度
            res = self._invoke_fn(fn, task, args, kwargs)
            if not task.is_cancelled():
                task.status = "completed"
                task.progress = 100
                task.result = res
                task.message = "执行成功完成"
                task.completed_at = time.time()
                try:
                    db.update_persistent_task(task.id, status="completed", progress=100, message=task.message, result=res)
                except Exception as e:
                    logger.warning(f"[TaskQueue] 持久化完成状态失败: {e}")
                logger.info(f"[TaskQueue] 任务 [{task.id}] 顺利完成")
        except Exception as e:
            if not task.is_cancelled():
                task.status = "failed"
                task.error = str(e)
                task.message = f"执行异常: {e}"
                task.completed_at = time.time()
                try:
                    db.update_persistent_task(task.id, status="failed", error=str(e), message=task.message)
                except Exception as exc:
                    logger.warning(f"[TaskQueue] 持久化失败状态异常: {exc}")
                logger.error(f"[TaskQueue] 任务 [{task.id}] 失败: {e}", exc_info=True)

    def register_job(self, jid: str, name: str, task_type: str, target_id: str = "",
                     total_steps: int = 1, params: Optional[dict] = None,
                     owner: str = "") -> Task:
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
            started_at=time.time(),
            owner=str(owner or ""),
        )
        with self._lock:
            self._tasks[jid] = task

        try:
            db.create_persistent_task(jid, name, task_type, target_id=target_id,
                                      total_steps=total_steps,
                                      params=_params_with_owner(params, owner))
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
                pt["owner"] = _owner_from_params(pt)
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
        # v15.9.8：用户主动取消不再写成 failed——取消不是失败，混进失败统计
        # 会污染「失败率」看板，也会触发「任务失败」类的用户通知。
        try:
            from web import admin
            if hasattr(admin, "JOBS") and task_id in admin.JOBS:
                admin.JOBS[task_id].update(status="cancelled", step="用户已取消", error="任务已由用户主动取消")
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
                            "owner": job.get("owner") or "",
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
            pt["owner"] = _owner_from_params(pt)
            merged.append(pt)
            seen.add(tid)

        merged.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return merged[:limit]


# 全局单例管理器
_global_task_manager = TaskManager(max_workers=4)




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
                params: Optional[dict] = None, *args, owner: str = "", **kwargs) -> Task:
    return _global_task_manager.submit(name, task_type, fn, params=params, owner=owner, *args, **kwargs)


def get_task(task_id: str) -> Optional[dict]:
    return _global_task_manager.get(task_id)


def cancel_task(task_id: str) -> bool:
    return _global_task_manager.cancel(task_id)


def list_tasks(limit: int = 40, active_only: bool = False) -> List[dict]:
    return _global_task_manager.list(limit=limit, active_only=active_only)


# ---------------------------------------------------------------------------
# 用户后台任务统一收口（v15.9.8）
# ---------------------------------------------------------------------------
#
# why 收拢：此前 drafts.py / media.py 等 5 处直接
# ``asyncio.get_event_loop().run_in_executor(None, ...)`` fire-and-forget：
#   1. 跑在 asyncio 默认池（无界），一个用户可无限堆任务把线程撑爆；
#   2. web.admin.JOBS 只进不出，常驻进程内存缓慢泄漏；
#   3. 与 TaskManager 持久化队列互不感知，无法取消、无法按用户隔离。
# 统一走 :func:`spawn_user_task`：独立受界线程池 + 每用户并发闸门 +
# JOBS 过期清理 + owner 归属。
#
# 为什么不复用 TaskManager 的池：那 4 个 worker 是给「分钟级重活」（渲染/
# 生图/批量生产）的持久化队列用的，用户交互型小任务（排版/发布/配音）挤进去
# 会被长任务饿死；独立小池互不抢占，且闸门/清理逻辑各管各的，互不干扰。

USER_JOB_MAX_WORKERS = 4       # 用户任务全局并发上限
USER_CONCURRENT_LIMIT = 2      # 每用户同时进行中的重任务数
_JOBS_STALE_AFTER_S = 3600     # 终态 JOBS 保留 1 小时后可清理

_USER_JOB_POOL = ThreadPoolExecutor(max_workers=USER_JOB_MAX_WORKERS,
                                    thread_name_prefix="yimu-user-job")
_USER_ACTIVE: Dict[str, set] = {}
_USER_GATE_LOCK = threading.Lock()

#: JOBS 视为「已结束」的状态集合（cleanup 只动这些）
_TERMINAL_JOB_STATUSES = ("done", "completed", "failed", "cancelled", "interrupted")


class UserTaskLimitError(RuntimeError):
    """每用户并发闸门拒绝（路由层转 429 友好提示）。"""


def prune_stale_jobs(max_age_s: int = _JOBS_STALE_AFTER_S) -> int:
    """清理 1 小时前已终态的 web.admin.JOBS 条目与内存任务快照（内存泄漏治理）。

    running/queued 永不清理。返回清理条数。spawn 时与启动时都会调用。
    """
    cutoff = time.time() - max_age_s
    pruned = 0
    try:
        from web import admin
        jobs = getattr(admin, "JOBS", None)
        if isinstance(jobs, dict):
            for jid in list(jobs.keys()):
                job = jobs.get(jid)
                if not isinstance(job, dict):
                    continue
                status = str(job.get("status") or "")
                ended = job.get("completed_at") or job.get("created_at") or 0
                if status in _TERMINAL_JOB_STATUSES and ended < cutoff:
                    jobs.pop(jid, None)
                    pruned += 1
    except Exception as e:
        logger.debug(f"[TaskQueue] 清理 JOBS 异常: {e}")
    # 同批清理内存任务快照里的过期终态任务
    try:
        with _global_task_manager._lock:
            stale = [
                tid for tid, t in _global_task_manager._tasks.items()
                if t.status in _TERMINAL_STATUSES
                and (t.completed_at or t.created_at or 0) < cutoff
            ]
            for tid in stale:
                _global_task_manager._tasks.pop(tid, None)
    except Exception as e:
        logger.debug(f"[TaskQueue] 清理内存任务快照异常: {e}")
    return pruned


def spawn_user_task(owner: str, name: str, fn: Callable[..., Any], *,
                    jid: Optional[str] = None, task_type: str = "general_task",
                    target_id: str = "", params: Optional[dict] = None,
                    initial_step: str = "排队中…") -> str:
    """把用户触发的后台重任务提交进统一受界线程池，返回 jid（路由回 ``{'job': jid}``）。

    - JOBS 注册带 owner 与 created_at；fn 结束时补终态时间戳（过期清理依据）；
    - 每用户并发闸门：同时最多 :data:`USER_CONCURRENT_LIMIT` 个，超出抛
      :class:`UserTaskLimitError`（路由层转 429 中文提示）；
    - fn 内部自管 JOBS 状态更新（沿用 ``_a.update_async_job`` 既有约定）；
      本函数只兜底「fn 抛异常未标终态」与「终态时间戳缺失」。
    """
    owner = str(owner or "").strip()
    jid = jid or f"job-{uuid.uuid4().hex[:12]}"

    # 每次派发顺带清理过期 JOBS（终态超 1 小时的条目）
    try:
        prune_stale_jobs()
    except Exception:
        pass

    if owner:
        with _USER_GATE_LOCK:
            active = _USER_ACTIVE.setdefault(owner, set())
            if len(active) >= USER_CONCURRENT_LIMIT:
                raise UserTaskLimitError(
                    f"后台任务较多（每用户同时最多 {USER_CONCURRENT_LIMIT} 个），"
                    "请等待当前任务完成后再试")
            active.add(jid)

    # 注册 JOBS + 持久化队列（带 owner，供 /api/tasks 按用户隔离）
    try:
        from web import admin as _admin
        _admin.start_async_job(jid, name=name, task_type=task_type, target_id=target_id,
                               params=dict(params or {}), owner=owner,
                               initial_step=initial_step)
    except Exception as e:
        logger.warning(f"[TaskQueue] 注册用户任务 [{jid}] 失败（继续执行）: {e}")

    def _safe_run():
        try:
            fn()
        except Exception as e:
            # 调用方 fn 通常自带 try/except 标记失败；这里兜底漏网的异常
            logger.exception(f"[TaskQueue] 用户任务 [{jid}] 执行异常: {e}")
            try:
                from web import admin as _admin2
                if isinstance(_admin2.JOBS.get(jid), dict):
                    _admin2.JOBS[jid].update(status="failed", error=str(e)[:300], step="执行失败")
            except Exception:
                pass
        finally:
            if owner:
                with _USER_GATE_LOCK:
                    active = _USER_ACTIVE.get(owner)
                    if active is not None:
                        active.discard(jid)
                        if not active:
                            _USER_ACTIVE.pop(owner, None)
            # 终态时间戳：prune_stale_jobs 依据它判断 1 小时过期
            try:
                from web import admin as _admin3
                job = _admin3.JOBS.get(jid)
                if isinstance(job, dict):
                    job.setdefault("completed_at", time.time())
            except Exception:
                pass

    try:
        _USER_JOB_POOL.submit(_safe_run)
    except RuntimeError as e:
        # why：池已关闭（进程退出中）时任务不能凭空消失，逐级兜底
        logger.warning(f"[TaskQueue] 用户任务池不可用，回退默认执行器: {e}")
        try:
            import asyncio as _asyncio
            _asyncio.get_event_loop().run_in_executor(None, _safe_run)
        except Exception:
            threading.Thread(target=_safe_run, daemon=True).start()
    logger.info(f"[TaskQueue] 用户任务 [{jid}] {name} 已提交（owner={owner or 'anonymous'}）")
    return jid


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

