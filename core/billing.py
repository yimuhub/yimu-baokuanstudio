# SPDX-License-Identifier: BUSL-1.1
"""MediaFlow 商业化计费中台（兼容层）—— ⭐ R2-3 账本收敛后的转发层。

===========================================================================
R2-3：为什么本文件不再自己记账
===========================================================================
历史实现用 ``data/billing.json`` 作唯一账本，``_load_data/_save_data`` 是
**进程级全局单例**，带来两个硬伤：

1. **多用户互相覆盖**：余额、tier、流水全在一个 JSON 里，任何一次写入都是
   「读全量→改一个字段→写全量」。A 充值与 B 消费并发时后写者覆盖前者，
   丢的是已经发给用户的额度（直接资损）。
2. **余额不归属到人**：所有用户共用一个 balance，谁在用都记在同一笔账上，
   无法对账、无法退款、无法风控。

现在全仓**只有一套账本**：
    -余额：``memberships.credits_total - memberships.credits_used``（按 user_id）
    - 明细：``ledger`` 表（只 INSERT，不可改）
    - 卡密：``invites`` 表（原子核销，防重放）
实现都在 studio/ 侧，本文件仅保留对外签名做转发。

历史 JSON 余额如何处理：见 ``migrate_legacy_json_balance``——
**必须由人工事先确认余额合理后再手动调用**，任何启动路径都不得自动执行。

⚠️ 为什么不做自动迁移：本地 ``data/billing.json`` 里往往躺着冒烟测试
   灌进去的巨额余额（本机实测 balance=999999 credits ≈ 9999.99 元）。
   自动并入 memberships 等于白送近万元额度——比任何后门都直接。
   迁移函数因此保持「手动调用」语义，且并入后会写回 0 防止重复并入。

⚠️ 卡密安全红线（R1 建立，R2-3 保留，不得 reintroduce）：
   卡密只认``invites`` 表内精确匹配且未使用的记录。不认任何万能码
   （VIP999 / MEDIAFLOW888 / PRO2026），不按前缀放行（TOKEN- / PRO- / MCN-），
   也不用 used 标记之外的任何旁路。需要发放额度请走 generate_cdkeys 正式生成。
"""
from __future__ import annotations
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BILLING_FILE = DATA_DIR / "billing.json"

# R2-1：档位额度与动作单价的**唯一真源**在 studio/pricing.py。
# 这里保留同名常量仅为兼容既有调用方，禁止在此另立一套数字。
from studio.pricing import (  # noqa: E402  (放在常量区，保持历史导入位置不变)
    ACTION_COSTS,
    DEFAULT_TIERS,
    TIER_CREDITS,
)

__all__ = [
    "ACTION_COSTS", "DEFAULT_TIERS",
    "get_billing_status", "check_and_deduct", "grant_tokens", "set_tier",
    "generate_cdkeys", "redeem_cdkey",
    "DATA_DIR", "BILLING_FILE", "migrate_legacy_json_balance",
]


# ---------------------------------------------------------------------------
# 会话辅助：把无 db 参数的旧签名桥接到 studio 侧
# ---------------------------------------------------------------------------

def _adapter():
    """懒加载 studio.billing_adapter（避免导入期循环依赖）。"""
    from studio import billing_adapter

    return billing_adapter


def _session():
    """开一个 studio DB session（调用方负责 close）。"""
    return _adapter()._web_session()


def _resolve(db, user_id: str | None = None) -> tuple[str, str]:
    """解析 (tenant_id, user_id)。

    显式给了 user_id 就用它；否则按「本地单机模式」取默认租户的首个用户
    （与历史 JSON 单例的语义对应：单机只有一个账户）。
    """
    adapter = _adapter()
    if user_id:
        return adapter.WEB_TENANT_NAME, str(user_id)
    tenant, user = adapter.get_default_billing_user(db)
    tenant_id = tenant.id if tenant is not None else adapter.WEB_TENANT_NAME
    uid = user.id if user is not None else "u-admin"
    return tenant_id, uid


# ---------------------------------------------------------------------------
# 遗留 JSON 迁移（一次性，把旧余额并入 memberships）
# ---------------------------------------------------------------------------

def migrate_legacy_json_balance() -> int:
    """把 data/billing.json 里的遗留余额并入 memberships，返回并入的额度。

    ⚠️ **手动调用，勿接入任何启动路径**：本地 JSON 里常是冒烟测试灌的
    巨额余额（本机实测 999999 credits ≈ 9999.99 元），自动并入等于白送近万元。
    多用户场景下这笔钱归属「本地单机账户」——历史 JSON 本就没有用户维度。
    并入后写回 0，避免重复并入。
    """
    data = _load_data()
    legacy = int(data.get("balance", 0) or 0)
    if legacy <= 0:
        return 0
    db = _session()
    try:
        tenant_id, user_id = _resolve(db)
        adapter = _adapter()
        before = adapter.get_billing_status(db, tenant_id, user_id)["balance"]
        adapter.grant_tokens(db, tenant_id, user_id, legacy, "迁移历史 JSON 余额")
        after = adapter.get_billing_status(db, tenant_id, user_id)["balance"]
        # 归零，避免下次重复并入
        data["balance"] = 0
        _save_data(data)
        return after - before
    except Exception:
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 遗留 JSON 读写（仅用于迁移与排障，不再参与计费）
# ---------------------------------------------------------------------------

