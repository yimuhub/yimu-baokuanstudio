"""电影级分镜大模型解构引擎与剪映工程导出器（Storyboard Engine）。

核心能力：
1. 将成稿图文一键解构为 4~8 个影视级标准分镜（景别、运镜轨迹、光影调色、中英文 Prompt、负向词）。
2. 生成剪映标准工程草稿（draft_content.json + draft_meta_info.json），一键导出 zip 压缩包直接在剪映中打开。
"""
from __future__ import annotations
import io
import json
import os
import re
import time
import uuid
import zipfile
from pathlib import Path

from core import agents, db, llm

BASE_DIR = Path(__file__).resolve().parent.parent

STORYBOARD_SYSTEM_PROMPT = """你是一位好莱坞顶级电影导演与视觉概念设计总监（精通 Midjourney v6、Flux、Sora、Runway、Kling 影视级分镜 Prompt 工程）。
请根据用户提供的文章标题和内容，将其解构成一系列极具电影叙事感、视觉冲击力和镜头动效的专业视频分镜脚本（共 4 到 6 个镜头）。

每个分镜必须严格包含以下要素：
- shot_index: 镜头序号 (1, 2, ...)
- duration: 预估时长秒数 (例如 4 或 5)
- shot_type: 景别与镜头 (特写 Extreme Close-up, 中景 Medium Shot, 全景 Wide Establishing Shot, 航拍 Drone Aerial View, 第一人称视角 POV, 低角度仰拍 Low Angle)
- camera_movement: 运镜指令 (缓慢推近 Slow Dolly In, 缓慢拉远 Pull Out, 侧移跟随 Tracking Pan, 环绕运镜 360 Orbit, 手持微晃 Subtle Handheld)
- lighting_style: 光影方案 (电影级侧逆光 Cinematic Rim Light, 丁达尔神光 Volumetric God Rays, 暖调复古 Warm Vintage Glow, 赛博深空霓虹 Cyberpunk Noir, 柔和窗光 Rembrandt Lighting)
- scene_description: 中文场景画面细致描述 (必须包含主体人物/道具、动作微表情、背景空间环境与情绪张力，50字以内)
- ai_prompt_en: 适配 Sora / 可灵 / Runway / Midjourney / Flux 的专业英文生图生视频提示词（70~100词，结构严谨，必须紧扣本文主题与具体画面）：
  格式：[Shot & Lens] + [Subject & Action: 具象人物外貌神态/道具特写] + [Environment & Background: 环境材质与景深] + [Lighting: 光位与光晕] + [Film & Color: Kodak Vision3 500T 35mm / ARRI Alexa LF] + [Render Tags: photorealistic, 8k, cinematic movie still, masterwork, Unreal Engine 5 render]
- negative_prompt: 负向提示词 (blurry, low quality, distorted anatomy, extra fingers, cartoon, 3d render, watermark, text, subtitles)

严格按以下 JSON 数组格式输出，不要输出任何外部多余废话或 markdown 标记：
[
  {
    "shot_index": 1,
    "duration": 4,
    "shot_type": "特写 Extreme Close-up",
    "camera_movement": "缓慢推近 Slow Dolly In",
    "lighting_style": "电影级微光 Cinematic Rim Light",
    "scene_description": "主角凝神注视着眼前的关键物品，瞳孔倒映微光，指尖微微触碰，充满期待与张力。",
    "ai_prompt_en": "Cinematic extreme close-up of intense focused eyes and trembling fingers touching glowing high-tech artifact, dramatic rim lighting, dark atmospheric studio background, shallow depth of field, 35mm anamorphic lens, Kodak Vision3 film grain, photorealistic, 8k resolution, cinematic movie still, masterwork --ar 16:9",
    "negative_prompt": "blurry, low quality, extra fingers, cartoon, distorted, text, watermark"
  }
]"""


