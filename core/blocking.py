# SPDX-License-Identifier: BUSL-1.1
"""受界阻塞任务池（全仓唯一入口，v15.9.11）。

为什么需要：
    ``asyncio.get_event_loop().run_in_executor(None, fn)`` 走的是事件循环的
    **默认**线程池——默认 max_workers = min(32, CPU+4)，不可配置、不区分
    业务。路由层曾有 40+ 处这样直连默认池：一批生图/改写/TTS 请求就能把
    32 个线程占满，其余同步接口排队，表现为 P99 突然 +100~500ms。

本模块提供一个进程级受界池：
- 默认 16 个工作线程，可用 ``YIMU_BLOCKING_WORKERS`` 调整（2~64）；
- 异步侧统一 ``await run_blocking(fn, *args)``；
- 进程退出由调用方按需 ``shutdown_blocking_pool(wait=False)``。

约定：除本模块与 ``core/task_queue.py`` 的关机兜底外，仓库内不得再出现
``run_in_executor(None, ...)``（由 ``tests/test_v15911_fixes.py`` 锁死）。
"""
from __future__ import annotations

import asyncio
import functools
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


def _worker_count() -> int:
    try:
        raw = int(os.environ.get("YIMU_BLOCKING_WORKERS", "16"))
    except (TypeError, ValueError):
        raw = 16
    return max(2, min(raw, 64))


_POOL = ThreadPoolExecutor(
    max_workers=_worker_count(),
    thread_name_prefix="yimu-blocking",
)


async def run_blocking(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """在受界池里执行同步阻塞函数，返回其结果（异常原样抛出）。

    用法：``res = await run_blocking(orchestrator.run_once)`` 或
    ``res = await run_blocking(build, did, platform)``。
    """
    loop = asyncio.get_running_loop()
    call = functools.partial(fn, *args, **kwargs)
    return await loop.run_in_executor(_POOL, call)


def shutdown_blocking_pool(wait: bool = False) -> None:
    """进程退出时关闭池（幂等；关闭后提交会抛 RuntimeError）。"""
    _POOL.shutdown(wait=wait)


__all__ = ["run_blocking", "shutdown_blocking_pool"]
