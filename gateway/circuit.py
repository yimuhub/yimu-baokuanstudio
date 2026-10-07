# SPDX-License-Identifier: BUSL-1.1
"""上游熔断器：每个上游独立维护 closed / open / half-open 状态。

⭐ 关键规则：连续失败达到阈值（默认 3 次）即打开熔断，冷却（默认 30 秒）后
半开试探；试探成功才关闭。熔断保护的是上游额度与用户等待时间——
失败的上游不再被调用，避免请求堆积与无效扣费。

手动上下线（管理接口 toggle）优先级最高：手动下线后一律拒绝放行，
直到手动恢复。
"""
from __future__ import annotations

import threading
import time

# 熔断器状态常量
CLOSED = "closed"  # 正常：请求直通
OPEN = "open"  # 熔断：请求直接拒绝，走其他上游
HALF_OPEN = "half-open"  # 试探：冷却后允许少量请求通过，验证是否恢复


class CircuitBreaker:
    """单个上游的熔断器（线程安全）。"""

    def __init__(
        self,
        upstream_id: str,
        fail_threshold: int = 3,
        open_seconds: float = 30.0,
    ) -> None:
        self.upstream_id = upstream_id
        self.fail_threshold = max(1, fail_threshold)
        self.open_seconds = max(1.0, open_seconds)
        self._state = CLOSED
        self._fail_count = 0
        self._opened_at: float | None = None
        self._enabled = True  # 手动上下线开关
        self._last_error = ""
        self._lock = threading.Lock()

    # -- 查询 ----------------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def allow(self) -> bool:
        """是否允许向该上游发请求。"""
        with self._lock:
            if not self._enabled:
                return False
            if self._state == CLOSED:
                return True
            if self._state == HALF_OPEN:
                return True
            # OPEN：冷却时间到则转入半开试探
            if self._opened_at is not None and (
                time.monotonic() - self._opened_at >= self.open_seconds
            ):
                self._state = HALF_OPEN
                return True
            return False

    # -- 事件 ----------------------------------------------------------

    def record_success(self) -> None:
        """一次成功：失败计数清零，半开/打开状态恢复为关闭。"""
        with self._lock:
            self._fail_count = 0
            self._opened_at = None
            self._last_error = ""
            self._state = CLOSED

    def record_failure(self, error: str = "") -> None:
        """一次失败：计数 +1；达到阈值则打开熔断。

        注意：error 仅记录错误摘要（脱敏），不得包含上游密钥。
        """
        with self._lock:
            self._fail_count += 1
            if error:
                self._last_error = error[:200]
            if self._state == HALF_OPEN or self._fail_count >= self.fail_threshold:
                self._state = OPEN
                self._opened_at = time.monotonic()

    # -- 手动控制 ------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        """手动上下线：下线后 allow() 恒为 False，直到手动恢复。"""
        with self._lock:
            self._enabled = enabled
            if not enabled:
                self._state = OPEN
                self._opened_at = time.monotonic()
            else:
                # 手动恢复：回到关闭状态，重新开始计数
                self._state = CLOSED
                self._fail_count = 0
                self._opened_at = None

    # -- 观测 ----------------------------------------------------------

    def to_dict(self) -> dict:
        """管理接口 /api/gw/upstreams 的展示字段（不含任何密钥）。"""
        with self._lock:
            return {
                "state": self._state,
                "enabled": self._enabled,
                "fail_count": self._fail_count,
                "opened_at": self._opened_at,
                "last_error": self._last_error,
            }
