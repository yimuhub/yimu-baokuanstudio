"""SQLite 存储层：选题 / 草稿 / 发布任务。"""
import json
import sqlite3
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DB_PATH = DATA / "mediaflow.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
  id TEXT PRIMARY KEY,
  created_at REAL,
  source TEXT,
  title TEXT,
  reason TEXT,
  matched INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending'   -- pending / approved / rejected / drafted
);
CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY,
  topic_id TEXT,
  created_at REAL,
  title TEXT,
  body_md TEXT,
  platforms TEXT,                  -- json: ["wechat_mp","xhs","toutiao"]
  status TEXT DEFAULT 'preview',   -- preview / approved / published / failed
  source_platform TEXT DEFAULT '',
  source_url TEXT DEFAULT '',
  source_title TEXT DEFAULT '',
  analysis TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS draft_history (
  id TEXT PRIMARY KEY,
  draft_id TEXT,
  created_at REAL,
  title TEXT,
  body_md TEXT,
  score REAL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  draft_id TEXT,
  platform TEXT,
  status TEXT DEFAULT 'queued',    -- queued / running / done / failed
  detail TEXT,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS async_tasks (
  id TEXT PRIMARY KEY,
  task_type TEXT,
  target_id TEXT,
  name TEXT,
  status TEXT DEFAULT 'queued',    -- queued / running / paused / completed / failed / cancelled / interrupted
  progress INTEGER DEFAULT 0,
  message TEXT DEFAULT '',
  current_step INTEGER DEFAULT 0,
  total_steps INTEGER DEFAULT 0,
  params_json TEXT DEFAULT '{}',
  result_json TEXT DEFAULT '{}',
  error TEXT DEFAULT '',
  created_at REAL,
  started_at REAL,
  updated_at REAL,
  completed_at REAL
);
CREATE TABLE IF NOT EXISTS ip_characters (
  id TEXT PRIMARY KEY,
  name TEXT,
  gender TEXT,
  age_group TEXT,
  style TEXT,
  avatar_url TEXT DEFAULT '',
  turnaround_sheet_url TEXT DEFAULT '',
  features_en TEXT DEFAULT '',
  dialogue_tone TEXT DEFAULT '',
  created_at REAL,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS scheduled_posts (
  id TEXT PRIMARY KEY,
  draft_id TEXT,
  platform TEXT,
  target_time REAL,
  status TEXT DEFAULT 'pending',   -- pending / running / published / failed / cancelled
  detail TEXT DEFAULT '',
  created_at REAL,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT,
  desc TEXT DEFAULT '',
  config_json TEXT DEFAULT '{}',
  created_at REAL,
  is_active INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  email TEXT DEFAULT '',
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  role TEXT DEFAULT 'user',        -- user / admin
  plan TEXT DEFAULT 'free',        -- free / pro / enterprise
  quota_used INTEGER DEFAULT 0,
  quota_max INTEGER DEFAULT 500000,
  created_at REAL,
  last_login REAL,
  is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS user_api_keys (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  provider TEXT NOT NULL,          -- deepseek / openai / claude / gemini / custom
  api_key TEXT NOT NULL,           -- encrypted
  base_url TEXT DEFAULT '',
  model_id TEXT DEFAULT '',
  is_active INTEGER DEFAULT 1,
  label TEXT DEFAULT '',
  created_at REAL
);
-- V7 新增表（列定义与 studio/db_models.py 对齐，raw sqlite3 与 SQLAlchemy 双层共用） --
CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free',            -- free / pro / studio
  launch_mode TEXT NOT NULL DEFAULT 'invite-only',  -- invite-only / public
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  user_id TEXT NOT NULL UNIQUE,
  tier TEXT NOT NULL DEFAULT 'free',             -- free / pro / studio
  credits_total INTEGER NOT NULL DEFAULT 0,
  credits_used INTEGER NOT NULL DEFAULT 0,
  period_start TEXT NOT NULL,
  period_end TEXT,
  status TEXT NOT NULL DEFAULT 'active',        -- active / expired / cancelled
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gateway_keys (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  user_id TEXT NOT NULL,
  key_prefix TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,                -- 只存哈希，永不返回前端
  name TEXT NOT NULL DEFAULT '',
  quota_credits INTEGER NOT NULL DEFAULT 0,
  rate_limit_rpm INTEGER NOT NULL DEFAULT 60,
  rate_limit_tpm INTEGER NOT NULL DEFAULT 100000,
  allowed_models TEXT,                          -- JSON 数组，NULL=不限制
  ip_allowlist TEXT,                            -- JSON 数组，NULL=不限制
  status TEXT NOT NULL DEFAULT 'active',        -- active / revoked / expired
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  key_id TEXT,
  model TEXT NOT NULL,
  direction TEXT NOT NULL,                      -- input / output
  tokens INTEGER NOT NULL DEFAULT 0,
  cost_cents INTEGER NOT NULL DEFAULT 0,        -- 整数分，杜绝浮点
  latency_ms INTEGER NOT NULL DEFAULT 0,
  cached INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  code TEXT NOT NULL UNIQUE,
  max_uses INTEGER NOT NULL DEFAULT 1,
  used_count INTEGER NOT NULL DEFAULT 0,
  credits_grant INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'active',        -- active / exhausted / revoked / expired
  created_at TEXT NOT NULL
);
"""


def conn() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    # 旧库迁移：补列
    cols = {r["name"] for r in c.execute("PRAGMA table_info(drafts)")}
    for col in ("source_platform", "source_url", "source_title", "analysis",
                "score", "score_detail", "score_round", "candidate_titles", "source_stats", "workspace_id", "user_id"):
        if col not in cols:
            t = {"score": "REAL", "score_detail": "TEXT", "score_round": "INTEGER DEFAULT 0"}.get(col, "TEXT DEFAULT ''")
            c.execute(f"ALTER TABLE drafts ADD COLUMN {col} {t}")
    # 旧库迁移：topics 新字段
    tcols = {r["name"] for r in c.execute("PRAGMA table_info(topics)")}
    if "content" not in tcols:
        c.execute("ALTER TABLE topics ADD COLUMN content TEXT DEFAULT ''")
    if "content_fetched" not in tcols:
        c.execute("ALTER TABLE topics ADD COLUMN content_fetched INTEGER DEFAULT 0")
    if "freshness_score" not in tcols:
        c.execute("ALTER TABLE topics ADD COLUMN freshness_score REAL DEFAULT 0")
    if "user_id" not in tcols:
        c.execute("ALTER TABLE topics ADD COLUMN user_id TEXT DEFAULT ''")
    
    # 确保默认管理员存在
    wcols = {r["name"] for r in c.execute("PRAGMA table_info(workspaces)")}
    if "user_id" not in wcols:
        c.execute("ALTER TABLE workspaces ADD COLUMN user_id TEXT DEFAULT ''")

    # V7 租户隔离：给业务表补 tenant_id 列，老数据统一归 'default' 租户。
    # ⭐ 新写入必须带当前租户 id；跨租户访问由应用层拦截。
    for _t in ("topics", "drafts", "draft_history", "jobs", "async_tasks",
               "ip_characters", "scheduled_posts", "workspaces",
               "users", "user_api_keys"):
        try:
            _cols = {r["name"] for r in c.execute(f"PRAGMA table_info({_t})")}
        except Exception:
            continue
        if "tenant_id" not in _cols:
            c.execute(f"ALTER TABLE {_t} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
    # 确保默认租户行存在
    c.execute(
        "INSERT OR IGNORE INTO tenants (id, name, plan, launch_mode, is_active, created_at) "
        "VALUES ('default', 'default', 'free', 'invite-only', 1, datetime('now'))"
    )

    c.commit()
    return c


def now() -> float:
    return time.time()


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------- topics ----------

def add_topic(source: str, title: str, reason: str = "", matched: bool = False,
              content: str = "", content_fetched: int = 0, freshness_score: float = 0.0) -> dict:
    c = conn()
    t = {"id": uid("tp"), "created_at": now(), "source": source, "title": title,
         "reason": reason, "matched": int(matched), "status": "pending",
         "content": content, "content_fetched": int(content_fetched), "freshness_score": float(freshness_score)}
    c.execute("INSERT INTO topics (id, created_at, source, title, reason, matched, status, content, content_fetched, freshness_score) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)",
              (t["id"], t["created_at"], t["source"], t["title"], t["reason"],
               t["matched"], t["status"], t["content"], t["content_fetched"], t["freshness_score"]))
    c.commit()
    c.close()
    return t


def list_topics(status: str | None = None) -> list[dict]:
    c = conn()
    if status:
        rows = c.execute("SELECT * FROM topics WHERE status=? ORDER BY created_at DESC",
                         (status,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM topics ORDER BY created_at DESC LIMIT 200").fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_topic(topic_id: str) -> dict | None:
    c = conn()
    r = c.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def set_topic_status(topic_id: str, status: str) -> None:
    c = conn()
    c.execute("UPDATE topics SET status=? WHERE id=?", (status, topic_id))
    c.commit()
    c.close()


def save_topic_content(topic_id: str, content: str) -> None:
    """保存热榜条目抓取到的文章内容。"""
    c = conn()
    c.execute("UPDATE topics SET content=?, content_fetched=1 WHERE id=?", (content, topic_id))
    c.commit()
    c.close()


def delete_old_topics(days: int) -> int:
    """删除 days 天前的热榜条目，返回删除数量。"""
    cutoff = time.time() - days * 86400
    c = conn()
    r = c.execute("DELETE FROM topics WHERE created_at < ?", (cutoff,))
    cnt = r.rowcount
    c.commit()
    c.close()
    return cnt


def delete_old_drafts(days: int) -> list[str]:
    """删除 days 天前的过期草稿，并清理其关联的任务和文件目录。返回删除的草稿ID列表。"""
    if days <= 0:
        return []
    cutoff = time.time() - days * 86400
    c = conn()
    rows = c.execute("SELECT id FROM drafts WHERE created_at < ?", (cutoff,)).fetchall()
    ids = [r["id"] for r in rows]
    if not ids:
        c.close()
        return []
    for did in ids:
        c.execute("DELETE FROM drafts WHERE id=?", (did,))
        c.execute("DELETE FROM jobs WHERE draft_id=?", (did,))
    c.commit()
    c.close()

    import shutil
    trash = Path.home() / ".Trash"
    for did in ids:
        ddir = DATA / "drafts" / did
        if ddir.exists():
            try:
                trash.mkdir(exist_ok=True)
                shutil.move(str(ddir), str(trash / did))
            except Exception:
                pass
    return ids


def clear_all_topics() -> int:
    """立刻清空全部热榜库，返回删除数量。"""
    c = conn()
    r = c.execute("DELETE FROM topics")
    cnt = r.rowcount
    c.commit()
    c.close()
    return cnt


def count_topics() -> dict:
    """统计热榜库概况。"""
    c = conn()
    total = c.execute("SELECT COUNT(*) as n FROM topics").fetchone()["n"]
    matched = c.execute("SELECT COUNT(*) as n FROM topics WHERE matched=1").fetchone()["n"]
    oldest = c.execute("SELECT MIN(created_at) as t FROM topics").fetchone()["t"]
    c.close()
    return {"total": total, "matched": matched,
            "oldest_ts": oldest,
            "oldest_days": round((time.time() - oldest) / 86400, 1) if oldest else 0}


def draft_dir(draft_id: str) -> Path:
    d = DATA / "drafts" / draft_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_draft(topic_id: str, title: str, body_md: str, platforms: list[str], *,
              source_platform: str = "", source_url: str = "",
              source_title: str = "", analysis: str = "",
              candidate_titles: list[dict] | None = None,
              source_stats: dict | None = None,
              workspace_id: str = "") -> dict:
    c = conn()
    cand_json = json.dumps(candidate_titles or [], ensure_ascii=False)
    stats_json = json.dumps(source_stats or {}, ensure_ascii=False)
    d = {"id": uid("dr"), "topic_id": topic_id, "created_at": now(), "title": title,
         "body_md": body_md, "platforms": json.dumps(platforms), "status": "preview",
         "source_platform": source_platform, "source_url": source_url,
         "source_title": source_title, "analysis": analysis,
         "candidate_titles": cand_json, "source_stats": stats_json,
         "workspace_id": workspace_id}
    c.execute("INSERT INTO drafts (id,topic_id,created_at,title,body_md,platforms,status,"
              "source_platform,source_url,source_title,analysis,candidate_titles,source_stats,workspace_id) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              tuple(d[k] for k in ("id", "topic_id", "created_at", "title", "body_md",
                                   "platforms", "status", "source_platform",
                                   "source_url", "source_title", "analysis",
                                   "candidate_titles", "source_stats", "workspace_id")))
    c.commit()
    c.close()
    return d


def create_custom_draft(title: str, body_md: str = "", workspace_id: str = "", platforms: list[str] | None = None) -> dict:
    """创作者在内容工作台手动新建草稿或导入外部草稿。"""
    if platforms is None:
        platforms = ["wechat_mp", "xhs", "toutiao", "zhihu", "weibo"]
    clean_title = (title or "").strip()
    if not clean_title:
        lines = [l.strip().lstrip("#").strip() for l in (body_md or "").splitlines() if l.strip()]
        clean_title = lines[0][:40] if lines else "未命名草稿"
    return add_draft(
        topic_id="",
        title=clean_title,
        body_md=body_md or "",
        platforms=platforms,
        source_platform="manual_import",
        source_title=clean_title,
        workspace_id=workspace_id or ""
    )


def get_draft(draft_id: str) -> dict | None:
    c = conn()
    r = c.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    c.close()
    if not r:
        return None
    d = dict(r)
    try:
        d["platforms"] = json.loads(d["platforms"]) if d.get("platforms") else []
    except Exception:
        d["platforms"] = []
    try:
        d["candidate_titles"] = json.loads(d["candidate_titles"]) if d.get("candidate_titles") else []
    except Exception:
        d["candidate_titles"] = []
    try:
        d["source_stats"] = json.loads(d["source_stats"]) if d.get("source_stats") else {}
    except Exception:
        d["source_stats"] = {}
    return d


def list_drafts() -> list[dict]:
    c = conn()
    rows = c.execute("SELECT id,topic_id,created_at,title,body_md,platforms,status,"
                     "source_platform,source_url,source_title,analysis,"
                     "score,score_detail,score_round,candidate_titles,source_stats "
                     "FROM drafts ORDER BY created_at DESC LIMIT 200").fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["platforms"] = json.loads(d["platforms"]) if d.get("platforms") else []
        except Exception:
            d["platforms"] = []
        try:
            d["candidate_titles"] = json.loads(d["candidate_titles"]) if d.get("candidate_titles") else []
        except Exception:
            d["candidate_titles"] = []
        try:
            d["source_stats"] = json.loads(d["source_stats"]) if d.get("source_stats") else {}
        except Exception:
            d["source_stats"] = {}
        out.append(d)
    return out


def update_draft_title(draft_id: str, new_title: str) -> None:
    c = conn()
    c.execute("UPDATE drafts SET title=? WHERE id=?", (new_title, draft_id))
    c.commit()
    c.close()


def update_draft_body(draft_id: str, new_body: str) -> None:
    c = conn()
    c.execute("UPDATE drafts SET body_md=? WHERE id=?", (new_body, draft_id))
    c.commit()
    c.close()


def update_draft_candidate_titles(draft_id: str, candidate_titles: list[dict]) -> None:
    c = conn()
    c.execute("UPDATE drafts SET candidate_titles=? WHERE id=?",
              (json.dumps(candidate_titles, ensure_ascii=False), draft_id))
    c.commit()
    c.close()


def set_draft_status(draft_id: str, status: str) -> None:
    c = conn()
    c.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
    c.commit()
    c.close()


# ---------- 版本历史 ----------

def add_history(draft_id: str, title: str, body_md: str, score) -> str:
    c = conn()
    hid = uid("hs")
    c.execute("INSERT INTO draft_history (id, draft_id, created_at, title, body_md, score) VALUES (?,?,?,?,?,?)",
              (hid, draft_id, now(), title, body_md, score))
    c.commit(); c.close()
    # 每篇最多保留 10 个历史版本
    c = conn()
    rows = c.execute("SELECT id FROM draft_history WHERE draft_id=? ORDER BY created_at DESC",
                     (draft_id,)).fetchall()
    for old in rows[10:]:
        c.execute("DELETE FROM draft_history WHERE id=?", (old["id"],))
    c.commit(); c.close()
    return hid


def list_history(draft_id: str) -> list[dict]:
    c = conn()
    rows = c.execute("SELECT id,created_at,title,score FROM draft_history WHERE draft_id=? "
                     "ORDER BY created_at DESC", (draft_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_history(hid: str) -> dict | None:
    c = conn()
    r = c.execute("SELECT * FROM draft_history WHERE id=?", (hid,)).fetchone()
    c.close()
    return dict(r) if r else None


# ---------- jobs ----------

def add_job(draft_id: str, platform: str) -> str:
    c = conn()
    jid = uid("jb")
    c.execute("INSERT INTO jobs (id, draft_id, platform, status, detail, updated_at) VALUES (?,?,?,?,?,?)",
              (jid, draft_id, platform, "queued", "", now()))
    c.commit()
    c.close()
    return jid


def set_job(jid: str, status: str, detail: str = "") -> None:
    c = conn()
    c.execute("UPDATE jobs SET status=?, detail=?, updated_at=? WHERE id=?",
              (status, detail, now(), jid))
    c.commit()
    c.close()


def list_jobs() -> list[dict]:
    c = conn()
    rows = c.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT 200").fetchall()
    c.close()
    return [dict(r) for r in rows]


# ---------- async_tasks (持久化任务状态机) ----------

def create_persistent_task(task_id: str, name: str, task_type: str,
                           target_id: str = "", total_steps: int = 1,
                           params: dict | None = None) -> dict:
    c = conn()
    t = {
        "id": task_id,
        "task_type": task_type,
        "target_id": target_id,
        "name": name,
        "status": "queued",
        "progress": 0,
        "message": "任务已提交持久化队列...",
        "current_step": 0,
        "total_steps": total_steps,
        "params_json": json.dumps(params or {}, ensure_ascii=False),
        "result_json": "{}",
        "error": "",
        "created_at": now(),
        "started_at": 0.0,
        "updated_at": now(),
        "completed_at": 0.0
    }
    c.execute(
        "INSERT INTO async_tasks (id, task_type, target_id, name, status, progress, message, "
        "current_step, total_steps, params_json, result_json, error, created_at, started_at, updated_at, completed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (t["id"], t["task_type"], t["target_id"], t["name"], t["status"], t["progress"], t["message"],
         t["current_step"], t["total_steps"], t["params_json"], t["result_json"], t["error"],
         t["created_at"], t["started_at"], t["updated_at"], t["completed_at"])
    )
    c.commit()
    c.close()
    return t


def update_persistent_task(task_id: str, *, status: str | None = None,
                           progress: int | None = None, message: str | None = None,
                           current_step: int | None = None, result: any = None,
                           error: str | None = None) -> None:
    c = conn()
    updates = ["updated_at=?"]
    vals = [now()]
    if status is not None:
        updates.append("status=?")
        vals.append(status)
        if status == "running":
            updates.append("started_at = CASE WHEN started_at = 0.0 THEN ? ELSE started_at END")
            vals.append(now())
        elif status in ("completed", "failed", "cancelled", "interrupted"):
            updates.append("completed_at=?")
            vals.append(now())
    if progress is not None:
        updates.append("progress=?")
        vals.append(max(0, min(100, int(progress))))
    if message is not None:
        updates.append("message=?")
        vals.append(str(message))
    if current_step is not None:
        updates.append("current_step=?")
        vals.append(int(current_step))
    if result is not None:
        updates.append("result_json=?")
        vals.append(json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result)
    if error is not None:
        updates.append("error=?")
        vals.append(str(error))

    vals.append(task_id)
    c.execute(f"UPDATE async_tasks SET {', '.join(updates)} WHERE id=?", tuple(vals))
    c.commit()
    c.close()


def get_persistent_task(task_id: str) -> dict | None:
    c = conn()
    r = c.execute("SELECT * FROM async_tasks WHERE id=?", (task_id,)).fetchone()
    c.close()
    if not r:
        return None
    d = dict(r)
    try:
        d["params"] = json.loads(d.get("params_json") or "{}")
    except Exception:
        d["params"] = {}
    try:
        d["result"] = json.loads(d.get("result_json") or "{}")
    except Exception:
        d["result"] = d.get("result_json")
    return d


def list_persistent_tasks(limit: int = 50, task_type: str | None = None, status: str | None = None) -> list[dict]:
    c = conn()
    query = "SELECT * FROM async_tasks"
    conds = []
    vals = []
    if task_type:
        conds.append("task_type=?")
        vals.append(task_type)
    if status:
        conds.append("status=?")
        vals.append(status)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY created_at DESC LIMIT ?"
    vals.append(limit)
    rows = c.execute(query, tuple(vals)).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d.get("params_json") or "{}")
        except Exception:
            d["params"] = {}
        try:
            d["result"] = json.loads(d.get("result_json") or "{}")
        except Exception:
            d["result"] = d.get("result_json")
        out.append(d)
    return out


def recover_interrupted_tasks() -> int:
    """启动时检测异常终止任务并标记为 interrupted，支持断点续跑。"""
    c = conn()
    r = c.execute("UPDATE async_tasks SET status='interrupted', message='服务重启，任务意外中断，可点击恢复' "
                  "WHERE status IN ('running', 'queued')")
    count = r.rowcount
    c.commit()
    c.close()
    return count


# ---------- ip_characters (全局 IP 角色资产库) ----------

def save_ip_character(name: str, gender: str = "", age_group: str = "",
                      style: str = "", avatar_url: str = "", turnaround_sheet_url: str = "",
                      features_en: str = "", dialogue_tone: str = "", cid: str | None = None) -> dict:
    c = conn()
    cid = cid or uid("ipc")
    now_ts = now()
    c.execute(
        "INSERT OR REPLACE INTO ip_characters (id, name, gender, age_group, style, "
        "avatar_url, turnaround_sheet_url, features_en, dialogue_tone, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,COALESCE((SELECT created_at FROM ip_characters WHERE id=?), ?), ?)",
        (cid, name, gender, age_group, style, avatar_url, turnaround_sheet_url,
         features_en, dialogue_tone, cid, now_ts, now_ts)
    )
    c.commit()
    c.close()
    return {
        "id": cid, "name": name, "gender": gender, "age_group": age_group,
        "style": style, "avatar_url": avatar_url, "turnaround_sheet_url": turnaround_sheet_url,
        "features_en": features_en, "dialogue_tone": dialogue_tone
    }


def list_ip_characters() -> list[dict]:
    c = conn()
    rows = c.execute("SELECT * FROM ip_characters ORDER BY updated_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_ip_character(cid: str) -> dict | None:
    c = conn()
    r = c.execute("SELECT * FROM ip_characters WHERE id=?", (cid,)).fetchone()
    c.close()
    return dict(r) if r else None


def delete_ip_character(cid: str) -> bool:
    c = conn()
    c.execute("DELETE FROM ip_characters WHERE id=?", (cid,))
    c.commit()
    c.close()
    return True


# ---------- scheduled_posts (排期发布日历) ----------

def add_scheduled_post(draft_id: str, platform: str, target_time: float) -> str:
    c = conn()
    pid = uid("sch")
    now_ts = now()
    c.execute(
        "INSERT INTO scheduled_posts (id, draft_id, platform, target_time, status, detail, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (pid, draft_id, platform, target_time, "pending", "", now_ts, now_ts)
    )
    c.commit()
    c.close()
    return pid


def list_scheduled_posts(status: str | None = None) -> list[dict]:
    c = conn()
    if status:
        rows = c.execute(
            "SELECT s.*, d.title as draft_title FROM scheduled_posts s "
            "LEFT JOIN drafts d ON s.draft_id = d.id "
            "WHERE s.status=? ORDER BY s.target_time ASC", (status,)).fetchall()
    else:
        rows = c.execute(
            "SELECT s.*, d.title as draft_title FROM scheduled_posts s "
            "LEFT JOIN drafts d ON s.draft_id = d.id "
            "ORDER BY s.target_time ASC LIMIT 200").fetchall()
    c.close()
    return [dict(r) for r in rows]


def update_scheduled_post_status(pid: str, status: str, detail: str = "") -> None:
    c = conn()
    c.execute("UPDATE scheduled_posts SET status=?, detail=?, updated_at=? WHERE id=?",
              (status, detail, now(), pid))
    c.commit()
    c.close()


def delete_scheduled_post(pid: str) -> bool:
    c = conn()
    c.execute("DELETE FROM scheduled_posts WHERE id=?", (pid,))
    c.commit()
    c.close()
    return True


# ---------- workspaces (品牌工作区) ----------

def init_workspaces() -> None:
    c = conn()
    cnt = c.execute("SELECT COUNT(*) as c FROM workspaces").fetchone()["c"]
    if cnt == 0:
        wid = "ws-default"
        c.execute("INSERT INTO workspaces (id, name, desc, config_json, created_at, is_active) "
                  "VALUES (?,?,?,?,?,?)",
                  (wid, "默认创作者工作室", "通用自媒体多形态生产", "{}", now(), 1))
        c.commit()
    c.close()


def _format_workspace_row(r) -> dict | None:
    if not r:
        return None
    d = dict(r)
    try:
        d["config"] = json.loads(d.get("config_json") or "{}")
    except Exception:
        d["config"] = {}
    return d


def list_workspaces() -> list[dict]:
    init_workspaces()
    c = conn()
    rows = c.execute("SELECT * FROM workspaces ORDER BY created_at ASC").fetchall()
    c.close()
    return [_format_workspace_row(r) for r in rows]


def get_active_workspace() -> dict:
    init_workspaces()
    c = conn()
    r = c.execute("SELECT * FROM workspaces WHERE is_active=1 LIMIT 1").fetchone()
    c.close()
    if r:
        return _format_workspace_row(r)
    return {"id": "ws-default", "name": "默认创作者工作室", "desc": "", "is_active": 1, "config": {}}


def set_active_workspace(wid: str) -> None:
    c = conn()
    c.execute("UPDATE workspaces SET is_active=0")
    c.execute("UPDATE workspaces SET is_active=1 WHERE id=?", (wid,))
    c.commit()
    c.close()


def create_workspace(name: str, desc: str = "", config: dict | None = None) -> dict:
    c = conn()
    wid = uid("ws")
    cfg_dict = config or {}
    cfg_json = json.dumps(cfg_dict, ensure_ascii=False)
    c.execute("INSERT INTO workspaces (id, name, desc, config_json, created_at, is_active) "
              "VALUES (?,?,?,?,?,0)", (wid, name, desc, cfg_json, now()))
    c.commit()
    c.close()
    return {"id": wid, "name": name, "desc": desc, "config_json": cfg_json, "config": cfg_dict, "is_active": 0}


def get_workspace(wid: str) -> dict | None:
    init_workspaces()
    c = conn()
    r = c.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()
    c.close()
    return _format_workspace_row(r)


def update_workspace(wid: str, name: str, desc: str = "", config: dict | None = None) -> dict | None:
    ws = get_workspace(wid)
    if not ws:
        return None
    c = conn()
    fields = []
    vals = []
    if name:
        fields.append("name=?")
        vals.append(name.strip())
    if desc is not None:
        fields.append("desc=?")
        vals.append(desc.strip())
    if config is not None:
        try:
            cur_cfg = json.loads(ws.get("config_json") or "{}")
        except Exception:
            cur_cfg = {}
        cur_cfg.update(config)
        fields.append("config_json=?")
        vals.append(json.dumps(cur_cfg, ensure_ascii=False))
    if fields:
        vals.append(wid)
        c.execute(f"UPDATE workspaces SET {', '.join(fields)} WHERE id=?", vals)
        c.commit()
    c.close()
    return get_workspace(wid)


def delete_workspace(wid: str) -> dict:
    if wid == "ws-default":
        raise ValueError("默认创作者工作室为系统基础空间，不可删除")
    ws = get_workspace(wid)
    if not ws:
        raise ValueError(f"工作区不存在: {wid}")
    was_active = bool(ws.get("is_active"))
    c = conn()
    c.execute("DELETE FROM workspaces WHERE id=?", (wid,))
    c.commit()
    c.close()
    if was_active:
        set_active_workspace("ws-default")
    return {"deleted_id": wid, "active": get_active_workspace()}


