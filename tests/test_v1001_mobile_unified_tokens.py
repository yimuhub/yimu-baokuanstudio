# SPDX-License-Identifier: BUSL-1.1
"""V10.0.1 移动端与 PC 端算力 Token 统一度量专项门禁测试。

核心验证：
1. 全站版本单一真源步进至 10.0.1（鸿蒙始 · Primordial Dawn）。
2. 后端 /api/auth/me 与 /api/billing/ui/me 统一度量真源，保证两端读取到的 credits_left、credits_total、credits_used、tier 完全一致。
3. /api/auth/me 将 quota_max 对齐为 memberships 表的实时 credits_left，杜绝遗留字段导致的口径漂移。
4. 移动端 (web/templates/mobile.html) 具备顶栏统一算力/会员药丸与个人中心商业化中枢，杜绝写死假额度（如 500,000 Token）。
"""
from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

import version
from web.admin import app

ROOT = Path(__file__).resolve().parent.parent


def test_v1001_version_single_source_of_truth():
    """验证版本单一真源兼容性与动态渲染。"""
    assert version.__version__ in ("10.1", "10.0.1")
    assert version.__codename__ == "鸿蒙始"

    # 验证 pyproject.toml
    pyproject_toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert ('version = "10.1"' in pyproject_toml or 'version = "10.0.1"' in pyproject_toml)

    # 验证动态渲染出的 PC 端、移动端与定价页
    from web.admin import get_html_page, get_mobile_html_page, pricing_page
    idx = get_html_page()
    mobile = get_mobile_html_page()
    from starlette.requests import Request
    from unittest.mock import MagicMock
    req = MagicMock(spec=Request)
    pricing = pricing_page(req).body.decode("utf-8")

    assert any(v in idx for v in ("V10.1", "V10.0.1"))
    assert any(v in mobile for v in ("V10.1", "V10.0.1"))
    assert any(v in pricing for v in ("V10.1", "V10.0.1"))


def test_v1001_mobile_template_has_unified_billing_pill_and_elements():
    """验证移动端模板具备与 PC 端统一的顶栏药丸与个人中心商业化算力中枢，且不包含写死伪算力。"""
    mobile = (ROOT / "web/templates/mobile.html").read_text(encoding="utf-8")

    # 1. 顶栏药丸组件存在
    assert 'id="m-nav-token-bal"' in mobile
    assert 'id="m-nav-tier-badge"' in mobile

    # 2. 个人中心商业化算力中枢与各字段 ID 存在
    assert 'id="prof-quota"' in mobile
    assert 'id="prof-tier-badge"' in mobile
    assert 'id="prof-credits-used"' in mobile
    assert 'id="prof-credits-total"' in mobile
    assert 'id="prof-quota-bar"' in mobile

    # 3. 杜绝在 profile 算力卡片中写死旧的 500,000 Token
    assert '<span id="prof-quota" style="color:var(--primary);font-weight:700">500,000 Token</span>' not in mobile

    # 4. 具备 loadMobileBillingStatus 函数定义且在 DOMContentLoaded 和 tab 切换中调用
    assert "async function loadMobileBillingStatus" in mobile
    assert "loadMobileBillingStatus()" in mobile


def test_v1001_api_auth_me_and_billing_ui_me_metric_alignment():
    """验证 /api/auth/me 与 /api/billing/ui/me 的算力字段在数值与口径上 100% 保持一致。"""
    from core import auth

    client = TestClient(app)
    u = auth.get_user_by_id("u-admin")
    if not u:
        c = auth._db()
        c.execute(
            "INSERT OR REPLACE INTO users (id, username, email, password_hash, salt, role, plan, quota_used, quota_max, created_at, last_login, is_active) "
            "VALUES (?,?,?,?,?,?,?,0,?,?,?,1)",
            ("u-admin", "admin", "admin@localhost", "!", "!", "admin", "enterprise", 6000000, auth._iso_now(), auth._iso_now())
        )
        c.commit()
        c.close()
        u = auth.get_user_by_id("u-admin")
    token = auth.make_token({"user_id": u["id"], "username": u["username"], "role": u.get("role", "admin")})
    client.cookies.set("mf_v6_token", token)
    client.cookies.set("yimu_session", token)

    # 1. 访问 PC 端的账本真源接口
    resp_billing = client.get("/api/billing/ui/me")
    assert resp_billing.status_code == 200
    billing_json = resp_billing.json()
    assert billing_json.get("ok") is True
    billing_data = billing_json.get("data") or {}

    expected_left = billing_data.get("credits_left")
    expected_used = billing_data.get("credits_used")
    expected_total = billing_data.get("credits_total")
    expected_tier = billing_data.get("tier")
    expected_display = billing_data.get("tier_display")

    assert expected_left is not None
    assert expected_total is not None
    assert expected_left == max(0, expected_total - expected_used)

    # 2. 访问移动端调用的 /api/auth/me 接口
    resp_me = client.get("/api/auth/me")
    assert resp_me.status_code == 200
    me_json = resp_me.json()
    assert me_json.get("ok") is True
    user = me_json.get("user") or {}

    # 验证字段完全对齐
    assert user.get("credits_left") == expected_left
    assert user.get("credits_used") == expected_used
    assert user.get("credits_total") == expected_total
    assert user.get("tier") == expected_tier
    assert user.get("tier_display") == expected_display
    assert user.get("quota_max") == expected_left, "quota_max 必须对齐为实时剩余可用算力 credits_left"
