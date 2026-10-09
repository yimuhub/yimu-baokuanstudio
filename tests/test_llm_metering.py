"""LLM 双轨制计量测试：官方通道扣费 + 全供应商统计。"""
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

    fake_db = MagicMock()
    with patch("studio.membership.capabilities.get_db_session", return_value=fake_db), \
         patch("studio.membership.capabilities.get_user_tier", return_value="pro"), \
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


def test_official_insufficient_credits_raises(tmp_usage):
    """官方通道额度不足：抛 InsufficientCreditsError（402 风格）。"""
    fake_db = MagicMock()
    with patch("studio.membership.capabilities.get_db_session", return_value=fake_db), \
         patch("studio.membership.capabilities.get_user_tier", return_value="free"), \
         patch("studio.membership.service.deduct_credits", return_value=(False, 10)):
        with pytest.raises(llm_metering.InsufficientCreditsError) as exc_info:
            llm_metering.record_llm_call("yimu_official", "yimu-chat", 100, 50, 150, user_id="u-free")
    assert "额度不足" in str(exc_info.value)


def test_official_no_user_id_skips_deduction(tmp_usage):
    """官方通道无 user_id：仅记统计不扣费，不抛异常。"""
    r = llm_metering.record_llm_call("yimu_official", "yimu-chat", 10, 5, 15, user_id=None)
    assert r["metered"] is True
    assert r["deducted"] == 0
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
