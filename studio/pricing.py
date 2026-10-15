# SPDX-License-Identifier: BUSL-1.1
"""⭐ 唯一计价真源：credits 单价、动作单价、档位额度、token 换算与超管动态定价中心。

===========================================================================
口径表（改动本文件前必读；口径只能改这里，禁止在其他模块另立一套）
===========================================================================

【1】基础汇率
    CREDIT_PRICE_CENTS = 1
    即 **1 credit = 1 分 = 0.01 元**。

【2】单位约定（全仓唯一）
    - credits：用户可消费的「算力点数」，整数。余额 = credits_total - credits_used。
    - cost_cents：**语义就是 credits**（整数），不是人民币分。
      历史遗留命名，见R2-4：曾有三套语义（点数 / 1 credit=1 cent / 1 credit=100 cent）
      混写同一列，导致任何 SUM(cost_cents) 都得出无意义数字。现已统一为
      「cost_cents 列里存的就是 credits 点数」，1:1 对应，列名保留只为兼容旧库。
    - 人民币只在「售价展示」时出现：yuan = credits * CREDIT_PRICE_CENTS / 100。

【3】动作单价（credits，非 token）
    rewrite=800 / drama_render=5000 …… 见 ACTION_COSTS。
    动作计费与 token 计费是**两套独立口径**，各自单位都是 credits：
      - 动作计费：一次操作扣固定 credits（与 token 数无关）。
      - token 计费：按 credits_for_tokens() 换算，**统一走 per-1k**。

【4】为什么 token 计费统一用 per-1k，而不是「1 token = 1 credit」
    per-1k 可与上游真实成本逐项对账（上游也按 1k 报价），是唯一可核对的单位；
    「1 token = 1 credit」只是打了折的直觉，无法解释成本。
    因此 **禁止任何模块再把 total_tokens 直接当 credits 扣**（R2-2 已修正）。

【5】一条完整短剧的真实消耗（credits）
    分镜解构 1000 + 生图 4×1000 + 渲染 5000 + 配音 4×500 = **12000 credits ≈ 120 元**
    而 Free 档周期总额度仅 3000 credits —— **连一条都跑不完**（只够 1/4）。

【6】超级管理员后台动态定价（V10.1 / Cloud V1.0 新增）
    支持超级管理员在后台自主设定各套餐价格（如将 Pro 设定为 99 元或 300 元）、
    授信算力额度、有效周期天数与权益说明，持久化存储于 data/pricing_config.json，
    前后端所有弹窗、个人中心、价格页与下单接口统一实时读取同一份真源，彻底消除价格不一致问题。
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path

__all__ = [
    "CREDIT_PRICE_CENTS",
    "CENTS_PER_CREDIT",
    "credits_to_yuan",
    "yuan_to_credits",
    "credits_for_tokens",
    "credits_for_call",
    "rate_for_model",
    "DEFAULT_MODEL_PRICING",
    "load_model_pricing",
    "ACTION_COSTS",
    "DEFAULT_TIERS",
    "TIER_CREDITS",
    "TIER_PERIOD_DAYS",
    "tier_credits",
    "tier_period_days",
    "action_cost",
    "FULL_DRAMA_CREDITS",
    "GRAPHIC_POST_CREDITS",
    "PLANS",
    "FREE_PLAN",
    "plan_price_cents",
    "plan_exists",
    "plan_capacity",
    "plan_catalog",
    "upsell_options",
    "FREE_DEMO_DAILY_CALLS",
    "FREE_DEMO_MAX_OUTPUT_TOKENS",
    "get_pricing_config",
    "update_pricing_config",
    "reset_pricing_config",
    "_sync_from_disk",
]

# ---------------------------------------------------------------------------
# 1) 基础汇率
# ---------------------------------------------------------------------------

CREDIT_PRICE_CENTS = 1
CENTS_PER_CREDIT = CREDIT_PRICE_CENTS


def credits_to_yuan(credits: int) -> float:
    """credits → 人民币（元），仅用于售价展示。"""
    return round(int(credits) * CREDIT_PRICE_CENTS / 100.0, 2)


def yuan_to_credits(yuan: float) -> int:
    """人民币（元）→ credits（向上取整，宁可少收不亏本）。"""
    if yuan <= 0:
        return 0
    return int(math.ceil(yuan * 100 / CREDIT_PRICE_CENTS))


# ---------------------------------------------------------------------------
# 2) token → credits：统一 per-1k 口径
# ---------------------------------------------------------------------------

def credits_for_tokens(tokens: int, per_1k: int) -> int:
    """⭐ token 数 → credits，**统一 per-1k 口径**。"""
    if tokens <= 0 or per_1k <= 0:
        return 0
    return max(1, math.ceil(tokens / 1000 * per_1k))


# ---------------------------------------------------------------------------
# 2b) 模型单价表（每 1k tokens 的 credits）
# ---------------------------------------------------------------------------

DEFAULT_MODEL_PRICING: dict[str, dict[str, int]] = {
    "yimu-auto": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-chat": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-reasoner": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-vision": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-embed": {"input_credits_per_1k": 1, "output_credits_per_1k": 0},
    "yimu-image": {"input_credits_per_1k": 2, "output_credits_per_1k": 50},
    "gpt-4o": {"input_credits_per_1k": 5, "output_credits_per_1k": 15},
    "gpt-4o-mini": {"input_credits_per_1k": 1, "output_credits_per_1k": 2},
    "deepseek-chat": {"input_credits_per_1k": 2, "output_credits_per_1k": 3},
    "deepseek-reasoner": {"input_credits_per_1k": 4, "output_credits_per_1k": 8},
    "qwen-max": {"input_credits_per_1k": 4, "output_credits_per_1k": 12},
    "glm-4": {"input_credits_per_1k": 5, "output_credits_per_1k": 5},
    "doubao-pro-32k": {"input_credits_per_1k": 2, "output_credits_per_1k": 6},
    "claude-3-5-sonnet": {"input_credits_per_1k": 6, "output_credits_per_1k": 30},
}

_FALLBACK_RATES: dict[str, int] = {"input_credits_per_1k": 2, "output_credits_per_1k": 4}


def load_model_pricing() -> dict[str, dict[str, int]]:
    """合并默认模型单价与 YIMU_PRICING 环境变量覆盖。"""
    pricing = {k: dict(v) for k, v in DEFAULT_MODEL_PRICING.items()}
    raw = os.environ.get("YIMU_PRICING", "").strip()
    if raw:
        try:
            override = json.loads(raw)
            for model, rates in override.items():
                pricing[model] = {
                    "input_credits_per_1k": int(rates.get("input_credits_per_1k", 0)),
                    "output_credits_per_1k": int(rates.get("output_credits_per_1k", 0)),
                }
        except (ValueError, AttributeError, TypeError):
            pass
    return pricing


def rate_for_model(model: str, pricing: dict[str, dict[str, int]] | None = None) -> dict[str, int]:
    """取某模型的 per-1k 单价；未知模型走兜底价。"""
    table = load_model_pricing() if pricing is None else pricing
    return table.get(model) or dict(_FALLBACK_RATES)


def credits_for_call(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    pricing: dict[str, dict[str, int]] | None = None,
) -> tuple[int, int]:
    """一次 LLM 调用 → (input_credits, output_credits)。"""
    rates = rate_for_model(model, pricing)
    return (
        credits_for_tokens(prompt_tokens, rates["input_credits_per_1k"]),
        credits_for_tokens(completion_tokens, rates["output_credits_per_1k"]),
    )


# ---------------------------------------------------------------------------
# 3) 动作单价（credits / 次）
# ---------------------------------------------------------------------------

ACTION_COSTS: dict[str, int] = {
    "rewrite": 800,           # AI 仿写/重构
    "score": 300,             # 7维评审官打分
    "refine_single": 400,     # 外科手术单点修补
    "refine_batch": 1200,     # 外科手术批量修补
    "furnace_round": 1000,    # 自进化熔炉每轮
    "xhs_card_layout": 500,   # 小红书12套卡片排版
    "drama_decompose": 1000,  # 短剧好莱坞分镜解构
    "drama_image": 1000,      # 短剧分镜参考生图 (每张)
    "drama_tts": 500,         # 短剧情感配音 (每段)
    "drama_render": 5000,     # 全AI短剧渲染合成 (每支)
    "deep_distill": 2500,     # 深度博主音色/排版逆向蒸馏
    "draft_create": 200,      # 手动新建/导入草稿（建档本身即可计费）
}

_DEFAULT_ACTION_COST = 500


def action_cost(action: str) -> int:
    """取某动作的单价；未知动作按 500 计。"""
    return ACTION_COSTS.get(action, _DEFAULT_ACTION_COST)


# ---------------------------------------------------------------------------
# 4) 档位额度与在售套餐（支持超管后台动态设定）
# ---------------------------------------------------------------------------

_DEFAULT_TIER_CREDITS: dict[str, int] = {
    "free": 3000,
    "pro": 30000,
    "studio": 200000,
}

_DEFAULT_TIER_PERIOD_DAYS: dict[str, int] = {
    "free": 30,     # 免费额度按月刷新
    "pro": 30,      # Pro 月卡
    "studio": 365,  # Studio 年卡
}

#: 档位 → 每周期授信额度（credits）
TIER_CREDITS: dict[str, int] = dict(_DEFAULT_TIER_CREDITS)

#: 档位 → 订阅周期天数
TIER_PERIOD_DAYS: dict[str, int] = dict(_DEFAULT_TIER_PERIOD_DAYS)

#: 每自然日免费体验调用次数（官方通道 · free 档）
FREE_DEMO_DAILY_CALLS = 3

#: 单次免费体验 output tokens 上限
FREE_DEMO_MAX_OUTPUT_TOKENS = 512

#: 一条完整 8 步短剧的真实消耗（credits）
FULL_DRAMA_CREDITS = (
    ACTION_COSTS["drama_decompose"]
    + ACTION_COSTS["drama_image"] * 4
    + ACTION_COSTS["drama_render"]
    + ACTION_COSTS["drama_tts"] * 4
)

#: 一篇图文的参考消耗
GRAPHIC_POST_CREDITS = (
    ACTION_COSTS["rewrite"] + ACTION_COSTS["score"] + ACTION_COSTS["xhs_card_layout"]
)

_DEFAULT_PLANS: dict[str, dict[str, object]] = {
    "pro": {
        "code": "pro",
        "name": "超级创作者 Pro",
        "tier": "pro",
        "credits": _DEFAULT_TIER_CREDITS["pro"],
        "price_cents": _DEFAULT_TIER_CREDITS["pro"],       # 默认 300 元（30000 分），支持后台改价如 99 元
        "period_days": _DEFAULT_TIER_PERIOD_DAYS["pro"],  # 30
        "tagline": "个人创作者日更不掉链子",
        "highlights": [
            "短剧流水线、卡片排版、名家音色全部解锁",
            "图片赛马 3 候选 + Judge 优选不限次",
            "热榜 24 平台全开、TTS 三引擎",
            "导出剪映工程 / 对标平台一键分发",
        ],
    },
    "studio": {
        "code": "studio",
        "name": "MCN 机构矩阵版 Studio",
        "tier": "studio",
        "credits": _DEFAULT_TIER_CREDITS["studio"],
        "price_cents": _DEFAULT_TIER_CREDITS["studio"],       # 默认 2000 元（200000 分），支持后台自定义
        "period_days": _DEFAULT_TIER_PERIOD_DAYS["studio"],  # 365
        "tagline": "工作室 / 机构批量产能与矩阵分发",
        "highlights": [
            "Pro 全部权益，且额度为Pro 的 6.7 倍",
            "深度博主音色 / 排版逆向蒸馏",
            "账号矩阵自动发布、优先级算力",
            "适合团队共用结算",
        ],
    },
}

_DEFAULT_FREE_PLAN: dict[str, object] = {
    "code": "free",
    "name": "新人体验官 Free",
    "tier": "free",
    "credits": _DEFAULT_TIER_CREDITS["free"],
    "price_cents": 0,
    "period_days": _DEFAULT_TIER_PERIOD_DAYS["free"],
    "tagline": "先跑通单镜头，不承诺完整短剧",
    "highlights": [
        "每日 3 篇草稿额度、AI 仿写与质量评分",
        "基础排版与单轮内容打磨",
        "**跑不完一条完整短剧**（额度不足一条的 1/4）",
        "额度每 30 天刷新一次",
    ],
}

PLANS: dict[str, dict[str, object]] = copy.deepcopy(_DEFAULT_PLANS)
FREE_PLAN: dict[str, object] = copy.deepcopy(_DEFAULT_FREE_PLAN)

DEFAULT_TIERS: dict[str, dict[str, object]] = {
    "free": {
        "name": "新人体验官",
        "tokens_grant": TIER_CREDITS["free"],
        "max_drafts_daily": 3,
        "features": ["basic_rewrite", "basic_video", "single_furnace"],
    },
    "pro": {
        "name": "超级创作者 (Pro)",
        "tokens_grant": TIER_CREDITS["pro"],
        "max_drafts_daily": 50,
        "features": [
            "all_xhs_styles", "full_furnace", "voices",
            "export_jianying", "ai_drama",
        ],
    },
    "studio": {
        "name": "MCN 机构矩阵版 (Studio)",
        "tokens_grant": TIER_CREDITS["studio"],
        "max_drafts_daily": 500,
        "features": [
            "all_features", "auto_matrix_publish",
            "deep_distill", "priority_compute",
        ],
    },
}


# ---------------------------------------------------------------------------
# 4c) 动态定价配置持久化与热同步（后台自主设定 Pro / Studio 价格与额度）
# ---------------------------------------------------------------------------

def _pricing_config_path() -> Path:
    """获取动态价格配置文件路径（跟随 core.db.DATA，确保测试隔离与生产持久化兼顾）。"""
    env_p = os.environ.get("YIMU_PRICING_CONFIG_FILE", "").strip()
    if env_p:
        return Path(env_p)
    try:
        from core import db as _core_db
        return Path(_core_db.DATA) / "pricing_config.json"
    except Exception:
        return Path(__file__).resolve().parent.parent / "data" / "pricing_config.json"


def _apply_in_memory(overrides: dict | None = None) -> None:
    """将默认配置与可选的自定义覆盖同步更新到本模块内存常量（保持引用不变）。"""
    # 1. 先恢复默认值
    TIER_CREDITS.clear()
    TIER_CREDITS.update(_DEFAULT_TIER_CREDITS)
    TIER_PERIOD_DAYS.clear()
    TIER_PERIOD_DAYS.update(_DEFAULT_TIER_PERIOD_DAYS)

    FREE_PLAN.clear()
    FREE_PLAN.update(copy.deepcopy(_DEFAULT_FREE_PLAN))
    PLANS.clear()
    PLANS.update(copy.deepcopy(_DEFAULT_PLANS))

    # 2. 叠加自定义配置
    if overrides and isinstance(overrides, dict):
        plans_ov = overrides.get("plans") if isinstance(overrides.get("plans"), dict) else overrides
        for code in ("free", "pro", "studio"):
            ov = plans_ov.get(code)
            if not isinstance(ov, dict):
                continue
            target = FREE_PLAN if code == "free" else PLANS.get(code, {})
            if not target:
                continue
            if "name" in ov and str(ov["name"]).strip():
                target["name"] = str(ov["name"]).strip()
            if "tagline" in ov and ov["tagline"] is not None:
                target["tagline"] = str(ov["tagline"]).strip()
            if "highlights" in ov and isinstance(ov["highlights"], list):
                target["highlights"] = [str(x).strip() for x in ov["highlights"] if str(x).strip()]
            if "credits" in ov and ov["credits"] is not None:
                try:
                    c_val = max(0, int(ov["credits"]))
                    target["credits"] = c_val
                    TIER_CREDITS[code] = c_val
                except (ValueError, TypeError):
                    pass
            if "period_days" in ov and ov["period_days"] is not None:
                try:
                    d_val = max(1, int(ov["period_days"]))
                    target["period_days"] = d_val
                    TIER_PERIOD_DAYS[code] = d_val
                except (ValueError, TypeError):
                    pass
            if code != "free":
                if "price_cents" in ov and ov["price_cents"] is not None:
                    try:
                        target["price_cents"] = max(1, int(ov["price_cents"]))
                    except (ValueError, TypeError):
                        pass
                elif "price_yuan" in ov and ov["price_yuan"] is not None:
                    try:
                        target["price_cents"] = max(1, int(round(float(ov["price_yuan"]) * 100)))
                    except (ValueError, TypeError):
                        pass

    # 3. 同步更新 DEFAULT_TIERS 与 studio.membership.service.TIERS（若已加载）
    DEFAULT_TIERS["free"]["tokens_grant"] = TIER_CREDITS["free"]
    DEFAULT_TIERS["pro"]["tokens_grant"] = TIER_CREDITS["pro"]
    DEFAULT_TIERS["studio"]["tokens_grant"] = TIER_CREDITS["studio"]
    DEFAULT_TIERS["free"]["name"] = str(FREE_PLAN.get("name") or "新人体验官")
    DEFAULT_TIERS["pro"]["name"] = str(PLANS["pro"].get("name") or "超级创作者 (Pro)")
    DEFAULT_TIERS["studio"]["name"] = str(PLANS["studio"].get("name") or "MCN 机构矩阵版 (Studio)")

    try:
        import sys
        svc_mod = sys.modules.get("studio.membership.service")
        if svc_mod and hasattr(svc_mod, "TIERS"):
            svc_mod.TIERS["free"]["credits"] = TIER_CREDITS["free"]
            svc_mod.TIERS["pro"]["credits"] = TIER_CREDITS["pro"]
            svc_mod.TIERS["studio"]["credits"] = TIER_CREDITS["studio"]
    except Exception:
        pass


def _sync_from_disk() -> None:
    """从磁盘配置文件同步最新套餐价格与额度配置。"""
    cfg_path = _pricing_config_path()
    if not cfg_path.exists():
        _apply_in_memory(None)
        return
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        _apply_in_memory(raw)
    except Exception:
        _apply_in_memory(None)


def get_pricing_config() -> dict:
    """获取当前生效的完整套餐价格与配额配置（供超管后台读取与编辑）。"""
    _sync_from_disk()
    return {
        "plans": {
            "free": {
                **copy.deepcopy(FREE_PLAN),
                "price_yuan": 0.0,
            },
            "pro": {
                **copy.deepcopy(PLANS["pro"]),
                "price_yuan": round(int(PLANS["pro"]["price_cents"]) / 100.0, 2),
            },
            "studio": {
                **copy.deepcopy(PLANS["studio"]),
                "price_yuan": round(int(PLANS["studio"]["price_cents"]) / 100.0, 2),
            },
        },
        "credit_price_cents": CREDIT_PRICE_CENTS,
        "full_drama_credits": FULL_DRAMA_CREDITS,
    }


def update_pricing_config(updates: dict) -> dict:
    """超级管理员更新套餐价格、额度、周期或权益描述，并持久化落盘。

    支持入参格式：
      1) {"plans": {"pro": {"price_yuan": 99, "credits": 30000, ...}, "studio": {...}}}
      2) {"pro": {"price_yuan": 99, ...}, "studio": {"price_yuan": 899, ...}}
      3) 快捷字段：{"pro_price_yuan": 99, "studio_price_yuan": 899, ...}
    """
    _sync_from_disk()
    cfg_path = _pricing_config_path()
    current_saved: dict = {"plans": {}}
    if cfg_path.exists():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current_saved = loaded if "plans" in loaded else {"plans": loaded}
        except Exception:
            current_saved = {"plans": {}}
    if not isinstance(current_saved.get("plans"), dict):
        current_saved["plans"] = {}

    incoming_plans = updates.get("plans") if isinstance(updates.get("plans"), dict) else {}
    for code in ("free", "pro", "studio"):
        if code in updates and isinstance(updates[code], dict):
            incoming_plans[code] = updates[code]

    # 支持扁平快捷字段（如 pro_price_yuan / pro_credits / studio_price_yuan / studio_credits）
    for code in ("free", "pro", "studio"):
        flat_ov: dict = {}
        if f"{code}_price_yuan" in updates and updates[f"{code}_price_yuan"] is not None:
            flat_ov["price_yuan"] = float(updates[f"{code}_price_yuan"])
        if f"{code}_price_cents" in updates and updates[f"{code}_price_cents"] is not None:
            flat_ov["price_cents"] = int(updates[f"{code}_price_cents"])
        if f"{code}_credits" in updates and updates[f"{code}_credits"] is not None:
            flat_ov["credits"] = int(updates[f"{code}_credits"])
        if f"{code}_period_days" in updates and updates[f"{code}_period_days"] is not None:
            flat_ov["period_days"] = int(updates[f"{code}_period_days"])
        if f"{code}_name" in updates and updates[f"{code}_name"] is not None:
            flat_ov["name"] = str(updates[f"{code}_name"]).strip()
        if f"{code}_tagline" in updates and updates[f"{code}_tagline"] is not None:
            flat_ov["tagline"] = str(updates[f"{code}_tagline"]).strip()
        if flat_ov:
            incoming_plans.setdefault(code, {}).update(flat_ov)

    for code, ov in incoming_plans.items():
        if code not in ("free", "pro", "studio") or not isinstance(ov, dict):
            continue
        cur_p = dict(current_saved["plans"].get(code) or {})
        if "name" in ov and str(ov["name"]).strip():
            cur_p["name"] = str(ov["name"]).strip()
        if "tagline" in ov and ov["tagline"] is not None:
            cur_p["tagline"] = str(ov["tagline"]).strip()
        if "highlights" in ov:
            if isinstance(ov["highlights"], list):
                cur_p["highlights"] = [str(x).strip() for x in ov["highlights"] if str(x).strip()]
            elif isinstance(ov["highlights"], str):
                cur_p["highlights"] = [x.strip() for x in ov["highlights"].splitlines() if x.strip()]
        if "credits" in ov and ov["credits"] is not None:
            c_val = int(ov["credits"])
            if c_val < 0:
                raise ValueError(f"{code} 套餐算力额度不能为负数")
            cur_p["credits"] = c_val
        if "period_days" in ov and ov["period_days"] is not None:
            d_val = int(ov["period_days"])
            if d_val < 1:
                raise ValueError(f"{code} 套餐周期天数必须大于 0")
            cur_p["period_days"] = d_val
        if code != "free":
            if "price_cents" in ov and ov["price_cents"] is not None:
                p_cents = int(ov["price_cents"])
                if p_cents <= 0:
                    raise ValueError(f"{code} 套餐价格必须大于 0")
                cur_p["price_cents"] = p_cents
                cur_p.pop("price_yuan", None)
            elif "price_yuan" in ov and ov["price_yuan"] is not None:
                p_yuan = float(ov["price_yuan"])
                if p_yuan <= 0:
                    raise ValueError(f"{code} 套餐价格必须大于 0 元")
                cur_p["price_cents"] = int(round(p_yuan * 100))
                cur_p.pop("price_yuan", None)
        current_saved["plans"][code] = cur_p

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(current_saved, ensure_ascii=False, indent=2), encoding="utf-8")
    _apply_in_memory(current_saved)
    return get_pricing_config()


def reset_pricing_config() -> dict:
    """恢复默认套餐价格与额度配置。"""
    cfg_path = _pricing_config_path()
    if cfg_path.exists():
        try:
            cfg_path.unlink()
        except Exception:
            pass
    _apply_in_memory(None)
    return get_pricing_config()


# ---------------------------------------------------------------------------
# 4d) 对外查询函数（每次调用均实时同步最新动态定价）
# ---------------------------------------------------------------------------

def tier_credits(tier: str) -> int:
    """取某档位每周期授信额度；未知档位按 free 处理。"""
    _sync_from_disk()
    return TIER_CREDITS.get((tier or "free").lower(), TIER_CREDITS["free"])


def tier_period_days(tier: str) -> int:
    """取某档位的周期天数；未知档位按 free 处理。"""
    _sync_from_disk()
    return TIER_PERIOD_DAYS.get((tier or "free").lower(), TIER_PERIOD_DAYS["free"])


def plan_price_cents(plan_code: str) -> int:
    """取某套餐售价（分）。未知套餐返回 0，且不会抛错（避免前端传错值就 500）。"""
    _sync_from_disk()
    key = (plan_code or "").strip().lower()
    if key == "free":
        return 0
    return int(PLANS.get(key, {}).get("price_cents", 0))


def plan_exists(plan_code: str) -> bool:
    """该套餐是否可购买（free 不可购买）。"""
    return (plan_code or "").strip().lower() in PLANS


def plan_capacity(credits: int) -> dict[str, object]:
    """把 credits 额度翻译成「能跑几条短剧/ 几篇图文」，供价格页与额度墙共用。"""
    credits = max(0, int(credits))
    return {
        "credits": credits,
        "yuan": credits_to_yuan(credits),
        "dramas": credits // FULL_DRAMA_CREDITS if FULL_DRAMA_CREDITS else 0,
        "dramas_exact": round(credits / FULL_DRAMA_CREDITS, 2) if FULL_DRAMA_CREDITS else 0,
        "graphic_posts": credits // GRAPHIC_POST_CREDITS if GRAPHIC_POST_CREDITS else 0,
        "can_run_full_drama": credits >= FULL_DRAMA_CREDITS,
    }


def plan_catalog() -> list[dict]:
    """全部套餐（free + pro + studio），价格页与下单页共用。"""
    _sync_from_disk()
    out: list[dict] = []
    for src in (FREE_PLAN, PLANS["pro"], PLANS["studio"]):
        item = dict(src)
        credits = int(item["credits"])
        item["price_yuan"] = round(int(item["price_cents"]) / 100.0, 2)
        item["capacity"] = plan_capacity(credits)
        out.append(item)
    return out


def upsell_options(need_credits: int = 0, balance: int = 0) -> dict:
    """额度墙引导用：还差多少 + 哪些套餐能立刻满足（R3-4）。"""
    _sync_from_disk()
    need = max(0, int(need_credits))
    left = max(0, int(balance))
    shortfall = max(0, need - left)
    options = []
    for code in ("pro", "studio"):
        p = PLANS[code]
        credits = int(p["credits"])
        options.append({
            "code": code,
            "name": str(p["name"]),
            "credits": credits,
            "price_yuan": round(int(p["price_cents"]) / 100.0, 2),
            "covers_action": credits >= need,
            "covers_full_drama": credits >= FULL_DRAMA_CREDITS,
        })
    return {
        "need": need,
        "balance": left,
        "shortfall": shortfall,
        "free_recommend": shortfall <= left,
        "options": options,
    }


# 模块首次加载时同步一次磁盘配置
_sync_from_disk()
