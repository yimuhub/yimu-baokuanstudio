# SPDX-License-Identifier: BUSL-1.1
"""TTS 对外入口：synthesize(text, out_path, db_url) -> str。

签名与 tests/probes.py 真活探针约定的完全一致：
判据 = 音频文件存在且 >0 字节。
db_url 保留给后续账本/审计扩展；当前仅做生产库隔离校验（⭐ 测试绝不碰真库）。
"""

from __future__ import annotations

from typing import Sequence

from .audio.chain import ChainReport, synthesize_with_chain


def synthesize(
    text: str,
    out_path: str,
    db_url: str,
    *,
    engine_order: Sequence[str] | None = None,
    enable_cloud: bool = False,
    voice: str = "xiaoxiao",
    rate: int = 0,
) -> str:
    """合成语音并返回音频文件路径。

    走三引擎自动切换链；云端 TTS 默认不进链（⭐ 防静默扣费）。
    """
    _assert_db_isolated(db_url)
    report = synthesize_with_chain(
        text,
        out_path,
        order=engine_order,
        enable_cloud=enable_cloud,
        voice=voice,
        rate=rate,
    )
    return report.out_path


def synthesize_report(
    text: str,
    out_path: str,
    db_url: str,
    *,
    engine_order: Sequence[str] | None = None,
    enable_cloud: bool = False,
    voice: str = "xiaoxiao",
    rate: int = 0,
) -> ChainReport:
    """带完整执行报告的合成入口（测试/排障用）。"""
    _assert_db_isolated(db_url)
    return synthesize_with_chain(
        text,
        out_path,
        order=engine_order,
        enable_cloud=enable_cloud,
        voice=voice,
        rate=rate,
    )


def _assert_db_isolated(db_url: str) -> None:
    """⭐ 生产库守卫：复用 conftest 的隔离逻辑（conftest 不可用时用最小实现）。"""
    try:
        from tests.conftest import assert_test_db_isolated

        path = db_url[len("sqlite:///") :] if db_url.startswith("sqlite:///") else db_url
        assert_test_db_isolated(path)
    except ImportError:
        lowered = str(db_url).lower()
        for marker in ("prod", "yimu.db", "runs/"):
            if marker in lowered:
                raise RuntimeError(f"⛔ 拦截疑似生产库：{db_url}")
