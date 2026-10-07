# SPDX-License-Identifier: BUSL-1.1
"""PromptForge：贫瘠输入 → 结构化提示词（主体/风格/光影/构图四维）+ 否定词。

⭐ 硬规则：
- assemble_prompt 是金丝雀锁死算法：输出必须与 tests/seed/expected.json 逐字一致，
  任何格式改动（标点、换行、拼接符号）都会导致 CI 金丝雀测试失败。改算法必须同步
  更新 expected.json 与 docs/CONTRACT.md §6，并经评审批准。
- forge_prompt 纯规则、确定性：不调外部服务，不读网络，不读密钥；相同输入永远
  得到相同输出。thin_input 为空/空白直接抛 BadRequest，禁止静默生成空提示词
  （空提示词会浪费一次生图额度）。
- 风格解析统一走 studio.image_forge.styles.get_style；解析不到用默认风格兜底，
  禁止因风格名输错而让用户拿到报错。
"""

from __future__ import annotations

from studio.errors import BadRequest
from studio.image_forge.styles import get_style

DEFAULT_STYLE_ID = "cinematic"  # 默认风格：电影质感（通用百搭）

# 固定通用否定词：压住低质量、水印、肢体畸变等常见翻车点
NEGATIVE_UNIVERSAL = (
    "低质量，模糊，噪点，水印，多余文字，扭曲的手指，变形的五官，"
    "画面杂乱，曝光过度，色彩失真，廉价感"
)

# 各风格的光影建议（确定性查表，无外部依赖）
_LIGHTING_BY_STYLE: dict[str, str] = {
    "cinematic": "电影感伦勃朗光，冷暖对比鲜明",
    "cyber-ink": "霓虹光斑与水墨雾气交织，神秘氛围",
    "guochao": "舞台式高饱和暖光，喜庆明亮",
    "documentary": "自然光抓拍，影调真实不做作",
    "minimalism": "大面积柔光，影调干净高级灰",
    "retro-film": "怀旧暖调柔光，轻微漏光感",
    "anime": "通透明亮的动漫式光影，色彩清透",
    "hyperreal-portrait": "影棚级柔光箱布光，皮肤质感细腻",
    "neo-chinese": "东方晨雾般的柔光，雅致含蓄",
    "pop-art": "高对比硬光，色彩冲击力强",
    "dark-fantasy": "月光冷调低照度，暗部细节丰富",
    "japanese-fresh": "午后阳光般的柔和高调光，空气感强",
}
_LIGHTING_DEFAULT = "自然柔光，影调干净"

# 构图库：按输入长度取模轮转，保证确定性（同一句话永远得到同一构图）
_COMPOSITIONS: tuple[str, ...] = (
    "三分法构图，主体略偏画面中心",
    "对称式构图，视觉重心稳定",
    "引导线构图，视线自然聚焦主体",
    "浅景深虚化背景，突出主体",
    "广角全景，环境氛围拉满",
)

# 方头括号：U+3010 为开括号、U+3011 为合括号（源码用 chr 构造，
# 避免字面量在写入链路中被误处理；运行时即为期望的方头括号字符）
_BRACKET_OPEN = chr(0x3010)
_BRACKET_CLOSE = chr(0x3011)


def assemble_prompt(hotspot: dict, style: str) -> str:
    """⭐ 金丝雀算法（锁死，逐字精确）：热点 → 三行生图提示词。

    hotspot 字段：id / title / keywords(list[str]) / angle / heat / platform。
    算法：先用顿号拼接 keywords，再按模板组装三行文本
    （模板：方头括号包裹风格名后接标题 / 关键词：… / 切入角度：…，
    行间用换行分隔）。
    """
    keywords = "、".join(hotspot["keywords"])
    head = _BRACKET_OPEN + style + _BRACKET_CLOSE + hotspot["title"]
    return head + "\n关键词：" + keywords + "\n切入角度：" + hotspot["angle"]


def forge_prompt(thin_input: str, style: str) -> dict:
    """贫瘠输入（一句话）→ 结构化提示词。

    返回固定键：subject（主体）/ style（风格名）/ lighting（光影）/
    composition（构图）/ negative（否定词）/ prompt（完整提示词）/ style_id。

    纯规则、确定性：不调用任何外部服务。style 按风格库 id 解析，
    解析不到则用默认风格兜底。

    ⭐ thin_input 为空或全空白时抛 BadRequest("请先输入一句话描述想要的画面")：
    禁止把空输入喂给生图通道，那会直接烧掉用户一次生图额度。
    """
    subject = (thin_input or "").strip()
    if not subject:
        raise BadRequest("请先输入一句话描述想要的画面")

    style_entry = get_style(style) or get_style(DEFAULT_STYLE_ID)
    assert style_entry is not None  # 默认风格恒存在，守卫兜底表被误删
    style_id = style_entry["id"]

    lighting = _LIGHTING_BY_STYLE.get(style_id, _LIGHTING_DEFAULT)
    composition = _COMPOSITIONS[len(subject) % len(_COMPOSITIONS)]
    fragment = style_entry["prompt_fragment"]

    prompt = subject + "，" + fragment + "；光影：" + lighting + "；构图：" + composition

    return {
        "subject": subject,
        "style": style_entry["name"],
        "lighting": lighting,
        "composition": composition,
        "negative": NEGATIVE_UNIVERSAL,
        "prompt": prompt,
        "style_id": style_id,
    }
