# SPDX-License-Identifier: BUSL-1.1
"""租户隔离测试：A/B 两租户的账本、Key、会员额度互相不可见、不可操作。

覆盖：B 的管理员查不到 A 的账本；B 的管理员动不了 A 的 Key（403）；
会员额度按 tenant+user 隔离，跨租户扣减不影响对方。
"""
# ⭐ 环境变量必须在任何 studio / gateway import 之前就绪
import os

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-ws-b")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")
os.environ.setdefault("YIMU_ADMIN_KEY", "test-admin-key-wsb-2026")

from tests.wsb_common import (  # noqa: E402
    cookie_headers,
    gw_client,
    issue_gateway_key,
    make_tenant_stack,
    mint_session_cookie,
    studio_client,
    test_env,
    unique_name,
)


def _two_tenants(db_session):
    """建 A/B 两个租户栈，各带 owner 与会员档。"""
    a = make_tenant_stack(db_session, unique_name("iso-a"))
    b = make_tenant_stack(db_session, unique_name("iso-b"))
    return a, b


def test_ledger_invisible_across_tenants(db_session, gw_client, studio_client):
    """A 的账本：B 的管理员（Cookie 会话）查不到。"""
    a, b = _two_tenants(db_session)
    issued_a = issue_gateway_key(gw_client, a["tenant_id"], a["user_id"])

    # A 调一次，产生 2 行账本
    resp = gw_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {issued_a['raw']}"},
        json={"model": "yimu-chat",
              "messages": [{"role": "user", "content": "隔离测试"}]},
    )
    assert resp.status_code == 200

    # B 的管理员登录（Cookie 会话通道），查自己租户账本
    b_cookie = mint_session_cookie(db_session, b["tenant_id"], b["username"])
    resp = gw_client.get("/api/gw/ledger", headers=cookie_headers(b_cookie))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0, "B 租户账本应为空，看不到 A 的调用记录"
    assert all(
        row["tenant_id"] == b["tenant_id"] for row in data["items"]
    ), "账本行租户归属必须为 B"

    # B 的管理员用 tenant_id 参数显式指定 A → 应被拒绝
    resp = gw_client.get(
        "/api/gw/ledger",
        headers=cookie_headers(b_cookie),
        params={"tenant_id": a["tenant_id"]},
    )
    assert resp.status_code == 403, "跨租户查账本应 403"


def test_key_admin_ops_rejected_across_tenants(
    db_session, gw_client, studio_client
):
    """A 的 Key：B 的管理员无权查看 / 吊销（403）；B 只能看到自己的 Key。"""
    a, b = _two_tenants(db_session)
    issued_a = issue_gateway_key(gw_client, a["tenant_id"], a["user_id"])
    issued_b = issue_gateway_key(gw_client, b["tenant_id"], b["user_id"])

    b_cookie = mint_session_cookie(db_session, b["tenant_id"], b["username"])
    b_headers = cookie_headers(b_cookie)

    # B 看自己的 Key 列表：只有 B 的
    resp = gw_client.get("/api/gw/keys", headers=b_headers)
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert items, "B 应能看到自己的 Key"
    assert all(i["tenant_id"] == b["tenant_id"] for i in items)
    assert all(i["id"] != issued_a["id"] for i in items), "B 不应看到 A 的 Key"

    # B 试图吊销 A 的 Key → 403
    resp = gw_client.delete(f"/api/gw/keys/{issued_a['id']}", headers=b_headers)
    assert resp.status_code == 403, "跨租户吊销 Key 应 403"

    # A 的 Key 依然可用
    resp = gw_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {issued_a['raw']}"},
        json={"model": "yimu-chat",
              "messages": [{"role": "user", "content": "仍可用"}]},
    )
    assert resp.status_code == 200, "A 的 Key 不应被 B 的操作影响"


def test_membership_isolated_by_tenant_and_user(db_session, studio_client):
    """会员额度按 tenant+user 隔离：B 看到的是自己的；跨租户扣减不影响 A。"""
    from studio.membership.service import (
        credits_left,
        deduct_credits,
        ensure_membership,
    )

    a, b = _two_tenants(db_session)

    # 给 A 加一笔额度，B 保持默认
    m_a = ensure_membership(db_session, a["tenant_id"], a["user_id"])
    m_a.credits_total = 50000
    db_session.commit()

    # B 登录看自己的额度：应为默认档，不含 A 的加额
    b_cookie = mint_session_cookie(db_session, b["tenant_id"], b["username"])
    resp = studio_client.get(
        "/api/membership/me", headers=cookie_headers(b_cookie)
    )
    assert resp.status_code == 200
    me_b = resp.json()["data"]
    assert me_b["credits_total"] == 10000, "B 应看到自己的默认额度"
    assert me_b["credits_left"] == 10000

    # 拿 B 的身份去扣 A 租户的账 → 失败，A 的额度纹丝不动
    left_a_before = credits_left(
        ensure_membership(db_session, a["tenant_id"], a["user_id"])
    )
    ok, _ = deduct_credits(db_session, a["tenant_id"], b["user_id"], 10)
    assert ok is False, "跨租户的用户 id 不应扣到 A 的账上"
    left_a_after = credits_left(
        ensure_membership(db_session, a["tenant_id"], a["user_id"])
    )
    assert left_a_after == left_a_before, "A 的剩余额度应不受影响"

    # A 自己扣减正常
    ok, left = deduct_credits(db_session, a["tenant_id"], a["user_id"], 1000)
    assert ok is True and left == left_a_before - 1000
