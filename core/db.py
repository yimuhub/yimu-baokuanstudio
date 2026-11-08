# SPDX-License-Identifier: BUSL-1.1
"""SQLite 存储层：选题 / 草稿 / 发布任务。"""
from __future__ import annotations
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

logger = logging.getLogger(__name__)

# R2-1：额度数字的唯一真源（core.auth 也从这里取，避免两处硬编码）
from studio.pricing import TIER_CREDITS

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

#: 数据库文件位置。默认 data/mediaflow.db；可用 YIMU_DB_PATH 覆盖。
#: 用途：① 测试时指向临时库，避免多个测试用例共享一份真库互相污染
#:      （改口令、加余额这类用例会把状态留给后面的用例）；
#:      ② 运维需要把库放到别的磁盘/卷时不必改代码。
DB_PATH = Path(os.environ.get("YIMU_DB_PATH") or (DATA / "mediaflow.db"))

#: 草稿 id / 工作区 id 等「会拼进文件路径」的标识符的合法形态。
#: 只允许字母数字下划线短横：足以覆盖 uuid4().hex[:12] 与历史数据，
#: 同时天然排除 "/"、"\""、".."、":"（Windows 盘符）等穿越字符。
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# ---------------------------------------------------------------------------
# 当前请求的用户上下文（ContextVar）
# ---------------------------------------------------------------------------
# 为什么 db 层需要知道"谁在请求"：
#   「当前活动工作区」原本是全库单例（UPDATE workspaces SET is_active=0 全表置零），
#   于是 A 切工作区，B 的草稿箱立刻跟着变；并发切换还会留下两行 is_active=1，
#   LIMIT 1 取哪行看物理顺序 → 刷新后工作区随机跳。
#   现在按 user_id 存偏好（workspace_active 表），db 层从 ContextVar 取当前用户。
#   web 层在 guard() 里 set_request_user()，后台任务不设值 → 沿用全局默认，
#   行为与历史一致。
_CURRENT_USER_ID: ContextVar[str] = ContextVar("yimu_db_user", default="")


def set_request_user(user_id: str) -> None:
    """由 web 层在每个请求的鉴权入口调用。"""
    _CURRENT_USER_ID.set(str(user_id or ""))


def current_request_user() -> str:
    return _CURRENT_USER_ID.get() or ""

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
  analysis TEXT DEFAULT '',
  platform TEXT NOT NULL DEFAULT '',
  tenant_id TEXT NOT NULL DEFAULT 'default',
  needs_review INTEGER NOT NULL DEFAULT 0,
  guard_reason TEXT DEFAULT '',
  updated_at TEXT DEFAULT ''
);
-- R10.0 性能整改说明：drafts 过滤列索引统一在 conn() 迁移块中创建
-- （user_id/platform/tenant_id 在旧库可能缺列，SCHEMA 阶段建索引会炸迁移）。
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
-- V7 新增表（列定义与 studio/db_models.py 对齐，raw sqlite3 与 SQLAlchemy 双层共用） --
--
-- ⭐ V9.3.2 P0-2：双层数据访问合并（审查报告"合并双层数据访问"建议）。
--   此前 users.created_at / last_login 在 core 侧写 REAL（epoch 秒）、
--   在 studio ORM 侧写 TEXT（ISO 字符串），同一列两种编码，
--   ORM 按 created_at 排序时 fromisoformat 崩溃（历史 P0 事故，
--   见 core/auth.py:_iso_now 与 studio/flex_datetime.py 的兼容层）。
--   本版本把 users / user_api_keys 的时间列统一为 TEXT ISO 8601
--   （studio ORM 真源，FlexibleDateTime 双向可读），
--   存量 REAL 值由 studio/flex_datetime.py 的读兼容层兜底，
--   新写入一律 ISO（core.auth._iso_now 已如此），
--   从此两条路径不再有编码分歧。
--   其余表（topics / drafts / ...）的 created_at REAL 保持不变，
--   因为它们不属于 ORM 真源，无此冲突。
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
  created_at TEXT,                 -- ⭐ V9.3.2：ISO 8601（与 studio ORM 真源一致；存量 REAL 由读兼容层兜底）
  last_login TEXT,                -- ⭐ V9.3.2：ISO 8601（同上）
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
  created_at TEXT                 -- ⭐ V9.3.2：ISO 8601（与 studio ORM UserApiKey 真源一致）
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


# 标准全量草稿表列定义（确保迁移后具备全部必要字段与安全默认值，绝无 CHECK 约束）
STANDARD_DRAFT_COLUMNS: dict[str, str] = {
    "id": "TEXT PRIMARY KEY",
    "topic_id": "TEXT DEFAULT ''",
    "created_at": "REAL DEFAULT 0",
    "title": "TEXT DEFAULT ''",
    "body_md": "TEXT DEFAULT ''",
    "platforms": "TEXT DEFAULT '[]'",
    "status": "TEXT DEFAULT 'preview'",
    "source_platform": "TEXT DEFAULT ''",
    "source_url": "TEXT DEFAULT ''",
    "source_title": "TEXT DEFAULT ''",
    "analysis": "TEXT DEFAULT ''",
    "platform": "TEXT DEFAULT 'wechat_mp'",
    "tenant_id": "TEXT DEFAULT 'default'",
    "needs_review": "INTEGER DEFAULT 0",
    "guard_reason": "TEXT DEFAULT ''",
    "updated_at": "TEXT DEFAULT ''",
    "score": "REAL",
    "score_detail": "TEXT DEFAULT ''",
    "score_round": "INTEGER DEFAULT 0",
    "candidate_titles": "TEXT DEFAULT '[]'",
    "source_stats": "TEXT DEFAULT '{}'",
    "workspace_id": "TEXT DEFAULT ''",
    "user_id": "TEXT DEFAULT 'u-admin'",
}


