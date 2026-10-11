"""MediaFlow 全 AI 短剧/短视频流水线工坊 (AI Short Drama Pipeline)。

参考开源项目与专业平台：StoryDiffusion, Pavo AI, ChatTTS, videolingo
8 步全流程工业级短剧出片管线：
Step 1: 需求分析与剧本改写 (Story Analysis & Requirement Specs)
Step 2: 剧本大纲与剧情脉络 (Beat Sheet, Outline & Entity Extraction)
Step 3: 角色、场景与道具资产设定 (Visual Design Specs & Consistency Prompts)
Step 4: 视觉资产与角色四视图生成 (Asset Generation & Turnaround Sheets)
Step 5: 逐镜头影视级分镜解构 (Storyboard Shot List Deconstruct)
Step 6: 分镜头关键帧画面生成 (Shot Keyframe Image Generation)
Step 7: 分镜头动态视频切片合成 (Shot Video Motion & Speech Audio Synthesis)
Step 8: 全剧视听母带拼接封装 (Final Drama Video Stitching, Audio Ducking & Subtitles)
"""
import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from core import agents, db, imagegen, video

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent

# 7 大影视工业级视觉艺术风格（全链路真实渗透：台词/光影/生图/运镜/音色/配乐）
DRAMA_STYLES = {
    "ancient_realistic": {
        "name": "🎎 真人古代写实",
        "desc": "国风历史正剧，考究汉唐明宋服饰，电影胶片质感",
        "suffix": ", hyperrealistic ancient Chinese historical cinema still, cinematic lighting, Ming and Song dynasty authentic silk clothing, historical set design, 8k resolution, Kodak Vision3 35mm film grain, ARRI Alexa LF look, masterpiece",
        "character_sheet_style": "ancient Chinese historical drama concept art, authentic traditional attire, silk embroidery, master cinematic concept sheet",
        "dialogue_tone": "古风雅正文白杂糅，遣词内敛凝练，严守汉唐明宋礼制称谓（如孤/卿/在下/阁下），含蓄机锋与宿命感。",
        "lighting_palette": "天然烛火暖光、宫廷漏窗微光透射、古朴木石暗调反射、柯达电影胶片颗粒。",
        "camera_style": "沉稳横移轴线镜头、端正对称构图、慢速轨道推近特写、克制凝重。",
        "recommended_voice": "zh-CN-YunxiNeural",
        "bgm_style": "古筝、尺八、琵琶与大提琴交融的古典深沉民乐，空灵苍凉。"
    },
    "modern_realistic": {
        "name": "🏙️ 现代都市写实",
        "desc": "都市商战/职场情感大片，自然环境光，现代质感",
        "suffix": ", contemporary urban drama movie still, realistic natural lighting, modern high-end interior, ARRI Alexa LF, shallow depth of field, 35mm lens, photorealistic, 8k resolution, cinematic color grading",
        "character_sheet_style": "contemporary urban fashion character sheet, tailored modern clothing, realistic concept art, clean studio lighting",
        "dialogue_tone": "现代干练职场口语，高语速机锋对决，金句频出，情绪直接有刺痛感与都市痛点。",
        "lighting_palette": "冷调落地窗自然天光、摩天大楼室内暖黄辅助光、浅景深商战写实色彩、真实环境反光。",
        "camera_style": "手持纪实微晃运镜、过肩平视机位、快节奏侧面推拉跟拍。",
        "recommended_voice": "zh-CN-XiaoxiaoNeural",
        "bgm_style": "轻快律动低音、现代都会微电子与轻钢琴，充满节奏紧迫感。"
    },
    "oriental_mythology": {
        "name": "🐉 东方神话玄幻",
        "desc": "仙侠飘逸神光，流云飞瀑，宏大天地灵气",
        "suffix": ", ethereal oriental mythology xianxia cinema, flowing celestial silk, floating misty sacred mountains, glowing spiritual energy particles, golden hour volumetric illumination, Unreal Engine 5 render, octane render, 8k",
        "character_sheet_style": "oriental fantasy xianxia character design sheet, celestial flowing robes, glowing mystic runes, concept art model sheet",
        "dialogue_tone": "仙风道骨与修真玄门语汇，言及天地大道、因果宿命，气势磅礴而超然出尘。",
        "lighting_palette": "金乌神光破云、周身流光溢彩、灵气粒子体积光、流云飞瀑的虚幻引擎UE5神迹渲染。",
        "camera_style": "大纵深御风穿梭飞行机位、环绕360度法阵旋转、极速拉远变千里大远景。",
        "recommended_voice": "zh-CN-YunyangNeural",
        "bgm_style": "空灵天籁编钟、悠远箫声配合宏大仙侠管弦乐与大堂鼓。"
    },
    "anime_3d": {
        "name": "🎬 3D 国漫大片风",
        "desc": "追光/深海级高精 3D CG 渲染，精致毛发与皮肤散射",
        "suffix": ", high-end 3D Chinese animated blockbuster style, Pixar and Light Chaser Animation aesthetic, hyper-detailed subsurface scattering, subsurface skin glow, cinematic dynamic lighting, 8k, Unreal Engine 5 cinematic render",
        "character_sheet_style": "3D animated feature film character model sheet, Pixar 3D aesthetic, turn-around model sheet, studio clean turntable",
        "dialogue_tone": "少年英气与热血掷地有声，带有动漫戏剧张力，情感宣泄极具爆发力与羁绊感。",
        "lighting_palette": "高精次表面皮肤散射 (SSS)、细腻发丝高光、鲜明戏剧对比光、皮克斯与追光CG质感。",
        "camera_style": "高动态三维自由运镜、破屏冲击力视角、激战升格慢动作锁定关键帧。",
        "recommended_voice": "zh-CN-YunxiNeural",
        "bgm_style": "热血史诗交响乐、激昂铜管与重低音电子打击乐，战意沸腾。"
    },
    "anime_2d": {
        "name": "🎨 新海诚日漫风",
        "desc": "唯美光影、积雨云层、青春情绪渲染",
        "suffix": ", Makoto Shinkai aesthetic, luminous anime style, painterly cumulonimbus clouds, golden hour sunlight flare, emotional atmospheric storytelling, crisp cel-shaded lines, masterpiece, 8k",
        "character_sheet_style": "anime character model sheet, Makoto Shinkai anime style, expressive line art, animation design reference",
        "dialogue_tone": "治愈系细腻内心独白，充满青春惆怅与温柔哲思，常用天空、雨滴、微风物象喻情。",
        "lighting_palette": "逆光夕阳余晖、澄澈深蓝与粉紫积雨云天际线、手绘赛璐璐高反差明亮光斑。",
        "camera_style": "缓慢仰望天空摇镜、移焦虚化前景、唯美视线定格留白。",
        "recommended_voice": "zh-CN-XiaoxiaoNeural",
        "bgm_style": "干净纯粹的慢速纯钢琴、小提琴抒情独奏与治愈系弦乐。"
    },
    "cyberpunk_scifi": {
        "name": "🌃 赛博朋克科幻",
        "desc": "未来夜景、雨夜霓虹暗调、全息流光与机械细节",
        "suffix": ", cyberpunk neon noir aesthetic, damp reflective asphalt, cyan and magenta rim light, holographic UI reflections, octane render, futuristic Blade Runner atmosphere, volumetric smoke, photorealistic, 8k",
        "character_sheet_style": "cyberpunk sci-fi character turnaround sheet, high-tech tactical gear, cybernetic implants, glowing neon accents, technical design sheet",
        "dialogue_tone": "科技冷峻质问、仿生人与阶级哲学隐喻、反乌托邦行话，语调克制甚至冷酷。",
        "lighting_palette": "雨夜湿滑黑沥青漫反射、青品（Cyan & Magenta）双色霓虹轮廓光、全息UI倒影、体素烟雾。",
        "camera_style": "低角度仰拍压迫机位、战术无人机快速切镜、冷色调电子穿梭变焦。",
        "recommended_voice": "zh-CN-YunjianNeural",
        "bgm_style": "80s 模拟合成器波 (Synthwave)、工业低音电子、深沉未来脉冲。"
    },
    "hollywood_cinematic": {
        "name": "🎬 好莱坞电影大片",
        "desc": "好莱坞史诗质感，35mm 变形宽银幕与胶片质感",
        "suffix": ", Hollywood cinematic lighting, 35mm anamorphic film grain, Kodak Vision3 500T, photorealistic, hyper-detailed, volumetric god rays, Unreal Engine 5 render, ARRI Alexa LF look, masterpiece",
        "character_sheet_style": "Hollywood blockbuster concept art turnaround sheet, cinematic lighting, realistic costume design, production model sheet",
        "dialogue_tone": "高戏剧张力与好莱坞三幕剧冲突，台词短促有潜台词，充满危机倒计时与悬念留白。",
        "lighting_palette": "35mm 变形宽银幕蓝光拉丝、柯达 Vision3 胶片颗粒、经典伦勃朗硬光、深邃阴影。",
        "camera_style": "大轨道平稳推近、升降摇臂全景俯瞰、黄金分割对称构图。",
        "recommended_voice": "zh-CN-YunyangNeural",
        "bgm_style": "汉斯·季默式沉浸低频打击乐、好莱坞史诗管弦交响与紧张悬疑弦乐。"
    },
    # 兼容别名映射
    "cinematic": {
        "name": "🎬 好莱坞电影大片",
        "desc": "好莱坞史诗质感",
        "suffix": ", Hollywood cinematic lighting, 35mm anamorphic film grain, Kodak Vision3 500T, photorealistic, hyper-detailed, volumetric god rays, Unreal Engine 5 render, ARRI Alexa LF look, masterpiece",
        "character_sheet_style": "Hollywood blockbuster concept art turnaround sheet, cinematic lighting",
        "dialogue_tone": "高戏剧张力好莱坞台词，短促有潜台词，充满悬念留白。",
        "lighting_palette": "经典伦勃朗硬光、柯达电影胶片颗粒、深邃阴影与体积光。",
        "camera_style": "大轨道平稳推近、升降摇臂俯瞰全景。",
        "recommended_voice": "zh-CN-YunyangNeural",
        "bgm_style": "好莱坞史诗管弦交响与紧张悬疑弦乐。"
    },
    "cyberpunk": {
        "name": "🌃 赛博朋克科幻",
        "desc": "赛博科幻",
        "suffix": ", cyberpunk neon noir aesthetic, damp reflective asphalt, cyan and magenta rim light, holographic UI reflections, octane render, futuristic Blade Runner atmosphere, volumetric smoke, photorealistic, 8k",
        "character_sheet_style": "cyberpunk sci-fi character turnaround sheet",
        "dialogue_tone": "科技冷峻质问、反乌托邦行话，语调克制。",
        "lighting_palette": "青品双色霓虹轮廓光、雨夜黑沥青漫反射、全息UI倒影。",
        "camera_style": "低角度仰拍压迫机位、战术无人机快速切镜。",
        "recommended_voice": "zh-CN-YunjianNeural",
        "bgm_style": "80s 模拟合成器波 (Synthwave)、工业低音电子。"
    },
    "anime_drama": {
        "name": "🎨 新海诚日漫风",
        "desc": "新海诚唯美",
        "suffix": ", Makoto Shinkai aesthetic, luminous anime style, painterly cumulonimbus clouds, golden hour sunlight flare, emotional atmospheric storytelling, crisp cel-shaded lines, masterpiece, 8k",
        "character_sheet_style": "anime character model sheet",
        "dialogue_tone": "治愈系细腻内心独白，充满青春惆怅与温柔哲思。",
        "lighting_palette": "逆光夕阳余晖、澄澈深蓝与粉紫积雨云天际线、明亮手绘光斑。",
        "camera_style": "缓慢仰望天空摇镜、移焦虚化留白。",
        "recommended_voice": "zh-CN-XiaoxiaoNeural",
        "bgm_style": "慢速纯钢琴与治愈系弦乐独奏。"
    },
    "vintage_film": {
        "name": "🎞️ 复古胶片港风",
        "desc": "王家卫复古胶片港风",
        "suffix": ", 1990s Hong Kong cinematic film still, Wong Kar-wai style, Kodak Portra 400, muted retro tones, soft halation, emotional nostalgic lighting",
        "character_sheet_style": "1990s vintage Hong Kong cinematic character turnaround sheet",
        "dialogue_tone": "抽离游离的都市呓语独白、错位时空叙事、充满文学留白感。",
        "lighting_palette": "王家卫式浓烈墨绿与暖黄复古影调、霓虹柔光晕轮、高颗粒胶片感。",
        "camera_style": "手持摇晃跟拍、慢快门抽帧拖影感。",
        "recommended_voice": "zh-CN-YunxiNeural",
        "bgm_style": "慢节奏复古萨克斯风、拉丁吉他与慵懒爵士弦乐。"
    }
}


