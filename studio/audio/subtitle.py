# SPDX-License-Identifier: BUSL-1.1
"""字幕生成：文本 → .srt 时间轴（移植自项目 A 的 subtitle 思路）。

按语速估算每句时长，保证字幕与音频大致对齐；兜底引擎也一定产出字幕。
"""

from __future__ import annotations

import re

# 中文朗读语速：约每秒 5 个字（含标点停顿折算）
CHARS_PER_SECOND = 5.0
MIN_LINE_SECONDS = 1.0


def split_sentences(text: str) -> list[str]:
    """按中英文句末标点切分，保留标点。"""
    parts = re.split(r"(?<=[。！？!?；;])", text)
    return [p.strip() for p in parts if p.strip()]


def _fmt_ts(seconds: float) -> str:
    ms = int(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(text: str, srt_path: str) -> str:
    """把文本写成 .srt 字幕文件，返回路径。

    时长估算：len(句子)/CHARS_PER_SECOND，单句不低于 1 秒。
    """
    sentences = split_sentences(text) or [text.strip()]
    cursor = 0.0
    blocks: list[str] = []
    for i, sent in enumerate(sentences, 1):
        dur = max(MIN_LINE_SECONDS, len(sent) / CHARS_PER_SECOND)
        start, end = cursor, cursor + dur
        blocks.append(f"{i}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{sent}\n")
        cursor = end + 0.2  # 句间留白
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    return srt_path