def auto_heal_drafts_check_constraint(c: sqlite3.Connection) -> bool:
    """自动无损自愈 drafts 表的 CHECK 约束。

    SQLite 无法通过 ALTER TABLE 修改或删除已存在的 CHECK 约束。
    若存量数据库中 drafts 表创建时带有限制 status 的 CHECK 约束（如 ck_drafts_status），
    在写入 'preview' / 'approved' / 'failed' 等新状态时会直接触发
    IntegrityError: CHECK constraint failed: ck_drafts_status。

    本函数执行 SQLite 官方标准的 12 步表重构无损迁移：
    1. 检查 sqlite_master 中 drafts 的 DDL 是否含有 ck_drafts_status 或状态 CHECK；
    2. 若有，关闭外键，获取当前所有列名与类型；
    3. 创建无限制性 CHECK 约束的 drafts_new 临时表（包含标准全量字段与存量自定义字段）；
    4. 迁移存量全量数据（对历史 NULL 值通过 COALESCE 智能安全回填）；
    5. 替换 drafts 表并重建索引；
    6. 恢复外键并提交。
    """
    try:
        row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='drafts'").fetchone()
    except Exception:
        return False
    if not row or not row[0]:
        return False
    sql = str(row[0])
    needs_heal = (
        "ck_drafts_status" in sql
        or ("check" in sql.lower() and "status" in sql.lower())
    )
    if not needs_heal:
        return False

    try:
        c.rollback()
    except Exception:
        pass
    orig_isolation = getattr(c, "isolation_level", None)
    c.isolation_level = None
    c.execute("PRAGMA foreign_keys=OFF;")
    try:
        old_count = c.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
        cols_info = c.execute("PRAGMA table_info(drafts)").fetchall()
        if not cols_info:
            return False

        col_defs = []
        for name, ddl in STANDARD_DRAFT_COLUMNS.items():
            col_defs.append(f'"{name}" {ddl}')

        existing_names = {r[1] for r in cols_info}
        for col in cols_info:
            name = col[1]
            if name not in STANDARD_DRAFT_COLUMNS:
                col_type = col[2] or "TEXT"
                dflt = col[4]
                part = f'"{name}" {col_type}'
                if dflt is not None:
                    part += f" DEFAULT {dflt}"
                col_defs.append(part)

        indexes = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='drafts' AND sql IS NOT NULL"
        ).fetchall()

        c.execute("DROP TABLE IF EXISTS drafts_new")
        c.execute(f"CREATE TABLE drafts_new (\n  " + ",\n  ".join(col_defs) + "\n)")

        # 针对存量数据中可能存在的历史 NULL 值，通过 COALESCE 安全回填默认值，杜绝 NOT NULL 报错
        select_exprs = []
        for col in cols_info:
            cname = col[1]
            if cname == "platform":
                select_exprs.append("COALESCE(\"platform\", 'wechat_mp')")
            elif cname == "tenant_id":
                select_exprs.append("COALESCE(\"tenant_id\", 'default')")
            elif cname == "user_id":
                select_exprs.append("COALESCE(\"user_id\", 'u-admin')")
            elif cname == "needs_review":
                select_exprs.append("COALESCE(\"needs_review\", 0)")
            elif cname == "status":
                select_exprs.append("COALESCE(\"status\", 'preview')")
            else:
                select_exprs.append(f'"{cname}"')

        col_names = ", ".join([f'"{r[1]}"' for r in cols_info])
        select_str = ", ".join(select_exprs)
        c.execute(f"INSERT INTO drafts_new ({col_names}) SELECT {select_str} FROM drafts")

        new_count = c.execute("SELECT COUNT(*) FROM drafts_new").fetchone()[0]
        if old_count != new_count:
            raise RuntimeError(f"Drafts migration count mismatch: {old_count} vs {new_count}")

        c.execute("DROP TABLE drafts")
        c.execute("ALTER TABLE drafts_new RENAME TO drafts")

        for idx in indexes:
            if idx[0]:
                try:
                    c.execute(idx[0])
                except Exception:
                    pass
        try:
            c.execute("CREATE INDEX IF NOT EXISTS ix_drafts_tenant_status ON drafts (tenant_id, status)")
        except Exception:
            pass

        try:
            c.execute("UPDATE drafts SET platform='wechat_mp' WHERE platform IS NULL OR TRIM(platform)=''")
            c.execute("UPDATE drafts SET tenant_id='default' WHERE tenant_id IS NULL OR TRIM(tenant_id)=''")
            c.execute("UPDATE drafts SET user_id='u-admin' WHERE user_id IS NULL OR TRIM(user_id)=''")
        except Exception:
            pass

        c.commit()
        return True
    except Exception as e:
        print(f"⚠️ [SQLite自愈] 重构 drafts 表异常: {e}")
        try:
            c.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            c.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            pass
        if orig_isolation is not None:
            try:
                c.isolation_level = orig_isolation
            except Exception:
                pass


def auto_heal_all_sqlite_databases() -> None:
    """自愈 data 目录下所有 SQLite 数据库（包括 mediaflow.db、yimu.db 等）。"""
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        for db_file in DATA.glob("*.db"):
            if ".corrupt." in db_file.name or db_file.name.endswith(".bak"):
                continue
            try:
                conn_temp = sqlite3.connect(str(db_file), timeout=10.0)
                auto_heal_drafts_check_constraint(conn_temp)
                conn_temp.close()
            except Exception:
                pass
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


_INITIALIZED_DB_PATHS: dict[str, int] = {}

