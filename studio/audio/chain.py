# SPDX-License-Identifier: BUSL-1.1
"""TTS 三引擎自动切换链（移植自项目 A 的 tts_chain.py 设计）。

链条顺序（⭐ 扣费红线）：
1. Edge-TTS（免费真人声，首选；缺包/无网时自动跳过）
2. 云端 TTS（⭐ 默认不在链中！需 enable_cloud=True 显式开启，防静默扣费）
3. 本地兜底引擎（纯标准库 wave 合成提示音 + 字幕，保证不断流）

任一引擎抛错只影响自己，链条自动试下一个；全部真实引擎失败才走兜底。
对外入口见 studio/tts.py::synthesize（真活探针签名）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .engines import BaseEngine, CloudTTSEngine, EdgeTTSEngine, LocalToneEngine
from .subtitle import write_srt


@dataclass
class ChainReport:
    """一次切换链执行的完整记录（供日志/测试断言）。"""

    out_path: str
    subtitle_path: str | None
    engine_used: str
    degraded: bool
    attempts: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.out_path)


# ⭐ 扣费红线：默认链只有免费引擎；云端 TTS 永不默认进入。
DEFAULT_CHAIN: tuple[str, ...] = ("edge", "local")

_ENGINE_CLASSES: dict[str, type[BaseEngine]] = {
    "edge": EdgeTTSEngine,
    "cloud": CloudTTSEngine,
    "local": LocalToneEngine,
}


def build_chain(order: Sequence[str] | None = None, *, enable_cloud: bool = False) -> list[BaseEngine]:
    """按指定顺序构造引擎实例。

    ⭐ 云端引擎只有 enable_cloud=True 才会被加入链条；默认链见 DEFAULT_CHAIN。
    """
    names = list(order) if order is not None else list(DEFAULT_CHAIN)
    if "cloud" in names and not enable_cloud:
        raise ValueError("云端 TTS 需要显式开启（enable_cloud=True），不会静默加入链条。")
    chain: list[BaseEngine] = []
    for name in names:
        cls = _ENGINE_CLASSES.get(name)
        if cls is None:
            raise ValueError(f"未知 TTS 引擎：{name}")
        chain.append(cls())
    return chain


def synthesize_with_chain(
    text: str,
    out_path: str,
    *,
    order: Sequence[str] | None = None,
    enable_cloud: bool = False,
    voice: str = "xiaoxiao",
    rate: int = 0,
) -> ChainReport:
    """走切换链合成语音，返回执行报告。

    ⭐ 失败隔离：单个引擎抛错只记录并继续，不中断链条。
    字幕文件与音频同名（.srt 后缀），每个引擎成功后都会顺手写一份。
    """
    if not text or not text.strip():
        raise ValueError("合成文本为空")
    chain = build_chain(order, enable_cloud=enable_cloud)
    attempts: list[dict] = []
    for engine in chain:
        if not engine.available:
            attempts.append({"engine": engine.name, "skipped": True, "reason": engine.unavailable_reason})
            continue
        try:
            result = engine.synthesize(text, out_path, voice=voice, rate=rate)
        except Exception as exc:  # noqa: BLE001 — ⭐ 失败隔离：吞掉单引擎异常继续链条
            attempts.append({"engine": engine.name, "skipped": False, "error": f"{type(exc).__name__}: {exc}"})
            continue
        subtitle_path = write_srt(text, _srt_path(out_path))
        attempts.append({"engine": engine.name, "skipped": False, "ok": True})
        return ChainReport(
            out_path=result.out_path,
            subtitle_path=subtitle_path,
            engine_used=engine.name,
            degraded=result.degraded,
            attempts=attempts,
        )
    failed = "; ".join(a.get("error", a.get("reason", "?")) for a in attempts)
    raise RuntimeError(f"TTS 切换链全部引擎失败：{failed}")


def _srt_path(out_path: str) -> str:
    base = out_path.rsplit(".", 1)[0]
    return f"{base}.srt"
