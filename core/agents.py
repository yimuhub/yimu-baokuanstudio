"""阶段化 Agent 体系：每个阶段独立模型 + 独立技能 + 独立指令。

阶段：collect 采集 / analyze 拆解 / write 写作 / image 配图 / layout 排版 / review 评审
技能库：skills/agents/*.md（frontmatter: name/description，正文=注入 prompt 的技能文本）
配置：config.yaml agents.{stage} = {model, skills: [name], instruction}
"""
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE / "skills" / "agents"

CONTENT_STAGES = {
    "collect": "采集 Agent（热榜/搜索数据获取）",
    "analyze": "拆解 Agent（爆款结构分析）",
    "write": "写作 Agent（成稿/仿写/重写）",
    "image": "配图 Agent（生图提示词与模型）",
    "layout": "排版 Agent（主题化渲染）",
    "review": "评审 Agent（多维打分）",
}

DRAMA_STAGES = {
    "director": "🎬 导演 Agent（剧本分析/节拍掌控/戏剧冲突）",
    "character_designer": "🎨 角色设计师 Agent（人物一致性/四视图设计）",
    "storyboard_artist": "📐 分镜师 Agent（景别机位/影视镜头解构）",
    "cinematographer": "🎥 摄影与动效 Agent（光影提示词/运镜动态）",
    "sound_designer": "🎧 声音总监 Agent（配音角色/BGM与情绪混音）",
}

AD_STAGES = {
    "ad_creative": "📢 广告创意分析 Agent（卖点提炼/广告脚本/竞品拆解/成片评估）",
    "ad_video": "🎬 广告视频生成 Agent（视频大模型/分镜转视频/运镜控制）",
}

STAGES = {**CONTENT_STAGES, **DRAMA_STAGES, **AD_STAGES}

STAGE_DEFAULT_SKILLS = {
    "director": ["director-beat-sheet"],
    "character_designer": ["character-turnaround-sheet"],
    "storyboard_artist": ["storyboard-visual-grammar"],
    "cinematographer": ["cinematic-optics-lighting"],
    "sound_designer": ["sound-director-scoring"],
    "ad_creative": ["ad-video-creative", "ad-reverse-engineer",
                    "ad-creative-evaluator", "ad-category-playbook"],
    "ad_video": ["ad-video-prompt-craft"],
}


