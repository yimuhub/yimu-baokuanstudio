# SPDX-License-Identifier: BUSL-1.1
"""SQLite 存储层：选题 / 草稿 / 发布任务。"""
import json
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

# R2-1：额度数字的唯一真源（core.auth 也从这里取，避免两处硬编码）
from studio.pricing import TIER_CREDITS

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
  status TEXT DEFAULT 'pending'   -- pending / approved / rejected / drafted / blocked
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
  quota_max INTEGER DEFAULT 3000,       -- R2-1：免费档额度，取自 studio/pricing.TIER_CREDITS
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
  inviter_id TEXT NOT NULL DEFAULT '',          -- R5-4：邀请人 user_id（空=运营发放）
  created_at TEXT NOT NULL
);

-- R5-6 用户行为事件表（漏斗埋点的唯一真源） --
-- ⭐ 为什么必须有：此前全仓零埋点，注册→首稿→首剧→撞墙→充值这条链
--   没有任何数据，运营判断全靠猜。这里记录 5 个关键事件，
--   /api/admin/metrics 按 event 聚合即得漏斗转化率。
CREATE TABLE IF NOT EXISTS user_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  user_id TEXT NOT NULL DEFAULT '',
  event TEXT NOT NULL,                          -- signup / first_draft_created / ...
  props TEXT NOT NULL DEFAULT '{}',             -- JSON 附加属性
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_events_event ON user_events(event, created_at);
CREATE INDEX IF NOT EXISTS idx_user_events_user ON user_events(user_id, event);

