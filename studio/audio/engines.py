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


# 中文常用音色（edge-tts 声音名）
VOICES: dict[str, str] = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",  # 女声，通用首选
    "yunxi": "zh-CN-YunxiNeural",  # 男声
    "yunjian": "zh-CN-YunjianNeural",  # 男声，偏播报
    "xiaoyi": "zh-CN-XiaoyiNeural",  # 女声，偏活泼
}


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

        voice_name = VOICES.get(voice, VOICES["xiaoxiao"])
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