def _fallback_storyboard(title: str, text: str) -> list[dict]:
    """基于文案实体与语境智能提取具象影视分镜，杜绝脱节模板。"""
    from core.short_drama import _synthesize_scene_prompt
    clean_title = title.replace('"', '').replace("'", "")[:24]
    paragraphs = [p.strip() for p in text.split("\n") if p.strip() and not p.strip().startswith("#")]
    if not paragraphs:
        paragraphs = [clean_title, "事件开端展开，充满悬念与期待。", "细节深入剖析，直击核心痛点。", "高潮反转来临，令人眼前一亮。", "回味沉淀，启迪深度思考。"]

    types = ["全景 Wide Establishing Shot", "中景 Medium Shot", "特写 Extreme Close-up", "动态交互 Medium Close-up", "中远景 Slow Pull-out"]
    types_en = ["Wide Establishing Shot", "Medium Shot", "Close-up", "Medium Close-up", "Wide Shot"]
    motions = ["缓慢推近 Slow Dolly In", "侧移跟随 Tracking Pan", "缓慢推进 Push In", "环绕运镜 360 Orbit", "缓慢后撤 Pull Out"]
    motions_en = ["Slow Dolly In", "Tracking Pan", "Push In", "Orbit", "Pull Out"]
    lights = [
        "电影级自然光 Cinematic Natural Daylight",
        "丁达尔神光 Volumetric God Rays",
        "侧逆轮廓光 Cinematic Rim Light",
        "暖调金光 Golden Hour Warmth",
        "沉稳电影暖调 Warm Cinematic Tone"
    ]
    lights_en = [
        "Cinematic Natural Daylight",
        "Volumetric God Rays",
        "Cinematic Rim Light with Soft Key",
        "Golden Hour Warm Reflections",
        "Moody Atmospheric Lighting"
    ]

    shots = []
    count = min(5, max(4, len(paragraphs)))
    for i in range(count):
        para = paragraphs[i % len(paragraphs)]
        script = para[:40] if len(para) > 40 else para
        p_en = _synthesize_scene_prompt(clean_title, script, types_en[i % len(types_en)], lights_en[i % len(lights_en)], motions_en[i % len(motions_en)])
        shots.append({
            "shot_index": i + 1,
            "duration": 4 if i % 2 == 0 else 5,
            "shot_type": types[i % len(types)],
            "camera_movement": motions[i % len(motions)],
            "lighting_style": lights[i % len(lights)],
            "scene_description": f"聚焦核心情节：{script[:30]}",
            "ai_prompt_en": p_en + " --ar 16:9",
            "negative_prompt": "blurry, low quality, watermark, cartoon, distorted anatomy, text"
        })
    return shots


