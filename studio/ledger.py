# SPDX-License-Identifier: BUSL-1.1
"""统一账本写入：一幕·YIMU 爆款工作室 V8.3.3 网关调用的计量与扣费入口。

职责：
- ``calc_cost``：金丝雀纯函数，账本金额汇总（签名与算法锁死，不得改动）。
- ``write_ledger_entry``：向 ``ledger`` 表追加一行计量记录（只 INSERT）。
- ``record_call``：一次模型调用的完整记账——写 input/output 两行账本，
  并从用户会员额度中原子扣费。
- ``get_usage``：按租户汇总近 N 天的使用量（供配额检查用）。

⭐ 关键规则（违反会丢数据 / 丢钱）：
1. ``ledger`` 与 ``audit_logs`` 为只增不改表：只允许 INSERT，禁止 UPDATE / DELETE。
   账本行是计费的唯一证据，删改即等于伪造账单。
2. 所有写入必须带 ``tenant_id``：缺租户 id 的写操作直接抛错，绝不静默落地，
   否则会产生无法归属的孤儿账单。
3. 金额统一整数（credits 点数 / cost_cents 整数分）：禁止浮点参与计费，
   浮点舍入会在长期累积中造成账实不符。
4. ``record_call`` 先原子扣费、成功后再写账本行；扣费失败（余额不足）
   直接抛 ``LedgerError("额度不足")``，不产生任何账本行。顺序抉择理由：
   若先写账本再扣费、扣费失败，会留下"已消费但未收费"的账本行——
   免费调用会被永久记录为已消费，造成少收钱且无从追回；
   先扣后记的最坏情况是"已扣费但账本行未落盘"，此时异常会直接抛给上游，
   钱的流向清晰可查，不会悄悄丢钱。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update

from .db_models import Ledger, Membership, utcnow

__all__ = [
    "LedgerError",
    "calc_cost",
    "write_ledger_entry",
    "record_call",
    "get_usage",
    "record_ledger_entry",
]

# 会员扣费：由 studio/membership/service.py 提供。
# 真实签名：deduct_credits(db, tenant_id, user_id, amount) -> (ok, credits_left)，
# 单条带余额充足条件的 UPDATE 原子扣费，失败返回 (False, 剩余额度)。
# 该文件尚不存在时，回退到本模块内的原子 UPDATE 实现（见 _deduct_credits_local）。
try:
    from .membership.service import deduct_credits as _service_deduct_credits
except Exception:
    _service_deduct_credits = None  # type: ignore[assignment]

#: ledger.direction 允许的取值（与数据库 CHECK 约束一致）
_VALID_DIRECTIONS = ("input", "output")


class LedgerError(Exception):
    """账本 / 扣费领域的错误。

    ``message`` 面向用户展示：中文一句话，禁止内部黑话。
    """


def calc_cost(entries: list[dict]) -> dict:
    """金丝雀纯函数：汇总账本条目的 credits。

    ⭐ 算法锁死（tests/test_canary.py 逐字断言）：
    返回 {"total_credits": 各条 cost_credits 之和, "count": 条目数}。
    只做 sum + len：不排序、不过滤、不补默认值。
    """
    return {
        "total_credits": sum(entry["cost_credits"] for entry in entries),
        "count": len(entries),
    }


def write_ledger_entry(
    session,
    *,
    tenant_id: str,
    model: str,
    direction: str,
    tokens: int,
    cost_cents: int,
    key_id: str | None = None,
    latency_ms: int = 0,
    cached: bool = False,
) -> Ledger:
    """向账本追加一行记录。

    ⭐ 只 INSERT：本函数不做任何 UPDATE / DELETE；事务提交由调用方控制。
    """
    if not tenant_id:
        raise LedgerError("缺少租户信息，无法记账。")
    if direction not in _VALID_DIRECTIONS:
        raise LedgerError(f"记账方向不正确：{direction!r}，应为 input 或 output。")
    if not model:
        raise LedgerError("缺少模型名称，无法记账。")
    if tokens < 0 or cost_cents < 0 or latency_ms < 0:
        raise LedgerError("记账数量不能为负数。")

    entry = Ledger(
        tenant_id=tenant_id,
        key_id=key_id,
        model=model,
        direction=direction,
        tokens=tokens,
        cost_cents=cost_cents,
        latency_ms=latency_ms,
        cached=cached,
    )
    session.add(entry)
    session.flush()  # 立即落盘到当前事务，让主键与行可见；提交仍由调用方决定
    return entry


def _deduct_credits_local(session, *, user_id: str, amount: int) -> int:
    """本地原子扣费（studio/membership/service.py 尚未交付时的备选路径）。

    用一条带余额充足条件的 UPDATE 完成扣费：同一条语句里既做
    ``credits_used = credits_used + :amount``，又要求
    ``credits_total - credits_used >= :amount``，数据库层面原子，
    并发下不会出现超扣。

    返回扣费后的剩余额度。余额不足或用户没有额度记录时抛 LedgerError。
    """
    result = session.execute(
        update(Membership)
        .where(
            Membership.user_id == user_id,
            Membership.credits_total - Membership.credits_used >= amount,
        )
        .values(credits_used=Membership.credits_used + amount)
    )
    if result.rowcount == 0:
        # 受影响行数为 0：要么余额不足，要么该用户根本没有额度记录——
        # 两种情况都不能扣费，区分提示。
        exists = session.execute(
            select(Membership.id).where(Membership.user_id == user_id)
        ).first()
        if exists is None:
            raise LedgerError("该用户没有额度记录，请先开通会员或补充额度。")
        raise LedgerError("额度不足")
    session.flush()
    row = session.execute(
        select(Membership.credits_total, Membership.credits_used).where(
            Membership.user_id == user_id
        )
    ).one()
    return int(row[0]) - int(row[1])


def record_call(
    session,
    *,
    tenant_id: str,
    key_id: str | None,
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    input_credits: int,
    output_credits: int,
    latency_ms: int = 0,
) -> dict:
    """一次模型调用的完整记账：原子扣费 + 写 input/output 两行账本。

    ⭐ 执行顺序（钱的安全第一）：
    1. 先原子扣费 ``total_credits = input_credits + output_credits``；
       余额不足 → 抛 ``LedgerError("额度不足")``，账本不产生任何行。
    2. 扣费成功后再写 input / output 两行账本；
       若写账本抛错，异常直接上抛（账本缺行比悄悄少收钱更严重，
       上游必须感知并处理，事务回滚由调用方决定）。

    返回 ``{"total_credits": 本次消费点数, "credits_left": 扣费后剩余额度}``。
    """
    if not tenant_id:
        raise LedgerError("缺少租户信息，无法记账。")
    if not user_id:
        raise LedgerError("缺少用户信息，无法扣费。")
    total_credits = input_credits + output_credits
    if total_credits < 0 or input_credits < 0 or output_credits < 0:
        raise LedgerError("记账数量不能为负数。")

    # 1）先原子扣费。0 点调用不走扣费（service 对 amount<=0 直接判失败）。
    if total_credits <= 0:
        mem = session.execute(
            select(Membership.credits_total, Membership.credits_used).where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == user_id,
            )
        ).first()
        if mem is None:
            raise LedgerError("该用户没有额度记录，请先开通会员或补充额度。")
        credits_left = int(mem[0]) - int(mem[1])
    elif _service_deduct_credits is not None:
        ok, credits_left = _service_deduct_credits(
            session, tenant_id=tenant_id, user_id=user_id, amount=total_credits
        )
        if not ok:
            raise LedgerError("额度不足")
    else:
        credits_left = _deduct_credits_local(
            session, user_id=user_id, amount=total_credits
        )

    # 2）扣费成功，再写账本两行（input / output 分开计量）
    write_ledger_entry(
        session,
        tenant_id=tenant_id,
        key_id=key_id,
        model=model,
        direction="input",
        tokens=input_tokens,
        cost_cents=input_credits,
        latency_ms=latency_ms,
    )
    write_ledger_entry(
        session,
        tenant_id=tenant_id,
        key_id=key_id,
        model=model,
        direction="output",
        tokens=output_tokens,
        cost_cents=output_credits,
        latency_ms=latency_ms,
    )
    return {"total_credits": total_credits, "credits_left": int(credits_left)}


def get_usage(
    session, tenant_id: str, key_id: str | None = None, since_days: int = 30
) -> dict:
    """汇总某租户近 ``since_days`` 天的使用量（供配额检查用）。

    返回 ``{"total_credits": 累计消费点数, "calls": 调用次数}``。
    ``calls`` 按 direction='input' 的行数统计——一次调用恰好写一行 input，
    与 ``record_call`` 的写入约定对应。
    """
    if not tenant_id:
        raise LedgerError("缺少租户信息，无法查询用量。")
    cutoff = utcnow() - timedelta(days=since_days)

    base = [
        Ledger.tenant_id == tenant_id,
        Ledger.created_at >= cutoff,
    ]
    if key_id is not None:
        base.append(Ledger.key_id == key_id)

    total = session.execute(
        select(func.coalesce(func.sum(Ledger.cost_cents), 0)).where(*base)
    ).scalar()
    calls = session.execute(
        select(func.count())
        .select_from(Ledger)
        .where(*base, Ledger.direction == "input")
    ).scalar()
    return {"total_credits": int(total or 0), "calls": int(calls or 0)}


# ---------------------------------------------------------------------------
# 兼容垫片：WS-C image_forge.generate 依赖 record_ledger_entry(db_url 签名)。
# 内部委托给 write_ledger_entry（同一事务语义、只 INSERT）。
# ---------------------------------------------------------------------------

def record_ledger_entry(
    *,
    tenant_id: str,
    model: str,
    direction: str,
    tokens: int,
    cost_cents: int,
    key_id: str | None,
    db_url: str,
) -> str:
    """⭐ 向 ledger 表追加一行（只增不改），返回记录 id。

    兼容签名：自行建引擎/会话，委托 write_ledger_entry 写入。
    金额整数；缺 tenant_id 直接抛错，绝不静默落地。
    """
    from .db import get_engine, get_session_factory

    if isinstance(tokens, bool) or not isinstance(tokens, int):
        raise LedgerError("tokens 必须为整数")
    if isinstance(cost_cents, bool) or not isinstance(cost_cents, int):
        raise LedgerError("cost_cents 必须为整数（整数分），杜绝浮点")

    engine = get_engine(db_url)
    session = get_session_factory(engine)()
    try:
        entry = write_ledger_entry(
            session,
            tenant_id=tenant_id,
            model=model,
            direction=direction,
            tokens=tokens,
            cost_cents=cost_cents,
            key_id=key_id,
        )
        entry_id = str(entry.id)
        session.commit()
        return entry_id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
