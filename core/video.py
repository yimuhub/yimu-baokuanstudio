"""一键短视频：草稿 → AI 压缩口播稿 → MPT 引擎合成 mp4。

时长：15s≈80字 / 30s≈150字；素材 pexels（key 已配）；配音晓晓；9:16 竖版。
"""
import re
import threading
import time
from pathlib import Path

from core import agents, db

MPT_DIR = Path(__file__).resolve().parent.parent / "vendors" / "MoneyPrinterTurbo"
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
    seconds = max(10, min(int(seconds), 120))
    subject = (subject or d["title"]).strip()[:40]

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
        emit(f"AI 压缩 {seconds} 秒口播稿（{'16:9 横版宽屏' if aspect == '16:9' else '9:16 竖版移动端'}）…")
        target_words = SCRIPT_TARGET.get(seconds, f"{int(seconds * 4.5)}~{int(seconds * 5.5)}")
        raw = agents.chat_for("write", [
            {"role": "user", "content":
                f"把下面文章压缩成 {seconds} 秒短视频口播稿（{target_words}字，纯口播文本，"
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

    # ② 提交 MPT 任务：支持 16:9 与 9:16 独立命名，避免相互覆盖
    aspect_tag = "16x9" if aspect == "16:9" else "9x16"
    tid = f"mf-{draft_id}-{seconds}s-{aspect_tag}"
    emit(f"下载素材并压制成片（{aspect}画幅，耗时约1~3分钟）…")
    import json as _json
    import subprocess
    runner = Path(__file__).resolve().parent / "video_runner.py"
    py = MPT_DIR / ".venv" / "bin" / "python"
    if not py.exists():
        raise RuntimeError("MPT 依赖未安装：先在引擎页点「启动引擎界面」完成初始化")
    payload = _json.dumps({
        "tid": tid, "subject": subject,
        "script": script, "terms": terms,
        "aspect": aspect,
        "clip": int(pack.get("video", {}).get("clip", 3)),
        "voice": voice,
        "bgm_type": bgm_type,
        "bgm_volume": float(bgm_volume),
        "bgm_file": bgm_file,
        "subtitle_enabled": bool(subtitle_enabled),
        "subtitle_position": subtitle_position,
        "text_fore_color": text_fore_color,
        "video_materials": video_materials or []
    }, ensure_ascii=False)
    r = subprocess.run([str(py), str(runner), payload],
                       cwd=str(MPT_DIR), capture_output=True, text=True, timeout=1500)
    result_line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT_JSON:")), "")
    if not result_line:
        raise RuntimeError("MPT 任务无结果：" + (r.stdout or r.stderr)[-200:])
    ok = _json.loads(result_line.split("RESULT_JSON:", 1)[1]).get("ok")
    if not ok:
        raise RuntimeError("MPT 合成未产出成片")

    mp4 = MPT_DIR / "storage" / "tasks" / tid / "final-1.mp4"
    if not mp4.exists():
        raise RuntimeError("合成完成但未找到成片")

    meta = {
        "tid": tid,
        "draft_id": draft_id,
        "title": d["title"],
        "aspect": aspect,
        "seconds": seconds,
        "voice": voice,
        "created_at": time.time(),
        "size_kb": mp4.stat().st_size // 1024,
    }
    (mp4.parent / "meta.json").write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    emit("完成")
    return {"tid": tid, "script": script, "terms": terms,
            "aspect": aspect, "title": d["title"],
            "mp4": str(mp4), "url": f"/api/video/file/{tid}",
            "size_kb": mp4.stat().st_size // 1024}


def recent_tasks(limit: int = 12) -> list[dict]:
    """列出最近的成片，包含横竖版比例及标题元数据。"""
    tasks_dir = MPT_DIR / "storage" / "tasks"
    out = []
    import json as _json
    if tasks_dir.exists():
        for mp4 in sorted(tasks_dir.glob("*/final-1.mp4"),
                          key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            meta_file = mp4.parent / "meta.json"
            meta = {}
            if meta_file.exists():
                try:
                    meta = _json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            tid = mp4.parent.name
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
            })
    return out


def add_task(task_id: str, draft_id: str, title: str, out_file: Path, aspect: str = "9:16", seconds: int = 15):
    """注册外部生成的成片（如 AI 短剧）至媒体库。"""
    tasks_dir = MPT_DIR / "storage" / "tasks" / task_id
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