#: 已做过「存量数据自愈」的数据库文件（path → inode）。
#: 为什么需要：自愈是 3 条全表 UPDATE，且 WHERE 里带 TRIM() 会让索引失效，
#: 等于每次建连都全表扫 + 开写事务。修复前它挂在 conn() 的**常规路径**上，
#: 而一次请求会调 2-4 次 conn()（get_active_workspace 里还再叠一层），
#: 并发时互相等写锁（busy_timeout 30s），接口被拖到秒级甚至超时。
_HEALED_DB_INODES: dict[str, int] = {}


def _heal_empty_defaults(c: sqlite3.Connection) -> None:
    """把历史数据里的空默认值补齐（**每个库文件只跑一次**）。

    只补 NULL / 空串，属于一次性迁移：跑完之后新写入的行走 NOT NULL DEFAULT，
    不会再产生空值，因此无需重复执行。
    """
    c.execute("CREATE TABLE IF NOT EXISTS workspace_active ("
              "user_id TEXT PRIMARY KEY, "
              "workspace_id TEXT NOT NULL, "
              "updated_at REAL)")
    _ensure_owner_backfill_trigger(c)
    c.execute("UPDATE drafts SET user_id='u-admin' WHERE user_id IS NULL OR TRIM(user_id)=''")
    c.execute("UPDATE drafts SET platform='wechat_mp' WHERE platform IS NULL OR TRIM(platform)=''")
    c.execute("UPDATE drafts SET tenant_id='default' WHERE tenant_id IS NULL OR TRIM(tenant_id)=''")
    c.commit()


def _ensure_owner_backfill_trigger(c: sqlite3.Connection) -> None:
    """建库级触发器：新插入的草稿若没有归属，自动记为 u-admin。

    为什么用触发器而不是在 add_draft 里写死默认值：
      * 语义要保留「add_draft 传空 = 这条稿件暂时无归属」的返回值，
        但又不能让库里长期存在 user_id='' 的行（历史实现是每次 conn()
        全表 UPDATE 回填，代价高且会开写事务）；
      * 触发器只在**插入那一行**上跑一次，零查询开销、无并发写锁问题，
        且对任何写入路径（含 ORM）都成立。
    """
    c.execute(
        "CREATE TRIGGER IF NOT EXISTS trg_drafts_owner_backfill "
        "AFTER INSERT ON drafts FOR EACH ROW "
        "WHEN NEW.user_id IS NULL OR TRIM(NEW.user_id) = '' "
        "BEGIN UPDATE drafts SET user_id='u-admin' WHERE id = NEW.id; END"
    )


#: core 自己会直接读写的表。旧库 / 半迁移库（例如 studio 建过库、
#: 或从很早的版本升级上来）可能缺其中某些表，而 conn() 的快速路径
#: 只认 `drafts` 一张表，缺的表不会被补出来。
_CORE_TABLES = (
    "topics", "drafts", "draft_history", "jobs", "async_tasks",
    "ip_characters", "scheduled_posts", "workspaces", "users",
    "user_api_keys", "tenants", "memberships", "gateway_keys", "ledger",
    "invites", "user_events", "user_notifications", "invite_referrals",
    "publish_attempts", "account_health", "share_links",
)


def _ensure_core_tables(c: sqlite3.Connection) -> list[str]:
    """快速路径下补齐缺失的核心表（幂等；SCHEMA 全是 IF NOT EXISTS）。

    真实事故：``drafts`` 存在但 ``draft_history`` 不存在时，conn() 直接 return，
    ``add_history`` 抛 "no such table: draft_history"。而**新建草稿不写历史表**，
    于是现象是「新建正常，所有改写方式全部失败」——正是 Windows 端反馈的形态。
    """
    try:
        missing = [
            t for t in _CORE_TABLES
            if not c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
        ]
        if missing:
            c.executescript(SCHEMA)
            c.commit()
            logger.warning("已自动补齐缺失的数据表: %s", ", ".join(missing))
        return missing
    except Exception as e:  # pragma: no cover - 补表失败不应阻断业务
        logger.warning("补齐数据表失败（忽略，继续运行）: %s", e)
        return []


