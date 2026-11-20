# SPDX-License-Identifier: BUSL-1.1
"""TTS 引擎实现：Edge-TTS / 云端 TTS / 本地兜底。

统一接口 BaseEngine，切换链只依赖接口不依赖具体引擎（插件化）。
"""

from __future__ import annotations

import math
import os
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅供注解解析（asyncio 在函数体内按需 import，避免模块级无用依赖）
    import asyncio


# 中文常用音色（edge-tts 声音名）
VOICES: dict[str, str] = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",  # 女声，通用首选
    "yunxi": "zh-CN-YunxiNeural",  # 男声
    "yunjian": "zh-CN-YunjianNeural",  # 男声，偏播报
    "xiaoyi": "zh-CN-XiaoyiNeural",  # 女声，偏活泼
}

# 全名反向索引（小写 → 真名）：core 侧历史传全名、A 链传短键，
# 归一后 resolve_voice 两种格式都接受（why：四份旧 TTS 实现各自猜格式，
# 音色错乱只有用户能发现；统一映射后修一处即全局生效）。
_VOICE_FULL_ALIASES: dict[str, str] = {name.lower(): name for name in VOICES.values()}


def resolve_voice(voice: str) -> str:
    """音色名统一映射：短键（xiaoxiao）与全名（zh-CN-XiaoxiaoNeural）都接受。

    未知短键回落 xiaoxiao（与旧 VOICES.get 行为一致）；其它语种的
    ``*Neural`` 全名（如 en-US-GuyNeural）原样透传给 edge-tts。
    """
    v = (voice or "").strip()
    if not v:
        return VOICES["xiaoxiao"]
    low = v.lower()
    if low in VOICES:
        return VOICES[low]
    if low in _VOICE_FULL_ALIASES:
        return _VOICE_FULL_ALIASES[low]
    if low.endswith("neural"):
        return v
    return VOICES["xiaoxiao"]


@dataclass
class EngineResult:
    out_path: str
    degraded: bool = False  # True = 非真人声兜底产物


class BaseEngine:
    """引擎基类：available 为 False 时链条自动跳过。"""

    name = "base"

    @property
    def available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str:
        return ""

    def synthesize(self, text: str, out_path: str, *, voice: str = "xiaoxiao", rate: int = 0) -> EngineResult:
        raise NotImplementedError


class EdgeTTSEngine(BaseEngine):
    """Edge-TTS：微软免费神经网络语音，无需 key。

    可用条件：装了 edge-tts 包且能连到 speech.platform.bing.com。
    缺包/无网 → available=False，链条静默跳过（不算失败）。
    """

    name = "edge"

    def __init__(self) -> None:
        self._mod = None
        self._reason = ""
        try:
            import edge_tts  # type: ignore[import-not-found]

            self._mod = edge_tts
        except ImportError:
            self._reason = "未安装 edge-tts 包（pip install edge-tts）"

    @property
    def available(self) -> bool:
        return self._mod is not None

    @property
    def unavailable_reason(self) -> str:
        return self._reason

    def synthesize(self, text: str, out_path: str, *, voice: str = "xiaoxiao", rate: int = 0) -> EngineResult:
        import asyncio

        # 归一后接受短键与全名两种音色格式（resolve_voice 统一映射）
        voice_name = resolve_voice(voice)
        # rate: -50 ~ +50 百分比，edge-tts 格式如 "+10%"
        rate_str = f"{rate:+d}%" if rate else "+0%"

        async def _run() -> None:
            communicate = self._mod.Communicate(text, voice=voice_name, rate=rate_str)
            await communicate.save(out_path)

        asyncio.run(_run())
        return EngineResult(out_path=out_path)


