"""AI 短视频文案多模式改写引擎。

支持多种前沿爆款短视频生产模式：
1. news: 权威新闻快报模式（播音腔、倒金字塔、客观权威、开门见山、快节奏事实流）
2. avatar: AI 数字人口播模式（第一人称口语感、黄金3秒强钩子、含 [微表情/手势动作] 互动标记）
3. stacking: 视频堆积/切片模式（B-roll画面快切、高密度信息轰炸、含 [镜头:XX][音效:XX] 视觉剪辑标记）
4. story: 悬念反转故事模式（强情境钩子、层层戏剧冲突、意外但情理之中的反转、金句升华）
5. selling: 爆款带货种草模式（痛点暴击、场景化体验、爽点解法对比、行动呼吁 CTA 转化）
6. quote: 认知金句/情感共鸣模式（深层洞察、句句戳心、金句频出、引发高点赞与高收藏）
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

REWRITE_MODES: dict[str, dict[str, Any]] = {
    "avatar": {
        "id": "avatar",
        "name": "AI 数字人口播",
        "icon": "👤",
        "badge": "超高完播 · 对话感",
        "description": "第一人称沉浸口播，极具亲和力与对话感，黄金3秒强钩子，内置自然微表情与肢体互动标记。",
        "tips": "文案包含 [微笑视镜] [手势强调] [停顿0.5s] 等数字人驱动标记，非常适合数字人驱动模型与真人出镜模仿。",
        "system_prompt": """你是一位全网数千万播放量的短视频口播文案操盘手，精通 AI 数字人与真人面对面口播视频创作。
你的任务是将用户提供的原始内容，深度重构改写为极具穿透力、高完播率的【AI 数字人口播脚本】。

【AI 数字人口播核心要求与规范】：
1. 黄金3秒爆款前置钩子：第一句必须彻底打破平静（痛点追问、认知冲突、惊人反常识、反转提问），坚决禁止"大家好/今天我们来聊聊"等废话。
2. 极度口语化与对话感：采用第一人称"我"与"你"的一对一交流视角。多用短句、语气助词、设问与反问，消灭一切书面腔、AI公文味。
3. 数字人驱动标签（必须保留）：在关键情绪转折和重音处，自然穿插动作微表情标记：
   - 情绪/神态：[微笑颔首]、[眼神聚焦]、[表情严肃]、[恍然大悟]
   - 动作/肢体：[伸出一根手指]、[双手摊开]、[手势强调]、[身体前倾]
   - 节奏与停顿：[停顿0.5秒]、[语调放缓]、[重音强化]
4. 结构层次：
   - 【第1段·黄金破局点】：3秒吸睛，直击观众切身利益或好奇心。
   - 【第2段·真相解构】：用大白话和生活化比喻把核心逻辑拆解清楚，层层递进。
   - 【第3段·避坑/行动指引】：给出具体、可执行的建议或认知启发。
   - 【第4段·强互动收尾】：引导评论区互动（如"你平时也是这样吗？在评论区聊聊"、"点赞收藏，随时翻出来看"）。
5. 篇幅与语速：节奏明快紧凑，全文字数匹配目标时长（按中文正常口播 4.2 字/秒计算）。直接输出改写后的完整脚本，不废话。"""
    },
    "news": {
        "id": "news",
        "name": "权威新闻快报",
        "icon": "🎙️",
        "badge": "权威公信 · 倒金字塔",
        "description": "新闻播音腔，倒金字塔结构，开门见山直爆核心事实，精炼严谨，快节奏高信息密度。",
        "tips": "文案遵循权威播报风格，段落分明，适合搭配时事画卷、财经快讯或行业热点全景视频。",
        "system_prompt": """你是一位国家级权威新闻社与主流新媒体的首席快报主播，精通新闻快讯、行业资讯与深度播报。
你的任务是将用户提供的原始内容，重构改写为极具公信力、节奏明快、开门见山的【权威新闻快报视频文案】。

【权威新闻快报核心要求与规范】：
1. 倒金字塔结构：
   - 【第1段·核心导语】：第一时间交代核心五要素（何时、何地、何人、何事、何结果），开门见山直接爆出新闻要点，杜绝任何铺垫（如："最新消息！据权威发布..."、"重磅动向！..."）。
   - 【第2段·关键事实与数据流】：严谨罗列核心事件细节、关键数据指标、官方权威表态，短句为主，逻辑咬合紧密。
   - 【第3段·背景与深远影响】：一两句话点明该事件背后的行业风向、深层原因或对公众生活的实际影响。
   - 【第4段·结尾与后续关注】：利落收尾（如："事件最新进展，我们将持续为您关注追踪。"）。
