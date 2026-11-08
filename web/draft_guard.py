# SPDX-License-Identifier: BUSL-1.1
"""草稿归属校验路由类（R3-9 fail-closed · R11 自 admin.py 抽出为独立稳定模块）。

⭐ 为什么独立成模块：tests/test_nine_sixty.py 会 importlib.reload(web.admin)
   ——reload 会产生**新的类对象**，而 web/routers/* 在 sys.modules 中是缓存的
   旧模块，其路由实例仍属于旧类，isinstance 校验全部失效。
   抽到独立模块后，类身份跨 reload 稳定，reload 语义与拆分前完全一致。
"""
from __future__ import annotations

from fastapi import HTTPException, Request, Response  # noqa: F401
from fastapi.routing import APIRoute

from core import db

#: 豁免归属校验的前缀（分享令牌与公开预览本身不携带作者语义）
DID_OWNER_EXEMPT_PREFIXES = ("/s/", "/preview/")


class DraftOwnerRoute(APIRoute):
    """R3-9：对所有带 {did} 的路由强制校验草稿归属（fail-closed）。"""

    def get_route_handler(self):
        original = super().get_route_handler()
        if "{did}" not in self.path or self.path.startswith(DID_OWNER_EXEMPT_PREFIXES):
            return original

        async def guarded(request: Request) -> Response:
            # 晚绑定：admin 模块在路由首次匹配时早已完整加载
            from web import admin as _a

            u = _a.get_current_user(request)
            # 未登录：交给下游 guard() 处理，保持 401 语义统一；
            # 这里放行不代表能访问——所有业务路由自身都会再 guard() 一次。
            if u and not _a._is_admin_user(u):
                did = str(request.path_params.get("did") or "")
                draft = db.get_draft(did) if did else None
                if not db.is_draft_owner(draft, _a._current_user_id(u), is_admin=False):
                    # 刻意用 404 而非 403：403 等于确认「该 id 存在」，
                    # 反而给了遍历 did 探测的口子。
                    raise HTTPException(404, "草稿不存在或无权访问")
            return await original(request)

        return guarded
