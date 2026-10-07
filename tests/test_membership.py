# SPDX-License-Identifier: BUSL-1.1
"""会员与认证测试：注册首发模式、登录会话、管理员鉴权、额度原子扣减、计费桥接。

覆盖：invite-only/public 注册、launch_mode 非法值、HttpOnly Cookie、
/me 额度视图、/status、/login 别名、管理员接口 401/403、
deduct_credits 原子性、billing_adapter 卡密与档位升级。
"""
# ⭐ 环境变量必须在任何 studio / gateway import 之前就绪
import os

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-ws-b")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")
os.environ.setdefault("YIMU_ADMIN_KEY", "test-admin-key-wsb-2026")

import pytest  # noqa: E402

from tests.wsb_common import (  # noqa: E402
    login_cookie,
    make_tenant_stack,
    studio_client,
    test_env,
    unique_name,
)


@pytest.fixture()
def owner_stack(db_session):
    """默认租户的 owner（幂等：已存在则复用；保证首发模式为 public 以便建号）。"""
    from studio.auth import ensure_default_tenant, register_user
    from studio.db_models import User

    tenant = ensure_default_tenant(db_session)
    if tenant.launch_mode != "public":
        tenant.launch_mode = "public"
        db_session.commit()
    user = (
        db_session.query(User)
        .filter(User.tenant_id == tenant.id, User.username == "wsb_owner")
        .first()
    )
    if user is None:
        user = register_user(db_session, tenant, "wsb_owner", "owner-pass-123")
    assert user.role == "owner", "首个用户应自动成为 owner"
    return {
        "tenant_id": tenant.id,
        "user_id": user.id,
        "username": user.username,
        "password": "owner-pass-123",
    }


@pytest.fixture()
def owner_cookie(studio_client, owner_stack):
    """owner 的会话 Cookie。"""
    return login_cookie(
        studio_client, owner_stack["username"], owner_stack["password"]
    )


def _set_launch_mode(db_session, mode: str) -> None:
    from studio.auth import ensure_default_tenant

    tenant = ensure_default_tenant(db_session)
    tenant.launch_mode = mode
    db_session.commit()


