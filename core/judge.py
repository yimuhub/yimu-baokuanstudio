"""LLM-as-Judge 多维评分（7 维 100 分制）+ 平台差异化评分体系。

通用维度：标题钩子15 / 内容价值25 / 结构逻辑15 / 语言风格15 / 图文配合15 / 排版可读10 / 互动潜力5
等级：<75 不合格（自动重写）｜75-84 合格｜85-94 良好｜≥95 优秀

v3.33新增：平台差异化评分体系
- 微信公众号(wechat_mp)：深度、逻辑、品牌感权重更高
- 小红书(xhs)：颜值、口语化、标签、互动权重更高
- 今日头条(toutiao)：信息量、标题点击率权重更高
- 微博(weibo)：热点关联、简洁感、互动权重更高
- 知乎(zhihu)：专业深度、逻辑严密权重更高
- 推特/X(twitter)：简洁金句、话题标签、英文适配权重更高
"""
import json
import re

from core import agents, db, llm

DIMENSIONS = [
    ("title", "标题钩子", 15, "数字/悬念/身份代入等钩子是否有力，长度与平台适配"),
    ("value", "内容价值", 25, "信息增量、干货密度、真实可信、与主题契合度"),
    ("structure", "结构逻辑", 15, "钩子→共鸣→干货→CTA 是否完整，段落功能是否清晰"),
    ("style", "语言风格", 15, "活人感、无AI味、平台语感（小红书口语化/公众号有深度）"),
    ("visual", "图文配合", 15, "配图与段落相关性、卡片节奏、封面吸引力"),
    ("layout", "排版可读", 10, "分节/列表/长度合规/留白节奏"),
    ("cta", "互动潜力", 5, "CTA 明确、能引导评论/收藏/转发"),
]

# 平台差异化评分标准（覆盖通用评分的特殊评审角度）
PLATFORM_TIPS = {
    "wechat_mp": (
        "当前评审平台：微信公众号。\n"
        "重点关注：① 深度叙事与品牌调性（value权重+3）；② 标题悬念感（title权重+2）；"
        "③ 正文结构完整（钩子→共鸣→干货→CTA）；④ 图文配合（visual）。\n"
        "扣分项：段落太长/无分节、无故事切入、AI味重、过于口语化。"
    ),
    "xhs": (
        "当前评审平台：小红书。\n"
        "重点关注：① 口语化短句、表情符号节奏（style权重+3）；② 封面和配图吸引力（visual权重+2）；"
        "③ 话题标签质量（cta权重+2）；④ 标题20字内、含颜文字或数字钩子。\n"
        "扣分项：段落过长、无标签、用词书面化、无封面设计感。"
    ),
    "toutiao": (
        "当前评审平台：今日头条。\n"
        "重点关注：① 标题点击率（title权重+4，必须含数字/问题/反转）；"
        "② 信息量与权威感（value权重+3）；③ 头图吸引力（visual+1）。\n"
        "扣分项：标题无数字/疑问/反转、内容空洞、段落过多嵌套。"
    ),
    "weibo": (
        "当前评审平台：微博。\n"
        "重点关注：① 热点关联与话题感（value+2）；② 简洁有力、金句密度（style+3）；"
        "③ 互动引导（cta+2）；④ 情绪共鸣。\n"
        "扣分项：内容过长（超800字扣分）、话题标签缺失、无金句。"
    ),
    "zhihu": (
        "当前评审平台：知乎。\n"
        "重点关注：① 专业深度与论据充分（value权重+5）；② 逻辑严密、结构清晰（structure+3）；"
        "③ 引用数据/案例（style+2）。\n"
        "扣分项：无论据支撑、结论武断、口语化过重。"
    ),
    "twitter": (
        "当前评审平台：推特/X。\n"
        "重点关注：① 280字内精炼金句（style+3）；② 话题标签 #tag 质量（cta+3）；"
        "③ 英文适配性与国际视野（value+2）；④ Thread分组清晰。\n"
        "扣分项：超字数、无话题标签、翻译腔。"
    ),
}

JUDGE_PROMPT = (
    "你是严格的自媒体内容质量评审官。按以下维度对稿件打分（不要人情分）：\n"
    + "\n".join(f"- {k}（满分{v}）：{d}" for k, v, _, d in DIMENSIONS)
    + "\n\n输出严格 JSON（不要 markdown 代码块）：\n"
    '{"scores":{"title":0,"value":0,"structure":0,"style":0,"visual":0,"layout":0,"cta":0},'
    '"total":0,"reasons":{"title":"...","value":"..."},"improvements":["改进点1","改进点2","改进点3"]}'
)


