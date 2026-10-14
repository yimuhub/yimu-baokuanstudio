"""音频管线：草稿 → 口播稿 → TTS 音频（edge-tts，微软免费音色）。"""
from __future__ import annotations
import logging
import re
from pathlib import Path

from core import db
from core.platforms import get_pack

log = logging.getLogger(__name__)

SCRIPT_TARGET = {15: "70~90", 30: "140~170", 60: "280~330"}


def _tts_engine_via_a(script: str, out_path: str, voice_cfg: dict) -> dict | None:
    """尝试 A 的 TTS 三引擎链（studio.tts.synthesize，Edge-TTS/云端/本地 WAV 兜底）。

    成功返回 {"out_path": 实际产物路径, "engine": "studio.tts"}；
    任何异常返回 None，由调用方降级回 B 原有 _tts。⭐ 绝不静默吞错：每次失败都打日志。
    """
    try:
        from studio.tts import synthesize  # 延迟导入：避免循环导入
    except Exception as exc:  # noqa: BLE001
        log.warning("[TTS] A 语音链不可用（导入失败 %s: %s），降级为 B 内置 TTS",
                    type(exc).__name__, exc)
        return None
    # B 的 voice 如 zh-CN-XiaoxiaoNeural → A 的 voice 键 xiaoxiao（未知键由 A 引擎内部兜底）
    b_voice = str(voice_cfg.get("voice", ""))
    a_voice = b_voice.split("-")[-1].replace("Neural", "").lower() or "xiaoxiao"
    try:
        rate = float(voice_cfg.get("rate", 1.0) or 1.0)
    except (TypeError, ValueError):
        rate = 1.0
    a_rate = max(-50, min(50, int(round((rate - 1.0) * 100))))  # B 倍率 → A 百分比
    try:
        # db_url 仅用于 A 内部生产库隔离校验；TTS 本身不读写库，传 :memory: 如实声明
        produced = synthesize(script, out_path, "sqlite:///:memory:",
                              voice=a_voice, rate=a_rate)
    except Exception as exc:  # noqa: BLE001
        log.warning("[TTS] A 语音链合成失败（%s: %s），降级为 B 内置 TTS",
                    type(exc).__name__, exc)
        return None
    return {"out_path": produced, "engine": "studio.tts"}


async def _tts(text: str, voice: str, rate: str, out_mp3: Path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=f"+{int(float(rate)*100)}%" if rate else "")
    await communicate.save(str(out_mp3))


def make_audio(draft_id: str, seconds: int = 30, platform: str = "xhs",
               subject: str = "", emit=None, custom_script: str = "") -> dict:
    emit = emit or (lambda *_: None)
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError("草稿不存在")
    seconds = seconds if seconds in (15, 30, 60) else 30
    subject = (subject or d["title"]).strip()[:40]
    pack = get_pack(platform)
    voice_cfg = pack["audio"]

    if custom_script and custom_script.strip():
        script = custom_script.strip()
        emit(f"使用当前工作台编辑的专属口播稿（共 {len(script)} 字）…")
    else:
        emit(f"AI 压缩 {seconds} 秒口播稿…")
        from core import agents
        raw = agents.chat_for("write", [
            {"role": "user", "content":
                f"把下面文章压缩成 {seconds} 秒音频口播稿（{SCRIPT_TARGET.get(seconds, '140~170')}字，"
                "纯口播文本，口语化，有钩子，禁止任何markdown/标题/说明）。\n"
                f"【标题】{d['title']}\n【正文】{d['body_md'][:3000]}"}],
            temperature=0.7)
        lines = [l for l in raw.strip().splitlines() if l.strip()]
        script = lines[0] if lines else raw[:200]
        script = re.sub(r"\**", "", script).strip()
        if len(script) < 20:
            raise RuntimeError("口播稿生成失败：" + raw[:150])

    emit(f"TTS 合成音频（{voice_cfg['voice']}）…")
    ddir = db.draft_dir(draft_id)
    out = ddir / f"audio-{seconds}s-{platform}.mp3"
    # ⭐ 先走 A 的 TTS 三引擎链；成功则用其产物
    a_hit = _tts_engine_via_a(script, str(out), voice_cfg)
    if a_hit is not None:
        produced = Path(a_hit["out_path"])
        emit(f"A 语音链合成成功（{produced.name}）…")
        return {"file": produced.name, "url": f"/audio/{draft_id}/{produced.name}",
                "script": script, "platform": platform, "voice": voice_cfg["voice"],
                "tts_engine": a_hit["engine"], "degraded": False}
    # ⭐ 降级：A 链不可用/失败 → 回 B 原有 _tts；原因已在 _tts_engine_via_a 打日志，此处再记一次
    degrade_reason = "A TTS 三引擎链不可用或合成失败（详见服务端日志），已降级为 B 内置 edge-tts 直连"
    log.warning("[TTS] %s", degrade_reason)
    emit("语音链降级：使用内置 TTS（原因已记录日志）…")
    import asyncio
    asyncio.run(_tts(script, voice_cfg["voice"], voice_cfg["rate"], out))
    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError("TTS 合成失败")
    return {"file": out.name, "url": f"/audio/{draft_id}/{out.name}",
            "script": script, "platform": platform, "voice": voice_cfg["voice"],
            "tts_engine": "builtin", "degraded": True, "degrade_reason": degrade_reason}
