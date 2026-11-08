# SPDX-License-Identifier: BUSL-1.1
"""后台用户与审计路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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
from web.draft_guard import DraftOwnerRoute  # noqa: E402  (稳定类身份,跨 admin reload 不变)

router = APIRouter(route_class=DraftOwnerRoute)  # {did} 归属校验路由类(与拆分前 app.route_class 等效)

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811

@router.get('/api/admin/users')
def admin_list_users(request: Request):
    """R3-7：用户列表（分页 + 搜用户名/邮箱/档位/封禁态）。"""
    _a.guard_admin(request)
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(_a.get_current_user(request)))
        return {'ok': True, **commerce.list_users(db, tenant_id, keyword=request.query_params.get('keyword') or '', tier=request.query_params.get('tier') or '', banned=request.query_params.get('banned') or '', limit=int(request.query_params.get('limit') or 20), offset=int(request.query_params.get('offset') or 0))}
    finally:
        db.close()

@router.post('/api/admin/users/{user_id}/ban')
async def admin_ban_user(request: Request, user_id: str):
    """R3-7：封禁用户（banned=true）/ 解封（banned=false）。

    ⚠️ 权限动作：必须 guard_admin，且**必须写审计日志**（见 commerce.set_user_banned）。
       封禁后 is_active=False，``get_current_user`` 会拒绝其令牌 →
       即「无法调 API」（见 tests/test_r3_monetization.py）。
    """
    admin = _a.guard_admin(request)
    body = await request.json()
    banned = bool(body.get('banned', True))
    reason = str(body.get('reason') or '').strip()
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(admin))
        result = commerce.set_user_banned(db, tenant_id, user_id, banned, actor=_a._current_user_id(admin), reason=reason)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f'[封禁] 操作异常: {e}')
        raise HTTPException(500, '操作失败，请稍后重试')
    finally:
        db.close()
    return {'ok': True, **result}

@router.post('/api/admin/users')
async def admin_create_user(request: Request):
    """管理员新建用户"""
    _a.guard_admin(request)
    body = await request.json()
    username = str(body.get('username') or '').strip()
    password = str(body.get('password') or '').strip()
    email = str(body.get('email') or '').strip()
    role = str(body.get('role') or 'user').strip()
    plan = str(body.get('plan') or 'free').strip()
    quota_max = int(body.get('quota_max') or 0)
    try:
        from core import auth
        user = auth.create_user_crud(username, password, email, role, plan, quota_max)
        return {'ok': True, 'user': user, 'msg': f'用户 {username} 创建成功'}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.put('/api/admin/users/{user_id}')
async def admin_update_user(user_id: str, request: Request):
    """管理员编辑用户信息（邮箱、角色、档位、额度、封禁态）"""
    _a.guard_admin(request)
    body = await request.json()
    try:
        from core import auth
        user = auth.update_user_crud(user_id, email=body.get('email'), role=body.get('role'), plan=body.get('plan'), quota_max=body.get('quota_max'), is_active=body.get('is_active'))
        return {'ok': True, 'user': user, 'msg': '用户信息已更新'}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post('/api/admin/users/{user_id}/password')
async def admin_change_user_password(user_id: str, request: Request):
    """管理员直接重置修改用户密码"""
    _a.guard_admin(request)
    body = await request.json()
    new_password = str(body.get('password') or '').strip()
    try:
        from core import auth
        auth.change_password_crud(user_id, new_password)
        return {'ok': True, 'msg': '密码已成功修改'}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.delete('/api/admin/users/{user_id}')
async def admin_delete_user(user_id: str, request: Request):
    """管理员删除指定用户"""
    _a.guard_admin(request)
    try:
        from core import auth
        auth.delete_user_crud(user_id)
        return {'ok': True, 'msg': '用户已成功删除'}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get('/api/admin/audit_logs')
def admin_audit_logs(request: Request):
    """R3-8：审计日志查询（分页 + 按动作/操作人/对象过滤）。"""
    _a.guard_admin(request)
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(_a.get_current_user(request)))
        return {'ok': True, **commerce.query_audit_logs(db, tenant_id, action=request.query_params.get('action') or '', actor=request.query_params.get('actor') or '', target=request.query_params.get('target') or '', keyword=request.query_params.get('keyword') or '', limit=int(request.query_params.get('limit') or 50), offset=int(request.query_params.get('offset') or 0))}
    finally:
        db.close()

@router.get('/api/admin/audit_actions')
def admin_audit_actions(request: Request):
    """R3-8：已出现过的审计动作列表（给查询页做下拉筛选）。"""
    _a.guard_admin(request)
    from studio.membership import commerce
    db = _a._r3_session()
    try:
        tenant_id = _a._web_tenant_id(db, _a._current_user_id(_a.get_current_user(request)))
        return {'ok': True, 'actions': commerce.audit_actions(db, tenant_id)}
    finally:
        db.close()

