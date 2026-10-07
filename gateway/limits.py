# SPDX-License-Identifier: BUSL-1.1
"""限速与配额：按 Key 的 rpm / tpm 滑动窗口限速、Key 配额检查、会员额度原子扣减。

⭐ 关键规则（违反后果）：
- 超限一律 429，body 必须带 retry_after（秒）与 credits_left；
  否则调用方无法退避重试，会把网关打穿。
- 会员扣费必须是原子 UPDATE（credits_used + n <= credits_total），
  绝不允许「先查后改」——并发下会超发额度，直接造成资损。
- 扣费顺序：先扣会员额度 → 再调上游；扣费失败直接 429（不调上游）；
  上游失败不退款（V7.0 简化，差额不追补），但必须记 error 日志。
- ledger 只增不改：所有写入均为 INSERT。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from studio.db_models import GatewayKey, Ledger, Membership, utcnow

from .config import GatewayError, credits_for_tokens

# Key 配额统计窗口：最近 30 天的 ledger cost_cents 求和
QUOTA_WINDOW_DAYS = 30


class RateLimiter:
    """按 Key 的滑动窗口限速器（进程内内存实现，多线程安全）。

    - rpm：60 秒窗口内的请求数上限。
    - tpm：60 秒窗口内的 token 数上限（调用前用预估值预占，调用后用实际值结算）。
    """

    def __init__(self) -> None:
        self._req: dict[str, deque] = defaultdict(deque)  # key_id → 请求时间戳
        self._tok: dict[str, deque] = defaultdict(deque)  # key_id → (时间戳, tokens)
        self._lock = threading.Lock()

    def _prune(self, key_id: str, now: float) -> None:
        cutoff = now - 60.0
        req = self._req[key_id]
        while req and req[0] <= cutoff:
            req.popleft()
        tok = self._tok[key_id]
        while tok and tok[0][0] <= cutoff:
            tok.popleft()

    def consume(self, key_id: str, rpm: int, tpm: int, est_tokens: int) -> tuple[bool, float]:
        """尝试占用一次调用配额。返回 (是否允许, 需等待秒数)。"""
        now = time.monotonic()
        with self._lock:
            self._prune(key_id, now)
            if rpm > 0 and len(self._req[key_id]) >= rpm:
                retry_after = max(1.0, 60.0 - (now - self._req[key_id][0]))
                return False, retry_after
            if tpm > 0:
                used = sum(t for _, t in self._tok[key_id])
                if used + est_tokens > tpm:
                    oldest = self._tok[key_id][0][0] if self._tok[key_id] else now
                    retry_after = max(1.0, 60.0 - (now - oldest))
                    return False, retry_after
            self._req[key_id].append(now)
            self._tok[key_id].append((now, max(0, est_tokens)))
            return True, 0.0

    def settle(self, key_id: str, est_tokens: int, actual_tokens: int) -> None:
        """调用结束后用实际 tokens 替换预估值，使窗口统计更准确。"""
        now = time.monotonic()
        with self._lock:
            self._prune(key_id, now)
            tok = self._tok[key_id]
            if tok and tok[-1][1] == max(0, est_tokens):
                tok.pop()
                tok.append((now, max(0, actual_tokens)))


def key_used_credits(db: Session, tenant_id: str, key_id: str) -> int:
    """Key 在配额窗口内已消耗的 credits（ledger cost_cents 求和）。"""
    since = utcnow() - timedelta(days=QUOTA_WINDOW_DAYS)
    used = (
        db.query(func.coalesce(func.sum(Ledger.cost_cents), 0))
        .filter(
            Ledger.tenant_id == tenant_id,
            Ledger.key_id == key_id,
            Ledger.created_at >= since,
        )
        .scalar()
    )
    return int(used or 0)


def key_credits_left(db: Session, tenant_id: str, key: GatewayKey) -> int:
    """Key 剩余额度（配额 - 已用，不为负）。"""
    return max(0, key.quota_credits - key_used_credits(db, tenant_id, key.id))


def membership_credits_left(db: Session, tenant_id: str, user_id: str) -> int:
    """会员剩余额度（同一账本：网关 credits 即会员 credits）。"""
    ms = (
        db.query(Membership)
        .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .one_or_none()
    )
    if ms is None:
        return 0
    return max(0, ms.credits_total - ms.credits_used)


def charge_membership(db: Session, tenant_id: str, user_id: str, amount: int) -> bool:
    """⭐ 原子扣会员额度：UPDATE … WHERE credits_used + n <= credits_total。

    返回 True=扣费成功；False=余额不足（调用方应返回 429）。
    成功后调用方必须 db.commit()；失败时不做任何写入。
    """
    if amount <= 0:
        return True
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # 与 SQLite 存储格式对齐比较
    sql = text(
        "UPDATE memberships SET credits_used = credits_used + :n, updated_at = :now "
        "WHERE tenant_id = :t AND user_id = :u AND status = 'active' "
        "AND credits_used + :n <= credits_total "
        "AND (period_end IS NULL OR period_end > :now)"
    )
    result = db.execute(sql, {"n": amount, "now": now, "t": tenant_id, "u": user_id})
    return result.rowcount > 0


def check_rate_limit(
    limiter: RateLimiter,
    key: GatewayKey,
    tenant_id: str,
    db: Session,
    est_tokens: int,
    request_id: str,
) -> None:
    """rpm / tpm 检查；超限抛 429（带 retry_after 与 credits_left）。"""
    allowed, retry_after = limiter.consume(key.id, key.rate_limit_rpm, key.rate_limit_tpm, est_tokens)
    if not allowed:
        raise GatewayError(
            "QUOTA_EXCEEDED",
            "请求过于频繁，请稍后重试",
            "请降低调用频率，或联系管理员提升该 Key 的限速",
            extra={
                "retry_after": int(retry_after) + 1,
                "credits_left": key_credits_left(db, tenant_id, key),
            },
        )


def check_key_quota(
    db: Session,
    tenant_id: str,
    key: GatewayKey,
    est_credits: int,
    request_id: str,
) -> None:
    """Key 配额检查：已用 + 本次预估 > 配额 → 429。"""
    used = key_used_credits(db, tenant_id, key.id)
    if used + est_credits > key.quota_credits:
        raise GatewayError(
            "QUOTA_EXCEEDED",
            "该 Key 的剩余额度不足",
            "请联系管理员提升该 Key 的配额，或更换 Key 后重试",
            extra={"retry_after": 60, "credits_left": max(0, key.quota_credits - used)},
        )


def charge_or_429(
    db: Session,
    tenant_id: str,
    user_id: str,
    amount: int,
) -> None:
    """⭐ 先扣费再调上游：原子扣减失败 → 429（credits_left=0），不调用上游。"""
    ok = charge_membership(db, tenant_id, user_id, amount)
    if not ok:
        db.rollback()
        raise GatewayError(
            "QUOTA_EXCEEDED",
            "账户剩余额度不足",
            "请联系管理员充值或提升会员档位后重试",
            extra={"retry_after": 60, "credits_left": 0},
        )
    db.commit()


def write_ledger_rows(
    db: Session,
    tenant_id: str,
    key_id: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    input_rate: int,
    output_rate: int,
    latency_ms: int,
    cached: bool = False,
) -> tuple[int, int]:
    """⭐ 写 ledger 两行（direction=input / output），只增不改。

    返回 (input_cost, output_cost)；调用方负责 commit。
    """
    from studio.db_models import Ledger, new_id, utcnow

    now = utcnow()
    cost_in = credits_for_tokens(input_tokens, input_rate)
    cost_out = credits_for_tokens(output_tokens, output_rate)
    db.add(
        Ledger(
            id=new_id(),
            tenant_id=tenant_id,
            key_id=key_id,
            model=model,
            direction="input",
            tokens=input_tokens,
            cost_cents=cost_in,
            latency_ms=latency_ms,
            cached=cached,
            created_at=now,
        )
    )
    db.add(
        Ledger(
            id=new_id(),
            tenant_id=tenant_id,
            key_id=key_id,
            model=model,
            direction="output",
            tokens=output_tokens,
            cost_cents=cost_out,
            latency_ms=latency_ms,
            cached=cached,
            created_at=now,
        )
    )
    return cost_in, cost_out
