# SPDX-License-Identifier: BUSL-1.1
"""计费 / 支付 / 订单 / 定价 / 计量路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

⭐ 拆分约定:
- `_a` 指向 web.admin 模块对象,凡引用 admin 模块级 helper/常量一律走 `_a.X`
  (晚绑定:测试对 web_admin.* 的 monkeypatch 继续生效);
- 族内路由保持与拆分前完全一致的注册顺序;
- admin.py 底部统一 include 本 router。"""
from __future__ import annotations

import asyncio  # noqa: F401
import base64  # noqa: F401
import hashlib  # noqa: F401
import json  # noqa: F401
import re  # noqa: F401
import time  # noqa: F401
import uuid  # noqa: F401
from pathlib import Path  # noqa: F401
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form  # noqa: E402
from fastapi.responses import (FileResponse, HTMLResponse,  # noqa: E402,F401
                               JSONResponse, Response, StreamingResponse)

from web import admin as _a  # noqa: E402  (循环安全:admin 底部才 include 本模块)

from web.draft_guard import DraftOwnerRoute  # noqa: E402  稳定类身份
router = APIRouter(route_class=DraftOwnerRoute)  # {did} 归属校验路由类

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
import time  # noqa: E402,F811

@router.get('/api/billing/status')
def billing_status(request: Request):
    u = _a.guard(request)
    from studio import billing_adapter
    db = billing_adapter._web_session()
    try:
        user_id = str((u or {}).get('id') or '')
        tenant_id = _a._web_tenant_id(db, user_id)
        if not user_id:
            tenant, u_row = billing_adapter.get_default_billing_user(db)
            tenant_id = tenant.id if tenant is not None else tenant_id
            user_id = u_row.id if u_row is not None else 'u-admin'
        return billing_adapter.get_billing_status(db, tenant_id, user_id)
    finally:
        db.close()

@router.get('/api/llm/usage')
def llm_usage(request: Request):
    """各模型服务使用量统计 + 一幕官方通道消费汇总（双轨制）。"""
    user = _a.guard(request)
    from studio import llm_metering
    from core import llm as _llm
    user_id = str((user or {}).get('id') or '')
    usage = llm_metering.get_provider_usage()
    providers = _llm.MODEL_PROVIDERS
    rows = []
    for pid, u in usage.items():
        info = providers.get(pid, {})
        rows.append({**u, 'name': info.get('name', pid), 'icon': info.get('icon', '⚡'), 'badge': info.get('badge', ''), 'billing_mode': '官方扣额度' if u.get('metered') else '自备Key·不计费'})
    rows.sort(key=lambda r: r['calls'], reverse=True)
    return {'providers': rows, 'official_summary': llm_metering.get_yimu_official_summary(user_id or None)}

@router.post('/api/billing/redeem')
async def billing_redeem(request: Request):
    u = _a.guard(request)
    body = await request.json()
    code = body.get('code') or body.get('cdkey', '')
    from studio import billing_adapter
    try:
        res = billing_adapter.redeem_cdkey_for_user(code, str((u or {}).get('id') or ''))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f'卡密兑换失败，请稍后重试: {e}')
    if isinstance(res, dict) and res.get('ok'):
        try:
            from core import analytics
            analytics.track('cdkey_redeemed', str((u or {}).get('id') or ''), {'code': (code or '')[:8]})
        except Exception:
            pass
    return res

@router.post('/api/billing/admin/gen_keys')
async def billing_gen_keys(request: Request):
    admin = _a.guard_admin(request)
    body = await request.json()
    key_type = body.get('key_type', 'tokens')
    amount = int(body.get('amount', 100000))
    count = int(body.get('count', 5))
    from studio import billing_adapter
    try:
        keys = billing_adapter.generate_cdkeys_for_actor(key_type=key_type, amount=amount, count=count, actor=str((admin or {}).get('id') or ''))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f'生成卡密失败，请稍后重试: {e}')
    return {'ok': True, 'keys': keys}