def _migrate_columns(c: sqlite3.Connection) -> None:
    """幂等补列：``CREATE TABLE IF NOT EXISTS`` 不会给**已存在**的表补列。

    ⭐ 必须在 conn() 的**快速路径**也执行。
    真实事故：studio 建过的库 ``draft_history`` 有 ``version`` 但没有
    ``title`` / ``body_md`` / ``score``，而补列代码只写在"首次建库"分支里，
    只要 ``drafts`` 表存在就永远走不到 —— 于是 ``add_history`` 恒报
    ``table draft_history has no column named title``。
    新建草稿不写历史表，改写要写，表现就是「新建正常、所有改写方式全失败」。
    """
    try:
        # ---- drafts ----
        cols = {r["name"] for r in c.execute("PRAGMA table_info(drafts)")}
        for col in ("source_platform", "source_url", "source_title", "analysis",
                    "score", "score_detail", "score_round", "candidate_titles",
                    "source_stats", "workspace_id", "user_id",
                    "topic_id", "platforms", "platform", "tenant_id",
                    "needs_review", "guard_reason", "updated_at"):
            if col not in cols:
                t = {"score": "REAL", "score_detail": "TEXT", "score_round": "INTEGER DEFAULT 0",
                     "needs_review": "INTEGER DEFAULT 0",
                     "tenant_id": "TEXT DEFAULT 'default'"}.get(col, "TEXT DEFAULT ''")
                c.execute(f"ALTER TABLE drafts ADD COLUMN {col} {t}")

        # ---- topics ----
        tcols = {r["name"] for r in c.execute("PRAGMA table_info(topics)")}
        for col, typ in (("content", "TEXT DEFAULT ''"),
                         ("content_fetched", "INTEGER DEFAULT 0"),
                         ("freshness_score", "REAL DEFAULT 0"),
                         ("user_id", "TEXT DEFAULT ''"),
                         ("blocked_reason", "TEXT DEFAULT ''"),
                         ("workspace_id", "TEXT DEFAULT ''"),
                         ("tenant_id", "TEXT DEFAULT 'default'")):
            if col not in tcols:
                c.execute(f"ALTER TABLE topics ADD COLUMN {col} {typ}")

        # ---- draft_history：改写链路赖以存活的三个列 ----
        _hcols = {r["name"] for r in c.execute("PRAGMA table_info(draft_history)")}
        for _col, _typ in (("title", "TEXT"), ("body_md", "TEXT"),
                           ("score", "REAL"), ("created_at", "REAL"),
                           ("tenant_id", "TEXT DEFAULT 'default'")):
            if _col not in _hcols:
                try:
                    c.execute(f"ALTER TABLE draft_history ADD COLUMN {_col} {_typ}")
                except sqlite3.OperationalError:
                    pass

        # ---- 其它后加列 ----
        wcols = {r["name"] for r in c.execute("PRAGMA table_info(workspaces)")}
        if "user_id" not in wcols:
            c.execute("ALTER TABLE workspaces ADD COLUMN user_id TEXT DEFAULT ''")
        _icols = {r["name"] for r in c.execute("PRAGMA table_info(invites)")}
        if "inviter_id" not in _icols:
            c.execute("ALTER TABLE invites ADD COLUMN inviter_id TEXT NOT NULL DEFAULT ''")

        # ---- 租户隔离：给业务表补 tenant_id ----
        for _t in ("drafts", "draft_history", "jobs", "async_tasks",
                   "ip_characters", "scheduled_posts", "workspaces",
                   "users", "user_api_keys"):
            try:
                _cols = {r["name"] for r in c.execute(f"PRAGMA table_info({_t})")}
            except Exception:
                continue
            if _cols and "tenant_id" not in _cols:
                c.execute(f"ALTER TABLE {_t} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")

        try:
            ensure_users_columns(c)
        except Exception:
            pass

        # ---- 存量数据自愈 ----
        c.execute("UPDATE drafts SET platform='wechat_mp' WHERE platform IS NULL OR TRIM(platform)=''")
        c.execute("UPDATE drafts SET tenant_id='default' WHERE tenant_id IS NULL OR TRIM(tenant_id)=''")
        c.execute("UPDATE drafts SET user_id='u-admin' WHERE user_id IS NULL OR TRIM(user_id)=''")
        c.commit()
    except Exception as e:  # pragma: no cover - 迁移失败不应阻断业务
        logger.warning("补列迁移失败（忽略，继续运行）: %s", e)


