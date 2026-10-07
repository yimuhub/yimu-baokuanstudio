# SPDX-License-Identifier: BUSL-1.1
"""网关管理路由：/api/gw/keys、/api/gw/ledger、/api/gw/upstreams（需管理员）。

⭐ 关键规则（违反后果）：
- 所有查询必须带 tenant_id 过滤；按 id 查到的资源若属其他租户 → 403
  （tenant_id 只从鉴权上下文注入，绝不信任客户端）。
- key_hash 永不返回前端；明文 Key 只在 POST /keys 的创建响应里返回一次，
  之后任何接口都查不到（只存哈希）。
- DELETE /keys/{id} 为吊销（status=revoked），不删行，保证账本可追溯。
- ledger 只增不改：本模块只有查询，没有写入口。
- 用户可见 message / hint 使用用户语言，禁用内部黑话。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from studio.db_models import GatewayKey, Ledger, Tenant, User, hash_gateway_key, new_id, utcnow

from .config import GatewayError, ok_body
from .deps import AdminAuth, get_db, key_public_dict, require_admin

router = APIRouter(prefix="/api/gw", tags=["gateway-admin"])

KEY_PREFIX_LEN = 12  # 明文 Key 前缀展示长度，如 yimu_sk_ab12


def _resolve_tenant(
    db: Session, admin: AdminAuth, tenant_id: str | None, *, required: bool = True
) -> str:
    """确定本次管理操作的租户。

    - session 管理员：只能操作自己的租户（传入的不一致 → 403）。
    - 环境变量密钥管理员：必须显式指定 tenant_id。
    """
    if admin.tenant_id is not None:
        if tenant_id is not None and tenant_id != admin.tenant_id:
            raise GatewayError("FORBIDDEN", "无权操作其他工作区的数据", "请使用本工作区范围内的资源")
        return admin.tenant_id
    if not tenant_id:
        if required:
            raise GatewayError("BAD_REQUEST", "缺少 tenant_id 参数", "请在请求中指定要操作的工作区 id")
        return ""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise GatewayError("NOT_FOUND", "指定的工作区不存在", "请检查 tenant_id 是否正确")
    return tenant_id


def _get_key_scoped(db: Session, admin: AdminAuth, key_id: str) -> GatewayKey:
    """按 id 取 Key；不存在 → 404；属其他租户 → 403（⭐ 租户隔离）。"""
    key = db.get(GatewayKey, key_id)
    if key is None:
        raise GatewayError("NOT_FOUND", "该 Key 不存在", "请检查 Key id 是否正确")
    if admin.tenant_id is not None and key.tenant_id != admin.tenant_id:
        raise GatewayError("FORBIDDEN", "无权操作其他工作区的数据", "请使用本工作区范围内的资源")
    return key


def _parse_iso_datetime(value: str | None, field: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GatewayError("BAD_REQUEST", f"{field} 时间格式错误", "请使用 ISO-8601 格式，如 2026-10-06T12:00:00Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Key 发放与管理
# ---------------------------------------------------------------------------


@router.get("/keys")
async def list_keys(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminAuth = Depends(require_admin),
    tenant_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Key 列表（分页；永不返回明文与 key_hash）。"""
    tenant = _resolve_tenant(db, admin, tenant_id, required=False)
    q = db.query(GatewayKey)
    if tenant:
        q = q.filter(GatewayKey.tenant_id == tenant)
    total = q.count()
    keys = q.order_by(GatewayKey.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok_body(
        {
            "items": [key_public_dict(k) for k in keys],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/keys")
async def issue_key(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminAuth = Depends(require_admin),
):
    """发放 Key：明文 Key 只在本次响应返回一次，之后永远查不到。

    请求体：{tenant_id?, user_id?, name, quota_credits, rate_limit_rpm,
             rate_limit_tpm, allowed_models?, ip_allowlist?, expires_at?}
    """
    try:
        body = await request.json()
    except ValueError:
        raise GatewayError("BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式")
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")

    tenant_id = _resolve_tenant(db, admin, body.get("tenant_id"))
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.is_active:
        raise GatewayError("FORBIDDEN", "指定的工作区不存在或已停用", "请检查 tenant_id 是否正确")

    user_id = body.get("user_id") or (admin.user.id if admin.user else None)
    if not user_id:
        raise GatewayError("BAD_REQUEST", "缺少 user_id 参数", "请指定该 Key 的归属用户")
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or not user.is_active:
        raise GatewayError("BAD_REQUEST", "指定的用户不存在或不在该工作区内", "请检查 user_id 是否正确")

    # ⭐ 明文 Key 只在此刻存在：生成 → 取哈希入库 → 响应返回一次
    raw_key = "yimu_sk_" + secrets.token_urlsafe(32)
    key = GatewayKey(
        id=new_id(),
        tenant_id=tenant_id,
        user_id=user_id,
        key_prefix=raw_key[:KEY_PREFIX_LEN],
        key_hash=hash_gateway_key(raw_key),
        name=str(body.get("name", "")),
        quota_credits=int(body.get("quota_credits", 0) or 0),
        rate_limit_rpm=int(body.get("rate_limit_rpm", 60) or 60),
        rate_limit_tpm=int(body.get("rate_limit_tpm", 100000) or 100000),
        allowed_models=body.get("allowed_models"),
        ip_allowlist=body.get("ip_allowlist"),
        status="active",
        expires_at=_parse_iso_datetime(body.get("expires_at"), "expires_at"),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(key)
    db.commit()
    data = key_public_dict(key)
    data["key"] = raw_key  # ⭐ 仅此一次返回明文；之后任何接口都查不到
    data["prefix"] = data["key_prefix"]  # 契约字段别名
    data["_warning"] = "请立即保存该 Key，明文不会再次显示"
    return ok_body(data)


@router.patch("/keys/{key_id}")
async def update_key(
    key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminAuth = Depends(require_admin),
):
    """更新 Key 的配额 / 限速 / 白名单等（不含 status，吊销请走 DELETE）。"""
    key = _get_key_scoped(db, admin, key_id)
    try:
        body = await request.json()
    except ValueError:
        raise GatewayError("BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式")
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")
    updatable = (
        "name",
        "quota_credits",
        "rate_limit_rpm",
        "rate_limit_tpm",
        "allowed_models",
        "ip_allowlist",
        "expires_at",
    )
    changed = False
    for field_name in updatable:
        if field_name in body:
            value = body[field_name]
            if field_name == "expires_at":
                value = _parse_iso_datetime(value, "expires_at")
            elif field_name in ("quota_credits", "rate_limit_rpm", "rate_limit_tpm"):
                value = int(value or 0)
            setattr(key, field_name, value)
            changed = True
    if changed:
        key.updated_at = utcnow()
        db.commit()
    return ok_body(key_public_dict(key))


@router.delete("/keys/{key_id}")
async def revoke_key(
    key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminAuth = Depends(require_admin),
):
    """吊销 Key：status 置为 revoked，不删行（保证历史账本可追溯）。"""
    key = _get_key_scoped(db, admin, key_id)
    key.status = "revoked"
    key.updated_at = utcnow()
    db.commit()
    return ok_body(key_public_dict(key))


# ---------------------------------------------------------------------------
# 账本查询
# ---------------------------------------------------------------------------


def _ledger_item(row: Ledger) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "key_id": row.key_id,
        "model": row.model,
        "direction": row.direction,
        "tokens": row.tokens,
        "cost_cents": row.cost_cents,
        "latency_ms": row.latency_ms,
        "cached": row.cached,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/ledger")
async def query_ledger(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminAuth = Depends(require_admin),
    tenant_id: str | None = Query(default=None),
    key_id: str | None = Query(default=None),
    model: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """调用账本查询：按 key / model / 日期过滤 + 分页（page_size ≤ 100）。"""
    tenant = _resolve_tenant(db, admin, tenant_id, required=False)
    q = db.query(Ledger)
    if tenant:
        q = q.filter(Ledger.tenant_id == tenant)
    if key_id:
        # ⭐ 租户隔离：key 必须属于当前租户，否则 403
        key = db.get(GatewayKey, key_id)
        if key is None:
            raise GatewayError("NOT_FOUND", "指定的 Key 不存在", "请检查 key_id 是否正确")
        if tenant and key.tenant_id != tenant:
            raise GatewayError("FORBIDDEN", "无权查看其他工作区的数据", "请使用本工作区范围内的资源")
        q = q.filter(Ledger.key_id == key_id)
    if model:
        q = q.filter(Ledger.model == model)
    dt_from = _parse_iso_datetime(date_from, "date_from")
    dt_to = _parse_iso_datetime(date_to, "date_to")
    if dt_from:
        q = q.filter(Ledger.created_at >= dt_from)
    if dt_to:
        q = q.filter(Ledger.created_at <= dt_to)
    total = q.count()
    rows = (
        q.order_by(Ledger.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok_body(
        {
            "items": [_ledger_item(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


# ---------------------------------------------------------------------------
# 上游健康与手动上下线
# ---------------------------------------------------------------------------


def _upstream_public(entry) -> dict[str, Any]:
    """上游状态展示：含熔断器状态，不含任何密钥。"""
    cfg = entry.cfg
    info = {
        "id": cfg.id,
        "base_url": cfg.base_url,
        "models": cfg.models,
        "timeout_sec": cfg.timeout_sec,
        "echo": cfg.echo,
    }
    info.update(entry.breaker.to_dict())
    return info


@router.get("/upstreams")
async def list_upstreams(
    request: Request,
    admin: AdminAuth = Depends(require_admin),
):
    """上游健康与熔断状态（不含密钥）。"""
    pool = request.app.state.upstream_pool
    return ok_body({"data": [_upstream_public(e) for e in pool]})


@router.post("/upstreams/{upstream_id}/toggle")
async def toggle_upstream(
    upstream_id: str,
    request: Request,
    admin: AdminAuth = Depends(require_admin),
):
    """手动上下线：请求体可选 {enabled: bool}，缺省则翻转当前状态。"""
    pool = request.app.state.upstream_pool
    entry = next((e for e in pool if e.cfg.id == upstream_id), None)
    if entry is None:
        raise GatewayError("NOT_FOUND", f"上游 {upstream_id} 不存在", "请通过 GET /api/gw/upstreams 查看可用上游")
    try:
        body = await request.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "enabled" in body:
        enabled = bool(body["enabled"])
    else:
        enabled = not entry.breaker.enabled
    entry.breaker.set_enabled(enabled)
    return ok_body(_upstream_public(entry))
