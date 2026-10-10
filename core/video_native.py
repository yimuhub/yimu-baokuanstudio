"""V7 原生视频合成引擎。

链路：口播文案 → TTS 配音 → 免费素材/AI 图片/文字卡 → ffmpeg 合成 MP4。

画面素材优先级：
  1. Pexels / Pixabay 免费视频（studio.stock，按关键词搜索下载）
  2. AI 生成图片（core.imagegen.gen_image）
  3. Pillow 纯文字标题卡（保底，永远可用）

合成策略：
  - 有视频素材：ffmpeg concat 拼接 → 混配音 → 烧字幕
  - 只有图片：zoompan 肯本斯特效轮播 → 混配音 → 烧字幕
  - 无音频：输出无声视频（不抛异常）
  - 无素材：纯文字卡视频（不抛异常）

只依赖：标准库 + pillow + 系统 ffmpeg（8.x 已验证）。
"""
import logging
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

# 画幅 → 分辨率
RESOLUTIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")

# imageio-ffmpeg 内置各平台二进制：系统没装 ffmpeg 时自动兜底，用户零操作
if not _FFMPEG:
    try:
        import imageio_ffmpeg
        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        log.info("[video_native] 系统 ffmpeg 未找到，已启用内置 ffmpeg: %s", _FFMPEG)
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] imageio-ffmpeg 不可用: %s", exc)


def ffmpeg_install_hint() -> str:
    """按操作系统返回 ffmpeg 安装指引（跨平台：macOS/Windows/Linux）。"""
    sys = platform.system()
    if sys == "Darwin":
        return "Mac 请执行 `brew install ffmpeg`"
    if sys == "Windows":
        return "Windows 请执行 `winget install ffmpeg`，或去 https://www.gyan.dev/ffmpeg/builds/ 下载并加入 PATH"
    return "Linux 请执行 `sudo apt install ffmpeg`"


