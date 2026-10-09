"""一键短视频：草稿 → AI 压缩口播稿 → V7 原生引擎合成 mp4。

时长：15s≈80字 / 30s≈150字；素材 pexels（key 已配）；配音晓晓；9:16 竖版。
"""
import re
import threading
import time
from pathlib import Path

from core import agents, db

SCRIPT_TARGET = {15: "70~90", 30: "140~170"}


def make_video(draft_id: str, seconds: int = 15, subject: str = "", emit=None,
               platform: str = "douyin", aspect: str = "", voice: str = "",
               custom_script: str = "", bgm_type: str = "random",
               bgm_volume: float = 0.2, bgm_file: str = "",
               subtitle_enabled: bool = True, subtitle_position: str = "bottom",
               text_fore_color: str = "#FFFFFF", video_materials: list = None) -> dict:
    emit = emit or (lambda *_: None)
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError("草稿不存在")
    from core.platforms import get_pack
    pack = get_pack(platform)
    # seconds=0 表示不限时长（按配音自动），此时跳过截断
    seconds = 0 if int(seconds or 0) <= 0 else max(10, min(int(seconds), 120))

    # 画幅与音色自适应：优先用户显式指定，次之平台包配置，兜底 9:16
    aspect = (aspect or pack.get("video", {}).get("aspect") or "9:16").strip()
    if aspect not in ("16:9", "9:16"):
        aspect = "9:16"
    voice = (voice or pack.get("audio", {}).get("voice") or "zh-CN-XiaoxiaoNeural").strip()

    # ① 口播文案与英文检索词处理
    if custom_script and custom_script.strip():
        script = custom_script.strip()
        emit(f"使用专属口播稿（共 {len(script)} 字 · {'16:9 横版' if aspect == '16:9' else '9:16 竖版'}）…")
        # 为自定义口播稿提取英文检索词
        terms = ["cinematic", "technology", "modern lifestyle"]
        try:
            raw_terms = agents.chat_for("write", [
                {"role": "user", "content": f"根据以下口播文案，提炼3个用于在Pexels查找高质量4K视频素材的英文关键词（逗号分隔）：\n{script[:500]}"}
            ], temperature=0.3, timeout_s=10)
            m_t = re.search(r"([a-zA-Z\s,]+)", raw_terms)
            if m_t:
                parsed = [t.strip() for t in m_t.group(1).split(",") if t.strip()]
                if parsed:
                    terms = parsed[:4]
        except Exception:
            pass
    else:
        _sec_label = f"{seconds} 秒" if seconds > 0 else "完整"
        emit(f"AI 压缩 {_sec_label}口播稿（{'16:9 横版宽屏' if aspect == '16:9' else '9:16 竖版移动端'}）…")
        target_words = SCRIPT_TARGET.get(seconds, f"{int(seconds * 4.5)}~{int(seconds * 5.5)}") if seconds > 0 else "全文完整保留"
        raw = agents.chat_for("write", [
            {"role": "user", "content":
                f"把下面文章压缩成 {_sec_label}短视频口播稿（{target_words}字，纯口播文本，"
                "一句一断句，前3秒要有吸引人的黄金悬念钩子，口语化强，禁止任何markdown/标题/说明）。\n"
                f"另给3个用于检索高质量视频素材的英文关键词。\n"
                f"严格按格式输出：\nSCRIPT: <口播稿>\nTERMS: <英文词,英文词,英文词>\n\n"
                f"【标题】{d['title']}\n【正文】{d['body_md'][:3000]}"}],
            temperature=0.7)
        # 宽容解析：模型偶尔丢掉 SCRIPT: 标签或加粗，按分隔特征兜底
        terms = ["coffee shop"]
        m_t = re.search(r"TERMS\s*[:：]\s*([^\n]+)", raw)
        if m_t:
            terms = [t.strip().strip("*` ") for t in re.split(r"[,，]", m_t.group(1).strip()) if t.strip()][:4] or terms
        script = raw.split("TERMS")[0]
        script = re.sub(r"\**SCRIPT\**\s*[:：]?\s*", "", script).strip()
        script = script.strip("*` \n")
        script = re.sub(r"^(好的|以下是|这是)[^：:]*[:：]\s*", "", script)
        if len(script) < 20:
            raise RuntimeError("口播稿生成失败：" + raw[:150])

    # ② 视频合成：V7 原生引擎（ffmpeg 直出）
    aspect_tag = "16x9" if aspect == "16:9" else "9x16"
    tid = f"mf-{draft_id}-{seconds}s-{aspect_tag}"

    from core import video_native
    if not video_native.ffmpeg_available():
        from core.video_native import ffmpeg_install_hint
        raise RuntimeError(f"视频合成暂不可用：V7 原生引擎需要 ffmpeg（{ffmpeg_install_hint()}）")
    emit(f"V7 原生引擎合成（{aspect}画幅，ffmpeg 直出）…")
    native_work = Path(__file__).resolve().parent.parent / "runs" / "videos" / tid
    nr = video_native.make_video_native(
        script=script, terms=terms, seconds=seconds,
        aspect=aspect, voice=voice, title=d["title"],
        work_dir=native_work, emit=emit)
    mp4 = Path(nr["mp4"])
    meta = {
        "tid": tid, "draft_id": draft_id, "title": d["title"],
        "aspect": aspect, "seconds": seconds, "voice": voice,
        "engine": "native", "material": nr.get("material"),
        "created_at": time.time(),
        "size_kb": mp4.stat().st_size // 1024 if mp4.exists() else 0,
    }
    (mp4.parent / "meta.json").write_text(
        __import__("json").dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8")
    emit("完成（V7 原生引擎）")
    return {"tid": tid, "script": script, "terms": terms,
            "aspect": aspect, "title": d["title"],
            "mp4": str(mp4), "url": f"/api/video/file/{tid}",
            "engine": "native", "material": nr.get("material"),
            "size_kb": meta["size_kb"]}


def recent_tasks(limit: int = 12) -> list[dict]:
    """列出最近的成片（V7 原生引擎），包含横竖版比例及标题元数据。"""
    import json as _json
    out = []

    def _collect(mp4: Path, tid: str, engine: str):
        meta_file = mp4.parent / "meta.json"
        meta = {}
        if meta_file.exists():
            try:
                meta = _json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        aspect = meta.get("aspect") or ("16:9" if "16x9" in tid else "9:16")
        title = meta.get("title") or tid
        out.append({
            "tid": tid,
            "url": f"/api/video/file/{tid}",
            "aspect": aspect,
            "title": title,
            "size_kb": mp4.stat().st_size // 1024,
            "mtime": int(mp4.stat().st_mtime),
            "seconds": meta.get("seconds", 0),
            "engine": meta.get("engine", engine),
        })

    # V7 原生成片
    native_dir = Path(__file__).resolve().parent.parent / "runs" / "videos"
    if native_dir.exists():
        for mp4 in sorted(native_dir.glob("*/final-*.mp4"),
                          key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            _collect(mp4, mp4.parent.name, "native")
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out[:limit]


def add_task(task_id: str, draft_id: str, title: str, out_file: Path, aspect: str = "9:16", seconds: int = 15):
    """注册外部生成的成片（如 AI 短剧）至媒体库（V7 原生目录）。"""
    tasks_dir = Path(__file__).resolve().parent.parent / "runs" / "videos" / task_id
    tasks_dir.mkdir(parents=True, exist_ok=True)
    dst_mp4 = tasks_dir / "final-1.mp4"
    import shutil
    shutil.copy2(out_file, dst_mp4)
    import json as _json
    meta = {
        "tid": task_id,
        "draft_id": draft_id,
        "title": title,
        "aspect": aspect,
        "seconds": seconds,
        "created_at": time.time(),
        "size_kb": dst_mp4.stat().st_size // 1024,
    }
    (tasks_dir / "meta.json").write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