@router.get('/api/pricing')
def pricing_plans(request: Request):
    """R3-1：三档套餐与售价（价格页数据源）。

    ⭐ 登录即可见（未登录也能看价格，这是获客页），因此这里用 try 取用户：
       取不到不影响返回套餐。
    ⚠️ 返回体里的 capacity.can_run_full_drama 为False 时（Free 档），
       前端**必须如实展示「跑不完一条完整短剧」**，不得美化。
    """
    from studio import pricing as _pricing
    plans = _pricing.plan_catalog()
    payload = {'ok': True, 'plans': plans, 'full_drama_credits': _pricing.FULL_DRAMA_CREDITS, 'credit_price_cents': _pricing.CREDIT_PRICE_CENTS}
    u = _a.get_current_user(request)
    if u:
        try:
            payload['current'] = {'user_id': _a._current_user_id(u), 'tier': str(u.get('plan') or 'free')}
        except Exception:
            pass
    return payload

@router.get('/api/admin/pricing')
def admin_get_pricing(request: Request):
    """超级管理员查询当前套餐价格与配额配置。"""
    _a.guard_admin(request)
    from studio import pricing as _pricing
    cfg = _pricing.get_pricing_config()
    return {'ok': True, **cfg, 'catalog': _pricing.plan_catalog()}

@router.put('/api/admin/pricing')
@router.post('/api/admin/pricing')
async def admin_update_pricing(request: Request):
    """超级管理员在后台自主设定 Pro / Studio / Free 套餐价格、算力额度与有效期，并记录审计日志。"""
    admin = _a.guard_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from studio import pricing as _pricing
    try:
        updated = _pricing.update_pricing_config(body if isinstance(body, dict) else {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f'价格配置保存失败: {e}')
    db = _a._r3_session()
    try:
        from studio.db_models import AuditLog, new_id, utcnow
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(admin))
        db.add(AuditLog(id=new_id(), tenant_id=str(tenant_id), actor=_a._current_user_id(admin) or 'u-admin', action='pricing.update', target='pricing:plans', detail={'pro_price_yuan': updated['plans']['pro']['price_yuan'], 'pro_credits': updated['plans']['pro']['credits'], 'studio_price_yuan': updated['plans']['studio']['price_yuan'], 'studio_credits': updated['plans']['studio']['credits'], 'free_credits': updated['plans']['free']['credits']}, created_at=utcnow()))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
    return {'ok': True, 'msg': '套餐价格与配额配置已更新并全局生效', **updated, 'catalog': _pricing.plan_catalog()}

@router.post('/api/admin/pricing/reset')
def admin_reset_pricing(request: Request):
    """超级管理员一键恢复默认套餐价格配置。"""
    admin = _a.guard_admin(request)
    from studio import pricing as _pricing
    updated = _pricing.reset_pricing_config()
    db = _a._r3_session()
    try:
        from studio.db_models import AuditLog, new_id, utcnow
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(admin))
        db.add(AuditLog(id=new_id(), tenant_id=str(tenant_id), actor=_a._current_user_id(admin) or 'u-admin', action='pricing.reset', target='pricing:plans', detail={'reset': True}, created_at=utcnow()))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
    return {'ok': True, 'msg': '已恢复默认套餐价格配置', **updated, 'catalog': _pricing.plan_catalog()}

@router.get('/api/billing/pay/channels')
def billing_pay_channels(request: Request):
    """R10：列出当前可用的支付渠道（含沙箱与线下核销）。"""
    _a.guard(request)
    from studio.membership import payments
    return {'ok': True, 'channels': payments.available_channels()}

@router.post('/api/billing/pay/create')
async def billing_pay_create(request: Request):
    """R10：为本人待支付订单生成渠道收银台链接（sandbox/xunhu/stripe）。"""
    u = _a.guard(request)
    body = await request.json()
    order_id = str((body or {}).get('order_id') or '').strip()
    channel = str((body or {}).get('channel') or '').strip().lower()
    if not order_id:
        raise HTTPException(400, '缺少 order_id')
    from studio.membership import payments
    db = _a._r3_session()
    try:
        user_id = _a._current_user_id(u)
        tenant_id = _a._web_tenant_id(db, user_id)
        r = payments.create_payment(db, tenant_id, user_id, order_id, channel)
    except HTTPException:
        db.rollback()
        raise
    except RuntimeError as e:
        db.rollback()
        raise HTTPException(502, str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f'创建支付失败: {e}')
    finally:
        db.close()
    return {'ok': True, **r}