def load_config() -> dict:
    with open(BASE / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def agents_cfg() -> dict:
    cfg = load_config().get("agents", {})
    out = {}
    for stage in STAGES:
        a = cfg.get(stage, {}) or {}
        def_skills = STAGE_DEFAULT_SKILLS.get(stage, [])
        skills = a.get("skills")
        if skills is None:
            skills = def_skills
        out[stage] = {
            "model": a.get("model", ""),
            "skills": skills,
            "instruction": a.get("instruction", "")
        }
    return out


def list_skills() -> dict:
    """读取所有技能文件及其 frontmatter 元数据：{id: {"name","description","category","scope","icon","body"}}

    ⭐ 性能：结果按目录 mtime 缓存，技能文件增删改时自动失效。
    技能库页面/Copilot/改写链高频调用此函数，缓存后单次调用从 ~50ms 降至 <1ms。
    """
    global _skills_cache
    try:
        if SKILLS_DIR.exists():
            files = list(SKILLS_DIR.glob("*.md"))
            # 目录 mtime 只反映增删，文件 mtime 反映内容修改，两者都要
            dir_mtime = SKILLS_DIR.stat().st_mtime
            max_file_mtime = max((f.stat().st_mtime for f in files), default=0)
            cache_key = (dir_mtime, len(files), max_file_mtime)
        else:
            cache_key = (0, 0, 0)
    except OSError:
        cache_key = None
    if cache_key is not None and _skills_cache.get("key") == cache_key:
        return _skills_cache["data"]
    out = _read_skills_from_disk()
    if cache_key is not None:
        _skills_cache = {"key": cache_key, "data": out}
    return out


_skills_cache: dict = {}


def _read_skills_from_disk() -> dict:
    """从磁盘读取所有技能文件（list_skills 的实际 IO 部分）。"""
    out = {}
    if SKILLS_DIR.exists():
        for f in sorted(SKILLS_DIR.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            name, desc, body = f.stem, "", text
            category = "通用技能"
            scope = "writing"
            icon = "⚡"
            if text.startswith("---"):
                try:
                    _, fm, body = text.split("---", 2)
                    meta = yaml.safe_load(fm) or {}
                    name = meta.get("name", f.stem)
                    desc = meta.get("description", "")
                    category = meta.get("category", "通用技能")
                    scope = meta.get("scope", "writing")
                    icon = meta.get("icon", "⚡")
                except Exception:
                    pass
            out[f.stem] = {
                "id": f.stem,
                "name": name,
                "description": desc,
                "category": category,
                "scope": scope,
                "icon": icon,
                "body": body.strip()
            }
    return out


def get_catalog_skills() -> list[dict]:
    """返回规范化的技能库目录列表，供工作区绑定。
    
    scope:
      "writing" — 写作/内容提升专用，显示在 AI 改写弹框和工作室写作技能区
      "video"   — 影音/短剧专用，只显示在影音工坊相关面板
      "both"    — 写作与影音双用途，两处均可显示
    """
    raw = list_skills()
    icons = {
        "title-forge": "✍️",
        "de-ai": "🧠",
        "viral-copy": "🚀",
        "viral-formulas": "📈",
        "xhs-style": "📕",
        "colloquial": "🗣️",
        "x-thread-viral": "𝕏",
        "visual-hierarchy-layout": "📐",
        "contrarian-insight": "💡",
        "user-evolving-habit": "🧠",
        "storyboard-visual-grammar": "🎬",
        "cinematic-optics-lighting": "🎭",
        "sound-director-scoring": "🎧",
        "judge-strict": "⚖️",
        "heritage-narrative": "🏮",
        "query-expand": "🔍",
        "pro-writing": "📝",
        "pro-layout": "📰",
        "character-turnaround-sheet": "📐",
        "director-beat-sheet": "🎞️",
        "王家卫式独白": "🎭",
    }
    categories = {
        "title-forge": "爆款转化",
        "viral-copy": "爆款转化",
        "viral-formulas": "爆款转化",
        "x-thread-viral": "平台特色",
        "xhs-style": "平台特色",
        "de-ai": "文风调优",
        "colloquial": "文风调优",
        "contrarian-insight": "认知穿透",
        "user-evolving-habit": "自主进化",
        "pro-writing": "深度长文",
        "pro-layout": "排版美学",
        "visual-hierarchy-layout": "排版美学",
        "storyboard-visual-grammar": "短剧影音",
        "cinematic-optics-lighting": "短剧影音",
        "sound-director-scoring": "短剧影音",
        "character-turnaround-sheet": "短剧影音",
        "director-beat-sheet": "短剧影音",
        "heritage-narrative": "特色母语",
        "judge-strict": "品控质检",
        "query-expand": "全网溯源",
        "王家卫式独白": "文风调优",
    }
    scopes = {
        "title-forge": "writing",
        "de-ai": "writing",
        "viral-copy": "writing",
        "viral-formulas": "writing",
        "xhs-style": "writing",
        "x-thread-viral": "writing",
        "colloquial": "writing",
        "contrarian-insight": "writing",
        "user-evolving-habit": "writing",
        "pro-writing": "writing",
        "pro-layout": "writing",
        "visual-hierarchy-layout": "writing",
        "heritage-narrative": "writing",
        "judge-strict": "writing",
        "query-expand": "writing",
        "王家卫式独白": "both",
        "storyboard-visual-grammar": "video",
        "cinematic-optics-lighting": "video",
        "sound-director-scoring": "video",
        "character-turnaround-sheet": "video",
        "director-beat-sheet": "video",
    }
    result = []
    for k, v in raw.items():
        # 优先读取 frontmatter，未定义则降级至预设字典
        cat = v.get("category") if v.get("category") != "通用技能" else categories.get(k, "通用技能")
        sc = v.get("scope") if v.get("scope") else scopes.get(k, "writing")
        ic = v.get("icon") if v.get("icon") != "⚡" else icons.get(k, "⚡")
        result.append({
            "id": k,
            "name": v.get("name") or k,
            "description": v.get("description") or "",
            "icon": ic,
            "category": cat,
            "scope": sc,
        })
    return result



def skills_for(stage: str) -> list[str]:
    return agents_cfg().get(stage, {}).get("skills", [])


ROUTING_STAGE_MAP = {
    "write": "writer",
    "analyze": "analyzer",
    "review": "critic",
    "director": "drama",
    "character_designer": "drama",
    "storyboard_artist": "drama",
    "cinematographer": "drama",
    "sound_designer": "drama",
    "image": "image",
    "video": "video",
}


def model_for(stage: str, default: str = "") -> str:
    """获取指定阶段生效的模型ID。
    优先级：
    1. agents.{stage}.model 显式指定的值（非空）
    2. gateway.agent_routing 中该阶段对应的分工路由模型（非空）
    3. default 参数（若非空）
    4. gateway.model 全局活动主模型
    """
    cfg = load_config()
    a_model = cfg.get("agents", {}).get(stage, {}).get("model", "").strip()
    if a_model:
        return a_model

    routing_key = ROUTING_STAGE_MAP.get(stage)
    if routing_key:
        r_model = cfg.get("gateway", {}).get("agent_routing", {}).get(routing_key, "").strip()
        if r_model:
            return r_model

    if default:
        return default

    gw_model = cfg.get("gateway", {}).get("model", "").strip()
    if gw_model:
        return gw_model

    return "deepseek-chat"


def compose_system(stage: str, base_prompt: str) -> str:
    """base + 已分配技能文本 + 阶段自定义指令。"""
    skill_lib = list_skills()
    parts = [base_prompt]
    for name in skills_for(stage):
        sk = skill_lib.get(name)
        if sk:
            parts.append(f"【技能·{sk['name']}】{sk['description']}\n{sk['body']}")
    inst = agents_cfg().get(stage, {}).get("instruction", "")
    if inst:
        parts.append(f"【本阶段特别要求】{inst}")
    return "\n\n".join(parts)


def chat_for(stage: str, messages: list[dict], fallback_model: str = "", **kw) -> str:
    """按阶段的模型与技能调用 LLM，自动感知跨供应商与平滑回退。"""
    from core import llm
    sys = compose_system(stage, "")
    msgs = list(messages)
    if sys:
        if msgs and msgs[0].get("role") == "system":
            msgs[0] = {"role": "system", "content": msgs[0]["content"] + "\n\n" + sys}
        else:
            msgs = [{"role": "system", "content": sys}] + msgs
    target_m = model_for(stage, fallback_model)
    return llm.chat(msgs, model=target_m, stage=stage, **kw)