class CloudTTSEngine(BaseEngine):
    """云端 TTS：按量计费的上游语音服务。

    ⭐ 扣费红线（三重保护）：
    1. 默认不在切换链中，只有 enable_cloud=True 才加入；
    2. available 要求显式开关注入：环境变量 YIMU_TTS_CLOUD_ENABLED=1；
    3. Key 只从环境变量 YIMU_TTS_CLOUD_API_KEY 读取，绝不硬编码、不进默认配置。
    上游协议：POST {api_url}/tts，JSON {text, voice}，返回音频字节。
    具体上游对接在 _call_upstream 中按所选服务商实现。
    """

    name = "cloud"

    def __init__(self) -> None:
        self.api_url = os.environ.get("YIMU_TTS_CLOUD_API_URL", "").strip()
        self.api_key = os.environ.get("YIMU_TTS_CLOUD_API_KEY", "").strip()
        self.enabled = os.environ.get("YIMU_TTS_CLOUD_ENABLED", "") == "1"

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.api_url and self.api_key)

    @property
    def unavailable_reason(self) -> str:
        if not self.enabled:
            return "云端 TTS 未显式开启（YIMU_TTS_CLOUD_ENABLED=1）"
        if not self.api_key:
            return "缺少 YIMU_TTS_CLOUD_API_KEY"
        return "缺少 YIMU_TTS_CLOUD_API_URL"

    def synthesize(self, text: str, out_path: str, *, voice: str = "xiaoxiao", rate: int = 0) -> EngineResult:
        # ⭐ 二次确认：即使进了链条，调用前再查一次开关
        if os.environ.get("YIMU_TTS_CLOUD_ENABLED", "") != "1":
            raise RuntimeError("云端 TTS 未显式开启，拒绝调用（防静默扣费）。")
        audio_bytes = self._call_upstream(text, voice=voice)
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        return EngineResult(out_path=out_path)

    def _call_upstream(self, text: str, *, voice: str) -> bytes:
        """调用云端上游。按所选服务商实现具体协议；超时必须抛错以便链条继续。"""
        import json
        import urllib.request

        req = urllib.request.Request(
            self.api_url.rstrip("/") + "/tts",
            data=json.dumps({"text": text, "voice": voice}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()


class LocalToneEngine(BaseEngine):
    """本地兜底引擎：纯标准库，按文本长度生成提示音 WAV。

    不是真人声（degraded=True），作用是保证链条不断流：
    下游视频合成等环节一定能拿到一条有效音频轨。
    字幕文件由切换链统一写 .srt。
    """

    name = "local"

    def synthesize(self, text: str, out_path: str, *, voice: str = "xiaoxiao", rate: int = 0) -> EngineResult:
        _write_tone_wav(text, out_path)
        return EngineResult(out_path=out_path, degraded=True)


def _write_tone_wav(text: str, out_path: str, *, sample_rate: int = 22050) -> None:
    """按文本长度生成正弦提示音：每字约 0.35 秒，首尾淡入淡出。"""
    seconds = min(60.0, max(1.0, len(text) * 0.35))
    n = int(sample_rate * seconds)
    freq = 440.0
    frames = bytearray()
    fade = int(sample_rate * 0.05)
    for i in range(n):
        t = i / sample_rate
        amp = 0.5
        if i < fade:
            amp *= i / fade
        elif i > n - fade:
            amp *= (n - i) / fade
        # 轻微颤音，避免听感像单调蜂鸣
        v = amp * math.sin(2 * math.pi * freq * t) * (0.8 + 0.2 * math.sin(2 * math.pi * 5 * t))
        frames += struct.pack("<h", int(v * 32767))
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))


# ---------------------------------------------------------------------------
# ⭐ 全仓唯一 TTS 引擎封装（v15.9.9 归一）
#
# why：此前 core/audio.py、core/video_native.py、core/short_drama.py 各自维护
# 一份 TTS 实现（直连 / 直连 / CLI 子进程），加上本模块的 A 链共四份，行为
# 不一致——音色映射、倍率换算、失败处置各写各的；短剧那份失败还会用 ffmpeg
# 生成 3.5s 静音音频冒充成功，用户拿到无声剧集却无任何报错。
# 归一后所有调用点走 synthesize / synthesize_async：短键与全名音色统一映射、
# 失败显式抛错、并发场景进程内 await（edge_tts.Communicate 本身是异步库，
# 不再 spawn 子进程）。本地提示音引擎不进本入口——需要「一定能出声」的
# 探针/切换链场景继续走 studio.audio.chain（含提示音兜底），业务链路要的
# 是「明确知道失败」，静音兜底只会把失败藏进成片。
# ---------------------------------------------------------------------------


