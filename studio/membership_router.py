# SPDX-License-Identifier: BUSL-1.1
"""会员与首发模式路由：会员自查、launch_mode 开关、邀请码发放/列表。

注意：契约 §7 的 ``POST /api/auth/register`` 就是 auth_router 的注册路由，
本文件不再重复实现注册逻辑；邀请码核销统一走 membership/service。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import errors
from .auth import get_current_tenant, get_current_user, get_db, require_admin
from .db_models import AuditLog, Invite, Tenant, User, new_id
from .membership import service as membership_service

router = APIRouter()


class LaunchModeIn(BaseModel):
    """首发模式入参。"""

    launch_mode: str = Field(description="invite-only（邀请制）或 public（公开注册）")


class InviteCreateIn(BaseModel):
    """发放邀请码入参。"""

    max_uses: int = Field(default=1, ge=1, le=10000)
    credits_grant: int = Field(default=0, ge=0)
    expires_at: str | None = Field(
        default=None, description="ISO-8601 时间，可空表示永不过期"
    )


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_expires_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        errors.raise_err("BAD_REQUEST", "过期时间格式不正确，请使用 ISO-8601 格式")
    return dt


def _invite_view(invite: Invite) -> dict:
    # code 对管理员可见（管理员负责发放）；不含任何密钥类字段
    return {
        "id": invite.id,
        "code": invite.code,
        "max_uses": int(invite.max_uses),
        "used_count": int(invite.used_count),
        "credits_grant": int(invite.credits_grant),
        "expires_at": _iso(invite.expires_at),
        "status": invite.status,
        "created_at": _iso(invite.created_at),
    }


@router.get("/api/membership/me")
def membership_me(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """我的会员档位与剩余额度（需登录）。"""
    m = membership_service.ensure_membership(db, user.tenant_id, user.id)
    db.commit()
    return errors.ok(
        {
            "tier": m.tier,
            "tier_name": membership_service.tier_name(m.tier),
            "credits_total": int(m.credits_total),
            "credits_used": int(m.credits_used),
            "credits_left": membership_service.credits_left(m),
            "period_start": _iso(m.period_start),
            "period_end": _iso(m.period_end),
            "status": m.status,
        }
    )


@router.get("/api/admin/launch_mode")
def get_launch_mode(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    tenant: Tenant = Depends(get_current_tenant),
):
    """查询当前租户的首发模式（需管理员）。"""
    return errors.ok({"launch_mode": tenant.launch_mode})


@router.put("/api/admin/launch_mode")
def set_launch_mode(
    body: LaunchModeIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    tenant: Tenant = Depends(get_current_tenant),
):
    """切换首发模式 invite-only / public（需管理员），并写审计日志。"""
    mode = (body.launch_mode or "").strip()
    if mode not in ("invite-only", "public"):
        errors.raise_err(
            "BAD_REQUEST",
            "首发模式只能是 invite-only 或 public",
        )
    old = tenant.launch_mode
    if old != mode:
        tenant.launch_mode = mode
        db.add(
            AuditLog(
                id=new_id(),
                tenant_id=tenant.id,
                actor=admin.id,
                action="tenant.launch_mode",
                target=f"tenant:{tenant.id}",
                detail={"old": old, "new": mode},
            )
        )
        db.commit()
        db.refresh(tenant)
    return errors.ok({"launch_mode": tenant.launch_mode})


@router.get("/api/admin/invites")
def list_invites(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    tenant: Tenant = Depends(get_current_tenant),
):
    """邀请码列表（需管理员，分页；⭐ 只查本租户）。"""
    q = (
        db.query(Invite)
        .filter(Invite.tenant_id == tenant.id)
        .order_by(Invite.created_at.desc())
    )
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return errors.ok(
        {
            "items": [_invite_view(i) for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/api/admin/invites", status_code=201)
def create_invite(
    body: InviteCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    tenant: Tenant = Depends(get_current_tenant),
):
    """发放邀请码（需管理员）：生成可读短码，返回完整记录。"""
    invite = membership_service.create_invite(
        db,
        tenant,
        max_uses=body.max_uses,
        credits_grant=body.credits_grant,
        expires_at=_parse_expires_at(body.expires_at),
        actor=admin.id,
    )
    return errors.ok({"invite": _invite_view(invite)})