def grade(total: float) -> str:
    if total < 75:
        return "不合格"
    if total < 85:
        return "合格"
    if total < 95:
        return "良好"
    return "优秀"


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"评审输出无 JSON: {text[:200]}")
    s = m.group(0).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # 尝试清洗控制字符与非法转义
    try:
        clean = re.sub(r"[\x00-\x1f]", lambda c: " " if c.group(0) not in "\r\n\t" else c.group(0), s)
        return json.loads(clean)
    except Exception:
        pass
    # 尝试正则提取 scores 字典兜底
    scores = {}
    for key in ("title", "value", "structure", "style", "visual", "layout", "cta"):
        val_m = re.search(rf'"{key}"\s*:\s*([0-9]+(?:\.[0-9]+)?)', s)
        if val_m:
            scores[key] = float(val_m.group(1))
    if scores:
        return {"scores": scores, "total": sum(scores.values()), "reasons": {}}
    raise ValueError(f"评审输出 JSON 解析失败: {text[:200]}")


def judge_draft(draft_id: str, platform: str | None = None,
                min_score: float | None = None) -> dict:
    """独立评审一篇草稿（与写稿分开调用），结果入库并返回。

    v3.33: 支持 platform 参数，为不同平台使用差异化评审标准。
    v5.302: 新增 min_score 参数 + 内置分数地板保护：
      - 若新评分 < 草稿当前已保存的分数，不更新 DB 分数，以防 LLM 评分随机波动导致分数倒退。
      - 调用方可额外指定 min_score 下限（通常为改写前的分数），进一步防止退分。
    """
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")

    # 取草稿当前已持久化的分数作为内置地板
    existing_score = d.get("score") or 0.0
    floor = max(float(existing_score), float(min_score) if min_score is not None else 0.0)

    # 构建平台专属补充提示
    platform_hint = ""
    if platform and platform in PLATFORM_TIPS:
        platform_hint = f"\n\n{PLATFORM_TIPS[platform]}"

    def _ask(extra=""):
        return agents.chat_for("review", [
            {"role": "system", "content": JUDGE_PROMPT + platform_hint + extra},
            {"role": "user", "content":
                f"标题：{d['title']}\n正文：\n{d['body_md'][:4000]}\n\n"
                "（图文配合维度：若无配图信息，按正文对配图的规划合理性评估）"}],
            temperature=0.2)
    raw = _ask()
    try:
        data = _extract_json(raw)
    except Exception:
        # 格式漂移重试一次（强约束键名与满分）
        raw = _ask("\n\n再次强调：只输出一个 JSON 对象；scores 的键必须是 "
                   "title,value,structure,style,visual,layout,cta；"
                   "各项满分分别是 15,25,15,15,15,10,5，不得超过。")
        data = _extract_json(raw)
    # 归一化：兼容百分制打分/中文键名/模型自报 total 不可信
    maxmap = {k: mx for k, _, mx, _ in DIMENSIONS}
    labelmap = {lbl: k for k, lbl, _, _ in DIMENSIONS}
    raw_scores = data.get("scores", {}) or {}
    norm = {}
    for k in maxmap:
        lbl = [l for kk, l, _, _ in DIMENSIONS if kk == k][0]
        val = raw_scores.get(k, raw_scores.get(lbl, 0))
        try:
            norm[k] = float(val)
        except Exception:
            norm[k] = 0.0
    # 若明显是百分制（多项超过满分），按比例折算
    if any(norm[k] > maxmap[k] + 0.01 for k in maxmap):
        norm = {k: norm[k] / 100.0 * maxmap[k] for k in maxmap}
    scores = {k: round(max(0.0, min(norm[k], float(maxmap[k]))), 1) for k in maxmap}
    total = round(sum(scores.values()), 1)
    detail = {
        "scores": scores,
        "reasons": data.get("reasons", {}),
        "improvements": data.get("improvements", []),
        "grade": grade(total),
        "platform": platform or "general",  # v3.33: 记录评审平台
    }

    # ── v5.302 分数地板保护 ──
    # 若 LLM 本次评分低于当前已持久化分数（或调用方指定的 min_score），
    # 不覆盖 DB 中已有的更高分数，只对 score_round 计数器 +1，
    # 并返回当前最优分数数据（而非倒退后的低分）。
    if total < floor and floor > 0:
        # 从 DB 中取出上一次保存的 score_detail 并返回
        existing_detail = {}
        try:
            import json as _json
            existing_detail = _json.loads(d.get("score_detail") or "{}") or {}
        except Exception:
            pass
        existing_detail.setdefault("grade", grade(floor))
        # 只更新 score_round，不改动 score / score_detail
        c = db.conn()
        c.execute("UPDATE drafts SET score_round=score_round+1 WHERE id=?", (draft_id,))
        c.commit()
        c.close()
        # 同时把本次 LLM 的改进建议合并进来（方便下一轮继续优化）
        merged_improvements = list(dict.fromkeys(
            list(existing_detail.get("improvements", [])) + list(data.get("improvements", []))
        ))[:5]
        existing_detail["improvements"] = merged_improvements
        return {"total": floor, **existing_detail}

    # 正常流程：新分数 >= 地板，写入 DB
    c = db.conn()
    c.execute("UPDATE drafts SET score=?, score_detail=?, score_round=score_round+1 WHERE id=?",
              (total, json.dumps(detail, ensure_ascii=False), draft_id))
    c.commit()
    c.close()
    return {"total": total, **detail}



