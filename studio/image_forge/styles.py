# SPDX-License-Identifier: BUSL-1.1
"""12 现代审美风格库：PromptForge / 风格选择器的统一真源。

⭐ 硬规则：
- list_styles() 必须返回深拷贝：调用方对返回结果的任何修改都不得污染 STYLES 本体，
  否则全仓引用的风格描述将被静默篡改（后果：用户看到的风格说明与实际不符）。
- get_style() 解析不到 id 时返回 None，由调用方决定兜底风格；本模块不抛异常、
  不做外部请求。

示例图链接说明：example_image_url 为演示用的示例链接（后续由运营替换为真实素材图），
不是真实成图承诺。"""

from __future__ import annotations

import copy

STYLES: list[dict] = [
    {
        "id": "cinematic",
        "name": "电影质感",
        "description": "大片级光影与影调：深沉色调、伦勃朗光、胶片颗粒感，适合讲故事的画面。",
        "use_cases": ["短剧封面", "剧情高光时刻", "人物特写海报"],
        "prompt_fragment": "cinematic lighting, film still, dramatic contrast, shallow depth of field, 35mm film grain",
        "example_image_url": "https://example.com/styles/cinematic.jpg",
    },
    {
        "id": "cyber-ink",
        "name": "赛博水墨",
        "description": "东方水墨笔意 × 霓虹赛博：留白与光斑并存，传统意境撞上未来感。",
        "use_cases": ["国风科幻", "品牌概念海报", "东方美学短视频封面"],
        "prompt_fragment": "cyberpunk neon lights blended with Chinese ink wash painting, mist, glowing circuitry, elegant negative space",
        "example_image_url": "https://example.com/styles/cyber-ink.jpg",
    },
    {
        "id": "guochao",
        "name": "国潮插画",
        "description": "敦煌纹样、祥云瑞兽、浓墨重彩：年轻化的国风视觉语言。",
        "use_cases": ["国货品牌", "节气主题", "传统文化短视频"],
        "prompt_fragment": "guochao illustration style, bold Chinese traditional patterns, vibrant red and gold, flat yet detailed, festive",
        "example_image_url": "https://example.com/styles/guochao.jpg",
    },
    {
        "id": "documentary",
        "name": "纪实摄影",
        "description": "不摆拍的真实感：自然光、抓拍瞬间、轻微噪点，像新闻现场一样可信。",
        "use_cases": ["社会热点", "纪实短评配图", "人物访谈"],
        "prompt_fragment": "documentary photography, candid moment, natural light, realistic skin texture, unposed, photojournalism style",
        "example_image_url": "https://example.com/styles/documentary.jpg",
    },
    {
        "id": "minimalism",
        "name": "极简留白",
        "description": "少即是多：大面积留白、单一主体、高级灰影调，呼吸感拉满。",
        "use_cases": ["金句海报", "品牌调性图", "知识类封面"],
        "prompt_fragment": "minimalist composition, generous negative space, single subject, soft muted tones, elegant simplicity",
        "example_image_url": "https://example.com/styles/minimalism.jpg",
    },
    {
        "id": "retro-film",
        "name": "复古胶片",
        "description": "过期胶卷的味道：偏色、漏光、颗粒，时光倒流的怀旧氛围。",
        "use_cases": ["怀旧主题", "年代感故事", "复古穿搭"],
        "prompt_fragment": "retro film photography, expired film color cast, light leaks, grain, nostalgic warm tones, 1980s vibe",
        "example_image_url": "https://example.com/styles/retro-film.jpg",
    },
    {
        "id": "anime",
        "name": "二次元插画",
        "description": "日式动画质感：干净线条、通透色彩、细腻光影，二次元浓度高。",
        "use_cases": ["动漫解说", "游戏相关", "年轻向内容"],
        "prompt_fragment": "anime illustration, clean line art, vibrant translucent colors, detailed cel shading, studio quality",
        "example_image_url": "https://example.com/styles/anime.jpg",
    },
    {
        "id": "hyperreal-portrait",
        "name": "超写实人像",
        "description": "毛孔级真实：皮肤质感、发丝细节、眼神光，照片级人像。",
        "use_cases": ["人物故事", "颜值向内容", "高端访谈"],
        "prompt_fragment": "hyperrealistic portrait, ultra detailed skin texture, individual hair strands, catchlights in eyes, 85mm lens, studio lighting",
        "example_image_url": "https://example.com/styles/hyperreal-portrait.jpg",
    },
    {
        "id": "neo-chinese",
        "name": "新中式",
        "description": "宋式美学当代演绎：青绿山水、屏风回廊、含蓄雅致，东方高级感。",
        "use_cases": ["新中式家居", "茶文化", "东方美学品牌"],
        "prompt_fragment": "neo-Chinese aesthetic, Song dynasty painting style, blue-green landscape, elegant pavilion, refined and serene",
        "example_image_url": "https://example.com/styles/neo-chinese.jpg",
    },
    {
        "id": "pop-art",
        "name": "波普艺术",
        "description": "高饱和撞色、网点印刷、街头张力：第一眼就被抓住的视觉冲击。",
        "use_cases": ["潮流话题", "娱乐向封面", "年轻化营销"],
        "prompt_fragment": "pop art style, bold saturated colors, halftone dots, comic book energy, striking graphic composition",
        "example_image_url": "https://example.com/styles/pop-art.jpg",
    },
    {
        "id": "dark-fantasy",
        "name": "暗黑奇幻",
        "description": "哥特式暗夜美学：低饱和冷调、神秘氛围，适合奇幻与悬疑题材。",
        "use_cases": ["悬疑故事", "奇幻题材", "暗夜氛围封面"],
        "prompt_fragment": "dark fantasy art, gothic atmosphere, desaturated cold tones, mysterious fog, moonlight, dramatic shadows",
        "example_image_url": "https://example.com/styles/dark-fantasy.jpg",
    },
    {
        "id": "japanese-fresh",
        "name": "清新日系",
        "description": "空气感与治愈：柔光、高明度、淡雅色彩，像午后阳光一样舒服。",
        "use_cases": ["生活方式", "治愈系内容", "旅行vlog封面"],
        "prompt_fragment": "fresh Japanese style photography, soft daylight, high key, light pastel tones, airy and healing mood",
        "example_image_url": "https://example.com/styles/japanese-fresh.jpg",
    },
]


def list_styles() -> list[dict]:
    """返回 12 风格的深拷贝（调用方修改结果不会污染风格库本体）。

    ⭐ 深拷贝是硬规则：返回浅拷贝会导致调用方无意间改写 STYLES，
    全仓所有引用该风格的页面都会展示被篡改的描述。
    """
    return copy.deepcopy(STYLES)


def get_style(style_id: str) -> dict | None:
    """按 id 查找风格；找不到返回 None（由调用方决定兜底策略）。

    本函数是纯查表，不抛异常、不请求网络。
    """
    for style in STYLES:
        if style["id"] == style_id:
            return style
    return None
