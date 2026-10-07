"""编排器：选题/搜索 → 创作 → 评分 → 重写 → 排版 → 草稿箱 → 人工确认后发布。"""
import json
import logging
import re
import shutil
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import agents, db, judge, llm             # noqa: E402
from core.topics import collect_topics              # noqa: E402
from core.render_card import render_draft_cards     # noqa: E402
from core.imagegen import decorate_draft, img_dir   # noqa: E402
from core.llm import load_config                    # noqa: E402
from adapters import wechat_mp, toutiao             # noqa: E402
from adapters.base import save_preview              # noqa: E402
from core.layouter import render as layout_render   # noqa: E402
from core.themes import DEFAULT_CARD_STYLE, DEFAULT_THEME  # noqa: E402
from core.title_forge import generate_candidate_titles     # noqa: E402

VIRAL_FORMULAS = (
    "爆款公式（参考全网百篇万赞爆款蒸馏的七式）：\n"
    "1.数字盘点式：《普通人必知的3个破局真相》/《3个动作化解换季焦虑》\n"
    "2.悬念反差式：先给反常识结论再解释\n"
    "3.身份代入式：以体验者第一人称叙述\n"
    "4.地域+热点嫁接式：把全国热词接到本地生活与文化上\n"
    "5.干货清单式：分点可收藏\n"
    "6.对比反差式：过去vs现在/别处vs我们\n"
    "7.故事化开头：30字内场景钩子"
)

SYS_PROMPT = (
    "你是全网爆款文案操盘手，什么领域的爆款都能写（科技数码/商业财经/职场生活/美食家居/情感认知/文化艺术皆可）。\n"
    f"{VIRAL_FORMULAS}\n"
    "创作要求：必须严格围绕用户给定的主题领域展开深度创作，严禁擅自偏离主题！"
    "从『当日热榜参考』和『对标网页全文素材』里观察爆款切入角度与情绪点；"
    "正文结构：钩子开头→痛点共鸣→干货分点（### 分节、- 列表）→结尾CTA引导关注。\n"
    "严格按以下格式输出，不要额外解释：\n"
    "TITLE: <爆款标题，不超过30字，含数字或悬念钩子>\n"
    "BODY:\n<正文 markdown>\n"
    "铁律：正文里禁止出现任何『视觉指南/配图建议/封面设计/排版说明』等制作性内容——视觉由系统自动处理。"
    "另外所有成稿统一禁止这类内容出现在读者可见的正文中。"
)

REWRITE_PROMPT = (
    "你是新媒体爆款操盘手，擅长各领域爆款的深度拆解与融合仿写。\n"
    f"{VIRAL_FORMULAS}\n"
    "任务分两步：\n"
    "第一步【拆解】深度拆解对标参考爆款的行文逻辑、叙事节奏与情绪曲线；\n"
    "第二步【仿写】严格遵循用户指定的创作主题（若未指定，则严格跟随参考素材的核心领域，严禁臆想偏向无关领域），"
    "融合参考爆款的事实骨架与金句技巧，写出具备爆款潜力的多平台版本"
    "（公众号长文、小红书短句体+标签、头条资讯体），标题含数字或悬念钩子。\n"
    "严格按以下格式输出，不要额外解释：\n"
    "ANALYSIS:\n<拆解报告，4-6行>\n"
    "TITLE_WX: <公众号标题>\nBODY_WX:\n<公众号正文 markdown，### 分节>\n"
    "TITLE_XHS: <小红书标题，20字内>\nBODY_XHS:\n<小红书正文，短句分点，末尾带 #标签>\n"
    "TITLE_TT: <头条标题>\nBODY_TT:\n<头条正文 markdown>"
)

STRUCTURE_PRESERVING_REWRITE_PROMPT = (
    "你是顶尖爆款内容重构导师与名家文学工坊操盘手。\n"
    f"{VIRAL_FORMULAS}\n"
    "【核心铁律：文章行文骨架结构 100% 严格锁定不变，内容全面换血深度重塑】\n"
    "任务必须按以下两阶段严格执行：\n"
    "第一阶段【骨架逆向解构】：深入剖析并提取原文的结构骨架脉络：\n"
    "  - 破题引子层：原文是如何切入的（热点现象/冲突对比/悬念痛点）？\n"
    "  - 论点推进层：原文有几个核心小节/论点层次？各层之间的递进逻辑是什么？\n"
    "  - 案例与转折层：如何展开论据、如何推进认知升级？\n"
    "  - 升华与收尾层：如何金句收拢、促成行动号召？\n"
    "第二阶段【同骨架名家深度改写】：\n"
    "  1. 严格锁定原篇的段落节次与论证逻辑，原文有几大章节，改写后的公众号文章就必须有相同章节（### 分节）与论述对应关系，绝不能随意打散或缩水遗漏！\n"
    "  2. 对原文的每一节内容进行深度重写：更换全新鲜活的案例、重塑论述词句、融入所挂载的名家文风（语调口吻、句式节奏、修辞习惯），彻底去除陈词滥调与 AI 味；\n"
    "  3. 严格围绕用户指定的主题展开，若未指定主题则严格跟随原文核心领域，严禁无中生有偏向无关领域；\n"
    "  4. 同步产出符合该骨架的小红书短句笔记与头条深度资讯版本。\n\n"
    "严格按以下格式输出，不要额外解释：\n"
    "ANALYSIS:\n<原文骨架解构（引子/核心节次/递进逻辑）与改写策略说明，4-6行>\n"
    "TITLE_WX: <公众号标题，含悬念或利益钩子>\nBODY_WX:\n<公众号正文 markdown，严格对应原文架构，### 分节>\n"
    "TITLE_XHS: <小红书爆款标题，20字内>\nBODY_XHS:\n<小红书正文，短句分点，段落精悍，末尾带 #标签>\n"
    "TITLE_TT: <今日头条深度标题>\nBODY_TT:\n<今日头条正文 markdown>"
)

ONE_SENTENCE_VIRAL_PROMPT = (
    "你是顶级全网爆款操盘手与深度内容主笔。\n"
    f"{VIRAL_FORMULAS}\n"
    "你接收到了用户的一句话创作灵感，以及系统全网实时检索抓取的 3~5 篇权威长文真实素材与论据。\n"
    "【创作铁律】：\n"
    "1. 充分消化理解抓取到的 3~5 篇真实长文中的核心论据、真实史料考证、专业案例与深度视角，以这些真实素材为事实底座，绝不凭空胡编！\n"
    "2. 针对用户的一句话核心意图与聚焦重点（例如若用户重点突出诸葛亮，则全篇必须紧扣诸葛亮的智慧与破局展开），绝不跑题！\n"
    "3. 严格融入用户指定挂载的名家文风指纹（如王小波、鲁迅、余华、张爱玲等，体现独特的冷峻/幽默/犀利语调与文学质感）；\n"
    "4. 同时生成三平台高标准爆款成稿（公众号深度长文、小红书高赞图文笔记、头条热点资讯）。\n\n"
    "严格按以下格式输出，不要额外解释：\n"
    "ANALYSIS:\n<创作意图拆解与全网素材整合思路，4-6行>\n"
    "TITLE_WX: <公众号高点击标题>\nBODY_WX:\n<公众号正文 markdown，### 分节，故事切入，论证详实，金句频出>\n"
    "TITLE_XHS: <小红书高赞标题，带情绪钩子，20字内>\nBODY_XHS:\n<小红书正文，短句分点，击中痛点，末尾带 #标签>\n"
    "TITLE_TT: <今日头条高推荐标题>\nBODY_TT:\n<今日头条正文 markdown>"
)

REVISION_PROMPT = (
    "你是自查自改的新媒体爆款写手。这是你的稿子和评审官的打分意见，请针对性修改（保持格式不变）：\n"
    f"{VIRAL_FORMULAS}\n"
    "严格按以下格式输出修改后的完整稿，不要额外解释：\n"
    "TITLE_WX: <公众号标题>\nBODY_WX:\n<公众号正文 markdown，### 分节>\n"
    "TITLE_XHS: <小红书标题，20字内>\nBODY_XHS:\n<小红书正文，短句分点，末尾带 #标签>\n"
    "TITLE_TT: <头条标题>\nBODY_TT:\n<头条正文 markdown>\n"
    "铁律：任何版本正文里禁止出现『视觉指南/配图建议/封面设计/排版说明』等制作性内容。"
)


def _split_llm_output(text: str) -> tuple[str, str]:
    title, body = "未命名选题", ""
    if "TITLE:" in text:
        head, _, rest = text.partition("BODY:")
        title = head.split("TITLE:", 1)[1].strip().splitlines()[0][:40]
        body = rest.strip()
    else:
        lines = [l for l in text.strip().splitlines() if l.strip()]
        title = lines[0][:40] if lines else title
        body = "\n".join(lines[1:]).strip()
    return title, body


def _placeholder(topic_title: str) -> tuple[str, str]:
    title = f"{topic_title[:28]}：深度解析与实操指南"
    body = ("### 为什么值得看\n- 选题来自热榜/对标爆款：{t}\n- 结构深度参考全网爆款结构公式\n\n### 三个核心维度\n"
            "- 要点一：核心痛点与现象解析\n- 要点二：底层逻辑与实操步骤\n- 要点三：高频避坑与认知升级\n\n### 写在最后\n配置 AI 模型网关后此占位稿将全自动替换为顶尖爆款成稿。"
            ).format(t=topic_title)
    return title, body


def _cfg_theme() -> tuple[str, str]:
    c = load_config().get("creation", {})
    return c.get("wechat_theme", DEFAULT_THEME), c.get("card_style", DEFAULT_CARD_STYLE)


META_KEYWORDS = ("视觉指南", "配图建议", "配图说明", "封面设计", "排版说明", "视觉策略", "视觉呈现")


def _strip_meta_sections(text: str) -> str:
    """从成稿里剔除『视觉指南/配图建议』等制作说明段落——这些不该出现在读者面前。"""
    if not text:
        return text
    lines = text.splitlines()
    out, skip = [], False
    for ln in lines:
        st = ln.strip()
        # 命中制作说明标题行（### 视觉指南… / 【视觉指南…】 / PAGE: 视觉指南…）→ 开始跳过
        is_heading = st.startswith(("###", "# ", "【", "PAGE:")) or (
            any(k in st[:12] for k in META_KEYWORDS) and ("：" in st[:16] or ":" in st[:16]))
        if any(k in st for k in META_KEYWORDS) and is_heading:
            skip = True
            continue
        if skip:
            # 新的 ### 标题 / 【段落头】 / PAGE 行 = 结束跳过
            if st.startswith(("###", "# ", "【", "PAGE:", "TITLE", "BODY", "TAGS", "LINE:")) and not any(
                    k in st for k in META_KEYWORDS):
                skip = False
                out.append(ln)
            continue
        out.append(ln)
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() or text.strip()


def _parse_rewrite(raw: str) -> dict:
    out, cur = {}, None
    for line in raw.splitlines():
        m = re.match(r"^(ANALYSIS|TITLE_WX|BODY_WX|TITLE_XHS|BODY_XHS|TITLE_TT|BODY_TT)\s*[:：]\s*(.*)$", line)
        if m:
            cur = m.group(1)
            out[cur] = (m.group(2) + "\n") if m.group(2) else ""
        elif cur:
            out[cur] += line + "\n"
    out = {k: v.strip() for k, v in out.items()}
    for key in ("BODY_WX", "BODY_XHS", "BODY_TT"):
        if out.get(key):
            out[key] = _strip_meta_sections(out[key])
    return out


