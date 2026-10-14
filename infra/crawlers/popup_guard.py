# SPDX-License-Identifier: BUSL-1.1
"""浏览器弹窗单次熔断器（Single-Popup Circuit Breaker）。

设计契约：
1. 外部爬虫或扫码通道在单次会话中最多只允许尝试唤起 1 次；
2. 若用户未选择、取消或超时，立即进入熔断拦截态（intercepted=True），后续请求直接静默跳过；
3. Playwright 一律强制附加无头静默启动参数，禁止在 macOS / Windows 桌面弹出可视窗口。
"""
from __future__ import annotations

SILENT_CHROMIUM_ARGS: list[str] = [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--mute-audio",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-position=-32000,-32000",
]


class BrowserPopupCircuitBreaker:
    """进程级单次弹窗熔断状态机。"""

    def __init__(self) -> None:
        self._triggered_channels: set[str] = set()
        self._global_blocked: bool = False

    def allow_launch(self, channel: str = "default") -> bool:
        if self._global_blocked or channel in self._triggered_channels:
            return False
        self._triggered_channels.add(channel)
        return True

    def trip(self, channel: str = "default") -> None:
        self._triggered_channels.add(channel)
        self._global_blocked = True

    def reset(self) -> None:
        self._triggered_channels.clear()
        self._global_blocked = False


POPUP_BREAKER = BrowserPopupCircuitBreaker()
