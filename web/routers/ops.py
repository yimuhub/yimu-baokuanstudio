# SPDX-License-Identifier: BUSL-1.1
"""每日工单 / 运营看板 / 续费提醒路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

from core.llm import load_config, load_env  # noqa: E402,F811
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
import asyncio  # noqa: E402,F811
import json  # noqa: E402,F811
import time  # noqa: E402,F811

@router.get('/api/ticket/last')
def ticket_last(request: Request):
    _a.guard(request)
    td = _a.BASE / 'data' / 'tickets'
    files = sorted(td.glob('*.json')) if td.exists() else []
    last = json.loads(files[-1].read_text()) if files else None
    env = load_env()
    return {'last': last, 'enabled': env.get('TICKET_ENABLED') == '1', 'time': env.get('TICKET_TIME', '07:30'), 'dingtalk': _a.notify_ok()}

@router.post('/api/ticket/run')
async def ticket_run(request: Request):
    _a.guard(request)
    import uuid
    jid = f'tkt-{uuid.uuid4().hex[:8]}'
    _a.start_async_job(jid, name='自动化每日巡航与热点产出工单', task_type='ticket_exec', initial_step='工单流水线启动中…')

    def _run():
        try:
            from core import ticket
            res = ticket.run_ticket(emit=lambda m: _a.update_async_job(jid, step=m))
            _a.update_async_job(jid, status='done', step='每日巡航工单执行完成！', progress=100, result=res)
        except Exception as e:
            _a.update_async_job(jid, status='failed', error=str(e)[:300], step='工单执行失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.post('/api/ticket/schedule')
async def ticket_schedule(request: Request):
    """设置每日工单的开关与时间（R5-2：应用内定时，不再依赖 macOS launchd）。

    ⚠️ 行为变更：原实现往 ``~/Library/LaunchAgents/`` 写 plist 并
    ``launchctl load``，那是**仅限 macOS 本机**的机制，云端部署
    （容器 / Linux）既无 launchctl 也无该目录，定时功能会静默失效。
    现改为只写配置，由应用内调度守护线程按点执行，跨平台一致。
    """
    _a.guard(request)
    body = await request.json()
    enabled = bool(body.get('enabled'))
    hh, mm = (body.get('time') or '07:30').split(':')
    _a.write_env('TICKET_ENABLED', '1' if enabled else '0')
    _a.write_env('TICKET_TIME', f'{int(hh):02d}:{int(mm):02d}')
    _a._unload_legacy_launchd()
    from core import scheduler as _sched
    st = _sched.ticket_status()
    return {'ok': True, 'enabled': enabled, 'time': st['time'], 'mode': 'in_app', 'daemon_running': st['daemon_running']}

@router.get('/api/ticket/schedule')
def ticket_schedule_get(request: Request):
    """读取每日工单定时状态（供设置页回显）。"""
    _a.guard(request)
    from core import scheduler as _sched
    st = _sched.ticket_status()
    return {'ok': True, 'enabled': st['enabled'], 'time': st['time'], 'ran_today': st['ran_today'], 'daemon_running': st['daemon_running']}

@router.get('/api/admin/metrics')
def admin_metrics(request: Request):
    """⭐ 运营漏斗看板数据（管理员）。

    返回 5 步漏斗（注册 → 首次成稿 → 首次跑短剧 → 撞额度墙 → 兑换卡密）
    的逐级转化，另附工单定时、账号健康、通知投递三个运营面板。

    ⚠️ 口径说明：漏斗按**累计触达的去重用户数**统计，非严格同会话序列，
    因此后段可能出现反超（如先撞墙再成稿）。看板已标注该口径。
    """
    _a.guard_admin(request)
    from core import analytics, pubguard
    from core import scheduler as _sched
    try:
        days = int(request.query_params.get('days') or 30)
    except Exception:
        days = 30
    fn = analytics.funnel(days)
    revenue = {}
    expiring = []
    try:
        from studio.membership import revenue as _rev
        db = _a._r3_session()
        try:
            tenant_id = _a._web_tenant_id(db, _a._current_user_id(_a.get_current_user(request)))
            revenue = _rev.revenue_summary(db, tenant_id, days=days)
            expiring = _rev.expiring_memberships(db, tenant_id, within_days=7)
        finally:
            db.close()
    except Exception as _e:
        revenue = {'ok': False, 'error': str(_e)[:200]}
    return {'ok': True, 'funnel': fn, 'recent_events': analytics.list_recent(20), 'ticket': _sched.ticket_status(), 'account_health': pubguard.health_summary(), 'revenue': revenue, 'expiring_memberships': expiring, 'generated_at': time.time()}

@router.post('/api/admin/renewal-reminders/send')
async def admin_send_renewal_reminders(request: Request):
    """R10：手动触发续费提醒（7/3/1 天节点，24h 节流幂等）。"""
    _a.guard_admin(request)
    from studio.membership import revenue as _rev
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(_a.get_current_user(request)))
        r = _rev.send_renewal_reminders(db, tenant_id, force=False)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f'续费提醒发送失败: {e}')
    finally:
        db.close()
    return {'ok': True, **r}

