"""一幕原生视频合成引擎。

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
from __future__ import annotations
import logging
import platform
import re
import shutil
import subprocess
import threading
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


# ---------------------------------------------------------------------------
# 取消联动（v15.9.8）：ffmpeg 从「subprocess.run 一跑到底」改为 Popen +
# 0.5s 轮询 wait。为什么：一条短剧渲染可能跑十几分钟，用户在任务面板点
# 「取消」后 ffmpeg 仍会把整条视频渲完——既浪费 CPU 也让取消按钮形同虚设。
# Task.cancel() 在请求线程触发，ffmpeg 跑在任务工作线程，跨线程要拿到进程
# 句柄才能 terminate，因此按 task_id 建立注册表；task_queue.Task 的
# on_cancel 回调作为兜底（轮询间隙也能立即杀进程）。
# ---------------------------------------------------------------------------
_ACTIVE_FFMPEG: dict[str, subprocess.Popen] = {}
_ACTIVE_FFMPEG_LOCK = threading.Lock()

# 线程局部取消上下文：make_video_native 开头写入，_run 轮询时读取
# （同一任务的所有 ffmpeg 调用都在同一个工作线程里串行执行）。
_CANCEL_CTX = threading.local()


def _hard_stop(proc: subprocess.Popen) -> None:
    """terminate → 等待 2s → kill：给 ffmpeg 一点时间收尾，僵死则强杀。"""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def _run(cmd: list[str], timeout: int = 600) -> subprocess.Popen:
    """跑 ffmpeg（Popen + 0.5s 轮询），失败/取消抛 RuntimeError（带 stderr 尾部）。

    轮询期间同时检查 task.cancel flag（经线程局部上下文注入）；取消时
    terminate→kill 并抛「任务已由用户主动取消」。跨平台：Windows 不弹黑窗口。
    """
    log.info("[video_native] ffmpeg: %s", " ".join(cmd[:6]) + " ...")
    cancel_check = getattr(_CANCEL_CTX, "cancel_check", None)
    task_id = getattr(_CANCEL_CTX, "task_id", None)

    # why 用子线程抽干 stderr 而不是 capture_output：ffmpeg 持续往 stderr 写
    # 进度，管道缓冲（~64KB）写满会反压卡死 ffmpeg；subprocess.run 靠
    # communicate 并发读，Popen+轮询必须自己安排读取，否则长渲染必然死锁。
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True,
                            **_subprocess_kwargs())
    stderr_tail: list[str] = []

    def _drain_stderr():
        try:
            if proc.stderr:
                stderr_tail.append(proc.stderr.read() or "")
        except Exception:
            pass

    import threading as _th
    _th.Thread(target=_drain_stderr, daemon=True).start()

    if task_id:
        with _ACTIVE_FFMPEG_LOCK:
            _ACTIVE_FFMPEG[task_id] = proc
    deadline = time.time() + max(30, int(timeout))
    try:
        while True:
            try:
                proc.wait(timeout=0.5)
                break  # 进程已退出
            except subprocess.TimeoutExpired:
                pass
            if cancel_check is not None:
                try:
                    if cancel_check():
                        _hard_stop(proc)
                        raise RuntimeError("任务已由用户主动取消，ffmpeg 渲染已中止")
                except RuntimeError:
                    raise
                except Exception:
                    pass  # 取消检查自身异常不阻断渲染
            if time.time() > deadline:
                _hard_stop(proc)
                raise RuntimeError(f"ffmpeg 执行超时（>{timeout}s），已强制中止")
        if proc.returncode != 0:
            tail = (stderr_tail[-1] if stderr_tail else "")[-500:]
            raise RuntimeError("ffmpeg 失败: " + tail)
        return proc
    finally:
        # 无论成功/失败/取消，都要摘掉注册表条目并保证进程不残留
        if task_id:
            with _ACTIVE_FFMPEG_LOCK:
                if _ACTIVE_FFMPEG.get(task_id) is proc:
                    _ACTIVE_FFMPEG.pop(task_id, None)
        if proc.poll() is None:
            _hard_stop(proc)


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

def voice_clone_request(provider: str, text: str, ref_audio: str | None = None, *,
                        api_url: str = "", api_key: str = "",
                        model: str = "", voice_id: str = "default") -> tuple[str, dict, dict]:
    """声音克隆请求体公共构造（v15.9.9 重复代码收敛 R2 的唯一真源）。

    why：core/video_native._make_voice_clone_audio 与
    web/routers/media.video_test_voice_clone 历史上各维护一份逐行对应的
    payload 组装，改一家漏一家。收敛后双方都调本函数拿 (url, headers, payload)。

    Args:
        provider: minimax / elevenlabs / cosyvoice / custom（其它值按 custom 兼容端点处理）
        text: 待合成文本
        ref_audio: 参考音频路径/URL；None 时 payload 不带参考音频字段
            （web 测试端点即传 None，与历史行为逐字节一致）
        api_url / api_key / model / voice_id: 连接与模型配置

    Returns:
        (url, headers, payload) — 调用方自行发 HTTP 请求（超时/SSRF 防护
        策略两侧不同，刻意留在调用方）。
    """
    provider = (provider or "custom").strip().lower()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    chosen_voice = voice_id or "default"

    if provider == "minimax":
        payload = {
            "model": model or "speech-01-turbo",
            "text": text,
            "voice_setting": {"voice_id": chosen_voice},
            "audio_setting": {"sample_rate": 24000, "format": "mp3"},
        }
    elif provider == "elevenlabs":
        payload = {
            "text": text,
            "model_id": model or "eleven_multilingual_v2",
        }
    elif provider == "cosyvoice":
        payload = {
            "model": model or "cosyvoice-v1",
            "input": text,
            "voice": chosen_voice,
        }
        if ref_audio:
            payload["prompt_audio"] = ref_audio
    else:  # custom / 通用兼容端点：字段冗余携带，兼容最多变体
        payload = {
            "text": text,
            "input": text,
            "model": model,
            "voice": chosen_voice,
        }
        if ref_audio:
            payload["prompt_audio"] = ref_audio
            payload["ref_audio"] = ref_audio
    return api_url, headers, payload


def parse_voice_clone_response(provider: str, data: bytes, *,
                               fetch_url: bool = True) -> bytes:
    """声音克隆响应公共解析：兼容 JSON（b64 变体 / audio url）与裸音频两种返回。

    why provider 形参保留：签名按审查报告定死（provider, data），当前四家
    上游响应结构一致；将来某家结构分叉时在此按 provider 分支，调用方无感。

    Args:
        data: 原始响应字节
        fetch_url: 响应只给音频 URL 时是否代下载（web 测试端点可传 False
            保持「只回显」的历史行为）

    Raises:
        ValueError: 提取不到有效音频或音频 <1KB（调用方转译为各自的错误响应）。
    """
    audio = bytes(data or b"")
    audio_url = ""
    if audio[:1] == b"{":
        import base64 as _b64
        import json as _json
        try:
            jd = _json.loads(audio.decode("utf-8", errors="ignore"))
            b64_str = (jd.get("audio") or jd.get("audio_content")
                       or (jd.get("data") or {}).get("audio")
                       or ((jd.get("data") or [{}])[0] if isinstance(jd.get("data"), list) else {}).get("b64_json"))
            audio_url = jd.get("url") or (jd.get("data") or {}).get("url") or ""
            if b64_str:
                audio = _b64.b64decode(b64_str)
        except Exception:
            audio = bytes(data or b"")  # JSON 剥壳失败按裸音频处理
    if len(audio) < 1000 and audio_url and fetch_url:
        import httpx
        dl = httpx.get(audio_url, timeout=60, follow_redirects=True)
        if dl.status_code == 200:
            audio = dl.content
    if len(audio) < 1000:
        raise ValueError(f"声音克隆返回音频无效或过小（{len(audio)} 字节）")
    return audio


def _make_voice_clone_audio(script: str, out_mp3: Path,
                            prompt_audio: str | None = None,
                            voice_id: str | None = None) -> Path | None:
    """声音克隆 API 配音（支持 CosyVoice / MiniMax / ElevenLabs / 通用兼容端点）。

    从视频合成配置读 voice_clone_api_url / voice_clone_api_key / voice_clone_provider / voice_clone_model，
    请求体与响应解析走公共函数 voice_clone_request / parse_voice_clone_response
    （与 web 侧测试端点同源）。成功写回 out_mp3，失败返回 None（上层回退 TTS）。
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
        log.warning("[video_native] 未配置 voice_clone_api_url，回退 TTS")
        return None

    import httpx

    url, headers, body = voice_clone_request(
        provider, script, ref_audio,
        api_url=api_url, api_key=api_key, model=model,
        voice_id=voice_id or default_voice or "default")

    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            resp = client.post(url, json=body, headers=headers)
            if resp.status_code != 200:
                log.warning("[video_native] 声音克隆 API 返回 HTTP %s: %s", resp.status_code, resp.text[:200])
                return None
            # 解析与有效性校验收敛进公共函数（<1KB 视为无效，抛 ValueError）
            audio = parse_voice_clone_response(provider, resp.content)

        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        out_mp3.write_bytes(audio)
        log.info("[video_native] 声音克隆配音成功: %s (%d KB)", out_mp3.name, len(audio) // 1024)
        return out_mp3
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] 声音克隆 API 调用失败（%s），回退 TTS", exc)
        return None