-- R5-3 通知外发记录（用户侧通道的投递台账 + 召回节流依据） --
CREATE TABLE IF NOT EXISTS user_notifications (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  user_id TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT 'email',
  recipient TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',       -- pending / sent / skipped / failed
  error TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  sent_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_user_notif_user ON user_notifications(user_id, created_at);

-- R5-4 邀请关系（谁邀请了谁，用于裂变 ROI 追踪） --
CREATE TABLE IF NOT EXISTS invite_referrals (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  inviter_id TEXT NOT NULL,
  invitee_id TEXT NOT NULL,
  invite_code TEXT NOT NULL DEFAULT '',
  reward_credits INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_invite_referrals_inviter ON invite_referrals(inviter_id);

-- R5-7 自动发布频控与账号健康 --
-- 一次 matrix 裂变 + 定时任务 = 一个账号一天发 6 条不同平台内容，
-- 正是平台风控模型的典型特征。这里记录每一次真实发布尝试，
-- 既做频控计数，也做账号健康度留痕。
CREATE TABLE IF NOT EXISTS publish_attempts (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  user_id TEXT NOT NULL DEFAULT '',
  draft_id TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT 'xhs',
  status TEXT NOT NULL DEFAULT 'success',       -- success / failed / blocked
  detail TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publish_attempts_acc ON publish_attempts(platform, created_at);

-- R5-7 账号健康状态（连续失败会被风控，冷却期内禁止自动发布） --
CREATE TABLE IF NOT EXISTS account_health (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  account_key TEXT NOT NULL,                    -- 账号标识（默认 'default'）
  platform TEXT NOT NULL DEFAULT 'xhs',
  status TEXT NOT NULL DEFAULT 'healthy',       -- healthy / degraded / cooldown
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_success_at REAL NOT NULL DEFAULT 0,
  last_failure_at REAL NOT NULL DEFAULT 0,
  cooldown_until REAL NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_account_health_key
  ON account_health(account_key, platform);

-- R5-5 分享链接：不可猜测令牌 → 稿件产物的映射。
-- ⭐ 访问地址里**不含 did**，只有 192 位熵的随机令牌，
--   因此「改别人的 did 拿别人的稿件」这条路在数据层就不存在。
CREATE TABLE IF NOT EXISTS share_links (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  owner_user_id TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL DEFAULT 0,
  revoked_at REAL NOT NULL DEFAULT 0,
  hits INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_share_links_draft ON share_links(draft_id);
"""


#: core.auth 侧需要的 users 列（studio.db_models.User 里没有的那几个）。
#: 两套 schema 共用同一张 users 表，谁先建表就会缺对方的列（见ensure_users_columns）。
_CORE_USER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("plan", "TEXT DEFAULT 'free'"),
    ("quota_used", "INTEGER DEFAULT 0"),
    # R2-1：额度默认取定价真源（禁止在此硬编码额度数字）
    ("quota_max", f"INTEGER DEFAULT {TIER_CREDITS['free']}"),
    ("last_login", "REAL"),
)


def ensure_users_columns(c: sqlite3.Connection) -> None:
    """幂等补齐 ``users`` 表中 core.auth 需要的列（R3-9）。

    ⚠️ 为什么必须有这一步：``core.db`` 与 ``studio.db_models`` 把 ``users``
       当作**同一张物理表**，但列集不同。SQLite 的
       ``CREATE TABLE IF NOT EXISTS`` 不会给已存在的表补列，
       因此**谁先建表决定了另一方会不会缺列**。
       实测：新装机器若 studio先 init_db，``core.auth.get_user_by_id``
       会抛 ``no such column: plan``，表现为**所有接口 500**。

    在 :func:`conn` 与 :func:`core.auth._db` 两条建连路径上都调用，
    保证无论哪一侧先建表都能自愈。
    """
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    except Exception:
        return
    if not cols:
        return  # 表还不存在（首次建库），交给 SCHEMA / create_all 处理
    for col, ddl in _CORE_USER_COLUMNS:
        if col not in cols:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            except Exception:
                pass  # 并发下可能已被另一方补上，忽略（幂等）
    try:
        c.commit()
    except Exception:
        pass


def _recover_corrupt_database(path: Path, err_msg: str) -> None:
    """自动清理并修复损坏的 SQLite 数据库文件及 WAL 临时日志。"""
    ts = int(time.time())
    bak_path = path.with_name(f"{path.stem}.corrupt.{ts}.db")
    try:
        if path.exists():
            shutil.move(str(path), str(bak_path))
            print(f"⚠️ [SQLite自愈] 检测到数据库损坏 ({err_msg})，已将坏库备份至 {bak_path.name}")
    except Exception as move_err:
        print(f"⚠️ [SQLite自愈] 备份坏库文件失败: {move_err}")
    # 彻底移除残留的 WAL 和共享内存锁文件
    for ext in ("-wal", "-shm", "-journal"):
        side_file = Path(str(path) + ext)
        if side_file.exists():
            try:
                side_file.unlink(missing_ok=True)
            except Exception:
                pass


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    """创建健壮的 SQLite 连接（超时 30 秒、WAL 模式、忙时等待重试、支持 malformed 自愈）。"""
    try:
        c = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")
        c.execute("PRAGMA busy_timeout=30000;")
        # 完整性校验抽检
        c.execute("SELECT 1 FROM sqlite_master LIMIT 1;").fetchone()
        return c
    except sqlite3.DatabaseError as e:
        err_str = str(e).lower()
        if any(keyword in err_str for keyword in ("malformed", "disk image", "not a database", "corrupt")):
            _recover_corrupt_database(path, str(e))
            # 重新建立全新的健康连接
            c = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute("PRAGMA synchronous=NORMAL;")
            c.execute("PRAGMA busy_timeout=30000;")
            return c
        raise


def conn() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = _connect_sqlite(DB_PATH)
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
    if "blocked_reason" not in tcols:
        c.execute("ALTER TABLE topics ADD COLUMN blocked_reason TEXT DEFAULT ''")

    # R4 合规：草稿待人工复核标记（不删草稿，只标记）
    _dcols = {r["name"] for r in c.execute("PRAGMA table_info(drafts)")}
    if "needs_review" not in _dcols:
        c.execute("ALTER TABLE drafts ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0")
    if "guard_reason" not in _dcols:
        c.execute("ALTER TABLE drafts ADD COLUMN guard_reason TEXT DEFAULT ''")
    
    # 确保默认管理员存在
    wcols = {r["name"] for r in c.execute("PRAGMA table_info(workspaces)")}
    if "user_id" not in wcols:
        c.execute("ALTER TABLE workspaces ADD COLUMN user_id TEXT DEFAULT ''")

    # R5-4 裂变：invites 补 inviter_id（记录邀请人，空串=运营发放的老邀请码）
    _icols = {r["name"] for r in c.execute("PRAGMA table_info(invites)")}
    if "inviter_id" not in _icols:
        c.execute("ALTER TABLE invites ADD COLUMN inviter_id TEXT NOT NULL DEFAULT ''")

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
    # ⭐ R3-9：补齐 core.auth 需要的 users 列（与 studio 共用同一张表，
    #   谁先建表另一方就会缺列——详见 ensure_users_columns 的说明）。
    ensure_users_columns(c)

    # 确保默认租户行存在
    c.execute(
        "INSERT OR IGNORE INTO tenants (id, name, plan, launch_mode, is_active, created_at) "
        "VALUES ('default', 'default', 'free', 'invite-only', 1, datetime('now'))"
    )

    # R3-9：把历史草稿（user_id 为空串）的归属一次性回填给本机管理员。
    # 幂等（只填空串），故每次建连执行成本可忽略；放在迁移之后是因为
    # 上面的 ALTER TABLE ADD COLUMN user_id 保证了该列一定存在。
    # ⚠️ 直接写 SQL（而非调 backfill_drafts_owner）是为了避免 conn() 与
    #    业务函数互相递归调用。
    c.execute(
        "UPDATE drafts SET user_id='u-admin' WHERE user_id IS NULL OR TRIM(user_id)=''"
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


def block_topic(topic_id: str, reason: str = "") -> None:
    """把选题标记为 blocked（**不删除**，保留痕迹便于复核与申诉）。

    R4-3：敏感选题入池前拦截 + 已入库敏感选题的一次性清理都走这里。
    """
    c = conn()
    c.execute("UPDATE topics SET status='blocked', blocked_reason=? WHERE id=?",
              (reason[:500], topic_id))
    c.commit()
    c.close()


def list_blocked_topics() -> list[dict]:
    """列出被内容安全闸拦下的选题。"""
    c = conn()
    rows = c.execute(
        "SELECT * FROM topics WHERE status='blocked' ORDER BY created_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def sweep_blocked_topics(apply: bool = False) -> dict:
    """扫描选题池，把命中内容安全闸的条目标记为 blocked。

    参数
    ----
    apply: False = 预演（只统计不落库），True = 真正标记。

    返回 ``{"total": 扫描数, "would_block": 命中数, "blocked": 实际标记数,
    "items": [{id,title,reason}]}``。
    """
    from core import content_guard

    c = conn()
    rows = c.execute(
        "SELECT id, title FROM topics WHERE status IN ('pending','approved')").fetchall()
    c.close()
    items = []
    for r in rows:
        res = content_guard.check_topic_title(r["title"])
        if res.blocked:
            items.append({"id": r["id"], "title": r["title"], "reason": res.reason()})
    blocked = 0
    if apply:
        for it in items:
            block_topic(it["id"], it["reason"])
            blocked += 1
    return {"total": len(rows), "would_block": len(items), "blocked": blocked,
            "items": items}


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
              workspace_id: str = "", user_id: str = "") -> dict:
    """新建草稿。

    ⭐ R3-9：新增 ``user_id`` 参数并**真正落库**。
       此前 add_draft 从不写 user_id，而所有读取路径又不过滤归属，
       等于「任何登录用户可访问任意 did」。调用方（web 路由）必须传入
       当前登录用户 id；留空仅允许内部任务使用（归属为空 → 对外不可见）。
    """
    c = conn()
    cand_json = json.dumps(candidate_titles or [], ensure_ascii=False)
    stats_json = json.dumps(source_stats or {}, ensure_ascii=False)
    d = {"id": uid("dr"), "topic_id": topic_id, "created_at": now(), "title": title,
         "body_md": body_md, "platforms": json.dumps(platforms), "status": "preview",
         "source_platform": source_platform, "source_url": source_url,
         "source_title": source_title, "analysis": analysis,
         "candidate_titles": cand_json, "source_stats": stats_json,
         "workspace_id": workspace_id, "user_id": str(user_id or "")}
    c.execute("INSERT INTO drafts (id,topic_id,created_at,title,body_md,platforms,status,"
              "source_platform,source_url,source_title,analysis,candidate_titles,source_stats,"
              "workspace_id,user_id) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              tuple(d[k] for k in ("id", "topic_id", "created_at", "title", "body_md",
                                   "platforms", "status", "source_platform",
                                   "source_url", "source_title", "analysis",
                                   "candidate_titles", "source_stats",
                                   "workspace_id", "user_id")))
    c.commit()
    c.close()
    return d


def create_custom_draft(title: str, body_md: str = "", workspace_id: str = "",
                         platforms: list[str] | None = None,
                         user_id: str = "") -> dict:
    """创作者在内容工作台手动新建草稿或导入外部草稿。

    ⭐ R3-9：透传 user_id，让新建的草稿立刻带上归属。
    """
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
        workspace_id=workspace_id or "",
        user_id=user_id or "",
    )


def get_draft(draft_id: str) -> dict | None:
    """按 id 取草稿（**不做归属校验**）。

    ⚠️ 安全警告（R3-9）：本函数只按 id 查，任何知道 did 的登录用户都能取到
       别人的稿件。仅供「内部任务/后台线程/归属已确定」的场景使用。
       对外暴露的接口必须改用 :func:`get_draft_for_user`
       （或web层的 ``_assert_draft_owner``），否则就是越权漏洞。
    """
    c = conn()
    r = c.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    c.close()
    if not r:
        return None
    d = dict(r)
    for k in ("platforms", "candidate_titles", "source_stats"):
        try:
            d[k] = json.loads(d[k]) if d.get(k) else ([] if k != "source_stats" else {})
        except Exception:
            d[k] = [] if k != "source_stats" else {}
    return d


# ---------------------------------------------------------------------------
# R3-9：草稿归属隔离
# ---------------------------------------------------------------------------
#
# 背景（实测）：``drafts.user_id`` 全库为空串，且 :func:`get_draft` /
# :func:`list_drafts` 从不过滤归属 → **任何登录用户拿到任意 did 就能读
# 别人的稿件与图片直链**（/img/{did}/{name}、/card/{did}/{name} 同样如此）。
#
# 归属判定规则（fail-closed）：
#   - 草稿有 user_id → 只有该user（及管理员）可访问；
#   - 草稿 user_id 为空（R3-9 前的历史数据）→ 已由 backfill_drafts_owner
#     一次性回填给本机唯一管理员；回填后仍为空的一律**只允许管理员**访问，
#     绝不退化成「谁都能看」。

def is_draft_owner(draft: dict | None, user_id: str, *, is_admin: bool = False) -> bool:
    """判断某用户是否有权访问该草稿。

    Args:
        draft: 草稿行（dict），为空视为无权。
        user_id: 当前登录用户 id。
        is_admin: 管理员/运营可跨用户访问（排障与合规复核需要）。
    """
    if not draft:
        return False
    if is_admin:
        return True
    owner = str(draft.get("user_id") or "").strip()
    uid = str(user_id or "").strip()
    if not owner:
        # 无归属的历史数据：只放行管理员，绝不「无人认领即公开」
        return False
    return bool(uid) and owner == uid


def get_draft_for_user(draft_id: str, user_id: str, *, is_admin: bool = False) -> dict | None:
    """取草稿并校验归属；无权访问时返回 ``None``（由调用方决定 403 还是 404）。

    刻意**不直接抛错**：不同端点对「存在但无权」应返回 403 还是 404
    有不同取舍（404 不泄露 id 是否存在），由web 层统一决定。
    """
    d = get_draft(draft_id)
    if not d:
        return None
    return d if is_draft_owner(d, user_id, is_admin=is_admin) else None


def backfill_drafts_owner(default_owner: str = "u-admin") -> int:
    """R3-9：把``drafts.user_id`` 为空的历史草稿归到 ``default_owner``名下。

    背景：库里有 6 条草稿 ``user_id`` 全为空串（实测），在归属校验上线后
    这些草稿会对所有人不可见（含原作者）。本函数在连接建立时**幂等执行**：
    只填空串，不动已有归属，因此可以安全地反复调用。

    Returns:
        本次回填的行数（无新增时返回 0）。
    """
    owner = str(default_owner or "").strip()
    if not owner:
        return 0
    try:
        c = conn()
        cur = c.execute(
            "UPDATE drafts SET user_id=? WHERE user_id IS NULL OR TRIM(user_id)=''",
            (owner,),
        )
        c.commit()
        n = cur.rowcount or 0
        c.close()
        return int(n)
    except Exception:
        # 回填失败绝不能拖垮连接建立：归属校验会 fail-closed 拒绝访问，
        # 宁可「暂时谁都看不到」，也不要「谁都能看」。
        return 0


def list_drafts(user_id: str = "", *, is_admin: bool = False) -> list[dict]:
    """草稿列表。

    ⭐ R3-9：新增归属过滤。传 ``user_id`` 只返回该用户的草稿；
       ``is_admin=True`` 返回全部（运营排障/合规复核）。
       **不传 user_id 且非管理员时返回空列表**（fail-closed）——
       绝不能退化成「列出所有人的稿件」。
    """
    c = conn()
    sql = ("SELECT id,topic_id,created_at,title,body_md,platforms,status,"
           "source_platform,source_url,source_title,analysis,"
           "score,score_detail,score_round,candidate_titles,source_stats,"
           "needs_review,guard_reason,user_id "
           "FROM drafts")
    params: tuple = ()
    if not is_admin:
        sql += " WHERE user_id = ?"
        params = (str(user_id or ""),)
    sql += " ORDER BY created_at DESC LIMIT 200"
    rows = c.execute(sql, params).fetchall()
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


def mark_draft_needs_review(draft_id: str, reason: str = "") -> bool:
    """把草稿标记为「待人工复核」（**不删除草稿**）。

    R4-1 灰区内容 / R4-4 存量违规草稿都走这里。
    """
    c = conn()
    cur = c.execute(
        "UPDATE drafts SET needs_review=1, guard_reason=? WHERE id=?",
        (reason[:500], draft_id))
    c.commit()
    n = cur.rowcount
    c.close()
    return bool(n)


def clear_draft_needs_review(draft_id: str) -> bool:
    """人工复核通过后清除标记。"""
    c = conn()
    cur = c.execute(
        "UPDATE drafts SET needs_review=0, guard_reason='' WHERE id=?", (draft_id,))
    c.commit()
    n = cur.rowcount
    c.close()
    return bool(n)


def list_drafts_needs_review() -> list[dict]:
    """列出待人工复核的草稿。"""
    c = conn()
    rows = c.execute(
        "SELECT * FROM drafts WHERE needs_review=1 ORDER BY created_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def sweep_drafts_needs_review(apply: bool = False) -> dict:
    """扫描全部草稿，把命中内容安全闸的条目标记 needs_review。

    参数 apply: False = 预演，True = 真正标记（不删草稿）。
    """
    from core import content_guard

    c = conn()
    rows = c.execute("SELECT id, title, body_md FROM drafts").fetchall()
    c.close()
    items = []
    for r in rows:
        res = content_guard.pre_publish_check(r["body_md"], r["title"])
        if res.blocked or res.needs_review:
            items.append({"id": r["id"], "title": r["title"], "level": res.level,
                          "reason": res.reason()})
    marked = 0
    if apply:
        for it in items:
            if mark_draft_needs_review(it["id"], it["reason"]):
                marked += 1
    return {"total": len(rows), "flagged": len(items), "marked": marked, "items": items}


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


def delete_old_tasks(statuses: list[str], older_than_ts: float) -> int:
    """删除指定状态且 updated_at 早于 older_than_ts 的任务。返回删除条数。"""
    if not statuses:
        return 0
    c = conn()
    placeholders = ",".join("?" for _ in statuses)
    r = c.execute(
        f"DELETE FROM async_tasks WHERE status IN ({placeholders}) AND updated_at < ?",
        (*statuses, older_than_ts),
    )
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


