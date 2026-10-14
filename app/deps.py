# SPDX-License-Identifier: BUSL-1.1
"""统一请求上下文与依赖注入（RequestContext & FastAPI Dependencies）。"""
from __future__ import annotations

from dataclasses import dataclass
from fastapi import Request
from domain.billing.service import billing_service
from studio import billing_adapter


@dataclass
class RequestContext:
    user_id: str
    username: str
    role: str
    tenant_id: str
    is_admin: bool


def build_request_context(request: Request, user: dict) -> RequestContext:
    uid = str((user or {}).get("id") or "u-admin")
    role = str((user or {}).get("role") or "user")
    db = billing_adapter._web_session()
    try:
        tid = billing_service.ensure_user_context(db, uid, user)
    finally:
        db.close()
    return RequestContext(
        user_id=uid,
        username=str((user or {}).get("username") or uid),
        role=role,
        tenant_id=tid,
        is_admin=role in ("admin", "owner"),
    )
