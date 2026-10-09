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
#
# R2-1：档位额度与动作单价的**唯一真源**已收敛到 studio/pricing.py。
# 这里保留同名常量仅为兼容既有调用方（billing_adapter / web/admin.py），
# 禁止在此另立一套数字——改价只能改 studio/pricing.py。
from studio.pricing import (  # noqa: E402  (放在常量区，保持历史导入位置不变)
    ACTION_COSTS,
    DEFAULT_TIERS,
    TIER_CREDITS,
)


def _load_data() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BILLING_FILE.exists():
        # ⭐ R2-3：本JSON 账本已废弃（全局单例，多用户互相覆盖），
        #   余额真源是 memberships.credits_total - credits_used。
        #   这里仅保留「首次运行时建一个空壳文件」以兼容旧读取路径。
        initial = {
            "tier": "free",
            "balance": 0,
            "total_consumed": 0,
            "history": [],
            "cdkeys": {}
        }
        _save_data(initial)
        return initial
    try:
        return json.loads(BILLING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tier": "free", "balance": 0, "total_consumed": 0, "history": [], "cdkeys": {}}


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
    """兑换商业化卡密。

    ⭐ 安全红线：只认cdkeys 表内精确匹配且未使用的卡密。
       历史版本存在两类万能后门，均已下线，不得 reintroduce：
       1) 硬编码通用体验码（VIP999 / MEDIAFLOW888 / PRO2026）——任何人可白嫖额度；
       2) 按前缀放行（TOKEN- / PRO- / MCN- 开头即认）——可自行编造卡密，
          且完全绕过 used 防重放，同一张"卡"可无限次兑换。
       需要发放额度请走 generate_cdkeys 正式生成。
    """
    code = (code or "").strip().upper()
    data = _load_data()
    cdkeys = data.get("cdkeys", {})

    # ⭐ 精确匹配：不存在（含伪造前缀码）一律判无效，不做任何额度动作
    if code not in cdkeys:
        return {"ok": False, "msg": "无效的卡密兑换码，请检查拼写"}

    item = cdkeys[code]
    if item.get("used"):
        return {"ok": False, "msg": "该卡密已被兑换使用过"}

    item["used"] = True
    item["used_at"] = int(time.time())

    #⭐ 先把「已核销」落盘，再发放额度。
    #   grant_tokens / set_tier 内部各自 _load_data + _save_data；若把
    #   _save_data(data) 放在它们之后，会用这份核销前的内存快照覆盖掉
    #   刚发放的额度（历史 bug：兑换提示成功但余额纹丝不动）。
    _save_data(data)

    if item["type"] == "pro":
        set_tier("pro")
        msg = "兑换成功！已升级为超级创作者 Pro 月卡并获得 500,000 Token！"
    elif item["type"] == "studio":
        set_tier("studio")
        msg = "兑换成功！已升级为 MCN 机构年卡并获得 6,000,000 Token！"
    else:
        amt = item.get("amount", 100000)
        new_bal = grant_tokens(amt, f"兑换卡密: {code}")
        msg = f"兑换成功！已为您的账户注入 {amt:,} Token 算力"
        return {"ok": True, "msg": msg, "balance": new_bal}

    return {"ok": True, "msg": msg}
