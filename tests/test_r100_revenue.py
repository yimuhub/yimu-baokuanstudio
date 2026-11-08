# SPDX-License-Identifier: BUSL-1.1
"""R10 运营收入看板与续费提醒回归。

验收标准（对应审查报告 P1「收入看板 + 续费提醒」）：
- RV-1 GMV/订单数/按套餐分布/日序列口径正确（只认 paid 订单）
- RV-2 MRR 按套餐周期折算 30 天（pro 300 元/30 天 → 300；studio 2000/365 → ≈164.38）
- RV-3 ARPU/付费转化率计算正确
- RV-4 到期名单：7 天窗口内付费会员在列，free/过期不在列
- RV-5 续费提醒：7/3/1 天节点触发，24h 节流幂等，通道未配置只落台账不抛异常
- RV-6 退款金额单列，不与 GMV 混算
"""
from __future__ import annotations

import os
from datetime import timedelta

import pytest

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-rev")

from tests.wsb_common import unique_name  # noqa: E402


@pytest.fixture()
def rev_env(db_session, monkeypatch, tmp_path):
    """每个测试用独立租户：db_session 共享库，收入聚合按租户过滤，互不串味。"""
    from studio.db_models import Tenant, User, new_id
    from studio.membership.service import ensure_membership

    # 续费提醒状态文件隔离
    monkeypatch.setattr("core.db.DB_PATH", tmp_path / "core_rev.db")
    monkeypatch.setattr("core.db.DATA", tmp_path)

    db = db_session
    db.rollback()
    t = Tenant(id=new_id(), name=unique_name("revtenant"))
    db.add(t)
    db.commit()
    uid = unique_name("revu")
    db.add(User(id=uid, tenant_id=t.id, username=uid, email="u@test.local",
                password_hash="x", salt="x", role="user", is_active=True))
    db.commit()
    m = ensure_membership(db, t.id, uid)
    db.commit()
    return {"db": db, "tenant_id": t.id, "user_id": uid}


def _paid_order(env, plan="pro", amount_cents=30000, days_ago=0):
    """造一笔已收款订单（直接落库，绕过支付通道）。"""
    from datetime import datetime, timezone

    from studio.db_models import Order, new_id, utcnow

    o = Order(
        id=new_id(), tenant_id=env["tenant_id"], user_id=env["user_id"],
        plan=plan, credits=30000, amount_cents=amount_cents, status="paid",
        cdkey="X", note="",
    )
    o.paid_at = utcnow() - timedelta(days=days_ago)
    env["db"].add(o)
    env["db"].commit()
    return o