def _find_bin(name: str) -> str:
    candidates = [
        shutil.which(name),
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return name


def _get_drama_dir(draft_id: str) -> Path:
    d = db.draft_dir(draft_id) / "drama"
    d.mkdir(parents=True, exist_ok=True)
    (d / "assets").mkdir(parents=True, exist_ok=True)
    (d / "shots").mkdir(parents=True, exist_ok=True)
    (d / "images").mkdir(parents=True, exist_ok=True)
    (d / "audio").mkdir(parents=True, exist_ok=True)
    return d


# -------------------------------------------------------------
# 1. 项目数据持久化引擎 (Project Persistence)
# -------------------------------------------------------------

def get_pipeline_project(draft_id: str) -> dict:
    """读取或初始化草稿的 8 步短剧工业流水线工程文件。"""
    d_dir = _get_drama_dir(draft_id)
    proj_file = d_dir / "drama_project.json"
    
    draft = db.get_draft(draft_id) or {}
    title = draft.get("title", "未命名短剧")
    body_md = draft.get("body_md", "")

    default_project = {
        "project_id": draft_id,
        "title": title,
        "current_step": 1,
        "step1": {
            "title": title,
            "premise": "",
            "duration_target": 45,
            "aspect": "9:16",
            "split_mode": "mixed",
            "style": "hollywood_cinematic",
            "director_notes": "节奏明快、开门见山、反转跌宕、突出视听细节与人物微表情",
            "original_script": body_md[:4000]
        },
        "step2": {
            "logline": "",
            "beats": [
                {"name": "起 (开端入局)", "summary": ""},
                {"name": "承 (矛盾升级)", "summary": ""},
                {"name": "转 (爆发反转)", "summary": ""},
                {"name": "合 (余韵悬念)", "summary": ""}
            ],
            "characters_list": [],
            "scenes_list": [],
            "props_list": []
        },
        "step3": {
            "characters": [],
            "scenes": [],
            "props": []
        },
        "step4": {
            "status": "pending",
            "assets_count": 0
        },
        "step5": {
            "shots": []
        },
        "step6": {
            "status": "pending"
        },
        "step7": {
            "status": "pending"
        },
        "step8": {
            "status": "pending",
            "video_url": "",
            "task_id": ""
        },
        "updated_at": int(time.time())
    }

    if proj_file.exists():
        try:
            saved = json.loads(proj_file.read_text(encoding="utf-8"))
            # 补齐可能缺失的键
            for k, v in default_project.items():
                if k not in saved:
                    saved[k] = v
                elif isinstance(v, dict) and isinstance(saved.get(k), dict):
                    for subk, subv in v.items():
                        if subk not in saved[k]:
                            saved[k][subk] = subv
            return saved
        except Exception as e:
            logger.warning(f"读取 drama_project.json 失败，重置为默认: {e}")

    # 如果有历史 legacy scenes.json，尝试自动同步迁移到 step5
    scenes_file = d_dir / "scenes.json"
    if scenes_file.exists():
        try:
            legacy_scenes = json.loads(scenes_file.read_text(encoding="utf-8"))
            if legacy_scenes and isinstance(legacy_scenes, list):
                default_project["step5"]["shots"] = legacy_scenes
        except Exception:
            pass

    proj_file.write_text(json.dumps(default_project, ensure_ascii=False, indent=2), encoding="utf-8")
    return default_project


def save_pipeline_project(draft_id: str, project_data: dict) -> dict:
    """持久化保存短剧工程数据。"""
    d_dir = _get_drama_dir(draft_id)
    proj_file = d_dir / "drama_project.json"
    project_data["updated_at"] = int(time.time())
    proj_file.write_text(json.dumps(project_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # 同步 step5 shots 到 scenes.json，保持向前兼容
    if "step5" in project_data and "shots" in project_data["step5"]:
        (d_dir / "scenes.json").write_text(
            json.dumps(project_data["step5"]["shots"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return project_data


# -------------------------------------------------------------
# 2. Step 1: 需求分析与剧本改写 (Story Analysis & Requirement Specs)
# -------------------------------------------------------------

STEP1_PROMPT = """你是一名资深好莱坞制片人兼短剧剧本总监。
用户正在构思或改编一部 30~90 秒高能短剧。请分析用户提供的剧本/文章材料及需求设定，提炼出电影级故事梗概，并拆解故事脉络与核心实体。

【输出要求】：严格返回纯 JSON 对象，不要输出任何多余解释或 Markdown 标记外壳：
{
  "title": "精炼有张力的短剧片名",
  "premise": "故事核心梗概（80~150字，交代背景、主角核心动机、面临的极端危机与最终反转）",
  "logline": "一句话高概念介绍（25字以内）",
  "beats": [
    {"name": "起 (开端入局)", "summary": "开头10秒建立悬念或危机"},
    {"name": "承 (矛盾升级)", "summary": "冲突加剧，各方博弈达到白热化"},
    {"name": "转 (爆发反转)", "summary": "出人意料的转折或关键真相揭露"},
    {"name": "合 (余韵悬念)", "summary": "扣人心弦的收尾，留下强烈回味"}
  ],
  "characters": [
    {
      "name": "角色名",
      "gender": "男/女",
      "age": "年龄段",
      "role": "主角/反派/导师/伙伴",
      "appearance": "外貌神态与服装特征（详细具体，便于后续生成四视图与生图提示词）"
    }
  ],
  "scenes": [
    {
      "name": "场景名",
      "desc": "空间与光影氛围描述（如：雨夜冷光天台、赛博霓虹地下实验室）"
    }
  ],
  "props": [
    {
      "name": "关键道具名",
      "desc": "外观特征与剧情用途"
    }
  ]
}
"""

def step1_analyze_and_rewrite(draft_id: str, text: str = "", overrides: dict = None) -> dict:
    """Step 1 & Step 2 联动：由导演 Agent (director) 统筹剧本分析、名家行文指纹与风格全链路渗透。"""
    proj = get_pipeline_project(draft_id)
    overrides = overrides or {}
    
    # 合并用户在需求确认弹窗中选定的参数
    for k in ["title", "duration_target", "aspect", "split_mode", "style", "director_notes", "mounted_persona"]:
        if k in overrides:
            proj["step1"][k] = overrides[k]
    
    input_text = (text or overrides.get("original_script") or proj["step1"].get("original_script") or "").strip()
    if input_text:
        proj["step1"]["original_script"] = input_text
    
    style_key = proj["step1"].get("style", "hollywood_cinematic")
    style_info = DRAMA_STYLES.get(style_key, DRAMA_STYLES["hollywood_cinematic"])
    mounted_persona = proj["step1"].get("mounted_persona", "")

    persona_prompt_segment = ""
    if mounted_persona:
        try:
            from core import orchestrator as O
            voice_txt = O.get_voice_content(mounted_persona)
            if voice_txt:
                persona_prompt_segment = f"\n【挂载大师人设/文风指纹 ({mounted_persona})】：\n请在故事叙事视角、台词遣词造句与潜台词中深度贯彻以下指纹特征：\n{voice_txt[:1800]}\n"
        except Exception as e:
            logger.warning(f"获取挂载名家文风失败: {e}")

    user_prompt = f"""【短剧核心设定与 5 维艺术规范】：
- 片名意向：{proj['step1'].get('title')}
- 目标时长：{proj['step1'].get('duration_target')} 秒
- 艺术风格：{style_info['name']} ({style_info.get('desc', '')})
- 对白与台词基调：{style_info.get('dialogue_tone', '精炼有张力')}
- 影视光影与色彩：{style_info.get('lighting_palette', '电影级布光')}
- 镜头运动律动：{style_info.get('camera_style', '平稳电影运镜')}
- 呈现画幅：{proj['step1'].get('aspect')}
- 台词模式：{proj['step1'].get('split_mode')} (纯旁白 / 多角色对白 / 混合模式)
- 导演补充说明：{proj['step1'].get('director_notes')}{persona_prompt_segment}

【原始素材与剧本文案】：
{input_text[:3500]}
"""

    parsed_result = None
    try:
        # 真正调用专职短剧导演 Agent (director)
        raw = agents.chat_for("director", [
            {"role": "system", "content": STEP1_PROMPT},
            {"role": "user", "content": user_prompt}
        ], temperature=0.7, timeout_s=60)

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            parsed_result = json.loads(m.group(0))
        else:
            parsed_result = json.loads(cleaned)
    except Exception as e:
        logger.warning(f"Step 1 AI 剧本分析失败，启用影视级智能保底提取: {e}")
        parsed_result = _fallback_step1_analysis(proj["step1"].get("title", "短剧"), input_text)

    # 将分析结果回填到 project
    if parsed_result:
        if parsed_result.get("title"):
            proj["step1"]["title"] = parsed_result["title"]
        proj["step1"]["premise"] = parsed_result.get("premise", "")
        
        proj["step2"]["logline"] = parsed_result.get("logline", "")
        proj["step2"]["beats"] = parsed_result.get("beats", proj["step2"]["beats"])
        
        chars = parsed_result.get("characters", [])
        scenes = parsed_result.get("scenes", [])
        props = parsed_result.get("props", [])
        
        proj["step2"]["characters_list"] = [f"{c.get('name')} ({c.get('role', '核心角色')})" for c in chars]
        proj["step2"]["scenes_list"] = [s.get("name") for s in scenes]
        proj["step2"]["props_list"] = [p.get("name") for p in props]

        # 同步生成初始 Step 3 资产规格（待后续单步细化或一键推进）
        step3_chars = []
        for i, c in enumerate(chars):
            cid = f"char_{i+1}"
            step3_chars.append({
                "id": cid,
                "name": c.get("name", f"角色{i+1}"),
                "gender": c.get("gender", "未知"),
                "age": c.get("age", "青年"),
                "role": c.get("role", "主角"),
                "appearance": c.get("appearance", "干练利落，眼神坚定"),
                "portrait_prompt": "",
                "turnaround_prompt": "",
                "image_url": "",
                "turnaround_image_url": ""
            })
        
        step3_scenes = []
        for i, s in enumerate(scenes):
            sid = f"scene_{i+1}"
            step3_scenes.append({
                "id": sid,
                "name": s.get("name", f"场景{i+1}"),
                "desc": s.get("desc", "充满光影张力的电影级空间"),
                "prompt": "",
                "image_url": ""
            })

        step3_props = []
        for i, p in enumerate(props):
            pid = f"prop_{i+1}"
            step3_props.append({
                "id": pid,
                "name": p.get("name", f"道具{i+1}"),
                "desc": p.get("desc", "推动情节发展的关键物品"),
                "prompt": "",
                "image_url": ""
            })

        proj["step3"] = {
            "characters": step3_chars,
            "scenes": step3_scenes,
            "props": step3_props
        }

    proj["current_step"] = max(proj.get("current_step", 1), 2)
    save_pipeline_project(draft_id, proj)
    return proj


def _fallback_step1_analysis(title: str, text: str) -> dict:
    """大模型离线或格式异常时的保底剧本分析器。"""
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    first_line = lines[0] if lines else title
    
    return {
        "title": title or "风暴前夕",
        "premise": f"围绕「{first_line[:30]}」展开的高能故事。在层层重压下，主角打破常规逆风破局，在关键时刻迎来令人意想不到的反转与释怀。",
        "logline": f"当危机逼近极限，唯有坚守信念才能破局新生。",
        "beats": [
            {"name": "起 (开端入局)", "summary": f"主角置身于突如其来的变故之中：{first_line[:35]}"},
            {"name": "承 (矛盾升级)", "summary": "多方矛盾交织，形势愈发失控，关键线索浮现"},
            {"name": "转 (爆发反转)", "summary": "主角做出孤注一掷的决断，剧情迎来决定性高潮"},
            {"name": "合 (余韵悬念)", "summary": "真相大白，但新的征途已在悄然展开"}
        ],
        "characters": [
            {
                "name": "主角 (林深)",
                "gender": "男",
                "age": "28岁",
                "role": "核心破局者",
                "appearance": "身着深灰战术风衣，黑发微乱，眼神沉着深邃，手腕佩戴发光的微型终端"
            },
            {
                "name": "搭档 (苏晚)",
                "gender": "女",
                "age": "26岁",
                "role": "关键支持者",
                "appearance": "干练高马尾，米白色修身西装，神情警觉敏锐，佩戴骨传导耳机"
            }
        ],
        "scenes": [
            {
                "name": "幽蓝微光控制中心",
                "desc": "环形全息数据流交互界面，暗色调金属工业质感，窗外雨夜霓虹流转"
            },
            {
                "name": "雨夜高空天台",
                "desc": "湿漉漉的地面倒映着摩天大楼的红色警示灯，冷风呼啸，视野广阔而压抑"
            }
        ],
        "props": [
            {
                "name": "加密数据芯片",
                "desc": "透明微型晶圆芯片，内嵌微型发光电路，蕴藏终极秘密"
            }
        ]
    }


# -------------------------------------------------------------
# 3. Step 2: 剧本大纲与脉络确认 (Outline & Beat Sheet)
# -------------------------------------------------------------

def step2_confirm_outline(draft_id: str, updates: dict = None) -> dict:
    """确认并保存修改后的剧本大纲、起承转合节拍与实体。"""
    proj = get_pipeline_project(draft_id)
    if updates:
        for k in ["logline", "beats", "characters_list", "scenes_list", "props_list"]:
            if k in updates:
                proj["step2"][k] = updates[k]
    proj["current_step"] = max(proj.get("current_step", 1), 3)
    save_pipeline_project(draft_id, proj)
    return proj


# -------------------------------------------------------------
# 4. Step 3: 角色、场景与道具设定 (Visual Design Specs & Prompts)
# -------------------------------------------------------------

def step3_generate_assets_specs(draft_id: str) -> dict:
    """为各个角色生成立绘与四视图一致性 Prompt，为场景与道具生成高清 Prompt。"""
    proj = get_pipeline_project(draft_id)
    style_key = proj["step1"].get("style", "hollywood_cinematic")
    style_info = DRAMA_STYLES.get(style_key, DRAMA_STYLES["hollywood_cinematic"])

    characters = proj.get("step3", {}).get("characters", [])
    scenes = proj.get("step3", {}).get("scenes", [])
    props = proj.get("step3", {}).get("props", [])

    # 如果角色列表为空，从 step2 兜底创建
    if not characters:
        characters = [
            {
                "id": "char_1",
                "name": "林深",
                "gender": "男",
                "age": "28岁",
                "role": "核心破局者",
                "appearance": "身着深灰战术风衣，黑发微乱，眼神沉着深邃",
                "portrait_prompt": "",
                "turnaround_prompt": "",
                "image_url": "",
                "turnaround_image_url": ""
            }
        ]

    # 为每个角色构建严谨一致的四视图 Prompt (StoryDiffusion / Concept Art Turnaround 规范)
    for c in characters:
        name = c.get("name", "Character")
        role = c.get("role", "Protagonist")
        app = c.get("appearance", "determined expression, stylish clothing")
        
        # 1. 单张人物正面立绘 Prompt
        c["portrait_prompt"] = (
            f"Cinematic portrait of {name}, {role}, {app}, "
            f"master cinematic lighting, 85mm portrait lens, shallow depth of field, sharp focus on face, "
            f"8k resolution, photorealistic"
            f"{style_info['suffix']}"
        )
        
        # 2. 核心：四视图一致性 Prompt (Turnaround Sheet: 正面、侧面、背面、3/4特写)
        c["turnaround_prompt"] = (
            f"technical character design sheet, 4-view turnaround (front view, side profile view, back view, 3/4 face close-up) of {name}, "
            f"{role}, {app}, neutral clean studio background with technical alignment guidelines, consistent proportions, "
            f"concept model turnaround sheet, {style_info.get('character_sheet_style', 'master concept art')}, "
            f"ultra-detailed, 8k resolution, masterpiece"
        )

    # 为每个场景生成 Prompt
    for s in scenes:
        sname = s.get("name", "Scene")
        sdesc = s.get("desc", "Cinematic environment")
        s["prompt"] = (
            f"Cinematic wide establishing shot of {sname}, {sdesc}, "
            f"volumetric lighting, atmospheric haze, 35mm anamorphic lens, hyper-detailed environment, "
            f"photorealistic, 8k resolution"
            f"{style_info['suffix']}"
        )

    # 为每个道具生成 Prompt
    for p in props:
        pname = p.get("name", "Prop")
        pdesc = p.get("desc", "Important cinematic item")
        p["prompt"] = (
            f"Detailed studio product shot of {pname}, {pdesc}, "
            f"isolated with moody cinematic rim lighting, macro lens, shallow depth of field, 8k resolution, photorealistic"
            f"{style_info['suffix']}"
        )

    proj["step3"] = {
        "characters": characters,
        "scenes": scenes,
        "props": props
    }
    proj["current_step"] = max(proj.get("current_step", 1), 4)
    save_pipeline_project(draft_id, proj)
    return proj


# -------------------------------------------------------------
# 5. Step 4: 资产图片生成与角色四视图 (Asset Gen & Turnaround Sheet)
# -------------------------------------------------------------

def _render_character_turnaround_sheet(out_file: Path, char_name: str, role: str, appearance: str, prompt_en: str, style_name: str):
    """当外部 API 离线或备用时，Pillow 渲染专业影视工业级 4 视图模型表 (Front / Side / Back / 3/4 Close-up)。"""
    from PIL import Image, ImageDraw, ImageFont
    w, h = 1600, 900
    img = Image.new("RGB", (w, h), color=(22, 26, 35))
    draw = ImageDraw.Draw(img)

    # 绘制科技感对齐网格与深空渐变
    for y in range(h):
        r = int(18 + (y / h) * 10)
        g = int(22 + (y / h) * 12)
        b = int(32 + (y / h) * 20)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    grid_color = (35, 42, 58)
    for x in range(0, w, 40):
        draw.line([(x, 70), (x, h - 80)], fill=grid_color, width=1)
    for y in range(70, h - 80, 40):
        draw.line([(0, y), (w, y)], fill=grid_color, width=1)

    # 顶部横幅
    draw.rectangle([(0, 0), (w, 65)], fill=(15, 18, 26))
    draw.line([(0, 65), (w, 65)], fill=(240, 136, 62), width=3)
    
    # 底部横幅
    draw.rectangle([(0, h - 75), (w, h)], fill=(15, 18, 26))
    draw.line([(0, h - 75), (w, h - 75)], fill=(60, 70, 90), width=1)

    # 加载系统字体
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/STHeiti Light.ttc"
    ]
    f_title, f_sub, f_tag = None, None, None
    for fp in font_paths:
        if Path(fp).exists():
            try:
                f_title = ImageFont.truetype(fp, 22)
                f_sub = ImageFont.truetype(fp, 14)
                f_tag = ImageFont.truetype(fp, 12)
                break
            except Exception:
                pass

    # 顶部标题文本
    header_txt = f"CHARACTER DESIGN SHEET · 角色四视图一致性蓝图: {char_name}"
    meta_txt = f"身份定位: {role} | 视觉风格: {style_name} | 工业标准: 4-View Turnaround & Face Detail"
    if f_title:
        draw.text((35, 12), header_txt, fill=(255, 255, 255), font=f_title)
        draw.text((35, 40), meta_txt, fill=(160, 175, 200), font=f_sub)
    else:
        draw.text((35, 20), header_txt, fill=(255, 255, 255))

    # 四视图区域划分 (4 个立柱面板)
    panel_w = (w - 100) // 4
    col_x = [40 + i * (panel_w + 7) for i in range(4)]
    views = [
        ("VIEW 01: FRONT", "正面立绘 (Front View)"),
        ("VIEW 02: SIDE", "侧身廓形 (Side Profile)"),
        ("VIEW 03: BACK", "背影结构 (Back View)"),
        ("VIEW 04: 3/4 CLOSE-UP", "面部特写 (Facial Detail)")
    ]

    # 人体比例水平参考标线 (头顶、眼平线、肩线、腰线、膝盖、脚底)
    guide_lines = [
        (160, "HEAD / 1.0"),
        (195, "EYE LEVEL"),
        (260, "SHOULDER"),
        (430, "WAIST / PELVIS"),
        (620, "KNEE LEVEL"),
        (760, "GROUND / 0.0")
    ]
    for gy, gname in guide_lines:
        draw.line([(30, gy), (w - 30, gy)], fill=(240, 136, 62, 80), width=1)
        if f_tag:
            draw.text((w - 110, gy - 12), gname, fill=(210, 153, 34), font=f_tag)

    # 绘制 4 个视图的线框立绘与高光卡片
    for i in range(4):
        x1 = col_x[i]
        x2 = x1 + panel_w
        y1 = 80
        y2 = h - 90
        
        # 容器卡片背景
        draw.rectangle([(x1, y1), (x2, y2)], fill=(28, 33, 46, 220), outline=(60, 75, 105), width=2)
        
        # 面板标题标签
        code_tag, zh_tag = views[i]
        draw.rectangle([(x1 + 8, y1 + 8), (x2 - 8, y1 + 38)], fill=(38, 46, 65))
        if f_sub:
            draw.text((x1 + 16, y1 + 14), f"{code_tag} · {zh_tag}", fill=(240, 136, 62), font=f_sub)

        # 绘制人体动态剪影与美学结构
        cx = (x1 + x2) // 2
        accent_color = (88, 166, 255) if i != 3 else (240, 136, 62)
        
        if i == 0:  # 正面
            draw.ellipse([(cx - 24, 165), (cx + 24, 225)], outline=accent_color, fill=(40, 50, 70), width=2)
            draw.polygon([(cx - 55, 260), (cx + 55, 260), (cx + 35, 440), (cx - 35, 440)], outline=accent_color, fill=(35, 45, 62), width=2)
            draw.line([(cx - 25, 440), (cx - 25, 760)], fill=accent_color, width=3)
            draw.line([(cx + 25, 440), (cx + 25, 760)], fill=accent_color, width=3)
            draw.line([(cx - 55, 260), (cx - 70, 480)], fill=accent_color, width=3)
            draw.line([(cx + 55, 260), (cx + 70, 480)], fill=accent_color, width=3)
        elif i == 1:  # 侧面
            draw.ellipse([(cx - 22, 165), (cx + 18, 225)], outline=accent_color, fill=(40, 50, 70), width=2)
            draw.polygon([(cx - 30, 260), (cx + 25, 260), (cx + 15, 440), (cx - 20, 440)], outline=accent_color, fill=(35, 45, 62), width=2)
            draw.line([(cx - 5, 440), (cx - 5, 760)], fill=accent_color, width=4)
            draw.line([(cx + 5, 260), (cx + 20, 480)], fill=accent_color, width=3)
        elif i == 2:  # 背面
            draw.ellipse([(cx - 24, 165), (cx + 24, 225)], outline=accent_color, fill=(30, 38, 55), width=2)
            draw.polygon([(cx - 55, 260), (cx + 55, 260), (cx + 35, 440), (cx - 35, 440)], outline=accent_color, fill=(28, 36, 50), width=2)
            draw.line([(cx - 25, 440), (cx - 25, 760)], fill=accent_color, width=3)
            draw.line([(cx + 25, 440), (cx + 25, 760)], fill=accent_color, width=3)
            draw.line([(cx, 260), (cx, 440)], fill=(240, 136, 62), width=1)
        elif i == 3:  # 特写面部表情
            draw.rectangle([(x1 + 18, 140), (x2 - 18, 480)], fill=(32, 40, 58), outline=accent_color, width=2)
            draw.ellipse([(cx - 65, 190), (cx + 65, 360)], outline=accent_color, fill=(45, 56, 80), width=2)
            draw.line([(cx - 40, 265), (cx - 15, 265)], fill=(255, 255, 255), width=3)
            draw.line([(cx + 15, 265), (cx + 40, 265)], fill=(255, 255, 255), width=3)
            draw.line([(cx, 270), (cx - 4, 305)], fill=(240, 136, 62), width=2)
            draw.line([(cx - 20, 325), (cx + 20, 325)], fill=(255, 255, 255), width=2)
            if f_tag:
                draw.text((x1 + 30, 495), "3/4 ANGLE FACIAL KEY", fill=(240, 136, 62), font=f_tag)
                draw.text((x1 + 30, 515), "CHARACTER CONSISTENCY LOCK", fill=(139, 148, 158), font=f_tag)

        if f_tag:
            draw.text((x1 + 16, y2 - 40), f"STATUS: ALIGNED · 100%", fill=(63, 185, 80), font=f_tag)
            draw.text((x1 + 16, y2 - 22), f"SCALE: 1:1 CANONICAL", fill=(139, 148, 158), font=f_tag)

    palette_colors = [(30, 35, 48), (88, 166, 255), (240, 136, 62), (210, 153, 34), (200, 215, 230)]
    for idx, c_rgb in enumerate(palette_colors):
        draw.ellipse([(35 + idx * 36, h - 55), (60 + idx * 36, h - 30)], fill=c_rgb, outline=(255, 255, 255), width=1)
    
    if f_sub:
        draw.text((230, h - 48), f"外观特征: {appearance[:70]}", fill=(200, 215, 230), font=f_sub)

    img.save(out_file, "PNG")


def step4_generate_asset_image(
    draft_id: str,
    asset_type: str,
    asset_id: str,
    prompt: str = "",
    is_turnaround: bool = False,
    aspect: str = "16:9",
    image_model: str = ""
) -> dict:
    """生成指定资产图片（角色正面照、角色四视图、场景图、道具图）。"""
    d_dir = _get_drama_dir(draft_id)
    assets_dir = d_dir / "assets"
    
    proj = get_pipeline_project(draft_id)
    style_key = proj["step1"].get("style", "hollywood_cinematic")
    style_info = DRAMA_STYLES.get(style_key, DRAMA_STYLES["hollywood_cinematic"])

    target_asset = None
    asset_list = proj.get("step3", {}).get(f"{asset_type}s" if not asset_type.endswith("s") else asset_type, [])
    for a in asset_list:
        if a.get("id") == asset_id:
            target_asset = a
            break

    if not target_asset:
        target_asset = {"id": asset_id, "name": asset_id}

    if is_turnaround:
        filename = f"{asset_id}_turnaround.png"
        out_file = assets_dir / filename
        p = prompt or target_asset.get("turnaround_prompt", "")
        # 风格一致性：四视图用 character_sheet_style
        _style_prompt = style_info.get("character_sheet_style", "") or style_info.get("suffix", "")
        p_styled = f"{p}, {_style_prompt}" if p and _style_prompt else (p or _style_prompt)
        size = "1792x1024"
        success = imagegen.gen_image(
            p_styled, out_file, size=size, angle_idx=0,
            context_title=f"角色四视图 [{target_asset.get('name')}]",
            context_sub=p_styled[:40],
            model=image_model
        )
        if not success or not out_file.exists() or out_file.stat().st_size < 1500:
            logger.info("启动影视级角色四视图专业蓝图生成器")
            _render_character_turnaround_sheet(
                out_file,
                char_name=target_asset.get("name", "主角"),
                role=target_asset.get("role", "核心主角"),
                appearance=target_asset.get("appearance", "深邃神情与专属服饰"),
                prompt_en=p_styled,
                style_name=style_info["name"]
            )
        url = f"/img/drama/{draft_id}/assets/{filename}"
        target_asset["turnaround_image_url"] = url
    else:
        filename = f"{asset_id}.png"
        out_file = assets_dir / filename
        p = prompt or target_asset.get("portrait_prompt") or target_asset.get("prompt", "")
        # 风格一致性：正面/场景/道具图用 suffix
        _style_prompt = style_info.get("suffix", "")
        p_styled = f"{p}, {_style_prompt}" if p and _style_prompt else (p or _style_prompt)
        size = "1024x1792" if aspect == "9:16" else "1792x1024"
        success = imagegen.gen_image(
            p_styled, out_file, size=size, angle_idx=1,
            context_title=f"{target_asset.get('name')}",
            context_sub=p_styled[:40],
            model=image_model
        )
        if not success or not out_file.exists() or out_file.stat().st_size < 1500:
            _generate_stylized_placeholder_image(out_file, 1, p_styled, aspect=aspect)
        url = f"/img/drama/{draft_id}/assets/{filename}"
        target_asset["image_url"] = url

    save_pipeline_project(draft_id, proj)
    return {"ok": True, "asset_id": asset_id, "url": url, "is_turnaround": is_turnaround}


def step4_batch_generate_assets(draft_id: str, image_model: str = "") -> dict:
    """一键批量生成全部资产参考图（含所有角色的四视图与正面照、场景图、道具图）。"""
    proj = get_pipeline_project(draft_id)
    step3 = proj.get("step3", {})
    chars = step3.get("characters", [])
    scenes = step3.get("scenes", [])
    props = step3.get("props", [])

    results = []
    # 1. 角色生成：四视图 + 正面立绘
    for c in chars:
        cid = c.get("id")
        r1 = step4_generate_asset_image(draft_id, "character", cid, prompt=c.get("turnaround_prompt", ""), is_turnaround=True, image_model=image_model)
        results.append(r1)
        r2 = step4_generate_asset_image(draft_id, "character", cid, prompt=c.get("portrait_prompt", ""), is_turnaround=False, image_model=image_model)
        results.append(r2)

    # 2. 场景生成
    for s in scenes:
        sid = s.get("id")
        r = step4_generate_asset_image(draft_id, "scene", sid, prompt=s.get("prompt", ""), is_turnaround=False, image_model=image_model)
        results.append(r)

    # 3. 道具生成
    for p in props:
        pid = p.get("id")
        r = step4_generate_asset_image(draft_id, "prop", pid, prompt=p.get("prompt", ""), is_turnaround=False, image_model=image_model)
        results.append(r)

    proj = get_pipeline_project(draft_id)
    proj["step4"]["status"] = "ready"
    proj["step4"]["assets_count"] = len(results)
    proj["current_step"] = max(proj.get("current_step", 1), 5)
    save_pipeline_project(draft_id, proj)
    return {"ok": True, "count": len(results), "results": results}


# -------------------------------------------------------------
# 6. Step 5: 逐镜头影视级分镜解构 (Storyboard Shot List)
# -------------------------------------------------------------

STORYBOARD_PROMPT = """你是一名顶级好莱坞导演兼电影分镜摄影大师。
请结合提供的短剧梗概、剧情节拍脉络、已确认的角色形象特征与场景资产，将其分解为具有强烈视听张力、快节奏电影感的【逐镜头分镜脚本】。

【输入资产信息】：
- 故事片名：{title}
- 目标时长：{duration_target} 秒 (建议解构出 4~6 个镜头，每个镜头 3~5 秒)
- 画幅：{aspect}
- 角色详细外观规格：
{characters_specs}
- 场景空间规格：
{scenes_specs}
- 视觉风格：{style_name}
- 导演说明：{director_notes}
- 剧本故事正文：\n{script_text}

【输出规范】：严格返回 JSON 数组，每个元素为一个镜头对象，绝不要包含任何 markdown 代码块外壳：
[
  {{
    "shot_id": 1,
    "duration": 4,
    "shot_type": "特写 Close-up / 中景 Medium / 全景 Wide / 主观 POV",
    "camera_motion": "缓慢推近 Slow Dolly In / 侧向平移 Tracking Pan / 环绕运镜 Orbit / 极速推进 Fast Zoom In",
    "character_ref": "出现的角色名（与资产库对齐）",
    "scene_ref": "发生的场景名（与资产库对齐）",
    "lighting": "电影轮廓光 / 丁达尔神光 / 霓虹暗调",
    "action": "镜头内人物神态微动作、道具交互与视听动态中文描述 (40字以内)",
    "dialogue": "角色对白或台词配音 (15~35字，纯文本，紧凑有感染力)",
    "image_prompt_en": "符合 Midjourney v6/Flux/SDXL 规范的结构化英文生图提示词 (80~110词，必须紧扣该角色外貌衣着、动作微表情、空间光影材质，包含胶片质感标签)",
    "video_prompt_en": "适配 Sora / 可灵 / Runway / Agnes 视频大模型的动态运镜与物理微动作英文提示词 (60~80词，包含主体运动动作、发丝衣物微动态、摄影机平滑轨迹、自然环境光影变化)"
  }}
]
"""

def _truncate_shots_to_duration(shots: list, max_total_seconds: float) -> tuple:
    """会员分级：按成片最大秒数截取分镜（整镜头保留，不中途剪断）。

    逐镜头累加 duration，保留累加不超过上限的镜头，保证至少保留第 1 个镜头。
    返回 (保留的分镜列表, 被截掉的镜头数)。
    """
    kept: list = []
    dropped = 0
    total = 0.0
    for sc in shots:
        try:
            dur = float(sc.get("duration", 4) or 4)
        except (TypeError, ValueError):
            dur = 4.0
        if dur <= 0:
            dur = 4.0
        if kept and total + dur > max_total_seconds:
            dropped += 1
            continue
        kept.append(sc)
        total += dur
    return kept, dropped


def step5_generate_storyboard(draft_id: str, max_total_seconds: float | None = None) -> list[dict]:
    """步骤 5：由分镜师 Agent (storyboard_artist) 解构影视分镜头剧本（穿透 5 维视听语言）。

    max_total_seconds：会员分级时长帽（秒）；为正数时截取分镜使总时长不超过上限。
    """
    proj = get_pipeline_project(draft_id)
    step1 = proj.get("step1", {})
    step2 = proj.get("step2", {})
    step3 = proj.get("step3", {})

    style_key = step1.get("style", "hollywood_cinematic")
    style_info = DRAMA_STYLES.get(style_key, DRAMA_STYLES["hollywood_cinematic"])
    mounted_persona = step1.get("mounted_persona", "")

    chars = step3.get("characters", [])
    scenes = step3.get("scenes", [])
    chars_specs = "\n".join([f"- {c.get('name')}: {c.get('appearance', '主角形象')} (角色定位: {c.get('role', '核心主角')})" for c in chars]) or "- 主角: 深邃神情与专属服饰"
    scenes_specs = "\n".join([f"- {s.get('name')}: {s.get('description', '核心现场空间')}" for s in scenes]) or "- 核心场景: 极具故事感的空间"
    chars_summary = ", ".join([c.get("name", "") for c in chars]) or "主角"
    scenes_summary = ", ".join([s.get("name", "") for s in scenes]) or "核心场景"
    script_text = step1.get("original_script", "") or proj.get("title", "")

    persona_line = ""
    if mounted_persona:
        persona_line = f"\n- 挂载名家对白指纹：{mounted_persona} (对白台词严格融入该名家句式与性格风格)"

    prompt = STORYBOARD_PROMPT.format(
        title=step1.get("title", "短剧"),
        duration_target=step1.get("duration_target", 45),
        aspect=step1.get("aspect", "9:16"),
        characters_specs=chars_specs,
        scenes_specs=scenes_specs,
        style_name=style_info["name"],
        director_notes=f"{step1.get('director_notes', '紧凑抓人')}。台词基调：{style_info.get('dialogue_tone', '')}。光影：{style_info.get('lighting_palette', '')}。运镜偏好：{style_info.get('camera_style', '')}{persona_line}",
        script_text=script_text[:3500]
    )

    shots = []
    try:
        # 真正调用影视分镜师 Agent (storyboard_artist)
        raw = agents.chat_for("storyboard_artist", [
            {"role": "system", "content": f"你是一名精通影视视听语言的分镜大师兼摄影指导。风格：{style_info['name']}。严格输出纯 JSON 数组。"},
            {"role": "user", "content": prompt}
        ], temperature=0.7, timeout_s=60)

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        m = re.search(r"\[\s*\{.*\}\s*\]", cleaned, re.DOTALL)
        if m:
            shots = json.loads(m.group(0))
        else:
            shots = json.loads(cleaned)
    except Exception as e:
        logger.warning(f"Step 5 大模型分镜解构失败，启用故事脉络保底: {e}")
        shots = _fallback_drama_scenes(step1.get("title", "短剧"), script_text)

    for idx, sc in enumerate(shots):
        sc["shot_id"] = idx + 1
        sc["duration"] = sc.get("duration", 4)
        if not sc.get("image_prompt_en", "").endswith(style_info["suffix"]):
            sc["image_prompt_en"] = sc.get("image_prompt_en", "") + style_info["suffix"]
        
        # 确保每个分镜头具备高质量视频动态提示词
        if not sc.get("video_prompt_en"):
            motion = sc.get("camera_motion", "slow cinematic motion")
            action = sc.get("action", "subtle movements")
            sc["video_prompt_en"] = f"Cinematic video clip, camera {motion.lower()}, protagonist performing {action}, highly realistic physical motion, subtle facial micro-expression, natural lighting, 4k 60fps"
            
        sc["script"] = sc.get("dialogue") or sc.get("script", "")
        sc["image_url"] = sc.get("image_url", "")
        sc["video_url"] = sc.get("video_url", "")
        sc["audio_url"] = sc.get("audio_url", "")
        sc["status"] = "ready"

    # ⭐ 会员分级：短剧成片时长帽（free：10 秒）——分镜期按总时长整镜头截取
    if isinstance(max_total_seconds, (int, float)) and max_total_seconds > 0:
        shots, dropped = _truncate_shots_to_duration(shots, float(max_total_seconds))
        if dropped:
            logger.info(f"会员分级时长帽：分镜截取为 {len(shots)} 镜（上限 {max_total_seconds} 秒，截掉 {dropped} 镜）")

    proj["step5"]["shots"] = shots
    proj["current_step"] = max(proj.get("current_step", 1), 6)
    save_pipeline_project(draft_id, proj)
    return shots


def _synthesize_scene_prompt(
    title: str,
    scene_context: str = "",
    shot_type: str = "Wide Establishing Shot",
    lighting: str = "Cinematic Natural Daylight",
    motion: str = "Slow Dolly In"
) -> str:
    """智能合成符合 Midjourney / Flux / SDXL 规范的高清影视场景与分镜英文 Prompt。"""
    clean_title = (title or "").replace('"', '').replace("'", "").strip()[:40]
    clean_ctx = (scene_context or "").replace('"', '').replace("'", "").strip()[:60]
    subject = clean_ctx or clean_title or "protagonist in dramatic scene"

    return (
        f"Cinematic {shot_type} depicting {subject}, set in the dramatic context of {clean_title}, "
        f"{lighting}, camera {motion.lower()}, 35mm anamorphic lens aesthetic, shallow depth of field, "
        f"subtle rim lighting, atmospheric volumetric haze, Kodak Vision3 film grain, hyper-detailed texture, "
        f"award-winning cinematography, photorealistic, 8k resolution, masterpiece"
    )


def _fallback_drama_scenes(title: str, text: str) -> list[dict]:
    """保底分镜生成器。"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip() and not p.strip().startswith("#")]
    if not paragraphs:
        paragraphs = [title, "精彩内容即将展开，高能反转不断。", "关键细节浮出水面，真相震撼人心。", "最终时刻来临，结局引人深思。"]
    
    shots = []
    types = ["Close-up", "Medium Shot", "Wide Establishing Shot", "POV Shot", "Low-angle Hero Shot"]
    motions = ["Slow Dolly In", "Tracking Pan", "Orbit Around Subject", "Handheld Subtle Motion", "Slow Pull Out"]
    lights = [
        "Cinematic Rim Light with Soft Key",
        "Golden Hour Volumetric Rays",
        "Dramatic Chiaroscuro Contrast",
        "Moody Ambient Neon Glow",
        "Diffused Window Natural Light"
    ]
    
    for i in range(min(5, max(4, len(paragraphs)))):
        para = paragraphs[i % len(paragraphs)]
        script = para[:35] if len(para) > 35 else para
        stype = types[i % len(types)]
        smotion = motions[i % len(motions)]
        slight = lights[i % len(lights)]
        
        prompt_en = _synthesize_scene_prompt(title, script, stype, slight, smotion)
        
        shots.append({
            "shot_id": i + 1,
            "duration": 4,
            "shot_type": stype,
            "camera_motion": smotion,
            "character_ref": "主角",
            "scene_ref": "核心现场",
            "lighting": slight,
            "action": f"聚焦核心情节：{script[:25]}",
            "dialogue": script,
            "script": script,
            "image_prompt_en": prompt_en,
            "negative_prompt": "blurry, low quality, distorted, bad anatomy, text, watermark, cartoon, 3d render"
        })
    return shots


# -------------------------------------------------------------
# 7. Step 6: 分镜头关键帧生图 (Shot Keyframe Image Generation)
# -------------------------------------------------------------

def step6_generate_shot_image(draft_id: str, shot_id: int, prompt_en: str = "", aspect: str = "9:16", image_model: str = "") -> dict:
    """生成指定分镜头的真实 AI 画面，保存在 drama/shots/shot_{shot_id}.png。"""
    d_dir = _get_drama_dir(draft_id)
    shots_dir = d_dir / "shots"
    out_file = shots_dir / f"shot_{shot_id}.png"

    proj = get_pipeline_project(draft_id)
    shots = proj.get("step5", {}).get("shots", [])
    target_shot = next((s for s in shots if s.get("shot_id") == shot_id), None)

    # 风格一致性：分镜关键帧同样注入 Step 1 选择的风格 suffix
    style_key = proj.get("step1", {}).get("style", "hollywood_cinematic")
    style_info = DRAMA_STYLES.get(style_key, DRAMA_STYLES["hollywood_cinematic"])
    _style_prompt = style_info.get("suffix", "")

    p = prompt_en or (target_shot.get("image_prompt_en") if target_shot else "")
    p_styled = f"{p}, {_style_prompt}" if p and _style_prompt else (p or _style_prompt)
    size = "1024x1792" if aspect == "9:16" else "1792x1024"
    angle_idx = (shot_id - 1) % 5

    success = imagegen.gen_image(
        p_styled, out_file, size=size, angle_idx=angle_idx,
        context_title=f"分镜头 #{shot_id}", context_sub=p_styled[:40],
        model=image_model
    )
    if not success or not out_file.exists() or out_file.stat().st_size < 1500:
        _generate_stylized_placeholder_image(out_file, shot_id, p_styled, aspect=aspect)

    legacy_file = d_dir / "images" / f"shot_{shot_id}.png"
    try:
        shutil.copyfile(out_file, legacy_file)
    except Exception:
        pass

    rel_url = f"/img/drama/{draft_id}/shots/shot_{shot_id}.png"
    if target_shot:
        target_shot["image_url"] = rel_url
        target_shot["local_image"] = str(out_file)
        if prompt_en:
            target_shot["image_prompt_en"] = prompt_en
    
    save_pipeline_project(draft_id, proj)
    return {"ok": True, "shot_id": shot_id, "image_url": rel_url}


def step6_batch_generate_shots(draft_id: str, aspect: str = "9:16", image_model: str = "") -> dict:
    """一键批量生成全部分镜画面。"""
    proj = get_pipeline_project(draft_id)
    shots = proj.get("step5", {}).get("shots", [])
    results = []
    for sc in shots:
        sid = sc.get("shot_id", 1)
        r = step6_generate_shot_image(draft_id, sid, prompt_en=sc.get("image_prompt_en", ""), aspect=aspect, image_model=image_model)
        results.append(r)
    
    proj = get_pipeline_project(draft_id)
    proj["step6"]["status"] = "ready"
    proj["current_step"] = max(proj.get("current_step", 1), 7)
    save_pipeline_project(draft_id, proj)
    return {"ok": True, "count": len(results), "results": results}


# -------------------------------------------------------------
# 8. Step 7: 分镜头动态视频切片生成 (Shot Video Clip Motion)
# -------------------------------------------------------------

# -------------------------------------------------------------
# 8. Step 7: 分镜头动态视频切片生成 (Shot Video Clip Motion)
# -------------------------------------------------------------

def generate_ai_video_clip(
    img_path: Path,
    prompt_en: str,
    out_mp4: Path,
    aspect: str = "9:16",
    duration_s: int = 5,
    preferred_model: str = "agnes-video-2.5-flash"
) -> bool:
    """调用原生 AI 视频大模型（agnes-video-2.5-flash），以首帧参考图驱动生成真实连续动态视频切片。
    新 schema(2026-10):mode=keyframe + first_frame;时长字段 seconds(字符串);分辨率 size=720P。
    agnes-video-v2.0 上游已无渠道(503 model_not_found),不再作为兜底。"""
    if not img_path.exists() or img_path.stat().st_size < 1000:
        return False

    from core.llm import load_config, load_env
    env = load_env()
    cfg = load_config()
    api_key = env.get("MEDIAFLOW_APIPOOL_KEY", "").strip()
    gw_base = (cfg.get("gateway", {}).get("base_url") or "http://127.0.0.1:8787/v1").rstrip("/")
    host_root = gw_base[:-3] if gw_base.endswith("/v1") else gw_base

    raw_bytes = img_path.read_bytes()
    b64_str = base64.b64encode(raw_bytes).decode("ascii")
    data_uri = f"data:image/png;base64,{b64_str}"

    motion_prompt = prompt_en or "cinematic video, camera movement, natural subtle subject movements, realistic lighting"
    if not any(k in motion_prompt.lower() for k in ("motion", "camera", "dolly", "pan", "movement", "cinematic")):
        motion_prompt = f"{motion_prompt}, smooth cinematic slow motion, subtle alive micro-movements, 4k 60fps"

    # 读取网关中绑定的专属视频生成 Agent 路由模型
    routed_video_m = cfg.get("gateway", {}).get("agent_routing", {}).get("video", "").strip()
    active_preferred = routed_video_m or preferred_model or "agnes-video-2.5-flash"

    models_to_try = [active_preferred]
    if active_preferred != "agnes-video-2.5-flash":
        models_to_try.append("agnes-video-2.5-flash")

    for model_id in models_to_try:
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            dur = max(4, min(int(duration_s), 8))
            # 统一走 Agnes 新 schema(text|keyframe|reference + seconds + size);
            # 旧 v2.0 那套 height/width/num_frames/frame_rate/image 字段上游已全部拒绝。
            req_body = {
                "model": model_id,
                "prompt": motion_prompt[:450],
                "mode": "keyframe",
                "first_frame": data_uri,
                "seconds": str(dur),
                "size": "720P",
                "aspect_ratio": aspect if aspect in ("9:16", "16:9") else "9:16",
                "n": 1
            }

            with httpx.Client(timeout=10.0) as client:
                res = client.post(f"{gw_base}/videos", headers=headers, json=req_body)
                if res.status_code != 200:
                    logger.warning(f"AI 视频模型 {model_id} 提交返回 ({res.status_code}): {res.text[:160]}")
                    continue

                resp_json = res.json()
                task_id = resp_json.get("task_id") or resp_json.get("id")
                if not task_id:
                    continue

                logger.info(f"AI 视频任务已提交: {task_id}, 开始轮询成片...")
                video_url = None
                poll_url = f"{gw_base}/videos/{task_id}"

                start_t = time.time()
                while time.time() - start_t < 60:
                    time.sleep(3.0)
                    try:
                        poll_res = client.get(poll_url, headers=headers, timeout=6.0)
                    except Exception:
                        continue
                    if poll_res.status_code != 200:
                        continue
                    poll_data = poll_res.json()
                    status = (poll_data.get("status") or "").lower()
                    if status in ("succeeded", "success", "completed", "done"):
                        video_url = poll_data.get("url") or poll_data.get("video_url") or (poll_data.get("metadata") or {}).get("url")
                        vid = poll_data.get("video_id") or (poll_data.get("metadata") or {}).get("video_id")
                        if not video_url and vid:
                            q_res = client.get(f"{host_root}/agnesapi", params={"video_id": vid}, headers=headers)
                            if q_res.status_code == 200:
                                q_data = q_res.json()
                                video_url = q_data.get("url") or q_data.get("video_url") or (q_data.get("metadata") or {}).get("url")
                        break
                    elif status in ("failed", "error", "cancelled"):
                        logger.warning(f"AI 视频任务状态为失败: {poll_data}")
                        break

                if video_url:
                    dl_res = client.get(video_url, follow_redirects=True, timeout=60.0)
                    if dl_res.status_code == 200 and len(dl_res.content) > 10000:
                        out_mp4.write_bytes(dl_res.content)
                        logger.info(f"🎉 真实 AI 视频切片已成功获取: {out_mp4.name} ({len(dl_res.content)} bytes)")
                        return True
        except Exception as err:
            logger.warning(f"调用 AI 视频模型 {model_id} 异常: {err}")

    return False


def _align_ai_video_with_audio_and_subtitle(
    ai_raw_mp4: Path,
    audio_file: Path,
    out_mp4: Path,
    target_dur: float,
    aspect: str = "9:16",
    script_text: str = "",
    subtitle_enabled: bool = False
):
    """将 AI 大模型生成的视频切片与配音频轨对齐，并按创作者偏好无损合成字幕（若关闭则纯净直出）。"""
    ffmpeg_bin = _find_bin("ffmpeg")
    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)

    if subtitle_enabled and script_text:
        sub_overlay_png = ai_raw_mp4.parent / f"sub_{ai_raw_mp4.stem}.png"
        _create_subtitle_overlay_png(sub_overlay_png, script_text, aspect=aspect)
        cmd = [
            ffmpeg_bin, "-y",
            "-stream_loop", "-1", "-i", str(ai_raw_mp4),
            "-i", str(sub_overlay_png),
            "-i", str(audio_file),
            "-filter_complex", f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[base];[base][1:v]overlay=0:0[v]",
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(target_dur),
            "-shortest", str(out_mp4)
        ]
    else:
        cmd = [
            ffmpeg_bin, "-y",
            "-stream_loop", "-1", "-i", str(ai_raw_mp4),
            "-i", str(audio_file),
            "-filter_complex", f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[v]",
            "-map", "[v]", "-map", "1:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(target_dur),
            "-shortest", str(out_mp4)
        ]

    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def step7_generate_shot_video(
    draft_id: str,
    shot_id: int,
    aspect: str = "9:16",
    subtitle_enabled: Optional[bool] = None,
    video_mode: str = "ai_video",
    video_model: str = ""
) -> dict:
    """步骤 7：为单个分镜头渲染配音并生成动态视频片段（优先调用 AI 视频大模型，支持字幕自由开关）。"""
    d_dir = _get_drama_dir(draft_id)
    shots_dir = d_dir / "shots"
    
    proj = get_pipeline_project(draft_id)
    step1 = proj.get("step1", {})
    shots = proj.get("step5", {}).get("shots", [])
    target_shot = next((s for s in shots if s.get("shot_id") == shot_id), None)
    if not target_shot:
        raise RuntimeError(f"未找到镜头 #{shot_id}")

    # 确定字幕设置（优先参数传入，其次项目配置，默认 False 纯净无字幕）
    if subtitle_enabled is None:
        subtitle_enabled = bool(step1.get("subtitle_enabled", False))

    # 1. 确保有关键帧参考图片
    img_file = shots_dir / f"shot_{shot_id}.png"
    if not img_file.exists() or img_file.stat().st_size < 1000:
        step6_generate_shot_image(draft_id, shot_id, target_shot.get("image_prompt_en", ""), aspect=aspect)

    # 2. 确保有配音音频
    style_key = step1.get("style", "hollywood_cinematic")
    style_info = DRAMA_STYLES.get(style_key, DRAMA_STYLES["hollywood_cinematic"])
    mounted_persona = step1.get("mounted_persona", "")
    voice = style_info.get("recommended_voice", "zh-CN-YunxiNeural")
    if mounted_persona:
        try:
            from core import orchestrator as O
            for v in O.list_famous_voices():
                if v.get("id") == mounted_persona and v.get("tts_voice"):
                    voice = v["tts_voice"]
                    break
        except Exception:
            pass

    script_text = target_shot.get("dialogue") or target_shot.get("script") or "精彩马上开始"
    audio_file = d_dir / "audio" / f"shot_{shot_id}.mp3"
    synthesize_scene_tts(draft_id, shot_id, script_text, voice=voice)

    # 计算音频时长
    ffprobe_bin = _find_bin("ffprobe")
    dur = 3.5
    try:
        probe = subprocess.run(
            [ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_file)],
            capture_output=True, text=True, check=True
        )
        dur = max(3.0, float(probe.stdout.strip()) + 0.3)
    except Exception:
        dur = float(target_shot.get("duration", 3.5))

    clip_out = shots_dir / f"clip_{shot_id}.mp4"
    is_ai_video = False

    # 3. 尝试调用原生 AI 视频大模型生成真正的连续动态视频
    if video_mode == "ai_video":
        ai_raw_mp4 = shots_dir / f"ai_raw_{shot_id}.mp4"
        prompt_en = target_shot.get("video_prompt_en") or target_shot.get("image_prompt_en", "")
        logger.info(f"正在调用真实 AI 视频大模型为镜头 #{shot_id} 生成首帧驱动动态视频...")
        ok = generate_ai_video_clip(img_file, prompt_en, ai_raw_mp4, aspect=aspect, duration_s=int(dur), preferred_model=video_model)
        if ok and ai_raw_mp4.exists() and ai_raw_mp4.stat().st_size > 5000:
            try:
                _align_ai_video_with_audio_and_subtitle(
                    ai_raw_mp4=ai_raw_mp4,
                    audio_file=audio_file,
                    out_mp4=clip_out,
                    target_dur=dur,
                    aspect=aspect,
                    script_text=script_text,
                    subtitle_enabled=subtitle_enabled
                )
                is_ai_video = True
                logger.info(f"🎉 镜头 #{shot_id} 成功由原生 AI 视频大模型驱动并对齐成片！")
            except Exception as e:
                logger.warning(f"AI 视频对齐异常，无缝切换至电影级动态渲染: {e}")

    # 4. 若未采用 AI 视频或大模型排队未就绪，使用电影级多轴动态光学镜头渲染
    if not is_ai_video or not clip_out.exists() or clip_out.stat().st_size < 1000:
        comp_img = shots_dir / f"frame_{shot_id}.png"
        # 若 subtitle_enabled 为 False，将完全不压制任何字幕，保持 100% 电影原片纯净！
        _composite_shot_with_subtitle(img_file, comp_img, script_text, shot_id, aspect=aspect, subtitle_enabled=subtitle_enabled)

        ffmpeg_bin = _find_bin("ffmpeg")
        w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
        motion = target_shot.get("camera_motion", "Push In")
        fps = 25
        total_frames = int(dur * fps)

        # 优化多轴平滑运镜：带柔和呼吸感与非线性缓动，彻底摆脱死板生硬拉伸
        if "Push" in motion or "Dolly" in motion:
            vf = f"scale={w*2}:{h*2},zoompan=z='min(zoom+0.0008,1.15)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
        elif "Pan" in motion or "Tracking" in motion:
            vf = f"scale={w*2}:{h*2},zoompan=z='1.08':x='if(lte(on,1),(iw-iw/zoom)/2,x+0.8)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={w}x{h}:fps={fps}"
        elif "Orbit" in motion:
            vf = f"scale={w*2}:{h*2},zoompan=z='1.06+0.02*sin(2*PI*on/{total_frames})':d={total_frames}:x='iw/2-(iw/zoom/2)+15*cos(2*PI*on/{total_frames})':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
        else:
            vf = f"scale={w*2}:{h*2},zoompan=z='1.04+0.02*sin(2*PI*on/{total_frames})':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"

        cmd = [
            ffmpeg_bin, "-y", "-loop", "1", "-i", str(comp_img), "-i", str(audio_file),
            "-vf", vf, "-t", str(dur),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-shortest", str(clip_out)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    rel_video_url = f"/video/drama/{draft_id}/shots/clip_{shot_id}.mp4"
    target_shot["video_url"] = rel_video_url
    target_shot["local_clip"] = str(clip_out)
    target_shot["is_ai_video"] = is_ai_video
    target_shot["subtitle_enabled"] = subtitle_enabled
    target_shot["video_mode"] = video_mode
    
    save_pipeline_project(draft_id, proj)
    return {
        "ok": True,
        "shot_id": shot_id,
        "video_url": rel_video_url,
        "is_ai_video": is_ai_video,
        "subtitle_enabled": subtitle_enabled
    }


def step7_batch_generate_videos(
    draft_id: str,
    aspect: str = "9:16",
    subtitle_enabled: Optional[bool] = None,
    video_mode: str = "ai_video",
    video_model: str = ""
) -> dict:
    """批量生成所有镜头的动态视频切片。"""
    proj = get_pipeline_project(draft_id)
    if subtitle_enabled is None:
        subtitle_enabled = bool(proj.get("step1", {}).get("subtitle_enabled", False))

    shots = proj.get("step5", {}).get("shots", [])
    results = []
    for sc in shots:
        sid = sc.get("shot_id", 1)
        r = step7_generate_shot_video(
            draft_id, sid,
            aspect=aspect,
            subtitle_enabled=subtitle_enabled,
            video_mode=video_mode,
            video_model=video_model
        )
        results.append(r)

    proj = get_pipeline_project(draft_id)
    proj["step7"]["status"] = "ready"
    proj["step7"]["subtitle_enabled"] = subtitle_enabled
    proj["step7"]["video_mode"] = video_mode
    if video_model:
        proj["step7"]["video_model"] = video_model
    proj["current_step"] = max(proj.get("current_step", 1), 8)
    save_pipeline_project(draft_id, proj)
    return {"ok": True, "count": len(results), "results": results}


# -------------------------------------------------------------
# 9. Step 8: 全剧视听成片母带封装 (Final Assembly & Concat)
# -------------------------------------------------------------

def step8_render_final_drama(
    draft_id: str,
    aspect: str = "9:16",
    subtitle_enabled: Optional[bool] = None,
    video_mode: str = "ai_video",
    video_model: str = "",
    emit=None
) -> dict:
    """步骤 8：将所有分镜头视频切片无缝拼接、背景音乐混音与母带导出。"""
    emit = emit or (lambda *_: None)
    emit("正在检查全部分镜视频切片…")
    
    d_dir = _get_drama_dir(draft_id)
    proj = get_pipeline_project(draft_id)
    if subtitle_enabled is None:
        subtitle_enabled = bool(proj.get("step1", {}).get("subtitle_enabled", False))

    shots = proj.get("step5", {}).get("shots", [])
    if not shots:
        raise RuntimeError("未发现短剧分镜数据，请先执行分镜拆解")

    clips = []
    for sc in shots:
        sid = sc.get("shot_id", 1)
        clip_file = d_dir / "shots" / f"clip_{sid}.mp4"
        if not clip_file.exists() or clip_file.stat().st_size < 1000:
            emit(f"自动补齐渲染分镜头 #{sid} 运镜视频切片…")
            step7_generate_shot_video(
                draft_id, sid,
                aspect=aspect,
                subtitle_enabled=subtitle_enabled,
                video_mode=video_mode,
                video_model=video_model
            )
        clips.append(clip_file)

    emit("多镜头智能缝合与成片母带封装…")
    concat_list = d_dir / "concat_list.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    aspect_tag = "16x9" if aspect == "16:9" else "9x16"
    final_mp4 = d_dir / f"short_drama_{aspect_tag}.mp4"
    ffmpeg_bin = _find_bin("ffmpeg")

    concat_cmd = [
        ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", str(final_mp4)
    ]
    try:
        subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError:
        # 若不同切片编码存在细微差别，回落到安全重编码平滑拼接
        reencode_cmd = [
            ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            str(final_mp4)
        ]
        subprocess.run(reencode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    task_id = f"drama-{draft_id[:8]}-{aspect_tag}"
    title = proj.get("step1", {}).get("title") or proj.get("title", "AI短剧")
    video.add_task(
        task_id=task_id,
        draft_id=draft_id,
        title=f"【全AI短剧】{title}",
        out_file=final_mp4,
        aspect=aspect
    )

    video_url = f"/api/video/file/{task_id}"
    proj["step8"]["status"] = "ready"
    proj["step8"]["video_url"] = video_url
    proj["step8"]["task_id"] = task_id
    proj["step8"]["subtitle_enabled"] = subtitle_enabled
    proj["current_step"] = 8
    save_pipeline_project(draft_id, proj)

    emit("🎉 全 AI 电影级短剧合成完毕！已入库成片资料库")
    return {
        "ok": True,
        "task_id": task_id,
        "video_url": video_url,
        "aspect": aspect,
        "scenes_count": len(shots),
        "subtitle_enabled": subtitle_enabled
    }


# -------------------------------------------------------------
# 10. 历史兼容函数 (Backwards Compatibility)
# -------------------------------------------------------------

def decompose_draft_to_drama(draft_id: str, style_key: str = "hollywood_cinematic", custom_script: str = "", mounted_persona: str = "") -> list[dict]:
    """历史入口兼容：执行 Step 1 ➔ Step 5 并返回 scenes（支持挂载名家文风与 5 维风格）。"""
    step1_analyze_and_rewrite(draft_id, text=custom_script, overrides={"style": style_key, "mounted_persona": mounted_persona})
    step3_generate_assets_specs(draft_id)
    return step5_generate_storyboard(draft_id)


def get_drama_scenes(draft_id: str) -> list[dict]:
    """读取分镜头列表。"""
    proj = get_pipeline_project(draft_id)
    return proj.get("step5", {}).get("shots", [])


def update_drama_scene(draft_id: str, shot_id: int, updates: dict) -> dict:
    """更新镜头属性。"""
    proj = get_pipeline_project(draft_id)
    shots = proj.get("step5", {}).get("shots", [])
    target = None
    for sc in shots:
        if sc.get("shot_id") == shot_id:
            for k, v in updates.items():
                if v is not None:
                    sc[k] = v
            target = sc
            break
    if target:
        save_pipeline_project(draft_id, proj)
    return target or {}


def generate_scene_image(draft_id: str, shot_id: int, prompt_en: str = "", aspect: str = "9:16") -> str:
    """历史入口兼容。"""
    res = step6_generate_shot_image(draft_id, shot_id, prompt_en=prompt_en, aspect=aspect)
    return res["image_url"]


def batch_generate_drama_images(draft_id: str, aspect: str = "9:16") -> list[dict]:
    """历史入口兼容。"""
    res = step6_batch_generate_shots(draft_id, aspect=aspect)
    return res["results"]


def render_short_drama_video(draft_id: str, aspect: str = "9:16", emit=None) -> dict:
    """历史入口兼容。"""
    return step8_render_final_drama(draft_id, aspect=aspect, emit=emit)


def synthesize_scene_tts(draft_id: str, shot_id: int, script_text: str, voice: str = "zh-CN-YunxiNeural") -> str:
    """单镜头配音合成。"""
    d_dir = _get_drama_dir(draft_id)
    audio_dir = d_dir / "audio"
    out_file = audio_dir / f"shot_{shot_id}.mp3"

    edge_bin = _find_bin("edge-tts")
    tts_success = False
    if edge_bin:
        try:
            cmd = [
                edge_bin,
                "--voice", voice,
                "--text", script_text,
                "--write-media", str(out_file)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if res.returncode == 0 and out_file.exists() and out_file.stat().st_size > 500:
                tts_success = True
        except Exception as e:
            logger.warning(f"Edge-TTS 调用异常: {e}")

    if not tts_success:
        ffmpeg_bin = _find_bin("ffmpeg")
        cmd_fallback = [
            ffmpeg_bin, "-y", "-f", "lavfi",
            "-i", "anullsrc=r=24000:cl=mono",
            "-t", "3.5", "-acodec", "libmp3lame", str(out_file)
        ]
        subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    rel_path = f"/audio/drama/{draft_id}/shot_{shot_id}.mp3"
    proj = get_pipeline_project(draft_id)
    for sc in proj.get("step5", {}).get("shots", []):
        if sc.get("shot_id") == shot_id:
            sc["audio_url"] = rel_path
            sc["local_audio"] = str(out_file)
            break
    save_pipeline_project(draft_id, proj)
    return rel_path


def _generate_stylized_placeholder_image(out_file: Path, shot_id: int, prompt_en: str, aspect: str = "9:16"):
    """使用 Pillow 渲染具备暗夜电影级构图、镜头标签与暗角的工业级分镜参考图。"""
    from PIL import Image, ImageDraw, ImageFont
    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
    img = Image.new("RGB", (w, h), color=(15, 20, 30))
    draw = ImageDraw.Draw(img)

    for y in range(h):
        r = int(12 + (y / h) * 20)
        g = int(18 + (y / h) * 15)
        b = int(32 + (y / h) * 45)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    line_color = (60, 80, 110)
    draw.rectangle([(40, 40), (w - 40, h - 40)], outline=line_color, width=2)
    draw.line([(w // 3, 40), (w // 3, h - 40)], fill=line_color, width=1)
    draw.line([(w * 2 // 3, 40), (w * 2 // 3, h - 40)], fill=line_color, width=1)
    draw.line([(40, h // 3), (w - 40, h // 3)], fill=line_color, width=1)
    draw.line([(40, h * 2 // 3), (w - 40, h * 2 // 3)], fill=line_color, width=1)

    draw.ellipse([(w//2 - 60, h//2 - 60), (w//2 + 60, h//2 + 60)], outline=(240, 136, 62), width=3)
    draw.line([(w//2 - 90, h//2), (w//2 + 90, h//2)], fill=(240, 136, 62), width=2)
    draw.line([(w//2, h//2 - 90), (w//2, h//2 + 90)], fill=(240, 136, 62), width=2)

    tag_text = f"SCENE SHOT #{shot_id} [{aspect}]"
    draw.rectangle([(60, 60), (320, 105)], fill=(240, 136, 62))
    draw.text((75, 72), tag_text, fill=(255, 255, 255))
    
    prompt_snip = (prompt_en[:120] + "...") if len(prompt_en) > 120 else prompt_en
    draw.rectangle([(60, h - 160), (w - 60, h - 60)], fill=(0, 0, 0, 160), outline=line_color)
    draw.text((75, h - 145), f"AI PROMPT: {prompt_snip}", fill=(200, 215, 230))
    draw.text((75, h - 100), "STATUS: REFERENCE CONCEPT READY · 100% VISUAL ALIGNED", fill=(63, 185, 80))

    img.save(out_file, "PNG")


def _create_subtitle_overlay_png(out_path: Path, script_text: str, aspect: str = "9:16"):
    """创建透明度通道的现代电影字幕遮罩图，用于与原生 AI 视频流进行无损合成。"""
    from PIL import Image, ImageDraw, ImageFont
    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if not script_text:
        overlay.save(out_path, "PNG")
        return

    draw = ImageDraw.Draw(overlay)
    font = None
    for fp in ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/STHeiti Light.ttc"]:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, size=int(h * 0.028))
                break
            except Exception:
                pass

    box_y1 = int(h * 0.83)
    box_y2 = int(h * 0.91)
    draw.rounded_rectangle([(36, box_y1), (w - 36, box_y2)], radius=12, fill=(8, 12, 18, 165), outline=(255, 255, 255, 45), width=1)

    if font:
        bbox = draw.textbbox((0, 0), script_text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = max(45, (w - tw) // 2)
        ty = box_y1 + (box_y2 - box_y1 - th) // 2
        draw.text((tx + 1, ty + 1), script_text, fill=(0, 0, 0, 180), font=font)
        draw.text((tx, ty), script_text, fill=(255, 255, 255, 245), font=font)
    else:
        draw.text((50, box_y1 + 18), script_text, fill=(255, 255, 255, 240))
    overlay.save(out_path, "PNG")


def _composite_shot_with_subtitle(base_img_path: Path, out_path: Path, script_text: str, shot_id: int, aspect: str = "9:16", subtitle_enabled: bool = False):
    """根据创作者选择，处理关键帧画面与字幕合成。若 subtitle_enabled 为 False，输出 100% 纯净无遮挡画面。"""
    from PIL import Image, ImageDraw, ImageFont
    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
    img = Image.open(base_img_path).convert("RGBA")
    if img.size != (w, h):
        img = img.resize((w, h), Image.Resampling.LANCZOS)
    
    if not subtitle_enabled or not script_text:
        # 纯净无字幕模式：直接输出高清无遮挡画面
        img.convert("RGB").save(out_path, "PNG")
        return

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    font = None
    for fp in ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/STHeiti Light.ttc"]:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, size=int(h * 0.028))
                break
            except Exception:
                pass
    
    box_y1 = int(h * 0.83)
    box_y2 = int(h * 0.91)
    draw.rounded_rectangle([(36, box_y1), (w - 36, box_y2)], radius=12, fill=(8, 12, 18, 165), outline=(255, 255, 255, 45), width=1)
    
    if font:
        bbox = draw.textbbox((0, 0), script_text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = max(45, (w - tw) // 2)
        ty = box_y1 + (box_y2 - box_y1 - th) // 2
        draw.text((tx + 1, ty + 1), script_text, fill=(0, 0, 0, 180), font=font)
        draw.text((tx, ty), script_text, fill=(255, 255, 255, 245), font=font)
    else:
        draw.text((50, box_y1 + 18), script_text, fill=(255, 255, 255, 240))
        
    final_img = Image.alpha_composite(img, overlay).convert("RGB")
    final_img.save(out_path, "PNG")


# -------------------------------------------------------------
# 10. IP 角色中台与单镜头非线性工作台 (IP Hub & NLE Storyboard Canvas)
# -------------------------------------------------------------

def export_character_to_ip_hub(draft_id: str, char_id: str) -> dict:
    """将短剧项目中的设定角色与四视图资产，沉淀入全局 IP 角色库。"""
    proj = get_pipeline_project(draft_id)
    chars = proj.get("step3", {}).get("characters", [])
    target = None
    for c in chars:
        if c.get("id") == char_id or c.get("name") == char_id:
            target = c
            break
    if not target:
        raise RuntimeError(f"未找到角色 {char_id}")

    d_dir = _get_drama_dir(draft_id)
    ip_dir = BASE_DIR / "data" / "ip_characters"
    ip_dir.mkdir(parents=True, exist_ok=True)

    # 迁移四视图与头像到全局 IP 目录
    src_turnaround = d_dir / "assets" / f"turnaround_{target.get('id', 'char_1')}.png"
    turnaround_rel = target.get("turnaround_image_url", "")
    if src_turnaround.exists():
        dest_turn = ip_dir / f"ip_{target.get('id', 'char_1')}_turnaround.png"
        shutil.copy2(src_turnaround, dest_turn)
        turnaround_rel = f"/data/ip_characters/{dest_turn.name}"

    src_portrait = d_dir / "assets" / f"portrait_{target.get('id', 'char_1')}.png"
    avatar_rel = target.get("image_url", "")
    if src_portrait.exists():
        dest_port = ip_dir / f"ip_{target.get('id', 'char_1')}_avatar.png"
        shutil.copy2(src_portrait, dest_port)
        avatar_rel = f"/data/ip_characters/{dest_port.name}"

    style_key = proj.get("step1", {}).get("style", "hollywood_cinematic")
    res = db.save_ip_character(
        name=target.get("name", "未命名角色"),
        gender=target.get("gender", "未知"),
        age_group=target.get("age", ""),
        style=style_key,
        avatar_url=avatar_rel,
        turnaround_sheet_url=turnaround_rel,
        features_en=target.get("turnaround_prompt", target.get("appearance", "")),
        dialogue_tone=target.get("dialogue_tone", "")
    )
    return {"ok": True, "ip_character": res}


def bind_ip_character_to_draft(draft_id: str, char_id: str, ip_char_id: str) -> dict:
    """将全局 IP 角色库中的角色深度绑定进当前短剧项目，继承四视图与特征锁。"""
    ip_char = db.get_ip_character(ip_char_id)
    if not ip_char:
        raise RuntimeError("全局 IP 角色不存在")

    proj = get_pipeline_project(draft_id)
    chars = proj.setdefault("step3", {}).setdefault("characters", [])
    found = False
    for c in chars:
        if c.get("id") == char_id:
            found = True
            c["name"] = ip_char["name"]
            c["gender"] = ip_char.get("gender", c.get("gender", ""))
            c["age"] = ip_char.get("age_group", c.get("age", ""))
            c["turnaround_prompt"] = ip_char.get("features_en", c.get("turnaround_prompt", ""))
            c["image_url"] = ip_char.get("avatar_url", "")
            c["turnaround_image_url"] = ip_char.get("turnaround_sheet_url", "")
            c["dialogue_tone"] = ip_char.get("dialogue_tone", "")
            c["ip_character_id"] = ip_char_id
            break
    if not found:
        chars.append({
            "id": char_id,
            "name": ip_char["name"],
            "gender": ip_char.get("gender", "男"),
            "age": ip_char.get("age_group", "28岁"),
            "role": "核心主角 (IP引用)",
            "appearance": ip_char.get("features_en", ""),
            "portrait_prompt": "",
            "turnaround_prompt": ip_char.get("features_en", ""),
            "image_url": ip_char.get("avatar_url", ""),
            "turnaround_image_url": ip_char.get("turnaround_sheet_url", ""),
            "dialogue_tone": ip_char.get("dialogue_tone", ""),
            "ip_character_id": ip_char_id
        })

    # 同步复制资产图片到短剧 assets 目录
    d_dir = _get_drama_dir(draft_id)
    assets_dir = d_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    if ip_char.get("turnaround_sheet_url"):
        ip_turn_file = BASE_DIR / ip_char["turnaround_sheet_url"].lstrip("/")
        if ip_turn_file.exists():
            shutil.copy2(ip_turn_file, assets_dir / f"turnaround_{char_id}.png")
    if ip_char.get("avatar_url"):
        ip_av_file = BASE_DIR / ip_char["avatar_url"].lstrip("/")
        if ip_av_file.exists():
            shutil.copy2(ip_av_file, assets_dir / f"portrait_{char_id}.png")

    save_pipeline_project(draft_id, proj)
    return {"ok": True, "characters": chars}


def reroll_shot_frame(draft_id: str, shot_id: int, prompt_en: str = "", aspect: str = "9:16") -> dict:
    """非线性工作台：单镜头关键帧独立重新生成 (Reroll)。"""
    proj = get_pipeline_project(draft_id)
    shots = proj.get("step5", {}).get("shots", [])
    target = None
    for s in shots:
        if s.get("shot_id") == shot_id:
            target = s
            break
    if not target:
        raise RuntimeError(f"未找到分镜头 #{shot_id}")

    if prompt_en:
        target["image_prompt_en"] = prompt_en
        save_pipeline_project(draft_id, proj)

    return step6_generate_shot_image(draft_id, shot_id, prompt_en=prompt_en, aspect=aspect)


def retake_shot_voice(draft_id: str, shot_id: int, script_text: str = "", voice: str = "") -> dict:
    """非线性工作台：单镜头台词配音独立重录 (Retake Voice)。"""
    proj = get_pipeline_project(draft_id)
    shots = proj.get("step5", {}).get("shots", [])
    target = None
    for s in shots:
        if s.get("shot_id") == shot_id:
            target = s
            break
    if not target:
        raise RuntimeError(f"未找到分镜头 #{shot_id}")

    if script_text:
        target["script"] = script_text
    if voice:
        target["voice"] = voice

    d_dir = _get_drama_dir(draft_id)
    audio_path = d_dir / "shots" / f"audio_{shot_id}.mp3"
    line_text = target.get("script", "")
    chosen_voice = voice or target.get("voice") or "zh-CN-YunxiNeural"

    # 调用 TTS 生成新音频
    from core import audio
    try:
        audio.generate_speech(line_text, str(audio_path), voice=chosen_voice)
        dur = 3.5
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                dur = max(2.5, min(float(r.stdout.strip()) + 0.6, 10.0))
        except Exception:
            pass
        target["duration"] = round(dur, 1)
        target["audio_file"] = f"shots/audio_{shot_id}.mp3"
    except Exception as e:
        logger.warning(f"TTS 单镜头配音失败: {e}")

    save_pipeline_project(draft_id, proj)
    return {"ok": True, "shot_id": shot_id, "duration": target.get("duration", 3.5), "audio_url": f"/data/drafts/{draft_id}/drama/shots/audio_{shot_id}.mp3"}


def reorder_and_restitch_drama(draft_id: str, new_order: list[int] = None, subtitle_enabled: Optional[bool] = None) -> dict:
    """非线性工作台：微调镜头排序并秒级快速重混视听母带（复用已渲染切片）。"""
    proj = get_pipeline_project(draft_id)
    shots = proj.get("step5", {}).get("shots", [])
    if new_order and len(new_order) == len(shots):
        shots_by_id = {s.get("shot_id"): s for s in shots}
        reordered = [shots_by_id[sid] for sid in new_order if sid in shots_by_id]
        if len(reordered) == len(shots):
            proj["step5"]["shots"] = reordered
            save_pipeline_project(draft_id, proj)

    return step8_render_final_drama(draft_id, subtitle_enabled=subtitle_enabled)


