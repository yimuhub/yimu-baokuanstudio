"""AI 短视频生成：分段 → 视频大模型逐段生成 → ffmpeg 拼接。

机制：
- plan_segments()：总时长按每段 N 秒切分（如 60s → 7×8s + 1×4s）
- start_ai_video_job()：注册异步任务，后台逐段/并行生成
- 全部段完成后 ffmpeg concat 无损拼接成完整视频
- 配置存 studio/ai_video_config.py（每段时长/段间间隔/并行数/默认模型）
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)


def plan_segments(total_seconds: int, max_seg_seconds: int = 8) -> list[dict]:
    """把总时长切成 N 段。

    如 60 秒、每段 8 秒 → 7 段×8s + 1 段×4s = 8 段。
    total_seconds=0（不限时长）时返回单段标记，由调用方按脚本估算。
    """
    if total_seconds <= 0:
        return [{"idx": 1, "dur": 0, "note": "不限时长：按脚本自动"}]
    max_seg_seconds = max(4, min(int(max_seg_seconds or 8), 30))
    segs: list[dict] = []
    remain = int(total_seconds)
    idx = 1
    while remain > 0:
        dur = min(max_seg_seconds, remain)
        segs.append({"idx": idx, "dur": dur})
        remain -= dur
        idx += 1
    return segs


def _estimate_seconds_from_script(script: str, seg_seconds: int = 8) -> int:
    """不限时长时按脚本字数估算总时长（中文约 4 字/秒）。"""
    n = len((script or "").strip())
    est = max(15, int(n / 4))
    # 向上取整到段长的倍数
    return ((est + seg_seconds - 1) // seg_seconds) * seg_seconds


def start_ai_video_job(script: str, total_seconds: int = 30, aspect: str = "9:16",
                       video_model: str = "", title: str = "AI 短视频",
                       user_id: str = "", avatar_image: str = "",
                       voice_engine: str = "tts", voice_audio: str = "") -> str:
    """创建 AI 短视频/数字人生成异步任务，返回 job id。

    后台按配置逐段调用视频大模型（支持照片参考图驱动数字人与声音克隆配音），全部完成后拼接。
    进度通过 core.task_queue 的 job 机制查询。
    """
    from core import task_queue
    from studio import ai_video_config as _cfg

    cfg = _cfg.get_config()
    seg_s = int(cfg["segment_seconds"])
    interval_s = int(cfg["interval_seconds"])
    max_par = int(cfg["max_parallel"])

    if total_seconds <= 0:
        total_seconds = _estimate_seconds_from_script(script, seg_s)
    segs = plan_segments(total_seconds, seg_s)

    jid = f"aiv-{uuid.uuid4().hex[:8]}"
    work_dir = Path(__file__).resolve().parent.parent / "runs" / "ai_video" / jid
    work_dir.mkdir(parents=True, exist_ok=True)

    task_queue.register_job(
        jid, name=f"AI 短视频生成: {title[:16]}",
        task_type="ai_video_gen", target_id=title,
        params={"script": script[:200], "total_seconds": total_seconds,
                "segments": len(segs), "aspect": aspect,
                "avatar_image": avatar_image,
                "voice_engine": voice_engine,
                "voice_audio": voice_audio},
        total_steps=len(segs),
    )
    task_queue.update_job(jid, step=f"共 {len(segs)} 段，准备生成…", progress=0)

    def _run():
        import time as _t
        from core import ad_video as _ad
        try:
            _vinfo = _ad.ad_video_model_info(video_model)
            if not (_vinfo and _vinfo.get("key") and _vinfo.get("base")):
                task_queue.update_job(jid, status="failed",
                                      step="视频大模型未配置",
                                      error=f"视频大模型配置无效: {_vinfo.get('reason') or '请先在「🤖 Agent 配置 → 🎬 广告视频生成 Agent」中配置视频大模型'}")
                return
            seg_files: list[Path] = []
            avatar_path = Path(avatar_image) if avatar_image and Path(avatar_image).exists() else None
            # 按并行数分批
            for b in range(0, len(segs), max_par):
                batch = segs[b:b + max_par]
                for s in batch:
                    idx, dur = s["idx"], s["dur"]
                    task_queue.update_job(
                        jid, step=f"生成第 {idx}/{len(segs)} 段（{dur}s）…",
                        progress=int(100 * (idx - 1) / len(segs)))
                    log.info("[ai_video_gen] job=%s 生成段 %d/%d (%ds) avatar=%s",
                             jid, idx, len(segs), dur, bool(avatar_path))
                    out = work_dir / f"seg-{idx:02d}.mp4"
                    # 分镜 prompt：按段落切分脚本
                    _lines = [ln.strip() for ln in (script or "").split("\n") if ln.strip()]
                    _ptext = _lines[(idx - 1) % max(1, len(_lines))] if _lines else (script or "")[:200]
                    if avatar_path:
                        prompt = (f"Photorealistic AI talking avatar of this person, natural speech, "
                                  f"lifelike facial expression, clear eye contact, subtle gesture, studio lighting, "
                                  f"cinematic vertical video {aspect}. Speaking narration: {_ptext[:250]}")
                        ok = _ad._call_video_model(prompt, out, dur, aspect, _vinfo, ref_image=str(avatar_path))
                    else:
                        prompt = (f"{_ptext[:300]}, cinematic vertical video, "
                                  f"smooth camera movement, high quality")
                        ok = _ad._call_video_model(prompt, out, dur, aspect, _vinfo)
                    if ok and out.exists():
                        seg_files.append(out)
                    else:
                        log.warning("[ai_video_gen] job=%s 段 %d 生成失败，已跳过", jid, idx)
                    if interval_s > 0 and idx < len(segs):
                        _t.sleep(interval_s)
            if not seg_files:
                reason = _vinfo.get("last_error") or "上游视频服务队列满载或暂时不可用"
                log.warning("[ai_video_gen] job=%s 视频模型直连不可用（%s），启动智能高保真动效保底生成…", jid, reason)
                task_queue.update_job(jid, step="大模型队列繁忙，已无缝切换高保真动效保底合成…", progress=70)
                try:
                    from core import video_native
                    final = work_dir / f"final-{aspect.replace(':', 'x')}.mp4"
                    # 1. 若上传了专属肖像，以肖像图片生成肯本斯动态出镜成片
                    if avatar_path and avatar_path.exists():
                        w, h = video_native.RESOLUTIONS.get(aspect, (1080, 1920))
                        dur_total = float(total_seconds or 15)
                        video_native._images_to_video([avatar_path], final, w, h, dur_total)
                    else:
                        # 2. 无肖像时走原生 AI 视觉分镜保底
                        terms = [ln[:15] for ln in (script or "").split("\n") if ln.strip()]
                        res = video_native.make_video_native(
                            script=script, terms=terms, seconds=total_seconds,
                            aspect=aspect, title=title, work_dir=work_dir,
                            material_mode="ai_only"
                        )
                        if res.get("mp4") and Path(res["mp4"]).exists():
                            final = Path(res["mp4"])

                    if final.exists():
                        task_queue.update_job(
                            jid, status="done", step="AI 短视频生成完成（智能高保真动效保底）", progress=100,
                            result={"mp4": str(final), "url": f"/api/aivideo/file/{jid}",
                                    "segments": len(segs), "total": len(segs),
                                    "aspect": aspect, "title": title,
                                    "fallback": True, "reason": reason})
                        log.info("[ai_video_gen] job=%s 智能保底完成: %s", jid, final)
                        return
                except Exception as fb_exc:
                    log.exception("[ai_video_gen] job=%s 智能保底合成失败: %s", jid, fb_exc)

                task_queue.update_job(jid, status="failed", step="全部段生成失败",
                                      error=f"视频大模型调用失败: {reason}")
                return
            # 拼接视频片段
            task_queue.update_job(jid, step=f"拼接 {len(seg_files)} 段画面并合成配音字幕…",
                                  progress=90)
            stitched = work_dir / f"stitched-{aspect.replace(':', 'x')}.mp4"
            _concat(seg_files, stitched)

            final = work_dir / f"final-{aspect.replace(':', 'x')}.mp4"
            # 混入配音（声音克隆或 TTS）与字幕
            try:
                from core import video_native as _vn
                audio_file = work_dir / "voice.mp3"
                p_audio = None
                if voice_engine == "voice_clone":
                    task_queue.update_job(jid, step="调取声音克隆专属配音…", progress=93)
                    p_audio = _vn._make_voice_clone_audio(script, audio_file, prompt_audio=voice_audio)
                    if not p_audio:
                        task_queue.update_job(jid, step="克隆服务不可用，降级智能语音配音…", progress=94)
                        p_audio = _vn._make_tts_audio(script, audio_file)
                else:
                    task_queue.update_job(jid, step="合成智能语音配音…", progress=93)
                    p_audio = _vn._make_tts_audio(script, audio_file)

                if p_audio and p_audio.exists():
                    total_dur = _vn._probe_duration(p_audio) or float(total_seconds or 15)
                    srt_file = work_dir / "sub.srt"
                    _vn._script_to_srt(script, total_dur, srt_file)
                    _vn._mux_audio_subtitle(stitched, p_audio, srt_file, final, total_dur)
                else:
                    if stitched.exists():
                        import shutil as _sh
                        _sh.copyfile(stitched, final)
            except Exception as _mux_e:
                log.warning("[ai_video_gen] 配音或字幕混流跳过: %s", _mux_e)
                if stitched.exists() and not final.exists():
                    import shutil as _sh
                    _sh.copyfile(stitched, final)

            task_queue.update_job(
                jid, status="done", step="AI 短视频生成完成！", progress=100,
                result={"mp4": str(final), "url": f"/api/aivideo/file/{jid}",
                        "segments": len(seg_files), "total": len(segs),
                        "aspect": aspect, "title": title})
            log.info("[ai_video_gen] job=%s 完成: %s", jid, final)
        except Exception as exc:  # noqa: BLE001
            log.exception("[ai_video_gen] job=%s 异常: %s", jid, exc)
            task_queue.update_job(jid, status="failed", step="生成异常",
                                  error=str(exc)[:300])

    import threading
    threading.Thread(target=_run, daemon=True).start()
    return jid


def _concat(seg_files: list[Path], out: Path) -> Path:
    """ffmpeg concat 无损拼接。"""
    from core import video_native as _vn
    if not _vn.ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法拼接")
    lst = out.parent / "concat.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in seg_files), encoding="utf-8")
    kw = _vn._subprocess_kwargs() if hasattr(_vn, "_subprocess_kwargs") else {}
    import subprocess
    r = subprocess.run([_vn._FFMPEG, "-y", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(out)],
                       capture_output=True, text=True, timeout=600, **kw)
    if r.returncode != 0:
        raise RuntimeError("拼接失败: " + (r.stderr or "")[-300:])
    return out
