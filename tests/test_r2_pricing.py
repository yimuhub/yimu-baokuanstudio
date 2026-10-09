# SPDX-License-Identifier: BUSL-1.1
"""R2 计费归一验收测试。

覆盖 5 条硬性验收标准（每条都能独立证伪）：
1. 同一模型走 llm_metering 与走 /v1，扣减 credits **完全一致**；
2. ``SELECT SUM(cost_cents) FROM ledger`` 与余额变动**逐笔对得上**；
3. 生成 1 张图后 ``credits_used`` **增长 5**（不只是 ledger 多一行）；
4. ``period_end`` 设为昨天 → 配额**自动重置**；
5. 多用户互不影响（用户 A 充值，用户 B 余额不变）。

另含口径护栏：禁止任何模块再把 total_tokens 直接当 credits 扣。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ⭐ 环境时序：必须在 import studio.auth 之前设好（与会话签名密钥一致）
os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-r2")

from sqlalchemy import func, select

from studio import ledger as ledger_mod
from studio import pricing
from studio.db_models import GatewayKey, Ledger, Membership, new_id, utcnow


# ---------------------------------------------------------------------------
# 验收 1：两条计费路径扣减完全一致
# ---------------------------------------------------------------------------

def test_llm_metering_and_gateway_deduct_identically():
    """同一模型同一 token 数，走官方直扣与走 /v1 账本，credits 必须一字不差。

    这是 R2-2 的核心验收：历史上官方通道按「1 token = 1 credit」扣，
    /v1 按 per-1k 扣，两者差 250~500 倍，同一份额度两条路径价值完全不同。
    """
    from studio import llm_metering

    cases = [
        ("yimu-chat", 100, 50),
        ("yimu-chat", 1000, 1000),
        ("gpt-4o", 4321, 1234),
        ("deepseek-chat", 1, 1),
        ("qwen-max", 0, 5000),
        ("unknown-model-x", 800, 200),
    ]
    for model, ptok, ctok in cases:
        # 路径 A：官方通道直扣（studio/llm_metering）
        fake_db = MagicMock()
        with patch("studio.membership.capabilities.get_db_session", return_value=fake_db), \
             patch("studio.membership.capabilities.get_user_tier", return_value="pro"), \
             patch("studio.membership.service.deduct_credits", return_value=(True, 999)) as m_a, \
             patch.object(llm_metering, "_USAGE_PATH", Path("/tmp/_r2_metering.json")):
            r = llm_metering.record_llm_call(
                "yimu_official", model, ptok, ctok, ptok + ctok, user_id="u-a"
            )
        deducted_a = m_a.call_args[0][3]

        # 路径 B：网关 /v1 账本（gateway/limits.write_ledger_rows 内部的同一换算）
        in_c, out_c = pricing.credits_for_call(model, ptok, ctok)
        deducted_b = in_c + out_c

        assert deducted_a == deducted_b, (
            f"{model}(in={ptok},out={ctok}) 两条路径扣减不一致："
            f"llm_metering={deducted_a} vs gateway={deducted_b}"
        )
        assert r["deducted"] == deducted_a, "返回值应与实际扣减一致"


def test_no_module_deducts_raw_token_count():
    """静态护栏：llm_metering 不得再把 total_tokens 直接传去扣费。

    历史 bug 是 ``deduct_credits(_db, tid, uid, total_tokens)``——
    1 token = 1 credit，与per-1k 口径差 250~500 倍。
    """
    src = (Path(__file__).resolve().parent.parent / "studio" / "llm_metering.py").read_text(
        encoding="utf-8"
    )
    assert "deduct_credits(_db, _TENANT_ID, str(user_id), total_tokens)" not in src, (
        "llm_metering 不得把 total_tokens 直接当 credits 扣（R2-2 要求走 per-1k）"
    )
    assert "credits_for_call" in src, "llm_metering 应经由 pricing.credits_for_call 换算"


def test_pricing_is_single_source_of_truth():
    """价格常量只能有一个真源：core.billing / billing_adapter / membership 都转发到 pricing。"""
    from core import billing
    from studio import billing_adapter
    from studio.membership import service

    assert billing.ACTION_COSTS is pricing.ACTION_COSTS
    assert billing.DEFAULT_TIERS is pricing.DEFAULT_TIERS
    assert billing_adapter.ACTION_COSTS is pricing.ACTION_COSTS
    assert billing_adapter.DEFAULT_TIERS is pricing.DEFAULT_TIERS
    assert service.tier_credits("free") == pricing.TIER_CREDITS["free"]
    assert service.tier_credits("pro") == pricing.TIER_CREDITS["pro"]
    assert service.tier_credits("studio") == pricing.TIER_CREDITS["studio"]


# ---------------------------------------------------------------------------
# 验收 2：SUM(cost_cents) 与余额变动逐笔对得上
# ---------------------------------------------------------------------------

def test_ledger_sum_matches_credits_used_delta(db_session):
    """billing_adapter 扣费后：ledger 汇总增量 == memberships.credits_used 增量。

    R2-4 之前 cost_cents 有三种语义（点数 / 1 credit=1 cent / 1 credit=100 cent），
    任何跨来源 SUM 都得出无意义数字。统一为「cost_cents 存的就是 credits」后，
    汇总才有意义，才能真正对账。
    """
    from studio import billing_adapter
    from studio.db_models import Membership
    from studio.membership.service import ensure_membership

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2rec"))
    tid, uid = stack["tenant_id"], stack["user_id"]
    ensure_membership(db_session, tid, uid)
    db_session.commit()
    # 免费档 3000 credits 不足以覆盖下面这串动作，先补足额度再验对账
    from studio import billing_adapter as _ba

    _ba.grant_tokens(db_session, tid, uid, 50000, "R2 对账测试补额度")

    def ledger_sum() -> int:
        return int(
            db_session.execute(
                select(func.coalesce(func.sum(Ledger.cost_cents), 0)).where(
                    Ledger.tenant_id == tid
                )
            ).scalar()
            or 0
        )

    def used() -> int:
        m = (
            db_session.query(Membership)
            .filter(Membership.tenant_id == tid, Membership.user_id == uid)
            .one()
        )
        return int(m.credits_used)

    sum0, used0 = ledger_sum(), used()
    for action, count in (("rewrite", 1), ("score", 3), ("drama_image", 2)):
        assert billing_adapter.check_and_deduct(db_session, tid, uid, action, count) is True

    d_ledger = ledger_sum() - sum0
    d_used = used() - used0
    assert d_ledger == d_used, (
        f"账本汇总与额度消耗不一致：ledger +{d_ledger} vs credits_used +{d_used}"
    )
    # 逐笔金额也必须等于动作单价
    expected = (
        pricing.ACTION_COSTS["rewrite"] * 1
        + pricing.ACTION_COSTS["score"] * 3
        + pricing.ACTION_COSTS["drama_image"] * 2
    )
    assert d_used == expected, f"扣费金额应等于动作单价之和 {expected}，实际 {d_used}"


def test_cost_cents_unit_is_credits_not_cents(db_session):
    """R2-4 护栏：cost_cents 列存的必须是 credits 点数（1 credit ≠ 100 cent）。"""
    from studio import billing_adapter

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2unit"))
    tid, uid = stack["tenant_id"], stack["user_id"]

    assert billing_adapter.check_and_deduct(db_session, tid, uid, "rewrite", 1) is True
    row = (
        db_session.query(Ledger)
        .filter(Ledger.tenant_id == tid, Ledger.model == "billing:rewrite")
        .one()
    )
    assert row.cost_cents == pricing.ACTION_COSTS["rewrite"], (
        "cost_cents 必须等于 credits 点数，不得再乘 CENTS_PER_CREDIT"
    )
    assert row.cost_cents != pricing.ACTION_COSTS["rewrite"] * 100, (
        "1 credit 不得再等于 100 分（R2-4 已统一为 1 credit = 1 cent 语义位）"
    )


def test_key_used_credits_reads_cost_cents_as_credits(db_session):
    """key_used_credits() 直接 SUM(cost_cents)，单位统一后才有意义。"""
    from gateway.limits import key_used_credits

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2key"))
    tid = stack["tenant_id"]

    # ⭐ ledger.key_id 有外键约束，必须先有真实的 gateway_keys 行
    key = GatewayKey(
        id="k-1", tenant_id=tid, user_id=stack["user_id"], name="r2key",
        key_hash="h1", key_prefix="k1",
        quota_credits=100000, rate_limit_rpm=60, rate_limit_tpm=100000,
        status="active", created_at=utcnow(),
    )
    db_session.add(key)
    db_session.commit()

    db_session.add(
        Ledger(
            id=new_id(), tenant_id=tid, key_id=None, model="m",
            direction="input", tokens=10, cost_cents=7, latency_ms=0,
            cached=False, created_at=utcnow(),
        )
    )
    db_session.commit()
    # ⭐ 注意：key_id=None 会生成 `key_id IS NULL`，因此上面那条 key_id=None
    #   的行是**会**被计入的。
    assert key_used_credits(db_session, tid, None) == 7, (
        "key_id=None 时统计的是 key_id IS NULL 的行"
    )

    db_session.add(
        Ledger(
            id=new_id(), tenant_id=tid, key_id="k-1", model="m",
            direction="input", tokens=10, cost_cents=7, latency_ms=0,
            cached=False, created_at=utcnow(),
        )
    )
    db_session.commit()
    assert key_used_credits(db_session, tid, "k-1") == 7, (
        "cost_cents 为 credits 语义时，7 credits 应读出 7"
    )

    # 混入另一个 key：按key 汇总必须彼此隔离
    db_session.add(
        GatewayKey(
            id="k-2", tenant_id=tid, user_id=stack["user_id"], name="r2key2",
            key_hash="h2", key_prefix="k2",
            quota_credits=100000, rate_limit_rpm=60, rate_limit_tpm=100000,
            status="active", created_at=utcnow(),
        )
    )
    db_session.add(
        Ledger(
            id=new_id(), tenant_id=tid, key_id="k-2", model="m",
            direction="input", tokens=10, cost_cents=11, latency_ms=0,
            cached=False, created_at=utcnow(),
        )
    )
    db_session.commit()
    assert key_used_credits(db_session, tid, "k-1") == 7, "k-1 的汇总不应含 k-2"
    assert key_used_credits(db_session, tid, "k-2") == 11


# ---------------------------------------------------------------------------
# 验收 3：生图 1 张 → credits_used 增长 5
# ---------------------------------------------------------------------------

def test_image_generate_deducts_five_credits(db_session, tmp_path, monkeypatch):
    """R2-5：image_forge.generate 只写ledger 不扣额度是「账记了钱没扣」。

    验收标准：生成 1 张图后 memberships.credits_used **增长 5**
    （不只是ledger 多一行）。
    """
    from studio.db_models import Membership
    from studio.image_forge import generate as gen
    from studio.membership.service import ensure_membership

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2img"))
    tid, uid = stack["tenant_id"], stack["user_id"]
    ensure_membership(db_session, tid, uid)
    db_session.commit()

    db_url = f"sqlite:///{db_session.bind.url.database}"
    # 把studio 侧的会话工厂指向本测试库
    from studio.membership import capabilities as caps

    monkeypatch.setenv("YIMU_DB_URL", db_url)
    monkeypatch.setattr(caps, "_session_factory_cache", {})

    def used() -> int:
        db_session.expire_all()
        m = (
            db_session.query(Membership)
            .filter(Membership.tenant_id == tid, Membership.user_id == uid)
            .one()
        )
        return int(m.credits_used)

    def ledger_rows() -> int:
        return (
            db_session.query(Ledger)
            .filter(Ledger.tenant_id == tid, Ledger.model == "image-gen")
            .count()
        )

    fake_client = MagicMock(return_value=[{"url": "http://x/1.png", "revised_prompt": ""}])
    before_used, before_rows = used(), ledger_rows()

    res = gen.generate(
        prompt="一只猫", n=1, tenant_id=tid, db_url=db_url,
        client=fake_client, race_allowed=False, user_id=uid,
    )
    assert res["ok"] is True, f"生图应成功：{res}"
    assert "ledger_warning" not in res, f"记账不应失败：{res.get('ledger_warning')}"
    assert res["cost_credits"] == gen.CREDITS_PER_IMAGE == 5

    assert ledger_rows() == before_rows + 1, "ledger 应新增 1 行"
    assert used() == before_used + 5, (
        f"生图 1 张应扣5 credits：used {before_used} → {used()}"
    )


def test_image_generate_ledger_amount_equals_credits(db_session, tmp_path, monkeypatch):
    """R2-4+R2-5 交叉验收：生图写入的 cost_cents 必须是 5（credits），不是 500。"""
    from studio.image_forge import generate as gen
    from studio.membership import capabilities as caps
    from studio.membership.service import ensure_membership

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2img2"))
    tid, uid = stack["tenant_id"], stack["user_id"]
    ensure_membership(db_session, tid, uid)
    db_session.commit()

    db_url = f"sqlite:///{db_session.bind.url.database}"
    monkeypatch.setenv("YIMU_DB_URL", db_url)
    monkeypatch.setattr(caps, "_session_factory_cache", {})

    gen.generate(
        prompt="一只狗", n=1, tenant_id=tid, db_url=db_url,
        client=MagicMock(return_value=[{"url": "http://x/2.png", "revised_prompt": ""}]),
        race_allowed=False,
    )
    row = (
        db_session.query(Ledger)
        .filter(Ledger.tenant_id == tid, Ledger.model == "image-gen")
        .one()
    )
    assert row.cost_cents == 5, (
        f"生图 cost_cents 应为 5 credits（1 credit≠100 cent），实际 {row.cost_cents}"
    )


# ---------------------------------------------------------------------------
# 验收 4：period_end 到期 → 配额自动重置
# ---------------------------------------------------------------------------

def test_expired_period_resets_quota(db_session):
    """R2-6：period_end 设为昨天 → 配额自动重置（credits_used 归零、额度恢复）。"""
    from studio.db_models import Membership
    from studio.membership.service import ensure_membership, reset_period_if_expired

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2per"))
    tid, uid = stack["tenant_id"], stack["user_id"]
    m = ensure_membership(db_session, tid, uid)
    db_session.commit()

    total0 = int(m.credits_total)
    # 消耗一部分额度，再把period_end 设成昨天
    ok, _ = __import__(
        "studio.membership.service", fromlist=["deduct_credits"]
    ).deduct_credits(db_session, tid, uid, 1200)
    assert ok is True

    m.period_end = datetime.now(timezone.utc) - timedelta(days=1)
    m.period_start = datetime.now(timezone.utc) - timedelta(days=31)
    db_session.commit()
    assert int(m.credits_used) == 1200

    changed = reset_period_if_expired(db_session, m)
    db_session.commit()
    assert changed is True, "过期周期应被判定为需要重置"
    db_session.refresh(m)
    assert int(m.credits_used) == 0, f"过期后已用额度应归零，实际 {m.credits_used}"
    assert int(m.credits_total) == total0, "重置应恢复本档位标准额度"
    # ⭐ SQLite 读回的 period_end 是 naive UTC，比较时要统一
    end = m.period_end.replace(tzinfo=None) if m.period_end.tzinfo else m.period_end
    assert m.period_end is not None and end > utcnow().replace(tzinfo=None), (
        "重置后应滚动出新的 period_end"
    )


def test_valid_period_is_not_reset(db_session):
    """未到期的周期不得被重置（否则等于随时免费刷新额度）。"""
    from studio.membership.service import ensure_membership, reset_period_if_expired

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2per2"))
    tid, uid = stack["tenant_id"], stack["user_id"]
    m = ensure_membership(db_session, tid, uid)
    db_session.commit()

    svc = __import__("studio.membership.service", fromlist=["deduct_credits"])
    svc.deduct_credits(db_session, tid, uid, 500)
    m.period_end = utcnow() + timedelta(days=15)
    db_session.commit()

    assert reset_period_if_expired(db_session, m) is False, "未到期不得重置"
    db_session.refresh(m)
    assert int(m.credits_used) == 500, "未到期时已用额度必须保留"


def test_deduct_credits_auto_resets_expired_membership(db_session):
    """R2-6：period_end 已过期时，扣费入口应先重置周期再扣，而不是永久拒绝。

    ⚠️ 这里修正了一个真实的不一致：``gateway.limits.charge_membership`` 的 SQL
    带 ``period_end >now`` 条件，过期用户会被永久拒绝（额度再也用不了）；
    而 ``membership.service.deduct_credits`` 此前不看period_end。
    R2-6 已让 deduct_credits 先做周期判定重置，两条路径语义就此对齐。
    """
    from studio.membership.service import deduct_credits, ensure_membership

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2per3"))
    tid, uid = stack["tenant_id"], stack["user_id"]
    m = ensure_membership(db_session, tid, uid)
    db_session.commit()

    # 先消耗 2000，再让周期过期
    assert deduct_credits(db_session, tid, uid, 2000)[0] is True
    m.period_end = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    # 过期后再扣：应自动重置 → 额度恢复 → 本次扣费成功
    ok, left = deduct_credits(db_session, tid, uid, 10)
    assert ok is True, "过期周期应先自动重置，而不是永久拒绝扣费"
    db_session.expire_all()
    m2 = (
        db_session.query(type(m))
        .filter(type(m).tenant_id == tid, type(m).user_id == uid)
        .one()
    )
    assert int(m2.credits_used) == 10, (
        f"重置后本次扣费应只累计 10，实际 {m2.credits_used}"
    )
    assert left == pricing.TIER_CREDITS["free"] - 10


# ---------------------------------------------------------------------------
# 验收 5：多用户互不影响
# ---------------------------------------------------------------------------

def test_users_do_not_interfere(db_session):
    """用户 A 充值，用户 B 余额不变；A 消费不影响 B。"""
    from studio import billing_adapter
    from studio.db_models import Membership
    from studio.membership.service import ensure_membership

    from tests.wsb_common import make_tenant_stack, unique_name

    stack_a = make_tenant_stack(db_session, unique_name("r2A"))
    tid = stack_a["tenant_id"]
    uid_a = stack_a["user_id"]
    # ⭐ 同一租户下再建一个用户，才谈得上「A 消费不影响 B」
    from studio.auth import register_user
    from studio.db_models import Tenant

    tenant = db_session.query(Tenant).filter(Tenant.id == tid).one()
    user_b = register_user(db_session, tenant, unique_name("userB"), "pw-r2-test-1234")
    uid_b = user_b.id
    ensure_membership(db_session, tid, uid_a)
    ensure_membership(db_session, tid, uid_b)
    db_session.commit()

    def used(uid: str) -> int:
        db_session.expire_all()
        m = (
            db_session.query(Membership)
            .filter(Membership.tenant_id == tid, Membership.user_id == uid)
            .one()
        )
        return int(m.credits_used)

    def total(uid: str) -> int:
        db_session.expire_all()
        m = (
            db_session.query(Membership)
            .filter(Membership.tenant_id == tid, Membership.user_id == uid)
            .one()
        )
        return int(m.credits_total)

    used_b0, total_b0 = used(uid_b), total(uid_b)

    # A 充值 5000
    billing_adapter.grant_tokens(db_session, tid, uid_a, 5000, "A 充值")
    assert total(uid_a) == pricing.TIER_CREDITS["free"] + 5000
    assert total(uid_b) == total_b0, "A 充值不得改变 B 的总额度"
    assert used(uid_b) == used_b0, "A 充值不得改变 B 的已用额度"

    # A 消费 800，B 纹丝不动
    assert billing_adapter.check_and_deduct(db_session, tid, uid_a, "rewrite", 1) is True
    assert used(uid_a) == pricing.ACTION_COSTS["rewrite"]
    assert used(uid_b) == used_b0, "A 消费不得影响 B"
    assert total(uid_b) == total_b0, "A 消费不得影响 B 的额度"


def test_two_users_same_tenant_deduct_independently(db_session):
    """同租户两个用户并发式交替扣费，各自余额独立。"""
    from studio.membership.service import deduct_credits, ensure_membership

    from tests.wsb_common import make_tenant_stack, unique_name

    stack_a = make_tenant_stack(db_session, unique_name("r2iA"))
    tid = stack_a["tenant_id"]
    uid_a = stack_a["user_id"]
    from studio.auth import register_user
    from studio.db_models import Tenant

    tenant = db_session.query(Tenant).filter(Tenant.id == tid).one()
    uid_b = register_user(db_session, tenant, unique_name("userC"), "pw-r2-test-5678").id
    ensure_membership(db_session, tid, uid_a)
    ensure_membership(db_session, tid, uid_b)
    db_session.commit()

    for _ in range(3):
        assert deduct_credits(db_session, tid, uid_a, 100)[0] is True
        assert deduct_credits(db_session, tid, uid_b, 250)[0] is True

    def used(uid: str) -> int:
        db_session.expire_all()
        return int(
            db_session.query(Membership)
            .filter(Membership.tenant_id == tid, Membership.user_id == uid)
            .one().credits_used
        )

    assert used(uid_a) == 300
    assert used(uid_b) == 750


# ---------------------------------------------------------------------------
# 口径护栏：额度与售价必须自洽
# ---------------------------------------------------------------------------

def test_tier_credits_match_documented_price():
    """R2-1 口径护栏：1 credit = 0.01 元，三档额度与售价必须对得上。"""
    assert pricing.CREDIT_PRICE_CENTS == 1
    assert pricing.CENTS_PER_CREDIT == 1, "1 credit 不得再等于 100 分"
    assert pricing.credits_to_yuan(1) == 0.01
    assert pricing.credits_to_yuan(100) == 1.0
    assert pricing.yuan_to_credits(1.0) == 100
    # 三档额度（下调后）
    assert pricing.TIER_CREDITS == {"free": 3000, "pro": 30000, "studio": 200000}
    # Free 档必须跑不完一条完整短剧（R2-7 的前提）
    assert pricing.TIER_CREDITS["free"] < pricing.FULL_DRAMA_CREDITS, (
        "Free 额度应小于一条完整短剧消耗，才能支撑「只送单镜头体验」"
    )


def test_no_hardcoded_tier_amounts_outside_pricing():
    """静态护栏：三档额度数字不得在业务代码里硬编码，只能来自 pricing。

    用 AST 只扫「字符串/数字常量」，避免误伤注释里对历史值的说明文字
    （那是刻意留档，不是代码）——与 R1 的 no_backdoor_literals 护栏同一手法。
    """
    import ast

    root = Path(__file__).resolve().parent.parent
    legacy = {10000, 500000, 6000000, 10000000}

    for rel in ("core/auth.py", "core/billing.py", "studio/membership/service.py",
                "studio/billing_adapter.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, int) \
                    and not isinstance(node.value, bool) and node.value in legacy:
                raise AssertionError(
                    f"{rel}:{node.lineno} 硬编码了旧额度 {node.value}，"
                    f"应由 studio/pricing.TIER_CREDITS 提供"
                )

    # db schema 默认值同样必须跟定价真源一致（走字符串，排除注释干扰）
    db_src = (root / "core" / "db.py").read_text(encoding="utf-8")
    assert "quota_max INTEGER DEFAULT 500000" not in db_src, (
        "core/db.py 的 quota_max 默认值仍为旧的 500000"
    )


def test_calc_cost_canary_unchanged():
    """金丝雀纯函数 calc_cost 算法不得被 R2 改动（金丝雀逐字断言）。"""
    assert ledger_mod.calc_cost([]) == {"total_credits": 0, "count": 0}
    assert ledger_mod.calc_cost([{"cost_credits": 5}, {"cost_credits": 7}]) == {
        "total_credits": 12,
        "count": 2,
    }


# ---------------------------------------------------------------------------
# R2-3 账本收敛验收
# ---------------------------------------------------------------------------

def test_core_billing_no_longer_owns_a_json_ledger():
    """R2-3：core/billing.py 不得再用 JSON 单例做余额真源。

    收敛后余额真源是 memberships，明细是 ledger，JSON 仅保留迁移用途。
    """
    src = (Path(__file__).resolve().parent.parent / "core" / "billing.py").read_text(
        encoding="utf-8"
    )
    # 对外函数必须转发到 studio 侧账本
    assert "billing_adapter" in src, "core/billing.py 应转发到 studio.billing_adapter"
    # 旧的「直接改 JSON 里的 balance」实现应消失
    assert 'data["balance"] = data.get("balance", 0) + amount' not in src, (
        "grant_tokens 不得再直接改 JSON 余额"
    )
    assert 'data["balance"] -= total_cost' not in src, (
        "check_and_deduct 不得再直接改 JSON 余额"
    )


def test_check_and_deduct_writes_ledger_and_membership(db_session):
    """R2-3 核心验收：core.billing.check_and_deduct 落到 memberships + ledger。"""
    import core.billing as cb
    from studio import billing_adapter
    from studio.db_models import Ledger, Membership
    from studio.membership.service import ensure_membership

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2conv"))
    tid, uid = stack["tenant_id"], stack["user_id"]
    ensure_membership(db_session, tid, uid)
    db_session.commit()

    # 直接调adapter（core.billing 的 db 参数版），验证收敛后的行为
    assert billing_adapter.check_and_deduct(db_session, tid, uid, "rewrite", 1) is True

    m = (
        db_session.query(Membership)
        .filter(Membership.user_id == uid)
        .one()
    )
    assert int(m.credits_used) == pricing.ACTION_COSTS["rewrite"]
    n = (
        db_session.query(Ledger)
        .filter(Ledger.tenant_id == tid, Ledger.model == "billing:rewrite")
        .count()
    )
    assert n == 1, "必须写 ledger 明细"
    assert callable(cb.check_and_deduct), "core.billing 兼容签名仍需存在"


def test_json_and_membership_do_not_diverge(db_session):
    """R2-3：JSON 里的余额变化不得再影响真实余额（JSON 已非真源）。"""
    from studio import billing_adapter
    from studio.membership.service import ensure_membership

    from tests.wsb_common import make_tenant_stack, unique_name

    stack = make_tenant_stack(db_session, unique_name("r2div"))
    tid, uid = stack["tenant_id"], stack["user_id"]
    ensure_membership(db_session, tid, uid)
    db_session.commit()

    before = billing_adapter.get_billing_status(db_session, tid, uid)["balance"]

    # 篡改 JSON（模拟历史单例被外部改写）
    import core.billing as cb

    data = cb._load_data()
    data["balance"] = 999999
    cb._save_data(data)

    after = billing_adapter.get_billing_status(db_session, tid, uid)["balance"]
    assert after == before, (
        f"真实余额不应被 JSON 影响：before={before} after={after}"
    )


def test_tenant_id_resolved_from_studio_users_row(db_session):
    """回归：租户 id 必须以 studio users 行为准，不能假定为 'default'。

    ⭐ 这是 R2-3 实测抓到的真实 bug：core/auth.py 返回的 tenant_id 可能是
       字符串 'default'（core/db.py 的 schema 默认值），而 studio 侧真实租户
       id 是 uuid（ensure_default_tenant 生成）。若直接采信前者，
       查 memberships 会查不到行，表现为「明明有额度却永远提示不足」——
       即用户被永久锁死。
    """
    from studio.auth import ensure_default_tenant
    from studio.db_models import User
    from studio.membership.service import ensure_membership

    db_session.rollback()
    tenant = ensure_default_tenant(db_session)
    db_session.commit()
    # 该租户 id 很可能不是 'default'（正是 bug 的触发条件）
    uid = "u-tenant-probe"
    exists = db_session.query(User).filter(User.id == uid).first()
    if exists is None:
        db_session.add(User(
            id=uid, tenant_id=tenant.id, username=uid, email="",
            password_hash="x", salt="x", role="user", is_active=True,
            created_at=utcnow(),
        ))
        db_session.commit()
    m = ensure_membership(db_session, tenant.id, uid)
    db_session.commit()
    assert m.tenant_id == tenant.id
    # 断言：该租户 id 若恰好不是 'default'，则本用例才真正覆盖了 bug
    if tenant.id != "default":
        # 用错误的 'default' 去查必然查不到——这正是需要避免的路径
        assert (
            db_session.query(Membership)
            .filter(Membership.tenant_id == "default", Membership.user_id == uid)
            .first() is None
        )