def conn() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = _connect_sqlite(DB_PATH)
    c.row_factory = sqlite3.Row
    db_key = str(DB_PATH)
    try:
        db_ino = DB_PATH.stat().st_ino if DB_PATH.exists() else 0
    except OSError:
        db_ino = 0
    # ⭐ V9.4.0 性能优化：同一数据库文件仅在首次建连或表缺失时执行全量 DDL 与列迁移，
    #   避免每次 SELECT/UPDATE 重复跑 40+ 条 PRAGMA 与 CREATE TABLE（性能提升 10x+）。
    has_drafts = False
    if db_ino and _INITIALIZED_DB_PATHS.get(db_key) == db_ino:
        try:
            has_drafts = bool(
                c.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='drafts'"
                ).fetchone()
            )
        except Exception:
            has_drafts = False
    if has_drafts:
        # ⭐ R11 双线融合：
        #   ① 远端设计——重迁移只在本进程首次接触该库时做一次
        #     （补表+补列：drafts 存在不代表 draft_history 等表/列也存在，
        #      老库 draft_history 缺列会一直报错）；
        #   ② 本地 R10.0 连接税整改——运行期坏数据自愈走索引探测，
        #     干净库 3 次索引 seek 即返回，不背全表扫描税。
        if _HEALED_DB_INODES.get(db_key) != db_ino:
            auto_heal_drafts_check_constraint(c)
            _heal_empty_defaults(c)
            _ensure_core_tables(c)
            _migrate_columns(c)
            _HEALED_DB_INODES[db_key] = db_ino
        try:
            dirty = (
                c.execute("SELECT 1 FROM drafts WHERE user_id IS NULL OR user_id='' LIMIT 1").fetchone()
                or c.execute("SELECT 1 FROM drafts WHERE platform IS NULL OR platform='' LIMIT 1").fetchone()
                or c.execute("SELECT 1 FROM drafts WHERE tenant_id IS NULL OR tenant_id='' LIMIT 1").fetchone()
            )
        except sqlite3.OperationalError:
            dirty = False  # 缺列/缺索引场景已由上方一次性迁移补齐
        if dirty:
            auto_heal_drafts_check_constraint(c)
            c.execute("UPDATE drafts SET user_id='u-admin' WHERE user_id IS NULL OR TRIM(user_id)=''")
            c.execute("UPDATE drafts SET platform='wechat_mp' WHERE platform IS NULL OR TRIM(platform)=''")
            c.execute("UPDATE drafts SET tenant_id='default' WHERE tenant_id IS NULL OR TRIM(tenant_id)=''")
            c.commit()
        return c

    c.executescript(SCHEMA)
    auto_heal_drafts_check_constraint(c)
    # 旧库迁移：补列
    cols = {r["name"] for r in c.execute("PRAGMA table_info(drafts)")}
    for col in ("source_platform", "source_url", "source_title", "analysis",
                "score", "score_detail", "score_round", "candidate_titles", "source_stats", "workspace_id", "user_id",
                "topic_id", "platforms", "platform", "tenant_id", "needs_review", "guard_reason", "updated_at"):
        if col not in cols:
            t = {"score": "REAL", "score_detail": "TEXT", "score_round": "INTEGER DEFAULT 0",
                 "needs_review": "INTEGER DEFAULT 0", "tenant_id": "TEXT DEFAULT 'default'"}.get(col, "TEXT DEFAULT ''")
            c.execute(f"ALTER TABLE drafts ADD COLUMN {col} {t}")
    # 存量数据自愈：补齐历史数据中的空默认值
    c.execute("UPDATE drafts SET platform='wechat_mp' WHERE platform IS NULL OR TRIM(platform)=''")
    c.execute("UPDATE drafts SET tenant_id='default' WHERE tenant_id IS NULL OR TRIM(tenant_id)=''")
    c.execute("UPDATE drafts SET user_id='u-admin' WHERE user_id IS NULL OR TRIM(user_id)=''")
    # R10.0 性能整改：迁移完成后统一补建 drafts 过滤列索引（新库/旧库都安全）
    for _idx_sql in (
        "CREATE INDEX IF NOT EXISTS ix_drafts_user ON drafts (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_drafts_platform ON drafts (platform)",
        "CREATE INDEX IF NOT EXISTS ix_drafts_tenant ON drafts (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_drafts_updated ON drafts (updated_at)",
    ):
        try:
            c.execute(_idx_sql)
        except Exception:
            pass  # 极旧库缺列时静默跳过，下轮迁移补齐后再建
    c.commit()
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
    if "workspace_id" not in tcols:
        c.execute("ALTER TABLE topics ADD COLUMN workspace_id TEXT DEFAULT ''")

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
    for _t in ("topics", "drafts", "draft_history", "jobs", "async_tasks",
               "ip_characters", "scheduled_posts", "workspaces",
               "users", "user_api_keys"):
        try:
            _cols = {r["name"] for r in c.execute(f"PRAGMA table_info({_t})")}
        except Exception:
            continue
        if "tenant_id" not in _cols:
            c.execute(f"ALTER TABLE {_t} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")

    # 版本历史：老库 draft_history 可能缺 title / body_md / score（这些列是后加的，
    # 而 CREATE TABLE IF NOT EXISTS 不会给「已存在」的表补列），这里幂等补齐。
    # 否则 add_history / list_history 会因「no column named title」直接 500，
    # 「外科手术定点精修 / 批量切除」等功能全部瘫痪。
    _hcols = {r["name"] for r in c.execute("PRAGMA table_info(draft_history)")}
    for _col, _typ in (("title", "TEXT"), ("body_md", "TEXT"), ("score", "REAL")):
        if _col not in _hcols:
            try:
                c.execute(f"ALTER TABLE draft_history ADD COLUMN {_col} {_typ}")
            except sqlite3.OperationalError:
                pass
    ensure_users_columns(c)

    # 确保默认租户行存在
    c.execute(
        "INSERT OR IGNORE INTO tenants (id, name, plan, launch_mode, is_active, created_at) "
        "VALUES ('default', 'default', 'free', 'invite-only', 1, datetime('now'))"
    )

    # R3-9：把历史草稿（user_id 为空串）的归属一次性回填给本机管理员。
    c.execute(
        "UPDATE drafts SET user_id='u-admin' WHERE user_id IS NULL OR TRIM(user_id)=''"
    )

    # 工作区偏好按用户隔离（见 get_active_workspace / set_active_workspace）
    c.execute("CREATE TABLE IF NOT EXISTS workspace_active ("
              "user_id TEXT PRIMARY KEY, "
              "workspace_id TEXT NOT NULL, "
              "updated_at REAL)")
    # 新建的草稿若没归属，由触发器自动记为 u-admin（见 _ensure_owner_backfill_trigger）
    _ensure_owner_backfill_trigger(c)

    c.commit()
    try:
        if DB_PATH.exists():
            _INITIALIZED_DB_PATHS[db_key] = DB_PATH.stat().st_ino
    except OSError:
        pass
    return c


def now() -> float:
    return time.time()


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------- topics ----------

def add_topic(source: str, title: str, reason: str = "", matched: bool = False,
              content: str = "", content_fetched: int = 0, freshness_score: float = 0.0,
              workspace_id: str = "") -> dict:
    c = conn()
    ws_id = workspace_id or get_active_workspace().get("id", "ws-default")
    t = {"id": uid("tp"), "created_at": now(), "source": source, "title": title,
         "reason": reason, "matched": int(matched), "status": "pending",
         "content": content, "content_fetched": int(content_fetched), "freshness_score": float(freshness_score),
         "workspace_id": ws_id}
    c.execute("INSERT INTO topics (id, created_at, source, title, reason, matched, status, content, content_fetched, freshness_score, workspace_id) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (t["id"], t["created_at"], t["source"], t["title"], t["reason"],
               t["matched"], t["status"], t["content"], t["content_fetched"], t["freshness_score"], t["workspace_id"]))
    c.commit()
    c.close()
    return t


