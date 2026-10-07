# SPDX-License-Identifier: BUSL-1.1
"""V7 主服务入口垫片：复用 B 的 FastAPI app（web/admin.py），不重写路由。

tests/test_contract_lock.py 通过本模块的 ``app`` 做 CONTRACT 双向锁死校验。
"""

from __future__ import annotations

from web.admin import app  # noqa: E402  (B 的 185 条路由全部保留)

__all__ = ["app"]