def _validate_output(out_path: str) -> None:
    """产物校验：缺失或小于 1KB 视为失败。

    why：TTS 上游偶发返回空流/截断流，不校验会把空文件当成功写进成片，
    用户听到的是无声视频而日志显示「成功」，排障成本极高。
    """
    p = Path(out_path)
    if not p.exists() or p.stat().st_size < 1000:
        raise RuntimeError(f"TTS 产物异常（缺失或小于 1KB）: {out_path}")


def _rate_pct_from_multiplier(rate: float) -> int:
    """语速倍率（1.0=常速）→ edge-tts 整数百分比（-50~50）。"""
    try:
        mult = float(rate)
    except (TypeError, ValueError):
        mult = 1.0
    if mult <= 0:
        mult = 1.0  # 非正倍率非法（0 倍速等于无声），按常速处理
    return max(-50, min(50, int(round((mult - 1.0) * 100))))


def synthesize(text: str, voice: str, out_path: str, *,
               rate: float = 1.0, enable_cloud: bool = False) -> EngineResult:
    """统一 TTS 入口（同步版）：真实人声合成，任何失败抛 RuntimeError。

    引擎次序：Edge-TTS（免费首选）→ 云端 TTS（仅 enable_cloud=True 才加入，
    ⭐ 防静默扣费红线）。与 studio.tts.synthesize 的分工：后者是探针契约
    入口（全链失败落到本地提示音，保证探针产物存在）；本入口给业务链路用，
    失败必须向上抛。

    Args:
        text: 待合成文本（纯口播文本）
        voice: 音色短键（xiaoxiao/yunxi/…）或 edge-tts 全名（zh-CN-XiaoxiaoNeural）
        out_path: 产物路径（mp3/wav 均可，edge-tts 按扩展名写流）
        rate: 语速倍率（1.0=常速，0.5~1.5）
        enable_cloud: 是否允许云端 TTS 引擎参与
    """
    if not (text or "").strip():
        raise ValueError("合成文本为空")
    rate_pct = _rate_pct_from_multiplier(rate)
    errors: list[str] = []
    engines: list[BaseEngine] = [EdgeTTSEngine()]
    if enable_cloud:
        engines.append(CloudTTSEngine())
    for eng in engines:
        if not eng.available:
            errors.append(f"{eng.name}: {eng.unavailable_reason}")
            continue
        try:
            result = eng.synthesize(text, out_path, voice=resolve_voice(voice), rate=rate_pct)
        except Exception as exc:  # noqa: BLE001 — 失败隔离：单引擎失败记因后试下一个
            errors.append(f"{eng.name}: {type(exc).__name__}: {exc}")
            continue
        try:
            _validate_output(result.out_path)
        except RuntimeError as exc:
            errors.append(f"{eng.name}: {exc}")
            continue
        return result
    raise RuntimeError("TTS 合成失败（全部引擎均不可用或产物无效）：" + "; ".join(errors))


async def synthesize_async(text: str, voice: str, out_path: str, *,
                           rate: float = 1.0,
                           limiter: "asyncio.Semaphore | None" = None) -> EngineResult:
    """统一 TTS 入口（异步版）：供多镜头并发场景 asyncio.gather 使用。

    why 进程内 await：edge_tts.Communicate 本身是异步库，旧短剧实现却每镜
    spawn 一个 edge-tts CLI 子进程（慢、难控并发、失败还要静音充数）；本函数
    直接 await 上游保存，并发由调用方传入的 limiter（如 Semaphore(3)）限流。
    失败显式抛错，不做任何静音/提示音兜底。
    """
    import asyncio

    if not (text or "").strip():
        raise ValueError("合成文本为空")
    voice_name = resolve_voice(voice)
    rate_str = f"{_rate_pct_from_multiplier(rate):+d}%"

    async def _save() -> None:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice=voice_name, rate=rate_str)
        await communicate.save(str(out_path))

    if limiter is not None:
        async with limiter:
            await _save()
    else:
        await _save()
    _validate_output(out_path)
    return EngineResult(out_path=str(out_path))
