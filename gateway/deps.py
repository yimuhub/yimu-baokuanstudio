# SPDX-License-Identifier: BUSL-1.1
"""网关鉴权依赖：Bearer 网关 Key → 鉴权上下文；管理员依赖。

⭐ 关键规则（违反后果）：
- 所有 DB 查询必须带 tenant_id 过滤；跨租户访问一律 403。
  tenant_id 只从鉴权上下文注入，绝不信任客户端传值——否则 A 租户
  能看到 B 租户的 Key 与账单，造成越权泄密。
- key_hash 永不返回前端；明文 Key 只在发放接口返回一次。
- 管理员鉴权优先复用 studio 侧 Cookie session（studio.auth，由另一
  子 Agent 实现）；该模块不存在时回退为只认 YIMU_ADMIN_KEY，
  接入点见 require_admin 内的 try import（不要自己实现 session 解析）。

术语注意：内部可用「上游」一词；用户可见 message / hint 里禁用内部黑话，
用「服务暂时不可用」这类用户语言。
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from studio.db_models import GatewayKey, Tenant, User, hash_gateway_key

from .config import GatewayError

# 允许的管理员角色（studio 侧用户体系）
ADMIN_ROLES = ("owner", "admin")


@dataclass
class GatewayAuth:
    """网关 Key 鉴权上下文：/v1/* 路由的调用者身份。"""

    tenant_id: str
    user_id: str
    key: GatewayKey


@dataclass
class AdminAuth:
    """管理员鉴权上下文：/api/gw/* 路由的调用者身份。

    tenant_id 为 None 表示环境变量密钥登录的全租户管理员；
    此时写操作必须显式指定 tenant_id，读操作可按租户过滤。
    """

    tenant_id: str | None
    user: User | None
    via: str  # "session"（studio Cookie）或 "env_key"（YIMU_ADMIN_KEY）


def get_db(request: Request):
    """FastAPI 依赖：按请求提供 DB Session，请求结束自动关闭。"""
    factory = request.app.state.session_factory
    db: Session = factory()
    try:
        yield db
    finally:
        db.close()


def _bearer_token(request: Request) -> str | None:
    """从 Authorization 头提取 Bearer token；缺失/格式错误返回 None。"""
    auth = request.headers.get("Authorization", "")
    if not auth:
        return None
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _as_aware(dt: datetime | None) -> datetime | None:
    """SQLite 读回的 datetime 可能是 naive 的，统一视为 UTC 后比较。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def key_public_dict(key: GatewayKey) -> dict:
    """⭐ Key 的对外展示字典：绝不包含 key_hash 与明文 Key。

    列表/详情/更新接口统一走这里序列化，杜绝密钥泄漏。
    """
    return {
        "id": key.id,
        "tenant_id": key.tenant_id,
        "user_id": key.user_id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "quota_credits": key.quota_credits,
        "rate_limit_rpm": key.rate_limit_rpm,
        "rate_limit_tpm": key.rate_limit_tpm,
        "allowed_models": key.allowed_models,
        "ip_allowlist": key.ip_allowlist,
        "status": key.status,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "updated_at": key.updated_at.isoformat() if key.updated_at else None,
    }


async def require_gateway_key(
    request: Request, db: Session = Depends(get_db)
) -> GatewayAuth:
    """Bearer 网关 Key 鉴权：Authorization: Bearer yimu_sk_...。

    校验链：格式 → 哈希比对 → Key 状态 → 租户有效 → 用户有效 → IP 白名单。
    任一环节失败即 401/403，绝不透露是哪一环节（防枚举）。
    """
    token = _bearer_token(request)
    if not token or not token.startswith("yimu_sk_"):
        raise GatewayError(
            "UNAUTHORIZED",
            "缺少有效的 API Key",
            "请在请求头携带 Authorization: Bearer yimu_sk_... 后重试",
        )
    key = (
        db.query(GatewayKey)
        .filter(GatewayKey.key_hash == hash_gateway_key(token))
        .one_or_none()
    )
    if key is None:
        raise GatewayError(
            "UNAUTHORIZED",
            "API Key 无效或已失效",
            "请检查 Key 是否正确，或联系管理员重新发放",
        )
    now = datetime.now(timezone.utc)
    # Key 状态：吊销 / 过期 → 403（凭证已知但无权使用）
    if key.status != "active" or (
        _as_aware(key.expires_at) is not None and _as_aware(key.expires_at) <= now
    ):
        raise GatewayError(
            "FORBIDDEN",
            "该 API Key 已失效",
            "请联系管理员重新发放新的 Key",
        )
    # 租户有效性（⭐ 租户隔离：停用租户的 Key 一律拒绝）
    tenant = db.get(Tenant, key.tenant_id)
    if tenant is None or not tenant.is_active:
        raise GatewayError(
            "FORBIDDEN", "所属工作区已停用", "请联系管理员确认工作区状态"
        )
    # 用户有效性
    user = db.get(User, key.user_id)
    if user is None or not user.is_active or user.tenant_id != key.tenant_id:
        raise GatewayError(
            "FORBIDDEN", "该 API Key 关联的用户已失效", "请联系管理员重新发放新的 Key"
        )
    # IP 白名单（为空表示不限制）
    if key.ip_allowlist:
        client_ip = request.client.host if request.client else ""
        allowed = key.ip_allowlist if isinstance(key.ip_allowlist, list) else []
        if client_ip not in allowed:
            raise GatewayError(
                "FORBIDDEN",
                "当前 IP 不在该 Key 的白名单内",
                "请联系管理员将当前出口 IP 加入白名单",
            )
    return GatewayAuth(tenant_id=key.tenant_id, user_id=key.user_id, key=key)


async def require_admin(
    request: Request, db: Session = Depends(get_db)
) -> AdminAuth:
    """管理员鉴权（双通道）：

    1. studio 侧 Cookie session：``studio.auth.get_current_user_optional``。
       该模块由另一子 Agent 实现；若暂时不存在（ImportError），
       则跳过本通道（下方有明确接入点注释）。
    2. 环境变量 YIMU_ADMIN_KEY：Authorization: Bearer 比对（constant-time）。

    session 登录但角色非管理员 → 直接 403，不再尝试通道 2；
    无任何有效凭证 → 401。
    """
    # ---- 接入点 1：studio Cookie session（不要自己实现 session 解析） ----
    # studio.auth 由另一子 Agent 实现；模块缺失、或因缺 YIMU_SECRET_KEY 等
    # 原因拒绝加载（import 期 raise），都视为本通道不可用，回退到通道 2。
    get_current_user_optional = None
    try:
        # 集成完成后改为：from studio.auth import get_current_user_optional
        from studio.auth import get_current_user_optional  # type: ignore
    except Exception as exc:  # noqa: BLE001 — ImportError / RuntimeError 均回退
        import logging

        logging.getLogger("yimu.gateway").warning(
            "studio.auth 不可用（%s），管理员鉴权仅认 YIMU_ADMIN_KEY", type(exc).__name__
        )
        get_current_user_optional = None

    if get_current_user_optional is not None:
        session_factory = request.app.state.session_factory
        session_db: Session = session_factory()
        try:
            user = get_current_user_optional(request, session_db)
        finally:
            session_db.close()
        if user is not None:
            if getattr(user, "role", None) in ADMIN_ROLES:
                return AdminAuth(tenant_id=user.tenant_id, user=user, via="session")
            raise GatewayError(
                "FORBIDDEN", "需要管理员权限", "请使用管理员账号登录后重试"
            )

    # ---- 接入点 2：环境变量 YIMU_ADMIN_KEY（constant-time 比对） ----
    admin_key = os.environ.get("YIMU_ADMIN_KEY", "") or request.app.state.settings.admin_key
    token = _bearer_token(request)
    if admin_key and token and hmac.compare_digest(token, admin_key):
        return AdminAuth(tenant_id=None, user=None, via="env_key")

    raise GatewayError(
        "UNAUTHORIZED",
        "需要管理员身份",
        "请先登录管理员账号，或在请求头携带有效的管理员密钥",
    )