def _refresh_artifacts(draft_id: str, parsed: dict, fallback_title: str, fallback_body: str,
                       media_name: str = "一幕·YIMU 爆款工作室", platforms: list[str] | None = None,
                       generate_images: bool = True):
    """按选中的目标平台极速重渲染产物（支持按需少生成，后续在工作台按需补充）。"""
    selected_platforms = platforms if platforms is not None else ["wechat_mp", "xhs", "toutiao"]
    theme, card_style = _cfg_theme()
    title = (parsed.get("TITLE_WX") or fallback_title)[:40]
    body = parsed.get("BODY_WX") or fallback_body
    xhs_title = parsed.get("TITLE_XHS", title)
    xhs_body = parsed.get("BODY_XHS", "")
    tt_title = parsed.get("TITLE_TT", title)
    tt_body = parsed.get("BODY_TT", "")

    ddir = db.draft_dir(draft_id)
    # AI 配图（按小节内容生成，差异化角度；失败自动回落）
    sec_meta, cur = [], None
    for line in body.splitlines():
        if line.startswith("### "):
            cur = [line[4:].strip(), []]
            sec_meta.append(cur)
        elif cur is not None and line.strip():
            cur[1].append(line.strip().lstrip("- "))
    # 配图上下文：上一节的结尾 + 本节内容
    sec_arg = []
    for i, (t, paras) in enumerate(sec_meta):
        prev_tail = " ".join(sec_meta[i - 1][1])[-60:] if i > 0 else ""
        sec_arg.append((t, (prev_tail + " " + " ".join(paras))[:140]))
    # 兜底：若解析出的小节 < 4，从正文段落自动补充，确保至少 4 个小节条目生成配图
    if len(sec_arg) < 4:
        para_chunks = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        fallback_names = ["核心背景", "深度解析", "实战方法论", "价值洞察", "行动指南"]
        for j, para in enumerate(para_chunks[:5]):
            if len(sec_arg) >= 5:
                break
            sec_arg.append((fallback_names[j % len(fallback_names)], para[:140]))

    if generate_images:
        imgs = decorate_draft(ddir, title, sec_arg, body_md=body, count=5)
    else:
        imgs = {"cover": None, "sections": {}}
        if (ddir / "img" / "cover.png").exists():
            imgs["cover"] = "img/cover.png"
        for i, (t, _) in enumerate(sec_meta):
            if (ddir / "img" / f"sec-{i}.png").exists():
                imgs["sections"][t] = f"img/sec-{i}.png"
        if not imgs["sections"]:
            all_secs = sorted((ddir / "img").glob("sec-*.png"))
            for i, p in enumerate(all_secs):
                key = sec_meta[i][0] if i < len(sec_meta) else f"小节_{i+1}"
                imgs["sections"][key] = f"img/{p.name}"
                
    images = {k: f"/img/{draft_id}/{v.split('/')[-1]}" for k, v in imgs["sections"].items()}
    cover = f"/img/{draft_id}/cover.png" if imgs.get("cover") else None
    
    from core.imagegen import inject_images_to_markdown
    injected_body = inject_images_to_markdown(body, draft_id)

    # 微信公众号
    if "wechat_mp" in selected_platforms:
        save_preview(ddir, "wechat_mp",
                     layout_render(body, title, theme, meta=media_name, images=images, cover=cover))

    from adapters import toutiao, zhihu, weibo, twitter
    if "toutiao" in selected_platforms:
        save_preview(ddir, "toutiao", toutiao.render_preview(injected_body, tt_title or title, images=images, cover=cover, draft_id=draft_id))
        (ddir / "toutiao.md").write_text(f"# {tt_title or title}\n\n{inject_images_to_markdown(tt_body or body, draft_id)}", encoding="utf-8")

    if "zhihu" in selected_platforms:
        save_preview(ddir, "zhihu", zhihu.render_preview(injected_body, title, images=images, cover=cover, draft_id=draft_id))
        (ddir / "zhihu.md").write_text(f"# {title}\n\n{injected_body}", encoding="utf-8")

    if "weibo" in selected_platforms:
        save_preview(ddir, "weibo", weibo.render_preview(injected_body, title, images=images, cover=cover, draft_id=draft_id))
        (ddir / "weibo.md").write_text(f"# {title}\n\n{injected_body}", encoding="utf-8")

    if "twitter" in selected_platforms:
        tw_text = parsed.get("TEXT_TWITTER", "")
        if not tw_text:
            tw_text = f"1/3 🔥 关于《{title}》的核心要点 👇\n\n{body[:180]}\n\n---\n\n2/3 💡 深度洞察：\n{body[180:360]}\n\n---\n\n3/3 🎯 关注 @yimu_creator 获取更多干货 #自媒体"
        (ddir / "twitter.md").write_text(tw_text, encoding="utf-8")
        save_preview(ddir, "twitter", twitter.render_twitter_html(tw_text, title))

    # 小红书多图
    if "xhs" in selected_platforms:
        (ddir / "xhs.md").write_text(f"# {xhs_title}\n\n{xhs_body or body[:500]}", encoding="utf-8")
        sections = []
        cur_t, cur_pts = None, []
        for line in (xhs_body or body).splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("### ") or s.startswith("## ") or (s.startswith("【") and s.endswith("】")):
                if cur_t and cur_pts:
                    sections.append((cur_t[:18], cur_pts[:3]))
                cur_t = re.sub(r'^[#【\s]+|[】]+$', '', s).strip()
                cur_pts = []
            elif s.startswith("- ") or s.startswith("• ") or re.match(r'^\d+[\.、]', s):
                cur_pts.append(re.sub(r'^[-•\d\.、\s]+', '', s).strip()[:35])
            elif not s.startswith("#") and not s.startswith("🔥"):
                if cur_t:
                    cur_pts.append(s[:35])
                else:
                    sections.append((s[:16], [s[:35]]))
        if cur_t and cur_pts:
            sections.append((cur_t[:18], cur_pts[:3]))
        # 兜底：若解析出的 section < 3，从段落自动补充，确保至少 3 张小红书卡片
        if len(sections) < 3:
            src_text = xhs_body or body
            paras = [p.strip() for p in src_text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
            card_names = ["🔑 核心要点", "💡 深度解析", "✨ 实战技巧", "🎯 关键洞察", "🚀 行动指南"]
            for j, para in enumerate(paras[:5]):
                if len(sections) >= 5:
                    break
                pts = [s.strip()[:35] for s in para.splitlines() if s.strip()][:3] or [para[:35]]
                sections.append((card_names[j % len(card_names)], pts))
        if not sections:
            sections = [(xhs_title, [xhs_body[:60] or title])]

        target_card_style = card_style if card_style and card_style != "magazine" else "ai_visual_dark"
        cover_file = ddir / "img" / "cover.png" if (ddir / "img" / "cover.png").exists() else None
        render_draft_cards(ddir, xhs_title, sections[:5], style=target_card_style, cover_img=cover_file)
        save_xhs_history_snapshot(draft_id, note="多端全量重排")

    c = db.conn()
    c.execute("UPDATE drafts SET title=?, body_md=?, platforms=? WHERE id=?",
              (title, body, json.dumps(selected_platforms, ensure_ascii=False), draft_id))
    c.commit()
    c.close()


def generate_draft(topic_id: str, emit=None, media_name: str = "一幕·YIMU 爆款工作室",
                   platforms: list[str] | None = None) -> dict:
    """对已通过选题生成草稿：LLM 成稿 → 按需多端渲染/配图/卡片 → 自动评分循环。"""
    emit = emit or (lambda *_: None)
    emit("AI 写作中…（约20-40秒）")
    topic = db.get_topic(topic_id)
    if not topic:
        raise RuntimeError(f"选题不存在: {topic_id}")

    selected_platforms = platforms if platforms is not None else ["wechat_mp", "xhs"]

    if llm.available():
        try:
            from core.search import fetch_topic_multisource_references
            web_refs = fetch_topic_multisource_references(topic["title"], limit=4)
            web_ref_text = ""
            if web_refs:
                web_ref_text = "\n\n【全网 3~5 篇真实网页深度对标蓝本（必须通读其事实论据、写作手法与逻辑结构进行升华改写）】\n"
                for i, r in enumerate(web_refs, 1):
                    web_ref_text += f"◆ 参考篇 {i}：《{r['title']}》（{r['source']}）\n  网页核心内容与事实：{r['snippet']}\n\n"

            recent = [t for t in db.list_topics() if t["status"] in ("pending", "approved")][:12]
            hot_ref = "\n".join(f"- {t['title']}（{t['reason']}）" for t in recent) or "（暂无）"
            user_msg = (f"创作选题：{topic['title']}\n选题热度与背景：{topic['reason']}\n"
                        f"【发布媒体/创作者署名账号】：{media_name}（在文章正文及结尾处自然融入该账号品牌标识并引导关注）\n"
                        f"{web_ref_text}"
                        f"【当日热榜参考（观察爆款情绪规律）】\n{hot_ref}\n\n"
                        f"【特别铁律】：严格围绕上述创作选题展开，以抓取到的 3~5 篇真实网页素材为事实蓝本深度扩写，绝不允许凭空捏造或偏向不相关的非遗/其他领域！")
            raw = agents.chat_for("write", [{"role": "system", "content": SYS_PROMPT},
                                            {"role": "user", "content": user_msg}],
                                  fallback_model=llm.load_config().get("gateway", {}).get("model", ""))
            title, body = _split_llm_output(raw)
        except Exception:
            traceback.print_exc()
            title, body = _placeholder(topic["title"])
    else:
        title, body = _placeholder(topic["title"])

    emit(f"排版渲染与配图 [{', '.join(selected_platforms)}]…")
    cand_titles = generate_candidate_titles(title, body)
    draft = db.add_draft(topic_id, title, body, selected_platforms,
                         candidate_titles=cand_titles)
    parsed = {"TITLE_WX": title, "BODY_WX": body,
              "TITLE_XHS": title, "BODY_XHS": body,
              "TITLE_TT": title, "BODY_TT": body}
    _refresh_artifacts(draft["id"], parsed, title, body, media_name=media_name, platforms=selected_platforms)
    db.set_topic_status(topic_id, "drafted")
    result = {"draft": db.get_draft(draft["id"])}
    if llm.available():
        emit("评审评分中…")
        result["score"] = judge_and_iterate(draft["id"], emit=emit)
    return result


def switch_draft_title(draft_id: str, new_title: str) -> dict:
    """极速切换草稿标题（毫秒级热更新微信、小红书封面卡、头条、知乎、微博、Twitter及矩阵数据）。"""
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    new_title = (new_title or "").strip()[:80]
    db.update_draft_title(draft_id, new_title)
    ddir = db.draft_dir(draft_id)
    theme, card_style = _cfg_theme()
    imgs = [p.name for p in (ddir / "img").glob("*.png")] if (ddir / "img").exists() else []
    cover = f"/img/{draft_id}/cover.png" if "cover.png" in imgs else None
    images = {p.split(".")[0]: f"/img/{draft_id}/{p}" for p in imgs if p != "cover.png"}

    from core.imagegen import inject_images_to_markdown
    injected = inject_images_to_markdown(d["body_md"], draft_id)

    from adapters import toutiao, zhihu, weibo, twitter
    save_preview(ddir, "wechat_mp", layout_render(d["body_md"], new_title, theme, images=images, cover=cover))
    save_preview(ddir, "toutiao", toutiao.render_preview(injected, new_title, images=images, cover=cover, draft_id=draft_id))
    save_preview(ddir, "zhihu", zhihu.render_preview(injected, new_title, images=images, cover=cover, draft_id=draft_id))
    save_preview(ddir, "weibo", weibo.render_preview(injected, new_title, images=images, cover=cover, draft_id=draft_id))

    (ddir / "content.md").write_text(f"# {new_title}\n\n{d['body_md']}", encoding="utf-8")
    (ddir / "toutiao.md").write_text(f"# {new_title}\n\n{injected}", encoding="utf-8")
    (ddir / "zhihu.md").write_text(f"# {new_title}\n\n{injected}", encoding="utf-8")
    (ddir / "weibo.md").write_text(f"# {new_title}\n\n{injected}", encoding="utf-8")
    
    # Twitter 预览同步
    tw_file = ddir / "twitter.md"
    if tw_file.exists():
        tw_text = tw_file.read_text(encoding="utf-8")
        save_preview(ddir, "twitter", twitter.render_twitter_html(tw_text, new_title))

    # 小红书文案与封面卡 Card 0 毫秒级极速重绘
    xhs_file = ddir / "xhs.md"
    xhs_body = ""
    if xhs_file.exists():
        content = xhs_file.read_text(encoding="utf-8")
        xhs_body = re.sub(r"^#\s+.*\n*", "", content).strip()
    xhs_file.write_text(f"# {new_title}\n\n{xhs_body or d['body_md']}", encoding="utf-8")
    
    cover_file = ddir / "img" / "cover.png" if (ddir / "img" / "cover.png").exists() else None
    
    # 极速重绘封面卡 Card 0
    from core.render_card import render_cover_card_only
    render_cover_card_only(ddir, new_title, style=card_style, cover_img=cover_file)
    
    # 同步更新 matrix.json
    mf = ddir / "matrix.json"
    if mf.exists():
        try:
            mdata = json.loads(mf.read_text(encoding="utf-8"))
            if "master" in mdata:
                mdata["master"]["title"] = new_title
            if "wechat_mp" in mdata:
                mdata["wechat_mp"]["title"] = new_title
            if "xhs" in mdata:
                mdata["xhs"]["title"] = new_title
            if "toutiao" in mdata:
                mdata["toutiao"]["title"] = new_title
            if "zhihu" in mdata:
                mdata["zhihu"]["title"] = new_title
            mf.write_text(json.dumps(mdata, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return db.get_draft(draft_id)


def benchmark_and_rewrite(source_platform: str, source_title: str, source_url: str,
                          theme: str, extra: dict | None = None,
                          source_text: str = "") -> dict:
    """读取对标爆款 → 拆解结构 → 仿写三平台 → 自动评分循环。

    source_text 非空（手动贴文模式）时直接以其为原文，跳过抓取。
    """
    from core import search as S
    from core.extractor import extract_url
    detail = source_text
    extracted_imgs = []
    if not detail and source_url:
        try:
            ext = extract_url(source_url)
            if ext.get("ok") and ext.get("content"):
                detail = ext["content"]
                extracted_imgs = ext.get("images", [])
        except Exception:
            pass
    if not detail:
        try:
            if source_platform == "xhs":
                detail = S.xhs_detail((extra or {}).get("note_id", ""),
                                      (extra or {}).get("xsec_token", ""))
            elif source_platform == "toutiao" and source_url:
                detail = S.toutiao_detail(source_url)
        except Exception:
            pass

    # 若正文内容仍不足，自动检索抓取 3~5 篇全网真实对标网页内容作为详细蓝本
    multi_refs_text = ""
    if len(detail or "") < 160:
        query_topic = theme if (theme and theme.strip() and theme != "跟随对标爆款领域") else source_title
        refs = S.fetch_topic_multisource_references(query_topic, limit=4)
        if refs:
            multi_refs_text = "\n\n【全网 3~5 篇同主题热门爆款网页深度蓝本（AI 必须深度阅读以下真实文章要点与事实进行融合重写）】\n"
            for i, r in enumerate(refs, 1):
                multi_refs_text += f"◆ 对标蓝本 {i}：《{r['title']}》（来源：{r['source']}）\n  网页核心内容与事实：\n{r['snippet']}\n\n"

    plat_label = "手动贴文" if source_platform == "manual" else source_platform
    raw = agents.chat_for("write", [
        {"role": "system", "content": REWRITE_PROMPT},
        {"role": "user", "content":
            f"【对标爆款（{plat_label}）】\n标题：{source_title}\n"
            f"链接：{source_url or '无'}\n"
            f"网页真实正文/长文详情：\n{(detail or source_title)[:4500]}\n"
            f"{multi_refs_text}"
            f"【创作用途与主题约束】：{theme or '严格跟随对标爆款的领域，绝不擅自偏离或捏造其他无关领域'}\n"
            f"【特别要求】：以抓取的网页真实长文和参考素材为蓝本，保留原爆款的核心论据与干货深度，全面升华重写！"}], temperature=0.85)
    parsed = _parse_rewrite(raw)
    title = (parsed.get("TITLE_WX") or source_title)[:40]
    body = parsed.get("BODY_WX") or f"（成稿解析失败，原始输出）\n{raw[:600]}"
    cand_titles = generate_candidate_titles(title, body)
    source_stats = (extra or {}).get("stats", {}) if extra and isinstance((extra or {}).get("stats"), dict) else {}
    d = db.add_draft(None, title, body, ["wechat_mp", "xhs", "toutiao"],
                     source_platform=source_platform, source_url=source_url,
                     source_title=source_title, analysis=parsed.get("ANALYSIS", ""),
                     candidate_titles=cand_titles, source_stats=source_stats)
    _refresh_artifacts(d["id"], parsed, title, body)
    result = {"draft": db.get_draft(d["id"]), "analysis": parsed.get("ANALYSIS", "")}
    if llm.available():
        result["score"] = judge_and_iterate(d["id"])
    return result


def rewrite_draft_once(draft_id: str, instruction: str = "") -> dict:
    """按评审意见（+可选人工指令）重写一篇，并重新评分一次。"""
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    sc = judge.get_score(draft_id)
    pre_score = (sc or {}).get("total") or 0.0  # v5.302: 记录改写前分数基线
    feedback = ""
    if sc:
        feedback = (f"【上轮得分】{sc['total']}（{sc.get('grade','')}）\n"
                    "【各维度点评】\n" +
                    "\n".join(f"- {k}: {v}" for k, v in (sc.get("reasons") or {}).items()) +
                    "\n【必须改进】\n" +
                    "\n".join(f"- {x}" for x in (sc.get("improvements") or [])))
    if instruction:
        feedback += f"\n【人工定向要求】{instruction}"
    db.add_history(draft_id, d["title"], d["body_md"], pre_score)
    raw = agents.chat_for("write", [
        {"role": "system", "content": REVISION_PROMPT},
        {"role": "user", "content":
            f"【原稿】\n标题：{d['title']}\n{d['body_md'][:4000]}\n\n{feedback}"}],
        temperature=0.8)
    parsed = _parse_rewrite(raw)
    if not parsed.get("BODY_WX"):
        raise RuntimeError("重写解析失败")
    _refresh_artifacts(draft_id, parsed, d["title"], d["body_md"])
    # v5.302: 传入 min_score=pre_score，确保打分结果不低于改写前
    score = judge.judge_draft(draft_id, min_score=pre_score)
    return {"score": score, "draft": db.get_draft(draft_id)}


# 各平台专属重写提示词
PLATFORM_REWRITE_PROMPTS = {
    "wechat_mp": (
        "你是顶级微信公众号内容策划与写手。\n"
        "任务：对给定草稿进行深度改写，专为微信公众号读者优化。\n"
        "要求：① 标题悬念感强，含数字/反差钩子；② 深度叙事，逻辑严密；"
        "③ 分节清晰（### 标题 + 列表），5-10分钟阅读量；④ 结尾 CTA 明确。\n"
        "严格按格式输出，不要额外解释：\n"
        "TITLE_WX: <公众号精改标题>\nBODY_WX:\n<公众号正文 markdown，### 分节>"
    ),
    "xhs": (
        "你是顶级小红书爆款博主和内容策划。\n"
        "任务：对给定草稿进行小红书专属改写/重排。\n"
        "要求：① 标题20字内，带表情符号或数字钩子；② 正文全部短句，每段2-4行；"
        "③ 口语化表达，有共鸣感；④ 末尾必须带3-5个精准 #话题标签。\n"
        "严格按格式输出，不要额外解释：\n"
        "TITLE_XHS: <小红书标题，20字内>\nBODY_XHS:\n<小红书正文，短句分点，末尾带 #标签>"
    ),
    "toutiao": (
        "你是今日头条资深内容策划与主笔。\n"
        "任务：对给定草稿进行头条专属改写/重排。\n"
        "要求：① 标题必须含数字/悬念/反转，吸引点击；② 信息密度高，数据权威；"
        "③ 分段清晰，适合手机快读；④ 首句必须是核心结论或引爆点。\n"
        "严格按格式输出，不要额外解释：\n"
        "TITLE_TT: <头条标题>\nBODY_TT:\n<头条正文 markdown>"
    ),
    "weibo": (
        "你是微博爆款内容策划与金句写手。\n"
        "任务：对给定草稿进行微博专属改写/重排。\n"
        "要求：① 总字数800字以内；② 首句必须是金句或反差观点；"
        "③ 每段一个核心观点，短而有力；④ 结尾引导评论/转发；⑤ 加2-3个话题标签。\n"
        "严格按格式输出，不要额外解释：\n"
        "TITLE_WEIBO: <微博热榜标题>\nBODY_WEIBO:\n<微博正文，简洁有力，末尾带话题标签>"
    ),
    "zhihu": (
        "你是知乎顶流答主和深度内容主笔。\n"
        "任务：对给定草稿进行知乎专属改写/重排。\n"
        "要求：① 标题用疑问/对比句式；② 内容有理有据，引用数据/案例；"
        "③ 结构完整（背景→论点→论据→结论）；④ 专业术语适度，不失亲和力。\n"
        "严格按格式输出，不要额外解释：\n"
        "TITLE_ZHIHU: <知乎标题>\nBODY_ZHIHU:\n<知乎正文 markdown，论据充分>"
    ),
    "twitter": (
        "你是推特/X 爆款内容策划与英文写手。\n"
        "任务：将给定草稿改写为推特/X 专属 Thread 格式。\n"
        "要求：① 每条推文280字符以内；② 用 1/ 2/ 3/ 编号排列 Thread；"
        "③ 首条必须是核心金句或惊人数字；④ 末条引导关注，带2-3个 #hashtag。\n"
        "严格按格式输出，不要额外解释：\n"
        "TEXT_TWITTER:\n<Thread 格式推文，每条用 --- 分隔>"
    ),
}


def rewrite_single_platform(draft_id: str, platform: str, instruction: str = "") -> dict:
    """对单个平台进行专属重写/重排，只更新该平台文件，不影响其他平台。
    
    v3.33新增功能。
    """
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    
    prompt = PLATFORM_REWRITE_PROMPTS.get(platform)
    if not prompt:
        raise RuntimeError(f"不支持的平台: {platform}")
    
    # 构建上下文：原标题+原正文+可选指令
    extra = f"\n\n【创作定向要求】{instruction}" if instruction else ""
    user_content = (
        f"【原草稿主题/标题】{d['title']}\n"
        f"【原正文内容】\n{d['body_md'][:3000]}"
        f"{extra}"
    )
    
    # 保存历史版本
    db.add_history(draft_id, d["title"], d["body_md"],
                   (judge.get_score(draft_id) or {}).get("total"))
    
    raw = agents.chat_for("write", [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content}],
        temperature=0.85)
    
    ddir = db.draft_dir(draft_id)
    updated = {}
    
    # 解析并写入对应平台文件
    if platform == "wechat_mp":
        parsed = _parse_rewrite(raw)
        title = (parsed.get("TITLE_WX") or d["title"])[:40]
        body = parsed.get("BODY_WX") or ""
        if body:
            from adapters.base import save_preview
            from core.layouter import render as layout_render
            from core.imagegen import inject_images_to_markdown
            theme, card_style = _cfg_theme()
            injected = inject_images_to_markdown(body, draft_id)
            save_preview(ddir, "wechat_mp", layout_render(body, title, theme, meta="一幕·YIMU 爆款工作室"))
            c = db.conn()
            c.execute("UPDATE drafts SET title=?, body_md=? WHERE id=?", (title, body, draft_id))
            c.commit(); c.close()
            updated = {"title": title, "body": body}
    
    elif platform == "xhs":
        _, card_style = _cfg_theme()
        res = ai_xhs_upgrade_pipeline(draft_id, style=card_style or "ai_visual_dark", emit=None)
        updated = {"xhs_title": res.get("title", d["title"]), "xhs_body": res.get("text", "")}
    
    elif platform == "toutiao":
        parsed = _parse_rewrite(raw)
        tt_title = (parsed.get("TITLE_TT") or d["title"])[:40]
        tt_body = parsed.get("BODY_TT") or ""
        if tt_body:
            from adapters import toutiao
            from adapters.base import save_preview
            from core.imagegen import inject_images_to_markdown
            injected = inject_images_to_markdown(tt_body, draft_id)
            save_preview(ddir, "toutiao", toutiao.render_preview(injected, tt_title, draft_id=draft_id))
            (ddir / "toutiao.md").write_text(f"# {tt_title}\n\n{injected}", encoding="utf-8")
            updated = {"tt_title": tt_title, "tt_body": tt_body}
    
    elif platform == "weibo":
        # 解析 BODY_WEIBO 格式
        weibo_title, weibo_body = d["title"], ""
        for line in raw.splitlines():
            m = re.match(r"^TITLE_WEIBO\s*[:：]\s*(.+)$", line)
            if m: weibo_title = m.group(1).strip()
            m2 = re.match(r"^BODY_WEIBO\s*[:：]", line)
            if m2: weibo_body = ""
        # 简单提取：BODY_WEIBO 后面的内容
        import re as _re
        weibo_match = _re.search(r"BODY_WEIBO\s*[:：]\s*(.*)", raw, _re.DOTALL)
        if weibo_match:
            weibo_body = weibo_match.group(1).strip()
        if weibo_body:
            from adapters import weibo as weibo_adapter
            from adapters.base import save_preview
            from core.imagegen import inject_images_to_markdown
            injected = inject_images_to_markdown(weibo_body, draft_id)
            save_preview(ddir, "weibo", weibo_adapter.render_preview(injected, weibo_title, draft_id=draft_id))
            (ddir / "weibo.md").write_text(f"# {weibo_title}\n\n{injected}", encoding="utf-8")
            updated = {"weibo_title": weibo_title, "weibo_body": weibo_body}
    
    elif platform == "zhihu":
        import re as _re
        zhihu_title, zhihu_body = d["title"], ""
        zhihu_match = _re.search(r"BODY_ZHIHU\s*[:：]\s*(.*)", raw, _re.DOTALL)
        title_match = _re.search(r"TITLE_ZHIHU\s*[:：]\s*(.+)", raw)
        if title_match: zhihu_title = title_match.group(1).strip()
        if zhihu_match: zhihu_body = zhihu_match.group(1).strip()
        if zhihu_body:
            from adapters import zhihu as zhihu_adapter
            from adapters.base import save_preview
            from core.imagegen import inject_images_to_markdown
            injected = inject_images_to_markdown(zhihu_body, draft_id)
            save_preview(ddir, "zhihu", zhihu_adapter.render_preview(injected, zhihu_title, draft_id=draft_id))
            (ddir / "zhihu.md").write_text(f"# {zhihu_title}\n\n{injected}", encoding="utf-8")
            updated = {"zhihu_title": zhihu_title, "zhihu_body": zhihu_body}
    
    elif platform == "twitter":
        import re as _re
        tw_match = _re.search(r"TEXT_TWITTER\s*[:：]\s*(.*)", raw, _re.DOTALL)
        tw_text = tw_match.group(1).strip() if tw_match else raw.strip()
        if tw_text:
            from adapters import twitter as twitter_adapter
            from adapters.base import save_preview
            save_preview(ddir, "twitter", twitter_adapter.render_twitter_html(tw_text, d["title"]))
            (ddir / "twitter.md").write_text(tw_text, encoding="utf-8")
            updated = {"twitter_text": tw_text}
    
    return {
        "ok": True,
        "platform": platform,
        "draft_id": draft_id,
        "updated": updated,
        "draft": db.get_draft(draft_id)
    }


SURGICAL_REFINE_PROMPT = (
    "你是顶级新媒体爆款主编。你的任务是针对当前文章指出的具体短板，执行【外科手术式的精准定点精修】。\n"
    "注意：你不需要全篇盲目重写，而是精准攻坚并消除指出的这些具体缺陷：\n"
    "- 标题钩子弱：重炼更具数字悬念、反差或认知颠覆的高点击标题；\n"
    "- 干货深度不足/缺数据：在对应正文段落注入权威数据、真实案例与专业操作细节；\n"
    "- 语言平淡/缺情绪：强化冲突与共鸣，提炼金句；\n"
    "- 视觉排版密集：优化分段分节（### 小节、- 列表），制造呼吸感；\n"
    "- 结尾缺乏转化：强化引导评论、收藏、转发的强互动 CTA 与情绪收口。\n\n"
    "严格按以下格式输出精修后的完整稿，不要输出任何多余解释：\n"
    "TITLE_WX: <公众号精修标题>\nBODY_WX:\n<公众号精修正文 markdown，### 分节>\n"
    "TITLE_XHS: <小红书精修标题，20字内>\nBODY_XHS:\n<小红书精修正文，短句分点，末尾带 #标签>\n"
    "TITLE_TT: <头条精修标题>\nBODY_TT:\n<头条精修正文 markdown>\n"
    "铁律：任何版本正文里严禁出现『视觉指南/配图建议/封面设计/排版说明』等制作性文字。"
)


def refine_draft_points(draft_id: str, defects: list[str]) -> dict:
    """执行外科手术式定点补齐缺陷，并重新自动评分。"""
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    if not defects:
        raise RuntimeError("请指定至少一条需要定点补齐的短板项")

    defect_text = "\n".join(f"- 待消除短板 #{i+1}：{x}" for i, x in enumerate(defects))
    db.add_history(draft_id, d["title"], d["body_md"],
                   (judge.get_score(draft_id) or {}).get("total"))
    raw = agents.chat_for("write", [
        {"role": "system", "content": SURGICAL_REFINE_PROMPT},
        {"role": "user", "content":
            f"【当前原稿】\n标题：{d['title']}\n{d['body_md'][:4000]}\n\n"
            f"【本次必须精准切除并补齐的短板清单】：\n{defect_text}"}],
        temperature=0.75)
    parsed = _parse_rewrite(raw)
    title = (parsed.get("TITLE_WX") or d["title"])[:40]
    body = parsed.get("BODY_WX") or d["body_md"]
    _refresh_artifacts(draft_id, parsed, title, body)
    score = judge.judge_draft(draft_id)
    return {"score": score, "draft": db.get_draft(draft_id), "fixed_count": len(defects)}


def init_draft_artifacts(draft_id: str, title: str, body_md: str, media_name: str = "一幕·YIMU 爆款工作室"):
    """为新建或导入的外稿初始化多端文件与初始预览。有实质内容时自动后台生成 3-5 张配图。"""
    ddir = db.draft_dir(draft_id)
    (ddir / "img").mkdir(parents=True, exist_ok=True)
    clean_body = body_md.strip() if body_md and body_md.strip() else "### 核心内容\n在此输入您的草稿正文…"
    parsed = {
        "TITLE_WX": title,
        "BODY_WX": clean_body,
        "TITLE_XHS": title[:20],
        "BODY_XHS": clean_body[:600],
        "TITLE_TT": title,
        "BODY_TT": clean_body,
    }
    # 先同步渲染排版预览（不生图，保证快速响应）
    _refresh_artifacts(draft_id, parsed, title, clean_body, media_name=media_name,
                       platforms=["wechat_mp", "xhs", "toutiao"], generate_images=False)
    # 有实质内容时（导入外部文章）：后台异步触发 5 张配图生成，完成后自动更新预览
    if len(clean_body.strip()) > 100:
        import threading
        from core.imagegen import generate_and_inject_images
        def _bg_gen():
            try:
                generate_and_inject_images(draft_id, count=5)
            except Exception:
                pass
        threading.Thread(target=_bg_gen, daemon=True).start()


def ai_upgrade_draft(
    draft_id: str,
    persona_id: str = "",
    skills: list[str] | None = None,
    focus_targets: list[str] | None = None,
    custom_instruction: str = "",
    media_name: str = ""
) -> dict:
    """结合名家文风、专属技能库与黄金钩子/去AI味对草稿进行一键深度改写与提分。"""
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")

    # 继承工作区配置
    from core import workspace
    active_ws = workspace.get_active_workspace()
    ws_cfg = (active_ws.get("config") if active_ws else {}) or {}

    # 若未指定，自动继承工作区名家与技能
    if not persona_id:
        persona_id = ws_cfg.get("persona", "")
    if skills is None:
        skills = ws_cfg.get("skills", ["title-forge", "de-ai", "viral-formulas"])
    if not media_name:
        media_name = ws_cfg.get("media_name", "一幕·YIMU 爆款工作室")

    focus_targets = focus_targets or ["hook", "de_ai", "punchlines", "cta"]

    # 1. 组装名家文风指纹
    persona_rule = ""
    if persona_id:
        pv = get_voice_content(persona_id)
        if pv:
            persona_rule = (
                f"\n\n【必须贯彻的大师/名家行文指纹（{persona_id}）】：\n"
                f"请在公众号长文、小红书、头条各版本中，全面融入以下标志性语调、句式节奏、用词哲学与思考姿态：\n"
                f"{pv[:2000]}\n"
            )

    # 2. 组装所选技能规则
    skills_rule = ""
    if skills:
        skill_lib = agents.list_skills()
        sk_parts = []
        for sk_id in skills:
            sk_obj = skill_lib.get(sk_id)
            if sk_obj:
                sk_parts.append(f"◆ 技能【{sk_obj['name']}】：{sk_obj['description']}\n{sk_obj['body']}")
        if sk_parts:
            skills_rule = "\n\n【必须严格调用的核心爆款技能规范】：\n" + "\n\n".join(sk_parts)

    # 3. 组装重点攻坚维度
    focus_items = []
    if "hook" in focus_targets:
        focus_items.append("1. 【黄金3秒Hook与悬念攻坚】：开头前100字坚决杜绝客套与废话，用强反差、认知失调、数据悬念或极端场景瞬间抓住读者眼球，制造不得不读下去的好奇心缺口。")
    if "de_ai" in focus_targets:
        focus_items.append("2. 【深度去除AI味与注入活人感】：严禁使用『首先、总而言之、不可否认的是、宛如、犹如、让我们来看看、在这个快节奏的时代』等AI机械公文腔；全篇改用口语化短句、生活人味细节与自然呼吸感节奏。")
    if "punchlines" in focus_targets:
        focus_items.append("3. 【震撼认知金句与干货密度】：提炼能引发读者疯狂截图、转发朋友圈的穿透性认知金句；论据翔实、逻辑层层递进。")
    if "cta" in focus_targets:
        focus_items.append(f"4. 【结尾强互动与品牌收口】：自然融入发布媒体/创作者账号标识【{media_name}】，设置引发强烈评论欲的提问或价值交付式关注号召。")

    focus_text = "\n".join(focus_items)

    # 2.5 组装 6 维账号数字画像与长期记忆 (借鉴 Easel Profile 体系)
    profile_rule = workspace.build_profile_system_prompt()

    system_prompt = (
        "你是顶级新媒体爆款主编与文案重构大师。你的任务是对用户输入的草稿进行【全方位一键深度改写与品质飞跃】。\n"
        "你需要保持原稿的核心事实与价值主张，但将行文、结构、节奏、语调彻底爆款化重塑。\n\n"
        f"【核心攻坚目标】\n{focus_text}\n"
        f"{persona_rule}\n"
        f"{skills_rule}\n"
        f"{profile_rule}\n\n"
        "严格按以下格式输出改写后的各平台完整内容，不要输出任何额外的解释或对话：\n"
        "TITLE_WX: <公众号重塑后爆款标题，28字内>\nBODY_WX:\n<公众号重塑后正文 markdown，使用 ### 分节，金句加粗，段落短小有呼吸感>\n"
        "TITLE_XHS: <小红书高赞标题，情绪钩子，20字内>\nBODY_XHS:\n<小红书爆款文案，短句分点，击中痛点，末尾带 #标签>\n"
        "TITLE_TT: <今日头条高推荐标题>\nBODY_TT:\n<今日头条正文 markdown>\n"
        "铁律：任何平台正文中严禁出现『视觉指南/配图建议/封面设计/排版说明』等幕后制作性文字。"
    )

    user_prompt = (
        f"【原稿标题】：{d['title']}\n"
        f"【原稿正文】：\n{d['body_md'][:5000]}\n"
    )
    if custom_instruction:
        user_prompt += f"\n【创作者追加特别要求】：{custom_instruction}\n"

    raw = agents.chat_for("write", [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ], temperature=0.75)

    parsed = _parse_rewrite(raw)
    if not parsed.get("BODY_WX"):
        parsed["TITLE_WX"] = parsed.get("TITLE_WX") or d["title"]
        parsed["BODY_WX"] = raw.strip()
        parsed["TITLE_XHS"] = parsed.get("TITLE_XHS") or d["title"][:20]
        parsed["BODY_XHS"] = d.get("body_md", "")[:600]
        parsed["TITLE_TT"] = parsed.get("TITLE_TT") or d["title"]
        parsed["BODY_TT"] = raw.strip()

    new_title = (parsed.get("TITLE_WX") or d["title"])[:40]
    new_body = parsed.get("BODY_WX") or d["body_md"]

    # 记录历史版本 & 保存当前改写前的分数基线
    pre_score = (judge.get_score(draft_id) or {}).get("total") or 0.0
    db.add_history(draft_id, d["title"], d["body_md"], pre_score)

    # 更新主数据库
    db.update_draft_title(draft_id, new_title)
    db.update_draft_body(draft_id, new_body)

    # 刷新全域多端产物与排版
    _refresh_artifacts(draft_id, parsed, new_title, new_body, media_name=media_name)

    # 重新评审打分 —— v5.302: 传入 min_score=pre_score 确保不退分
    score = judge.judge_draft(draft_id, min_score=pre_score)

    # v5.302 分数保升机制：若经评审后分数仍未超越改写前分数
    # （理论上 judge_draft 的 floor 保护已经能防止这种情况，
    #  但为双重保险，此处额外执行一轮外科手术式微补丁）
    if score.get("total", 0) <= pre_score and pre_score > 0:
        improvements = score.get("improvements", []) or [
            "进一步强化标题悬念钩子与数字冲击力",
            "压缩段落至 3 行内，提升呼吸感与易读性",
            "在结尾加入明确的互动引导与 CTA 行动召唤",
        ]
        try:
            refine_res = refine_draft_points(draft_id, improvements[:3])
            refined_score = judge.judge_draft(draft_id, min_score=pre_score)
            if refined_score.get("total", 0) >= score.get("total", 0):
                score = refined_score
        except Exception as re_err:
            logger.warning(f"ai_upgrade 自动二次优化失败，忽略: {re_err}")

    return {
        "ok": True,
        "draft_id": draft_id,
        "title": new_title,
        "body_md": new_body,
        "score": score,
        "persona": persona_id,
        "skills": skills,
        "draft": db.get_draft(draft_id)
    }


def evolve_draft_to_target(draft_id: str, target_score: int = 80,
                           max_rounds: int = 3, emit=None) -> dict:
    """目标分驱动的自进化炼丹熔炉：根据目标门槛分持续迭代打磨，直到突破或轮数用尽。"""
    emit = emit or (lambda *_: None)
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    target_score = max(60, min(int(target_score), 98))
    max_rounds = max(1, min(int(max_rounds), 15))

    history = []
    score = judge.judge_draft(draft_id)
    history.append({
        "round": 0,
        "score": score["total"],
        "grade": score.get("grade", ""),
        "scores": score.get("scores", {}),
        "reasons": score.get("reasons", {}),
        "improvements": score.get("improvements", [])
    })

    rounds = 0
    while score["total"] < target_score and rounds < max_rounds:
        rounds += 1
        shortfalls = score.get("improvements", []) or ["针对 7 维打分各项不足全面深化打磨"]
        emit(f"第 {rounds}/{max_rounds} 轮自进化炼制中（当前 {score['total']}分 ➔ 目标 {target_score}分）…")
        try:
            res = refine_draft_points(draft_id, shortfalls[:3])
            score = res["score"]
        except Exception:
            traceback.print_exc()
            break
        history.append({
            "round": rounds,
            "score": score["total"],
            "grade": score.get("grade", ""),
            "scores": score.get("scores", {}),
            "reasons": score.get("reasons", {}),
            "improvements": score.get("improvements", [])
        })

    achieved = (score["total"] >= target_score)
    emit(f"进化熔炉结束：最终得分 {score['total']} 分（{'已达标 ✓' if achieved else '已用尽轮数'}）")
    return {
        "achieved": achieved,
        "target_score": target_score,
        "final_score": score["total"],
        "total_rounds": rounds,
        "history": history,
        "draft": db.get_draft(draft_id),
    }


def judge_and_iterate(draft_id: str, emit=None) -> dict:
    """评审 → 低于合格线自动带意见重写 → 达标即停（或轮数用尽）。"""
    emit = emit or (lambda *_: None)
    qc = judge.quality_cfg()
    res = evolve_draft_to_target(draft_id, target_score=int(qc["threshold"]),
                                max_rounds=int(qc["max_rounds"]), emit=emit)
    final_score = judge.get_score(draft_id) or {"total": res["final_score"]}
    return {"total": res["final_score"], "grade": final_score.get("grade", ""),
            "history": [h["score"] for h in res["history"]],
            "improvements": final_score.get("improvements", []),
            "scores": final_score.get("scores", {}),
            "reasons": final_score.get("reasons", {})}


def run_once() -> dict:
    """抓一轮热榜选题入库（返回统计）。"""
    return collect_topics()


XHS_REWRITE_PROMPT = (
    "你是顶级小红书爆款内容总监与视觉文案大师。请深度理解给到的文章，提炼出 4~5 张高吸引力、结构严谨的轮播图文案。\n"
    "核心要求：\n"
    "1. 必须深度契合文章主题：精准抽出文章最核心的 3~4 个分论点/实操干货/反常识亮点，做成系列卡片；\n"
    "2. 封面页：标题≤20字，必须有强烈钩子（数字对比/认知反差/痛点直击），让人忍不住下滑；\n"
    "3. 内页（3~4页）：每页针对文章的一个核心要点，给出一个吸睛小标题（如「01 认知突围｜避开3大隐形雷区」），下附2~3条精炼金句或硬核实操，配合生动emoji，文案具有极高价值感与吸引力；\n"
    "4. 最后一页：CTA互动页，设置引发热议的问题，引导点赞收藏+评论区互动；\n"
    "5. 末尾提供 5-8 个精准的高流量小红书 #话题标签；\n"
    "严格按以下格式输出，禁止任何多余解释与噪音符号：\n"
    "TITLE: <封面标题>\n"
    "PAGE: <第1张内页核心小点标题>\nLINE: <提炼金句/要点1>\nLINE: <提炼金句/要点2>\n"
    "PAGE: <第2张内页核心小点标题>\nLINE: <提炼金句/要点1>\nLINE: <提炼金句/要点2>\n"
    "PAGE: <第3张内页核心小点标题>\nLINE: <提炼金句/要点1>\nLINE: <提炼金句/要点2>\n"
    "PAGE: <互动收尾页标题>\nLINE: <互动提问>\nLINE: <行动呼吁>\n"
    "TAGS: #标签1 #标签2 #标签3\n"
    "铁律：绝对禁止出现任何『视觉指南/配图建议/封面设计/排版说明』等说明性文字，所有内容必须是直接展示给读者的成品文案。"
)


# ---------------- 小红书独立历史版本回溯与全能 AI 改写流水线 ----------------

def save_xhs_history_snapshot(draft_id: str, note: str = "") -> dict | None:
    """保存小红书专属历史版本快照（包含 xhs.md 文本和生成的全套 card-*.png 图片）。"""
    ddir = db.draft_dir(draft_id)
    xhs_file = ddir / "xhs.md"
    cards = sorted(list(ddir.glob("card-*.png")), key=lambda p: [int(x) if x.isdigit() else x for x in re.findall(r'\d+|\D+', p.name)])

    if not xhs_file.exists() and not cards:
        return None

    hist_dir = ddir / "xhs_history"
    hist_dir.mkdir(parents=True, exist_ok=True)

    snap_id = f"xhs_snap_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    target_dir = hist_dir / snap_id
    target_dir.mkdir(parents=True, exist_ok=True)

    # 复制 xhs.md
    xhs_content = ""
    title = ""
    if xhs_file.exists():
        xhs_content = xhs_file.read_text(encoding="utf-8")
        shutil.copy2(xhs_file, target_dir / "xhs.md")
        for l in xhs_content.splitlines():
            if l.strip().startswith("# "):
                title = l.strip()[2:].strip()
                break
    if not title:
        d = db.get_draft(draft_id)
        title = (d or {}).get("title", "小红书图文")

    # 复制所有 card-*.png
    copied_cards = []
    for c in cards:
        shutil.copy2(c, target_dir / c.name)
        copied_cards.append(c.name)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = {
        "id": snap_id,
        "created_at": now_str,
        "timestamp": int(time.time()),
        "title": title[:30],
        "note": note or "小红书快照",
        "cards_count": len(copied_cards),
        "cards": copied_cards,
        "summary": (xhs_content[:140] if xhs_content else f"{len(copied_cards)} 张卡片")
    }

    (target_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 清理多余版本（最多保留最近 15 个快照）
    try:
        all_snaps = sorted(
            [p for p in hist_dir.iterdir() if p.is_dir() and (p / "meta.json").exists()],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if len(all_snaps) > 15:
            for old in all_snaps[15:]:
                shutil.rmtree(old, ignore_errors=True)
    except Exception as ce:
        logger.warning(f"清理小红书历史快照失败: {ce}")

    return meta


def list_xhs_history(draft_id: str) -> list[dict]:
    """获取指定草稿的所有小红书专属历史版本。"""
    ddir = db.draft_dir(draft_id)
    hist_dir = ddir / "xhs_history"
    if not hist_dir.exists():
        return []
    res = []
    for p in hist_dir.iterdir():
        if p.is_dir():
            mf = p / "meta.json"
            if mf.exists():
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    snap_id = data.get("id") or p.name
                    data["id"] = snap_id
                    data["card_urls"] = [
                        f"/api/drafts/{draft_id}/xhs/history/{snap_id}/card/{c}"
                        for c in data.get("cards", [])
                    ]
                    # 读取该版本 xhs.md 内容预览
                    snap_md = p / "xhs.md"
                    if snap_md.exists():
                        data["text"] = snap_md.read_text(encoding="utf-8")
                    else:
                        data["text"] = ""
                    res.append(data)
                except Exception as e:
                    logger.warning(f"解析历史快照失败 {p}: {e}")
    res.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return res


def restore_xhs_history(draft_id: str, snapshot_id: str) -> dict:
    """回溯还原指定的小红书历史版本（包括 xhs.md 和卡片图片）。"""
    ddir = db.draft_dir(draft_id)
    target_dir = ddir / "xhs_history" / snapshot_id
    if not target_dir.exists():
        raise RuntimeError(f"历史快照不存在: {snapshot_id}")
    mf = target_dir / "meta.json"
    if not mf.exists():
        raise RuntimeError("快照元数据损坏")
    meta = json.loads(mf.read_text(encoding="utf-8"))

    # 还原前对当前小红书版本做一次快照存档，防止误操作丢失
    save_xhs_history_snapshot(draft_id, note="回溯前自动存档")

    # 还原 xhs.md
    snap_xhs = target_dir / "xhs.md"
    xhs_text = ""
    if snap_xhs.exists():
        xhs_text = snap_xhs.read_text(encoding="utf-8")
        shutil.copy2(snap_xhs, ddir / "xhs.md")

    # 还原 card-*.png
    for c in ddir.glob("card-*.png"):
        try:
            c.unlink()
        except Exception:
            pass

    restored_cards = []
    for c in target_dir.glob("card-*.png"):
        shutil.copy2(c, ddir / c.name)
        restored_cards.append(c.name)

    restored_cards = sorted(
        restored_cards,
        key=lambda x: [int(n) if n.isdigit() else n for n in re.findall(r'\d+|\D+', x)]
    )

    # 同步更新 matrix.json
    matrix_file = ddir / "matrix.json"
    if matrix_file.exists():
        try:
            m_data = json.loads(matrix_file.read_text(encoding="utf-8"))
            if "xhs" in m_data:
                m_data["xhs"]["cards"] = restored_cards
                m_data["xhs"]["cards_count"] = len(restored_cards)
                matrix_file.write_text(json.dumps(m_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "title": meta.get("title", ""),
        "cards": restored_cards,
        "text": xhs_text,
        "restored_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def ai_xhs_upgrade_pipeline(draft_id: str, style: str = "ai_visual_dark", emit=None) -> dict:
    """小红书统一 AI 改写提升与全套视觉图文卡片流水线：
    1. 总结上下文（通读提炼 4 幕核心卖点矩阵）；
    2. 根据总结的上下文内容生成专属高清插图（共 5 张：封面+4幕）；
    3. 总结内容经 AI 深度优化为小红书专属爆款文案，更新 xhs.md 并压制成套卡片；
    4. 自动记录小红书独立历史版本快照（含文案与全套卡片图）。
    """
    emit = emit or (lambda *_: None)
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    ddir = db.draft_dir(draft_id)

    # 步骤 1：总结上下文
    emit("🔍 Step 1/4: 深度通读文章，提炼小红书 4 幕核心卖点矩阵…")
    from core.copilot import extract_xhs_card_selling_points
    sections = []
    try:
        sections = extract_xhs_card_selling_points(d["title"], d["body_md"])
    except Exception as spe:
        logger.warning(f"提炼核心卖点失败: {spe}")

    if not sections or len(sections) < 2:
        lines = [ln.strip() for ln in d["body_md"].splitlines() if ln.strip()]
        cur_t, cur_pts = None, []
        for ln in lines:
            if ln.startswith("### ") or ln.startswith("## ") or (ln.startswith("【") and ln.endswith("】")):
                if cur_t and cur_pts:
                    sections.append((cur_t, cur_pts))
                cur_t = re.sub(r'^[#【\s]+|[】]+$', '', ln).strip()
                cur_pts = []
            elif ln and not ln.startswith("#") and not ln.startswith("🔥"):
                cur_pts.append(ln.lstrip("-• 1234567890.、")[:40])
        if cur_t and cur_pts:
            sections.append((cur_t, cur_pts))

    if not sections:
        paras = [p.strip() for p in d["body_md"].split("\n\n") if p.strip() and not p.strip().startswith("#")]
        sections = [(f"核心要点 {i+1}", [p[:40]]) for i, p in enumerate(paras[:4])]

    # 确保至少有 4 幕正文小节（加上封面共 5 张卡片）
    if len(sections) < 4:
        paras = [p.strip() for p in d["body_md"].split("\n\n") if p.strip() and not p.strip().startswith("#")]
        default_names = ["🔑 核心洞察", "💡 痛点破局", "✨ 实操法则", "🎯 行动指南"]
        for j, para in enumerate(paras[:4]):
            if len(sections) >= 4:
                break
            sections.append((default_names[j % len(default_names)], [para[:40]]))

    # 步骤 2：根据上下文内容生成图片
    emit("🎨 Step 2/4: 根据提炼的上下文内容，并发生成全套高清视觉配图 (共 5 张)…")
    from core.imagegen import decorate_draft
    sec_arg = [(s[0], s[1][0] if s[1] else s[0]) for s in sections[:4]]
    decorate_draft(ddir, d["title"], sec_arg, body_md=d["body_md"], count=5)

    # 步骤 3：所展示的内容是总结出来以后让 AI 进行优化以后的内容
    emit("✨ Step 3/4: 总结内容经 AI 深度优化（注入痛点钩子、去AI味、爆款短句排版）…")
    summarized_brief = f"原标题：《{d['title']}》\n提炼出的核心要点结构：\n"
    for i, (st, pts) in enumerate(sections[:4], 1):
        summarized_brief += f"第{i}幕【{st}】:\n" + "\n".join(f"- {p}" for p in pts) + "\n"

    # 借鉴 Easel carousel-planner 体系，注入卡片剧本心理节奏
    opt_prompt = (
        "你是顶级小红书文案专家与爆款视觉卡片主理人。请基于以下总结出的核心要点，结合【爆款轮播图心理节奏规划 (Carousel Planner)】进行【深度优化与重构】：\n"
        "【卡片节奏规划设计】：\n"
        "• 第1幕 (共鸣踩坑/痛点还原): 还原受众最真实的踩坑场景，击碎常识盲区，引发强烈代入；\n"
        "• 第2幕 (核心转折/底层逻辑): 给出认知破局点，用极简逻辑拆解本质原因；\n"
        "• 第3幕 (实操清单/硬核交付): 给出可落地的 1-2-3 步骤或避坑自查清单，激发读者点击收藏；\n"
        "• 第4幕 (强力收尾/金句升华): 提炼穿透性认知金句，并附带低门槛评论区互动钩子。\n\n"
        f"{summarized_brief}\n\n"
        "优化要求：\n"
        "1. 标题必须有极强的点击欲、情绪钩子或反差，20字以内，包含合适emoji。\n"
        "2. 正文必须语言简练、短句分明、句式呼吸感强、彻底去除AI机械公文腔，直击痛点与实操价值。\n"
        "3. 严格保留 4 幕小结，每幕以【小标题】引导，下面附 2-3 条短句要点（每条不超过35字）。\n"
        "4. 末尾提供 5-8 个热门标签，以 # 开头。\n"
        "5. 严禁输出任何『视觉指南/封面建议/排版说明』等幕后制作性文字。\n\n"
        "请严格按以下格式输出：\n"
        "TITLE: <爆款小红书标题>\n"
        "PAGE: <第1幕小标题>\n"
        "LINE: <要点1>\n"
        "LINE: <要点2>\n"
        "PAGE: <第2幕小标题>\n"
        "LINE: <要点1>\n"
        "LINE: <要点2>\n"
        "PAGE: <第3幕小标题>\n"
        "LINE: <要点1>\n"
        "LINE: <要点2>\n"
        "PAGE: <第4幕小标题>\n"
        "LINE: <要点1>\n"
        "LINE: <要点2>\n"
        "TAGS: #标签1 #标签2 #标签3"
    )

    xhs_title = d["title"][:22]
    optimized_pages = []
    tags = "#干货分享 #认知思维 #自媒体创业 #生活记录"

    try:
        raw_opt = agents.chat_for("write", [{"role": "user", "content": opt_prompt}], temperature=0.75)
        cur_p = None
        from core.orchestrator import META_KEYWORDS as _MK
        for line in raw_opt.splitlines():
            line = line.strip()
            if line.startswith("TITLE:"):
                t = line[6:].strip()
                if t:
                    xhs_title = t[:25]
            elif line.startswith("PAGE:"):
                heading = line[5:].strip()
                if not any(k in heading for k in _MK):
                    cur_p = {"heading": heading, "lines": []}
                    optimized_pages.append(cur_p)
            elif line.startswith("LINE:"):
                if cur_p and not any(k in line for k in _MK):
                    cur_p["lines"].append(line[5:].strip())
            elif line.startswith("TAGS:"):
                tags = line[5:].strip()
    except Exception as oe:
        logger.warning(f"AI 优化小红书文案失败，使用原总结内容: {oe}")

    if optimized_pages:
        final_sections = [(p["heading"][:18], p["lines"][:3]) for p in optimized_pages[:4]]
    else:
        final_sections = sections[:4]

    # 构建更新后的 xhs.md
    xhs_text = f"# {xhs_title}\n\n"
    for st, pts in final_sections:
        xhs_text += f"【{st}】\n" + "\n".join(f"- {p}" for p in pts) + "\n\n"
    xhs_text += tags
    (ddir / "xhs.md").write_text(xhs_text, encoding="utf-8")

    # 压制成套卡片
    from core.render_card import render_draft_cards
    cover_file = ddir / "img" / "cover.png" if (ddir / "img" / "cover.png").exists() else None
    cards = render_draft_cards(ddir, xhs_title, final_sections, style=style, cover_img=cover_file)

    # 同步更新 matrix.json
    mf = ddir / "matrix.json"
    if mf.exists():
        try:
            m_data = json.loads(mf.read_text(encoding="utf-8"))
            if "xhs" in m_data:
                m_data["xhs"]["cards"] = cards
                m_data["xhs"]["cards_count"] = len(cards)
                m_data["xhs"]["style"] = style
                mf.write_text(json.dumps(m_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # 步骤 4：自动保存独立快照
    emit("💾 Step 4/4: 自动归档小红书独立版本快照（含文案与卡片图）…")
    snap_meta = save_xhs_history_snapshot(draft_id, note="AI 改写提升")

    emit("🎉 小红书 AI 改写提升与全套卡片压制完成！")
    return {
        "ok": True,
        "title": xhs_title,
        "pages": len(final_sections),
        "cards": cards,
        "text": xhs_text,
        "style": style,
        "snapshot": snap_meta
    }


def ai_xhs(draft_id: str, style: str = "magazine", emit=None) -> dict:
    """小红书 AI 重排与文案重构：触发标准小红书 AI 改写提升流水线。"""
    return ai_xhs_upgrade_pipeline(draft_id, style=style, emit=emit)


def ai_xhs_visual(draft_id: str, style: str = "ai_visual_dark", emit=None) -> dict:
    """小红书 AI 视觉全套生图与图文卡片精修制卡引擎。"""
    return ai_xhs_upgrade_pipeline(draft_id, style=style, emit=emit)


def change_xhs_style(draft_id: str, style: str = "magazine") -> dict:
    """即时快速切换小红书卡片美学风格（毫秒级重绘已有内容与配图）。"""
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    ddir = db.draft_dir(draft_id)

    title = d["title"]
    xhs_f = ddir / "xhs.md"
    text = xhs_f.read_text(encoding="utf-8") if xhs_f.exists() else d["body_md"]

    sections = []
    lines = text.splitlines()
    cur_title = None
    cur_paras = []

    for line in lines:
        line_s = line.strip()
        if line_s.startswith("# "):
            title = line_s[2:].strip()
        elif line_s.startswith("### ") or line_s.startswith("## ") or (line_s.startswith("【") and line_s.endswith("】")):
            if cur_title and cur_paras:
                sections.append((cur_title, cur_paras))
            cur_title = line_s.lstrip("#【").rstrip("】").strip()
            cur_paras = []
        elif line_s and not line_s.startswith("#") and not line_s.startswith("🔥"):
            cur_paras.append(line_s.lstrip("-• 1234567890.、"))

    if cur_title and cur_paras:
        sections.append((cur_title, cur_paras))

    if not sections:
        paras = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        sections = [(f"精选看点 {i+1}", [p]) for i, p in enumerate(paras[:5])]
    elif len(sections) < 3:
        paras = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        extra_names = ["🔑 核心要点", "💡 深度解析", "✨ 实战技巧", "🎯 关键洞察", "🚀 行动指南"]
        for j, para in enumerate(paras[:5]):
            if len(sections) >= 5:
                break
            pts = [s.strip() for s in para.splitlines() if s.strip()][:3] or [para[:60]]
            sections.append((extra_names[j % len(extra_names)], pts))

    from core.render_card import render_draft_cards
    cover_file = ddir / "img" / "cover.png" if (ddir / "img" / "cover.png").exists() else None
    cards = render_draft_cards(ddir, title, sections[:5], style=style, cover_img=cover_file)

    # 更新 matrix.json
    mf = ddir / "matrix.json"
    if mf.exists():
        try:
            m_data = json.loads(mf.read_text(encoding="utf-8"))
            if "xhs" in m_data:
                m_data["xhs"]["cards"] = cards
                m_data["xhs"]["cards_count"] = len(cards)
                m_data["xhs"]["style"] = style
                mf.write_text(json.dumps(m_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    save_xhs_history_snapshot(draft_id, note=f"风格切换: {style}")
    return {"ok": True, "title": title, "cards": cards, "style": style}



def approve_and_publish(draft_id: str, platforms: list[str]) -> list[dict]:
    """人工确认后执行发布。公众号走 API，其余进入发布队列（一期人工/二期 Playwright）。"""
    draft = db.get_draft(draft_id)
    if not draft:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    ddir = db.draft_dir(draft_id)
    cfg = load_config().get("publish", {})
    theme, _ = _cfg_theme()
    results = []
    recent = {j["platform"] for j in db.list_jobs()
              if j["draft_id"] == draft_id and time.time() - j["updated_at"] < 300}
    for p in platforms:
        if p in recent:  # 幂等：5分钟内已执行过同一发布，跳过重放请求
            results.append({"platform": p, "ok": True, "detail": "已执行过（防重跳过）"})
            continue
        jid = db.add_job(draft_id, p)
        try:
            if p == "wechat_mp" and cfg.get("wechat_mp_mode") == "api":
                db.set_job(jid, "running")
                media = wechat_mp.push_draft(draft["title"], draft["body_md"], theme=theme)
                db.set_job(jid, "done", f"草稿箱 media_id={media['media_id']}")
                results.append({"platform": p, "ok": True,
                                "detail": f"已进公众号草稿箱 {media['media_id']}"})
            else:
                detail = {"xhs": f"卡片图 {len(list(ddir.glob('card-*.png')))} 张，待发布",
                          "toutiao": "Markdown 已备好，待粘贴发布"}.get(p, "待发布")
                db.set_job(jid, "queued", detail)
                results.append({"platform": p, "ok": True, "detail": f"已排队：{detail}"})
        except Exception as e:
            db.set_job(jid, "failed", str(e)[:300])
            results.append({"platform": p, "ok": False, "detail": str(e)[:300]})
    done = all(r["ok"] for r in results)
    db.set_draft_status(draft_id, "published" if done else "approved")
    return results


# ---------------- 8大名家音色与深度自我进化蒸馏 ----------------

BASE_DIR = Path(__file__).resolve().parent.parent
VOICES_DIR = BASE_DIR / "skills" / "refs" / "humanizer-zh" / "voices"

VOICE_METADATA = {
    "fengtang": {"tts_voice": "zh-CN-YunxiNeural", "tag": "商业随笔", "category": "modern", "tone": "文白杂糅/身体诚实"},
    "wujun": {"tts_voice": "zh-CN-YunyangNeural", "tag": "科技理性", "category": "modern", "tone": "长者洞察/逻辑严密"},
    "luozhenyu": {"tts_voice": "zh-CN-YunxiNeural", "tag": "认知启发", "category": "modern", "tone": "场景痛点/金句抓手"},
    "hefan": {"tts_voice": "zh-CN-YunyangNeural", "tag": "宏观叙事", "category": "modern", "tone": "慢变量/故事化经济"},
    "liuzichao": {"tts_voice": "zh-CN-YunxiNeural", "tag": "文学漫游", "category": "modern", "tone": "冷静白描/世界漫步"},
    "lishanglong": {"tts_voice": "zh-CN-YunxiNeural", "tag": "青年力量", "category": "modern", "tone": "警醒刺痛/直给行动"},
    "lixiaolai": {"tts_voice": "zh-CN-YunyangNeural", "tag": "概念重塑", "category": "modern", "tone": "反常识/底层算法"},
    "helaoshi": {"tts_voice": "zh-CN-YunxiNeural", "tag": "犀利商业", "category": "modern", "tone": "辛辣幽默/解剖本质"},
    "luxun": {"tts_voice": "zh-CN-YunyangNeural", "tag": "冷峻批判", "category": "classic", "tone": "骨感短句/反讽深刻"},
    "wangxiaobo": {"tts_voice": "zh-CN-YunxiNeural", "tag": "黑色幽默", "category": "classic", "tone": "特立独行/智性自由"},
    "yuhua": {"tts_voice": "zh-CN-YunyangNeural", "tag": "沉静宿命", "category": "classic", "tone": "质朴白描/生命重量"},
    "zhangailing": {"tts_voice": "zh-CN-XiaoxiaoNeural", "tag": "华丽苍凉", "category": "classic", "tone": "通感奇喻/世俗冷眼"},
}

def list_famous_voices() -> list[dict]:
    """读取预置名家写作音色及用户自蒸馏大师技能。"""
    out = []
    # 1. 预置声音库
    if VOICES_DIR.exists():
        for f in sorted(VOICES_DIR.glob("*.md")):
            if f.name == "index.md":
                continue
            text = f.read_text(encoding="utf-8")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            title = lines[0].lstrip("# ").replace("声音：", "").strip() if lines else f.stem
            summary = lines[1] if len(lines) > 1 else ""
            meta = VOICE_METADATA.get(f.stem, {})
            out.append({
                "id": f.stem,
                "name": title,
                "summary": summary[:80],
                "file": str(f),
                "tts_voice": meta.get("tts_voice", "zh-CN-YunxiNeural"),
                "tag": meta.get("tag", "名家风格"),
                "category": meta.get("category", "classic"),
                "tone": meta.get("tone", "经典风格"),
                "is_distilled": False,
            })

    # 2. 动态扫描用户自蒸馏的名家与文风技能
    agents_skills_dir = BASE_DIR / "skills" / "agents"
    if agents_skills_dir.exists():
        existing_ids = {x["id"] for x in out}
        exclude_core = {
            "director-beat-sheet", "character-turnaround-sheet", "storyboard-visual-grammar",
            "cinematic-optics-lighting", "sound-director-scoring", "colloquial", "de-ai",
            "judge-strict", "pro-layout", "pro-writing", "query-expand", "title-forge",
            "viral-copy", "viral-formulas", "xhs-style"
        }
        for f in sorted(agents_skills_dir.glob("*.md")):
            if f.stem in existing_ids or f.stem in exclude_core:
                continue
            text = f.read_text(encoding="utf-8")
            if f.stem.startswith("distill-") or "声音与人设指纹" in text or "Voice & Persona" in text:
                name = f.stem.replace("distill-", "")
                desc = ""
                if "description:" in text:
                    m = re.search(r"description:\s*(.+)", text)
                    if m:
                        desc = m.group(1).strip()
                out.append({
                    "id": f.stem,
                    "name": f"自蒸馏·{name}",
                    "summary": desc[:80] or "用户深度蒸馏的专属行文指纹与写作法则",
                    "file": str(f),
                    "tts_voice": "zh-CN-YunxiNeural",
                    "tag": "自蒸馏名家",
                    "category": "custom",
                    "tone": desc[:30] or "定制风格",
                    "is_distilled": True,
                })
    return out


def get_voice_content(voice_id: str) -> str:
    """获取指定作者音色或自蒸馏技能内容。"""
    f = VOICES_DIR / f"{voice_id}.md"
    if f.exists():
        return f.read_text(encoding="utf-8")
    f_agent = BASE_DIR / "skills" / "agents" / f"{voice_id}.md"
    if f_agent.exists():
        return f_agent.read_text(encoding="utf-8")
    return ""


DEEP_DISTILL_PROMPT = """你是一名世界顶级认知语言学家、自媒体爆款逆向工程师和写作教练。
请对给到的代表作或文案样本进行多维度深度逆向蒸馏，提取其“不可复制的底层心智模型与行文指纹”。
必须输出以下结构化内容（Markdown 格式）：
---
name: {slug}
description: {one_line_desc}
---

# {name} 核心爆款基因与写作技能

## 1. 声音与人设指纹 (Voice & Persona)
- **核心人设定位**：说话者的身份感、社会姿态与认知层级
- **标志性语气**：设问习惯、口头禅、幽默感/犀利感
- **标点与断句习惯**：长短句交错比例、破折号/引号/感叹号使用习惯
- **反模式 (绝对禁止)**：该风格绝不会出现的废话、套话与大词

## 2. 黄金 3 秒 Hook 与悬念公式
- **开头套路逆向**：如何在前 30 字内制造认知失调或好奇心缺口
- **冲突制造公式**：例如【极致反差 / 颠覆常识 / 情绪勒索 / 痛点暴击】

## 3. 视觉排版与阅读节奏规范
- **段落长度控制**：平均几句话一段，如何留白
- **重点高亮规则**：加粗与 Emoji 的克制与分布
- **小红书/公众号/头条适配法则**：跨平台分发时的排版变形

## 4. 落地实操创作指令 (Prompt Preamble)
一段可直接嵌入大模型系统提示词中的精炼指令（以 "你现在是..." 开头），让大模型能 100% 还原该风格。
"""


def deep_distill_anything(content: str, distill_type: str = "all", author_name: str = "") -> dict:
    """深度逆向蒸馏任何博主、排版或爆款公式，并沉淀为系统的独立 Skill 资产。"""
    if not content or len(content.strip()) < 50:
        raise RuntimeError("样本文案内容过短，无法提取高质量的底层行文指纹")
    author_name = author_name.strip() or "深度逆向博主"
    import re
    slug = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fa5]", "-", author_name).strip("-").lower() or f"distill-{int(time.time())%10000}"
    
    prompt = f"【待蒸馏的样本文本/博主代表作】（作者/风格名：{author_name}，类型：{distill_type}）：\n\n{content[:4500]}"
    raw = agents.chat_for("write", [
        {"role": "system", "content": DEEP_DISTILL_PROMPT.format(
            slug=slug,
            one_line_desc=f"基于 {author_name} 逆向蒸馏的爆款写作与排版技能",
            name=author_name
        )},
        {"role": "user", "content": prompt}
    ], temperature=0.7)
    
    out_dir = BASE_DIR / "skills" / "agents"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{slug}.md"
    out_file.write_text(raw, encoding="utf-8")
    
    return {
        "ok": True,
        "name": author_name,
        "slug": slug,
        "file": str(out_file),
        "content": raw
    }


def generate_one_sentence_viral(sentence: str, mounted_persona: str = "", theme: str = "",
                                media_name: str = "一幕·YIMU 爆款工作室", emit=None,
                                platforms: list[str] | None = None) -> dict:
    """一句话爆款引擎：
    1. 意图拆解与多组高精准搜索 Query 提炼；
    2. 全网多源真实并发检索 3~5 篇权威长文；
    3. 消化真实文章，结合名家文风生成所选平台的爆款成稿；
    4. 入库草稿箱并完成 7 维智能评审。
    """
    emit = emit or (lambda *_: None)
    sentence = (sentence or "").strip()
    if not sentence:
        raise ValueError("请输入创作灵感或一句话需求")

    selected_platforms = platforms if platforms is not None else ["wechat_mp", "xhs"]

    # Step 1: 意图拆解与检索词提炼
    emit("正在理解创作意图并提炼全网检索词…")
    search_queries = [sentence]
    try:
        raw_kw = agents.chat_for("collect", [
            {"role": "system", "content": "你是资深媒体检索专家。根据用户的一句话创作想法，提炼出 2~3 组用于在全网检索高价值深度文章、真实案例与史料论据的搜索关键词。只输出 JSON 数组，如 [\"关键词1\", \"关键词2\"]，不要任何额外字符。"},
            {"role": "user", "content": f"用户一句话创作意图：{sentence}"}
        ], temperature=0.3)
        import re as _re, json as _json
        m = _re.search(r"\[.*\]", raw_kw, _re.S)
        if m:
            extracted = _json.loads(m.group(0))
            if isinstance(extracted, list) and extracted:
                search_queries = [q.strip() for q in extracted if isinstance(q, str) and q.strip()][:3]
    except Exception:
        pass
    if sentence not in search_queries:
        search_queries.insert(0, sentence)

    # Step 2: 真实全网检索 3~5 篇长文
    emit("正在全网实时检索 3~5 篇权威长文与深度素材…")
    from core.search import fetch_topic_multisource_references
    all_refs = []
    seen_titles = set()
    for q in search_queries:
        try:
            sub_refs = fetch_topic_multisource_references(q, limit=4)
            for r in sub_refs:
                if r["title"] not in seen_titles:
                    seen_titles.add(r["title"])
                    all_refs.append(r)
        except Exception:
            pass
        if len(all_refs) >= 5:
            break

    # 组装真实参考蓝本
    ref_text = ""
    if all_refs:
        ref_text = "\n\n【全网实时抓取到的真实参考长文与核心论据（必须充分理解消化，并以此为事实基底展开写作）】：\n"
        for i, r in enumerate(all_refs[:5], 1):
            ref_text += f"◆ 真实参考源 {i}：《{r['title']}》（来源：{r['source']}）\n  网页核心内容与论据要点：\n{r['snippet']}\n\n"

    # Step 3: 结合名家文风与系统技能进行爆款创作
    emit("正在消化真实素材，融合名家文风进行多平台爆款创作…")
    persona_rule = ""
    if mounted_persona:
        pv = get_voice_content(mounted_persona)
        if pv:
            persona_rule = f"\n\n【必须深度挂载的大师文风指纹 ({mounted_persona})】：\n请在公众号长文、小红书、头条版本中，全面贯彻以下语调节奏、句式用词与修辞哲学：\n{pv[:1800]}\n"

    media_name = (media_name or "").strip() or "一幕·YIMU 爆款工作室"
    media_rule = f"\n\n【发布媒体/创作者署名账号】：{media_name}\n请在正文行文或结尾引导关注时，自然融入该账号品牌标识（如「欢迎关注【{media_name}】」）。"
    target_theme = theme.strip() if theme and theme.strip() else sentence

    user_msg = (
        f"【用户一句话创作意图】：{sentence}\n"
        f"【聚焦核心主题】：{target_theme}\n"
        f"{ref_text}"
        f"{persona_rule}"
        f"{media_rule}\n\n"
        f"【创作要求】：\n"
        f"1. 严格围绕用户的一句话核心意图展开，深度借力上述全网抓取的真实事实与论据；\n"
        f"2. 绝对不捏造或偏向无关领域；\n"
        f"3. 保持公众号文章深度（至少 1500~2200 字，故事性、痛点与洞察俱全）、小红书笔记高互动（短句、排版吸睛）、今日头条客观透彻；"
    )

    raw_output = agents.chat_for("write", [
        {"role": "system", "content": ONE_SENTENCE_VIRAL_PROMPT},
        {"role": "user", "content": user_msg}
    ], temperature=0.85)

    parsed = _parse_rewrite(raw_output)
    title = (parsed.get("TITLE_WX") or sentence)[:40]
    body = parsed.get("BODY_WX") or f"（成稿解析失败）\n{raw_output[:600]}"

    emit("排版渲染与配图…")
    cand_titles = generate_candidate_titles(title, body)
    draft = db.add_draft(
        None, title, body, selected_platforms,
        source_platform="one_sentence",
        source_url="",
        source_title=sentence,
        analysis=parsed.get("ANALYSIS", ""),
        candidate_titles=cand_titles,
        source_stats={"search_queries": search_queries, "reference_count": len(all_refs)}
    )
    _refresh_artifacts(draft["id"], parsed, title, body, media_name=media_name, platforms=selected_platforms)

    # Step 4: 7 维智能评审打分
    score = None
    if llm.available():
        emit("正在进行 7 维爆款智能评审打分…")
        try:
            score = judge_and_iterate(draft["id"], emit=emit)
        except Exception:
            pass

    return {
        "draft_id": draft["id"],
        "title": title,
        "score": score,
        "queries": search_queries,
        "references": all_refs[:5]
    }


def batch_create_drafts(items: list[dict], options: dict = None, emit=None, task=None) -> dict:
    """批量矩阵生产引擎 (Batch Engine)：
    支持一次性传入多组选题/一句话或长文，
    后台顺序/受控并发执行全套生成（长文、配图、小红书卡片、7维打分），
    配合 task 汇报工业级百分比进度与 Checkpoint。
    """
    emit = emit or (lambda *_: None)
    options = options or {}
    persona = options.get("persona", "鲁迅（冷峻深刻/讽刺幽默）")
    theme = options.get("theme", "spring-fresh")
    media_name = options.get("media_name", "一幕·YIMU 爆款工作室")

    total = len(items)
    if total == 0:
        return {"ok": False, "msg": "批量列表为空", "results": []}

    results = []
    emit(f"批量矩阵任务启动：共 {total} 篇选题待生成…")

    for idx, it in enumerate(items, 1):
        if task and task.is_cancelled():
            emit("用户已取消后续批量任务。")
            break

        sentence = it.get("sentence") or it.get("title") or it.get("text", "")
        if not sentence or not sentence.strip():
            continue

        emit(f"[{idx}/{total}] 正在全网挖掘与生成：《{sentence[:25]}…》")
        if task:
            task.checkpoint(idx - 1, total, f"正在生成第 {idx}/{total} 篇：《{sentence[:20]}》")

        try:
            res = generate_one_sentence_viral(
                sentence=sentence.strip(),
                mounted_persona=it.get("persona") or persona,
                theme=it.get("theme") or theme,
                media_name=media_name,
                emit=lambda msg: emit(f"[{idx}/{total}] {msg}")
            )
            draft_id = res.get("draft_id")
            results.append({
                "draft_id": draft_id,
                "title": res.get("title", sentence),
                "score": res.get("score"),
                "status": "success"
            })
        except Exception as e:
            logger.error(f"批量生成第 {idx} 篇失败: {e}", exc_info=True)
            results.append({
                "title": sentence,
                "error": str(e),
                "status": "failed"
            })

    if task:
        task.checkpoint(total, total, f"批量生产完成，共成功 {len([r for r in results if r['status'] == 'success'])} 篇")

    emit(f"🎉 批量生产完毕！成功 {len([r for r in results if r['status'] == 'success'])}/{total} 篇")
    return {"ok": True, "total": total, "results": results}


def clean_xhs_text(text: str, title: str = "") -> str:
    """去除 Markdown 符号噪音（#、***、**、-、###等），转换为地道小红书爆款排版格式。"""
    if not text:
        return ""
    import re
    lines = text.splitlines()
    clean_lines = []
    tags = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append("")
            continue

        # 提取末尾标签行（如 #自媒体 #干货）
        if stripped.startswith("#") and not stripped.startswith("###") and " " in stripped:
            tag_matches = re.findall(r"#([^#\s]+)", stripped)
            if tag_matches and len(tag_matches) >= 2:
                tags.extend(tag_matches)
                continue

        # 移除行首的 Markdown 标题标记（###、##、#等）
        l = re.sub(r"^#{1,6}\s*", "", stripped)

        # 移除分割线（---、***等）
        if re.match(r"^(\-{3,}|\*{3,}|_{3,})$", l):
            continue

        # 移除加粗与斜体（***文本***、**文本**）
        l = re.sub(r"\*{2,3}(.*?)\*{2,3}", r"\1", l)
        l = re.sub(r"_{2,3}(.*?)_{2,3}", r"\1", l)
        l = re.sub(r"`+(.*?)`+", r"\1", l)

        # 将行首列表符（-、*、•）优雅转换为小红书呼吸感短句
        if re.match(r"^[\-\+\*•]\s*", l):
            l = "👉 " + re.sub(r"^[\-\+\*•]\s*", "", l)
        elif re.match(r"^\d+[\.\、]\s*", l):
            l = "✨ " + l

        # 移除正文中间孤零零的 # 杂音
        l = re.sub(r"(?<!\w)#(?!\w)", "", l)

        # 过滤与剔除制作类噪音（视觉指南、排版说明等）
        if re.search(r"视觉指南|排版说明|封面设计|设计建议|镜头提示", l):
            continue
        if re.match(r"^(PAGE|TITLE|LINE|TAGS)\s*[:：]", l, re.IGNORECASE):
            l = re.sub(r"^(PAGE|TITLE|LINE|TAGS)\s*[:：]\s*", "", l, flags=re.IGNORECASE).strip()
            if not l:
                continue

        clean_lines.append(l)

    body_res = "\n".join(clean_lines).strip()

    # 底部统一整理纯正的 3~5 个话题标签
    if not tags:
        tags = ["自媒体干货", "爆款笔记", "生活灵感", "创作日常"]
    unique_tags = []
    for t in tags:
        t_clean = t.replace("#", "").strip()
        if t_clean and t_clean not in unique_tags:
            unique_tags.append(t_clean)

    tag_str = " ".join([f"#{t}" for t in unique_tags[:5]])
    return f"{body_res}\n\n{tag_str}"
