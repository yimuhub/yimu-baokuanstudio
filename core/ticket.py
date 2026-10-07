"""每日工单：热榜 → 选3题 → 成稿(评分自迭代+AI排版+配图) → 最优稿出15s片 → 汇总推送。"""
import json
import time
from datetime import datetime
from pathlib import Path

from core.llm import load_env

BASE = Path(__file__).resolve().parent.parent
TICKETS_DIR = BASE / "data" / "tickets"


def _pick_topics(n: int = 3) -> list[dict]:
    """选题策略：命中关键词优先，其次按榜单顺序。"""
    from core import db
    cutoff = time.time() - 48 * 3600
    pending = [t for t in db.list_topics(status="pending")
               if t["created_at"] >= cutoff]
    matched = [t for t in pending if t["matched"]]
    rest = [t for t in pending if not t["matched"]]
    chosen = (matched + rest)[:n]
    for t in chosen:
        db.set_topic_status(t["id"], "approved")
    return chosen


def run_ticket(emit=None, n: int = 3, with_video: bool = True) -> dict:
    emit = emit or (lambda *_: None)
    from core import db, orchestrator
    from core.topics import collect_topics

    started = time.time()
    emit("① 抓取实时热榜…")
    stats = collect_topics()
    chosen = _pick_topics(n)
    if not chosen:
        emit("今日热榜无可选题，工单结束")
        return {"topics": 0, "drafts": [], "error": "无候选选题"}

    drafts = []
    for i, t in enumerate(chosen, 1):
        emit(f"②[{i}/{len(chosen)}] 成稿《{t['title'][:24]}》…（评分自迭代+排版，约3分钟）")
        try:
            res = orchestrator.generate_draft(t["id"])
            sc = res.get("score") or {}
            drafts.append({"topic": t["title"], "draft_id": res["draft"]["id"],
                           "title": res["draft"]["title"],
                           "score": sc.get("total"), "grade": sc.get("grade")})
        except Exception as e:
            drafts.append({"topic": t["title"], "error": str(e)[:120]})

    video_res = None
    done = [d for d in drafts if d.get("draft_id")]
    if with_video and done:
        best = max(done, key=lambda d: (d.get("score") or 0))
        emit(f"③ 给最优稿出 15 秒视频…")
        try:
            from core import video
            video_res = video.make_video(best["draft_id"], 15,
                                         emit=lambda m: emit(f"③ {m}"))
            best["video"] = video_res["url"]
        except Exception as e:
            video_res = {"error": str(e)[:150]}

    # 汇总落盘
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    video_summary = {"tid": video_res["tid"], "url": video_res["url"]} if (video_res and "tid" in video_res) else None
    summary = {"date": date, "started": started, "duration_min": round((time.time() - started) / 60, 1),
               "hot": stats, "drafts": drafts, "video": video_summary}
    (TICKETS_DIR / f"{date}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                              encoding="utf-8")

    # 钉钉推送审核卡片
    emit("④ 推送审核通知…")
    from core import notify
    lines = [f"## 📮 每日工单 {date}", ""]
    for d in drafts:
        if d.get("draft_id"):
            lines.append(f"- **{d['title'][:30]}** · {d.get('score')}分（{d.get('grade')}）")
        else:
            lines.append(f"- ~~{d['topic'][:24]}~~ 生成失败")
    if video_res and video_res.get("tid"):
        lines.append(f"- 🎬 视频已出片：{video_res['tid']}")
    lines.append("\n👉 打开 mediaflow 草稿库审核后发布")
    push = notify.send("每日工单", "\n".join(lines))
    summary["push"] = push
    (TICKETS_DIR / f"{date}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    return summary
