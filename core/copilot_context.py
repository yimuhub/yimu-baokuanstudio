# SPDX-License-Identifier: BUSL-1.1
"""Copilot 对话上下文组装（R10.0 从 966 行上帝函数中抽出的第一块缝）。

===========================================================================
拆分说明
===========================================================================
``core.copilot.handle_copilot_chat`` 历史上把「意图识别 → 上下文组装 →
技能注入 → LLM 调用 → 草稿回写」全部塞在一个 967 行的函数里，无法单测。
本模块先把**自包含的上下文组装阶段**抽出来：

- 名家大师人设（persona）注入
- 五种文风调性（style）映射
- 爆款技能库（skills）注入（含工作区默认技能回退）
- 目标模型解析（provider/model 组合）
- LLM 调用工厂（指定模型 or 走 write 岗位 Agent）

行为与历史版本逐字节一致（skills 注入文案、组装顺序均未改动），
由 tests 既有 copilot 用例回归保障。
"""
from __future__ import annotations

from typing import Callable, Optional

__all__ = [
    "STYLE_MAP",
    "build_system_prompt",
    "resolve_target_model",
    "make_llm_call",
    "build_chat_context",
]

#: 五种预置文风调性（历史文案原样保留，勿改字——有测试锚定行为）
STYLE_MAP: dict[str, str] = {
    "wangxiaobo": "【文风调性：王小波幽默犀利】用幽默、清醒、反讽、极度真诚的口吻写作，善用日常生活比喻，彻底破除AI套话与官腔。",
    "xhs_seed": "【文风调性：小红书爆款短句种草】短句成行，高密度emoji，突出痛点场景与即时获得感，文末附带热门互动话题标签。",
    "deep_resonance": "【文风调性：深度情感共鸣】叙事细腻，直击当代人内心孤独与焦虑，层层递进，金句频出，引发强烈共鸣与转发欲。",
    "dry_goods": "【文风调性：避坑干货清单】条理极度清晰，拒绝废话，提炼核心要点、避坑法则与即拿即用的SOP清单。",
    "story_conflict": "【文风调性：电影级戏剧冲突】强悬念开场，节奏跌宕起伏，通过具体的场景、动作和对白展现反转与冲突。",
}


def build_system_prompt(
    base_prompt: str,
    persona: Optional[str],
    style: Optional[str],
    skills: Optional[list],
) -> tuple[str, list[str]]:
    """组装系统提示词：名家文风 / 预置调性 / 爆款技能注入。

    Returns:
        ``(active_sys_prompt, skills_applied_names)``
    """
    active = base_prompt
    if persona:
        from core import orchestrator

        voice_content = orchestrator.get_voice_content(persona)
        if voice_content:
            active += f"\n\n【名家大师人设与文风指纹（强制遵循）】\n{voice_content}"
    elif style and style != "default":
        if style in STYLE_MAP:
            active += f"\n\n{STYLE_MAP[style]}"

    # 爆款技能库注入（如黄金钩子、去AI味、反差认知洞察、金句提炼等）
    from core import agents, workspace

    active_ws = workspace.get_active_workspace()
    ws_cfg = (active_ws.get("config") if active_ws else {}) or {}
    applied_skills = skills or ws_cfg.get("skills") or [
        "viral-formulas", "de-ai", "contrarian-insight", "title-forge",
    ]

    applied_names: list[str] = []
    if applied_skills:
        from core.copilot import skill_display_name  # R11 融合:技能中文名映射

        skill_lib = agents.list_skills()
        sk_parts = []
        for sk_id in applied_skills:
            sk_obj = skill_lib.get(sk_id)
            if sk_obj and sk_obj.get("body"):
                _disp = skill_display_name(sk_obj)
                sk_parts.append(
                    f"◆ 技能【{_disp}】：{sk_obj.get('description', '')}\n{sk_obj['body']}"
                )
                applied_names.append(_disp)
        if sk_parts:
            active += ("\n\n【创作者专属爆款创作与改写技能规范（必须严格调用贯彻）】：\n"
                       + "\n\n".join(sk_parts))
    return active, applied_names


def resolve_target_model(provider: Optional[str], model: Optional[str]) -> Optional[str]:
    """把「供应商 + 模型」组合为目标模型串；__default__ 视为未指定。

    v15.9.1 修复：只选供应商不选模型时，旧实现返回裸 ``"provider"``——
    解析器把它当模型名去匹配，必然失配后静默回落主模型，用户的选择等于没选。
    现在补上该供应商的默认主模型（预设 default_model 或用户池内保存的 model），
    让「指定供应商」真正生效。
    """
    if provider and provider != "__default__":
        if model and model != "__default__":
            return f"{provider}/{model}"
        # 只选了供应商：补默认模型，形如 "deepseek/deepseek-chat"
        try:
            from core import llm
            saved = llm.load_config().get("gateway", {}).get("providers", {}).get(provider, {}) or {}
            default_m = (saved.get("model") or "").strip() \
                or str(llm.MODEL_PROVIDERS.get(provider, {}).get("default_model") or "").strip()
            if default_m:
                return f"{provider}/{default_m}"
        except Exception:
            pass
        return f"{provider}"
    if model and model != "__default__":
        return model
    return None


def make_llm_call(target_model: Optional[str], user_id: Optional[str]) -> Callable[[list[dict], float], str]:
    """返回闭包：指定模型走 llm.chat，否则走 write 岗位 Agent。"""
    from core import agents, llm

    def _call_llm(msgs: list[dict], temp: float = 0.75) -> str:
        if target_model:
            return llm.chat(msgs, model=target_model, temperature=temp, user_id=user_id)
        return agents.chat_for("write", msgs, temperature=temp, user_id=user_id)

    return _call_llm


def build_chat_context(
    base_prompt: str,
    *,
    persona: Optional[str] = None,
    style: Optional[str] = None,
    skills: Optional[list] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """一次性组装 Copilot 对话上下文（handle_copilot_chat 的前置阶段）。"""
    sys_prompt, applied_names = build_system_prompt(base_prompt, persona, style, skills)
    target_model = resolve_target_model(provider, model)
    return {
        "sys_prompt": sys_prompt,
        "skills_applied_names": applied_names,
        "target_model": target_model,
        "call_llm": make_llm_call(target_model, user_id),
    }
