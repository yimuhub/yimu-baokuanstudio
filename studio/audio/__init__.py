# SPDX-License-Identifier: BUSL-1.1
"""★ V7.1：TTS 三引擎自动切换链（移植自项目 A）。

Edge-TTS → 云端 TTS → 本地兜底（字幕必产出）；云端不进默认链（防静默扣费）。
V7.0 先留接口与骨架。

对外入口：studio.tts.synthesize(text, out_path, db_url) -> str
"""

from .chain import ChainReport, build_chain, synthesize_with_chain
from .engines import BaseEngine, CloudTTSEngine, EdgeTTSEngine, LocalToneEngine, VOICES
from .subtitle import split_sentences, write_srt

__all__ = [
    "ChainReport",
    "build_chain",
    "synthesize_with_chain",
    "BaseEngine",
    "EdgeTTSEngine",
    "CloudTTSEngine",
    "LocalToneEngine",
    "VOICES",
    "write_srt",
    "split_sentences",
]