def _subprocess_kwargs() -> dict:
    """跨平台 subprocess 参数：Windows 下不弹黑窗口。"""
    if platform.system() == "Windows":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def ffmpeg_available() -> bool:
    """ffmpeg 是否可用。"""
    return bool(_FFMPEG)


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """跑 ffmpeg，失败抛 RuntimeError（带 stderr 尾部）。跨平台：Windows 不弹黑窗口。"""
    log.info("[video_native] ffmpeg: %s", " ".join(cmd[:6]) + " ...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       **_subprocess_kwargs())
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 失败: " + (r.stderr or "")[-500:])
    return r


def _probe_duration(path: Path) -> float:
    """读媒体时长（秒）。优先使用 ffprobe，不存在时降级使用 ffmpeg -i 解析。失败返回 0。"""
    if _FFPROBE:
        try:
            r = subprocess.run(
                [_FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=30,
                **_subprocess_kwargs())
            val = float(r.stdout.strip() or 0)
            if val > 0:
                return val
        except Exception:  # noqa: BLE001
            pass

    if _FFMPEG:
        try:
            r = subprocess.run(
                [_FFMPEG, "-i", str(path)],
                capture_output=True, text=True, timeout=30,
                **_subprocess_kwargs())
            # 输出例如: Duration: 00:00:03.00, start: 0.000000, bitrate: 123 kb/s
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
            if m:
                hours, minutes, seconds = m.groups()
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception:  # noqa: BLE001
            pass
    return 0.0


# ------------------------------------------------------------------ TTS ---

def _make_voice_clone_audio(script: str, out_mp3: Path,
                            prompt_audio: str | None = None,
                            voice_id: str | None = None) -> Path | None:
    """声音克隆 API 配音（支持 CosyVoice / MiniMax / ElevenLabs / 通用兼容端点）。

    从视频合成配置读 voice_clone_api_url / voice_clone_api_key / voice_clone_provider / voice_clone_model，
    组装对应供应商请求格式。成功写回 out_mp3，失败返回 None（上层优雅降级 TTS）。
    """
    try:
        from studio import video_config as _vc
        cfg = _vc.get_config()
        api_url = (cfg.get("voice_clone_api_url") or "").strip().rstrip("/")
        api_key = (cfg.get("voice_clone_api_key") or "").strip()
        provider = (cfg.get("voice_clone_provider") or "custom").lower()
        model = (cfg.get("voice_clone_model") or "").strip()
        default_voice = (cfg.get("voice_clone_voice_id") or "").strip()
        ref_audio = prompt_audio or (cfg.get("voice_clone_prompt_audio") or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] 读声音克隆配置失败: %s", exc)
        return None

    if not api_url:
        log.warning("[video_native] 未配置 voice_clone_api_url，降级 TTS")
        return None

    import json as _json
    import base64 as _b64
    import httpx

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    chosen_voice = voice_id or default_voice or "default"
    if provider == "minimax":
        body = {
            "model": model or "speech-01-turbo",
            "text": script,
            "voice_setting": {"voice_id": chosen_voice},
            "audio_setting": {"sample_rate": 24000, "format": "mp3"}
        }
    elif provider == "elevenlabs":
        body = {
            "text": script,
            "model_id": model or "eleven_multilingual_v2",
        }
    elif provider == "cosyvoice":
        body = {
            "model": model or "cosyvoice-v1",
            "input": script,
            "voice": chosen_voice,
        }
        if ref_audio:
            body["prompt_audio"] = ref_audio
    else:
        body = {
            "text": script,
            "input": script,
            "model": model,
            "voice": chosen_voice,
        }
        if ref_audio:
            body["prompt_audio"] = ref_audio
            body["ref_audio"] = ref_audio

    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            resp = client.post(api_url, json=body, headers=headers)
            if resp.status_code != 200:
                log.warning("[video_native] 声音克隆 API 返回 HTTP %s: %s", resp.status_code, resp.text[:200])
                return None

            content_type = resp.headers.get("content-type", "").lower()
            data = resp.content
            if "application/json" in content_type or data.startswith(b"{"):
                try:
                    jd = resp.json()
                    b64_str = (jd.get("audio") or jd.get("audio_content")
                               or (jd.get("data") or {}).get("audio")
                               or ((jd.get("data") or [{}])[0] if isinstance(jd.get("data"), list) else {}).get("b64_json"))
                    audio_url = jd.get("url") or (jd.get("data") or {}).get("url")
                    if b64_str:
                        data = _b64.b64decode(b64_str)
                    elif audio_url:
                        dl = client.get(audio_url, timeout=60)
                        if dl.status_code == 200:
                            data = dl.content
                except Exception as parse_e:
                    log.warning("[video_native] 声音克隆响应解析失败: %s", parse_e)

            if len(data) < 1000:
                log.warning("[video_native] 声音克隆返回音频过小（%d 字节），降级 TTS", len(data))
                return None

            out_mp3.parent.mkdir(parents=True, exist_ok=True)
            out_mp3.write_bytes(data)
            log.info("[video_native] 声音克隆配音成功: %s (%d KB)", out_mp3.name, len(data) // 1024)
            return out_mp3
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] 声音克隆 API 调用失败（%s），降级 TTS", exc)
        return None


def _make_tts_audio(script: str, out_mp3: Path, voice: str = "zh-CN-XiaoxiaoNeural",
                    voice_engine: str | None = None) -> Path | None:
    """配音。voice_engine: tts（默认，A 三引擎链）/ voice_clone / local_model。

    - voice_clone：调配置的声音克隆 API，失败降级 tts
    - local_model：暂未实现，直接降级 tts（打日志明示）
    """
    # ① 声音克隆
    if voice_engine == "voice_clone":
        p = _make_voice_clone_audio(script, out_mp3)
        if p:
            return p
        log.warning("[video_native] 声音克隆不可用，已降级 TTS")
    elif voice_engine == "local_model":
        log.warning("[video_native] 本地声音模型暂未实现，已降级 TTS")
    # ② A 链（studio.tts.synthesize）
    try:
        from studio.tts import synthesize  # 延迟导入防循环
        a_voice = voice.split("-")[-1].replace("Neural", "").lower() or "xiaoxiao"
        produced = synthesize(script, str(out_mp3), "sqlite:///:memory:",
                              voice=a_voice, rate=0)
        p = Path(produced)
        if p.exists() and p.stat().st_size > 1000:
            log.info("[video_native] TTS 成功（A 链）: %s", p)
            return p
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] A 链 TTS 失败（%s），降级 edge-tts 直连", exc)

    # ② edge-tts 直连
    try:
        import asyncio
        import edge_tts
        asyncio.run(_edge_tts_save(script, voice, out_mp3))
        if out_mp3.exists() and out_mp3.stat().st_size > 1000:
            log.info("[video_native] TTS 成功（edge-tts 直连）: %s", out_mp3)
            return out_mp3
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] edge-tts 直连失败（%s），输出无声视频", exc)
    return None