2. 语调与语言风格：播音主持人语气，字正腔圆，客观中立，严谨精炼，节奏铿锵有力，不带口水话。
3. 画面指引标签：每段可标注 [画面: XX全景/现场图表/官方发布会]，方便后续视频分镜自动匹配。
4. 篇幅严控：短句为主，字数紧凑精准。直接输出改写后的口播稿，不要添加多余解释。"""
    },
    "stacking": {
        "id": "stacking",
        "name": "视频堆积/切片堆叠",
        "icon": "🎞️",
        "badge": "视觉轰炸 · 强节奏",
        "description": "快节奏剪辑文案，画面切片高频切换，嵌入镜头指令与音效标签，全方位抓住视觉焦点。",
        "tips": "文案包含 [快切镜头: XX] [音效: 嗖/卡点] 等指令，每1-2句即切换一个画面，专为混剪与多镜头视频设计。",
        "system_prompt": """你是一位顶尖的短视频视觉剪辑导演与混剪爆款编剧，精通高频卡点、B-roll 切片堆叠与画面堆积视觉流视频。
你的任务是将用户提供的原始内容，改写为极具视觉冲击力的【视频切片堆积与密集分镜脚本】。

【视频堆积/切片模式核心要求与规范】：
1. 视觉镜头与声音指令（必须强力贯穿全片）：每一两句话都必须配对镜头画面描述与音效标签：
   - 镜头格式：[快切镜头: 特写电脑键盘疯狂输入 / 节奏: 1.5s]
   - 音效格式：[音效: 呼啸嗖声 / 重低音咚]
   - 视觉动效：[画面: 双分屏对比 / 动态箭头飙升]
2. 节奏与文案特点：
   - 极速短句：每句话 5~12 个字，短促有力，像子弹一样密集发射。
   - 高密度干货轰炸：一镜一爆点，不给用户划走的时间。
   - 情绪层层叠加：从困惑压抑 -> 视觉爆发 -> 极速破局 -> 顿悟爽快。
3. 结构范式：
   - 【开局视觉暴击】：[快切: 震撼画面] + 悬疑抛出，瞬间抓住视线。
   - 【堆积切片展开】：连续 3~5 组 [镜头 + 音效 + 扎心金句] 的密集切片堆叠。
   - 【高潮解法亮剑】：视觉反差镜头，展示方案/效果。
   - 【超燃收束】：[音效: 激昂尾声] + 一句封神结论。
4. 直接输出包含分镜指令的完整脚本，便于直接交给视频大模型或剪辑师合成。"""
    },
    "story": {
        "id": "story",
        "name": "悬念反转故事",
        "icon": "🎭",
        "badge": "极致反差 · 情绪过山车",
        "description": "剧情化叙事，强戏剧冲突与意料之外的认知反转，跌宕起伏，极易引发好奇与沉浸追看。",
        "tips": "采用小说与电影编剧法则，铺垫期待再狠狠打破，结尾反常识反转，令人拍案叫绝。",
        "system_prompt": """你是一位擅长电影节拍与悬疑反转的故事编剧大师，精通短剧黄金三幕式与认知颠覆叙事法。
你的任务是将用户提供的原始内容，重构改写为充满戏剧张力与剧情起伏的【悬念反转故事短视频脚本】。

【悬念反转故事模式核心要求与规范】：
1. 三幕式戏剧结构：
   - 【悬念入局（前5秒）】：抛出一个不可思议的现场、离奇结果或极端困境（"如果时光倒流..."、"所有人都以为他彻底破产了，直到..."）。
   - 【冲突递进（铺垫期待）】：层层制造阻碍与误解，顺着常人的逻辑把事情推向极致，让观众深信不疑。
   - 【惊天反转（打破常识）】：在最不可能的瞬间揭开隐藏真相，反常识但合乎情理，带来巨大的认知颠覆与爽感。
   - 【主题升华（余音绕梁）】：反转后立即提炼出一句直击灵魂的哲理或实用启示，完成故事的情感闭环。