@router.post('/api/billing/pay/sandbox/{order_id}/confirm')
async def billing_pay_sandbox_confirm(request: Request, order_id: str):
    """R10：沙箱收银台「模拟支付成功」（仅 YIMU_PAY_SANDBOX!=0 时可用，须登录且须本人订单）。"""
    u = _a.guard(request)
    import os as _os
    if _os.environ.get('YIMU_PAY_SANDBOX', '1') in ('0', 'false', 'no'):
        raise HTTPException(403, '沙箱支付已在生产配置中关闭')
    from studio.membership import payments
    db = _a._r3_session()
    try:
        user_id = _a._current_user_id(u)
        tenant_id = _a._web_tenant_id(db, user_id)
        r = payments.settle_paid_order(db, tenant_id, order_id, channel='sandbox', trade_no=f'sandbox-{int(time.time())}')
        if r.get('order', {}).get('id') and (not _a._is_admin_user(u)):
            from studio.db_models import Order
            own = db.query(Order).filter(Order.id == str(order_id), Order.user_id == user_id).first()
            if own is None:
                raise HTTPException(403, '无权操作他人订单')
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f'沙箱核销失败: {e}')
    finally:
        db.close()
    return r

@router.api_route('/api/billing/pay/notify/{channel}', methods=['GET', 'POST'])
async def billing_pay_notify(channel: str, request: Request):
    """R10：支付渠道异步回调（公开端点，渠道验签把关；GET 用于虎皮椒类同步通知兼容）。"""
    from fastapi.responses import JSONResponse, PlainTextResponse
    from studio.membership import payments
    if str(channel or '').lower() not in ('xunhu', 'stripe'):
        return JSONResponse({'ok': False, 'error': '未知渠道'}, status_code=400)
    query = dict(request.query_params)
    body = await request.body()
    headers = {k.lower(): v for k, v in (request.headers or {}).items()}
    try:
        evt = payments.verify_callback(str(channel).lower(), query=query, body=body, headers=headers)
    except ValueError as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)
    if not evt.get('order_id'):
        return JSONResponse({'ok': False, 'error': '回调缺少订单号'}, status_code=400)
    db = _a._r3_session()
    try:
        from studio.db_models import Order
        o = db.query(Order).filter(Order.id == evt['order_id']).first()
        if o is None:
            return JSONResponse({'ok': False, 'error': '订单不存在'}, status_code=404)
        r = payments.settle_paid_order(db, str(o.tenant_id), evt['order_id'], channel=str(channel).lower(), trade_no=evt.get('trade_no', ''), amount_cents=evt.get('amount_cents'))
    except Exception as e:
        db.rollback()
        return JSONResponse({'ok': False, 'error': str(e)[:200]}, status_code=500)
    finally:
        db.close()
    if str(channel).lower() == 'xunhu':
        return PlainTextResponse('success')
    return {'ok': True, 'idempotent': r.get('idempotent', False)}

@router.post('/api/billing/order')
async def billing_create_order(request: Request):
    """R3-2：用户下单购买套餐 → 生成 CDKey + 返回支付指引。

    ⚠️ 收款方式说明（重要，勿误认为已接支付网关）：
       本项目**没有微信支付/支付宝商户资质**，因此不提供「一键支付」按钮。
       真实链路是「下单 → 生成卡密 → 线下转账 → 管理员核销 → 用户兑换到账」。
       这不是临时应付，而是当前资质下**唯一能真实收钱**的通路。
    """
    u = _a.guard(request)
    body = await request.json()
    plan = str(body.get('plan') or '').strip().lower()
    from studio import pricing as _pricing
    if not _pricing.plan_exists(plan):
        raise HTTPException(400, '该套餐不可购买，可选：pro、studio')
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        user_id = _a._current_user_id(u)
        tenant_id = _a._web_tenant_id(db, user_id)
        view = commerce.create_order(db, tenant_id, user_id, plan)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f'[下单] 创建订单异常: {e}')
        raise HTTPException(500, '下单失败，请稍后重试')
    finally:
        db.close()
    try:
        from core import analytics
        analytics.track('order_created', _a._current_user_id(u), {'plan': plan, 'amount_yuan': view.get('amount_yuan')})
    except Exception:
        pass
    return {'ok': True, 'order': view}