def _make_tts_audio(script: str, out_mp3: Path, voice: str = "zh-CN-XiaoxiaoNeural",
                    voice_engine: str | None = None) -> Path | None:
    """配音。voice_engine: tts（默认，A 三引擎链）/ voice_clone / local_model。

    - voice_clone：调配置的声音克隆 API，失败回退 tts
    - local_model：暂未实现，直接回退 tts（打日志明示）
    v15.9.9 归一：②段原是又一份 edge-tts 直连实现，现改调统一引擎封装
    （studio.audio.engines.synthesize），音色短键/全名映射与失败处置全仓一致。
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
        log.warning("[video_native] A 链 TTS 失败（%s），回退统一引擎封装", exc)

    # ② 统一引擎封装（原 edge-tts 直连实现已归一；失败显式抛错 → 上层输出无声视频）
    try:
        from studio.audio.engines import synthesize as _unified_synthesize
        result = _unified_synthesize(script, voice, str(out_mp3), rate=1.0)
        log.info("[video_native] TTS 成功（统一引擎封装）: %s", result.out_path)
        return Path(result.out_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("[video_native] 统一引擎封装 TTS 失败（%s），输出无声视频", exc)
    return None


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
    kw_candidates = list(terms or [])
    for fallback in ["cinematic", "lifestyle", "city", "nature", "business"]:
        if fallback not in kw_candidates:
            kw_candidates.append(fallback)
    for kw in kw_candidates:
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
              # faststart：moov 前置，边下边播秒开（所有 mp4 产出统一加）
              "-movflags", "+faststart",
              "-an", str(seg)])
        segs.append(seg)
    lst.write_text("\n".join(f"file '{s}'" for s in segs), encoding="utf-8")
    _run([_FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-movflags", "+faststart", "-c", "copy", str(out)])
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
              "-crf", "23", "-movflags", "+faststart", str(seg)])
        segs.append(seg)
    lst = out.parent / "imgconcat.txt"
    lst.write_text("\n".join(f"file '{s}'" for s in segs), encoding="utf-8")
    _run([_FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-movflags", "+faststart", "-c", "copy", str(out)])
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
        # 音频长度决定总时长；-shortest 以最短流为准；faststart 便于在线播放秒开
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                "-shortest", str(out)]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-movflags", "+faststart",
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
                      person_ref_image: str | Path | None = None,
                      task=None) -> dict:
    """一幕原生视频合成主入口。

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
        task: task_queue.Task 实例（可选）。传入后 ffmpeg 轮询每 0.5s 检查
            task.cancel flag，取消时 terminate→kill；并把「杀当前 ffmpeg」
            注册进该 Task 的 on_cancel 回调列表（取消瞬间即时生效）。

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

    # 取消联动注入（v15.9.8）：线程局部上下文供所有 _run 轮询读取；
    # on_cancel 回调兜底「轮询间隙也能立即杀进程」。
    if task is not None:
        _CANCEL_CTX.task_id = getattr(task, "id", None)
        _CANCEL_CTX.cancel_check = getattr(task, "is_cancelled", None)

        def _on_cancel_kill_ffmpeg():
            with _ACTIVE_FFMPEG_LOCK:
                procs = [p for p in _ACTIVE_FFMPEG.values()]
            for p in procs:
                try:
                    _hard_stop(p)
                except Exception:
                    pass

        try:
            task.register_cancel(_on_cancel_kill_ffmpeg)
        except Exception as exc:  # noqa: BLE001
            log.warning("[video_native] 注册取消联动失败（不影响渲染）: %s", exc)

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
                  "-i", str(lst), "-movflags", "+faststart",
                  "-c", "copy", str(merged)])
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