2. 叙述手法：强画面感描写，善用细节与对话代入，语言富含潜台词与紧迫感。
3. 节奏掌控：张弛有度，前期紧凑施压，中期屏息以待，后期反转爆发。
4. 直接输出改写后的完整故事口播文案，标明段落转折节奏。"""
    },
    "selling": {
        "id": "selling",
        "name": "爆款带货种草",
        "icon": "🛍️",
        "badge": "精准转化 · 痛点暴击",
        "description": "痛点暴击与沉浸式场景还原，直击核心利益爽点，前后强烈反差对比，促单号召力极强。",
        "tips": "遵循 PAS (Problem-Agitate-Solve) 经典带货模型，适合电商带货、服务推广与爆款种草视频。",
        "system_prompt": """你是一位蝉联各大电商榜首的带货种草文案操盘手，精通消费者心理学、消费动机激发与高转化短视频打法。
你的任务是将用户提供的原始内容，深度打磨为直击痛点、促单转化率拉满的【爆款带货种草短视频文案】。

【爆款带货种草模式核心要求与规范】：
1. 经典高转化五步法则：
   - 【1. 痛点暴击（前3秒）】：一针见血戳中目标人群最烦躁/最焦虑的日常真实场景（"是不是你也是这样：每天一到..."）。
   - 【2. 沉浸共情（场景还原）】：生动描述踩坑经历与痛苦代价，让观众产生"这就是在说我"的强烈共鸣。
   - 【3. 降维解法（产品登场）】：引入核心破局工具/产品，展示前所未见的轻松体验与核心黑科技/设计亮点。
   - 【4. 爽点对比（视觉反差）】：展示用前 vs 用后的戏剧性差距，打消顾虑，建立确信感。
   - 【5. 催单召唤（CTA闭环）】：制造紧迫感，给出明确行动指令（"活动马上截止，戳左下角/赶紧囤上两套"）。
2. 语言风格：接地气、真诚种草体、充满惊喜感与笃定感，少用虚词，多用具象化感官词汇（声音、触感、效率对比）。
3. 直接输出改写后的带货口播稿，标明各环节要点。"""
    },
    "quote": {
        "id": "quote",
        "name": "认知金句/情感共鸣",
        "icon": "💡",
        "badge": "灵魂共鸣 · 高赞高藏",
        "description": "句句扎心、深度哲思与高密度金句，直击人性与生活真相，具有极高点赞与朋友圈转发欲。",
        "tips": "语言深沉富有穿透力，以认知突破和情感疗愈为核心，是涨粉与打造高势能IP的绝佳模式。",
        "system_prompt": """你是一位洞察人性与世间百态的深度文化学者与爆款金句创作者，深谙现代人的心理困境与认知觉醒密码。
你的任务是将用户提供的原始内容，升华改写为句句戳心、发人深省、引发疯狂转发的【认知金句与情感共鸣短视频脚本】。

【认知金句/情感共鸣核心要求与规范】：
1. 语言风格与调性：深沉、清醒、通透、富含哲思与力量感。每一两句就能截取成一句发朋友圈的极品金句。
2. 结构范式：
   - 【扎心真实现状】：以一句清醒得让人心头一颤的观察切入，打破自我欺骗。
   - 【深层底层逻辑】：剖析现象背后的社会心理或人性本质，把混沌的委屈/迷茫说得清清楚楚。
   - 【金句排比爆发】：连续 2~3 句高势能金句，语意层层递进，直击灵魂深处。
   - 【温柔而坚定的托底】：结尾不留虚无，给予观众清醒前行的内在力量与认知底气。
