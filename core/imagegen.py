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
    ", shot on Hasselblad X2D 100C with 50mm f/1.8 lens, authentic documentary photograph, "
    "natural ambient daylight, soft rim lighting, candid moment, unposed real life scene, "
    "realistic environment textures, subtle skin pores and authentic imperfections, Kodak Portra 400 film look, "
    "8k resolution, award-winning photojournalism, no CGI, no 3D render, no plastic skin, "
    "no airbrushing, no doll face, no stock photo cliche, no text, no watermark, no typography, sharp focus"
)
STYLE_SUFFIX = HYPER_REAL_PHOTO_SUFFIX  # 兼容旧引用

# ---------- 六大视觉风格体系（借鉴 Easel card-design 极简主义+品质分层思想）----------
VISUAL_STYLE_PRESETS = {
    # 1. 纪实摄影（人物/生活/情感类内容）
    "documentary": {
        "name": "纪实摄影·生活烟火",
        "keywords": ["生活", "情感", "人物", "日常", "故事", "美食", "旅行", "亲子", "健康", "运动"],
        "suffix": (
            ", shot on Hasselblad X2D 100C 50mm f/1.8, authentic candid moment, "
            "natural golden-hour window light, realistic skin texture with subtle pores, "
            "unposed real-life scene, warm Kodak Portra 400 film grain, bokeh background, "
            "8k photorealistic, no CGI, no plastic skin, no stock photo pose, no text, no watermark"
        ),
        "system_prompt": (
            "你是普利策奖纪实摄影师兼国家地理图片总监。将用户主题转化为极度具象的真实生活抓拍英文 Prompt。"
            "要求：①明确人物动作与真实微表情；②具体环境道具与生活杂物细节；"
            "③光线方向（自然侧光/逆光/窗边漫射光）；④相机参数。"
            "只输出英文 Prompt，不要解释。"
        ),
    },
    # 2. 瑞士极简（商业/知识/效率类内容）—— 借鉴 Easel 的 Swiss Minimalism 理念
    "swiss_minimal": {
        "name": "瑞士极简·商业质感",
        "keywords": ["商业", "职场", "效率", "管理", "职业", "简历", "成功", "财富", "理财", "投资", "创业", "办公"],
        "suffix": (
            ", Swiss International Typographic Style, clean negative space, "
            "precise geometric composition, muted neutral palette with single accent color, "
            "high-end editorial photography, shot on Phase One IQ4 150MP with 85mm f/2, "
            "controlled studio lighting with soft boxes, razor-sharp detail, "
            "premium commercial photography, minimalist restraint, no clutter, no text, no watermark"
        ),
        "system_prompt": (
            "你是顶级商业摄影指导兼平面设计总监，擅长瑞士国际主义风格。"
            "将用户主题转化为极简高端商业摄影英文 Prompt。"
            "要求：①大量留白与几何构图；②中性色调搭配单一强调色；"
            "③专业摄影棚可控光源；④商务场景质感道具。只输出英文 Prompt，不要解释。"
        ),
    },
    # 3. 杂志编辑（时尚/美妆/生活方式类内容）
    "magazine_editorial": {
        "name": "杂志编辑·高端生活方式",
        "keywords": ["时尚", "美妆", "美容", "护肤", "穿搭", "风格", "潮流", "设计", "艺术", "创意", "家居", "装修"],
        "suffix": (
            ", Vogue/Harper's Bazaar editorial style, dramatic directional lighting, "
            "shot on Canon EOS R5 with 85mm f/1.2L lens, rich saturated tones, "
            "fashion-forward composition, sophisticated color grading, "
            "high fashion photography, glossy magazine aesthetic, "
            "impeccable styling, no text, no watermark, 8k ultra-detailed"
        ),
        "system_prompt": (
            "你是《Vogue》《时尚COSMO》资深图片总监。将用户主题转化为顶级时尚杂志摄影英文 Prompt。"
            "要求：①戏剧性方向光与高对比度；②浓郁饱和色调与精致调色；"
            "③时尚前沿构图与造型；④高端质感道具细节。只输出英文 Prompt，不要解释。"
        ),
    },
    # 4. 科技赛博（AI/数字/未来/技术类内容）
    "tech_cyber": {
        "name": "科技赛博·数字未来感",
        "keywords": ["科技", "AI", "人工智能", "数字", "互联网", "编程", "代码", "数据", "算法", "区块链", "元宇宙", "芯片", "半导体", "机器人"],
        "suffix": (
            ", cyberpunk-inspired but grounded in near-future realism, "
            "cool blue-cyan-purple tonal range, volumetric light rays through digital interfaces, "
            "shallow depth of field on circuitry or glowing screens, "
            "shot on Sony A1 with 24mm f/1.4 GM, long exposure light trails, "
            "8k photorealistic rendering, cinematic tech aesthetic, "
            "no cartoon, no anime, no 3D render plastic, no text, no watermark"
        ),
        "system_prompt": (
            "你是科幻电影视觉总监兼MIT媒体实验室创意总监。将用户主题转化为近未来科技感摄影英文 Prompt。"
            "要求：①蓝青紫科技色调；②数字界面/电路板/光源轨迹等科技道具；"
            "③体积光与景深特效；④近未来感真实场景。只输出英文 Prompt，不要解释。"
        ),
    },
    # 5. 古风雅韵（传统古风/汉服/仙侠/国风/历史文化）
    "ancient_chinese": {
        "name": "古风雅韵·东方意境",
        "keywords": ["古风", "国风", "东方", "传统", "文化", "历史", "国学", "茶道", "书法", "汉服", "古建", "仙侠", "非遗", "民俗", "亭台楼阁", "诗意"],
        "suffix": (
            ", ancient Chinese aesthetic, traditional Hanfu elegance, poetic atmospheric lighting, "
            "misty Jiangnan pavilions or grand classical courtyards, shot on Leica SL2 with 50mm f/1.4, "
            "soft ethereal morning mist diffusion, delicate silk and embroidery textures, cinematic color grading, "
            "refined Oriental composition, elegant wabi-sabi restraint, 8k photorealistic, no modern objects, no text, no watermark"
        ),
        "system_prompt": (
            "你是顶级古风美学摄影师兼东方影视视觉总监。将用户主题转化为极富诗意意境的中国古风摄影英文 Prompt。"
            "要求：①古风场景道具（汉服、飞檐、亭台、古卷、水墨意象）；②柔和漫射光与晨雾丁达尔光；"
            "③深沉典雅的东方传统色彩（朱红、黛青、茶白、水绿）；④电影级胶片质感。只输出英文 Prompt，不要解释。"
        ),
    },
    # 兼容历史别名
    "chinese_ink": {
        "name": "古风雅韵·东方意境",
        "keywords": ["传统", "文化", "历史", "国学", "茶道", "书法", "汉服", "古建", "非遗", "民俗", "中医", "国潮", "东方"],
        "suffix": (
            ", contemporary Chinese ink wash aesthetic meets modern photography, "
            "misty mountains and ancient architecture, wabi-sabi imperfection, "
            "shot on Leica M11 Monochrom with 35mm Summilux f/1.4, "
            "soft natural mist diffusion, warm rice-paper tones or deep ink blacks, "
            "poetic negative space, traditional craft textures, "
            "no neon, no western aesthetic, no text, no watermark, 8k"
        ),
        "system_prompt": (
            "你是新中式美学摄影师兼东方视觉总监。将用户主题转化为融合水墨与现代摄影的东方美学英文 Prompt。"
            "要求：①水墨晕染与负空间哲学；②古典道具与现代质感融合；"
            "③山水薄雾或宣纸暖调；④徕卡胶片质感。只输出英文 Prompt，不要解释。"
        ),
    },
    # 6. 城市风/都市风（都会天际线/现代街道/车水马龙/摩天大楼/城市街拍）
    "city_urban": {
        "name": "城市风·现代都市摩天",
        "keywords": ["城市", "都市", "都会", "街头", "街拍", "天际线", "摩天大楼", "建筑", "街道", "车水马龙", "夜景", "步行街", "CBD", "地铁"],
        "suffix": (
            ", modern urban metropolis atmosphere, dramatic city skyline with architectural glass reflections, "
            "shot on Sony A7R V with 35mm f/1.4 GM lens, golden hour sunlight bouncing off modern skyscrapers, "
            "bustling metropolitan streets, realistic asphalt and neon city textures, wide-angle cinematic perspective, "
            "crisp urban details, no CGI cartoon, no plastic, no text, no watermark, 8k ultra-sharp"
        ),
        "system_prompt": (
            "你是国家地理都市摄影师兼全球建筑摄影总监。将用户主题转化为繁华现代城市/都市风摄影英文 Prompt。"
            "要求：①现代化都市地标/摩天大楼/商业街景/天际线构图；②城市黄金时段或蓝调时刻真实光影；"
            "③高解析度现代城市质感与层次；④大片级景深。只输出英文 Prompt，不要解释。"
        ),
    },
    # 7. 电影光影（戏剧大片/宽银幕质感）
    "cinematic_movie": {
        "name": "影视大片·电影光影",
        "keywords": ["电影", "影视", "大片", "戏剧", "故事", "光影", "镜头", "叙事", "情绪", "氛围"],
        "suffix": (
            ", cinematic movie still, 35mm anamorphic lens with subtle horizontal flares, "
            "dramatic chiaroscuro lighting, rich Kodachrome color grading, emotive storytelling atmosphere, "
            "shallow depth of field, natural film grain, 8k resolution, Panavision widescreen aesthetic, "
            "no text, no watermark, award-winning cinematography"
        ),
        "system_prompt": (
            "你是奥斯卡最佳摄影奖电影摄影师。将用户主题转化为电影大片剧照级英文 Prompt。"
            "要求：①强烈的明暗对比与叙事光影；②变形宽银幕电影构图；"
            "③电影胶片色调与颗粒感；④极具故事张力的瞬间。只输出英文 Prompt，不要解释。"
        ),
    },
    # 8. 高端商业广告（产品/品牌/营销类内容）
    "commercial_premium": {
        "name": "高端商业·品牌广告",
        "keywords": ["产品", "品牌", "营销", "广告", "推广", "电商", "销售", "促销", "新品", "发布", "种草"],
        "suffix": (
            ", luxury product photography, ultra-precise focus stacking, "
            "studio strobe lighting with honeycomb grid modifiers, "
            "shot on Phase One XF IQ4 150MP, perfect white or gradient background, "
            "hyper-detailed product textures, premium brand aesthetic, "
            "Apple/Nike/Hermès level visual quality, aspirational lifestyle context, "
            "no text overlay, no watermark, 100MP ultra-high resolution"
        ),
        "system_prompt": (
            "你是苹果/爱马仕级广告摄影总监。将用户主题转化为奢华品牌级商业广告摄影英文 Prompt。"
            "要求：①精准焦叠与超清质感；②专业蜂巢遮光器棚拍光源；"
            "③高端品牌审美与精致背景；④产品细节的超高分辨率呈现。只输出英文 Prompt，不要解释。"
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


def photojournalism_prompt_engine(raw_text: str, context: str = "",
                                  force_style: str | None = None) -> str:
    """v5.302 升级版提示词引擎：自动识别内容类型，从六大风格体系中选择最佳风格，
    生成远超单一纪实摄影风格的高品质 Prompt。借鉴 Easel card-design 的风格分层与密度质检原则。"""
    raw_s = (raw_text or "").strip()
    combined = f"{raw_s} {context or ''}".strip()

    if not raw_s:
        return (
            "Authentic candid street photography, warm golden hour light, "
            "human connection moment, realistic details, 8k"
            + HYPER_REAL_PHOTO_SUFFIX
        )

    # 若已是高质量英文长提示词，直接附加必要的反 AI 感参数
    if (not bool(re.search(r"[\u4e00-\u9fa5]", raw_s))
            and len(raw_s.split()) >= 12
            and any(k in raw_s for k in ["shot on", "lens", "mm f/", "lighting", "photorealistic"])):
        if "no text" not in raw_s and "no watermark" not in raw_s:
            return raw_s + ", no text, no watermark, no CGI, no plastic skin"
        return raw_s

    # 自动检测或强制指定风格
    style_key = force_style if force_style in VISUAL_STYLE_PRESETS else _detect_visual_style(combined)
    preset = VISUAL_STYLE_PRESETS[style_key]

    # 调用 LLM 按对应风格的 system_prompt 生成专属提示词
    try:
        from core import llm
        user_msg = (
            f"【画面核心主题】：{raw_s}\n"
            f"【上下文细节】：{context[:200] if context else '内容配图'}\n"
            f"【视觉风格要求】：{preset['name']}"
        )
        msgs = [
            {"role": "system", "content": preset["system_prompt"]},
            {"role": "user", "content": user_msg}
        ]
        en_prompt = llm.chat(msgs, temperature=0.65, timeout_s=18)
        clean_en = en_prompt.strip().strip('"').replace("\n", " ")
        # 若生成成功且为英文，追加风格专属尾缀
        if len(clean_en) >= 20 and not re.search(r"[\u4e00-\u9fa5]", clean_en):
            # 避免尾缀重复
            if preset["suffix"].strip(", ")[:30] not in clean_en:
                return clean_en + preset["suffix"]
            return clean_en
    except Exception as e:
        print(f"[VisualPromptEngine Fallback] style={style_key}: {e}")

    # 降级：用规则引擎拼装 + 风格尾缀
    try:
        from core.short_drama import _synthesize_scene_prompt
        synthesized = _synthesize_scene_prompt(
            raw_s, context or raw_s,
            "Medium Establishing Shot", "Natural Daylight", "Steady Cam"
        )
        return synthesized + preset["suffix"]
    except Exception:
        return f"Authentic scene of {raw_s[:80]}, photorealistic, 8k" + preset["suffix"]


# 全文通读 ➔ 视觉要点提取 ➔ 多风格提示词生成（v5.302 升级版）
ARTICLE_VISUAL_DIGEST_PROMPT = """你是一名顶级视觉总监，兼具普利策纪实摄影师、《Vogue》图片总监、
苹果广告摄影导演和新中式美学大师四重身份。

你的任务：深度通读整篇文章，根据文章核心主题自动匹配最合适的视觉风格，
并为【封面大图】和【各段落小节】生成极具专业感的纯英文生图 Prompt。

【视觉风格自动匹配规则（必须严格执行）】：
- 生活/情感/人物/美食/旅行 → 纪实摄影风格（Hasselblad + Kodak Portra 胶片感，真实烟火气）
- 商业/职场/效率/管理/财富 → 瑞士极简风格（Phase One，大留白，几何构图，商务质感）
- 时尚/美妆/穿搭/家居/艺术 → 杂志编辑风格（Canon R5，戏剧光，高饱和调色，Vogue感）
- 科技/AI/数字/互联网/算法 → 科技赛博风格（Sony A1，蓝青光效，数字界面，近未来感）
- 传统/文化/国潮/茶道/历史 → 新中式水墨风格（Leica M11，薄雾，负空间，东方美学）
- 产品/品牌/营销/电商/种草 → 高端商业广告风格（Phase One 150MP，焦叠，品牌级光源）

【核心输出规范】：
1. 通读全文，精准判断主题类型，从上述6种风格中选择最匹配的1种；
2. 每张图片的英文 Prompt 必须包含：具体主体动作/场景细节 + 专业相机参数 + 风格专属光效 + 反AI感负向词（no text, no watermark, no CGI, no plastic, no stock photo）；
3. 中文 zh 字段用于人类审查，英文 en 字段用于实际生图；
4. 严格输出纯 JSON，无 markdown 包裹：

{
  "theme_vibe": "文章整体视觉调性（如：职场效率·瑞士极简商业质感）",
  "visual_style": "swiss_minimal",
  "cover_prompt": {
    "zh": "封面具象场景描述：人物动作、环境细节、光线方向",
    "en": "Clean minimalist composition of a focused professional reviewing analytics dashboard on dual monitors, controlled studio lighting, Phase One IQ4, precise geometric framing, muted grey-white palette with electric blue accent, premium commercial photography, no text, no watermark, no CGI, 8k"
  },
  "sections_prompts": [
    {
      "section_title": "小节标题",
      "zh": "该小节具象场景：主体、动作、环境道具、光线",
      "en": "Authentic candid moment of... shot on [camera], [lighting style], [style-specific params], no text, no watermark"
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
        # 降级：使用智能实体提取器保底，并应用自动检测的风格尾缀
        try:
            from core.short_drama import _synthesize_scene_prompt
            cover_en = (
                _synthesize_scene_prompt(title, title, "Wide Establishing Shot", "Natural Daylight", "Slow Dolly In")
                + auto_preset["suffix"]
            )
        except Exception:
            cover_en = f"Authentic scene of {title[:60]}, photorealistic, 8k" + auto_preset["suffix"]
        cover_zh = f"《{title[:20]}》核心意象全景：主体细节与空间光影交织"

        sec_prompts = []
        for i, sec in enumerate(sections):
            t, ctx = (sec if isinstance(sec, (list, tuple)) else (sec, ""))
            try:
                from core.short_drama import _synthesize_scene_prompt
                p_en = (
                    _synthesize_scene_prompt(title, ctx or t, "Medium Shot", "Cinematic Rim Light", "Push In")
                    + auto_preset["suffix"]
                )
            except Exception:
                p_en = f"Authentic scene of {t[:60]}, photorealistic, 8k" + auto_preset["suffix"]
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
        w, h = (1080, 720) if not is_cover else (1080, 600)

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
        for x in range(0, w, 60):
            draw.line([(x, 0), (x, h)], fill=(255, 255, 255, 8), width=1)
        for y in range(0, h, 60):
            draw.line([(0, y), (w, y)], fill=(255, 255, 255, 8), width=1)

        margin = 32
        draw.rectangle([(margin, margin), (w - margin, h - margin)], outline=(255, 255, 255, 30), width=2)
        draw.line([(margin, margin + 4), (margin + 60, margin + 4)], fill=p["accent"], width=4)

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
                    font_title = ImageFont.truetype(fp, 44 if not is_cover else 48)
                    font_sub = ImageFont.truetype(fp, 26)
                    font_tag = ImageFont.truetype(fp, 20)
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


def parse_dimensions(size: str) -> tuple[int, int]:
    """从尺寸字符串（如 1024x1792）解析宽度和高度。"""
    try:
        parts = size.lower().split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 1024, 1024


def gen_image_pollinations(prompt: str, out_path: Path, width: int = 1024, height: int = 1024) -> bool:
    """通道 2：调用全球开源高质量 Pollinations Flux 真实文生图引擎（100% 真实摄影画质，免 API Key）。"""
    import urllib.parse
    clean_prompt = prompt.strip()
    if not clean_prompt:
        clean_prompt = "cinematic movie still, photorealistic, 8k resolution, masterpiece"
    
    # 限制 URL 长度与编码
    encoded_p = urllib.parse.quote(clean_prompt[:400])
    seed = abs(hash(clean_prompt)) % 100000
    target_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width={width}&height={height}&model=flux&nologo=true&seed={seed}"
    
    try:
        with httpx.Client(timeout=35, follow_redirects=True) as client:
            r = client.get(target_url)
            if r.status_code == 200 and len(r.content) > 2048:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(r.content)
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


def gen_image(prompt: str, out_path: Path, size: str = "1024x1024", context_title: str = "", context_sub: str = "", angle_idx: int = 0, is_cover: bool = False, model: str = "") -> bool:
    """生成一张配图并存入 out_path。
    智能多通道真实生图机制：
    1. 商业通道：若配置了支持生图的商业供应商（如 agnes-image、OpenAI dall-e-3、阿里 wanx-v1、智谱 cogview 或自建网关），调用 /images/generations；
    2. 全球开源保底通道：Pollinations Flux 真实文生图引擎，全国全网免 Key，100% 真实摄影画面；
    3. 极端断网保底：Pillow 美学信息卡片。
    """
    cfg = image_cfg()
    req_model = (model or "").strip() or cfg.get("model", "").strip() or "flux-schnell"

    # 全局通过纪实摄影引擎升华 Prompt（彻底去除 AI 塑料感与假人感）
    enhanced_prompt = photojournalism_prompt_engine(prompt, context=context_sub or context_title)

    from core.llm import resolve_llm_endpoint, classify_model
    base, key, resolved_model, pid = resolve_llm_endpoint(req_model)
    _reset_gen_diagnosis(resolved_model, pid)

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
        commercial_ok = False
        for req_url in candidate_urls:
            try:
                with httpx.Client(timeout=60, trust_env=not is_local) as client:
                    r = client.post(
                        req_url,
                        json={"model": resolved_model, "prompt": enhanced_prompt, "n": 1, "size": size},
                        headers={"Authorization": f"Bearer {key}"},
                    )
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
                            with httpx.Client(timeout=40, follow_redirects=True) as dl_client:
                                dl_r = dl_client.get(img_url)
                                if dl_r.status_code == 200 and len(dl_r.content) > 1024:
                                    out_path.parent.mkdir(parents=True, exist_ok=True)
                                    out_path.write_bytes(dl_r.content)
                                    commercial_ok = True
                                    break
                            _GEN_DIAG["commercial_error"] = f"生图端点返回的图片地址拉取失败（HTTP {dl_r.status_code}）"
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
            return True
    else:
        # 未进入商业通道（key 缺失 / 模型非 image 类）也要给出可观测原因
        if not key:
            _GEN_DIAG["commercial_error"] = f"供应商 [{pid}] 未配置有效 API Key（占位/空 Key）"
        elif classify_model(resolved_model) != "image":
            _GEN_DIAG["commercial_error"] = f"目标模型 [{resolved_model}] 不是生图模型"

    # 2. 尝试开源保底通道：Pollinations Flux 真实文生图引擎（免 Key、免配置、100% 真实可用）
    w, h = parse_dimensions(size)
    if gen_image_pollinations(enhanced_prompt, out_path, width=w, height=h):
        _GEN_DIAG["channel"] = "pollinations"
        return True

    # 3. 极端断网降级：美学卡片
    card_ok = _render_fallback_card(context_title or prompt[:30], context_sub or prompt, out_path, angle_idx, is_cover)
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
        if gen_image(prompt_cover, f_cover, "1024x1024", context_title=title, context_sub=cover_zh[:40], angle_idx=0, is_cover=True, model=model):
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
        
        if gen_image(prompt_sec, f_sec, "1024x1024", context_title=t, context_sub=p_zh[:40], angle_idx=angle_i, is_cover=False, model=model):
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
    cov_en = cov_p.get("en", "") or f"Cinematic wide shot of {title}, 35mm film, volumetric lighting, photorealistic, 8k"
    cov_zh = cov_p.get("zh", "") or f"《{title}》核心意象全景"
    
    res["cover"] = {
        "name": "cover",
        "title": "封面大图",
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
        sec_en = sec_p.get("en", "") or f"Cinematic medium shot of {sec_title}, dramatic lighting, photorealistic, 8k"
        sec_zh = sec_p.get("zh", "") or f"小节【{sec_title}】核心场景"
        
        res["sections"].append({
            "name": s.stem,
            "section_num": sec_num,
            "section_title": sec_title,
            "title": f"小节配图 #{sec_num + 1}",
            "exists": True,
            "url": f"/img/{draft_id}/{s.name}",
            "prompt_zh": sec_zh,
            "prompt_en": sec_en
        })

    # 3. 自定义配图元数据
    for c in sorted(img_d.glob("custom-*.png")):
        res["custom"].append({
            "name": c.stem,
            "title": "自定义插图",
            "exists": True,
            "url": f"/img/{draft_id}/{c.name}",
            "prompt_zh": "",
            "prompt_en": ""
        })

    return res


def regenerate_draft_image(draft_id: str, name: str, prompt: str = "", title: str = "", aspect: str = "1:1") -> dict:
    """针对草稿中的单个图片（封面、某小节图、或自定义图）使用指定或微调的 Prompt 重新生成并同步刷新排版。"""
    from core import db, themes
    from adapters import toutiao as _tt, zhihu as _zh, weibo as _wb
    from core.layouter import _inject_cover

    d = db.get_draft(draft_id)
    if not d:
        raise ValueError(f"草稿不存在: {draft_id}")
    ddir = db.draft_dir(draft_id)
    d_img = img_dir(ddir)
    
    # 尺寸解析
    size_map = {
        "1:1": "1024x1024",
        "16:9": "1792x1024",
        "3:4": "1024x1365",
        "9:16": "1024x1792"
    }
    size = size_map.get(aspect, "1024x1024")

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

        if ln.startswith("### ") and sec_idx < num_secs:
            sec_title = ln[4:].strip()
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
        if line.startswith("### "):
            cur = [line[4:].strip(), []]
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

    new_lines = []
    cover_injected = (f"/img/{draft_id}/cover.png" in body_md)

    sec_img_map = {}
    for idx, (t, _) in enumerate(sec_arg):
        sec_img_map[t] = f"/img/{draft_id}/sec-{idx}.png"

    for line in body_md.splitlines():
        if not cover_injected and (line.startswith("### ") or line.startswith("## ")):
            new_lines.append(f"![封面](/img/{draft_id}/cover.png)\n")
            cover_injected = True

        new_lines.append(line)

        if line.startswith("### "):
            sec_title = line[4:].strip()
            img_url = sec_img_map.get(sec_title)
            if img_url and img_url not in body_md:
                new_lines.append(f"\n![{sec_title}]({img_url})\n")

    updated_body_md = "\n".join(new_lines).strip()

    c = db.conn()
    c.execute("UPDATE drafts SET body_md=? WHERE id=?", (updated_body_md, draft_id))
    c.commit()
    c.close()

    images_dict = {f.name: f"/img/{draft_id}/{f.name}" for f in sorted((ddir / "img").glob("sec-*.png"))}
    cover_url = f"/img/{draft_id}/cover.png" if (ddir / "img" / "cover.png").exists() else None
    
    theme = load_config().get("creation", {}).get("wechat_theme", "caozhou")
    wx_html = themes.md_to_wechat_html(updated_body_md, title, theme=theme, images=images_dict)
    wx_html = _inject_cover(wx_html, cover_url)
    (ddir / "preview-wechat_mp.html").write_text(wx_html, encoding="utf-8")

    tt_html = _tt.render_preview(updated_body_md, title)
    (ddir / "preview-toutiao.html").write_text(tt_html, encoding="utf-8")
    (ddir / "toutiao.md").write_text(updated_body_md, encoding="utf-8")

    zh_html = _zh.render_preview(updated_body_md, title)
    (ddir / "preview-zhihu.html").write_text(zh_html, encoding="utf-8")
    (ddir / "zhihu.md").write_text(updated_body_md, encoding="utf-8")

    wb_html = _wb.render_preview(updated_body_md, title)
    (ddir / "preview-weibo.html").write_text(wb_html, encoding="utf-8")
    (ddir / "weibo.md").write_text(updated_body_md, encoding="utf-8")

    img_list = []
    if (ddir / "img" / "cover.png").exists():
        img_list.append({"name": "封面图", "url": f"/img/{draft_id}/cover.png"})
    for f in sorted((ddir / "img").glob("sec-*.png")):
        img_list.append({"name": f.stem, "url": f"/img/{draft_id}/{f.name}"})
    for f in sorted((ddir / "img").glob("custom-*.png")):
        img_list.append({"name": f.stem, "url": f"/img/{draft_id}/{f.name}"})

    return {
        "ok": True,
        "count": len(img_list),
        "images": img_list,
        "body_md": updated_body_md,
        "html_wechat": wx_html,
        "image_channel": last_gen_diagnosis()
    }