def judge_platform_scores(draft_id: str) -> dict:
    """为草稿生成各平台的差异化评分概览（轻量版，不更新DB）。
    
    用于内容工作台展示各平台适配分数。
    v3.33新增。
    """
    d = db.get_draft(draft_id)
    if not d:
        return {}
    
    platforms = d.get("platforms") or ["wechat_mp", "xhs", "toutiao"]
    # 基础评分（从已保存的detail推导）
    try:
        det = json.loads(d["score_detail"]) if d.get("score_detail") else {}
    except Exception:
        det = {}
    
    base_scores = det.get("scores", {})
    base_total = d.get("score") or 0
    
    if not base_scores:
        if base_total:
            base_scores = {
                "title": round(base_total * 0.15, 1),
                "value": round(base_total * 0.25, 1),
                "structure": round(base_total * 0.15, 1),
                "style": round(base_total * 0.15, 1),
                "visual": round(base_total * 0.15, 1),
                "layout": round(base_total * 0.10, 1),
                "cta": round(base_total * 0.05, 1),
            }
        else:
            base_scores = {
                "title": 12.0, "value": 20.0, "structure": 12.0,
                "style": 12.0, "visual": 10.0, "layout": 8.0, "cta": 4.0
            }
    
    result = {}
    # 基于基础分 + 平台权重系数快速估算各平台分
    PLATFORM_WEIGHTS = {
        "wechat_mp": {"value": 1.1, "structure": 1.1, "title": 1.05},
        "xhs":       {"style": 1.15, "visual": 1.1, "cta": 1.1, "title": 0.95},
        "toutiao":   {"title": 1.2, "value": 1.05},
        "zhihu":     {"value": 1.15, "structure": 1.1, "style": 0.9},
        "weibo":     {"style": 1.1, "cta": 1.1, "value": 0.9},
        "twitter":   {"style": 1.1, "cta": 1.15, "layout": 0.9},
    }
    maxmap = {k: mx for k, _, mx, _ in DIMENSIONS}
    
    for plat in PLATFORM_WEIGHTS.keys():
        weights = PLATFORM_WEIGHTS.get(plat, {})
        plat_scores = {}
        for dim, base_val in base_scores.items():
            w = weights.get(dim, 1.0)
            maxv = maxmap.get(dim, 10)
            plat_scores[dim] = round(min(base_val * w, maxv), 1)
        plat_total = round(min(sum(plat_scores.values()), 100.0), 1)
        result[plat] = {
            "total": plat_total,
            "grade": grade(plat_total),
            "scores": plat_scores
        }
    
    return result


def get_score(draft_id: str) -> dict | None:
    d = db.get_draft(draft_id)
    if not d or not d.get("score"):
        return None
    try:
        det = json.loads(d["score_detail"]) if d["score_detail"] else {}
    except Exception:
        det = {}
    return {"total": d["score"], "round": d["score_round"], **det}


def quality_cfg() -> dict:
    from core.llm import load_config
    q = load_config().get("quality", {})
    return {"threshold": float(q.get("threshold", 75)),
            "max_rounds": int(q.get("max_rounds", 3))}
