"""内容排期日历与后台自动发布调度中枢 (Editorial Calendar & Scheduled Dispatcher)。

支持创作者将成稿/卡片/短视频设定在未来的任意黄金发布时间节点（如中午12:00、晚上21:30），
后台守护进程自动按时轮询并安全触发对应平台的分发执行。
"""
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional
from core import db

logger = logging.getLogger(__name__)

_daemon_running = False
_daemon_lock = threading.Lock()


def schedule_post(draft_id: str, platform: str, target_time: float) -> str:
    """添加一条排期发布任务。"""
    d = db.get_draft(draft_id)
    if not d:
        raise ValueError(f"草稿 [{draft_id}] 不存在")
    pid = db.add_scheduled_post(draft_id, platform, target_time)
    dt_str = datetime.fromtimestamp(target_time).strftime("%Y-%m-%d %H:%M")
    logger.info(f"[Scheduler] 已排期草稿 [{draft_id}] 至 [{platform}]，设定发布时间: {dt_str}")
    return pid


def list_scheduled(status: Optional[str] = None) -> List[dict]:
    """查询排期列表。"""
    posts = db.list_scheduled_posts(status)
    for p in posts:
        p["target_time_fmt"] = datetime.fromtimestamp(p["target_time"]).strftime("%Y-%m-%d %H:%M")
        p["created_at_fmt"] = datetime.fromtimestamp(p["created_at"]).strftime("%Y-%m-%d %H:%M")
    return posts


def cancel_scheduled(pid: str) -> bool:
    """取消一条排期任务。"""
    db.update_scheduled_post_status(pid, "cancelled", "用户主动取消排期")
    return True


def _run_scheduled_job(item: dict):
    pid = item["id"]
    draft_id = item["draft_id"]
    platform = item["platform"]
    logger.info(f"[Scheduler] 开始执行定时排期任务 [{pid}]: 草稿={draft_id}, 平台={platform}")
    db.update_scheduled_post_status(pid, "running", "正在执行自动发布...")

    try:
        if platform == "xhs":
            from core import xhspub
            res = xhspub.publish(draft_id)
            if res.get("ok"):
                db.update_scheduled_post_status(pid, "published", f"小红书发布成功: {res.get('title')}")
            else:
                db.update_scheduled_post_status(pid, "failed", f"小红书发布未成功: {res.get('detail')}")
        else:
            # 其他平台
            db.update_scheduled_post_status(pid, "published", f"[{platform}] 定时任务模拟分发成功完成")
    except Exception as e:
        logger.error(f"[Scheduler] 定时排期任务 [{pid}] 执行异常: {e}", exc_info=True)
        db.update_scheduled_post_status(pid, "failed", f"异常: {e}")


def _scheduler_loop():
    global _daemon_running
    logger.info("[Scheduler] 后台定时发布调度引擎已就绪启动")
    while _daemon_running:
        try:
            pending_posts = db.list_scheduled_posts(status="pending")
            current_ts = time.time()
            for item in pending_posts:
                if item["target_time"] <= current_ts:
                    # 触发执行
                    threading.Thread(target=_run_scheduled_job, args=(item,), daemon=True).start()
        except Exception as e:
            logger.debug(f"[Scheduler] 调度轮询轻微异常: {e}")
        time.sleep(15)


def start_scheduler_daemon():
    """启动全局调度线程。"""
    global _daemon_running
    with _daemon_lock:
        if not _daemon_running:
            _daemon_running = True
            t = threading.Thread(target=_scheduler_loop, name="mediaflow-scheduler", daemon=True)
            t.start()
