# SPDX-License-Identifier: BUSL-1.1
"""★ V7.1：TTS 三引擎自动切换链（移植自项目 A）。

Edge-TTS → 云端 TTS → 本地兜底（字幕必产出）；云端不进默认链（防静默扣费）。
V7.0 先留接口与骨架。

对外入口：studio.tts.synthesize(text, out_path, db_url) -> str
"""

from .chain import ChainReport, build_chain, synthesize_with_chain
from .engines import (
    BaseEngine,
    CloudTTSEngine,
    EdgeTTSEngine,
    EngineResult,
    LocalToneEngine,
    VOICES,
    resolve_voice,
    synthesize,
    synthesize_async,
)
from .subtitle import split_sentences, write_srt

__all__ = [
    "ChainReport",
    "build_chain",
    "synthesize_with_chain",
    # v15.9.9 归一后的全仓唯一 TTS 业务入口（探针契约入口仍是 studio.tts.synthesize）
    "synthesize",
    "synthesize_async",
    "resolve_voice",
    "EngineResult",
    "BaseEngine",
    "EdgeTTSEngine",
    "CloudTTSEngine",
    "LocalToneEngine",
    "VOICES",
    "write_srt",
    "split_sentences",
]
