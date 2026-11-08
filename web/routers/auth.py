# SPDX-License-Identifier: BUSL-1.1
"""认证 / 账号 / Key 保险箱 / 引导路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse  # noqa: E402,F811
import time  # noqa: E402,F811

@router.post('/api/auth/register')
async def api_register(request: Request):
    """V6/V7 用户自助注册新账号（同步记录 signup 漏斗、支持邀请码核销并双写 yimu_session）"""
    body = await request.json()
    username = (body.get('username') or '').strip()
    password = (body.get('password') or '').strip()
    email = (body.get('email') or '').strip()
    invite_code = (body.get('invite_code') or '').strip()
    try:
        from core import auth
        res = auth.register_user(username, password, email, invite_code=invite_code)
        resp = JSONResponse(res)
        resp.set_cookie('mf_v6_token', res['token'], httponly=True, samesite='lax', max_age=30 * 86400, path='/')
        resp.set_cookie('yimu_session', res['token'], httponly=True, samesite='lax', max_age=30 * 86400, path='/')
        return resp
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post('/api/auth/login')
async def api_login(request: Request):
    """V6 用户登录"""
    body = await request.json()
    username = (body.get('username') or '').strip()
    password = (body.get('password') or '').strip()
    strong_pwd = _a._admin_password()
    is_loopback_client = _a._is_loopback(request)
    loopback_grant = is_loopback_client and strong_pwd is not None
    pwd_match_grant = strong_pwd is not None and password == strong_pwd
    if username in ('admin', '') and (loopback_grant or pwd_match_grant):
        from core import auth
        auth.ensure_default_admin(strong_pwd)
        token = auth.make_token({'user_id': 'u-admin', 'username': 'admin', 'role': 'admin'})
        u = auth.get_user_by_id('u-admin') or {'id': 'u-admin', 'username': 'admin', 'role': 'admin', 'plan': 'enterprise'}
        resp = JSONResponse({'ok': True, 'token': token, 'user': u, 'msg': '管理员登录成功'})
        resp.set_cookie('mf_v6_token', token, httponly=True, samesite='lax', max_age=30 * 86400, path='/')
        resp.set_cookie('mf_token', _a._token(), httponly=True, samesite='lax', max_age=30 * 86400, path='/')
        return resp
    try:
        from core import auth
        res = auth.login_user(username, password)
        resp = JSONResponse(res)
        resp.set_cookie('mf_v6_token', res['token'], httponly=True, samesite='lax', max_age=30 * 86400, path='/')
        resp.set_cookie('yimu_session', res['token'], httponly=True, samesite='lax', max_age=30 * 86400, path='/')
        return resp
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get('/api/auth/me')
def api_auth_me(request: Request):
    """获取当前登录用户的资料与额度（与 PC 端 /api/billing/ui/me 统一度量真源）"""
    u = _a.guard(request)
    if isinstance(u, dict):
        u['avatar_url'] = u.get('avatar_url') or '/static/img/default-avatar.png'
        try:
            from web.gateway_ui import _db, _studio_user, _membership_summary, TENANT_ID, ADMIN_ROLES
            from studio.membership.service import ensure_membership
            from studio.db_models import User as StudioUser, utcnow
            db = _db()
            try:
                user_ctx = {'user_id': str(u.get('id', '') or u.get('user_id', '')), 'username': str(u.get('username', '')), 'role': str(u.get('role', 'user'))}
                su = _studio_user(db, user_ctx)
                if su is None and user_ctx['user_id']:
                    role = 'admin' if user_ctx['role'] in ADMIN_ROLES else 'user'
                    su = StudioUser(id=user_ctx['user_id'], tenant_id=TENANT_ID, username=user_ctx['username'] or user_ctx['user_id'], email='', password_hash='!', salt='', role=role, is_active=True, created_at=utcnow())
                    db.add(su)
                    db.flush()
                if su:
                    target_tenant = getattr(su, 'tenant_id', None) or TENANT_ID
                    m = ensure_membership(db, target_tenant, su.id)
                    if su.id == 'u-admin':
                        if not m.tier:
                            m.tier = 'studio'
                        if m.credits_total < 6000000:
                            m.credits_total = 6000000
                        if int(m.credits_used or 0) > int(m.credits_total or 0):
                            m.credits_used = 0
                    db.commit()
                    summ = _membership_summary(m)
                    u['credits_left'] = summ['credits_left']
                    u['credits_total'] = summ['credits_total']
                    u['credits_used'] = summ['credits_used']
                    u['tier'] = summ['tier']
                    u['tier_name'] = summ['tier_name']
                    u['tier_display'] = summ['tier_display']
                    u['plan'] = summ['tier']
                    u['quota_max'] = summ['credits_left']
                    u['membership'] = summ
            finally:
                db.close()
        except Exception:
            pass
    return {'ok': True, 'user': u}

@router.post('/api/auth/change_password')
async def api_change_password(request: Request):
    """用户修改自身密码【V8.3.33】
    
    支持两种调用场景：
    1. 已登录会话中调用：guard 校验当前登录用户；
    2. 未登录/通过账号通行证弹窗修改：根据传入的 username 和 old_password 进行严密凭证核验。
    """
    body = await request.json()
    username = str(body.get('username') or '').strip()
    old_password = str(body.get('old_password') or '').strip()
    new_password = str(body.get('new_password') or '').strip()
    confirm_password = str(body.get('confirm_password') or '').strip()
    if not new_password:
        raise HTTPException(400, '新密码不能为空')
    if len(new_password) < 6:
        raise HTTPException(400, '新密码长度至少为 6 个字符')
    if confirm_password and new_password != confirm_password:
        raise HTTPException(400, '两次输入的新密码不一致')
    from core import auth
    u = _a.get_current_user(request)
    user_dict = None
    user_id = None
    if u and (not username or u.get('username') == username):
        user_id = u.get('id') or 'u-admin'
        c = auth._db()
        r = c.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if r:
            user_dict = dict(r)
        c.close()
    if not user_dict and username:
        c = auth._db()
        r = c.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if r:
            user_dict = dict(r)
            user_id = user_dict['id']
        c.close()
    if not user_dict:
        if username in ('admin', ''):
            strong_pwd = _a._admin_password()
            auth.ensure_default_admin(strong_pwd)
            c = auth._db()
            r = c.execute("SELECT * FROM users WHERE id='u-admin' OR username='admin'").fetchone()
            if r:
                user_dict = dict(r)
                user_id = user_dict['id']
            c.close()
    if not user_dict:
        raise HTTPException(400, '原密码不正确，请重新输入')
    if user_dict.get('password_hash'):
        if not old_password:
            raise HTTPException(400, '请输入原密码以验证身份')
        verified = auth.verify_password(old_password, user_dict['password_hash'], user_dict.get('salt', ''))
        strong_pwd = _a._admin_password()
        admin_matched = bool(user_dict.get('role') == 'admin' and strong_pwd and (old_password == strong_pwd))
        if not verified and (not admin_matched):
            raise HTTPException(400, '原密码不正确，请重新输入')
    else:
        strong_pwd = _a._admin_password()
        if strong_pwd and old_password != strong_pwd:
            raise HTTPException(400, '当前管理员口令不正确')
    auth.change_password_crud(user_id, new_password)
    return {'ok': True, 'msg': '密码修改成功，请牢记新密码'}

@router.get('/api/user/vault/keys')
def api_user_vault_keys(request: Request):
    """获取用户自己添加的所有模型服务 API Key 列表"""
    u = _a.guard(request)
    from core import auth
    keys = auth.list_user_api_keys(u['id'])
    active_key = auth.get_active_user_llm_config(u['id'])
    return {'ok': True, 'keys': keys, 'using_platform_default': active_key is None, 'active_provider': active_key.get('provider') if active_key else 'system_default'}

@router.post('/api/user/vault/keys')
async def api_save_user_vault_key(request: Request):
    """用户在自己账号下添加/配置单独的模型 API Key"""
    u = _a.guard(request)
    body = await request.json()
    provider = (body.get('provider') or '').strip()
    api_key = (body.get('api_key') or '').strip()
    base_url = (body.get('base_url') or '').strip()
    model_id = (body.get('model_id') or '').strip()
    label = (body.get('label') or '').strip()
    if not provider or not api_key:
        raise HTTPException(400, '模型服务与 API Key 均不能为空')
    from core import auth
    res = auth.save_user_api_key(u['id'], provider, api_key, base_url, model_id, label)
    return {'ok': True, 'key': res, 'msg': f'模型服务【{provider}】API Key 已安全加密存储并生效！'}

@router.delete('/api/user/vault/keys/{kid}')
def api_delete_user_vault_key(kid: str, request: Request):
    """用户删除自己的 API Key，自动切回平台托管"""
    u = _a.guard(request)
    from core import auth
    auth.delete_user_api_key(u['id'], kid)
    return {'ok': True, 'msg': '该 API 凭证已删除，后续调用将自动切回平台统一服务'}

@router.get('/api/auth/status')
def auth_status(request: Request):
    u = _a.get_current_user(request)
    from studio import llm_metering
    u_id = str((u or {}).get('id') or (u or {}).get('user_id') or '')
    try:
        from core import auth
        has_own_key = auth.get_active_user_llm_config(u.get('id')) is not None
    except Exception:
        has_own_key = False
    return {'authed': u is not None, 'user': u, 'is_default': load_env().get('ADMIN_PASSWORD', 'local-admin') == 'local-admin', 'wizard': {'show': bool(u and u_id and (not _a._wiz_done(u_id)) and (not has_own_key)), 'daily_free_calls': llm_metering.pricing.FREE_DEMO_DAILY_CALLS, 'free_left_today': llm_metering.free_demo_left_today(u_id)}}

@router.post('/api/onboarding/done')
def onboarding_done(request: Request):
    """首次引导完成/跳过标记（防反复打扰）。"""
    u = _a.get_current_user(request)
    if not u:
        raise HTTPException(401, '请先登录')
    p = _a.ENV_PATH.parent / 'data' / 'user_onboarding_done.json'
    import json as _json
    data = {}
    try:
        data = _json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    uid = str(u.get('id') or u.get('user_id') or '')
    data[uid] = {'done': True, 'ts': time.time()}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'ok': True}

@router.post('/api/auth/logout')
def logout():
    resp = JSONResponse({'ok': True, 'msg': '已退出登录'})
    resp.delete_cookie('mf_v6_token', path='/')
    resp.delete_cookie('mf_token', path='/')
    return resp

