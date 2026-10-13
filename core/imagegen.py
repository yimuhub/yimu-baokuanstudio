"""AI 生图与智能排版配图引擎：多通道生图（支持各大供应商生图模型） + 电影级 Pillow 美学信息插图 100% 保底 + 正文自动插图回填。
"""
import base64
import json
import os
import re
from pathlib import Path

import httpx

from core.agents import model_for
from core.llm import load_config, load_env

# ═══════════════════════════════════════════════════════════════════════
# v5.302 升级版：多风格视觉 Prompt 系统（借鉴 Easel card-design 理念）
# ═══════════════════════════════════════════════════════════════════════

# ---------- 通用反 AI 塑料感尾缀 ----------
HYPER_REAL_PHOTO_SUFFIX = (
    ", crystal clear photography, shot on Hasselblad X2D 100C with 50mm lens, "
    "ultra-sharp razor focus, vivid vibrant saturated colors, pristine bright natural daylight, "
    "realistic immaculate environment textures, brilliant clarity across entire frame, "
    "8k ultra-high resolution, vibrant saturation, rich crisp contrast, "
    "no smoke, no fog, no mist, no haze, no blurry blur, no dim lighting, no washed out pale colors, "
    "no grain, no noise, no CGI, no 3D render, no plastic skin, no text, no watermark, sharp focus"
)
STYLE_SUFFIX = HYPER_REAL_PHOTO_SUFFIX  # 兼容旧引用