async def _edge_tts_save(text: str, voice: str, out: Path):
    import edge_tts
    await edge_tts.Communicate(text, voice).save(str(out))


# ------------------------------------------------------------------ 素材 ---

def _gather_videos(terms: list[str], n: int, aspect: str) -> list[Path]:
    """从免费素材站搜视频。无 key / 失败返回 []。"""
    try:
        from studio import stock
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] stock 模块不可用: %s", exc)
        return []
    orientation = "portrait" if aspect == "9:16" else "landscape"
    paths: list[Path] = []
    for kw in (terms or ["cinematic"]):
        if len(paths) >= n:
            break
        try:
            got = stock.search_videos(kw, n=n - len(paths), orientation=orientation)
            paths.extend(got)
        except Exception as exc:  # noqa: BLE001
            log.warning("[video_native] 素材搜索失败 [%s]: %s", kw, exc)
    return paths[:n]


def _gather_ai_images(title: str, script: str, n: int, out_dir: Path,
                      w: int, h: int, emit=None) -> list[Path]:
    """AI 生成配图。失败返回已成功部分（可为 []）。"""
    emit = emit or (lambda *_: None)
    try:
        from core import imagegen
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] imagegen 不可用: %s", exc)
        return []
    paths: list[Path] = []
    size = f"{w}x{h}"
    for i in range(n):
        p = out_dir / f"ai-scene-{i}.jpg"
        try:
            prompt = f"{title}，{script[i*60:(i+1)*60]}" if script else title
            ok = imagegen.gen_image(prompt, p, size=size,
                                    context_title=title, angle_idx=i)
            if ok and p.exists():
                paths.append(p)
                emit(f"AI 配图 {i+1}/{n} 完成…")
        except Exception as exc:  # noqa: BLE001
            log.warning("[video_native] AI 图片 %d 失败: %s", i, exc)
    return paths