def list_topics(status: str | None = None, workspace_id: str = "") -> list[dict]:
    c = conn()
    wheres = []
    params = []
    if status:
        wheres.append("status = ?")
        params.append(status)
    if workspace_id:
        if workspace_id == "ws-default":
            wheres.append("(workspace_id = ? OR workspace_id = '' OR workspace_id IS NULL)")
            params.append(workspace_id)
        else:
            wheres.append("workspace_id = ?")
            params.append(workspace_id)
    sql = "SELECT * FROM topics"
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY created_at DESC LIMIT 200"
    rows = c.execute(sql, tuple(params)).fetchall()
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
    """草稿的资源目录（不存在则创建）。

    ⚠️ 安全：``draft_id`` 会被拼进文件路径，因此必须校验形态。
       修复前这里直接 ``DATA / "drafts" / draft_id``，调用方若把
       ``did="../../etc"`` 传进来（例如 /api/drafts/delete 直接取 body 的 ids），
       就能把仓库任意目录当作草稿目录读写甚至 shutil.move 走。
       现在非法 id 直接抛错，路由层返回 400。
    """
    did = str(draft_id or "").strip()
    if not _SAFE_ID_RE.match(did):
        raise ValueError(f"非法草稿 id: {draft_id!r}")
    root = (DATA / "drafts").resolve()
    d = (root / did).resolve()
    if d != root and root not in d.parents:
        raise ValueError(f"非法草稿 id（越界）: {draft_id!r}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_draft(topic_id: str, title: str, body_md: str, platforms: list[str], *,
              source_platform: str = "", source_url: str = "",
              source_title: str = "", analysis: str = "",
              candidate_titles: list[dict] | None = None,
              source_stats: dict | None = None,
              workspace_id: str = "", user_id: str = "",
              platform: str = "") -> dict:
    """新建草稿。

    ⭐ R3-9：新增 ``user_id`` 参数并**真正落库**。
       此前 add_draft 从不写 user_id，而所有读取路径又不过滤归属，
       等于「任何登录用户可访问任意 did」。调用方（web 路由）必须传入
       当前登录用户 id；留空仅允许内部任务使用（归属为空 → 对外不可见）。
    ⭐ V10.1.4 健壮性增强：显式写入 platform / tenant_id / updated_at / needs_review 等字段，
       无论数据库由 studio ORM 先创建还是由 SQLite 原生 DDL 先创建，均 100% 满足约束并支持双层互访。
    """
    c = conn()
    # ⭐ 落库总闸（存储态）：正文保留 Markdown 排版标记，只清结构性垃圾。
    #    公众号的加粗/小节标题全靠 `**`、`##` 在渲染时转成 HTML——源头剥掉就等于
    #    永久丢弃排版能力。符号的清除统一放在展示出口（卡片图 / 复制 / 纯文本平台）。
    #    标题没有排版需求，且要在列表页单行展示，仍走 purify_title。
    from core.text_purity import purify_title, to_storage

    title = purify_title(title or "")
    body_md = to_storage(body_md or "")
    cand_json = json.dumps(candidate_titles or [], ensure_ascii=False)
    stats_json = json.dumps(source_stats or {}, ensure_ascii=False)
    ws_id = workspace_id or get_active_workspace().get("id", "ws-default")
    uid_str = str(user_id or "")

    # 主平台识别
    main_platform = (platform or "").strip()
    if not main_platform:
        if platforms and isinstance(platforms, (list, tuple)) and platforms[0]:
            main_platform = str(platforms[0]).strip()
        elif source_platform:
            main_platform = str(source_platform).strip()
        else:
            main_platform = "wechat_mp"

    created_time = now()
    d = {"id": uid("dr"), "topic_id": str(topic_id or ""), "created_at": created_time, "title": title or "",
         "body_md": body_md or "",
         "platforms": json.dumps(platforms, ensure_ascii=False) if isinstance(platforms, (list, tuple)) else str(platforms or "[]"),
         "status": "preview",
         "source_platform": source_platform or "", "source_url": source_url or "",
         "source_title": source_title or "", "analysis": analysis or "",
         "candidate_titles": cand_json, "source_stats": stats_json,
         "workspace_id": ws_id, "user_id": uid_str,
         "platform": main_platform,
         "tenant_id": "default",
         "needs_review": 0,
         "guard_reason": "",
         "updated_at": str(created_time)}

    insert_sql = (
        "INSERT INTO drafts (id,topic_id,created_at,title,body_md,platforms,status,"
        "source_platform,source_url,source_title,analysis,candidate_titles,source_stats,"
        "workspace_id,user_id,platform,tenant_id,needs_review,guard_reason,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    insert_params = tuple(
        d[k]
        for k in (
            "id", "topic_id", "created_at", "title", "body_md",
            "platforms", "status", "source_platform",
            "source_url", "source_title", "analysis",
            "candidate_titles", "source_stats",
            "workspace_id", "user_id", "platform",
            "tenant_id", "needs_review", "guard_reason", "updated_at",
        )
    )
    try:
        c.execute(insert_sql, insert_params)
    except sqlite3.IntegrityError as e:
        if "ck_drafts_status" in str(e) or "drafts.status" in str(e) or "status" in str(e).lower():
            try:
                c.rollback()
            except Exception:
                pass
            auto_heal_drafts_check_constraint(c)
            try:
                c.execute(insert_sql, insert_params)
            except Exception:
                # 终极保底：若旧库约束极端固化，临时以 'draft' 状态写入（'draft' 满足任何历史约束，100% 入库）
                d["status"] = "draft"
                safe_params = list(insert_params)
                safe_params[6] = "draft"
                try:
                    c.execute(insert_sql, tuple(safe_params))
                except Exception:
                    # 极端精简模式降级兜底
                    c.execute(
                        "INSERT INTO drafts (id, title, body_md, status, user_id, platform, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)",
                        (d["id"], d["title"], d["body_md"], d["user_id"] or "u-admin", d["platform"] or "wechat_mp", d["created_at"], d["updated_at"])
                    )
        else:
            raise
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
    if not r:
        c.close()
        return None
    d = dict(r)
    # 历史草稿（user_id 为空串）在**首次被读取时**回填给本机管理员。
    # 为什么放这里而不是 conn()：conn() 是每次建连都跑的常规路径，
    # 在那里做全表 UPDATE 会让每次请求都开写事务、并发互相等锁；
    # 而单行回填只在真的读到无归属稿件时发生一次，代价可忽略。
    if not str(d.get("user_id") or "").strip():
        try:
            c.execute("UPDATE drafts SET user_id='u-admin' WHERE id=? AND (user_id IS NULL OR TRIM(user_id)='')",
                      (draft_id,))
            c.commit()
            d["user_id"] = "u-admin"
        except Exception:
            pass
    c.close()
    for k in ("platforms", "candidate_titles", "source_stats"):
        try:
            d[k] = json.loads(d[k]) if d.get(k) else ([] if k != "source_stats" else {})
        except Exception:
            d[k] = [] if k != "source_stats" else {}
    # ⭐ 读取侧兜底（存储态）：只清结构性垃圾，**保留** `**`/`##` 等排版标记。
    #    老稿件的噪音由展示出口（卡片渲染、纯文本接口）负责清除。
    try:
        from core.text_purity import purify_title, to_storage

        d["title"] = purify_title(d.get("title") or "")
        d["body_md"] = to_storage(d.get("body_md") or "")
        if isinstance(d.get("candidate_titles"), list):
            d["candidate_titles"] = [
                ({**t, "title": purify_title(t.get("title", ""))} if isinstance(t, dict) else t)
                for t in d["candidate_titles"]
            ]
    except Exception:
        pass
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