@router.get('/api/billing/orders')
def billing_my_orders(request: Request):
    """R3-2：查询**当前用户自己**的订单列表（含卡密与状态）。"""
    u = _a.guard(request)
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        user_id = _a._current_user_id(u)
        tenant_id = _a._web_tenant_id(db, user_id)
        from studio.db_models import Order
        rows = db.query(Order).filter(Order.tenant_id == tenant_id, Order.user_id == user_id).order_by(Order.created_at.desc()).limit(50).all()
        items = [{'id': r.id, 'plan': r.plan, 'credits': int(r.credits), 'amount_yuan': round(int(r.amount_cents) / 100.0, 2), 'status': r.status, 'cdkey': r.cdkey if r.status == 'paid' else '', 'created_at': r.created_at.isoformat() if r.created_at else None} for r in rows]
    finally:
        db.close()
    return {'ok': True, 'items': items, 'total': len(items)}

@router.post('/api/billing/orders/{order_id}/cancel')
async def billing_cancel_my_order(request: Request, order_id: str):
    """用户取消自己的待支付订单（或管理员取消订单），并同步作废对应卡密。"""
    u = _a.guard(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from studio.membership import commerce
    from studio.db_models import Order
    db = _a._r3_session()
    try:
        user_id = _a._current_user_id(u)
        tenant_id = _a._web_tenant_id(db, user_id)
        order = db.query(Order).filter(Order.id == str(order_id), Order.tenant_id == tenant_id).first() or db.query(Order).filter(Order.id == str(order_id)).first() or db.query(Order).filter(Order.id == str(order_id)).first() or db.query(Order).filter(Order.id == str(order_id)).first()
        if order is None:
            raise HTTPException(404, '订单不存在')
        if order.user_id != user_id and (not _a._is_admin_user(u)):
            raise HTTPException(403, '无权操作他人订单')
        view = commerce.cancel_order(db, tenant_id, order_id, actor=user_id, reason=str((body or {}).get('reason') or '用户主动取消'))
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f'取消订单失败: {e}')
    finally:
        db.close()
    return {'ok': True, 'order': view}

@router.post('/api/billing/orders/{order_id}/activate')
async def billing_activate_order(request: Request, order_id: str):
    """管理员代客核销：把**已确认收款**订单的卡密兑换到账。

    🔴 这是一个历史漏洞点，改动请勿回退：
       修复前用的是 ``guard(request)``，且会在 ``status == "pending"`` 时
       自己调 ``confirm_order_paid``——等于任何注册用户都能把自己的订单
       一键标记为「已收款」并把卡密兑换成额度（Pro ¥300 / Studio ¥2000 白嫖），
       同时把假订单写成 paid 污染财务对账。
       现在：① 仅管理员可调用；② **绝不自助确认收款**，必须已是 paid；
       ③ 订单查询去掉跨租户兜底。
    """
    admin = _a.guard_admin(request)
    from studio.membership import commerce
    from studio import billing_adapter
    from studio.db_models import Order
    db = _a._r3_session()
    try:
        actor_id = _a._current_user_id(admin)
        tenant_id = _a._web_tenant_id(db, actor_id)
        order = db.query(Order).filter(Order.id == str(order_id), Order.tenant_id == tenant_id).first()
        if order is None:
            raise HTTPException(404, '订单不存在')
        if order.status != 'paid':
            raise HTTPException(409, f'订单当前状态为 {order.status}，只有已确认收款（paid）的订单才能核销到账')
        cdkey = order.cdkey
        target_uid = order.user_id
    finally:
        db.close()
    if not cdkey:
        raise HTTPException(400, '该订单无可用卡密')
    res = billing_adapter.redeem_cdkey_for_user(cdkey, target_uid)
    try:
        from core import analytics
        analytics.track('cdkey_redeemed', actor_id, {'order_id': str(order_id), 'by': 'admin', 'ok': bool(res.get('ok'))})
    except Exception:
        pass
    return {'ok': bool(res.get('ok')), 'redeem': res, 'order_id': order_id}

@router.get('/api/admin/orders')
def admin_list_orders(request: Request):
    """R3-2/R3-6：订单管理列表（管理员），支持状态筛选与分页。"""
    _a.guard_admin(request)
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(_a.get_current_user(request)))
        status = request.query_params.get('status') or ''
        limit = int(request.query_params.get('limit') or 50)
        offset = int(request.query_params.get('offset') or 0)
        return {'ok': True, **commerce.list_orders(db, tenant_id, status=status, limit=limit, offset=offset)}
    finally:
        db.close()

