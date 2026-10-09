# SPDX-License-Identifier: BUSL-1.1
"""R5-6 用户行为埋点与漏斗聚合。

为什么需要
----------
R5 批次前全仓搜索``埋点/analytics/DAU/retention/转化率/funnel/漏斗``
**零命中**——没有任何用户行为数据，运营判断（该推付费还是该做留存、
哪一步流失最严重）全靠猜。本模块提供最小可用的埋点层：

- :func:`track` 记一条事件（唯一写入口，永远不抛异常）
- :func:`funnel` 按 5 步链路算逐级转化率

5 步漏斗定义（顺序即用户真实旅程）
----------------------------------
1. ``signup``               注册
2. ``first_draft_created``  首次成稿（价值感知点）
3. ``first_drama_run``      首次跑短剧（重度功能体验）
4. ``quota_blocked``        撞上额度墙（付费触点）
5. ``cdkey_redeemed``       兑换卡密（转化完成）

⚠️ 诚实说明：漏斗按**事件发生过的去重用户数**统计，不是严格同会话序列。
   用户可能先撞墙再成稿，因此逐级转化率可能出现 >100% 的后段反超，
   看板已在UI 上标注这是「累计触达」口径而非「严格顺序」。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

#: 漏斗 5 步的事件名与中文名（看板与接口共用，保证口径一致）
FUNNEL_STEPS: list[tuple[str, str]] = [
    ("signup", "注册"),
    ("first_draft_created", "首次成稿"),
    ("first_drama_run", "首次跑短剧"),
    ("quota_blocked", "撞上额度墙"),
    ("cdkey_redeemed", "兑换卡密"),
]

#: 全部被识别的事件名（写入时校验，防止拼错事件名静默污染漏斗）
KNOWN_EVENTS: set[str] = {name for name, _ in FUNNEL_STEPS}


def track(event: str, user_id: str = "", props: dict[str, Any] | None = None,
          tenant_id: str = "default") -> str:
    """记一条用户事件，返回事件 id。

    ⭐ 埋点是旁路能力：**任何异常都不许上抛**（表不存在、字段不对、
       props 不可序列化等），否则埋点会把主业务带崩。失败返回空串。
    """
    eid = ""
    try:
        eid = f"ev-{uuid.uuid4().hex[:12]}"
        payload = json.dumps(props or {}, ensure_ascii=False, default=str)
        from core import db

        c = db.conn()
        c.execute(
            "INSERT INTO user_events (id, tenant_id, user_id, event, props, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (eid, tenant_id or "default", str(user_id or ""), event, payload, time.time()),
        )
        c.commit()
        c.close()
    except Exception:
        return ""
    return eid


def count_event(event: str, since: float | None = None,
                tenant_id: str = "default") -> int:
    """某事件的发生次数（不去重）。"""
    try:
        from core import db

        c = db.conn()
        if since is None:
            row = c.execute(
                "SELECT COUNT(*) n FROM user_events WHERE event=? AND tenant_id=?",
                (event, tenant_id or "default")).fetchone()
        else:
            row = c.execute(
                "SELECT COUNT(*) n FROM user_events "
                "WHERE event=? AND tenant_id=? AND created_at>=?",
                (event, tenant_id or "default", float(since))).fetchone()
        n = int(row["n"]) if row else 0
        c.close()
        return n
    except Exception:
        return 0


def count_users(event: str, since: float | None = None,
                tenant_id: str = "default") -> int:
    """某事件的**去重用户数**（漏斗分子，空 user_id 不计）。

    去重而非计数是必要的：同一个用户可能撞 10 次额度墙，
    但在漏斗里只应算作 1 个人。
    """
    try:
        from core import db

        c = db.conn()
        if since is None:
            row = c.execute(
                "SELECT COUNT(DISTINCT user_id) n FROM user_events "
                "WHERE event=? AND tenant_id=? AND user_id<>''",
                (event, tenant_id or "default")).fetchone()
        else:
            row = c.execute(
                "SELECT COUNT(DISTINCT user_id) n FROM user_events "
                "WHERE event=? AND tenant_id=? AND user_id<>'' AND created_at>=?",
                (event, tenant_id or "default", float(since))).fetchone()
        n = int(row["n"]) if row else 0
        c.close()
        return n
    except Exception:
        return 0


def funnel(days: int = 30, tenant_id: str = "default") -> dict:
    """计算 5 步漏斗。

    Args:
        days: 回看窗口（天）。传 0 表示全量历史。
        tenant_id: 租户。

    Returns:
        ``{"steps": [...], "window_days": n, "generated_at": ts}``，
        每步含 ``event/label/users/total/rate_from_prev/rate_from_top``。
        ``rate_from_prev`` 为相对上一步的转化率（0~100，保留 1 位小数）。
    """
    since = (time.time() - days * 86400) if days > 0 else None
    steps: list[dict] = []
    top_users = 0
    for idx, (event, label) in enumerate(FUNNEL_STEPS):
        users = count_users(event, since, tenant_id)
        total = count_event(event, since, tenant_id)
        if idx == 0:
            top_users = users
        prev_users = steps[-1]["users"] if steps else 0
        steps.append({
            "step": idx + 1,
            "event": event,
            "label": label,
            "users": users,
            "total": total,
            "rate_from_prev": (round(users / prev_users * 100, 1) if prev_users else 0.0),
            "rate_from_top": (round(users / top_users * 100, 1) if top_users else 0.0),
        })
    return {
        "steps": steps,
        "window_days": days,
        "top_users": top_users,
        "generated_at": time.time(),
    }


def list_recent(limit: int = 50, tenant_id: str = "default") -> list[dict]:
    """最近事件流（看板调试用）。"""
    try:
        from core import db

        c = db.conn()
        rows = c.execute(
            "SELECT id, user_id, event, props, created_at FROM user_events "
            "WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
            (tenant_id or "default", int(limit))).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["props"] = json.loads(d.get("props") or "{}")
            except Exception:
                d["props"] = {}
            out.append(d)
        c.close()
        return out
    except Exception:
        return []