def list_drafts(user_id: str = "", *, is_admin: bool = False, workspace_id: str = "") -> list[dict]:
    """草稿列表。
    支持按工作空间 workspace_id 完全隔离。
    """
    c = conn()
    sql = ("SELECT id,topic_id,created_at,title,body_md,platforms,status,"
           "source_platform,source_url,source_title,analysis,"
           "score,score_detail,score_round,candidate_titles,source_stats,"
           "needs_review,guard_reason,user_id,workspace_id "
           "FROM drafts")
    wheres = []
    params = []
    if not is_admin:
        wheres.append("user_id = ?")
        params.append(str(user_id or ""))
    if workspace_id:
        if workspace_id == "ws-default":
            wheres.append("(workspace_id = ? OR workspace_id = '' OR workspace_id IS NULL)")
            params.append(workspace_id)
        else:
            wheres.append("workspace_id = ?")
            params.append(workspace_id)
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY created_at DESC LIMIT 200"
    rows = c.execute(sql, tuple(params)).fetchall()
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
        # ⭐ 列表页标题同样不能带 ** / ## / #话题
        from core.text_purity import purify_title

        d["title"] = purify_title(d.get("title") or "")
        out.append(d)
    return out


def update_draft_title(draft_id: str, new_title: str) -> None:
    # ⭐ 落库总闸：标题里绝不能出现 **、##、#话题 之类的标记噪音
    from core.text_purity import purify_title

    c = conn()
    c.execute("UPDATE drafts SET title=? WHERE id=?", (purify_title(new_title), draft_id))
    c.commit()
    c.close()


def update_draft_body(draft_id: str, new_body: str) -> None:
    # ⭐ 落库总闸（存储态）：保留 Markdown 排版标记，符号在展示出口清除
    from core.text_purity import to_storage

    c = conn()
    c.execute("UPDATE drafts SET body_md=? WHERE id=?", (to_storage(new_body), draft_id))
    c.commit()
    c.close()


def update_draft_candidate_titles(draft_id: str, candidate_titles: list[dict]) -> None:
    from core.text_purity import purify_title

    # 赛马标题会直接展示给用户挑，同样不允许带 ** / ## / #话题
    cleaned = [
        ({**t, "title": purify_title(t.get("title", ""))} if isinstance(t, dict) else t)
        for t in (candidate_titles or [])
    ]
    c = conn()
    c.execute("UPDATE drafts SET candidate_titles=? WHERE id=?",
              (json.dumps(cleaned, ensure_ascii=False), draft_id))
    c.commit()
    c.close()


