# SPDX-License-Identifier: BUSL-1.1
"""⭐ 唯一计价真源：credits 单价、动作单价、档位额度、token 换算。

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
    （注：R2 任务书里写的是 9000，实际按 ACTION_COSTS 逐项相加是 12000——
      9000 漏算了配音或生图的一项。此处以代码为准，见 FULL_DRAMA_CREDITS。）
    而 Free 档周期总额度仅 3000 credits —— **连一条都跑不完**（只够 1/4）。
    这正是 R2-7 把 Free 档「完整短剧」缩减为「单镜头体验」的依据：
    承诺必须与额度自洽，否则就是账本设计的失败。
    （真实上游成本约 2~8 元/条，credits 售价远高于成本，毛利成立。）

⚠️ 历史漏钱口子（已修复，勿回退）：
   core/auth.py 注册曾硬编码 quota_max=500000，按 0.05 元/篇折算≈ 25000 元白送。
   现已改为引用本模块的档位额度常量。
"""
from __future__ import annotations

import json
import math
import os

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
]

# ---------------------------------------------------------------------------
# 1) 基础汇率
# ---------------------------------------------------------------------------

#: ⭐ 1 credit 值多少「分」。1 → 1 credit = 0.01 元。
#: 注意：这不是 cost_cents 的换算率（那个恒为 1），而是 credits 的**售价**。
CREDIT_PRICE_CENTS = 1

#: 兼容旧名：1 credit 折合多少分。与 CREDIT_PRICE_CENTS 同义，禁止再出现 100。
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
    """⭐ token 数 → credits，**统一 per-1k 口径**。

    credits = ceil(tokens / 1000 × per_1k)，非零消费至少 1 credit（0 token 则为 0）。

    - 与 gateway/config.py 的同名函数口径完全一致（那边保留一份是为了
      网关模块自治，实际实现已收敛到本函数，避免两处漂移）。
    - cost_cents 与 credits 1:1 对应（整数，杜绝浮点误差）。
    """
    if tokens <= 0 or per_1k <= 0:
        return 0
    return max(1, math.ceil(tokens / 1000 * per_1k))


# ---------------------------------------------------------------------------
# 2b) 模型单价表（每 1k tokens 的 credits）
# ---------------------------------------------------------------------------
#
# ⭐ R2-2：这张表原先只存在于 gateway/config.py，导致「同一模型走
#   llm_metering 与走 /v1」两条路径需要各查一份单价，很容易漂移成
#   「一条按 token 数扣、一条按 per-1k 扣」。现收敛到本模块唯一真源，
#   gateway/config.py 改为转调本表，两条路径共用同一份数据。

#: 模型 → 每 1k tokens 的 credits（input / output分开计价）
DEFAULT_MODEL_PRICING: dict[str, dict[str, int]] = {
    # 网关别名与内置测试模型
    "yimu-auto": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-chat": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-reasoner": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-vision": {"input_credits_per_1k": 2, "output_credits_per_1k": 4},
    "yimu-embed": {"input_credits_per_1k": 1, "output_credits_per_1k": 0},
    "yimu-image": {"input_credits_per_1k": 2, "output_credits_per_1k": 50},
    # 常见上游模型（可通过 YIMU_PRICING 覆盖）
    "gpt-4o": {"input_credits_per_1k": 5, "output_credits_per_1k": 15},
    "gpt-4o-mini": {"input_credits_per_1k": 1, "output_credits_per_1k": 2},
    "deepseek-chat": {"input_credits_per_1k": 2, "output_credits_per_1k": 3},
    "deepseek-reasoner": {"input_credits_per_1k": 4, "output_credits_per_1k": 8},
    "qwen-max": {"input_credits_per_1k": 4, "output_credits_per_1k": 12},
    "glm-4": {"input_credits_per_1k": 5, "output_credits_per_1k": 5},
    "doubao-pro-32k": {"input_credits_per_1k": 2, "output_credits_per_1k": 6},
    "claude-3-5-sonnet": {"input_credits_per_1k": 6, "output_credits_per_1k": 30},
}

