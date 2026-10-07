# SPDX-License-Identifier: BUSL-1.1
"""认证路由：POST /api/auth/register、/login、/logout、GET /me、/status，
以及 POST /login 兼容别名（deprecated）。

本文件只挂路由；业务逻辑在 studio/auth.py。供 WS-D 的 studio/main.py
``app.include_router(auth_router)`` 挂载；测试也可直接挂载验证。

⭐ 安全：任何响应都绝不携带 password_hash / salt。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import errors
from .auth import (
    SESSION_COOKIE,
    SESSION_TTL_SEC,
    authenticate,
    create_session_token,
    ensure_default_tenant,
    get_current_tenant,
    get_current_user,
    get_db,
    register_user,
)
from .db_models import Tenant, User
from .membership import service as membership_service

router = APIRouter()


class RegisterIn(BaseModel):
    """注册入参。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str = Field(default="", max_length=256)
    invite_code: str | None = None


class LoginIn(BaseModel):
    """登录入参。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def _iso(dt: datetime | None) -> str | None:
    """datetime → ISO-8601 UTC 字符串（SQLite 读出的 naive 时间补 UTC）。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _public_user(user: User) -> dict:
    """⭐ 用户对外视图：显式只取安全字段，password_hash / salt 永不外泄。"""
    return {"id": user.id, "username": user.username, "role": user.role}


def _membership_view(db: Session, user: User) -> dict:
    m = membership_service.ensure_membership(db, user.tenant_id, user.id)
    db.commit()
    return {
        "tier": m.tier,
        "credits_total": int(m.credits_total),
        "credits_used": int(m.credits_used),
        "credits_left": membership_service.credits_left(m),
    }


def _do_login(db: Session, body: LoginIn) -> tuple[dict, str]:
    """登录核心：校验 → 签发 token；失败统一 401（不透露用户名/密码哪个错）。"""
    tenant = ensure_default_tenant(db)
    user = authenticate(db, tenant, body.username, body.password)
    if user is None:
        # ⭐ 用户名或密码错误统一返回 401，防止攻击者枚举已注册用户名
        errors.raise_err("UNAUTHORIZED", "用户名或密码不正确")
    db.commit()
    token = create_session_token(user)
    return _public_user(user), token


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_SEC,
        path="/",
        httponly=True,
        samesite="lax",
    )


@router.post("/api/auth/register", status_code=201)
def api_register(body: RegisterIn, db: Session = Depends(get_db)):
    """用户自助注册（invite-only 下需邀请码）。201 返回新建用户摘要。"""
    tenant = ensure_default_tenant(db)
    user = register_user(
        db,
        tenant,
        body.username,
        body.password,
        email=body.email,
        invite_code=body.invite_code,
    )
    return errors.ok({"user": _public_user(user)})


@router.post("/api/auth/login")
def api_login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    """登录：校验通过后写 HttpOnly 会话 Cookie。"""
    user_view, token = _do_login(db, body)
    _set_session_cookie(response, token)
    return errors.ok({"user": user_view})


@router.post(
    "/login",
    deprecated=True,
    summary="旧路径兼容别名（deprecated），行为同 POST /api/auth/login",
)
def login_compat(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    """POST /login：兼容别名，行为与 /api/auth/login 完全一致。"""
    user_view, token = _do_login(db, body)
    _set_session_cookie(response, token)
    return errors.ok({"user": user_view})


@router.post("/api/auth/logout")
def api_logout(response: Response):
    """退出登录：清除会话 Cookie。"""
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return errors.ok({"logged_out": True})


@router.get("/api/auth/me")
def api_auth_me(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """当前用户资料：用户 + 租户 + 会员额度摘要。"""
    return errors.ok(
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "launch_mode": tenant.launch_mode,
            },
            "membership": _membership_view(db, user),
        }
    )


@router.get("/api/auth/status")
def auth_status(
    request: Request,
    db: Session = Depends(get_db),
):
    """登录状态查询：未登录返回 logged_in=false（不抛 401，方便前端探活）。"""
    from .auth import get_current_user_optional

    user = get_current_user_optional(request, db)
    if user is None:
        return errors.ok({"logged_in": False, "user": None})
    return errors.ok({"logged_in": True, "user": _public_user(user)})
