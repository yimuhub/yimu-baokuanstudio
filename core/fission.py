"""全域多端矩阵级裂变引擎：按需并发产出 6 大主流平台版本（公众号、小红书5图全集、今日头条、知乎、微博、Twitter / 𝕏）。"""
import html
import json
import logging
import re
import time
from pathlib import Path

from core import agents, db, llm
from core.render_card import render_draft_cards
from core.themes import DEFAULT_CARD_STYLE, DEFAULT_THEME
from adapters import toutiao, wechat_mp, zhihu, weibo, twitter
from adapters.base import save_preview

logger = logging.getLogger(__name__)

ALL_SUPPORTED_PLATFORMS = ["wechat_mp", "xhs", "toutiao", "zhihu", "weibo", "twitter"]

PLATFORM_PROMPT_PARTS = {
    "xhs": (
        "【小红书版】(双层吸睛标题含爆款Emoji，黄金3秒痛点共鸣Hook，1️⃣2️⃣3️⃣结构化实操干货要点，避坑指南，金句收尾，文末带 5~8 个高频热门#标签#)",
        "===TITLE_XHS===\n<小红书标题，20字内带爆款Emoji>\n===BODY_XHS===\n<小红书正文，短句分点，末尾带 #标签>\n"
    ),
    "toutiao": (
        "【今日头条版】(两句一断黄金短律排版，红标核心速览导读，数字反差吸睛标题，关键信息加粗，文末设置强争议留评互动话题)",
        "===TITLE_TT===\n<今日头条标题，带数字或悬念>\n===BODY_TT===\n<今日头条正文，两句一换行短律，带小节>\n"
    ),
    "zhihu": (
        "【知乎版】(盐选专业答主风格，“谢邀”引言，严密底层商业逻辑推导，实战对比论证与结构化总结)",
        "===TITLE_ZH===\n<知乎问答标题>\n===BODY_ZH===\n<知乎深度回答 markdown>\n"
    ),
    "weibo": (
        "【微博快讯版】(140~260字高浓度情绪导语 + 核心事实 + 话题标签#xxx#，极度适合碎片化社交传播)",
        "===TEXT_WB===\n<微博即刻快讯文本，含 #话题#>\n"
    ),
    "twitter": (
        "【Twitter / 𝕏 连击串推 Thread 版】(百万曝光结构：输出纯净文本推文，严禁使用任何 Markdown 语法如 **加粗、*斜体、###标题；严禁输出任何前言后语或元数据包装；严禁堆砌 # 话题标签，末尾最多保留 1~2 个精准标签；每条推文以 1/N 序号开头，推文间用 --- 分隔，内容直接复制即发)",
        "===TEXT_TWITTER===\n<Twitter 纯净推文串，无任何 ** 或 ###，按 1/N 序号分段，每条推文间用 --- 分隔，末条含 CTA 与 1~2 个 #标签>\n"
    )
}

def _build_derivation_prompt(target_platforms: list[str]) -> tuple[str, bool]:
    """根据选中的平台动态构建 Prompt，如果不需要 LLM 派生则返回需要为 False"""
    req_platforms = [p for p in target_platforms if p in PLATFORM_PROMPT_PARTS]
    if not req_platforms:
        return "", False
        
    instr_list = []
    format_list = []
    for idx, p in enumerate(req_platforms, 1):
        desc, fmt = PLATFORM_PROMPT_PARTS[p]
        instr_list.append(f"{idx}. {desc}")
        format_list.append(fmt)
        
    prompt = (
        "你是一名资深的全域新媒体矩阵内容操盘总监。\n"
        f"请将创作者提供的【母版终稿文章】，一次性派生与重构为以下 {len(req_platforms)} 个矩阵平台的原生专属版本（公众号版已保留母稿全文，无需重写）：\n\n"
        + "\n".join(instr_list) + "\n\n"
        "严格按以下标记格式输出，严禁输出任何多余解释说明：\n"
        + "\n".join(format_list)
    )
    return prompt, True


def _parse_fission_output(raw: str) -> dict:
    sections = {}
    pattern = r"===([A-Z_]+)===\s*\n(.*?)(?====[A-Z_]+===|\Z)"
    matches = re.findall(pattern, raw, re.DOTALL)
    for k, v in matches:
        sections[k.strip()] = v.strip()
    return sections