#: 未知模型的兜底单价（与 gateway/routers_openai.py 历史兜底一致）
_FALLBACK_RATES: dict[str, int] = {"input_credits_per_1k": 2, "output_credits_per_1k": 4}


def load_model_pricing() -> dict[str, dict[str, int]]:
    """合并默认模型单价与 YIMU_PRICING 环境变量覆盖。

    环境变量格式错误时沿用默认单价，不阻断启动（与历史行为一致）。
    """
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
            pass  # 格式错误时沿用默认单价，不阻断启动
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
    """一次 LLM 调用 → (input_credits, output_credits)。

    ⭐ 这是「两条计费路径」共同的换算入口：
       - studio/llm_metering.record_llm_call（官方通道直扣）
       - gateway/limits.write_ledger_rows（/v1 网关调用）
       两者都调本函数，因此同一模型同一 token 数必然扣出同样的 credits。
    """
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

#: 未知动作的兜底单价（与历史 check_and_deduct 的 .get(action, 500) 保持一致）
_DEFAULT_ACTION_COST = 500


def action_cost(action: str) -> int:
    """取某动作的单价；未知动作按 500 计。"""
    return ACTION_COSTS.get(action, _DEFAULT_ACTION_COST)


# ---------------------------------------------------------------------------
# 4) 档位额度（每周期授信 credits）
# ---------------------------------------------------------------------------
#
# ⚠️ 为什么从 10000 / 500000 / 6000000 下调到 3000 / 30000 / 200000：
#   原额度与「售价」完全脱钩。按 1 credit = 0.01 元：
#     Free   10000 credits = 100 元  ← 注册白送，等于每人送 100 元
#     Pro   500000 credits = 5000 元 ← 送5000 元
#     Studio 6000000 credits = 60000 元 ← 送 6 万元
#   core/auth.py 注册即送 quota_max=500000（≈25000 元口径），是比卡密后门
#   更隐蔽的漏钱口子。下调后：
#     Free   3000 credits = 30 元   （约 1/3 条短剧，够跑单镜头体验）
#     Pro   30000 credits = 300 元  （约 3 条短剧/月）
#     Studio 200000 credits = 2000 元（约 22 条短剧/月）

#: 档位 → 每周期授信额度（credits）
TIER_CREDITS: dict[str, int] = {
    "free": 3000,
    "pro": 30000,
    "studio": 200000,
}

#: 档位 → 订阅周期天数（配合 memberships.period_end 的周期重置，见 R2-6）
TIER_PERIOD_DAYS: dict[str, int] = {
    "free": 30,     # 免费额度按月刷新
    "pro": 30,      # Pro 月卡
    "studio": 365,  # Studio 年卡
}


def tier_credits(tier: str) -> int:
    """取某档位每周期授信额度；未知档位按 free 处理。"""
    return TIER_CREDITS.get((tier or "free").lower(), TIER_CREDITS["free"])


def tier_period_days(tier: str) -> int:
    """取某档位的周期天数；未知档位按 free 处理。"""
    return TIER_PERIOD_DAYS.get((tier or "free").lower(), TIER_PERIOD_DAYS["free"])


#: ⭐ 一条完整 8 步短剧的真实消耗（credits）：
#:   drama_decompose 1000 + drama_image 4×1000 + drama_render 5000 + drama_tts 4×500
FULL_DRAMA_CREDITS = (
    ACTION_COSTS["drama_decompose"]
    + ACTION_COSTS["drama_image"] * 4
    + ACTION_COSTS["drama_render"]
    + ACTION_COSTS["drama_tts"] * 4
)

# ---------------------------------------------------------------------------
# 5) 兼容层：DEFAULT_TIERS（billing_adapter / core.billing 的历史结构）
# ---------------------------------------------------------------------------
#
# 结构与旧 core/billing.py 的 DEFAULT_TIERS 保持一致（name / tokens_grant /
# max_drafts_daily / features），其中 tokens_grant 改为从 TIER_CREDITS 取值，
# 保证「档位额度」在本模块是唯一真源。

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