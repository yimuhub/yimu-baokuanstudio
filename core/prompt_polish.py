# SPDX-License-Identifier: BUSL-1.1
"""提示词优化（V14）。

输入一句随手写的话，输出一段可直接执行的创作提示词。

两条路径：
  1. 有可用大模型 → 交给模型改写（保留用户原意，只补结构与约束）；
  2. 模型不可用（未配 Key、断网、超时）→ 用固定骨架补全，并如实标注
     source="template"，前端会提示「已按结构模板补全（大模型暂不可用）」。
绝不假装模型成功，也绝不让按钮点了没反应。
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time

logger = logging.getLogger(__name__)

MAX_INPUT = 4000

# ── V14 交互体验：把「点了转半分钟没反应」摁死 ────────────────────────────
# 实测定位到的真凶不是网络，而是模型本身：
#   默认通道解析到 Sage-A1.5（推理型），不设 max_tokens 时会一路生成到上下文尽头，
#   设了 700 又把 token 全烧在 reasoning_content 上、正文 content 为空 ——
#   两种表现合起来就是「按钮转 35-45 秒，最后什么都没拿到，静默降级模板」。
# 对策四条：
#   1. 交互式短任务优先用「直出型」快模型（reasoning=0，实测 10s 出 230 字）；
#   2. max_tokens 封顶，杜绝无限续写；
#   3. 总时间预算 18s，超预算立刻收手走模板，绝不让请求无限滚下去；
#   4. 同文案 + 同平台结果缓存 10 分钟，重复点击瞬回。
# 换供应商时用环境变量 YIMU_POLISH_MODELS 覆盖模型链，不用改代码。
LLM_TIMEOUT_S = 12
LLM_MAX_TOKENS = 900
TOTAL_BUDGET_S = 18
CACHE_TTL_S = 600
CACHE_MAX = 64
MIN_TEXT_LEN = 40

PREFERRED_MODELS = [
    m.strip()
    for m in (os.environ.get("YIMU_POLISH_MODELS") or "").split(",")
    if m.strip()
]
# v15.9.1：出厂不再预置任何测试模型（Agnes 是测试通道）。空列表 = 只走
# 「默认通道」（活动供应商主模型）；运营想指定改写模型时设 YIMU_POLISH_MODELS。

_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()

PLATFORM_STYLE = {
    "xhs": ("小红书笔记", "口语化第一人称，短句＋表情，结尾 3-6 个话题标签"),
    "wechat_mp": ("微信公众号长文", "有分层小标题，观点与案例交替，结尾给可执行清单"),
    "toutiao": ("今日头条图文", "开头三句抛出冲突点，信息密度高，段落短"),
    "douyin": ("抖音口播脚本", "前 3 秒钩子，单句不超过 20 字，带镜头提示"),
    "bilibili": ("B 站专栏", "有信息增量与个人判断，允许长句与括号吐槽"),
}

SYSTEM_PROMPT = (
    "你是资深内容创作提示词工程师。用户会给你一句随手写的创作想法。"
    "请把它扩写成一段可直接交给写作 Agent 执行的中文提示词，要求：\n"
    "1. 保留用户原意与关键信息，不要替换主题，不要凭空编造事实与人名；\n"
    "2. 补齐这些维度：选题角度、目标读者、内容目标、结构、文风、字数、禁忌；\n"
    "3. 用自然段或短列表组织，不要输出解释、不要加「以下是」之类的前后缀；\n"
    "4. 直接给结果，不要复述要求，总长度控制在 160-260 字。"
)


def _cache_get(key: tuple[str, str]) -> dict | None:
    with _cache_lock:
        hit = _cache.get(key)
        if not hit:
            return None
        ts, val = hit
        if time.time() - ts > CACHE_TTL_S:
            _cache.pop(key, None)
            return None
        return dict(val)


def _cache_put(key: tuple[str, str], val: dict) -> None:
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            # 简单淘汰：清掉最早写入的一批，够用且不引依赖
            for k in list(_cache)[: max(1, CACHE_MAX // 4)]:
                _cache.pop(k, None)
        _cache[key] = (time.time(), dict(val))



def _clean(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = re.sub(r"^(以下是|这是)[^\n]{0,30}[:：]\s*", "", s)
    return s.strip()


def _chat_once(messages: list[dict], model: str | None, user_id: str, timeout_s: float) -> str:
    """走 llm.chat 拿正文；返回空串代表「这次没拿到可用内容」，由上层换下一个模型。"""
    from core import llm

    out = llm.chat(
        messages,
        model=model,
        temperature=0.6,
        timeout_s=timeout_s,
        user_id=user_id or None,
        max_tokens=LLM_MAX_TOKENS,
    )
    return _clean(out or "")


def _template(text: str, platform: str) -> str:
    name, style = PLATFORM_STYLE.get(platform, ("图文内容", "自然、具体、少套话"))
    topic = text.strip().replace("\n", " ")[:200]
    return (
        f"请帮我创作一篇{name}。\n\n"
        f"选题：{topic}\n"
        "目标读者：对该话题有兴趣、但还没系统了解的普通用户\n"
        "内容目标：给出可执行的信息增量，不停留在泛泛而谈\n"
        "结构：钩子开头 → 3 个核心要点（每点配一个具体例子或数据）→ 收束成行动建议\n"
        f"文风：{style}\n"
        "字数：800-1200 字\n"
        "硬性要求：不编造数据与来源；不用「首先/其次/最后」式套话；"
        "标题给 3 个备选，其中一个带数字或反差。"
    )


def polish(text: str, platform: str = "xhs", user_id: str = "") -> dict:
    raw = (text or "").strip()[:MAX_INPUT]
    if not raw:
        return {"text": "", "source": "empty"}

    ck = (raw, platform or "")
    cached = _cache_get(ck)
    if cached:
        cached["cached"] = True
        return cached

    name, style = PLATFORM_STYLE.get(platform, ("图文内容", "自然、具体、少套话"))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"平台：{name}（文风要求：{style}）\n原始想法：{raw}",
        },
    ]

    started = time.time()
    deadline = started + TOTAL_BUDGET_S
    tried: list[str] = []

    # 快模型优先，最后才轮到系统默认通道。None = 不指定，由 llm 解析默认模型。
    for model in [*PREFERRED_MODELS, None]:
        remain = deadline - time.time()
        if remain < 2:
            tried.append("<预算耗尽>")
            break
        label = model or "<默认通道>"
        try:
            cleaned = _chat_once(messages, model, user_id, min(LLM_TIMEOUT_S, remain))
        except Exception as e:  # 单个模型不可用不该拖垮整次调用
            tried.append(f"{label}: 异常 {type(e).__name__}")
            logger.info("[prompt_polish] 模型 %s 调用异常，换下一个: %s", label, e)
            continue
        if len(cleaned) >= MIN_TEXT_LEN:
            logger.info(
                "[prompt_polish] 模型 %s 改写完成 %.2fs / %d 字",
                label, time.time() - started, len(cleaned),
            )
            result = {"text": cleaned, "source": "llm", "model": label}
            _cache_put(ck, result)
            return dict(result)
        tried.append(f"{label}: 正文过短({len(cleaned)}字)")
        logger.info("[prompt_polish] 模型 %s 未给出可用正文(%d 字)，换下一个", label, len(cleaned))

    logger.info(
        "[prompt_polish] 全部模型未产出，降级模板补全，用时 %.2fs，尝试记录: %s",
        time.time() - started, "; ".join(tried),
    )
    return {"text": _template(raw, platform), "source": "template", "tried": tried}
