# SPDX-License-Identifier: BUSL-1.1
"""功能登记 ↔ 路由实现 双向锁死测试（模板）。

- 读取 docs/CONTRACT.md 中标题含「路由清单」的节，
  用正则 ``- `([A-Z]+) ([^`]+)` `` 提取 (METHOD, path) 集合。
- 与 FastAPI app（studio.main:app）的 app.routes 做双向 diff：
  CONTRACT 有但 app 没有 → fail；app 有但 CONTRACT 没有 → fail。
- 骨架期（CONTRACT.md 缺失 / 路由清单为空 / app 未实现）→ skip 并打印中文提示。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_MD = REPO_ROOT / "docs" / "CONTRACT.md"

# 约定格式：- `METHOD /path` → handler（见 docs/CONTRACT.md 路由清单节）
ROUTE_RE = re.compile(r"- `([A-Z]+) ([^`]+)`")
# 标题含「路由清单」的节（兼容「## 5. Studio 主服务：路由清单（…）」这类编号标题）
SECTION_RE = re.compile(r"^##\s.*路由清单.*$", re.M)
NEXT_SECTION_RE = re.compile(r"^##\s", re.M)

# 自动挂载的辅助方法不参与锁死比对（如 Starlette 自动加的 HEAD/OPTIONS）
IGNORED_METHODS = {"HEAD", "OPTIONS", "TRACE"}
# FastAPI 自动生成的文档路由不参与锁死比对
IGNORED_PATHS = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}


def _load_contract_routes() -> set[tuple[str, str]]:
    """解析 CONTRACT.md 路由清单节；骨架期返回空集合并 skip。"""
    if not CONTRACT_MD.exists():
        pytest.skip(f"骨架期：{CONTRACT_MD} 尚未编写，跳过路由锁死检查。")
    text = CONTRACT_MD.read_text(encoding="utf-8")
    section_match = SECTION_RE.search(text)
    if not section_match:
        pytest.skip("骨架期：docs/CONTRACT.md 中没有「路由清单」节，跳过路由锁死检查。")
    body_start = section_match.end()
    next_match = NEXT_SECTION_RE.search(text, body_start)
    body = text[body_start : next_match.start() if next_match else len(text)]
    routes = {(method, path.strip()) for method, path in ROUTE_RE.findall(body)}
    if not routes:
        pytest.skip("骨架期：路由清单节暂无条目（待路由挖掘员填入），跳过路由锁死检查。")
    return routes


def _iter_expanded_routes(routes, prefix=""):
    """递归展开路由表：FastAPI 0.142+ 的 include_router 挂的是 _IncludedRouter
    懒加载节点（请求时才求值），直接遍历 app.routes 会漏掉被 include 的子路由。
    这里按 include_context.prefix 展开，还原 (route, 完整前缀) 供锁死比对。"""
    for route in routes or []:
        if type(route).__name__ == "_IncludedRouter":
            ctx = getattr(route, "include_context", None)
            sub_prefix = getattr(ctx, "prefix", "") or ""
            yield from _iter_expanded_routes(
                getattr(getattr(route, "original_router", None), "routes", []),
                prefix + sub_prefix,
            )
            continue
        yield route, prefix


def _load_app_routes() -> set[tuple[str, str]]:
    """读取 studio.main:app 的路由表；骨架期 skip。"""
    try:
        from studio.main import app  # type: ignore[import-not-found]
    except Exception as exc:  # 骨架期 app 尚未实现：任何导入失败都视为未实现
        pytest.skip(f"骨架期：无法导入 studio.main:app（{exc}），跳过路由锁死检查。")
    routes: set[tuple[str, str]] = set()
    for route, route_prefix in _iter_expanded_routes(getattr(app, "routes", [])):
        methods = {m for m in (getattr(route, "methods", None) or set()) if m not in IGNORED_METHODS}
        path = route_prefix + getattr(route, "path", "")
        if path in IGNORED_PATHS:
            continue
        for method in methods:
            routes.add((method, path))
    return routes


def test_contract_routes_match_app():
    """⭐ 双向锁死：登记的功能必须实现，实现的功能必须登记。"""
    contract_routes = _load_contract_routes()
    app_routes = _load_app_routes()

    only_in_contract = sorted(contract_routes - app_routes)
    only_in_app = sorted(app_routes - contract_routes)

    errors = []
    if only_in_contract:
        errors.append(
            "CONTRACT 登记了但 app 没有实现：\n"
            + "\n".join(f"  - `{method} {path}`" for method, path in only_in_contract)
        )
    if only_in_app:
        errors.append(
            "app 实现了但 CONTRACT 没有登记：\n"
            + "\n".join(f"  - `{method} {path}`" for method, path in only_in_app)
        )
    assert not errors, (
        "路由双向锁死检查失败——请同步 docs/CONTRACT.md 与 studio/main.py：\n\n" + "\n\n".join(errors)
    )
