# SPDX-License-Identifier: BUSL-1.1
"""采集 pipeline 编排：多平台并发 + ⭐ 失败隔离（移植自项目 A app/pipeline.py）。

⭐ 硬规则：单个平台抛错（网络超时/反爬/解析失败）只记入 detail，
绝不中断其他平台；collect_all 永远返回汇总而不是抛错。
"""

from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from .base import NotConfiguredError, _REGISTRY, get_collector
from .models import HotItem
from .normalize import dedup, normalize


def _collect_one(name: str) -> tuple[str, list[HotItem] | None, str | None, str | None]:
    """采单个平台；返回 (平台码, 条目|None, 错误|None, 未配置原因|None)。"""
    try:
        collector = get_collector(name)
        if not collector.enabled:
            return name, None, None, "已禁用"
        return name, collector.collect(), None, None
    except NotConfiguredError as exc:
        return name, None, None, str(exc)
    except Exception as exc:  # noqa: BLE001 — ⭐ 失败隔离点
        return name, None, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=2)}", None


def collect_all(
    platforms: list[str] | None = None,
    max_workers: int = 8,
    *,
    normalize_scores: bool = True,
    dedup_items: bool = True,
) -> dict:
    """采集全部（或指定）平台热榜，返回汇总（对齐 A 的 hot.py collect 命令输出字段）。

    返回：{ok_count, fail_count, total_items, new_count(去重后),
           duration_ms, items, detail{平台码: {count} 或 {error}}}
    """
    from . import collectors  # noqa: F401 触发注册

    names = list(platforms) if platforms else sorted(_REGISTRY.keys())
    unknown = [n for n in names if n not in _REGISTRY]
    if unknown:
        raise ValueError(f"未知平台：{', '.join(unknown)}（可用 platform_catalog() 查看）")

    started = time.time()
    items: list[HotItem] = []
    detail: dict[str, dict] = {}
    ok_count, fail_count, skip_count = 0, 0, 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for name, result, error, skipped in pool.map(_collect_one, names):
            if skipped is not None:
                skip_count += 1
                detail[name] = {"skipped": skipped}
            elif error is None:
                ok_count += 1
                items.extend(result or [])
                detail[name] = {"count": len(result or [])}
            else:
                fail_count += 1
                detail[name] = {"error": error}
    if normalize_scores:
        normalize(items)
    if dedup_items:
        items = dedup(items)
    return {
        "ok_count": ok_count,
        "fail_count": fail_count,
        "skip_count": skip_count,
        "total_items": sum(d.get("count", 0) for d in detail.values()),
        "new_count": len(items),
        "duration_ms": int((time.time() - started) * 1000),
        "items": [it.to_dict() for it in items],
        "detail": detail,
    }