def switch_theme_pure(
    draft_id: str,
    theme: str,
    title: str | None = None,
    body_md: str | None = None,
    media_name: str | None = None,
) -> dict:
    """零大模型调用、100% 纯规则排版换肤（一字不改、零幻觉、零篡改）。"""
    from core.themes import WECHAT_THEMES, md_to_wechat_html
    from core.layouter import _inject_cover

    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")
    ddir = db.draft_dir(draft_id)

    cur_title = (title if title is not None else d.get("title", "")).strip() or "未命名草稿"
    cur_body = body_md if body_md is not None else d.get("body_md", "")
    theme = theme if theme in WECHAT_THEMES else (d.get("theme") or DEFAULT_THEME)

    # 若前端带上了最新文本，则同步安全持久化
    if title is not None or body_md is not None:
        c = db.conn()
        c.execute("UPDATE drafts SET title=?, body_md=? WHERE id=?", (cur_title, cur_body, draft_id))
        c.commit()
        c.close()
        (ddir / "content.md").write_text(f"# {cur_title}\n\n{cur_body}", encoding="utf-8")

    images = {f.name: f"/img/{draft_id}/{f.name}" for f in sorted((ddir / "img").glob("sec-*.png"))} if (ddir / "img").exists() else {}
    cover = f"/img/{draft_id}/cover.png" if (ddir / "img" / "cover.png").exists() else None
    meta = media_name or "一幕·YIMU 爆款工作室"

    html = md_to_wechat_html(cur_body, cur_title, theme=theme, meta=meta, images=images)
    html = _inject_cover(html, cover)
    save_preview(ddir, "wechat_mp", html)

    return {
        "ok": True,
        "draft_id": draft_id,
        "theme": theme,
        "html": html,
        "title": cur_title,
        "body_md": cur_body,
    }