def _load_data() -> dict:
    """读遗留 JSON账本。⚠️ 已不参与计费，仅供迁移/排障使用。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BILLING_FILE.exists():
        initial = {"tier": "free", "balance": 0, "total_consumed": 0,
                   "history": [], "cdkeys": {}}
        _save_data(initial)
        return initial
    try:
        return json.loads(BILLING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tier": "free", "balance": 0, "total_consumed": 0,
                "history": [], "cdkeys": {}}


def _save_data(data: dict) -> None:
    """写遗留 JSON。⚠️ 已不参与计费，调用它不会影响用户余额。"""
    BILLING_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 对外 API（全部转发到 studio 侧账本）
# ---------------------------------------------------------------------------

def get_billing_status(user_id: str | None = None) -> dict:
    """获取当前商业化账户状态与算力余额（读 memberships + ledger）。"""
    db = _session()
    try:
        tenant_id, uid = _resolve(db, user_id)
        return _adapter().get_billing_status(db, tenant_id, uid)
    finally:
        db.close()


def check_and_deduct(action: str, count: int = 1, desc: str = "",
                     user_id: str | None = None) -> bool:
    """扣除指定动作的额度。余额不足返回 False。

    ⭐ R2-3：先原子扣 memberships.credits_used，成功后才写 ledger 行；
       扣费失败不产生任何账本行（防「消费了但没收费」）。
    """
    db = _session()
    try:
        tenant_id, uid = _resolve(db, user_id)
        return _adapter().check_and_deduct(
            db, tenant_id, uid, action, count, desc)
    finally:
        db.close()


def grant_tokens(amount: int, reason: str = "充值增加",
                 user_id: str | None = None) -> int:
    """充值增加额度，返回充值后余额。"""
    db = _session()
    try:
        tenant_id, uid = _resolve(db, user_id)
        return _adapter().grant_tokens(db, tenant_id, uid, amount, reason)
    finally:
        db.close()


def set_tier(tier: str, user_id: str | None = None) -> bool:
    """切换用户套餐等级并按档位发放配额。"""
    if tier not in DEFAULT_TIERS:
        return False
    db = _session()
    try:
        tenant_id, uid = _resolve(db, user_id)
        return _adapter().set_tier(db, tenant_id, uid, tier)
    finally:
        db.close()


#:卡密默认面额（credits）。取免费档额度，避免在签名里硬编码额度数字。
DEFAULT_CDKEY_AMOUNT = TIER_CREDITS["free"]


def generate_cdkeys(key_type: str = "tokens",
                    amount: int = DEFAULT_CDKEY_AMOUNT,
                    count: int = 5) -> list[str]:
    """生成商业化卡密兑换码（写入 invites 表，原子核销）。"""
    db = _session()
    try:
        tenant_id, _uid = _resolve(db)
        return _adapter().generate_cdkeys(
            db, tenant_id, "system", key_type=key_type, amount=amount, count=count)
    finally:
        db.close()


def redeem_cdkey(code: str, user_id: str | None = None) -> dict:
    """兑换商业化卡密。

    ⭐ 安全红线（R1 建立，R2-3 保留）：只认 ``invites`` 表内精确匹配且未使用的
       卡密。历史版本存在两类万能后门，均已下线，**不得 reintroduce**：
       1) 硬编码通用体验码（VIP999 / MEDIAFLOW888 / PRO2026）——任何人可白嫖额度；
       2) 按前缀放行（TOKEN- / PRO- / MCN- 开头即认）——可自行编造卡密，
          且完全绕过 used 防重放，同一张「卡」可无限次兑换。
       需要发放额度请走 generate_cdkeys 正式生成。

    R2-3：核销与发放同生共死——发放失败会把卡密退还用户（见 billing_adapter）。
    """
    adapter = _adapter()
    db = _session()
    try:
        tenant_id, uid = _resolve(db, user_id)
        res = adapter.redeem_cdkey(db, tenant_id, uid, code)
        if not res.get("ok"):
            return res
        # 兑换成功后按实际档位回填文案（不再混用「Token 算力」旧说法）
        try:
            st = adapter.get_billing_status(db, tenant_id, uid)
            tier_name = DEFAULT_TIERS.get(st.get("tier", "free"),
                                          DEFAULT_TIERS["free"])["name"]
            res["msg"] = f"兑换成功！账户现有额度 {st.get('balance', 0):,} 点" \
                         f"（{tier_name}）。可以通过「设置 - 会员与额度」查看明细。"
        except Exception:
            pass
        return res
    finally:
        db.close()
