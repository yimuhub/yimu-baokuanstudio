# SPDX-License-Identifier: BUSL-1.1
"""R5-7 自动发布频控与账号健康：把「用小号、控频」从注释变成实现。

背景
----
本模块原文件头的风控提醒写着「用小号、控频，发布前人工审核」，
但**全模块没有任何一处实现**。而上游的组合能力恰好构成典型风控特征：

    一次 matrix 裂变（6 平台派生）+ 每日工单定时任务
      = 一个账号一天内向多个平台各发一条内容

这在平台侧是明确的机器行为信号（发布间隔过于规律、跨平台同步、内容
同源），极易触发限流甚至封号。本模块补上两道防线：

1. **频控**（:func:`check_rate_limit`）：滑动窗口内发布次数超阈值即拦截。
   默认 **1 小时不超过 3 条**，可在 ``.env`` 用 ``XHS_PUBLISH_MAX_PER_HOUR``
   调整；间隔不足（``XHS_PUBLISH_MIN_INTERVAL_S``，默认 300 秒）也拦。
2. **账号健康**（:func:`record_result` / :func:`account_health`）：
   连续失败达到阈值（默认 3 次）判定账号 ``degraded`` 并进入冷却
   （默认 6 小时），冷却期内**禁止自动发布**——此时人工介入比
   继续重试更安全。

⚠️ 诚实说明：本频控只覆盖**本系统经``core.xhspub`` 发出的发布**。
用户在浏览器里手动发、或绕过本系统的其他工具发布，本模块管不到；
平台侧风控是黑盒，本模块只能降低触发概率，不能保证不封号。
"""
from __future__ import annotations

import logging
import time
import uuid

logger = logging.getLogger(__name__)

#: 默认频控：1 小时内最多 3 条
DEFAULT_MAX_PER_HOUR = 3
#: 默认最小发布间隔：300 秒（5 分钟）
DEFAULT_MIN_INTERVAL_S = 300
#: 连续失败多少次判定账号异常
DEFAULT_FAIL_THRESHOLD = 3
#: 账号异常后的冷却时长：6 小时
DEFAULT_COOLDOWN_S = 6 * 3600
#: 滑动窗口长度：1 小时
WINDOW_S = 3600


def _int_env(name: str, default: int) -> int:
    from core.llm import load_env

    try:
        raw = load_env().get(name, "").strip()
        return int(raw) if raw else default
    except Exception:
        return default


def max_per_hour() -> int:
    """1 小时发布上限（可通过 ``XHS_PUBLISH_MAX_PER_HOUR`` 调整）。"""
    return max(1, _int_env("XHS_PUBLISH_MAX_PER_HOUR", DEFAULT_MAX_PER_HOUR))


def min_interval_s() -> int:
    """两次发布的最小间隔秒数（``XHS_PUBLISH_MIN_INTERVAL_S``）。"""
    return max(0, _int_env("XHS_PUBLISH_MIN_INTERVAL_S", DEFAULT_MIN_INTERVAL_S))


def fail_threshold() -> int:
    """连续失败几次后判定账号异常。"""
    return max(1, _int_env("XHS_PUBLISH_FAIL_THRESHOLD", DEFAULT_FAIL_THRESHOLD))


def cooldown_s() -> int:
    """账号异常后的冷却秒数。"""
    return max(0, _int_env("XHS_PUBLISH_COOLDOWN_S", DEFAULT_COOLDOWN_S))


# ---------------------------------------------------------------------------
# 频控
# ---------------------------------------------------------------------------


def recent_attempts(platform: str = "xhs", window_s: int = WINDOW_S,
                    account_key: str = "default") -> list[dict]:
    """取窗口内的发布尝试记录（含blocked，用于算真实频次）。"""
    from core import db

    c = db.conn()
    rows = c.execute(
        "SELECT id, user_id, draft_id, platform, status, detail, created_at "
        "FROM publish_attempts WHERE platform=? AND created_at>=? "
        "ORDER BY created_at DESC",
        (platform, time.time() - window_s)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def check_rate_limit(platform: str = "xhs", account_key: str = "default") -> dict:
    """发布前频控检查。**不通过时调用方必须中止发布。**

    Returns:
        ``{"ok": bool, "reason": str, "detail": {...}}``。
        ``ok=False`` 时 ``reason`` 为可直接展示给用户的中文说明。
    """
    # ① 账号健康：冷却期内一律禁止自动发布
    health = account_health(platform, account_key)
    if health["status"] == "cooldown":
        left = int(max(0, health["cooldown_until"] - time.time()))
        return {
            "ok": False,
            "reason": f"该发布账号处于冷却期（连续失败 {health['consecutive_failures']} 次），"
                      f"还需等待 {left // 60} 分钟。请先在浏览器里手动确认账号是否正常。",
            "detail": {"kind": "cooldown", "left_s": left},
        }

    # ② 滑动窗口频次
    try:
        recent = recent_attempts(platform, WINDOW_S, account_key)
    except Exception as e:
        # 频控查询失败时**放行**：宁可少一层保护，也不能因为计数器故障
        # 让所有正常发布全部瘫痪（fail-open）。
        logger.warning(f"[频控] 查询近期发布记录失败，本次放行: {e}")
        return {"ok": True, "reason": "", "detail": {"degraded_check": True}}

    limit = max_per_hour()
    if len(recent) >= limit:
        wait_s = int(max(0, recent[0]["created_at"] + WINDOW_S - time.time()))
        return {
            "ok": False,
            "reason": f"发布过于频繁：最近 1 小时内已发布 {len(recent)} 条"
                      f"（上限 {limit} 条）。为避免账号被平台限流，"
                      f"请等待 {wait_s // 60 + 1} 分钟后再试。",
            "detail": {"kind": "count", "recent": len(recent), "limit": limit,
                       "wait_s": wait_s},
        }

    # ③ 最小间隔
    gap = min_interval_s()
    if gap > 0 and recent:
        elapsed = time.time() - float(recent[0]["created_at"])
        if elapsed < gap:
            wait_s = int(gap - elapsed)
            return {
                "ok": False,
                "reason": f"发布间隔过短：距上次发布仅 {int(elapsed)} 秒，"
                          f"系统要求至少间隔 {gap} 秒，请等待 {wait_s} 秒后再试。",
                "detail": {"kind": "interval", "elapsed": int(elapsed),
                           "required": gap, "wait_s": wait_s},
            }

    return {"ok": True, "reason": "", "detail": {"recent": len(recent), "limit": limit}}


def record_attempt(draft_id: str = "", user_id: str = "", platform: str = "xhs",
                    status: str = "success", detail: str = "") -> str:
    """记一条发布尝试（成功/失败/被频控拦截）。

    ⭐ 被拦截也记录：运营需要看到「有多少次发布是被频控挡下来的」，
    这是判断频控阈值是否设置过严的唯一依据。
    """
    try:
        pid = f"pa-{uuid.uuid4().hex[:12]}"
        from core import db

        c = db.conn()
        c.execute(
            "INSERT INTO publish_attempts "
            "(id, tenant_id, user_id, draft_id, platform, status, detail, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, "default", str(user_id or ""), str(draft_id or ""), platform,
             status, (detail or "")[:300], time.time()),
        )
        c.commit()
        c.close()
        return pid
    except Exception as e:
        logger.warning(f"[频控] 记录发布尝试失败: {e}")
        return ""