def generate_storyboard(draft_id: str, count: int = 5) -> dict:
    """为指定草稿生成电影级分镜脚本。"""
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")

    title = d["title"]
    text = d["body_md"]
    shots = []

    if llm.available():
        try:
            user_msg = f"【文章标题】：{title}\n【文章核心内容】：\n{text[:2500]}"
            raw = agents.chat_for(
                "write",
                [
                    {"role": "system", "content": STORYBOARD_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.8,
                timeout_s=25,
            )
            m = re.search(r"\[.*\]", raw, re.S)
            if m:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, list) and len(parsed) >= 2:
                    shots = parsed
        except Exception:
            pass

    if not shots:
        shots = _fallback_storyboard(title, text)

    # 规范化字段与时长汇总
    total_seconds = 0
    for idx, s in enumerate(shots, 1):
        s["shot_index"] = idx
        dur = int(s.get("duration", 4))
        dur = max(2, min(dur, 10))
        s["duration"] = dur
        total_seconds += dur

    # 保存到草稿目录下
    ddir = db.draft_dir(draft_id)
    sb_file = ddir / "storyboard.json"
    result = {
        "draft_id": draft_id,
        "title": title,
        "total_seconds": total_seconds,
        "shot_count": len(shots),
        "shots": shots,
        "updated_at": time.time(),
    }
    sb_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def get_storyboard(draft_id: str) -> dict:
    """获取草稿已有分镜或自动生成。"""
    ddir = db.draft_dir(draft_id)
    sb_file = ddir / "storyboard.json"
    if sb_file.exists():
        try:
            return json.loads(sb_file.read_text(encoding="utf-8"))
        except Exception:
            pass
def generate_storyboard_image(draft_id: str, shot_index: int, prompt_en: str = "", aspect: str = "16:9", image_model: str = "") -> str:
    """为电影级分镜生成真实 AI 配图并持久化。"""
    from core import imagegen
    ddir = db.draft_dir(draft_id)
    img_dir = ddir / "storyboard_images"
    img_dir.mkdir(parents=True, exist_ok=True)
    out_file = img_dir / f"shot_{shot_index}.png"

    sb = get_storyboard(draft_id)
    matched = next((s for s in sb.get("shots", []) if s.get("shot_index") == shot_index), None)
    if not prompt_en and matched:
        prompt_en = matched.get("ai_prompt_en", "")

    size = "1792x1024" if aspect == "16:9" else "1024x1792"
    imagegen.gen_image(
        prompt_en, out_file, size=size,
        context_title=f"电影分镜 #{shot_index}", context_sub=prompt_en[:40],
        model=image_model
    )
    rel_path = f"/img/storyboard/{draft_id}/images/shot_{shot_index}.png"
    if matched:
        matched["image_url"] = rel_path
        matched["local_image"] = str(out_file)
        if prompt_en:
            matched["ai_prompt_en"] = prompt_en
        (ddir / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    return rel_path


def batch_generate_storyboard_images(draft_id: str, aspect: str = "16:9", image_model: str = "") -> list[dict]:
    """一键批量生成电影级分镜全部分镜的真实 AI 图。"""
    sb = get_storyboard(draft_id)
    results = []
    for s in sb.get("shots", []):
        idx = s.get("shot_index", 1)
        p = s.get("ai_prompt_en", "")
        url = generate_storyboard_image(draft_id, idx, prompt_en=p, aspect=aspect, image_model=image_model)
        results.append({"shot_index": idx, "image_url": url})
    return results


def export_jianying_draft(draft_id: str, aspect: str = "9:16") -> Path:

    """将分镜脚本导出为剪映工程草稿规范的 zip 压缩包。

    剪映草稿目录规范：
    - draft_content.json (剪映工程数据结构：画布分辨率、轨道、素材、转场)
    - draft_meta_info.json (工程元数据)
    """
    sb = get_storyboard(draft_id)
    d = db.get_draft(draft_id)
    ddir = db.draft_dir(draft_id)

    is_horizontal = (aspect == "16:9")
    width = 1920 if is_horizontal else 1080
    height = 1080 if is_horizontal else 1920

    # 剪映时间戳以微秒 (microseconds, 1s = 1,000,000us) 计量
    current_time_us = 0
    segments = []
    texts = []
    materials_texts = []
    
    for shot in sb.get("shots", []):
        dur_us = shot["duration"] * 1_000_000
        text_id = str(uuid.uuid4()).upper()
        seg_id = str(uuid.uuid4()).upper()
        
        # 画面解说字幕
        desc = shot.get("scene_description", "")
        materials_texts.append({
            "id": text_id,
            "content": json.dumps({"text": desc, "styles": []}, ensure_ascii=False),
            "font_path": "",
            "type": "subtitle"
        })
        texts.append({
            "id": seg_id,
            "material_id": text_id,
            "target_timerange": {"start": current_time_us, "duration": dur_us},
            "clip": {"speed": 1.0}
        })
        current_time_us += dur_us

    draft_content = {
        "version": 3000,
        "canvas_config": {
            "width": width,
            "height": height,
            "ratio": "16:9" if is_horizontal else "9:16"
        },
        "duration": current_time_us,
        "tracks": [
            {
                "id": str(uuid.uuid4()).upper(),
                "type": "video",
                "segments": []
            },
            {
                "id": str(uuid.uuid4()).upper(),
                "type": "text",
                "segments": texts
            },
            {
                "id": str(uuid.uuid4()).upper(),
                "type": "audio",
                "segments": []
            }
        ],
        "materials": {
            "texts": materials_texts,
            "videos": [],
            "audios": []
        }
    }

    draft_meta = {
        "draft_id": str(uuid.uuid4()).upper(),
        "draft_name": f"MediaFlow-{sb['title'][:16]}-{'横版16-9' if is_horizontal else '竖版9-16'}",
        "draft_fold_path": "",
        "tm_draft_create": int(time.time()),
        "tm_draft_modified": int(time.time()),
        "draft_timeline_duration": current_time_us,
        "draft_cover": "",
    }

    zip_path = ddir / f"jianying_project_{'16x9' if is_horizontal else '9x16'}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("draft_content.json", json.dumps(draft_content, ensure_ascii=False, indent=2))
        zf.writestr("draft_meta_info.json", json.dumps(draft_meta, ensure_ascii=False, indent=2))
        # 顺便将中英文分镜表附带一份 markdown
        md_content = f"# 《{sb['title']}》电影级分镜脚本与大模型 Prompt 表\n\n"
        md_content += f"- 画幅比例：{'16:9 横版 (1920x1080)' if is_horizontal else '9:16 竖版 (1080x1920)'}\n"
        md_content += f"- 预估总时长：{sb['total_seconds']} 秒\n\n---\n\n"
        for s in sb.get("shots", []):
            md_content += f"### 镜头 #{s['shot_index']}（{s['duration']}秒）- {s['shot_type']} | {s['camera_movement']}\n"
            md_content += f"- **光影氛围**：{s['lighting_style']}\n"
            md_content += f"- **中文画面描述**：{s['scene_description']}\n"
            md_content += f"- **AI 视频大模型 Prompt (可灵/Sora/Midjourney)**：\n  `{s['ai_prompt_en']}`\n"
            md_content += f"- **Negative Prompt (负向过滤词)**：\n  `{s['negative_prompt']}`\n\n"
        zf.writestr("storyboard_prompts.md", md_content)

    return zip_path
