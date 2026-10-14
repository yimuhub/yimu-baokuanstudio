"""LLM 双轨制计量测试：官方通道扣费 + 全供应商统计 + V9.3.2 免费体验额度。"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import llm_metering


@pytest.fixture
def tmp_usage(tmp_path, monkeypatch):
    p = tmp_path / "llm_usage.json"
    monkeypatch.setattr(llm_metering, "_USAGE_PATH", p)
    return p


def test_official_provider_registered_first():
    """yimu_official 在 MODEL_PROVIDERS 第一个位置，标记正确。"""
    from core import llm

    first_key = next(iter(llm.MODEL_PROVIDERS))
    assert first_key == "yimu_official"
    info = llm.MODEL_PROVIDERS["yimu_official"]
    assert info["official"] is True
    assert info["metered"] is True
    assert info["badge"] == "官方计费"


def test_other_provider_records_stats_no_deduction(tmp_usage):
    """非官方 provider：记统计，不扣额度。"""
    r = llm_metering.record_llm_call("deepseek", "deepseek-chat", 100, 50, 150, user_id="u-x")
    assert r["metered"] is False
    assert r["deducted"] == 0
    usage = llm_metering.get_provider_usage()
    assert usage["deepseek"]["calls"] == 1
    assert usage["deepseek"]["total_tokens"] == 150
    assert usage["deepseek"]["metered"] is False


def test_official_deducts_credits(tmp_usage):
    """官方通道：扣减额度并记统计。

    ⭐ R2-2：扣减的是**credits**（per-1k 换算），不再是 token 数。
       yimu-chat 单价 input 2 / output 4 credits per 1k，
       100 prompt + 50 completion tokens → ceil(100/1000*2)=1 + ceil(50/1000*4)=1 = 2 credits。
    """
    from studio import pricing

    # ⭐ V9.3.2：consume_free_demo_call 的档位判定需 mock，
    #   否则真连 DB 判 tier 会异常/误判。统一 patch 为 unknown → 不享受免费体验。
    _caps = "studio.membership.capabilities"
    fake_db = MagicMock()
    fake_tier = "unknown-tier-paid"  # 非 free，走正常扣费
    with patch(f"{_caps}.get_db_session", return_value=fake_db), \
         patch(f"{_caps}.get_user_tier", return_value=fake_tier), \
         patch("studio.membership.service.deduct_credits", return_value=(True, 29998)) as mock_deduct:
        r = llm_metering.record_llm_call("yimu_official", "yimu-chat", 100, 50, 150, user_id="u-pro")
    in_c, out_c = pricing.credits_for_call("yimu-chat", 100, 50)
    expected = in_c + out_c
    assert expected == 2, f"per-1k 换算口径应得2 credits，实际 {expected}"
    assert r["metered"] is True
    assert r["deducted"] == expected, "扣除的应是 credits 而非 token 数"
    assert r["left"] == 29998
    mock_deduct.assert_called_once()
    args = mock_deduct.call_args[0]
    assert args[3] == expected, f"amount 应为换算后的 credits {expected}，实际 {args[3]}"
    usage = llm_metering.get_provider_usage()
    assert usage["yimu_official"]["metered"] is True
    assert usage["yimu_official"]["deducted_total"] == expected


def test_official_insufficient_credits_raises(tmp_usage, tmp_demo, monkeypatch):
    """官方通道额度不足：抛 InsufficientCreditsError（402 风格）。

    ⭐ 该测试用 free 档 + 免费体验额度已耗尽的前置状态，
       验证"耗尽后回落正常扣费 → 额度不足抛错"的完整链路。"""
    # 前置：先把今日免费体验额度用尽（3 次）
    _patch_tier_free(monkeypatch)
    _caps = "studio.membership.capabilities"
    _svc = "studio.membership.service"
    with patch(f"{_caps}.get_db_session", return_value=MagicMock()), \
         patch(f"{_caps}.get_user_tier", return_value="free"), \
         patch(f"{_svc}.deduct_credits", return_value=(True, 10)):
        for _ in range(llm_metering.pricing.FREE_DEMO_DAILY_CALLS):
            llm_metering.record_llm_call("yimu_official", "yimu-chat", 10, 5, 15, user_id="u-free")
    assert llm_metering.free_demo_left_today("u-free") == 0
    # 第 N+1 次：已耗免费体验额度 → 回落正常扣费 → 额度不足 → 抛错
    fake_db = MagicMock()
    with patch(f"{_caps}.get_db_session", return_value=fake_db), \
         patch(f"{_caps}.get_user_tier", return_value="free"), \
         patch(f"{_svc}.deduct_credits", return_value=(False, 10)):
        with pytest.raises(llm_metering.InsufficientCreditsError) as exc_info:
            llm_metering.record_llm_call("yimu_official", "yimu-chat", 100, 50, 150, user_id="u-free")
    assert "额度不足" in str(exc_info.value)


def test_official_no_user_id_skips_deduction(tmp_usage):
    """官方通道无 user_id：仅记统计不扣费，不抛异常。"""
    r = llm_metering.record_llm_call("yimu_official", "yimu-chat", 10, 5, 15, user_id=None)
    assert r["metered"] is True
    assert r["deducted"] == 0
    # 无 user_id 时不享受免费体验（免费额度以用户为粒度）
    assert r["free_demo"] is False
    usage = llm_metering.get_provider_usage()
    assert usage["yimu_official"]["calls"] == 1


def test_usage_accumulates_across_calls(tmp_usage):
    """多次调用累加统计。"""
    llm_metering.record_llm_call("qwen", "qwen-max", 100, 0, 100)
    llm_metering.record_llm_call("qwen", "qwen-max", 200, 100, 300)
    usage = llm_metering.get_provider_usage()
    assert usage["qwen"]["calls"] == 2
    assert usage["qwen"]["total_tokens"] == 400
    assert usage["qwen"]["prompt_tokens"] == 300


def test_get_official_summary(tmp_usage):
    """官方通道汇总返回消费数据。"""
    llm_metering.record_llm_call("yimu_official", "yimu-chat", 100, 50, 150, user_id=None)
    s = llm_metering.get_yimu_official_summary()
    assert s["provider_id"] == "yimu_official"
    assert s["calls"] == 1
    assert s["total_tokens"] == 150


def test_estimate_tokens_chinese():
    """中文文本估算：约 0.6 token/字。"""
    est = llm_metering.estimate_tokens("你好世界")
    assert 1 <= est <= 4  # 4字 -> 约2-3


def test_estimate_tokens_english():
    """英文文本估算：约 0.25 token/字符。"""
    est = llm_metering.estimate_tokens("hello world foo bar")
    assert 1 <= est <= 8


def test_estimate_tokens_empty():
    assert llm_metering.estimate_tokens("") == 0
    assert llm_metering.estimate_tokens(None) == 0


def test_record_falls_back_to_estimation(tmp_usage):
    """usage 缺失时用文本估算兜底，不再是 0。"""
    r = llm_metering.record_llm_call(
        "yimu_official", "yimu-chat", 0, 0, 0,
        user_id=None,
        prompt_text="请写一篇爆款文章",
        completion_text="这是一篇测试文章的内容" * 10,
    )
    assert r["estimated"] is True
    usage = llm_metering.get_provider_usage()
    assert usage["yimu_official"]["total_tokens"] > 0


# ---------------------------------------------------------------------------
# ⭐ V9.3.2 免费体验额度（官方通道免费降级 · 审查报告 P0-1 修复）
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_demo(tmp_path, monkeypatch):
    p = tmp_path / "free_demo_calls.json"
    monkeypatch.setattr(llm_metering, "_DEMO_PATH", p)
    return p


def _patch_tier_free(monkeypatch, tier="free"):
    """让 consume_free_demo_call 的档位判定走 free 档。"""
    monkeypatch.setattr(
        "studio.membership.capabilities.get_user_tier",
        lambda db, tenant_id, user_id: tier,
    )
    monkeypatch.setattr(
        "studio.membership.capabilities.get_db_session",
        lambda: MagicMock(),
    )


def test_free_demo_first_call_no_deduction(tmp_usage, tmp_demo, monkeypatch):
    """free 档官方通道第一次：免扣费（free_demo=True），deducted=0。"""
    _patch_tier_free(monkeypatch)
    with patch("studio.membership.service.deduct_credits") as mock_deduct:
        r = llm_metering.record_llm_call(
            "yimu_official", "yimu-chat", 100, 50, 150, user_id="u-free-demo")
    assert r["free_demo"] is True
    assert r["deducted"] == 0
    assert r["free_demo_left"] == llm_metering.pricing.FREE_DEMO_DAILY_CALLS - 1
    mock_deduct.assert_not_called()


def test_free_demo_exhausted_falls_back_to_billing(tmp_usage, tmp_demo, monkeypatch):
    """免费体验次数耗尽 → 自动回落正常扣费。"""
    _patch_tier_free(monkeypatch)
    with patch("studio.membership.service.deduct_credits", return_value=(True, 2998)) as mock_deduct:
        for i in range(llm_metering.pricing.FREE_DEMO_DAILY_CALLS):
            r = llm_metering.record_llm_call(
                "yimu_official", "yimu-chat", 100, 50, 150, user_id="u-free-demo2")
            assert r["free_demo"] is (i < llm_metering.pricing.FREE_DEMO_DAILY_CALLS - 1 or True)
        # 第 N+1 次：超出免费额度，必须走扣费
        r = llm_metering.record_llm_call(
            "yimu_official", "yimu-chat", 100, 50, 150, user_id="u-free-demo2")
    assert r["free_demo"] is False
    assert r["deducted"] > 0
    mock_deduct.assert_called_once()


def test_free_demo_long_output_not_eligible(tmp_usage, tmp_demo, monkeypatch):
    """单次输出超 FREE_DEMO_MAX_OUTPUT_TOKENS → 不享受免费体验，正常扣费。"""
    _patch_tier_free(monkeypatch)
    with patch("studio.membership.service.deduct_credits", return_value=(True, 20000)) as mock_deduct:
        r = llm_metering.record_llm_call(
            "yimu_official", "yimu-chat", 100,
            llm_metering.pricing.FREE_DEMO_MAX_OUTPUT_TOKENS + 1,
            9999, user_id="u-long-out")
    assert r["free_demo"] is False
    assert r["deducted"] > 0
    mock_deduct.assert_called_once()


def test_free_demo_paid_tier_not_eligible(tmp_usage, tmp_demo, monkeypatch):
    """pro 档不占用免费体验额度（付费档直接正常扣费）。"""
    _patch_tier_free(monkeypatch, tier="pro")
    with patch("studio.membership.service.deduct_credits", return_value=(True, 29980)):
        r = llm_metering.record_llm_call(
            "yimu_official", "yimu-chat", 100, 50, 150, user_id="u-pro")
    assert r["free_demo"] is False
    assert r["deducted"] > 0


def test_free_demo_left_today_reflects_usage(tmp_usage, tmp_demo, monkeypatch):
    """free_demo_left_today：用掉 1 次后剩 2。"""
    _patch_tier_free(monkeypatch)
    assert llm_metering.free_demo_left_today("u-check") == llm_metering.pricing.FREE_DEMO_DAILY_CALLS
    llm_metering.record_llm_call("yimu_official", "yimu-chat", 100, 50, 150, user_id="u-check")
    assert llm_metering.free_demo_left_today("u-check") == llm_metering.pricing.FREE_DEMO_DAILY_CALLS - 1
