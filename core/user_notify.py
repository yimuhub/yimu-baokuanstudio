# SPDX-License-Identifier: BUSL-1.1
"""R5-3 用户侧通知投递：落库台账 + 24 小时召回节流。

为什么要有台账而不是直接发
--------------------------
``notify_user`` 直接返回成功/失败，但产品侧真正要回答的是三个问题：
「这条通知发出去没？」「同一用户会不会被反复轰炸？」「召回邮件 24 小时内
到底发了几封？」——这些都必须有持久记录，因此每次投递先落
``user_notifications`` 再发。

节流口径
--------
配额墙召回（``kind="quota_recall"``）默认 **24 小时内只发 1 封**：
用户撞墙后可能连续点 10 个功能，每次都发信会被当成骚扰。
其他类型（欢迎信、邀请奖励）默认不限流。
"""
from __future__ import annotations

import time
import uuid

#: 召回节流窗口（秒）——24 小时
QUOTA_RECALL_WINDOW_S = 24 * 3600

#: 各类通知的节流窗口（秒）；0 表示不节流
THROTTLE_WINDOWS = {
    "quota_recall": QUOTA_RECALL_WINDOW_S,
    "welcome": 0,
    "invite_reward": 0,
}


def _now() -> float:
    return time.time()


def recent_count(user_id: str, kind: str, window_s: int,
                 tenant_id: str = "default") -> int:
    """统计窗口内该用户同类型通知的条数（用于节流判断）。"""
    if window_s <= 0:
        return 0
    try:
        from core import db

        c = db.conn()
        since = _now() - window_s
        # kind 编在 subject 前缀里（如「[额度召回]...」），
        # 这里用 props 无关的稳定前缀匹配，避免额外加列。
        row = c.execute(
            "SELECT COUNT(*) n FROM user_notifications "
            "WHERE user_id=? AND tenant_id=? AND subject LIKE ? AND created_at>=?",
            (str(user_id), tenant_id, f"%[{kind}]%", since)).fetchone()
        n = int(row["n"]) if row else 0
        c.close()
        return n
    except Exception:
        return 0


def deliver(user_id: str, recipient: str, title: str, body: str,
            kind: str = "quota_recall", channel: str = "email",
            tenant_id: str = "default", force: bool = False,
            sender=None) -> dict:
    """投递一条用户侧通知：先落台账 → 节流判定 → 实际发送 → 回写状态。

    Args:
        user_id: 目标用户。
        recipient: 收件地址（可为空，为空则只落库待补发）。
        title: 通知标题（**必须**以 ``[kind]`` 前缀开头，作为节流匹配键）。
        body: 正文。
        kind: 通知类型，见 :data:`THROTTLE_WINDOWS`。
        channel: 通道名，默认 email。
        force: True 时跳过节流（人工重发用）。
        sender: 可注入的发送函数（测试用），签名 ``(to, subject, body) -> dict``。

    Returns:
        ``{"ok": bool, "status": str, "skipped": bool, "reason": str}``。
        本函数**永不抛异常**——通知失败绝不能影响用户正在看的主流程。
    """
    nid = f"nt-{uuid.uuid4().hex[:12]}"
    subject = title if title.startswith("[") else f"[{kind}] {title}"
    created = _now()

    # ① 先落台账（即使后面被节流拦下，也留下「本该发」的记录便于排查）
    try:
        from core import db

        c = db.conn()
        c.execute(
            "INSERT INTO user_notifications "
            "(id, tenant_id, user_id, channel, recipient, subject, body, status, error, created_at, sent_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (nid, tenant_id or "default", str(user_id or ""), channel,
             recipient or "", subject, body, "pending", "", created, 0.0),
        )
        c.commit()
        c.close()
    except Exception:
        return {"ok": False, "status": "failed", "skipped": False,
                "reason": "台账写入失败", "id": nid}

    def _finish(status: str, error: str = "", extra: dict | None = None) -> dict:
        """回写投递结果。"""
        try:
            from core import db

            c = db.conn()
            c.execute(
                "UPDATE user_notifications SET status=?, error=?, sent_at=? WHERE id=?",
                (status, error[:200], (_now() if status in ("sent", "failed") else 0.0), nid),
            )
            c.commit()
            c.close()
        except Exception:
            pass
        out = {"ok": status == "sent", "status": status, "id": nid,
               "skipped": status in ("skipped", "pending"),
               "reason": error or ("" if status == "sent" else status)}
        if extra:
            out.update(extra)
        return out

    # ② 节流判定
    window = THROTTLE_WINDOWS.get(kind, 0)
    if not force and window > 0:
        sent_n = recent_count(user_id, kind, window, tenant_id)
        if sent_n > 0:
            return _finish("skipped", f"{window // 3600} 小时内已发过 {sent_n} 封召回邮件")

    # ③ 无收件地址：保持 pending，等用户补全邮箱后由后续任务补发
    if not (recipient or "").strip():
        return _finish("pending", "缺少收件地址，等待用户补全邮箱")

    # ④ 实际发送
    try:
        if sender is None:
            from core import notify

            sender = notify.notify_user
        res = sender(recipient, subject, body)
    except Exception as e:
        return _finish("failed", str(e))

    if res.get("ok"):
        return _finish("sent")
    if res.get("skipped"):
        # 通道未配置（如 SMTP 未设）——不是错误，保持 pending 以便配置后补发
        return _finish("pending", res.get("error") or "通道未配置")
    return _finish("failed", res.get("error") or "发送失败")


def quota_recall_body(action_label: str, need: int, balance: int,
                      upgrade_hint: str = "") -> tuple[str, str]:
    """组装配额墙召回邮件的（标题, 正文）。

    单独抽出便于测试断言文案质量——文案是转化触点，
    必须说清「发生了什么 + 现在怎么办」，且不含开发者黑话。
    """
    title = "[quota_recall] 算力额度已用完，升级后可继续创作"
    body = (
        f"你好，\n\n"
        f"你刚才使用「{action_label}」时，算力额度已经用完了。\n"
        f"这次该功能需要 {need:,} 点，你的账户当前还剩 {balance:,} 点。\n\n"
        f"你可以这样继续用：\n"
        f"1. 兑换卡密：为账户直接充值点数，立刻继续；\n"
        f"2. 升级套餐：升级到 Pro 后额度大幅提升，适合高频创作；\n"
        f"3. 攒点额度：等下个额度周期自动恢复。\n\n"
        f"{upgrade_hint}\n"
        f"—— 一幕·YIMU 爆款工作室\n"
        f"（本邮件因你的额度耗尽触发，如已充值请忽略）"
    )
    return title, body


def list_for_user(user_id: str, limit: int = 20,
                  tenant_id: str = "default") -> list[dict]:
    """查某用户收到的通知（用户中心「我的消息」用）。"""
    try:
        from core import db

        c = db.conn()
        rows = c.execute(
            "SELECT id, channel, recipient, subject, body, status, created_at, sent_at "
            "FROM user_notifications WHERE user_id=? AND tenant_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (str(user_id), tenant_id or "default", int(limit))).fetchall()
        out = [dict(r) for r in rows]
        c.close()
        return out
    except Exception:
        return []