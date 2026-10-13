# SPDX-License-Identifier: BUSL-1.1
"""TTS 三引擎切换链测试（降级链容灾机制）。

⭐ 硬规则：
- 云端 TTS 默认不在链中（防静默扣费），显式开启才加入。
- 单引擎失败必须被隔离，链条继续试下一个。
"""

from __future__ import annotations

import os
import wave

import pytest

from studio.audio.chain import DEFAULT_CHAIN, build_chain, synthesize_with_chain
from studio.audio.engines import BaseEngine, EngineResult, LocalToneEngine


class _FailingEngine(BaseEngine):
    """测试替身：永远抛错的引擎。"""

    name = "failing"

    def synthesize(self, text, out_path, *, voice="xiaoxiao", rate=0):
        raise RuntimeError("模拟引擎故障")


class _ScriptedEngine(BaseEngine):
    """测试替身：按脚本成功并记录调用顺序。"""

    name = "scripted"
    calls: list[str] = []

    def synthesize(self, text, out_path, *, voice="xiaoxiao", rate=0):
        _ScriptedEngine.calls.append(self.name)
        with open(out_path, "wb") as f:
            f.write(b"FAKEAUDIO")
        return EngineResult(out_path=out_path)


def _clear_env(monkeypatch):
    monkeypatch.delenv("YIMU_TTS_CLOUD_ENABLED", raising=False)
    monkeypatch.delenv("YIMU_TTS_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("YIMU_TTS_CLOUD_API_URL", raising=False)


def test_default_chain_excludes_cloud():
    """⭐ 默认链只有免费引擎，云端永不默认进入。"""
    assert "cloud" not in DEFAULT_CHAIN
    chain = build_chain()
    assert [e.name for e in chain] == ["edge", "local"]


def test_cloud_requires_explicit_opt_in():
    """⭐ order 里写了 cloud 但没显式开启 → 直接拒绝构造。"""
    with pytest.raises(ValueError, match="显式开启"):
        build_chain(order=["edge", "cloud", "local"], enable_cloud=False)


def test_cloud_engine_needs_env_switch(monkeypatch):
    """⭐ 云端引擎 available 要求环境变量三件套；缺一不可。"""
    _clear_env(monkeypatch)
    from studio.audio.engines import CloudTTSEngine

    assert not CloudTTSEngine().available
    monkeypatch.setenv("YIMU_TTS_CLOUD_ENABLED", "1")
    monkeypatch.setenv("YIMU_TTS_CLOUD_API_KEY", "test-key")
    # 缺 API_URL 仍不可用
    assert not CloudTTSEngine().available
    monkeypatch.setenv("YIMU_TTS_CLOUD_API_URL", "https://tts.example.com")
    assert CloudTTSEngine().available


def test_failover_order_and_isolation(tmp_path, monkeypatch):
    """引擎切换顺序断言：failing 抛错被隔离，scripted 接管，报告记录全过程。"""
    _clear_env(monkeypatch)
    import studio.audio.chain as chain_mod

    monkeypatch.setitem(chain_mod._ENGINE_CLASSES, "failing", _FailingEngine)
    monkeypatch.setitem(chain_mod._ENGINE_CLASSES, "scripted", _ScriptedEngine)
    _ScriptedEngine.calls.clear()

    out = str(tmp_path / "out.bin")
    report = synthesize_with_chain("测试文本", out, order=["failing", "scripted", "local"])
    assert report.engine_used == "scripted"
    assert os.path.getsize(out) > 0
    # 报告里能看到 failing 的错误和 scripted 的成功
    kinds = [(a["engine"], a.get("error"), a.get("ok")) for a in report.attempts]
    assert kinds[0][0] == "failing" and kinds[0][1]
    assert kinds[1] == ("scripted", None, True)


def test_local_engine_produces_real_wav(tmp_path):
    """本地兜底引擎：真实产出合法 WAV（>0 字节），同时链条写出 .srt。"""
    out = str(tmp_path / "fallback.wav")
    report = synthesize_with_chain("你好，一幕开场。", out, order=["local"])
    assert report.engine_used == "local"
    assert report.degraded is True
    assert os.path.getsize(out) > 0
    with wave.open(out, "rb") as w:
        assert w.getnchannels() == 1 and w.getframerate() == 22050
    assert report.subtitle_path and os.path.getsize(report.subtitle_path) > 0


def test_synthesize_entry_matches_probe_contract(tmp_path, monkeypatch):
    """synthesize(text, out_path, db_url) 端到端：产物存在且 >0 字节（探针判据）。"""
    _clear_env(monkeypatch)
    import tempfile

    from studio.tts import synthesize

    fd, db_path = tempfile.mkstemp(prefix="yimu_tts_test_", suffix=".db")
    os.close(fd)
    out = str(tmp_path / "hello.wav")
    result = synthesize("你好，一幕开场。", out, f"sqlite:///{db_path}")
    assert result == out
    assert os.path.exists(out) and os.path.getsize(out) > 0
