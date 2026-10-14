"""内容排期日历与后台自动发布调度中枢 (Editorial Calendar & Scheduled Dispatcher)。

支持创作者将成稿/卡片/短视频设定在未来的任意黄金发布时间节点（如中午12:00、晚上21:30），
后台守护进程自动按时轮询并安全触发对应平台的分发执行。

R4 合规修正
-----------
非小红书平台**不支持自动发布**。此前排期到点后会标 ``published`` 并附一条
「模拟分发成功完成」的文案，属于假成功（DB 显示已发布但实际未发），
现已改为 ``manual_pending`` 状态 +「该平台暂不支持自动发布，已生成内容请手动复制」
的诚实文案。
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from core import db

logger = logging.getLogger(__name__)

_daemon_running = False
_daemon_lock = threading.Lock()

#: 每日工单当日是否已执行过（防同一天重复跑，同时支持状态落盘防重启重复扣费）。
_ticket_ran_on: str = ""
_TICKET_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "daily_ticket_state.json"


def _load_ticket_ran_on() -> str:
    global _ticket_ran_on
    if _ticket_ran_on:
        return _ticket_ran_on
    try:
        if _TICKET_STATE_FILE.exists():
            data = json.loads(_TICKET_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("ran_on"):
                _ticket_ran_on = str(data["ran_on"])
    except Exception:
        pass
    return _ticket_ran_on


def _save_ticket_ran_on(day: str) -> None:
    global _ticket_ran_on
    _ticket_ran_on = day
    try:
        _TICKET_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TICKET_STATE_FILE.write_text(json.dumps({"ran_on": day}), encoding="utf-8")
    except Exception:
        pass


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
            d = db.get_draft(draft_id)
            title = (d or {}).get("title", "")
            db.update_scheduled_post_status(
                pid, "manual_pending",
                f"[{platform}] 该平台暂不支持自动发布，已生成内容请手动复制到{platform}发布"
                + (f"（稿件：{title[:30]}）" if title else ""),
            )
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
                    # 派发线程前先置为 running，防止下一轮轮询重复启动线程
                    db.update_scheduled_post_status(item["id"], "running", "已进入发布队列...")
                    threading.Thread(target=_run_scheduled_job, args=(item,), daemon=True).start()
        except Exception as e:
            logger.debug(f"[Scheduler] 调度轮询轻微异常: {e}")
        try:
            _maybe_run_daily_ticket()
        except Exception as e:
            logger.debug(f"[Scheduler] 每日工单检查异常: {e}")
        time.sleep(15)


#: 工单线程锁（防止轮询重入导致同一天并发跑两次）
_ticket_lock = threading.Lock()


def _ticket_settings() -> tuple[bool, int, int]:
    """读工单开关与时间：返回 (是否启用, 时, 分)。缺省 07:30。"""
    from core.llm import load_env

    env = load_env()
    enabled = str(env.get("TICKET_ENABLED", "")).strip() in ("1", "true", "True", "yes")
    raw = str(env.get("TICKET_TIME", "07:30")).strip() or "07:30"
    try:
        hh, mm = raw.split(":")
        return enabled, int(hh), int(mm)
    except Exception:
        return enabled, 7, 30


def _maybe_run_daily_ticket() -> None:
    """若已到设定时间且当天未跑过，则后台线程触发工单（支持跨整点 15 分钟窗口，如 07:50~08:04）。"""
    global _ticket_ran_on
    enabled, hh, mm = _ticket_settings()
    if not enabled:
        return
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if _ticket_ran_on == today:
        return
    sched_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    diff_sec = (now - sched_dt).total_seconds()
    if not (0 <= diff_sec < 15 * 60):
        return
    if not _ticket_lock.acquire(blocking=False):
        return
    _save_ticket_ran_on(today)

    def _run():
        try:
            logger.info("[Ticket] 触发每日工单（应用内定时）")
            from core import ticket

            ticket.run_ticket()
        except Exception as e:
            logger.error(f"[Ticket] 每日工单执行失败: {e}", exc_info=True)
        finally:
            _ticket_lock.release()

    threading.Thread(target=_run, name="mediaflow-daily-ticket", daemon=True).start()


def ticket_status() -> dict:
    """工单定时状态（供设置页展示）。"""
    enabled, hh, mm = _ticket_settings()
    return {
        "enabled": enabled,
        "time": f"{hh:02d}:{mm:02d}",
        "ran_today": _ticket_ran_on,
        "daemon_running": _daemon_running,
    }


def start_scheduler_daemon():
    """启动全局调度线程。"""
    global _daemon_running
    with _daemon_lock:
        if not _daemon_running:
            _daemon_running = True
            t = threading.Thread(target=_scheduler_loop, name="mediaflow-scheduler", daemon=True)
            t.start()