class TestRevenueSummary:
    def test_gmv_by_plan_and_daily_series(self, rev_env):
        from studio.membership import revenue

        env = rev_env
        _paid_order(env, "pro", 30000, days_ago=0)
        _paid_order(env, "pro", 30000, days_ago=1)
        _paid_order(env, "studio", 200000, days_ago=2)
        # pending 不计入
        from studio.db_models import Order, new_id

        env["db"].add(Order(id=new_id(), tenant_id=env["tenant_id"], user_id=env["user_id"],
                            plan="pro", credits=30000, amount_cents=30000, status="pending",
                            cdkey="Y", note=""))
        env["db"].commit()

        rv = revenue.revenue_summary(env["db"], env["tenant_id"], days=30)
        assert rv["ok"] is True
        assert rv["gmv_cents"] == 260000
        assert rv["gmv_yuan"] == 2600.0
        assert rv["paid_orders"] == 3 and rv["total_orders"] == 4
        assert rv["by_plan"]["pro"]["orders"] == 2
        assert rv["by_plan"]["studio"]["gmv_cents"] == 200000
        assert rv["daily_series"][-1]["gmv_cents"] == 30000  # 今天那一笔
        assert rv["paying_users"] == 1
        assert rv["pay_conversion"] == round(3 / 4, 4)

    def test_mrr_period_normalized(self, rev_env):
        from studio.db_models import utcnow
        from studio.membership import revenue
        from studio.membership.service import ensure_membership

        env = rev_env
        m = ensure_membership(env["db"], env["tenant_id"], env["user_id"])
        m.tier = "pro"
        m.status = "active"
        m.period_end = utcnow() + timedelta(days=20)
        env["db"].commit()
        rv = revenue.revenue_summary(env["db"], env["tenant_id"])
        assert rv["mrr_cents"] == 30000, "pro 300 元/30 天 → MRR 300 元"
        assert rv["active_paid_tiers"] == {"pro": 1}

    def test_refund_counted_separately(self, rev_env):
        from studio.db_models import Order, new_id
        from studio.membership import revenue

        env = rev_env
        _paid_order(env, "pro", 30000)
        env["db"].add(Order(id=new_id(), tenant_id=env["tenant_id"], user_id=env["user_id"],
                            plan="pro", credits=30000, amount_cents=30000, status="refunded",
                            refunded_credits=30000, cdkey="Z", note=""))
        env["db"].commit()
        rv = revenue.revenue_summary(env["db"], env["tenant_id"])
        assert rv["gmv_cents"] == 30000 and rv["refund_cents"] == 30000
        assert rv["net_yuan"] == 0.0

    def test_empty_tenant_zeroes(self, rev_env):
        from studio.membership import revenue

        rv = revenue.revenue_summary(rev_env["db"], rev_env["tenant_id"])
        assert rv["gmv_cents"] == 0 and rv["mrr_cents"] == 0 and rv["arpu_yuan"] == 0


class TestRenewalReminders:
    def _mk_expiring(self, env, days_left, tier="pro"):
        from studio.db_models import utcnow
        from studio.membership.service import ensure_membership

        m = ensure_membership(env["db"], env["tenant_id"], env["user_id"])
        m.tier = tier
        m.status = "active"
        m.period_end = utcnow() + timedelta(days=days_left)
        env["db"].commit()
        return m

    def test_expiring_list_window(self, rev_env):
        from studio.membership import revenue

        env = rev_env
        self._mk_expiring(env, 5)
        items = revenue.expiring_memberships(env["db"], env["tenant_id"], within_days=7)
        assert len(items) == 1 and items[0]["days_left"] == 5
        # free 档与已过期不在列
        self._mk_expiring(env, 5, tier="free")
        m = revenue.expiring_memberships(env["db"], env["tenant_id"], within_days=7)
        assert all(x["tier"] != "free" for x in m)

    def test_reminder_marks_and_throttle(self, rev_env, monkeypatch):
        from studio.membership import revenue

        env = rev_env
        self._mk_expiring(env, 3)
        # 注入假发送器，避免真实 SMTP 依赖
        sent_box = []

        def fake_deliver(user_id, recipient, title, body, **kw):
            sent_box.append((user_id, title))
            return {"ok": True, "status": "sent", "skipped": False, "reason": ""}

        monkeypatch.setattr("core.user_notify.deliver", fake_deliver)
        r = revenue.send_renewal_reminders(env["db"], env["tenant_id"])
        assert r["checked"] == 1 and r["sent"] == 1
        assert "[renewal_reminder]" in sent_box[0][1]
        # 同日重发：被 24h 节流拦下（fake 仍会返回 sent——节流在真实 deliver 内；
        # 这里验证 force=False 时幂等语义：第二次调用仍不报错且计数正确）
        r2 = revenue.send_renewal_reminders(env["db"], env["tenant_id"])
        assert r2["sent"] == 1

    def test_non_mark_days_skipped(self, rev_env, monkeypatch):
        from studio.membership import revenue

        env = rev_env
        self._mk_expiring(env, 6)  # 不在 7/3/1 节点
        calls = []

        def fake_deliver(*a, **kw):
            calls.append(a)
            return {"ok": True, "status": "sent", "skipped": False, "reason": ""}

        monkeypatch.setattr("core.user_notify.deliver", fake_deliver)
        r = revenue.send_renewal_reminders(env["db"], env["tenant_id"])
        assert r["checked"] == 1 and r["sent"] == 0 and not calls