# ---------- 十大视觉风格体系（深度融合清晰艳丽指令、紧扣现实内容与零烟雾参数）----------
VISUAL_STYLE_PRESETS = {
    # 1. 纪实摄影（人物/生活/情感类内容）
    "documentary": {
        "name": "纪实摄影·生活烟火",
        "tag": "Crystal Clear Documentary Photography",
        "keywords": ["生活", "情感", "人物", "日常", "故事", "美食", "旅行", "亲子", "健康", "运动"],
        "style_directive": "crystal clear authentic snapshot, vivid vibrant natural colors, bright clean natural daylight illumination, razor-sharp focus on realistic living details, authentic unposed real-life scene, Hasselblad X2D 100C 50mm",
        "suffix": (
            ", crystal clear authentic moment, shot on Hasselblad X2D 100C with 50mm lens, "
            "razor-sharp focus, vivid vibrant natural colors, bright clean natural illumination, "
            "realistic authentic environment textures, high clarity, rich contrast, "
            "8k photorealistic, no smoke, no fog, no mist, no haze, no blur, no grain, "
            "no CGI, no plastic skin, no stock photo cliche, no text, no watermark"
        ),
        "system_prompt": (
            "你是普利策奖纪实摄影师兼国家地理图片总监。将用户主题转化为极度清晰、生动鲜活的真实生活抓拍英文 Prompt。"
            "铁律：①必须晶莹清晰、纤毫毕现，严禁任何烟雾感、薄雾或模糊；②色彩必须饱满鲜艳真实；"
            "③紧扣文章真实客观的生活或工作场景，细节具体。只输出英文 Prompt，不要解释。"
        ),
    },
    # 2. 瑞士极简（商业/知识/效率类内容）
    "swiss_minimal": {
        "name": "瑞士极简·商业质感",
        "tag": "Crystal Clear Swiss Minimalism Commercial",
        "keywords": ["商业", "职场", "效率", "管理", "职业", "简历", "成功", "财富", "理财", "投资", "创业", "办公"],
        "style_directive": "crystal clear Swiss commercial aesthetic, clean modern negative space, razor-sharp geometric precision, vivid bold accent colors, bright clean studio lighting, Phase One IQ4 150MP 85mm",
        "suffix": (
            ", Swiss International commercial style, crystal clear crisp focus, "
            "razor-sharp geometric lines, vivid punchy accent colors, clean bright studio illumination, "
            "shot on Phase One IQ4 150MP with 85mm lens, pristine optical clarity across entire frame, "
            "high-end commercial photography, 8k ultra-sharp, no smoke, no fog, no mist, no haze, no blur, no text, no watermark"
        ),
        "system_prompt": (
            "你是顶级商业摄影总监兼设计顾问。将用户主题转化为极致清晰通透的高端商业摄影英文 Prompt。"
            "铁律：①全画幅极度锐利，绝对零烟雾、零模糊；②鲜明有力的对比与艳丽点缀色；"
            "③真实客观的现代办公与商业场景。只输出英文 Prompt，不要解释。"
        ),
    },
    # 3. 杂志编辑（时尚/美妆/生活方式类内容）
    "magazine_editorial": {
        "name": "杂志编辑·高端生活方式",
        "tag": "Crystal Clear High Fashion Editorial",
        "keywords": ["时尚", "美妆", "美容", "护肤", "穿搭", "风格", "潮流", "设计", "艺术", "创意", "家居", "装修"],
        "style_directive": "crystal clear high-fashion magazine editorial, vivid vibrant saturated colors, dramatic crisp directional lighting, razor-sharp focus on subject and couture styling, Canon EOS R5 85mm f/1.2L",
        "suffix": (
            ", Vogue/Harper's Bazaar high fashion editorial style, crystal clear, ultra-sharp focus, "
            "vivid rich saturated colors, crisp directional lighting, shot on Canon EOS R5 with 85mm f/1.2L lens, "
            "pristine glossy texture, punchy contrast, 8k ultra-detailed, "
            "no smoke, no fog, no mist, no haze, no blur, no dull colors, no text, no watermark"
        ),
        "system_prompt": (
            "你是顶级时尚杂志《Vogue》图片总监。将用户主题转化为清晰艳丽的时尚大片英文 Prompt。"
            "铁律：①光线明亮透彻，色彩浓郁饱和艳丽；②超清焦段与高质感细节，严禁烟雾朦胧；"
            "③紧扣文章内容设计造型与环境。只输出英文 Prompt，不要解释。"
        ),
    },
    # 4. 科技赛博（AI/数字/未来/技术类内容）
    "tech_cyber": {
        "name": "科技赛博·数字未来感",
        "tag": "Crystal Clear Futuristic Tech Realism",
        "keywords": ["科技", "AI", "人工智能", "数字", "互联网", "编程", "代码", "数据", "算法", "区块链", "元宇宙", "芯片", "半导体", "机器人"],
        "style_directive": "crystal clear futuristic high-tech reality, vivid electric cyan and magenta colors, razor-sharp glowing digital HUD interfaces and circuitry, bright clean tech laboratory, Sony A1 24mm f/1.4 GM",
        "suffix": (
            ", crystal clear futuristic tech realism, vivid electric cyan and purple colors, "
            "razor-sharp focus on glowing digital displays and clean modern hardware, "
            "shot on Sony A1 with 24mm f/1.4 GM lens, crisp high dynamic range, "
            "8k photorealistic rendering, immaculate clarity, "
            "no smoke, no fog, no mist, no haze, no blurry glow, no cartoon, no 3D render plastic, no text, no watermark"
        ),
        "system_prompt": (
            "你是前沿科技视觉总监。将用户主题转化为极致清晰透亮的现代科技感摄影英文 Prompt。"
            "铁律：①高亮清晰透彻，绝对不要烟雾弥漫与脏乱阴暗；②电子蓝、青、紫等艳丽光轨与屏幕；"
            "③紧密贴合文章所讲的具体技术、代码、硬件或数字应用。只输出英文 Prompt，不要解释。"
        ),
    },
    # 5. 古风雅韵（传统古风/汉服/仙侠/国风/历史文化）
    "ancient_chinese": {
        "name": "古风雅韵·东方意境",
        "tag": "Crystal Clear Traditional Chinese Oriental Aesthetics",
        "keywords": ["古风", "国风", "东方", "传统", "文化", "历史", "国学", "茶道", "书法", "汉服", "古建", "仙侠", "非遗", "民俗", "亭台楼阁", "诗意"],
        "style_directive": "crystal clear traditional Chinese elegance, vivid vermilion and cyan jade palette, bright clean natural daylight illumination, razor-sharp Hanfu silk embroidery and classical woodwork, Leica SL2 50mm f/1.4",
        "suffix": (
            ", crystal clear traditional Chinese classical scene, vivid vermilion red and jade cyan colors, "
            "bright clean natural daylight, razor-sharp textures of silk embroidery and carved architecture, "
            "shot on Leica SL2 with 50mm f/1.4 lens, pristine optical clarity across entire frame, "
            "rich vibrant palette, 8k photorealistic, no smoke, no fog, no mist, no haze, no blur, no text, no watermark"
        ),
        "system_prompt": (
            "你是顶级东方美学摄影师兼影视视觉总监。将用户主题转化为清晰生动、色彩典雅鲜明的中国古风摄影英文 Prompt。"
            "铁律：①坚决去除烟雾感与浓雾，光线明朗透亮，庭院与服饰纤毫毕现；②朱红、青绿等中国传统色彩艳丽饱和；"
            "③紧扣文章历史与文化内容。只输出英文 Prompt，不要解释。"
        ),
    },
    # 兼容历史别名
    "chinese_ink": {
        "name": "古风雅韵·东方意境",
        "tag": "Crystal Clear Traditional Chinese Oriental Aesthetics",
        "keywords": ["传统", "文化", "历史", "国学", "茶道", "书法", "汉服", "古建", "非遗", "民俗", "中医", "国潮", "东方"],
        "style_directive": "crystal clear contemporary Chinese aesthetic, vivid vermilion and deep ink contrasts, bright crisp daylight, razor-sharp architectural lines, Leica M11",
        "suffix": (
            ", crystal clear contemporary Chinese aesthetic, vivid vermilion and ink contrast, "
            "bright clean daylight, shot on Leica M11 with 35mm lens, razor-sharp focus, "
            "pristine clarity, rich vibrant traditional colors, 8k resolution, "
            "no smoke, no fog, no mist, no haze, no blur, no text, no watermark"
        ),
        "system_prompt": (
            "你是新中式美学摄影师。将用户主题转化为清晰明亮、色彩生动的东方美学摄影英文 Prompt。"
            "铁律：透亮清晰，零烟雾感，色彩鲜明。只输出英文 Prompt，不要解释。"
        ),
    },
    # 6. 城市风/都市风（都会天际线/现代街道/车水马龙/摩天大楼/城市街拍）
    "city_urban": {
        "name": "城市风·现代都市摩天",
        "tag": "Crystal Clear Urban Metropolis Skyline",
        "keywords": ["城市", "都市", "都会", "街头", "街拍", "天际线", "摩天大楼", "建筑", "街道", "车水马龙", "夜景", "步行街", "CBD", "地铁"],
        "style_directive": "crystal clear modern urban metropolis, brilliant vivid blue sky, golden sunlight reflecting off soaring glass skyscrapers, razor-sharp architectural lines, vibrant bustling streets, Sony A7R V 35mm f/1.4 GM",
        "suffix": (
            ", crystal clear modern urban metropolis, dramatic clear city skyline, "
            "shot on Sony A7R V with 35mm f/1.4 GM lens, golden sunlight reflecting off glass skyscrapers, "
            "vibrant metropolitan street colors, realistic asphalt and modern architecture, "
            "crisp urban edge definition, pristine clean air, 8k ultra-sharp, "
            "no smog, no smoke, no fog, no mist, no haze, no blur, no CGI cartoon, no text, no watermark"
        ),
        "system_prompt": (
            "你是全球顶尖城市与建筑摄影总监。将用户主题转化为极致通透清晰、色彩鲜明的繁华现代都市摄影英文 Prompt。"
            "铁律：①空气清澈通透，严禁雾霾、烟雾与朦胧感；②摩天楼玻璃反射与街道色彩饱满艳丽；"
            "③紧密结合文章现实商业与都市场景。只输出英文 Prompt，不要解释。"
        ),
    },
    # 7. 电影光影（戏剧大片/宽银幕质感）
    "cinematic_movie": {
        "name": "影视大片·电影光影",
        "tag": "Crystal Clear Cinematic Blockbuster Still",
        "keywords": ["电影", "影视", "大片", "戏剧", "故事", "光影", "镜头", "叙事", "情绪", "氛围"],
        "style_directive": "crystal clear cinematic widescreen blockbuster still, vivid saturated color grading, bright high-contrast visual storytelling, razor-sharp focus on actors and environment, ARRI Alexa 65 optical clarity",
        "suffix": (
            ", crystal clear cinematic movie still, 35mm anamorphic widescreen lens, "
            "vivid rich saturated color grading, crisp directional spotlighting, razor-sharp focus on subject, "
            "high dynamic range, pristine optics, 8k resolution, award-winning cinematography, "
            "no smoke, no fog, no mist, no haze, no grain, no blur, no text, no watermark"
        ),
        "system_prompt": (
            "你是奥斯卡最佳摄影奖电影摄影师。将用户主题转化为通透清晰、色彩极具张力的电影大片剧照英文 Prompt。"
            "铁律：①全画幅超清锐利，坚决杜绝烟雾感与朦胧发灰；②浓郁艳丽的电影调色与清晰光影；"
            "③与文章实际剧情或论点紧密锚定。只输出英文 Prompt，不要解释。"
        ),
    },
    # 8. 高端商业广告（产品/品牌/营销类内容）
    "commercial_premium": {
        "name": "高端商业·品牌广告",
        "tag": "Crystal Clear Luxury Commercial Brand Advertising",
        "keywords": ["产品", "品牌", "营销", "广告", "推广", "电商", "销售", "促销", "新品", "发布", "种草"],
        "style_directive": "crystal clear luxury commercial photography, vivid vibrant colors, hyper-sharp focus stacking, brilliant bright studio lighting, Phase One XF IQ4 150MP, pristine brand visual clarity",
        "suffix": (
            ", crystal clear luxury product and lifestyle photography, hyper-precise focus, "
            "brilliant clean studio strobe lighting, shot on Phase One XF IQ4 150MP, "
            "vivid punchy colors, hyper-detailed textures, Apple/Nike tier immaculate visual quality, "
            "8k ultra-high resolution, razor-sharp, no smoke, no fog, no mist, no haze, no blur, no text overlay, no watermark"
        ),
        "system_prompt": (
            "你是苹果/顶级品牌广告摄影总监。将用户主题转化为清澈通透、色彩纯正艳丽的商业广告摄影英文 Prompt。"
            "铁律：①极高清晰度与纯净背景，零烟雾感、零模糊；②鲜艳饱和的品牌质感；"
            "③紧扣文章产品、业务或品牌主题。只输出英文 Prompt，不要解释。"
        ),
    },
    # 9. 新海诚系·治愈电影（治愈/动漫/风景/情感/青春）
    "anime_cinematic": {
        "name": "治愈动漫·新海诚光影",
        "tag": "Crystal Clear Makoto Shinkai Cinematic Anime",
        "keywords": ["动漫", "二次元", "治愈", "新海诚", "唯美", "青春", "黄昏", "天空", "夏天", "晚霞", "樱花", "风景", "电影感动漫"],
        "style_directive": "crystal clear Makoto Shinkai anime animation, vivid saturated azure blue sky, luminous crystalline cumulus clouds, sparkling water reflections, highly detailed nostalgic background art, Kyoto Animation masterpiece",
        "suffix": (
            ", crystal clear Makoto Shinkai anime animation style, Kyoto Animation masterpiece, "
            "vibrant azure sky, brilliant colorful clouds, sparkling crisp reflections, "
            "hyper-detailed background anime art, 8k wallpaper illustration, rich vibrant color saturation, "
            "crisp line definition, no smoke, no fog, no mist, no haze, no blur, no 3D render plastic, no lowres, no text, no watermark"
        ),
        "system_prompt": (
            "你是新海诚与京阿尼的主美。将用户主题转化为澄澈通透、色彩极其艳丽纯净的动漫电影剧照 Prompt。"
            "铁律：①天空与环境纯净透亮，严禁发灰发暗的烟雾；②蔚蓝、明橙、粉紫等色彩艳丽饱满；"
            "③紧扣文章意境与真实故事。只输出英文 Prompt，不要解释。"
        ),
    },
    # 10. 极简三维·轻拟物艺术（3D图标/轻拟物/前沿概念/科技设计）
    "minimalist_3d": {
        "name": "极简三维·轻拟物艺术",
        "tag": "Crystal Clear Modern Claymorphism 3D & Isometric Art",
        "keywords": ["3D", "三维", "拟物", "立体", "轻拟物", "粘土", "盲盒", "C4D", "Blender", "图标", "概念", "极简3D", "设计"],
        "style_directive": "crystal clear minimalist claymorphism 3D art, vivid vibrant pop and pastel color palette, razor-sharp smooth geometry, bright clean studio global illumination, Apple keynote 3D infographic, Octane Render 8k",
        "suffix": (
            ", crystal clear modern claymorphism 3D style, razor-sharp smooth geometry, "
            "bright clean studio lighting, vivid vibrant pop and pastel colors, "
            "Apple Keynote 3D illustration aesthetic, Octane Render 8k, crisp reflections, "
            "no smoke, no fog, no mist, no haze, no noise, no blur, no text, no watermark"
        ),
        "system_prompt": (
            "你是苹果设计团队顶级 3D 视觉总监。将用户主题转化为清晰生动、色彩鲜明的三维艺术 Prompt。"
            "铁律：通透清爽，色彩艳丽，无烟雾无杂质。只输出英文 Prompt，不要解释。"
        ),
    },
}