@router.post('/api/admin/orders/{order_id}/confirm')
async def admin_confirm_order(request: Request, order_id: str):
    """R3-2：管理员核销收款（pending → paid）。

    ⭐ 这是手工核销收款方案的「收钱确认」环节：用户线下转账后，
       运营在这里点一下，订单才算真正收款成功。
    """
    admin = _a.guard_admin(request)
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(admin))
        view = commerce.confirm_order_paid(db, tenant_id, order_id, actor=_a._current_user_id(admin))
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f'[订单] 核销异常: {e}')
        raise HTTPException(500, '核销失败，请稍后重试')
    finally:
        db.close()
    return {'ok': True, 'order': view}

@router.post('/api/admin/orders/{order_id}/cancel')
async def admin_cancel_order(request: Request, order_id: str):
    """R3-2：作废未支付订单（pending → cancelled，并撤销卡密）。"""
    admin = _a.guard_admin(request)
    body = await request.json()
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(admin))
        view = commerce.cancel_order(db, tenant_id, order_id, actor=_a._current_user_id(admin), reason=str(body.get('reason') or ''))
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f'[订单] 取消异常: {e}')
        raise HTTPException(500, '取消失败，请稍后重试')
    finally:
        db.close()
    return {'ok': True, 'order': view}

@router.get('/api/billing/upgrade')
def billing_upgrade_options(request: Request):
    """R3-4：额度不足时的付费引导数据（额度对比表 + 购买入口）。

    供前端在撞402 后弹出「还差多少 + 买哪个档」；与 R5-3 的召回邮件**并存不冲突**：
    邮件走 user_notify（本接口不触发邮件），页面引导走本接口（不发邮件）。
    """
    _a.guard(request)
    from studio import pricing as _pricing
    try:
        need = int(request.query_params.get('need') or 0)
    except Exception:
        need = 0
    db = _a._r3_session()
    try:
        user_id = _a._current_user_id(_a.get_current_user(request))
        tenant_id = _a._web_tenant_id(db, user_id)
        from studio.billing_adapter import get_billing_status
        balance = int(get_billing_status(db, tenant_id, user_id)['balance'])
    except Exception:
        balance = 0
    finally:
        db.close()
    data = _pricing.upsell_options(need_credits=need, balance=balance)
    data['full_drama_credits'] = _pricing.FULL_DRAMA_CREDITS
    return {'ok': True, **data}

@router.post('/api/admin/grant_credits')
async def admin_grant_credits(request: Request):
    """R3-5：给指定用户发放额度（管理员）。

    背景：grant_credits 此前只有 service 层函数、**没有 HTTP 入口**，
    运营要发额度只能改代码发版。现补上管理端入口。
    ⚠️ 资金动作：必须 guard_admin，且发放与审计同事务（见 commerce 层）。
    """
    admin = _a.guard_admin(request)
    body = await request.json()
    user_id = str(body.get('user_id') or '').strip()
    try:
        amount = int(body.get('amount') or 0)
    except Exception:
        raise HTTPException(400, '额度必须是整数')
    reason = str(body.get('reason') or '').strip()
    if not user_id:
        raise HTTPException(400, '缺少 user_id')
    if amount <= 0:
        raise HTTPException(400, '发放额度必须为正数')
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(admin))
        result = commerce.grant_credits_to_user(db, tenant_id, user_id, amount, reason=reason or '管理员手动发放', actor=_a._current_user_id(admin))
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f'[发放] 额度发放异常: {e}')
        raise HTTPException(500, '发放失败，请稍后重试')
    finally:
        db.close()
    return {'ok': True, **result}

@router.post('/api/admin/orders/{order_id}/refund')
async def admin_refund_order(request: Request, order_id: str):
    """R3-6：退款（**真的扣回额度** + 作废卡密 + 写审计）。

    ⚠️ 资金动作：必须 guard_admin。
    ⭐ 「扣回额度」是本接口的核心——只改订单状态不扣额度等于假退款。
       用户已消费导致扣不满的部分（shortfall）会如实返回给运营。
    """
    admin = _a.guard_admin(request)
    body = await request.json()
    reason = str(body.get('reason') or '').strip()
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(admin))
        view = commerce.refund_order(db, tenant_id, order_id, actor=_a._current_user_id(admin), reason=reason or '运营退款')
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f'[退款] 退款异常: {e}')
        raise HTTPException(500, '退款失败，请稍后重试')
    finally:
        db.close()
    return {'ok': True, 'order': view}

