# SPDX-License-Identifier: BUSL-1.1
"""会员能力矩阵与配额引擎：Free / Pro / Studio 三档功能区分。

设计原则（2026-10-08 用户拍板）：
- 免费版"限量不限功能"：让用户体验完整版内容，用完整体验驱动付费转化。
- 网关 API 为Pro 专属卖点，免费版不开放。
- 配额按自然日/自然周重置；超限返回升级引导，不粗暴报错。

⭐ 配额计数只增不改；金额/次数一律整数。

⭐ R2-7 免费版权益必须与额度自洽：
   一条完整 8 步短剧真实消耗 **12000 credits**
   （解构 1000 + 生图 4×1000 + 渲染 5000 + 配音 4×500，见
   ``studio.pricing.FULL_DRAMA_CREDITS``），
   而免费档周期总额度只有 **3000 credits** —— 连一条都跑不完。
   此前本文件承诺"每周 1 次完整 8 步短剧"（``drama_weekly: 1``），
   是一条**必然跳票的承诺**：跑一条就归零，用户只会觉得被骗。
   现改为只送「单镜头体验」（单次分镜解构 + 单张生图），
   让用户尝到 AI 短剧的味道，但要出片必须升级 —— 承诺与账本自洽。
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..db_models import Membership, QuotaCounter, new_id, utcnow

# ---------------------------------------------------------------------------
# 档位显示名（内部 key 不变：free / pro / studio）
# ---------------------------------------------------------------------------

TIER_DISPLAY_NAMES: dict[str, str] = {
    "free": "Free",
    "pro": "Pro",
    "studio": "Studio",
}

# 升级引导文案统一出口
UPGRADE_HINT = "升级 Pro 解锁完整体验"


def tier_display_name(tier: str) -> str:
    """取档位的界面显示名；未知档位按 free 处理。"""
    return TIER_DISPLAY_NAMES.get((tier or "free").lower(), "Free")


# ---------------------------------------------------------------------------
# 能力矩阵 CAPABILITIES[tier][capability]
#
# 值语义：
#   True/False  → 开关型能力
#   正整数      → 配额上限（按 QUOTA_WINDOWS 的窗口计数）
#   -1          → 不限
# ---------------------------------------------------------------------------

CAPABILITIES: dict[str, dict[str, int | bool]] = {
    "free": {
        "hot_daily": 1,            # 每日热榜采集次数
        "hot_platforms": 5,        # 单次可选平台数
        "image_race": False,       # 赛马优选开关（False=单张直出）
        "image_race_weekly": 3,    # 每周赛马体验次数
        "tts_max_chars": 500,      # 单次 TTS 最大字数
        "tts_daily": 5,            # 每日 TTS 次数
        # ⭐ R2-7：free 不再承诺「完整 8 步短剧」——12000 credits 的消耗
        #   远超免费档 3000 的周期额度，承诺必然跳票。
        #   改为 0 次完整流水线；改送「单镜头体验」：
        #   每周可做 drama_shot_experience 次（解构 + 单张生图，约 2000 credits）。
        "drama_weekly": 0,         # 完整 8 步短剧流水线：免费档不提供
        "drama_shot_weekly": 1,    # 每周单镜头体验次数（解构 + 1 张图）
        "drama_max_seconds": 10,   # 短剧成片最大秒数
        "publish_platforms": 1,    # 单次可发布平台数
        "gateway_api": False,      # 网关 Key 创建/API 调用
        "task_concurrency": 1,     # 任务并发数
        "copilot_deep": False,     # Copilot 深度功能
        "copilot_daily": 20,       # 每日 Copilot 对话次数
        "workspaces": 1,           # 工作区数量
        "sub_accounts": False,     # 子账号
    },
    "pro": {
        "hot_daily": -1,
        "hot_platforms": 24,
        "image_race": True,
        "image_race_weekly": -1,
        "tts_max_chars": -1,
        "tts_daily": -1,
        "drama_weekly": -1,
        "drama_shot_weekly": -1,
        "drama_max_seconds": -1,
        "publish_platforms": -1,
        "gateway_api": True,
        "task_concurrency": 5,
        "copilot_deep": True,
        "copilot_daily": -1,
        "workspaces": -1,
        "sub_accounts": False,
    },
    "studio": {
        "hot_daily": -1,
        "hot_platforms": 24,
        "image_race": True,
        "image_race_weekly": -1,
        "tts_max_chars": -1,
        "tts_daily": -1,
        "drama_weekly": -1,
        "drama_shot_weekly": -1,
        "drama_max_seconds": -1,
        "publish_platforms": -1,
        "gateway_api": True,
        "task_concurrency": 20,
        "copilot_deep": True,
        "copilot_daily": -1,
        "workspaces": -1,
        "sub_accounts": True,
    },
}

# 配额型能力的计数窗口（开关型/不限型不需要窗口）
QUOTA_WINDOWS: dict[str, str] = {
    "hot_daily": "day",
    "image_race_weekly": "week",
    "tts_daily": "day",
    "drama_weekly": "week",
    "drama_shot_weekly": "week",
    "copilot_daily": "day",
}

# 超限时的中文引导文案（按能力定制）
_QUOTA_REASONS: dict[str, str] = {
    "hot_daily": "今日热榜采集次数已用完（{used}/{limit}），明日重置",
    "image_race_weekly": "本周图片赛马体验次数已用完（{used}/{limit}），下周一重置",
    "tts_daily": "今日语音合成次数已用完（{used}/{limit}），明日重置",
    "drama_weekly": "本周完整短剧次数已用完（{used}/{limit}），下周一重置",
    "drama_shot_weekly": "本周单镜头体验次数已用完（{used}/{limit}），下周一重置",
    "copilot_daily": "今日 Copilot 对话次数已用完（{used}/{limit}），升级 Pro 可无限使用，明日重置",
}


def capability_limit(tier: str, capability: str) -> int | bool:
    """取某档位某能力的配置值；未知档位/能力按 free 处理。"""
    tier_key = (tier or "free").lower()
    cfg = CAPABILITIES.get(tier_key, CAPABILITIES["free"])
    return cfg.get(capability, CAPABILITIES["free"].get(capability, False))


def is_allowed(tier: str, capability: str) -> bool:
    """开关型能力是否允许（True/-1/正整数视为允许，False/0 视为拒绝）。"""
    v = capability_limit(tier, capability)
    if isinstance(v, bool):
        return v
    return v != 0


# ---------------------------------------------------------------------------
# 配额引擎
# ---------------------------------------------------------------------------


def _window_start(window: str, now: date | None = None) -> str:
    """计算当前窗口的起始标识（UTC 自然日/周一/月初）。"""
    today = now or datetime.now(timezone.utc).date()
    if window == "day":
        return today.isoformat()
    if window == "week":
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()
    if window == "month":
        return today.strftime("%Y-%m")
    raise ValueError(f"未知配额窗口：{window}")


def _quota_reason(capability: str, used: int, limit: int, tier: str) -> str:
    """组装超限提示：已用/上限 + 重置说明 + 升级引导。"""
    tpl = _QUOTA_REASONS.get(capability, "本期可用次数已用完（{used}/{limit}）")
    base = tpl.format(used=used, limit=limit)
    if (tier or "free").lower() == "free":
        return f"{base}，{UPGRADE_HINT}不限次"
    return base


def check_and_consume(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    tier: str,
    capability: str,
) -> tuple[bool, str]:
    """检查配额并消费一次。

    流程：查矩阵（开关/不限直接放行）→ 查计数器（窗口内已用 < 上限则 +1）。
    返回 (allowed, reason)：允许时 reason 为 ""；拒绝时 reason 为中文引导。

    ⭐ 并发说明：计数器行级锁缺失时极端并发可能超发 1~2 次；
    配额是体验限制而非资金，允许该误差（资金扣减仍走原子 UPDATE）。
    """
    tier_key = (tier or "free").lower()
    limit = capability_limit(tier_key, capability)

    # 开关型能力
    if isinstance(limit, bool):
        if limit:
            return True, ""
        return False, f"该功能为 Pro 专属，{UPGRADE_HINT}"

    # -1 = 不限
    if limit == -1:
        return True, ""
    #⭐ R2-7：0 = 该档位不提供此能力（免费档完整短剧即此情形）。
    #   文案要说清「为什么」+「怎么办」，否则用户以为系统坏了。
    if limit == 0:
        if capability == "drama_weekly":
            return False, (
                "完整 8 步 AI 短剧为 Pro 专属功能。免费档可先体验「单镜头短剧」，"
                f"{UPGRADE_HINT}即可生成完整成片。"
            )
        return False, f"该功能为 Pro 专属，{UPGRADE_HINT}"

    # 配额型：按窗口计数
    window = QUOTA_WINDOWS.get(capability)
    if window is None:
        # 有数值上限但无窗口定义 → 视为开关（>0 即允许，不计数）
        return True, ""
    ws = _window_start(window)

    row = (
        db.query(QuotaCounter)
        .filter(
            QuotaCounter.tenant_id == tenant_id,
            QuotaCounter.user_id == user_id,
            QuotaCounter.capability == capability,
            QuotaCounter.window == window,
            QuotaCounter.window_start == ws,
        )
        .first()
    )
    used = int(row.count) if row else 0
    if used >= int(limit):
        return False, _quota_reason(capability, used, int(limit), tier_key)

    if row is None:
        row = QuotaCounter(
            id=new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            capability=capability,
            window=window,
            window_start=ws,
            count=1,
        )
        db.add(row)
    else:
        row.count = used + 1
    db.commit()
    return True, ""


def get_user_tier(db: Session, *, tenant_id: str, user_id: str) -> str:
    """取用户的会员档位 key；无记录时按 free 处理。

    管理员（u-admin）恒为 studio 档（最高权限），不依赖会员记录。
    """
    if (user_id or "") == "u-admin":
        return "studio"
    m = (
        db.query(Membership)
        .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .first()
    )
    if m is None:
        return "free"
    return str(m.tier or "free").lower()


# ---------------------------------------------------------------------------
# DB 会话（供 web 层端点使用；与主应用共用同一 sqlite 文件）
# ---------------------------------------------------------------------------

_session_factory_cache: dict[str, object] = {}


def default_db_url() -> str:
    """studio 侧默认数据库 URL：环境变量优先，否则复用主应用的 sqlite 文件。"""
    url = (os.environ.get("YIMU_DB_URL") or "").strip()
    if url:
        return url
    # 本文件在 <repo>/studio/membership/ 下，向上三级即仓库根
    root = Path(__file__).resolve().parent.parent.parent
    return "sqlite:///" + str(root / "data" / "mediaflow.db")


def get_db_session(db_url: str | None = None):
    """取一个 SQLAlchemy Session（调用方负责 close；建表幂等）。"""
    from ..db import get_engine, get_session_factory, init_db

    url = db_url or default_db_url()
    fac = _session_factory_cache.get(url)
    if fac is None:
        if url.startswith("sqlite:///"):
            parent = os.path.dirname(os.path.abspath(url[len("sqlite:///"):]))
            if parent:
                os.makedirs(parent, exist_ok=True)
        engine = get_engine(url)
        init_db(engine)  # 幂等建表（含 quota_counters）
        fac = get_session_factory(engine)
        _session_factory_cache[url] = fac
    return fac()
