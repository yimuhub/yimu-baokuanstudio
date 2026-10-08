# SPDX-License-Identifier: BUSL-1.1
"""会员能力矩阵与配额引擎测试：三档功能区分（V7 Free / V7 Pro / V7 Studio）。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from studio import db as studio_db
from studio.db_models import QuotaCounter
from studio.membership import capabilities as caps
from tests.conftest import make_test_db


@pytest.fixture()
def db():
    _, url = make_test_db(prefix="yimu_caps_")
    engine = studio_db.get_engine(url)
    studio_db.init_db(engine)
    sess = sessionmaker(bind=engine)()
    # 配额表 tenant_id 有外键，先建测试租户行
    from studio.db_models import Tenant, utcnow

    for tid in ("t1", "tA", "tB"):
        if sess.get(Tenant, tid) is None:
            sess.add(Tenant(id=tid, name=tid, plan="free",
                            launch_mode="invite-only", is_active=True,
                            created_at=utcnow()))
    sess.commit()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


class TestTierDisplayName:
    def test_display_names(self):
        assert caps.tier_display_name("free") == "V7 Free"
        assert caps.tier_display_name("pro") == "V7 Pro"
        assert caps.tier_display_name("studio") == "V7 Studio"
        assert caps.tier_display_name("unknown") == "V7 Free"
        assert caps.tier_display_name("") == "V7 Free"


class TestCapabilityMatrix:
    def test_free_limits(self):
        assert caps.capability_limit("free", "hot_daily") == 1
        assert caps.capability_limit("free", "hot_platforms") == 5
        assert caps.capability_limit("free", "image_race") is False
        assert caps.capability_limit("free", "image_race_weekly") == 3
        assert caps.capability_limit("free", "tts_max_chars") == 500
        assert caps.capability_limit("free", "tts_daily") == 5
        assert caps.capability_limit("free", "drama_weekly") == 1
        assert caps.capability_limit("free", "drama_max_seconds") == 10
        assert caps.capability_limit("free", "publish_platforms") == 1
        assert caps.capability_limit("free", "gateway_api") is False
        assert caps.capability_limit("free", "task_concurrency") == 1

    def test_pro_unlimited(self):
        assert caps.capability_limit("pro", "hot_daily") == -1
        assert caps.capability_limit("pro", "image_race") is True
        assert caps.capability_limit("pro", "gateway_api") is True
        assert caps.capability_limit("pro", "task_concurrency") == 5

    def test_studio_extras(self):
        assert caps.capability_limit("studio", "task_concurrency") == 20
        assert caps.capability_limit("studio", "sub_accounts") is True
        assert caps.capability_limit("studio", "gateway_api") is True

    def test_is_allowed(self):
        assert caps.is_allowed("free", "gateway_api") is False
        assert caps.is_allowed("pro", "gateway_api") is True
        assert caps.is_allowed("free", "hot_daily") is True  # 配额型 >0 视为允许


class TestQuotaEngine:
    def test_free_hot_daily_one_per_day(self, db):
        # free 每日 1 次：第 1 次允许，第 2 次拒绝
        ok1, r1 = caps.check_and_consume(
            db, tenant_id="t1", user_id="u1", tier="free", capability="hot_daily")
        assert ok1 is True and r1 == ""
        ok2, r2 = caps.check_and_consume(
            db, tenant_id="t1", user_id="u1", tier="free", capability="hot_daily")
        assert ok2 is False
        assert "1/1" in r2 and "V7 Pro" in r2

    def test_pro_unlimited(self, db):
        for _ in range(5):
            ok, _ = caps.check_and_consume(
                db, tenant_id="t1", user_id="u2", tier="pro", capability="hot_daily")
            assert ok is True

    def test_weekly_quota(self, db):
        # free 每周短剧 1 次
        ok1, _ = caps.check_and_consume(
            db, tenant_id="t1", user_id="u3", tier="free", capability="drama_weekly")
        assert ok1 is True
        ok2, r2 = caps.check_and_consume(
            db, tenant_id="t1", user_id="u3", tier="free", capability="drama_weekly")
        assert ok2 is False and "下周一" in r2

    def test_switch_capability(self, db):
        # 开关型：free 拒绝，pro 允许
        ok_f, r_f = caps.check_and_consume(
            db, tenant_id="t1", user_id="u4", tier="free", capability="gateway_api")
        assert ok_f is False and "V7 Pro" in r_f
        ok_p, _ = caps.check_and_consume(
            db, tenant_id="t1", user_id="u4", tier="pro", capability="gateway_api")
        assert ok_p is True

    def test_tenant_isolation(self, db):
        # 不同租户的计数器互不干扰
        caps.check_and_consume(
            db, tenant_id="tA", user_id="u5", tier="free", capability="hot_daily")
        ok, _ = caps.check_and_consume(
            db, tenant_id="tB", user_id="u5", tier="free", capability="hot_daily")
        assert ok is True

    def test_get_user_tier_default_free(self, db):
        assert caps.get_user_tier(db, tenant_id="t1", user_id="nonexistent") == "free"
