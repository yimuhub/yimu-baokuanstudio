# SPDX-License-Identifier: BUSL-1.1
"""R10 新用户「首篇完整体验券」回归。

验收标准（对应审查报告 P0「首篇完整体验保障」）：
- FP-1 长文触发：free 档输出超 512 tokens 时自动用券，该次免扣费且不占每日次数
- FP-2 终身一次：第二次长文回落 too_long_output 正常规则
- FP-3 幂等：并发/重复核销只成功一次
- FP-4 状态可查询
- FP-5 短文（≤512）不消耗券
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-fp")

from studio import first_piece, llm_metering, pricing  # noqa: E402


@pytest.fixture()
def fp_isolated(monkeypatch, tmp_path):
    """把券状态与免费体验计数都指到临时目录。"""
    monkeypatch.setattr(first_piece, "_PATH", tmp_path / "first_piece_free.json")
    monkeypatch.setattr(llm_metering, "_DEMO_PATH", tmp_path / "free_demo_calls.json")
    return tmp_path


class TestFirstPiece:
    def test_long_output_consumes_voucher_once(self, fp_isolated, monkeypatch):
        uid = "u-fp-1"
        # 初始：有券
        assert first_piece.first_piece_available(uid) is True
        # 第一篇长文：超 512 上限 → 用券成功、免计费、不占每日次数
        r1 = llm_metering.consume_free_demo_call(uid, completion_tokens=3000)
        assert r1.get("eligible") is True
        assert r1.get("first_piece") is True
        # 今日免费次数未被占用
        assert llm_metering.free_demo_left_today(uid) == pricing.FREE_DEMO_DAILY_CALLS
        # 券已核销
        assert first_piece.first_piece_available(uid) is False
        st = first_piece.first_piece_status(uid)
        assert st["available"] is False and st["used_at"]
        # 第二篇长文：回落正常规则（too_long_output，需扣费）
        r2 = llm_metering.consume_free_demo_call(uid, completion_tokens=3000)
        assert r2.get("eligible") is False
        assert r2.get("reason") == "too_long_output"

    def test_short_output_never_touches_voucher(self, fp_isolated):
        uid = "u-fp-2"
        r = llm_metering.consume_free_demo_call(uid, completion_tokens=100)
        assert r.get("eligible") is True
        assert "first_piece" not in r  # 短文走每日免费，不用券
        assert first_piece.first_piece_available(uid) is True

    def test_consume_is_idempotent_under_lock(self, fp_isolated):
        uid = "u-fp-3"
        assert first_piece.consume_first_piece(uid) is True
        assert first_piece.consume_first_piece(uid) is False
        assert first_piece.consume_first_piece(uid) is False

    def test_corrupt_state_file_falls_back_to_available(self, fp_isolated):
        uid = "u-fp-4"
        p = Path(fp_isolated) / "first_piece_free.json"
        p.write_text("{corrupted!!", encoding="utf-8")
        # 损坏按「未使用」兜底：宁可多发一次，不可把用户卡死
        assert first_piece.first_piece_available(uid) is True

    def test_empty_user_id_never_eligible(self, fp_isolated):
        assert first_piece.first_piece_available("") is False
        assert first_piece.consume_first_piece("") is False