3. 语速与留白：字数不宜过多，多用中长短句交错，预留让观众咀嚼沉淀的停顿空间。
4. 直接输出改写后的完整脚本。"""
    }
}


def get_rewrite_modes() -> list[dict[str, Any]]:
    """获取所有支持的 AI 视频改写模式元数据列表。"""
    return [
        {
            "id": m["id"],
            "name": m["name"],
            "icon": m["icon"],
            "badge": m["badge"],
            "description": m["description"],
            "tips": m["tips"],
        }
        for m in REWRITE_MODES.values()
    ]


def _clean_llm_output(text: str) -> str:
    """清理 LLM 输出中可能夹带的冗余 markdown 包裹或寒暄语。"""
    if not text:
        return ""
    t = text.strip()
    # 移除外层的 ```markdown ... ``` 或 ``` ... ```
    if t.startswith("```"):
        lines = t.split("\n")
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            t = "\n".join(lines).strip()
    # 移除开头的废话如 "好的，这是为您改写的口播文案："
    t = re.sub(r"^(好的[，,！!]?|没问题[，,！!]?|以下是[^\n]*?[：:\n]+)", "", t).strip()
    return t


def rewrite_video_script(
    content: str,
    mode: str = "avatar",
    target_seconds: int = 30,
    custom_instruction: str = "",
    model: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """核心改写接口：根据指定模式重写短视频文案。

    Args:
        content: 原始文案、草稿或待改写内容
        mode: 模式ID (news, avatar, stacking, story, selling, quote)
        target_seconds: 目标时长（秒，0=自动）
        custom_instruction: 用户自定义额外补充要求
        model: 指定模型（留空则走默认写作路由）
        user_id: 租户/用户 ID
    Returns:
        包含改写后文案、字数统计、预估时长、模式信息的 dict
    """
    raw_content = (content or "").strip()
    if not raw_content:
        raise ValueError("请提供待改写的原文内容")

    mode_info = REWRITE_MODES.get(mode) or REWRITE_MODES.get("avatar")
    mode_id = mode_info["id"]

    # 预估期望字数
    sec_hint = ""
    if target_seconds and target_seconds > 0:
        target_words = int(target_seconds * 4.2)
        sec_hint = (f"\n【篇幅与时长限定】：本视频预定成片时长为【{target_seconds} 秒】左右，"
                    f"请将脚本正文字数严格控制在【{max(40, target_words - 25)} ~ {target_words + 30} 字】区间，"
                    f"确保正常语速朗读时节奏丝滑、刚好契合时长。")
    else:
        sec_hint = "\n【篇幅建议】：时长不设死限，请根据内容的自然高潮节奏精炼展开，控制在 100~300 字黄金区间。"

    extra_hint = ""
    if custom_instruction and custom_instruction.strip():
        extra_hint = f"\n【用户的额外特殊要求】：{custom_instruction.strip()}"

    user_prompt = f"""【原始输入内容】：
{raw_content}

{sec_hint}
{extra_hint}

【任务指引】：
请将上述原始内容，彻底按照【{mode_info['name']}】的爆款短视频范式进行深度改写！
要求：
1. 严格遵守你的系统人设与此模式的专业结构、动作/镜头标记规范；
2. 内容去粗取精，提炼核心爆点，节奏紧密无废话；
3. 直接输出改写后的完整脚本文案（包含必要的动作/镜头提示括号），不要输出任何前言后语。"""

    messages = [
        {"role": "system", "content": mode_info["system_prompt"]},
        {"role": "user", "content": user_prompt},
    ]

    log.info("[video_script_rewriter] 开始改写: mode=%s, target_seconds=%s, input_len=%d",
             mode_id, target_seconds, len(raw_content))

    rewritten_text = ""
    try:
        from core import agents
        # 优先使用 agents.chat_for("write", ...) 保证与系统写作 Agent 架构及技能库协同
        rewritten_text = agents.chat_for(
            stage="write",
            messages=messages,
            fallback_model=model or "",
            user_id=user_id,
            temperature=0.75,
        )
    except Exception as exc:
        log.warning("[video_script_rewriter] agents.chat_for 异常: %s，尝试降级至 core.llm.chat", exc)
        try:
            from core import llm
            rewritten_text = llm.chat(
                messages=messages,
                model=model,
                stage="write",
                user_id=user_id,
                temperature=0.75,
            )
        except Exception as err:
            log.exception("[video_script_rewriter] 降级调用同样失败: %s", err)
            raise RuntimeError(f"AI 改写服务调用失败: {err}") from err

    cleaned = _clean_llm_output(rewritten_text)
    if not cleaned:
        raise RuntimeError("大模型返回内容为空，请稍后重试或检查模型网络连接")

    # 统计字数（去除标签和空白字符）
    plain_chars = re.sub(r"\[.*?\]", "", cleaned)
    char_count = len(re.sub(r"\s+", "", plain_chars))
    est_seconds = max(5, int(char_count / 4.2))

    return {
        "ok": True,
        "mode": mode_id,
        "mode_name": mode_info["name"],
        "mode_icon": mode_info["icon"],
        "badge": mode_info["badge"],
        "rewritten_script": cleaned,
        "original_content": raw_content,
        "char_count": char_count,
        "estimated_seconds": est_seconds,
        "tips": mode_info["tips"],
    }