# ---------------------------------------------------------------------------
# 账号健康
# ---------------------------------------------------------------------------


def account_health(platform: str = "xhs", account_key: str = "default") -> dict:
    """取账号健康状态（不存在时返回 healthy 初始态）。"""
    try:
        from core import db

        c = db.conn()
        row = c.execute(
            "SELECT account_key, platform, status, consecutive_failures, "
            "last_success_at, last_failure_at, cooldown_until, updated_at "
            "FROM account_health WHERE account_key=? AND platform=?",
            (account_key, platform)).fetchone()
        c.close()
        if row is None:
            return {"account_key": account_key, "platform": platform,
                    "status": "healthy", "consecutive_failures": 0,
                    "last_success_at": 0.0, "last_failure_at": 0.0,
                    "cooldown_until": 0.0, "updated_at": 0.0}
        d = dict(row)
        # 冷却期已过则自动恢复为 degraded（可继续尝试，但不回到 healthy，
        # 需一次成功发布才清零）
        if d["status"] == "cooldown" and d["cooldown_until"] <= time.time():
            d["status"] = "degraded"
        return d
    except Exception as e:
        logger.warning(f"[账号健康] 读取状态失败: {e}")
        return {"account_key": account_key, "platform": platform,
                "status": "healthy", "consecutive_failures": 0,
                "last_success_at": 0.0, "last_failure_at": 0.0,
                "cooldown_until": 0.0, "updated_at": 0.0}


def record_result(ok: bool, platform: str = "xhs", detail: str = "",
                  account_key: str = "default") -> dict:
    """记录一次发布结果并更新账号健康。

    - 成功：``consecutive_failures`` 清零，状态回 healthy
    - 失败：累加失败次数，达阈值则进冷却
    """
    now = time.time()
    cur = account_health(platform, account_key)
    fails = int(cur.get("consecutive_failures") or 0)
    status = str(cur.get("status") or "healthy")
    cooldown_until = float(cur.get("cooldown_until") or 0.0)
    last_ok = float(cur.get("last_success_at") or 0.0)
    last_fail = float(cur.get("last_failure_at") or 0.0)

    if ok:
        fails = 0
        status = "healthy"
        cooldown_until = 0.0
        last_ok = now
    else:
        fails += 1
        last_fail = now
        if fails >= fail_threshold():
            status = "cooldown"
            cooldown_until = now + cooldown_s()

    try:
        from core import db

        c = db.conn()
        c.execute(
            "INSERT INTO account_health (id, tenant_id, account_key, platform, status, "
            "consecutive_failures, last_success_at, last_failure_at, cooldown_until, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(account_key, platform) DO UPDATE SET "
            "status=excluded.status, consecutive_failures=excluded.consecutive_failures, "
            "last_success_at=excluded.last_success_at, last_failure_at=excluded.last_failure_at, "
            "cooldown_until=excluded.cooldown_until, updated_at=excluded.updated_at",
            (f"ah-{uuid.uuid4().hex[:12]}", "default", account_key, platform, status,
             fails, last_ok, last_fail, cooldown_until, now),
        )
        c.commit()
        c.close()
    except Exception as e:
        logger.warning(f"[账号健康] 写入状态失败: {e}")

    return {"status": status, "consecutive_failures": fails,
            "cooldown_until": cooldown_until, "detail": detail}


def health_summary() -> list[dict]:
    """所有账号的健康状态（运维看板用）。"""
    try:
        from core import db

        c = db.conn()
        rows = c.execute(
            "SELECT account_key, platform, status, consecutive_failures, "
            "last_success_at, last_failure_at, cooldown_until FROM account_health"
        ).fetchall()
        c.close()
        return [account_health(r["platform"], r["account_key"]) if r["status"] != "healthy"
                else dict(r) for r in rows]
    except Exception:
        return []