def test_register_invite_only_public_and_illegal_launch_mode(
    db_session, studio_client, owner_stack, owner_cookie
):
    """邀请制无码 400 / 有码 201；公开制无码可注册；非法首发模式 400。"""
    from studio.auth import ensure_default_tenant
    from studio.membership.service import create_invite

    _set_launch_mode(db_session, "invite-only")

    # 无码注册 → 400
    resp = studio_client.post(
        "/api/auth/register",
        json={"username": unique_name("u"), "password": "password123"},
    )
    assert resp.status_code == 400, f"邀请制无码应 400，实际 {resp.status_code}"

    # 有码注册 → 201
    tenant = ensure_default_tenant(db_session)
    invite = create_invite(
        db_session, tenant, max_uses=1, credits_grant=500, actor="test"
    )
    resp = studio_client.post(
        "/api/auth/register",
        json={
            "username": unique_name("u"),
            "password": "password123",
            "invite_code": invite.code,
        },
    )
    assert resp.status_code == 201, f"有码注册应 201：{resp.text[:300]}"
    assert resp.json()["data"]["user"]["role"] == "user"
    assert "password_hash" not in resp.text, "注册响应不得携带密码哈希"

    # 切到公开制 → 无码可注册
    resp = studio_client.put(
        "/api/admin/launch_mode",
        headers={"Cookie": f"yimu_session={owner_cookie}"},
        json={"launch_mode": "public"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["launch_mode"] == "public"
    resp = studio_client.post(
        "/api/auth/register",
        json={"username": unique_name("u"), "password": "password123"},
    )
    assert resp.status_code == 201, f"公开制无码应 201：{resp.text[:300]}"

    # 非法首发模式 → 400
    resp = studio_client.put(
        "/api/admin/launch_mode",
        headers={"Cookie": f"yimu_session={owner_cookie}"},
        json={"launch_mode": "everyone"},
    )
    assert resp.status_code == 400, f"非法首发模式应 400，实际 {resp.status_code}"


def test_login_sets_httponly_cookie_and_me_view(
    db_session, studio_client, owner_stack
):
    """登录写 HttpOnly Cookie；/me 返回额度且无密码哈希。"""
    _set_launch_mode(db_session, "public")
    username = unique_name("u")
    resp = studio_client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert resp.status_code == 201

    resp = studio_client.post(
        "/api/auth/login", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower(), "登录应写 HttpOnly 会话 Cookie"
    cookie = resp.cookies.get("yimu_session")
    assert cookie

    resp = studio_client.get(
        "/api/auth/me", headers={"Cookie": f"yimu_session={cookie}"}
    )
    assert resp.status_code == 200
    me = resp.json()["data"]
    assert me["username"] == username
    assert me["membership"]["credits_left"] == 10000, "新人默认额度应为 10000"
    assert "password_hash" not in resp.text, "/me 不得返回密码哈希"
    assert "salt" not in resp.text, "/me 不得返回盐值"


def test_status_and_login_alias(db_session, studio_client, owner_stack, owner_cookie):
    """/status 未登录/已登录；POST /login 别名行为一致。"""
    resp = studio_client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json()["data"]["logged_in"] is False

    resp = studio_client.get(
        "/api/auth/status", headers={"Cookie": f"yimu_session={owner_cookie}"}
    )
    assert resp.json()["data"]["logged_in"] is True
    assert resp.json()["data"]["user"]["username"] == "wsb_owner"

    # /login 别名
    resp = studio_client.post(
        "/login", json={"username": "wsb_owner", "password": "owner-pass-123"}
    )
    assert resp.status_code == 200
    assert resp.cookies.get("yimu_session"), "/login 别名也应写会话 Cookie"


def test_admin_endpoints_forbidden_and_unauthorized(
    db_session, studio_client, owner_stack
):
    """普通用户调管理接口 → 403；未登录 → 401。"""
    _set_launch_mode(db_session, "public")
    from studio.auth import ensure_default_tenant, register_user

    tenant = ensure_default_tenant(db_session)
    register_user(db_session, tenant, "wsb_normal", "normal-pass-123")
    user_cookie = login_cookie(studio_client, "wsb_normal", "normal-pass-123")

    resp = studio_client.get(
        "/api/admin/launch_mode",
        headers={"Cookie": f"yimu_session={user_cookie}"},
    )
    assert resp.status_code == 403, f"普通用户应 403，实际 {resp.status_code}"

    resp = studio_client.get("/api/admin/launch_mode")
    assert resp.status_code == 401, f"未登录应 401，实际 {resp.status_code}"

    resp = studio_client.get("/api/admin/invites")
    assert resp.status_code == 401


def test_deduct_credits_atomic_no_overdraw(db_session):
    """超扣被拒且额度不变；足额扣减成功。"""
    from studio.membership.service import (
        credits_left,
        deduct_credits,
        ensure_membership,
    )

    stack = make_tenant_stack(db_session, unique_name("deduct"))
    m = ensure_membership(db_session, stack["tenant_id"], stack["user_id"])
    m.credits_total = 100
    m.credits_used = 0
    db_session.commit()

    ok, left = deduct_credits(db_session, stack["tenant_id"], stack["user_id"], 150)
    assert ok is False, "超额扣减应被拒绝"
    assert left == 100, "拒绝后剩余额度应不变"
    db_session.refresh(m)
    assert m.credits_used == 0, "拒绝后已用额度应不变"

    ok, left = deduct_credits(db_session, stack["tenant_id"], stack["user_id"], 60)
    assert ok is True and left == 40
    db_session.refresh(m)
    assert m.credits_used == 60
    assert credits_left(m) == 40


def test_billing_adapter_ledger_cdkey_and_tier(db_session):
    """计费桥接：扣费写账本行；卡密生成/兑换/重复兑换拒绝；旧万能卡拒绝；档位升级。"""
    from studio import billing_adapter
    from studio.db_models import Ledger, Membership

    stack = make_tenant_stack(db_session, unique_name("bill"))
    tid, uid = stack["tenant_id"], stack["user_id"]

    before = billing_adapter.get_billing_status(db_session, tid, uid)["balance"]
    assert before == 10000

    # 扣费：写账本行，余额减少
    assert billing_adapter.check_and_deduct(db_session, tid, uid, "rewrite") is True
    cost = billing_adapter.ACTION_COSTS["rewrite"]
    row = (
        db_session.query(Ledger)
        .filter(Ledger.tenant_id == tid, Ledger.model == "billing:rewrite")
        .one_or_none()
    )
    assert row is not None, "扣费后应有账本行"
    assert row.cost_cents == cost
    after = billing_adapter.get_billing_status(db_session, tid, uid)["balance"]
    assert after == before - cost

    # 余额不足 → 拒绝且不写账本
    n_before = (
        db_session.query(Ledger).filter(Ledger.tenant_id == tid).count()
    )
    assert (
        billing_adapter.check_and_deduct(db_session, tid, uid, "rewrite", count=100)
        is False
    )
    n_after = db_session.query(Ledger).filter(Ledger.tenant_id == tid).count()
    assert n_after == n_before, "扣费失败不得产生账本行"

    # 卡密：生成 → 兑换 → 重复兑换被拒
    codes = billing_adapter.generate_cdkeys(
        db_session, tid, uid, key_type="tokens", amount=5000, count=2
    )
    assert len(codes) == 2 and all(c.startswith("YIMU-TOKEN-") for c in codes)
    bal_before = billing_adapter.get_billing_status(db_session, tid, uid)["balance"]
    result = billing_adapter.redeem_cdkey(db_session, tid, uid, codes[0])
    assert result["ok"] is True, f"首次兑换应成功：{result}"
    bal_after = billing_adapter.get_billing_status(db_session, tid, uid)["balance"]
    assert bal_after == bal_before + 5000
    again = billing_adapter.redeem_cdkey(db_session, tid, uid, codes[0])
    assert again["ok"] is False, "重复兑换应被拒绝"

    # 旧万能卡密不再有效
    for legacy in ("VIP999", "MEDIAFLOW888", "PRO2026"):
        bad = billing_adapter.redeem_cdkey(db_session, tid, uid, legacy)
        assert bad["ok"] is False, f"旧卡密 {legacy} 应被拒绝"

    # 档位升级
    bal_before = billing_adapter.get_billing_status(db_session, tid, uid)["balance"]
    assert billing_adapter.set_tier(db_session, tid, uid, "pro") is True
    ms = (
        db_session.query(Membership)
        .filter(Membership.tenant_id == tid, Membership.user_id == uid)
        .one()
    )
    assert ms.tier == "pro"
    grant = billing_adapter.DEFAULT_TIERS["pro"]["tokens_grant"]
    bal_after = billing_adapter.get_billing_status(db_session, tid, uid)["balance"]
    assert bal_after == bal_before + grant, "升级应按档位发放配额"