# 默认风格
DEFAULT_VISUAL_STYLE = "documentary"


def _detect_visual_style(text: str) -> str:
    """根据主题文本自动匹配最合适的视觉风格（借鉴 Easel 的内容类型→风格映射机制）。"""
    text_lower = text.lower()
    best_style = DEFAULT_VISUAL_STYLE
    best_score = 0
    for style_key, preset in VISUAL_STYLE_PRESETS.items():
        score = sum(1 for kw in preset["keywords"] if kw in text_lower or kw in text)
        if score > best_score:
            best_score = score
            best_style = style_key
    return best_style


def build_style_enhanced_prompt(raw_text: str, context: str = "", force_style: str | None = None) -> str:
    """极速且高阶的风格强化提示词引擎：
    将文章主题与段落具象化，并把用户选定的风格体系（古风、科技风、都市风等）的核心视觉指令、
    光影镜头、美学特征显式注入到发给 AI 生图模型的提示词中，杜绝风格丢失与虚假生成。
    """
    raw_s = (raw_text or "").strip()
    combined = f"{raw_s} {context or ''}".strip()
    style_key = force_style if (force_style and force_style in VISUAL_STYLE_PRESETS) else _detect_visual_style(combined)
    preset = VISUAL_STYLE_PRESETS.get(style_key, VISUAL_STYLE_PRESETS["documentary"])

    style_header = f"[{preset['name']} / Visual Style: {preset.get('tag', preset['name'])}]"
    directive = preset.get("style_directive", "")
    suffix = preset.get("suffix", HYPER_REAL_PHOTO_SUFFIX)

    # 如果 raw_s 已经包含了完整的 style_header，直接补充必要尾缀返回
    if style_header in raw_s:
        return raw_s if "no text" in raw_s else (raw_s + suffix)

    # 提取/拼装场景英文
    scene_core = ""
    if not bool(re.search(r"[\u4e00-\u9fa5]", raw_s)) and len(raw_s.split()) >= 8:
        scene_core = raw_s
    else:
        # 使用规则引擎快速合成具象摄影场景（0毫秒延时，绝不因外部大模型超时阻塞）
        try:
            from core.short_drama import _synthesize_scene_prompt
            scene_core = _synthesize_scene_prompt(
                raw_s, context or raw_s,
                "Crystal Clear Shot", "Brilliant Clean Natural Lighting", "Steady Framing"
            )
        except Exception:
            scene_core = f"Crystal clear realistic scene of {raw_s[:80]}, vivid colors, razor-sharp composition, no haze, no smoke"

    # 融合风格指令到 AI 提示词（确保风格核心词排在提示词最前列，强力指导生图大模型）
    final_prompt = f"{style_header}, {scene_core}, {directive}{suffix}"
    return final_prompt


def photojournalism_prompt_engine(raw_text: str, context: str = "",
                                  force_style: str | None = None) -> str:
    """提示词引擎：将内容与用户指定的多美学风格深度绑定，把风格特征显式添加到 AI 提示词中。"""
    return build_style_enhanced_prompt(raw_text, context=context, force_style=force_style)


# 全文通读 ➔ 极致清晰分镜头解构 ➔ 艳丽色彩与现实内容 1:1 锚定（V9.0.0 晶莹通透无烟雾版）
ARTICLE_VISUAL_DIGEST_PROMPT = """你是一名顶级商业视觉总监兼现代电影摄影大师，以【画质极致通透、纤毫毕现、色彩艳丽鲜活】享誉业界。

【系统核心铁律（必须 100% 贯彻执行）】：
1. 【极致清晰通透铁律（最高优先级）】：
   - 严禁任何烟雾感、浓雾、薄雾、朦胧遮罩、雾气氤氲或过度大面积虚焦模糊！
   - 画面光线必须像纯净晴朗日光或清亮专业棚拍一样通透无瑕；
   - 提示词必须显式使用【crystal clear, ultra-sharp focus, razor-sharp details, pristine optical clarity, immaculate focus across entire frame】；
   - 强制加入反烟雾负向词：【no smoke, no fog, no mist, no haze, no blurry blur, no dim lighting, no washed out pale colors】。
2. 【鲜明艳丽色彩铁律】：
   - 严禁灰暗、泛白、死气沉沉或陈旧褪色的低饱和度色调；
   - 必须使用【vivid vibrant saturated colors, rich punchy contrast, brilliant luminous highlights】，让画面的色彩饱满、鲜亮、充满视觉冲击力。
3. 【图文匹配度 >= 95% 紧扣文章现实客观内容】：
   - 画面必须严格根据文章当前的具体现实题材生成（例如文章写 AI 编程，就展现明亮清爽的现代工位、超清双屏代码与科技工具；文章写副业搞钱，就展现具体落地的工作台、电脑账目、现代都市人；文章写职场管理，就展现高采光会议室里清晰自信的团队；文章写健康美食，就展现鲜艳诱人的食材特写与明快厨房）；
   - 严禁脱离文章实际内容的虚无缥缈概念或空洞无物的大片烟雾！
4. 【先通读全文后生图 ➔ 影视短剧分镜视听语言】：
   - 必须先通读全文后生图，深刻理解文章的中心思想与每个小节的具象论述；
   - 【封面大图】：必须设计为电影级“全景建立镜头 (Wide Establishing Hero Shot)”，确立全篇清晰鲜活的现实世界观；
   - 【各段落配图】：必须设计为影视短剧分镜“具象叙事镜头 (Story Beat Shots)”，展现中景人物动作、真实器物道具或关键场景，严禁空泛摆拍！
5. 【高端现代化审美标准】：
   - 必须包含专业高端摄影机（如 Hasselblad X2D 100C, Sony A7R V, Canon EOS R5 等）；
   - 强制附带反 AI 感负向词：【no CGI, no cartoon, no 3D render plastic, no plastic skin, no extra fingers, no text, no watermark】。

【十大多美学风格体系（均已全面升级为零烟雾、极致清晰、色彩艳丽）】：
- documentary: 纪实摄影·生活烟火（哈苏相机，纯净自然光，饱满生活色彩，纤毫毕现）
- swiss_minimal: 瑞士极简·现代商务（Phase One 150MP，几何构图，鲜明强调色，清爽办公）
- magazine_editorial: 杂志编辑·高端大片（Canon R5 85mm，明亮立体光，浓郁高级艳丽调色）
- tech_cyber: 科技赛博·数字未来（Sony A1 24mm，高亮蓝紫电光，清晰数字终端，现代实验室）
- ancient_chinese: 古风雅韵·东方意境（Leica SL2，纯净明朗日光，朱红黛绿典雅艳丽，精美丝绣建筑细节）
- city_urban: 城市风·现代都市摩天（Sony A7R V，湛蓝天空，摩天楼明亮倒影，繁华街景鲜亮通透）
- cinematic_movie: 影视大片·电影光影（ARRI Alexa 65，高清晰度，浓郁艳丽电影色，戏剧张力）
- commercial_premium: 高端商业·品牌广告（Phase One 150MP，苹果级纯净透彻质感，鲜艳商品细节）
- anime_cinematic: 治愈动漫·新海诚光影（极清蔚蓝晴空，澄澈水波，鲜艳积雨云，纯净动漫美学）
- minimalist_3d: 极简三维·轻拟物艺术（现代粘土拟物，亮丽马卡龙色彩，清澈工作室全局光）

【输出格式（严格纯 JSON，禁止任何 markdown 标记或解释说明）】：
{
  "theme_vibe": "文章整体视觉世界观与调性总结（如：现代科技创新·明亮双屏工作台与鲜活色彩）",
  "visual_style": "上述10种风格key之一",
  "storyboard_summary": "全文视听分镜节奏规划简述",
  "cover_prompt": {
    "shot_type": "Wide Establishing Shot",
    "zh": "封面具象场景分镜描述：建立清晰明朗的现实场景、明确主体动作、鲜亮色彩、清澈光线",
    "en": "Crystal clear wide establishing shot of [specific realistic details directly from text], razor-sharp focus, vivid vibrant saturated colors, pristine natural daylight illumination, shot on Hasselblad X2D 100C, 8k resolution, ultra-detailed, no smoke, no fog, no mist, no haze, no blur, no text, no watermark"
  },
  "sections_prompts": [
    {
      "section_title": "小节标题",
      "shot_type": "Medium Narrative Shot / Close-up Detail Shot",
      "zh": "该小节影视分镜场景：与本节文本要点严格1:1锚定的具体主体、动作、环境道具，清晰通透，色彩艳丽",
      "en": "Crystal clear shot of [specific narrative beat strictly aligned with the section text], ultra-sharp focus, razor-sharp details, vivid saturated vibrant colors, bright crisp lighting, shot on Sony A7R V, 8k resolution, no smoke, no fog, no mist, no haze, no blur, no text, no watermark"
    }
  ]
}
"""

