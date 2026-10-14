# SPDX-License-Identifier: BUSL-1.1
"""认证与会话：注册 / 登录 / 会话签发与鉴权依赖（无路由，只有函数与依赖）。

会话机制：无状态 HMAC 签名 token，不新增表（避免改动冻结 schema）。
token = base64url(json({uid, tenant_id, exp})) + "." + hex(HMAC_SHA256(密钥, 载荷))。

⭐ 安全红线：会话签名密钥只从环境变量 YIMU_SECRET_KEY 读取，
   缺失时本模块在 import 阶段直接 raise RuntimeError，服务拒绝启动。
   绝不设置任何默认值——默认密钥等于没有密钥，这是 C-1 重写的核心要求。

⭐ 租户隔离：所有业务查询一律 WHERE tenant_id；token 里的 tenant_id
   与 users 表记录交叉校验，不一致即视为伪造/跨租户访问 → 401。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import errors
from .db import get_engine, get_session_factory as _make_session_factory, init_db
from .db_models import AuditLog, Membership, Tenant, User, hash_password, new_id, utcnow
from .membership import service as membership_service

# ---------------------------------------------------------------------------
# ⭐ 会话签名密钥：只走环境变量，缺失直接拒绝启动（无默认值）
# ---------------------------------------------------------------------------
_SIGNING_SECRET = os.environ.get("YIMU_SECRET_KEY")
if not _SIGNING_SECRET:
    raise RuntimeError(
        "YIMU_SECRET_KEY 环境变量未设置：会话签名密钥缺失，"
        "为防止使用默认密钥导致会话可被伪造，服务拒绝启动。"
        "请在启动前设置该环境变量（生产环境请使用随机生成的长字符串）。"
    )
_SIGNING_KEY = _SIGNING_SECRET.encode("utf-8")

# 会话有效期：7 天（秒）
SESSION_TTL_SEC = 7 * 24 * 3600
# 会话 Cookie 名（与契约 §2.1「Studio 浏览器 Cookie session」对应）
SESSION_COOKIE = "yimu_session"


# ---------------------------------------------------------------------------
# 会话 token 的签发与解析
# ---------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def create_session_token(user: User) -> str:
    """为用户签发会话 token（7 天有效）。

    ⭐ 只把 uid / tenant_id / exp 放进载荷；password_hash / salt
       永远不进 token，也不返回给前端。
    """
    payload = {
        "uid": user.id,
        "tenant_id": user.tenant_id,
        "exp": int(time.time()) + SESSION_TTL_SEC,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_SIGNING_KEY, raw, hashlib.sha256).hexdigest()
    return f"{_b64e(raw)}.{sig}"


def parse_session_token(token: str) -> dict | None:
    """验签并解析会话 token；签名不对 / 格式不对 / 过期 → 返回 None。

    兼容 studio.auth (yimu_session) 与 core.auth (mf_v6_token) 两种签名载荷。
    """
    try:
        payload_b64, sig = token.split(".", 1)
        raw = _b64d(payload_b64)
        expected_raw = hmac.new(_SIGNING_KEY, raw, hashlib.sha256).hexdigest()
        expected_b64 = hmac.new(_SIGNING_KEY, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        live_secret = os.environ.get("YIMU_SECRET_KEY", "").encode("utf-8")
        expected_live_b64 = hmac.new(live_secret, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest() if live_secret else ""
        sig_ok = (
            hmac.compare_digest(expected_raw, sig)
            or hmac.compare_digest(expected_b64, sig)
            or (bool(expected_live_b64) and hmac.compare_digest(expected_live_b64, sig))
        )
        if not sig_ok:
            return None
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        if float(payload.get("exp", 0)) < time.time():
            return None
        if not payload.get("uid") and payload.get("user_id"):
            payload["uid"] = payload["user_id"]
        if not payload.get("uid") or not payload.get("tenant_id"):
            return None
        return payload
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# DB session 依赖（DB URL 取环境变量 YIMU_DB_URL，默认本地 SQLite）
# ---------------------------------------------------------------------------
_session_factory = None


def get_session_factory():
    """返回缓存的 Session 工厂（首调时按 YIMU_DB_URL 建引擎并建表）。"""
    global _session_factory
    if _session_factory is None:
        db_url = os.environ.get("YIMU_DB_URL", "sqlite:///./data/yimu.db")
        engine = get_engine(db_url)
        init_db(engine)
        _session_factory = _make_session_factory(engine)
    return _session_factory


def get_db():
    """FastAPI 依赖：按请求提供 DB session，用完自动关闭。"""
    factory = get_session_factory()
    with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# 鉴权依赖
# ---------------------------------------------------------------------------
def _token_from_request(request: Request) -> str | None:
    """先读 Cookie yimu_session / mf_v6_token；没有再看 Authorization: Bearer（供 CLI/API）。"""
    token = request.cookies.get(SESSION_COOKIE) or request.cookies.get("mf_v6_token")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """⭐ 鉴权主依赖：解析会话 → 查用户（WHERE tenant_id 且 is_active）。

    失败一律 401，不透露是「用户不存在」「被禁用」还是「签名不对」，
    防止攻击者逐个试探枚举账号。
    """
    token = _token_from_request(request)
    if not token:
        errors.raise_err("UNAUTHORIZED", "未登录，请先登录")
    payload = parse_session_token(token)
    if payload is None:
        errors.raise_err("UNAUTHORIZED", "登录已失效，请重新登录")
    # ⭐ 交叉校验：token 里的 tenant_id 必须与 users 表记录一致，
    #    防止用 A 租户的合法 token 访问 B 租户数据。
    user = (
        db.query(User)
        .filter(
            User.id == payload["uid"],
            User.tenant_id == payload["tenant_id"],
            User.is_active.is_(True),
        )
        .first()
    )
    if user is None:
        errors.raise_err("UNAUTHORIZED", "登录已失效，请重新登录")
    return user


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    """可选鉴权：未登录返回 None（供网关管理类接口的宽松场景使用）。"""
    try:
        return get_current_user(request, db)
    except Exception:
        return None


def require_admin(user: User = Depends(get_current_user)) -> User:
    """管理员鉴权：role 不在 ('owner', 'admin') → 403。"""
    if user.role not in ("owner", "admin"):
        errors.raise_err("FORBIDDEN", "需要管理员权限")
    return user


def get_current_tenant(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Tenant:
    """取当前用户所属租户；租户被停用/删除 → 401（登录态整体失效）。"""
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == user.tenant_id, Tenant.is_active.is_(True))
        .first()
    )
    if tenant is None:
        errors.raise_err("UNAUTHORIZED", "所属租户已停用，请联系管理员")
    return tenant


def ensure_default_tenant(db: Session) -> Tenant:
    """取 name='default' 的租户；不存在则创建（launch_mode='invite-only'）。"""
    tenant = db.query(Tenant).filter(Tenant.name == "default").first()
    if tenant is None:
        tenant = Tenant(
            id=new_id(),
            name="default",
            plan="free",
            launch_mode="invite-only",
            is_active=True,
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    return tenant


# ---------------------------------------------------------------------------
# 注册与登录
# ---------------------------------------------------------------------------
def _validate_register_input(username: str, password: str) -> tuple[str, str]:
    username = (username or "").strip()
    if not username or len(username) > 64:
        errors.raise_err("BAD_REQUEST", "用户名不能为空且不超过 64 个字符")
    if len(password or "") < 8:
        errors.raise_err("BAD_REQUEST", "密码至少 8 位")
    return username, password


def register_user(
    db: Session,
    tenant: Tenant,
    username: str,
    password: str,
    email: str = "",
    invite_code: str | None = None,
) -> User:
    """注册用户：用户名同租户唯一 → 邀请码核销（invite-only 必填）→
    建 user + free 会员档 → 写审计日志。
    """
    username, password = _validate_register_input(username, password)
    email = (email or "").strip()

    exists = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.username == username)
        .first()
    )
    if exists is not None:
        errors.raise_err("CONFLICT", "用户名已被使用，请换一个")

    invite = None
    invite_code = (invite_code or "").strip()
    if tenant.launch_mode == "invite-only" and not invite_code:
        errors.raise_err(
            "BAD_REQUEST",
            "当前为邀请制注册，请填写邀请码",
            hint="请联系管理员获取邀请码",
        )
    if invite_code:
        invite = membership_service._redeem_invite_atomic(db, tenant, invite_code)

    user_count = (
        db.query(User).filter(User.tenant_id == tenant.id).count()
    )
    password_hash, salt = hash_password(password)
    user = User(
        id=new_id(),
        tenant_id=tenant.id,
        username=username,
        email=email,
        password_hash=password_hash,
        salt=salt,
        role="owner" if user_count == 0 else "user",
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        errors.raise_err("CONFLICT", "用户名已被使用，请换一个")

    membership = Membership(
        id=new_id(),
        tenant_id=tenant.id,
        user_id=user.id,
        tier="free",
        credits_total=membership_service.tier_credits("free"),
        credits_used=0,
        period_start=utcnow(),
        period_end=None,
        status="active",
    )
    if invite is not None and int(invite.credits_grant) > 0:
        membership.credits_total = int(membership.credits_total) + int(
            invite.credits_grant
        )
    db.add(membership)

    db.add(
        AuditLog(
            id=new_id(),
            tenant_id=tenant.id,
            actor=user.id,
            action="user.register",
            target=f"user:{user.id}",
            detail={
                "username": username,
                "role": user.role,
                "invite_code": invite.code if invite else None,
            },
        )
    )
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, tenant: Tenant, username: str, password: str) -> User | None:
    """校验用户名密码；成功返回 User（并更新 last_login_at），失败返回 None。"""
    username = (username or "").strip()
    if not username or not password:
        return None
    user = (
        db.query(User)
        .filter(
            User.tenant_id == tenant.id,
            User.username == username,
            User.is_active.is_(True),
        )
        .first()
    )
    if user is None:
        return None
    from .db_models import verify_password

    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utcnow()
    return user