def _make_title_card(title: str, subtitle: str, out_path: Path,
                     w: int, h: int, bg=(18, 18, 28)) -> Path:
    """Pillow 纯文字标题卡（保底，永远可用）。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    # 顶部装饰条
    d.rectangle([0, 0, w, 12], fill=(240, 136, 62))  # YIMU 橙
    # 标题（自动换行，居中偏上）
    import textwrap
    lines = textwrap.wrap(title, width=14 if w < h else 28)
    y = h // 3
    for ln in lines[:4]:
        # 简单居中：按字符数估算
        d.text((w // 2, y), ln, fill=(255, 255, 255), anchor="mm",
               font=None)  # 默认字体（无外部字体依赖）
        y += 90 if w < h else 70
    if subtitle:
        d.text((w // 2, y + 40), subtitle[:40], fill=(180, 180, 180),
               anchor="mm", font=None)
    # 底部品牌
    d.text((w // 2, h - 80), "一幕 · YIMU", fill=(240, 136, 62),
           anchor="mm", font=None)
    img.save(out_path, "JPEG", quality=88)
    return out_path


# ------------------------------------------------------------------ 字幕 ---

def _script_to_srt(script: str, total_s: float, srt_path: Path) -> Path:
    """按标点分句，均匀分配时长，生成 SRT。"""
    sents = [s.strip() for s in re.split(r"[。！？!?；;…\n]+", script) if s.strip()]
    if not sents:
        sents = [script[:60] or "一幕 YIMU"]
    per = max(1.0, total_s / len(sents))

    def _ts(sec: float) -> str:
        ms = int(sec * 1000)
        return f"{ms//3600000:02d}:{(ms//60000)%60:02d}:{(ms//1000)%60:02d},{ms%1000:03d}"

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, s in enumerate(sents):
            st, en = i * per, min((i + 1) * per, total_s)
            f.write(f"{i+1}\n{_ts(st)} --> {_ts(en)}\n{s[:60]}\n\n")
    return srt_path


# ------------------------------------------------------------------ 合成 ---

def _concat_videos(videos: list[Path], out: Path, w: int, h: int) -> Path:
    """多视频素材：统一分辨率后 concat 拼接。"""
    lst = out.parent / "concat.txt"
    # 先逐个转码为统一规格的中间文件
    segs = []
    for i, v in enumerate(videos):
        seg = out.parent / f"seg-{i}.mp4"
        _run([_FFMPEG, "-y", "-i", str(v),
              "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                     f"crop={w}:{h},setsar=1,fps=30",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
              "-an", str(seg)])
        segs.append(seg)
    lst.write_text("\n".join(f"file '{s}'" for s in segs), encoding="utf-8")
    _run([_FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c", "copy", str(out)])
    return out


def _interleave_ref_images(images: list[Path], ref_paths: list[Path],
                           person_path: Path | None = None) -> list[Path]:
    """参考图全片穿插：产品图插在 1/4、1/2、3/4 处，人物图放结尾 CTA 段。

    用于 AI 广告深度创作：产品/人物在全片保持出现，不止开场 3 秒。
    """
    if not ref_paths and not person_path:
        return images
    if not images:
        return list(ref_paths) + ([person_path] if person_path else [])
    out = list(images)
    n = len(out)
    # 从后往前插，避免索引偏移；去重点位
    positions = sorted({n // 4, n // 2, (3 * n) // 4}, reverse=True)
    for i, pos in enumerate(positions):
        if i < len(ref_paths):
            out.insert(min(pos, len(out)), ref_paths[i % len(ref_paths)])
    if person_path:
        out.append(person_path)
    return out


def _images_to_video(images: list[Path], out: Path, w: int, h: int,
                     total_s: float) -> Path:
    """图片轮播：每张 zoompan 肯本斯 2.5s~4s，拼成总时长。"""
    if not images:
        raise RuntimeError("无图片素材")
    per = max(2.5, total_s / len(images))
    frames = int(per * 30)
    segs = []
    for i, img in enumerate(images):
        seg = out.parent / f"imgseg-{i}.mp4"
        # zoompan：从 1.0 缓慢推到 1.12，制造运镜感
        _run([_FFMPEG, "-y", "-loop", "1", "-i", str(img),
              "-vf", f"scale={w*2}:{h*2},zoompan=z='min(zoom+0.0012,1.15)':"
                     f"d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                     f"s={w}x{h},fps=30",
              "-t", f"{per:.2f}", "-c:v", "libx264", "-preset", "veryfast",
              "-crf", "23", str(seg)])
        segs.append(seg)
    lst = out.parent / "imgconcat.txt"
    lst.write_text("\n".join(f"file '{s}'" for s in segs), encoding="utf-8")
    _run([_FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c", "copy", str(out)])
    return out


def _mux_audio_subtitle(video: Path, audio: Path | None, srt: Path | None,
                        out: Path, total_s: float) -> Path:
    """混配音 + 烧字幕，输出最终 MP4。"""
    cmd = [_FFMPEG, "-y", "-i", str(video)]
    if audio and audio.exists():
        cmd += ["-i", str(audio)]
    # 字幕烧录（需要字幕文件存在）
    vf = None
    if srt and srt.exists():
        # 转义字幕路径中的特殊字符
        sp = str(srt).replace("'", r"'\''").replace(":", r"\:")
        vf = (f"subtitles='{sp}':force_style="
              "'FontSize=22,PrimaryColour=&HFFFFFF&,OutlineColour=&H80000000&,"
              "BorderStyle=1,Outline=2,MarginV=60'")
    if vf:
        cmd += ["-vf", vf]
    if audio and audio.exists():
        # 音频长度决定总时长；-shortest 以最短流为准
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest", str(out)]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-t", f"{total_s:.1f}", str(out)]
    _run(cmd, timeout=900)
    return out


# ------------------------------------------------------------------ 主入口 ---

def make_video_native(script: str, terms: list[str] | None = None,
                      seconds: int = 15, aspect: str = "9:16",
                      voice: str = "zh-CN-XiaoxiaoNeural",
                      title: str = "一幕 YIMU",
                      work_dir: Path | None = None,
                      emit=None,
                      subtitle_enabled: bool | None = None,
                      voice_engine: str | None = None,
                      material_mode: str | None = None,
                      custom_audio: str | Path | None = None,
                      cover_images: list | None = None,
                      person_ref_image: str | Path | None = None) -> dict:
    """V7 原生视频合成主入口。

    Args:
        script: 口播文案（纯文本）
        terms: 素材检索英文关键词
        seconds: 目标时长（秒）
        aspect: "9:16" 或 "16:9"
        voice: TTS 音色
        title: 标题（用于标题卡/AI 图片）
        work_dir: 工作目录（默认 runs/videos/native-{ts}/）
        emit: 进度回调
        subtitle_enabled: 字幕开关；None 时读视频合成配置
        voice_engine: 声音引擎 tts/voice_clone/local_model；None 时读视频合成配置
        material_mode: 素材模式 stock_only/ai_only/mixed；None 时读视频合成配置
        custom_audio: 用户上传的配音文件路径；传了则跳过 TTS 直接使用
        cover_images: 产品参考图路径列表；开场 + 全片 1/4、1/2、3/4 处穿插
        person_ref_image: 卖货人员参考图；放在 CTA 结尾段

    Returns:
        {"mp4": 路径, "duration_s": 时长, "has_audio": bool,
         "material": "stock_video"|"ai_image"|"title_card"|"ref_image", ...}

    Raises:
        RuntimeError: ffmpeg 不可用时
    """
    emit = emit or (lambda *_: None)
    if not ffmpeg_available():
        raise RuntimeError(
            f"系统未安装 ffmpeg：{ffmpeg_install_hint()}后重试")

    # 读视频合成配置（显式传参优先）
    try:
        from studio import video_config as _vc
        if subtitle_enabled is None:
            subtitle_enabled = _vc.get_subtitle_enabled()
        if voice_engine is None:
            voice_engine = _vc.get_voice_engine()
        if material_mode is None:
            material_mode = _vc.get_material_mode()
    except Exception:  # noqa: BLE001
        if subtitle_enabled is None:
            subtitle_enabled = True
        if voice_engine is None:
            voice_engine = "tts"
        if material_mode is None:
            material_mode = "mixed"
    if material_mode not in ("stock_only", "ai_only", "mixed"):
        log.warning("[video_native] material_mode 非法（%s），回退 mixed", material_mode)
        material_mode = "mixed"

    aspect = aspect if aspect in RESOLUTIONS else "9:16"
    w, h = RESOLUTIONS[aspect]
    terms = terms or ["cinematic", "lifestyle"]

    ts = int(time.time())
    work_dir = Path(work_dir) if work_dir else (
        Path(__file__).resolve().parent.parent / "runs" / "videos" / f"native-{ts}")
    work_dir.mkdir(parents=True, exist_ok=True)

    # ① 配音（用户上传音频优先，其次 TTS）
    emit("合成配音…")
    audio = None
    if custom_audio:
        _ca = Path(custom_audio)
        if _ca.exists() and _ca.stat().st_size > 1000:
            audio = _ca
            emit("使用上传的配音音频…")
            log.info("[video_native] 使用用户上传音频: %s", _ca)
        else:
            log.warning("[video_native] 上传音频无效（%s），降级 TTS", custom_audio)
    if audio is None:
        audio_path = work_dir / "voice.mp3"
        audio = _make_tts_audio(script, audio_path, voice, voice_engine=voice_engine)
    if audio:
        total_s = _probe_duration(audio) or float(seconds or 15)
        # seconds=0（不限时长）：按配音实际时长完整合成，不截断
        if seconds and seconds > 0:
            total_s = min(max(total_s, 5.0), 180.0)
        else:
            total_s = max(total_s, 5.0)
    else:
        total_s = float(max(5, min(seconds or 15, 120)))
        emit("配音失败，输出无声视频…")

    # ② 画面素材（按素材模式）
    emit("准备画面素材…")
    material = "title_card"
    video_base = work_dir / "base.mp4"

    # 参考图（产品图/人物图）：校验有效性，转为 Path 列表
    _ref_paths: list[Path] = []
    for _rp in (cover_images or []):
        _p = Path(_rp)
        if _p.exists() and _p.stat().st_size > 1000:
            _ref_paths.append(_p)
        else:
            log.warning("[video_native] 参考图无效已跳过: %s", _rp)
    _person_path: Path | None = None
    if person_ref_image:
        _pp = Path(person_ref_image)
        if _pp.exists() and _pp.stat().st_size > 1000:
            _person_path = _pp
        else:
            log.warning("[video_native] 人物参考图无效已跳过: %s", person_ref_image)
    if _ref_paths:
        log.info("[video_native] 产品参考图 %d 张，将全片多点位穿插", len(_ref_paths))
    if _person_path:
        log.info("[video_native] 人物参考图 1 张，将放在 CTA 结尾段")

    def _build_title_cards() -> list:
        """终极保底：文字标题卡（永远可用）。"""
        cards = []
        for i in range(3):
            cp = work_dir / f"card-{i}.jpg"
            _make_title_card(title if i == 0 else f"{title} · {i+1}",
                             script[:40], cp, w, h)
            cards.append(cp)
        return cards

    def _build_ai_images() -> list:
        return _gather_ai_images(title, script, n=4, out_dir=work_dir,
                                 w=w, h=h, emit=emit)

    if material_mode == "stock_only":
        # 只用在线素材：搜不到直接报错，提示配 Key 或换模式
        stock_videos = _gather_videos(terms, n=3, aspect=aspect)
        if not stock_videos:
            raise RuntimeError(
                "在线素材搜索为空：请在「控制中心 → 🎬 视频合成配置」中填写 "
                "Pexels / Pixabay Key，或把素材模式切换为「混合 / 仅 AI 生成」")
        emit(f"免费素材视频 {len(stock_videos)} 段…")
        log.info("[video_native] 素材模式=stock_only：使用在线素材视频 %d 段",
                 len(stock_videos))
        _concat_videos(stock_videos, video_base, w, h)
        material = "stock_video"
    elif material_mode == "ai_only":
        # 只用 AI 生成图片（参考图全片穿插，保证产品/人物一致性）
        ai_images = _build_ai_images()
        if ai_images:
            ai_images = _interleave_ref_images(ai_images, _ref_paths, _person_path)
            emit(f"AI 配图 {len(ai_images)} 张（含参考图穿插），合成轮播…")
            log.info("[video_native] 素材模式=ai_only：使用 AI 生成图片 %d 张"
                     "（含参考图穿插）", len(ai_images))
            _images_to_video(ai_images, video_base, w, h, total_s)
            material = "ai_image"
        else:
            emit("AI 配图失败，改用文字标题卡…")
            log.warning("[video_native] 素材模式=ai_only：AI 图片生成失败，"
                        "降级文字标题卡")
            _images_to_video(_build_title_cards(), video_base, w, h, total_s)
            material = "title_card"
    else:
        # mixed（默认）：三级兜底 —— 免费视频优先 → AI 图片补足 → AI 视频片段
        # 优先免费平台视频（要多少拿多少），不足部分 AI 图片补，再不足 AI 视频模型生成片段补
        stock_videos = _gather_videos(terms, n=4, aspect=aspect)
        n_stock = len(stock_videos)
        ai_images = []
        ai_video_segs = []
        if n_stock < 2:
            # 第二级：AI 图片补足
            ai_images = _build_ai_images()
        # 第三级：AI 视频模型生成片段（如果视频模型可用且仍缺画面）
        need_video = n_stock == 0 and not ai_images
        if need_video:
            try:
                from core import ad_video as _ad
                _vinfo = _ad.ad_video_model_info()
                if _vinfo and _vinfo.get("key"):
                    emit("视频模型生成画面片段…")
                    _vseg = work_dir / "ai-video-seg.mp4"
                    _vprompt = f"{title}，{script[:120]}，cinematic product video"
                    if _ad._call_video_model(_vprompt, _vseg, 8, aspect, _vinfo):
                        ai_video_segs.append(_vseg)
                        log.info("[video_native] mixed 第三级：AI 视频模型生成 1 段")
            except Exception as _ve:  # noqa: BLE001
                log.warning("[video_native] mixed 第三级 AI 视频生成失败: %s", _ve)
        if n_stock >= 2:
            emit(f"免费素材视频 {n_stock} 段…")
            log.info("[video_native] 素材模式=mixed L1：免费视频 %d 段", n_stock)
            _concat_videos(stock_videos, video_base, w, h)
            material = "stock_video"
        elif ai_images:
            ai_images = _interleave_ref_images(ai_images, _ref_paths, _person_path)
            emit(f"AI 配图 {len(ai_images)} 张（含参考图穿插），合成轮播…")
            log.info("[video_native] 素材模式=mixed L2：免费视频 %d 段不足，AI 图片 %d 张补足",
                     n_stock, len(ai_images))
            _images_to_video(ai_images, video_base, w, h, total_s)
            material = "ai_image"
        elif ai_video_segs:
            emit("AI 视频片段合成…")
            log.info("[video_native] 素材模式=mixed L3：使用 AI 视频模型片段")
            _concat_videos(ai_video_segs, video_base, w, h)
            material = "ai_video_seg"
        else:
            emit("生成文字标题卡…")
            log.warning("[video_native] 素材模式=mixed：三级均不可用，降级文字标题卡")
            _images_to_video(_build_title_cards(), video_base, w, h, total_s)
            material = "title_card"

    # ②b 参考图开场：如果有参考图，在成片开头加 3 秒开场画面
    if _ref_paths:
        try:
            emit("合成参考图开场画面…")
            intro_clip = work_dir / "intro.mp4"
            # 参考图轮播 3 秒作为开场（Hook 视觉）
            _images_to_video(_ref_paths, intro_clip, w, h, 3.0)
            # 把开场拼到正片前面
            merged = work_dir / "base_with_intro.mp4"
            lst = work_dir / "intro_concat.txt"
            lst.write_text(
                f"file '{intro_clip}'\nfile '{video_base}'", encoding="utf-8")
            _run([_FFMPEG, "-y", "-f", "concat", "-safe", "0",
                  "-i", str(lst), "-c", "copy", str(merged)])
            video_base = merged
            material = "ref_image"
            log.info("[video_native] 已拼接参考图开场（3秒）")
        except Exception as exc:  # noqa: BLE001
            log.warning("[video_native] 参考图开场合成失败，已跳过: %s", exc)

    # ③ 字幕（可按配置关闭）
    srt = None
    if subtitle_enabled:
        srt = _script_to_srt(script, total_s, work_dir / "sub.srt")
    else:
        emit("字幕已关闭，跳过字幕烧录…")

    # ④ 混流输出
    emit("ffmpeg 合成最终成片…")
    final = work_dir / f"final-{aspect.replace(':', 'x')}.mp4"
    _mux_audio_subtitle(video_base, audio, srt, final, total_s)

    dur = _probe_duration(final) or total_s
    size_kb = final.stat().st_size // 1024 if final.exists() else 0
    log.info("[video_native] 完成: %s (%.1fs, %dKB, 素材=%s)",
             final, dur, size_kb, material)
    emit("完成")
    return {
        "mp4": str(final),
        "duration_s": round(dur, 1),
        "has_audio": bool(audio),
        "material": material,
        "material_mode": material_mode,
        "aspect": aspect,
        "size_kb": size_kb,
        "work_dir": str(work_dir),
    }