def set_draft_status(draft_id: str, status: str) -> None:
    c = conn()
    try:
        c.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
        c.commit()
    except sqlite3.IntegrityError as e:
        if "ck_drafts_status" in str(e) or "status" in str(e).lower():
            try:
                c.rollback()
            except Exception:
                pass
            auto_heal_drafts_check_constraint(c)
            try:
                c.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
                c.commit()
            except Exception:
                safe_status = "draft" if status in ("preview", "draft") else ("published" if status == "published" else "pending_review")
                c.execute("UPDATE drafts SET status=? WHERE id=?", (safe_status, draft_id))
                c.commit()
        else:
            raise
    finally:
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
    try:
        # draft_history 存在两套建表来源：core 建表无 version 列，studio 建表有 version 且 NOT NULL。
        # add_history 必须兼容两者：version 列存在就自增写入，不存在就省略，
        # 否则在 studio 建表的库上会因 NOT NULL 约束直接 500（与缺 title 同源）。
        _hcols = {r[1] for r in c.execute("PRAGMA table_info(draft_history)")}
        if not _hcols:
            # 表根本不存在（旧库 / 半迁移库）：先补建再继续，避免
            # "no such table: draft_history" 让整次改写失败
            _ensure_core_tables(c)
            _hcols = {r[1] for r in c.execute("PRAGMA table_info(draft_history)")}
        # ⭐ 最后一米：表存在但缺 title（studio 建表版本只有 version）时，
        #   就地补齐，不依赖 conn() 的一次性迁移 —— 多进程并存或迁移失败都可能漏掉。
        for _need, _typ in (("title", "TEXT"), ("body_md", "TEXT"),
                            ("score", "REAL"), ("created_at", "REAL")):
            if _need not in _hcols:
                try:
                    c.execute(f"ALTER TABLE draft_history ADD COLUMN {_need} {_typ}")
                    _hcols.add(_need)
                except sqlite3.OperationalError:
                    pass
        if "version" in _hcols:
            _row = c.execute("SELECT MAX(version) FROM draft_history WHERE draft_id=?", (draft_id,)).fetchone()
            _next_v = (int(_row[0]) if _row and _row[0] is not None else 0) + 1
            c.execute(
                "INSERT INTO draft_history (id, draft_id, created_at, title, body_md, score, version) "
                "VALUES (?,?,?,?,?,?,?)",
                (hid, draft_id, now(), title, body_md, score, _next_v),
            )
        else:
            c.execute(
                "INSERT INTO draft_history (id, draft_id, created_at, title, body_md, score) VALUES (?,?,?,?,?,?)",
                (hid, draft_id, now(), title, body_md, score),
            )
        # 每篇最多保留 10 个历史版本（同一连接内完成，少开一次库、少一次锁竞争）
        rows = c.execute("SELECT id FROM draft_history WHERE draft_id=? ORDER BY created_at DESC",
                         (draft_id,)).fetchall()
        for old in rows[10:]:
            c.execute("DELETE FROM draft_history WHERE id=?", (old["id"],))
        c.commit()
        return hid
    finally:
        # ⭐ 必须 finally 关闭：异常路径漏关连接会让 SQLite 长期持有写锁，
        #    Windows 上比 Unix 更容易演变成 "database is locked"。
        try:
            c.close()
        except Exception:
            pass


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
    """列出工作区。

    有当前用户上下文时只返回「他自己的 + 无归属的公共工作区」，
    避免多用户互相看到对方的品牌工作区配置。
    """
    init_workspaces()
    uid = current_request_user()
    c = conn()
    if uid:
        rows = c.execute(
            "SELECT * FROM workspaces WHERE user_id=? OR user_id IS NULL OR user_id='' "
            "ORDER BY created_at ASC", (uid,)).fetchall()
        if not rows:  # 用户还没有自己的工作区，且历史数据都挂在别人名下
            rows = c.execute("SELECT * FROM workspaces ORDER BY created_at ASC").fetchall()
    else:
        rows = c.execute("SELECT * FROM workspaces ORDER BY created_at ASC").fetchall()
    c.close()
    return [_format_workspace_row(r) for r in rows]


def get_active_workspace() -> dict:
    """当前活动工作区（**按用户隔离**）。

    查找顺序：
      1. 当前用户在 workspace_active 里的偏好；
      2. 该用户自己的 / 无归属的第一个工作区；
      3. 历史全局 is_active（后台任务、CLI、单机模式走这里）。
    """
    init_workspaces()
    uid = current_request_user()
    c = conn()
    try:
        if uid:
            row = c.execute(
                "SELECT workspace_id FROM workspace_active WHERE user_id=?", (uid,)
            ).fetchone()
            if row:
                ws = c.execute(
                    "SELECT * FROM workspaces WHERE id=?", (row["workspace_id"],)
                ).fetchone()
                if ws:
                    return _format_workspace_row(ws)
            ws = c.execute(
                "SELECT * FROM workspaces WHERE user_id=? OR user_id IS NULL OR user_id='' "
                "ORDER BY created_at ASC LIMIT 1", (uid,)).fetchone()
            if ws:
                return _format_workspace_row(ws)
        r = c.execute("SELECT * FROM workspaces WHERE is_active=1 LIMIT 1").fetchone()
        if r:
            return _format_workspace_row(r)
    finally:
        c.close()
    return {"id": "ws-default", "name": "默认创作者工作室", "desc": "", "is_active": 1, "config": {}}


def set_active_workspace(wid: str) -> None:
    """切换当前用户的活动工作区。

    ⭐ 修复：不再 `UPDATE workspaces SET is_active=0`（全表置零）。
       那等于「A 切工作区，全站用户跟着换」，并发切换还会留下多行
       is_active=1，`LIMIT 1` 取哪行取决于物理顺序 → 刷新后随机跳。
       有用户上下文时写 workspace_active（一用户一行）；
       无上下文（后台任务/CLI）才保留历史的全局标记。
    """
    wid = str(wid or "").strip()
    if not _SAFE_ID_RE.match(wid):
        raise ValueError(f"非法工作区 id: {wid!r}")
    uid = current_request_user()
    c = conn()
    try:
        if uid:
            c.execute(
                "INSERT OR REPLACE INTO workspace_active (user_id, workspace_id, updated_at) "
                "VALUES (?,?,?)", (uid, wid, time.time()))
            c.commit()
            return
        c.execute("UPDATE workspaces SET is_active=0")
        c.execute("UPDATE workspaces SET is_active=1 WHERE id=?", (wid,))
        c.commit()
    finally:
        c.close()


def create_workspace(name: str, desc: str = "", config: dict | None = None) -> dict:
    c = conn()
    wid = uid("ws")
    cfg_dict = config or {}
    cfg_json = json.dumps(cfg_dict, ensure_ascii=False)
    owner = current_request_user()
    c.execute("INSERT INTO workspaces (id, name, desc, config_json, created_at, is_active, user_id) "
              "VALUES (?,?,?,?,?,0,?)", (wid, name, desc, cfg_json, now(), owner))
    c.commit()
    c.close()
    return {"id": wid, "name": name, "desc": desc, "config_json": cfg_json,
            "config": cfg_dict, "is_active": 0, "user_id": owner}


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


# 模块初始化时主动扫描自愈所有本地 SQLite 数据库中的 drafts CHECK 约束
try:
    auto_heal_all_sqlite_databases()
except Exception:
    pass


