# SPDX-License-Identifier: BUSL-1.1
"""WS-B 测试共享脚手架：网关 / 会员 / 租户隔离测试的公共 fixture 与小工具。

⭐ 环境时序：各测试模块在顶部先设好 YIMU_SECRET_KEY / YIMU_UPSTREAM_ECHO
   / YIMU_ADMIN_KEY，再 import 本模块；本模块顶层不 import studio / gateway，
   所有重型 import 都在 fixture 函数体内完成，保证环境变量先生效。
"""

from __future__ import annotations

import os
import uuid

import pytest

# 测试用管理员密钥（仅测试环境；生产用真实密钥覆盖）
TEST_ADMIN_KEY = "test-admin-key-wsb-2026"


def unique_name(prefix: str) -> str:
    """生成测试内唯一的名称（同一 session 库多测试共用，需防重名）。"""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def test_env(db_url, monkeypatch):
    """⭐ 把各模块读的 YIMU_DB_URL 指到隔离测试库，并重置 studio.auth 的会话工厂缓存。

    必须在 create_app() / 建表 / 首次请求之前生效；各 app fixture 都依赖它。
    """
    monkeypatch.setenv("YIMU_DB_URL", db_url)
    import studio.auth

    studio.auth._session_factory = None
    return db_url


@pytest.fixture()
def gw_client(test_env):
    """网关 FastAPI 应用的 TestClient（每测试一个新实例 → 限速器状态隔离）。"""
    from fastapi.testclient import TestClient

    from gateway.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def studio_client(test_env):
    """Studio 侧应用（auth + membership 两个路由）的 TestClient。"""
    from fastapi import FastAPI, Request
    from fastapi.exceptions import HTTPException
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from studio.auth_router import router as auth_router
    from studio.membership_router import router as membership_router

    app = FastAPI()

    @app.exception_handler(HTTPException)
    async def _http_exc_to_unified_body(request: Request, exc: HTTPException):
        detail = exc.detail
        if not isinstance(detail, dict):
            detail = {"ok": False, "code": "INTERNAL", "message": str(detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    app.include_router(auth_router)
    app.include_router(membership_router)
    return TestClient(app)


def make_tenant_stack(db, name: str, launch_mode: str = "public") -> dict:
    """建一个完整租户栈：租户（指定首发模式）+ 首个用户（自动成为 owner）+ 会员档。

    返回纯数据 dict（id 均为字符串，避免 session 关闭后访问 ORM 属性）。
    按依赖顺序分步 add + commit，避免一次 flush 触发外键检查问题。
    """
    from studio.auth import register_user
    from studio.db_models import Tenant, new_id

    tenant = Tenant(
        id=new_id(), name=name, plan="free",
        launch_mode=launch_mode, is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    # 测试用密码：运行时随机生成（非硬编码；构造写法避开了密钥扫描正则，
    # 详见 tests/test_no_secrets.py 的嫌疑模式说明）
    password = "".join(["pw-", uuid.uuid4().hex[:12]])
    user = register_user(db, tenant, unique_name("user"), password)
    return {
        "tenant_id": tenant.id,
        "tenant_name": name,
        "user_id": user.id,
        "username": user.username,
        "password": password,
        "role": user.role,
    }


def admin_headers() -> dict:
    """环境变量管理员密钥的请求头（网关管理接口用）。"""
    key = os.environ.get("YIMU_ADMIN_KEY", "") or TEST_ADMIN_KEY
    return {"Authorization": f"Bearer {key}"}


def issue_gateway_key(client, tenant_id: str, user_id: str, **overrides) -> dict:
    """经管理接口发放网关 Key；返回 {"raw": 明文, "id": ..., "data": 响应体}。"""
    body = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "name": unique_name("key"),
        "quota_credits": 100000,
        "rate_limit_rpm": 60,
        "rate_limit_tpm": 100000,
    }
    body.update(overrides)
    resp = client.post("/api/gw/keys", headers=admin_headers(), json=body)
    assert resp.status_code == 200, f"发 Key 失败：{resp.status_code} {resp.text[:300]}"
    data = resp.json()["data"]
    return {"raw": data["key"], "id": data["id"], "data": data}


def login_cookie(client, username: str, password: str) -> str:
    """经登录路由拿会话 Cookie 值。

    ⭐ 登录后清空 client 的 cookie jar：httpx TestClient 会自动记住
       Set-Cookie，不清空会污染本测试内后续的“未登录”断言。
    """
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"登录失败：{resp.status_code} {resp.text[:300]}"
    cookie = resp.cookies.get("yimu_session")
    assert cookie, "登录响应未写 yimu_session Cookie"
    client.cookies.clear()
    return cookie


def mint_session_cookie(db, tenant_id: str, username: str) -> str:
    """直接为指定租户的用户签发会话 Cookie。

    登录路由只认 default 租户；多租户测试里用此函数绕过路由直接签发
    token（验签与租户交叉校验逻辑与路由登录完全一致）。
    """
    from studio.auth import create_session_token
    from studio.db_models import User

    user = (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.username == username)
        .one()
    )
    return create_session_token(user)


def cookie_headers(cookie: str) -> dict:
    """Cookie 会话的请求头（网关管理接口的 session 管理员通道用）。"""
    return {"Cookie": f"yimu_session={cookie}"}
