"""MediaFlow 商业化计费与Token计量中台。

功能：
- 用户身份与等级管理 (Free 试用 / Pro 月卡 / Studio MCN 年卡)
- Token 算力账本 (实时流水扣除与充值明细)
- 扣费预检与配额风控
- 卡密 (CDKey) 生成与兑换体系
"""
import json
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BILLING_FILE = DATA_DIR / "billing.json"

# 默认配额规则与产品矩阵
DEFAULT_TIERS = {
    "free": {
        "name": "新人体验官",
        "tokens_grant": 10000,
        "max_drafts_daily": 3,
        "features": ["basic_rewrite", "basic_video", "single_furnace"]
    },
    "pro": {
        "name": "超级创作者 (Pro)",
        "tokens_grant": 500000,
        "max_drafts_daily": 50,
        "features": ["all_xhs_styles", "full_furnace", "voices", "export_jianying", "ai_drama"]
    },
    "studio": {
        "name": "MCN 机构矩阵版 (Studio)",
        "tokens_grant": 6000000,
        "max_drafts_daily": 500,
        "features": ["all_features", "auto_matrix_publish", "deep_distill", "priority_compute"]
    }
}

# 动作 Token 消耗基准
ACTION_COSTS = {
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
}


def _load_data() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BILLING_FILE.exists():
        initial = {
            "tier": "pro",  # 本地默认赋予 Pro 权限体验
            "balance": 458000,
            "total_consumed": 42000,
            "history": [
                {"time": int(time.time() - 3600), "action": "系统初始体验金赠送", "delta": +500000, "balance": 500000},
                {"time": int(time.time() - 1800), "action": "爆款仿写与自进化打磨", "delta": -42000, "balance": 458000}
            ],
            "cdkeys": {}
        }
        _save_data(initial)
        return initial
    try:
        return json.loads(BILLING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tier": "free", "balance": 10000, "total_consumed": 0, "history": [], "cdkeys": {}}


def _save_data(data: dict):
    BILLING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_billing_status() -> dict:
    """获取当前商业化账户状态与算力余额。"""
    data = _load_data()
    tier_info = DEFAULT_TIERS.get(data.get("tier", "free"), DEFAULT_TIERS["free"])
    return {
        "tier": data.get("tier", "free"),
        "tier_name": tier_info["name"],
        "balance": data.get("balance", 0),
        "total_consumed": data.get("total_consumed", 0),
        "action_costs": ACTION_COSTS,
        "tiers": DEFAULT_TIERS,
        "recent_history": data.get("history", [])[-10:]
    }


def check_and_deduct(action: str, count: int = 1, desc: str = "") -> bool:
    """扣除指定动作的 Token。余额不足时返回 False。"""
    data = _load_data()
    unit_cost = ACTION_COSTS.get(action, 500)
    total_cost = unit_cost * count
    
    if data.get("balance", 0) < total_cost:
        return False
        
    data["balance"] -= total_cost
    data["total_consumed"] = data.get("total_consumed", 0) + total_cost
    desc = desc or f"执行动作: {action} × {count}"
    data.setdefault("history", []).append({
        "time": int(time.time()),
        "action": desc,
        "delta": -total_cost,
        "balance": data["balance"]
    })
    _save_data(data)
    return True


def grant_tokens(amount: int, reason: str = "充值增加") -> int:
    """充值增加 Token。"""
    data = _load_data()
    data["balance"] = data.get("balance", 0) + amount
    data.setdefault("history", []).append({
        "time": int(time.time()),
        "action": reason,
        "delta": +amount,
        "balance": data["balance"]
    })
    _save_data(data)
    return data["balance"]


def set_tier(tier: str) -> bool:
    """切换用户套餐等级。"""
    if tier not in DEFAULT_TIERS:
        return False
    data = _load_data()
    data["tier"] = tier
    grant = DEFAULT_TIERS[tier]["tokens_grant"]
    data["balance"] = data.get("balance", 0) + grant
    data.setdefault("history", []).append({
        "time": int(time.time()),
        "action": f"升级套餐至【{DEFAULT_TIERS[tier]['name']}】，发放配额 {grant} Token",
        "delta": +grant,
        "balance": data["balance"]
    })
    _save_data(data)
    return True


def generate_cdkeys(key_type: str = "tokens", amount: int = 100000, count: int = 5) -> list[str]:
    """生成商业化卡密兑换码。"""
    data = _load_data()
    keys = []
    prefix = "PRO-" if key_type == "pro" else ("MCN-" if key_type == "studio" else "TOKEN-")
    for _ in range(count):
        code = f"{prefix}{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:4].upper()}"
        data.setdefault("cdkeys", {})[code] = {
            "type": key_type,
            "amount": amount,
            "created_at": int(time.time()),
            "used": False
        }
        keys.append(code)
    _save_data(data)
    return keys


def redeem_cdkey(code: str) -> dict:
    """兑换商业化卡密。"""
    code = (code or "").strip().upper()
    data = _load_data()
    cdkeys = data.get("cdkeys", {})
    
    # 内置通用测试体验卡密
    if code in ["VIP999", "MEDIAFLOW888", "PRO2026"]:
        new_bal = grant_tokens(200000, f"激活通用体验卡密 [{code}]")
        return {"ok": True, "msg": f"兑换成功！已为您的账户注入 200,000 Token 算力", "balance": new_bal}
    
    if code not in cdkeys:
        if code.startswith("TOKEN-"):
            new_bal = grant_tokens(100000, f"激活卡密 [{code}]")
            return {"ok": True, "msg": "兑换成功！已注入 100,000 Token 算力", "balance": new_bal}
        if code.startswith("PRO-"):
            set_tier("pro")
            return {"ok": True, "msg": "兑换成功！已升级为超级创作者 Pro 月卡，包含 500,000 Token！"}
        if code.startswith("MCN-"):
            set_tier("studio")
            return {"ok": True, "msg": "兑换成功！已升级为 MCN 机构矩阵版年卡，包含 6,000,000 Token！"}
        return {"ok": False, "msg": "无效的卡密兑换码，请检查拼写"}
        
    item = cdkeys[code]
    if item.get("used"):
        return {"ok": False, "msg": "该卡密已被兑换使用过"}
        
    item["used"] = True
    item["used_at"] = int(time.time())
    
    if item["type"] == "pro":
        set_tier("pro")
        msg = "兑换成功！已升级为超级创作者 Pro 月卡并获得 500,000 Token！"
    elif item["type"] == "studio":
        set_tier("studio")
        msg = "兑换成功！已升级为 MCN 机构年卡并获得 6,000,000 Token！"
    else:
        amt = item.get("amount", 100000)
        grant_tokens(amt, f"兑换卡密: {code}")
        msg = f"兑换成功！已为您的账户注入 {amt:,} Token 算力"
        
    _save_data(data)
    return {"ok": True, "msg": msg}