def derive_all_platforms_from_master(
    draft_id: str,
    master_title: str | None = None,
    master_body_md: str | None = None,
    theme: str | None = None,
    media_name: str | None = None,
    card_style: str = DEFAULT_CARD_STYLE,
    target_platforms: list[str] | None = None,
    emit=None,
) -> dict:
    """母稿驱动·全域多端一键派生与重构引擎。
    
    逻辑原则：
    1. 以当前创作者在左侧确立的母稿为唯一基准（Single Source of Truth）；
    2. 严格按用户勾选的 target_platforms 进行精准按需派生，未勾选的平台跳过，大幅提速降费；
    3. 微信公众号 100% 采用母稿全文与标题（零大模型篡改，纯规则排版）；
    4. Twitter / 𝕏 采用专业 Thread 串推及单推解析。
    """
    emit = emit or (lambda *_: None)
    d = db.get_draft(draft_id)
    if not d:
        raise RuntimeError(f"草稿不存在: {draft_id}")

    ddir = db.draft_dir(draft_id)
    selected_platforms = target_platforms if target_platforms is not None else ALL_SUPPORTED_PLATFORMS

    # 1. 确定并持久化母稿内容
    title = (master_title if master_title is not None else d.get("title", "")).strip() or "未命名草稿"
    body_md = (master_body_md if master_body_md is not None else d.get("body_md", "")).strip()
    theme = theme or d.get("theme") or DEFAULT_THEME
    media_name = media_name or "一幕·YIMU 爆款工作室"

    emit("💾 母稿数据保真持久化…")
    c = db.conn()
    c.execute("UPDATE drafts SET title=?, body_md=? WHERE id=?", (title, body_md, draft_id))
    c.commit()
    c.close()
    (ddir / "content.md").write_text(f"# {title}\n\n{body_md}", encoding="utf-8")

    # 2. 微信公众号（若选中）
    if "wechat_mp" in selected_platforms:
        emit("🟢 渲染微信公众号版本（零篡改纯排版，文字 100% 忠实母稿）…")
        from core.themes import md_to_wechat_html
        from core.layouter import _inject_cover
        images = {f.name: f"/img/{draft_id}/{f.name}" for f in sorted((ddir / "img").glob("sec-*.png"))} if (ddir / "img").exists() else {}
        cover = f"/img/{draft_id}/cover.png" if (ddir / "img" / "cover.png").exists() else None
        wx_html = md_to_wechat_html(body_md, title, theme=theme, meta=media_name, images=images)
        wx_html = _inject_cover(wx_html, cover)
        save_preview(ddir, "wechat_mp", wx_html)

    # 3. 按需大模型并发派生其他各端
    prompt, needs_llm = _build_derivation_prompt(selected_platforms)
    parsed = {}
    if needs_llm:
        plat_names = [p for p in selected_platforms if p != "wechat_mp"]
        emit(f"🤖 智能并行派生已选平台 [{', '.join(plat_names)}]…")
        raw = ""
        try:
            raw = agents.chat_for("write", [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"【母稿标题】\n{title}\n\n【母稿全文】\n{body_md[:2500]}"}
            ], temperature=0.6, timeout_s=25)
        except Exception as e:
            logger.warning(f"全域派生模型请求异常: {e}")

        parsed = _parse_fission_output(raw)

    # 4. 今日头条处理
    tt_title = parsed.get("TITLE_TT")
    tt_body = parsed.get("BODY_TT")
    if "toutiao" in selected_platforms:
        emit("📰 渲染今日头条专属红标短律排版…")
        tt_title = tt_title or f"深度剖析：{title}"
        tt_body = tt_body or (
            "【导读】这是一篇值得深度阅读并收藏的干货解析。\n\n" +
            "\n\n".join(body_md.split("\n\n")[:5]) +
            "\n\n对于这件事情，你怎么看？欢迎在评论区留下你的真知灼见！"
        )
        tt_html = toutiao.render_preview(tt_body, tt_title)
        save_preview(ddir, "toutiao", tt_html)
        (ddir / "toutiao.md").write_text(f"# {tt_title}\n\n{tt_body}", encoding="utf-8")

    # 5. 知乎处理
    zh_title = parsed.get("TITLE_ZH")
    zh_body = parsed.get("BODY_ZH")
    if "zhihu" in selected_platforms:
        emit("🔵 渲染知乎深度专业问答…")
        zh_title = zh_title or f"如何看待「{title[:22]}」？背后的底层逻辑是什么？"
        zh_body = zh_body or (f"谢邀。\n\n关于这个问题，我们需要从底层逻辑进行深度拆解：\n\n{body_md}")
        zh_html = zhihu.render_preview(zh_body, zh_title)
        save_preview(ddir, "zhihu", zh_html)
        (ddir / "zhihu.md").write_text(f"# {zh_title}\n\n{zh_body}", encoding="utf-8")

    # 6. 微博处理
    wb_text = parsed.get("TEXT_WB")
    if "weibo" in selected_platforms:
        emit("🔴 渲染微博即刻快讯…")
        wb_text = wb_text or (
            f"#{title[:12]}#【{title}】\n\n" +
            "\n".join([line for line in body_md.splitlines() if line.strip()][:3])[:160] +
            "\n\n对此你怎么看？转发讨论！"
        )
        wb_html = weibo.render_preview(wb_text, title)
        save_preview(ddir, "weibo", wb_html)
        (ddir / "weibo.md").write_text(wb_text, encoding="utf-8")

    # 7. Twitter / 𝕏 连击串推处理
    tw_text = parsed.get("TEXT_TWITTER")
    if "twitter" in selected_platforms:
        emit("𝕏 渲染 Twitter / 𝕏 爆款 Thread 串推…")
        if not tw_text:
            # 智能兜底 Thread
            paras = [p.strip() for p in body_md.split("\n\n") if p.strip()]
            tot = min(len(paras) + 2, 5)
            tw_lines = [
                f"1/{tot} 🔥 为什么关于「{title}」，大部分人的理解都停留在表面？\n\n核心逻辑拆解 👇",
            ]
            for i, p in enumerate(paras[:tot-2], 2):
                clean_p = re.sub(r'[*#_~`]', '', p).strip()
                tw_lines.append(f"{i}/{tot} 💡 {clean_p[:160]}")
            tw_lines.append(f"{tot}/{tot} 🎯 总结：\n掌握底层逻辑，才能穿透迷雾。\n\n如果你觉得有用，请 🔁 转发支持并关注 @yimu_creator\n\n#认知提升 #方法论")
            tw_text = "\n\n---\n\n".join(tw_lines)

        tw_text = twitter.clean_twitter_text(tw_text)
        tw_html = twitter.render_twitter_html(tw_text, title)
        save_preview(ddir, "twitter", tw_html)
        (ddir / "twitter.md").write_text(tw_text, encoding="utf-8")

    # 8. 小红书多图压制
    made_cards = []
    xhs_title = parsed.get("TITLE_XHS")
    xhs_body = parsed.get("BODY_XHS")
    if "xhs" in selected_platforms:
        emit("📕 压制小红书 5~7 张高清美学卡片全集…")
        xhs_title = xhs_title or f"🔥 {title[:18]}"
        xhs_body = xhs_body or (
            body_md[:550] + "\n\n💡 核心重点：\n1️⃣ 建立底层认知框架\n2️⃣ 抓住核心关键杠杆\n3️⃣ 持续复盘与迭代行动\n\n#干货分享 #自媒体操盘 #认知提升 #爆款方法论"
        )
        (ddir / "xhs.md").write_text(f"# {xhs_title}\n\n{xhs_body}", encoding="utf-8")

        sections = []
        for line in xhs_body.splitlines():
            s = line.strip().lstrip("-• 1234567890.、")
            if not s or s.startswith("#") or s.startswith("🔥") or s.startswith("【"):
                continue
            sections.append((s[:20], [s]))
            if len(sections) >= 6:
                break
        if not sections:
            paras = [p.strip() for p in body_md.split("\n\n") if p.strip()]
            sections = [(f"精选看点 {i+1}", [p[:120]]) for i, p in enumerate(paras[:5])]

        cover_img = ddir / "img" / "cover.png" if (ddir / "img" / "cover.png").exists() else None
        made_cards = render_draft_cards(ddir, xhs_title, sections, style=card_style, cover_img=cover_img)

    # 9. 读取或更新全域矩阵数据
    existing_matrix = {}
    mf = ddir / "matrix.json"
    if mf.exists():
        try:
            existing_matrix = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            pass

    matrix_data = {
        "updated_at": int(time.time()),
        "draft_id": draft_id,
        "selected_platforms": selected_platforms,
        "master": {"title": title, "body": body_md, "theme": theme},
        "wechat_mp": {"title": title, "body": body_md, "preview_url": f"/preview/{draft_id}/wechat_mp"} if "wechat_mp" in selected_platforms else existing_matrix.get("wechat_mp", {}),
        "xhs": {"title": xhs_title, "body": xhs_body, "cards": made_cards, "cards_count": len(made_cards)} if "xhs" in selected_platforms else existing_matrix.get("xhs", {}),
        "toutiao": {"title": tt_title, "body": tt_body, "preview_url": f"/preview/{draft_id}/toutiao"} if "toutiao" in selected_platforms else existing_matrix.get("toutiao", {}),
        "zhihu": {"title": zh_title, "body": zh_body, "preview_url": f"/preview/{draft_id}/zhihu"} if "zhihu" in selected_platforms else existing_matrix.get("zhihu", {}),
        "weibo": {"text": wb_text, "preview_url": f"/preview/{draft_id}/weibo"} if "weibo" in selected_platforms else existing_matrix.get("weibo", {}),
        "twitter": {"text": tw_text, "preview_url": f"/preview/{draft_id}/twitter"} if "twitter" in selected_platforms else existing_matrix.get("twitter", {}),
    }
    (ddir / "matrix.json").write_text(json.dumps(matrix_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 10. 更新数据库中的平台列表
    c = db.conn()
    c.execute(
        "UPDATE drafts SET platforms=? WHERE id=?",
        (json.dumps(selected_platforms, ensure_ascii=False), draft_id),
    )
    c.commit()
    c.close()

    emit(f"🎉 所选矩阵平台 [{len(selected_platforms)} 端] 已同步派生完成！")
    return {
        "ok": True,
        "draft_id": draft_id,
        "selected_platforms": selected_platforms,
        "matrix": matrix_data,
        "cards_count": len(made_cards),
    }


def generate_omnichannel_matrix(draft_id: str, emit=None) -> dict:
    """向后兼容的全域裂变入口，直接复用母稿驱动派生引擎。"""
    return derive_all_platforms_from_master(draft_id, emit=emit)


def get_draft_matrix(draft_id: str) -> dict:
    """读取草稿的全矩阵六端数据。"""
    ddir = db.draft_dir(draft_id)
    mf = ddir / "matrix.json"
    if mf.exists():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            pass

    d = db.get_draft(draft_id)
    if not d:
        return {}
    title = d.get("title", "")
    body = d.get("body_md", "")

    xhs_file = ddir / "xhs.md"
    xhs_text = xhs_file.read_text(encoding="utf-8") if xhs_file.exists() else body[:600]

    tt_file = ddir / "toutiao.md"
    tt_text = tt_file.read_text(encoding="utf-8") if tt_file.exists() else body

    zh_file = ddir / "zhihu.md"
    zh_text = zh_file.read_text(encoding="utf-8") if zh_file.exists() else body

    wb_file = ddir / "weibo.md"
    wb_text = wb_file.read_text(encoding="utf-8") if wb_file.exists() else body[:240]

    tw_file = ddir / "twitter.md"
    tw_text = tw_file.read_text(encoding="utf-8") if tw_file.exists() else ""

    cards = sorted([p.name for p in ddir.glob("card-*.png")])

    return {
        "updated_at": int(time.time()),
        "draft_id": draft_id,
        "master": {"title": title, "body": body, "theme": d.get("theme", DEFAULT_THEME)},
        "wechat_mp": {"title": title, "body": body, "preview_url": f"/preview/{draft_id}/wechat_mp"},
        "xhs": {"title": title, "body": xhs_text, "cards": cards, "cards_count": len(cards)},
        "toutiao": {"title": title, "body": tt_text, "preview_url": f"/preview/{draft_id}/toutiao"},
        "zhihu": {"title": f"如何看待「{title[:22]}」？", "body": zh_text, "preview_url": f"/preview/{draft_id}/zhihu"},
        "weibo": {"text": wb_text, "preview_url": f"/preview/{draft_id}/weibo"},
        "twitter": {"text": tw_text, "preview_url": f"/preview/{draft_id}/twitter"},
    }