ANGLES = [
    "环境全景建立镜头",
    "人物动作与情绪特写",
    "关键道具与细节微距",
    "侧逆光生活场景",
    "俯拍纪实视角",
    "广角环境空间感",
]



def analyze_article_visual_prompts(title: str, body_md: str, sections: list, force_style: str | None = None) -> dict:
    """第一阶段：AI 通读整篇文章，提炼全文核心视觉基调与各小节视觉要点，并生成结构化提示词表。
    支持自动匹配或指定专属配图风格（古风、科技风、都市风、商务风等）。
    """
    from core import agents, llm

    clean_body = body_md[:3500] if body_md else title
    sec_names = [sec[0] if isinstance(sec, (list, tuple)) else str(sec) for sec in sections]
    
    # 确定目标风格
    chosen_style = force_style if (force_style and force_style in VISUAL_STYLE_PRESETS) else _detect_visual_style(f"{title} {clean_body[:400]}")
    auto_style_key = chosen_style
    auto_preset = VISUAL_STYLE_PRESETS[chosen_style]
    
    style_req = f"\n\n【用户指定视觉风格】：必须严格采用【{auto_preset['name']}】风格（代码 key: {chosen_style}），所有 Prompt 必须完美体现该风格意境与光效参数！" if force_style else ""

    user_content = (
        f"【文章标题】：{title}\n\n"
        f"【需要配图的小节列表】：{json.dumps(sec_names, ensure_ascii=False)}\n\n"
        f"【文章全文内容】：\n{clean_body}"
        f"{style_req}"
    )

    prompts_data = None
    try:
        # 提示词提炼是核心长文推理任务，必须使用文本语言模型，绝不能调用生图模型！
        raw = agents.chat_for("write", [
            {"role": "system", "content": ARTICLE_VISUAL_DIGEST_PROMPT},
            {"role": "user", "content": user_content}
        ], temperature=0.65, timeout_s=60)

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            prompts_data = json.loads(m.group(0))
    except Exception as e:
        import traceback
        traceback.print_exc()

    if not prompts_data or not isinstance(prompts_data, dict):
        # 降级：使用智能实体提取器与高保真 2K 摄影光学保底，并应用自动检测的风格尾缀
        try:
            from core.short_drama import _synthesize_scene_prompt
            cover_en = (
                _synthesize_scene_prompt(title, title, "Wide Establishing Shot", "Brilliant Clear Daylight", "Slow Dolly In")
                + ", crystal clear, ultra-sharp focus, vivid vibrant colors, 8k ultra hd, Hasselblad X2D 100C look, masterpiece"
                + auto_preset["suffix"]
            )
        except Exception:
            cover_en = f"Crystal clear wide establishing shot of {title[:60]}, razor-sharp focus, vivid vibrant colors, bright natural daylight, shot on Hasselblad X2D 100C, photorealistic, 8k ultra hd, no smoke, no fog, no mist, no haze, no blur" + auto_preset["suffix"]
        cover_zh = f"《{title[:20]}》现实核心场景：清晰通透，色彩鲜明"

        sec_prompts = []
        for i, sec in enumerate(sections):
            t, ctx = (sec if isinstance(sec, (list, tuple)) else (sec, ""))
            try:
                from core.short_drama import _synthesize_scene_prompt
                p_en = (
                    _synthesize_scene_prompt(title, ctx or t, "Medium Shot", "Brilliant Clear Directional Illumination", "Push In")
                    + ", crystal clear, razor-sharp focus, vivid vibrant colors, 8k ultra hd, Sony A7R V look"
                    + auto_preset["suffix"]
                )
            except Exception:
                p_en = f"Crystal clear medium narrative shot of {t[:50]}, {ctx[:50] if ctx else ''}, razor-sharp focus, vivid saturated vibrant colors, bright lighting, shot on Canon EOS R5 85mm f/1.2L, 8k ultra hd, no smoke, no fog, no mist, no haze, no blur" + auto_preset["suffix"]
            sec_prompts.append({
                "section_title": t,
                "zh": f"小节【{t[:15]}】核心场景：{ctx[:30] if ctx else t}",
                "en": p_en
            })
        prompts_data = {
            "theme_vibe": auto_preset["name"],
            "visual_style": auto_style_key,
            "cover_prompt": {"zh": cover_zh, "en": cover_en},
            "sections_prompts": sec_prompts
        }
    else:
        # LLM 成功生成：若未包含 visual_style 字段，补充自动检测的值
        if "visual_style" not in prompts_data:
            prompts_data["visual_style"] = auto_style_key

    return prompts_data



def build_prompt(title: str, context: str, angle: str) -> str:
    """兼容旧调用：用文本模型把上下文转写成绘画提示词。"""
    from core import agents, llm
    base = (f"文章标题：{title}\n上下文：{context[:200]}\n\n"
            f"补充要求：这张图采用「{angle}」视角。")
    try:
        msgs = [{"role": "system", "content": "请写一句中文绘画提示词，包含主体、环境、动作与光线。"},
                {"role": "user", "content": base}]
        raw = llm.chat(msgs, temperature=0.5)
        txt = raw.strip().strip('"').splitlines()[0][:120]
        if len(txt) >= 8:
            return f"{txt}，{angle}"
    except Exception:
        pass
    return f"主题：{title}，内容：{context[:60]}，{angle}"



def image_cfg() -> dict:
    raw_cfg = load_config()
    cfg = raw_cfg.get("image", {})
    # 优先采用 agent_routing.image 或 agents.image.model 路由绑定的生图模型
    routing_img = raw_cfg.get("gateway", {}).get("agent_routing", {}).get("image", "").strip()
    agent_img = raw_cfg.get("agents", {}).get("image", {}).get("model", "").strip()
    model = routing_img or agent_img or cfg.get("model", "flux-schnell")
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "model": model,
        "count": max(1, min(int(cfg.get("count", 3)), 5)),
        "card_bg": bool(cfg.get("card_bg", False))
    }


