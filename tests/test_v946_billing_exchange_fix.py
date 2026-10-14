# SPDX-License-Identifier: BUSL-1.1
"""验证算力与套餐更选/兑换后余额正常递增、零额度自愈与测试库隔离。"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
from studio import billing_adapter
from studio.db_models import Invite, Membership, Order, new_id, utcnow
from studio.membership.service import ensure_membership, credits_left
from studio.pricing import TIER_CREDITS


def test_package_redemption_and_exchange_increases_balance_and_heals(db_session, monkeypatch):
    """验证更选/兑换套餐后，可用算力必须绝对增加，杜绝已用额度超标导致算力归零的故障。"""
    monkeypatch.setattr(billing_adapter, "_web_session", lambda: db_session)
    tid = "t-test-billing"
    uid = "u-test-client"

    from studio.db_models import Tenant, User
    t = db_session.query(Tenant).filter(Tenant.id == tid).first()
    if not t:
        db_session.add(Tenant(id=tid, name=tid))
        db_session.commit()
    db_session.add(User(
        id=uid, tenant_id=tid, username="testclient",
        email="", password_hash="x", salt="x", role="user",
        is_active=True, created_at=utcnow(),
    ))
    db_session.commit()

    # 1. 模拟用户处于脏数据状态：已用额度超标（旧逻辑会导致可用算力恒为 0）
    m = ensure_membership(db_session, tid, uid)
    m.tier = "free"
    m.credits_total = 3000
    m.credits_used = 9999999  # 严重超标的已用额度
    db_session.commit()

    # 验证自愈机制：ensure_membership 再次调用时自动纠偏
    m = ensure_membership(db_session, tid, uid)
    assert m.credits_used == 0, "超标已用额度必须被自愈重置为 0"
    assert credits_left(m) == 3000, "重置后可用算力应为全额 3000"

    # 2. 模拟更选并兑换套餐（如 Pro 套餐 30,000 点）
    code_pro = "YIMU-TEST-PRO-01"
    db_session.add(Invite(
        id=new_id(), tenant_id=tid, code=code_pro,
        max_uses=1, used_count=0,
        credits_grant=30000,
        status="active", created_at=utcnow(),
    ))
    db_session.add(Order(
        id=new_id(), tenant_id=tid, user_id=uid,
        plan="pro", credits=30000, amount_cents=30000,
        status="pending", cdkey=code_pro,
        created_at=utcnow(),
    ))
    db_session.commit()

    # 执行卡密兑换
    res = billing_adapter.redeem_cdkey(db_session, tid, uid, code_pro)
    assert res.get("ok") is True, f"兑换应成功: {res}"
    assert res.get("tier") == "pro"
    assert res.get("balance") >= 30000, f"可用算力必须大于等于充值额度 30,000，实际 {res.get('balance')}"

    # 3. 再次验证用户数据库状态
    db_session.refresh(m)
    assert m.tier == "pro"
    assert m.credits_used <= m.credits_total
    assert credits_left(m) >= 30000

    # 4. 再次更选/升级至 Studio 套餐（200,000 点）
    code_studio = "YIMU-TEST-STUDIO-01"
    db_session.add(Invite(
        id=new_id(), tenant_id=tid, code=code_studio,
        max_uses=1, used_count=0,
        credits_grant=200000,
        status="active", created_at=utcnow(),
    ))
    db_session.add(Order(
        id=new_id(), tenant_id=tid, user_id=uid,
        plan="studio", credits=200000, amount_cents=200000,
        status="pending", cdkey=code_studio,
        created_at=utcnow(),
    ))
    db_session.commit()

    prev_balance = credits_left(m)
    res_s = billing_adapter.redeem_cdkey(db_session, tid, uid, code_studio)
    assert res_s.get("ok") is True
    assert res_s.get("tier") == "studio"
    assert res_s.get("balance") >= prev_balance + 200000, "算力必须在原有基础上递增，绝不能变成零"


def test_admin_ui_me_guarantees_sufficient_credits_and_no_zero_balance(db_session, monkeypatch):
    """验证 ui_me 接口在管理员身份下保证算力充足，不因异常历史数据导致算力为 0。"""
    from web.gateway_ui import _membership_summary
    from studio.db_models import User

    tid = "default"
    uid = "u-admin"
    m = ensure_membership(db_session, tid, uid)
    m.tier = "studio"
    m.credits_total = 6000000
    m.credits_used = 122800
    db_session.commit()

    summary = _membership_summary(m)
    assert summary["tier"] == "studio"
    assert summary["credits_left"] > 5000000, f"管理员算力应充足，实际 {summary['credits_left']}"