def _render_fallback_card(title: str, subtext: str, out_path: Path, angle_idx: int = 0, is_cover: bool = False) -> bool:
    """当外部 API 无法出图时，使用 Pillow 渲染一张工业级出版质感的信息美学插图/封面，100% 稳定出图。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        w, h = 2048, 1152

        palettes = [
            {"bg": (20, 28, 45), "accent": (56, 139, 253), "tag": "VISION ● 核心视点"},
            {"bg": (38, 24, 18), "accent": (240, 136, 62), "tag": "INSIGHT ● 深度洞察"},
            {"bg": (18, 36, 28), "accent": (63, 185, 80), "tag": "ANALYSIS ● 逻辑剖析"},
            {"bg": (34, 20, 42), "accent": (163, 113, 247), "tag": "PERSPECTIVE ● 独家视角"},
            {"bg": (30, 30, 35), "accent": (210, 153, 34), "tag": "SUMMARY ● 关键金句"},
        ]
        p = palettes[angle_idx % len(palettes)]

        img = Image.new("RGB", (w, h), color=p["bg"])
        draw = ImageDraw.Draw(img)

        # 绘制网格
        for x in range(0, w, 90):
            draw.line([(x, 0), (x, h)], fill=(255, 255, 255, 12), width=1)
        for y in range(0, h, 90):
            draw.line([(0, y), (w, y)], fill=(255, 255, 255, 12), width=1)

        margin = 64
        draw.rectangle([(margin, margin), (w - margin, h - margin)], outline=(255, 255, 255, 30), width=3)
        draw.line([(margin, margin + 8), (margin + 120, margin + 8)], fill=p["accent"], width=6)

        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
        ]
        font_title, font_sub, font_tag = None, None, None
        for fp in font_paths:
            if Path(fp).exists():
                try:
                    font_title = ImageFont.truetype(fp, 80 if not is_cover else 92)
                    font_sub = ImageFont.truetype(fp, 46)
                    font_tag = ImageFont.truetype(fp, 36)
                    break
                except Exception:
                    pass

        tag_text = p["tag"] if not is_cover else "FEATURED ● 深度专题头图"
        draw.rectangle([(margin + 36, margin + 36), (margin + 36 + len(tag_text) * 13, margin + 72)],
                       fill=(255, 255, 255, 18))
        if font_tag:
            draw.text((margin + 46, margin + 42), tag_text, fill=p["accent"], font=font_tag)

        y = margin + 110
        title_clean = title.strip().replace("#", "").strip()
        title_lines = []
        cur_line = ""
        for char in title_clean:
            cur_line += char
            if len(cur_line) >= 18:
                title_lines.append(cur_line)
                cur_line = ""
        if cur_line:
            title_lines.append(cur_line)

        for tl in title_lines[:2]:
            if font_title:
                draw.text((margin + 36, y), tl, fill=(255, 255, 255), font=font_title)
            y += 56

        y += 10
        draw.line([(margin + 36, y), (margin + 180, y)], fill=p["accent"], width=3)
        y += 30

        sub_clean = subtext.strip().replace("###", "").strip()[:80]
        sub_lines = []
        cur_sub = ""
        for char in sub_clean:
            cur_sub += char
            if len(cur_sub) >= 28:
                sub_lines.append(cur_sub)
                cur_sub = ""
        if cur_sub:
            sub_lines.append(cur_sub)

        for sl in sub_lines[:3]:
            if font_sub:
                draw.text((margin + 36, y), f"“ {sl} ”" if sl == sub_lines[0] else f"  {sl}",
                          fill=(200, 210, 225), font=font_sub)
            y += 38

        foot_y = h - margin - 50
        draw.line([(margin + 36, foot_y), (w - margin - 36, foot_y)], fill=(255, 255, 255, 20), width=1)
        if font_tag:
            draw.text((margin + 36, foot_y + 16), "MEDIAFLOW · AI VISUAL EDITORIAL",
                      fill=(130, 140, 155), font=font_tag)
            draw.text((w - margin - 190, foot_y + 16), "PRO EDITORIAL",
                      fill=p["accent"], font=font_tag)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="PNG", quality=95)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
# 2K 超清影视级分辨率标准体系（2048px 宽屏 / 方图 / 竖图）
# ═══════════════════════════════════════════════════════════════════════
DEFAULT_IMAGE_SIZE = "2048x1152"  # 默认 2K 16:9 宽画幅（最适宜自媒体图文与排版大图）

SIZE_PRESETS_2K = {
    "16:9": "2048x1152",  # 2K 宽画幅文章横图
    "1:1": "2048x2048",   # 2K 方形精细图
    "4:3": "2048x1536",   # 2K 传统摄影画幅
    "3:4": "1536x2048",   # 2K 小红书/手机竖版卡片
    "9:16": "1152x2048",  # 2K 沉浸全屏竖图
}


def normalize_image_size(size: str | None) -> str:
    """针对上游生图模型（特别是 Agnes 商业模型）规范化尺寸参数。
    规则要求：
    1. 上游只接受 1K / 2K / 3K / 4K 或 WIDTHxHEIGHT（例如 2048x1152）；
    2. 禁止传画幅字符串（例如 16:9, 9:16 等会导致 400 报错）；
    3. 若传入画幅串，自动映射为对应 2K 标准分辨率（如 16:9 -> 2048x1152，9:16 -> 1152x2048）；
    4. 其它非标准值统一兜底为 DEFAULT_IMAGE_SIZE (2048x1152)。
    """
    if not size:
        return DEFAULT_IMAGE_SIZE
    s = str(size).strip()
    if s in SIZE_PRESETS_2K:
        return SIZE_PRESETS_2K[s]
    if s.upper() in ("1K", "2K", "3K", "4K"):
        return s.upper()
    import re
    if re.match(r"^\d{3,4}x\d{3,4}$", s, re.I):
        return s.lower()
    if ":" in s:
        # 画幅比映射，默认宽屏 2K
        return SIZE_PRESETS_2K.get(s, DEFAULT_IMAGE_SIZE)
    return DEFAULT_IMAGE_SIZE


def parse_dimensions(size: str) -> tuple[int, int]:
    """从尺寸字符串（如 2048x1152 或 2K）解析宽度和高度，默认保底 2K（2048x1152）。"""
    try:
        norm = normalize_image_size(size)
        if norm == "1K":
            return 1024, 1024
        elif norm == "2K":
            return 2048, 2048
        elif norm == "3K":
            return 3072, 3072
        elif norm == "4K":
            return 4096, 4096
        parts = norm.lower().split("x")
        if len(parts) == 2:
            w, h = int(parts[0]), int(parts[1])
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return 2048, 1152


def ensure_2k_resolution(out_path: Path | str, target_w: int = 2048, target_h: int = 1152) -> bool:
    """保障输出图像物理文件 100% 达到 2K 分辨率标准，并运用 Lanczos 重采样微调锐化消除锯齿。"""
    try:
        from PIL import Image, ImageEnhance
        out_path = Path(out_path)
        if not out_path.exists() or out_path.stat().st_size == 0:
            return False
        with Image.open(out_path) as im:
            cur_w, cur_h = im.size
            # 若任意一边未达 2K 门槛，进行专业级高保真超分增强
            if cur_w < target_w or cur_h < min(target_h, 1080):
                scale = max(target_w / cur_w, target_h / cur_h)
                new_w = max(target_w, int(cur_w * scale))
                new_h = max(target_h, int(cur_h * scale))
                upscaled = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
                # 微调微观对比度与质感锐化（消除普通缩放的模糊与假平滑）
                sharpener = ImageEnhance.Sharpness(upscaled)
                crisp_im = sharpener.enhance(1.15)
                crisp_im.save(out_path, format="PNG", optimize=True)
                return True
    except Exception as e:
        pass
    return False


def gen_image_pollinations(prompt: str, out_path: Path, width: int = 2048, height: int = 1152) -> bool:
    """通道 2：调用全球开源高质量 Pollinations Flux 真实文生图引擎（100% 真实摄影画质，免 API Key，默认 2K 超清）。"""
    import urllib.parse
    clean_prompt = prompt.strip()
    if not clean_prompt:
        clean_prompt = "cinematic movie still, photorealistic, 2k 4k 8k ultra high resolution, masterpiece, sharp focus"
    
    # 扩大有效字符长度，确保完整镜头光影与反塑料感提示词全量传输（避免截断破坏画质）
    encoded_p = urllib.parse.quote(clean_prompt[:1200])
    seed = abs(hash(clean_prompt)) % 100000
    target_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width={width}&height={height}&model=flux&nologo=true&seed={seed}"
    
    try:
        with httpx.Client(timeout=45, follow_redirects=True) as client:
            r = client.get(target_url)
            if r.status_code == 200 and len(r.content) > 2048:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(r.content)
                ensure_2k_resolution(out_path, target_w=width, target_h=height)
                return True
    except Exception:
        pass
    return False


# 模块级生图通道诊断：记录每张图实际走了哪条通道 + 商业通道失败原因。
# 供上层（生图结果 / 前端）暴露「高性能商业模型」还是「开源保底」，避免静默降级。
_GEN_DIAG: dict = {"channel": "none", "model": "", "provider": "", "commercial_error": ""}


def last_gen_diagnosis() -> dict:
    """返回最近一次 gen_image 的通道诊断（供 UI 展示"用的是高性能生图模型"而非保底）。"""
    return dict(_GEN_DIAG)


def _reset_gen_diagnosis(model: str = "", provider: str = "") -> None:
    _GEN_DIAG.update({"channel": "none", "model": model, "provider": provider, "commercial_error": ""})


def gen_image(prompt: str, out_path: Path, size: str = DEFAULT_IMAGE_SIZE, context_title: str = "", context_sub: str = "", angle_idx: int = 0, is_cover: bool = False, model: str = "", style: str = "") -> bool:
    """生成一张配图并存入 out_path（默认 2K 超清 2048x1152 分辨率）。
    智能多通道真实生图机制：
    1. 商业通道：若配置了支持生图的商业供应商（如 agnes-image、OpenAI dall-e-3、阿里 wanx-v1、智谱 cogview 或自建网关），调用 /images/generations（请求 quality=hd）；
    2. 全球开源保底通道：Pollinations Flux 真实文生图引擎，全国全网免 Key，100% 真实摄影画面；
    3. 极端断网保底：Pillow 美学信息卡片。
    生成的图片 100% 经过 ensure_2k_resolution 校验，物理分辨率绝对达到 2K 标准。
    """
    cfg = image_cfg()
    req_model = (model or "").strip() or cfg.get("model", "").strip() or "flux-schnell"
    raw_size = size or cfg.get("size", DEFAULT_IMAGE_SIZE) or DEFAULT_IMAGE_SIZE
    req_size = normalize_image_size(raw_size)

    # 全局通过视觉美学引擎注入多风格指令与光影参数（彻底去除 AI 塑料感与假人感）
    enhanced_prompt = photojournalism_prompt_engine(prompt, context=context_sub or context_title, force_style=style)

    from core.llm import resolve_llm_endpoint, classify_model
    base, key, resolved_model, pid = resolve_llm_endpoint(req_model)
    _reset_gen_diagnosis(resolved_model, pid)

    w, h = parse_dimensions(req_size)

    # 1. 尝试商业通道：仅在指定模型是图像模型且配置了有效 API Key 时调用 /images/generations
    if key and base and classify_model(resolved_model) == "image":
        candidate_urls = []
        if base.endswith("/images/generations"):
            candidate_urls.append(base)
        elif base.endswith("/v1"):
            candidate_urls.append(f"{base}/images/generations")
        else:
            candidate_urls.append(f"{base}/v1/images/generations")
            candidate_urls.append(f"{base}/images/generations")

        is_local = "127.0.0.1" in base or "localhost" in base
        is_agnes = "agnes" in resolved_model.lower() or pid == "yimu_official"
        commercial_ok = False
        for req_url in candidate_urls:
            try:
                with httpx.Client(timeout=65, trust_env=not is_local) as client:
                    # 针对 Agnes 与通用商业模型的规范请求：
                    # 1. n 严格为 1；
                    # 2. size 严格为合法的 WIDTHxHEIGHT 或 1K/2K/3K/4K（normalize_image_size 杜绝画幅串）；
                    # 3. 严格禁止向 Agnes 传 quality（否则直接 400）；
                    # 4. 只有明确为 OpenAI 原生 dall-e-3 时才携带 quality="hd"。
                    payload = {
                        "model": resolved_model,
                        "prompt": enhanced_prompt,
                        "n": 1,
                        "size": req_size,
                    }
                    if "dall-e-3" in resolved_model.lower():
                        payload["quality"] = "hd"

                    r = client.post(req_url, json=payload, headers={"Authorization": f"Bearer {key}"})

                    # 智能容错救生机制：若遭遇 400，自适应修复并重试
                    if r.status_code == 400:
                        # 救生步骤 1：若 payload 存在 quality，立即剥除 quality 重试
                        if "quality" in payload:
                            payload.pop("quality", None)
                            r = client.post(req_url, json=payload, headers={"Authorization": f"Bearer {key}"})

                        # 救生步骤 2：若仍为 400，自适应降级 size（对于 Agnes 模型尝试 "2K" 或标准方图 "1024x1024"）
                        if r.status_code == 400:
                            fallback_sizes = ["2K", "1024x1024", "1792x1024"] if is_agnes else ["1024x1024", "1792x1024"]
                            for f_size in fallback_sizes:
                                if payload.get("size") != f_size:
                                    payload["size"] = f_size
                                    r = client.post(req_url, json=payload, headers={"Authorization": f"Bearer {key}"})
                                    if r.status_code == 200:
                                        break

                    if r.status_code == 200:
                        res_json = r.json()
                        data_arr = res_json.get("data", [{}])
                        data = data_arr[0] if isinstance(data_arr, list) and data_arr else {}
                        b64 = data.get("b64_json") or data.get("image") or res_json.get("b64_json")
                        img_url = data.get("url") or data.get("image_url") or res_json.get("url")
                        
                        if b64:
                            out_path.parent.mkdir(parents=True, exist_ok=True)
                            out_path.write_bytes(base64.b64decode(b64))
                            commercial_ok = True
                            break
                        elif img_url:
                            dl_r = None
                            with httpx.Client(timeout=45, follow_redirects=True) as dl_client:
                                dl_r = dl_client.get(img_url)
                                if dl_r.status_code == 200 and len(dl_r.content) > 1024:
                                    out_path.parent.mkdir(parents=True, exist_ok=True)
                                    out_path.write_bytes(dl_r.content)
                                    commercial_ok = True
                                    break
                            status_code_str = getattr(dl_r, 'status_code', 'error')
                            _GEN_DIAG["commercial_error"] = f"生图端点返回的图片地址拉取失败（HTTP {status_code_str}）"
                        else:
                            _GEN_DIAG["commercial_error"] = f"生图端点返回 200 但无图片数据体（model={resolved_model}）"
                    else:
                        _GEN_DIAG["commercial_error"] = f"HTTP {r.status_code}: {r.text[:120]}"
                        print(f"[ImageGen] 商业生图通道 [{pid}] {req_url} 返回 {r.status_code}，将转开源保底通道")
            except Exception as e:
                _GEN_DIAG["commercial_error"] = f"{type(e).__name__}: {str(e)[:120]}"
                print(f"[ImageGen] 商业生图通道 [{pid}] {req_url} 调用异常: {e}，将转开源保底通道")
        if commercial_ok:
            _GEN_DIAG["channel"] = "commercial"
            ensure_2k_resolution(out_path, target_w=w, target_h=h)
            return True
    else:
        # 未进入商业通道（key 缺失 / 模型非 image 类）也要给出可观测原因
        if not key:
            _GEN_DIAG["commercial_error"] = f"供应商 [{pid}] 未配置有效 API Key（占位/空 Key）"
        elif classify_model(resolved_model) != "image":
            _GEN_DIAG["commercial_error"] = f"目标模型 [{resolved_model}] 不是生图模型"

    # 2. 尝试开源保底通道：Pollinations Flux 真实文生图引擎（免 Key、免配置、100% 真实可用，默认 2K 超清）
    if gen_image_pollinations(enhanced_prompt, out_path, width=w, height=h):
        _GEN_DIAG["channel"] = "pollinations"
        ensure_2k_resolution(out_path, target_w=w, target_h=h)
        return True

    # 3. 极端断网降级：美学卡片
    card_ok = _render_fallback_card(context_title or prompt[:30], context_sub or prompt, out_path, angle_idx, is_cover)
    if card_ok:
        ensure_2k_resolution(out_path, target_w=w, target_h=h)
    _GEN_DIAG["channel"] = "card" if card_ok else "none"
    return card_ok


def img_dir(draft_dir: Path) -> Path:
    d = draft_dir / "img"
    d.mkdir(parents=True, exist_ok=True)
    return d


def decorate_draft(draft_dir: Path, title: str, sections: list, body_md: str = "", count: int | None = None, style: str | None = None, force_regen: bool = False, model: str = "") -> dict:
    """按文章小节与结构批量生成全套配图（先全文通读提取视觉要点，再生成结构化提示词并出图）。
    支持指定配图风格（古风、科技风、城市风、商务极简等）与一键换图重绘。"""
    cfg = image_cfg()
    total = cfg["count"] if count is None else max(1, min(int(count), 5))
    made = {"cover": None, "sections": {}}
    d = img_dir(draft_dir)

    prompts_file = d / "prompts.json"
    if force_regen or style:
        # 一键更换风格：清理历史图片与提示词缓存
        if prompts_file.exists():
            try: prompts_file.unlink()
            except Exception: pass
        if (d / "cover.png").exists():
            try: (d / "cover.png").unlink()
            except Exception: pass
        for f in d.glob("sec-*.png"):
            try: f.unlink()
            except Exception: pass

    # 1. 深度通读全文并提取视觉提示词（按指定风格）
    prompts_data = None
    if prompts_file.exists():
        try:
            prompts_data = json.loads(prompts_file.read_text(encoding="utf-8"))
        except Exception:
            prompts_data = None
    if not prompts_data:
        prompts_data = analyze_article_visual_prompts(title, body_md, sections, force_style=style)
        try:
            prompts_file.write_text(json.dumps(prompts_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # 2. 封面图生成
    f_cover = d / "cover.png"
    if f_cover.exists() and f_cover.stat().st_size > 1024:
        made["cover"] = "img/cover.png"
    else:
        first_ctx = sections[0][1] if sections else title
        cover_en = prompts_data.get("cover_prompt", {}).get("en", "")
        cover_zh = prompts_data.get("cover_prompt", {}).get("zh", f"{title}。{first_ctx}")
        prompt_cover = cover_en or photojournalism_prompt_engine(f"{title}。{first_ctx}", context="封面大图", force_style=style)
        if gen_image(prompt_cover, f_cover, DEFAULT_IMAGE_SIZE, context_title=title, context_sub=cover_zh[:40], angle_idx=0, is_cover=True, model=model, style=style or ""):
            made["cover"] = "img/cover.png"

    # 3. 各小节配图生成
    rest = total - (1 if made["cover"] else 0)
    sec_prompts_list = prompts_data.get("sections_prompts", [])
    
    for i, sec in enumerate(sections[:rest]):
        t, ctx = (sec if isinstance(sec, (list, tuple)) else (sec, ""))
        f_sec = d / f"sec-{i}.png"
        if f_sec.exists() and f_sec.stat().st_size > 1024:
            made["sections"][t] = f"img/sec-{i}.png"
            continue

        angle_i = (i + 1) % len(ANGLES)
        sec_p = sec_prompts_list[i] if i < len(sec_prompts_list) else {}
        p_en = sec_p.get("en", "")
        p_zh = sec_p.get("zh", ctx or t)
        prompt_sec = p_en or photojournalism_prompt_engine(f"{t}。{ctx}", context=t, force_style=style)
        
        if gen_image(prompt_sec, f_sec, DEFAULT_IMAGE_SIZE, context_title=t, context_sub=p_zh[:40], angle_idx=angle_i, is_cover=False, model=model, style=style or ""):
            made["sections"][t] = f"img/sec-{i}.png"

    return made


def get_draft_images_detail(draft_id: str) -> dict:
    """获取草稿所有配图的详细元数据（包含图片URL、小节标题、中英文生成提示词）。"""
    from core import db
    ddir = db.draft_dir(draft_id)
    d = db.get_draft(draft_id)
    title = d["title"] if d else "未命名草稿"
    img_d = ddir / "img"
    
    prompts_data = {}
    if (img_d / "prompts.json").exists():
        try:
            prompts_data = json.loads((img_d / "prompts.json").read_text(encoding="utf-8"))
        except Exception:
            pass

    res = {
        "draft_id": draft_id,
        "title": title,
        "theme_vibe": prompts_data.get("theme_vibe", "写实摄影质感"),
        "cover": None,
        "sections": [],
        "custom": []
    }

    if not img_d.exists():
        return res

    # 1. 封面图元数据
    cov_file = img_d / "cover.png"
    cov_p = prompts_data.get("cover_prompt", {})
    cov_en = cov_p.get("en", "") or f"Cinematic wide shot of {title}, 35mm film, volumetric lighting, photorealistic, 2k 8k ultra hd"
    cov_zh = cov_p.get("zh", "") or f"《{title}》核心意象全景"
    
    res["cover"] = {
        "name": "cover",
        "title": "封面大图 (2K超清)",
        "exists": cov_file.exists(),
        "url": f"/img/{draft_id}/cover.png" if cov_file.exists() else "",
        "prompt_zh": cov_zh,
        "prompt_en": cov_en
    }

    # 2. 小节配图元数据
    sec_prompts_list = prompts_data.get("sections_prompts", [])
    secs = sorted(img_d.glob("sec-*.png"))
    for idx, s in enumerate(secs):
        sec_num = int(s.stem.replace("sec-", "")) if s.stem.replace("sec-", "").isdigit() else idx
        sec_p = sec_prompts_list[sec_num] if sec_num < len(sec_prompts_list) else {}
        sec_title = sec_p.get("section_title", f"小节 #{sec_num + 1}")
        sec_en = sec_p.get("en", "") or f"Cinematic medium shot of {sec_title}, dramatic lighting, photorealistic, 2k 8k ultra hd"
        sec_zh = sec_p.get("zh", "") or f"小节【{sec_title}】核心场景"
        
        res["sections"].append({
            "name": s.stem,
            "section_num": sec_num,
            "section_title": sec_title,
            "title": f"小节配图 #{sec_num + 1} (2K超清)",
            "exists": True,
            "url": f"/img/{draft_id}/{s.name}",
            "prompt_zh": sec_zh,
            "prompt_en": sec_en
        })

    # 3. 自定义配图元数据
    for c in sorted(img_d.glob("custom-*.png")):
        res["custom"].append({
            "name": c.stem,
            "title": "自定义插图 (2K超清)",
            "exists": True,
            "url": f"/img/{draft_id}/{c.name}",
            "prompt_zh": "",
            "prompt_en": ""
        })

    return res


def regenerate_draft_image(draft_id: str, name: str, prompt: str = "", title: str = "", aspect: str = "16:9") -> dict:
    """针对草稿中的单个图片（封面、某小节图、或自定义图）使用指定或微调的 Prompt 重新生成并同步刷新排版（默认 2K 超清）。"""
    from core import db, themes
    from adapters import toutiao as _tt, zhihu as _zh, weibo as _wb
    from core.layouter import _inject_cover

    d = db.get_draft(draft_id)
    if not d:
        raise ValueError(f"草稿不存在: {draft_id}")
    ddir = db.draft_dir(draft_id)
    d_img = img_dir(ddir)
    
    # 尺寸解析：默认全线采用 2K 影视级矩阵标准
    size = SIZE_PRESETS_2K.get(aspect, DEFAULT_IMAGE_SIZE)

    # 确定目标文件路径
    is_cover = (name == "cover")
    if is_cover:
        out_file = d_img / "cover.png"
    elif name.startswith("sec-"):
        out_file = d_img / f"{name}.png"
    elif name.startswith("custom-"):
        out_file = d_img / f"{name}.png"
    else:
        existing = list(d_img.glob("custom-*.png"))
        out_file = d_img / f"custom-{len(existing)}.png"
        name = out_file.stem

    clean_prompt = prompt.strip() or f"{d['title']}。{title or '核心看点'}"
    gen_image(clean_prompt, out_file, size=size, context_title=title or d["title"], context_sub=clean_prompt[:40], angle_idx=0, is_cover=is_cover)

    # 更新 prompts.json
    prompts_file = d_img / "prompts.json"
    prompts_data = {}
    if prompts_file.exists():
        try:
            prompts_data = json.loads(prompts_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    
    if is_cover:
        if "cover_prompt" not in prompts_data:
            prompts_data["cover_prompt"] = {}
        prompts_data["cover_prompt"]["en"] = clean_prompt
    elif name.startswith("sec-"):
        try:
            sec_idx = int(name.replace("sec-", ""))
            sec_list = prompts_data.get("sections_prompts", [])
            while len(sec_list) <= sec_idx:
                sec_list.append({})
            sec_list[sec_idx]["en"] = clean_prompt
            if title:
                sec_list[sec_idx]["section_title"] = title
            prompts_data["sections_prompts"] = sec_list
        except Exception:
            pass
    
    try:
        prompts_file.write_text(json.dumps(prompts_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    # 重新编译五大平台排版预览
    body_md = d["body_md"]
    images_dict = {f.name: f"/img/{draft_id}/{f.name}" for f in sorted(d_img.glob("sec-*.png"))}
    cover_url = f"/img/{draft_id}/cover.png" if (d_img / "cover.png").exists() else None

    theme = load_config().get("creation", {}).get("wechat_theme", "caozhou")
    wx_html = themes.md_to_wechat_html(body_md, d["title"], theme=theme, images=images_dict)
    wx_html = _inject_cover(wx_html, cover_url)
    (ddir / "preview-wechat_mp.html").write_text(wx_html, encoding="utf-8")

    tt_html = _tt.render_preview(body_md, d["title"])
    (ddir / "preview-toutiao.html").write_text(tt_html, encoding="utf-8")

    zh_html = _zh.render_preview(body_md, d["title"])
    (ddir / "preview-zhihu.html").write_text(zh_html, encoding="utf-8")

    wb_html = _wb.render_preview(body_md, d["title"])
    (ddir / "preview-weibo.html").write_text(wb_html, encoding="utf-8")

    return {
        "ok": True,
        "name": name,
        "url": f"/img/{draft_id}/{out_file.name}?t={int(os.path.getmtime(out_file)) if out_file.exists() else 0}",
        "prompt": clean_prompt,
        "title": title,
        "image_channel": last_gen_diagnosis()
    }


def generate_single_image(draft_id: str, title: str, prompt: str = "") -> dict:
    """单独为草稿生成一张专属高清配图（支持大模型与美学卡片兜底）。"""
    return regenerate_draft_image(draft_id, name="new", prompt=prompt, title=title)


def get_draft_images(draft_id: str) -> dict:
    """获取草稿的封面和全部配图。"""
    from core import db
    ddir = db.draft_dir(draft_id)
    img_d = ddir / "img"
    res = {"cover": None, "sections": [], "all": []}
    if not img_d.exists():
        return res
    cov = img_d / "cover.png"
    if cov.exists():
        res["cover"] = f"/img/{draft_id}/cover.png"
        res["all"].append(res["cover"])
    secs = sorted(img_d.glob("sec-*.png"))
    for s in secs:
        u = f"/img/{draft_id}/{s.name}"
        res["sections"].append(u)
        res["all"].append(u)
    return res


def inject_images_to_markdown(body_md: str, draft_id: str) -> str:
    """若 markdown 中未显式包含图片标记，自动在合适位置注入已生成的封面与小节配图。"""
    if "![" in body_md:
        return body_md
    imgs = get_draft_images(draft_id)
    if not imgs["all"]:
        return body_md

    lines = body_md.splitlines()
    out = []
    cover_injected = False
    sec_idx = 0
    num_secs = len(imgs["sections"])

    for ln in lines:
        if not cover_injected and (ln.startswith("## ") or ln.startswith("### ")):
            if imgs["cover"]:
                out.append(f"![封面]({imgs['cover']})\n")
            cover_injected = True

        out.append(ln)

        if (ln.startswith("## ") or ln.startswith("### ")) and sec_idx < num_secs:
            sec_title = ln.lstrip("#").strip()
            out.append(f"\n![{sec_title}]({imgs['sections'][sec_idx]})\n")
            sec_idx += 1

    if not cover_injected and imgs["cover"]:
        out.insert(0, f"![封面]({imgs['cover']})\n")

    return "\n".join(out).strip()


def generate_and_inject_images(draft_id: str, count: int = 3, style: str = "", force_regen: bool = False, model: str = "") -> dict:
    """
    核心业务流程：
    1. 针对指定 draft_id，通读全文并提取视觉结构与小节；
    2. 按指定配图风格生成封面图 + 各小节配图（包含持久化 prompts.json）；
    3. 智能在 Markdown 中对应小节插入图片标记（若未插入过）；
    4. 重新编译各平台专属排版预览（微信、头条、知乎、微博等）；
    5. 返回图片列表与更新后内容。
    """
    from core import db, themes
    from adapters import toutiao as _tt, zhihu as _zh, weibo as _wb
    from core.layouter import _inject_cover

    d = db.get_draft(draft_id)
    if not d:
        raise ValueError(f"草稿不存在: {draft_id}")

    ddir = db.draft_dir(draft_id)
    title = d["title"]
    body_md = d["body_md"]

    sec_meta, cur = [], None
    for line in body_md.splitlines():
        if (line.startswith("## ") or line.startswith("### ")):
            cur = [line.lstrip("#").strip(), []]
            sec_meta.append(cur)
        elif cur is not None and line.strip():
            cur[1].append(line.strip().lstrip("- "))

    sec_arg = []
    for i, (t, paras) in enumerate(sec_meta):
        prev_tail = " ".join(sec_meta[i - 1][1])[-60:] if i > 0 else ""
        sec_arg.append((t, (prev_tail + " " + " ".join(paras))[:140]))

    if not sec_arg:
        sec_arg = [("核心解析", title)]

    imgs = decorate_draft(ddir, title, sec_arg, body_md=body_md, count=count, style=style, force_regen=bool(style or force_regen), model=model)

    import time
    ts = int(time.time())
    v_param = f"?v={ts}"

    has_cover = (ddir / "img" / "cover.png").exists()
    sec_files = sorted((ddir / "img").glob("sec-*.png"))

    # 1. 替换 body_md 中已存在的封面链接或注入新封面
    updated_body_md = body_md
    if f"/img/{draft_id}/cover.png" in updated_body_md:
        updated_body_md = re.sub(
            rf"!\[(.*?)\]\(/img/{re.escape(draft_id)}/cover\.png(?:\?[^)]*)?\)",
            rf"![\1](/img/{draft_id}/cover.png{v_param})",
            updated_body_md
        )
    elif has_cover:
        lines = updated_body_md.splitlines()
        cov_inserted = False
        new_lines = []
        for ln in lines:
            if not cov_inserted and (ln.startswith("## ") or ln.startswith("### ")):
                new_lines.append(f"![封面](/img/{draft_id}/cover.png{v_param})\n")
                cov_inserted = True
            new_lines.append(ln)
        if not cov_inserted:
            new_lines.insert(0, f"![封面](/img/{draft_id}/cover.png{v_param})\n")
        updated_body_md = "\n".join(new_lines).strip()

    # 2. 刷新已有小节配图时间戳，或精准回填缺失小节配图到正文
    for i, sfile in enumerate(sec_files):
        sec_url = f"/img/{draft_id}/{sfile.name}{v_param}"
        sec_title = sec_arg[i][0] if i < len(sec_arg) else f"小节{i+1}"
        if f"/img/{draft_id}/{sfile.name}" in updated_body_md:
            updated_body_md = re.sub(
                rf"!\[(.*?)\]\(/img/{re.escape(draft_id)}/{re.escape(sfile.name)}(?:\?[^)]*)?\)",
                rf"![\1]({sec_url})",
                updated_body_md
            )
        else:
            lines = updated_body_md.splitlines()
            injected = False
            new_lines = []
            for ln in lines:
                new_lines.append(ln)
                if not injected and (ln.startswith("## ") or ln.startswith("### ")):
                    hdr = ln.lstrip("#").strip()
                    if hdr == sec_title or (len(sec_meta) == 0 and i == 0):
                        new_lines.append(f"\n![{sec_title}]({sec_url})\n")
                        injected = True
            if not injected:
                new_lines.append(f"\n![{sec_title}]({sec_url})\n")
            updated_body_md = "\n".join(new_lines).strip()

    c = db.conn()
    c.execute("UPDATE drafts SET body_md=? WHERE id=?", (updated_body_md, draft_id))
    c.commit()
    c.close()

    images_dict = {f.name: f"/img/{draft_id}/{f.name}{v_param}" for f in sec_files}
    cover_url = f"/img/{draft_id}/cover.png{v_param}" if has_cover else None
    
    theme = load_config().get("creation", {}).get("wechat_theme", "caozhou")
    wx_html = themes.md_to_wechat_html(updated_body_md, title, theme=theme, images=images_dict)
    wx_html = _inject_cover(wx_html, cover_url)
    (ddir / "preview-wechat_mp.html").write_text(wx_html, encoding="utf-8")

    tt_html = _tt.render_preview(updated_body_md, title, images=[f"/img/{draft_id}/{f.name}{v_param}" for f in sec_files], cover=cover_url, draft_id=draft_id)
    (ddir / "preview-toutiao.html").write_text(tt_html, encoding="utf-8")
    (ddir / "toutiao.md").write_text(updated_body_md, encoding="utf-8")

    zh_html = _zh.render_preview(updated_body_md, title)
    (ddir / "preview-zhihu.html").write_text(zh_html, encoding="utf-8")
    (ddir / "zhihu.md").write_text(updated_body_md, encoding="utf-8")

    wb_html = _wb.render_preview(updated_body_md, title)
    (ddir / "preview-weibo.html").write_text(wb_html, encoding="utf-8")
    (ddir / "weibo.md").write_text(updated_body_md, encoding="utf-8")

    img_list = []
    if has_cover:
        img_list.append({"name": "封面图", "url": f"/img/{draft_id}/cover.png{v_param}"})
    for f in sec_files:
        img_list.append({"name": f.stem, "url": f"/img/{draft_id}/{f.name}{v_param}"})
    for f in sorted((ddir / "img").glob("custom-*.png")):
        img_list.append({"name": f.stem, "url": f"/img/{draft_id}/{f.name}{v_param}"})

    return {
        "ok": True,
        "count": len(img_list),
        "images": img_list,
        "body_md": updated_body_md,
        "html_wechat": wx_html,
        "image_channel": last_gen_diagnosis()
    }


