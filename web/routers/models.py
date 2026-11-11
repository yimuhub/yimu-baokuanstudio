# SPDX-License-Identifier: BUSL-1.1
"""模型服务配置路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

@router.get('/api/models/providers')
def get_model_providers(request: Request):
    _a.guard(request)
    from core import llm
    all_providers = llm.get_all_configured_providers()
    cfg = llm.load_config()
    gw = cfg.get('gateway', {})
    active_pid = gw.get('provider_id', 'deepseek')
    # V15.8.3：与真正发请求时同源（示例值不算已配置），避免界面说「已配置」而调用 401
    _diag = llm.diagnose()
    has_active_key = _diag['key_present']
    cross_models = []
    for pid, p in all_providers.items():
        for m in p.get('models', []):
            m_copy = dict(m)
            m_copy['provider_id'] = pid
            m_copy['provider_name'] = p['name']
            m_copy['has_key'] = bool(p.get('has_key'))
            m_copy['is_active_provider'] = pid == active_pid
            cross_models.append(m_copy)
    all_presets = {pid: {'id': pid, 'name': pinfo['name'], 'badge': pinfo.get('badge', ''), 'base_url': pinfo['base_url'], 'default_model': pinfo['default_model'], 'models': pinfo.get('models', []), 'icon': pinfo.get('icon', '⚡')} for pid, pinfo in llm.MODEL_PROVIDERS.items()}
    from core import video_rules
    from studio import llm_metering
    from studio import first_piece as _fp_mod
    _fp_status = _fp_mod.first_piece_status
    u_for_demo = _a.get_current_user(request)
    user_id_demo = str(u_for_demo.get('id') or u_for_demo.get('user_id') or '') if u_for_demo else ''
    return {'providers': all_providers, 'all_presets': all_presets, 'current': gw, 'active_provider_id': active_pid, 'configured_models': llm.get_configured_models(), 'cross_models': cross_models, 'env_key_set': has_active_key, 'video_rules': video_rules.load_rules().get('rules', []), 'free_demo': {'daily_calls': llm_metering.pricing.FREE_DEMO_DAILY_CALLS, 'max_output_tokens': llm_metering.pricing.FREE_DEMO_MAX_OUTPUT_TOKENS, 'left_today': llm_metering.free_demo_left_today(user_id_demo), 'first_piece': _fp_status(user_id_demo)}}

@router.post('/api/models/fetch')
async def model_fetch(request: Request):
    """拉取远端模型清单（**管理员**：这是全站模型配置的一部分）。

    🔴 安全：修复前是 guard() 且 route 层自己做了
       ``api_key or MEDIAFLOW_APIPOOL_KEY`` 的兜底——普通用户把 base_url
       指向自己的服务器就能收到平台主 Key 明文。
       现在：① 仅管理员；② 平台主 Key 的兜底只在 core.llm 内部、
       且仅对「平台自有端点」生效（见 llm._is_platform_endpoint）。
    """
    _a.guard_admin(request)
    body = await request.json()
    base_url = body.get('base_url', '')
    provider_id = body.get('provider_id', 'custom')
    from core import llm
    api_key = body.get('api_key') or ''
    return llm.fetch_remote_models(base_url, api_key, provider_id)

@router.post('/api/models/ping')
async def model_ping(request: Request):
    """连通性测试（**管理员**，原因同 :func:`model_fetch`）。

    ``api_key`` 允许留空：设置页编辑已有模型服务时输入框是故意清空的
    （留空=不修改已存密钥），此时由 ``llm.resolve_provider_key`` 回退到
    该服务已保存的 Key，否则「编辑 → 测速」必然 401。
    """
    _a.guard_admin(request)
    body = await request.json()
    base_url = body.get('base_url', '')
    from core import llm
    api_key = body.get('api_key') or ''
    model = body.get('model', '')
    provider_id = body.get('provider_id', '')
    return llm.ping_provider(base_url, api_key, model, provider_id)

@router.get('/api/models/diagnose')
def model_diagnose(request: Request):
    """通道自检：返回当前解析到的地址、密钥来源与可执行建议（不含 Key 明文）。"""
    _a.guard(request)
    from core import llm
    return {'ok': True, **llm.diagnose()}

@router.post('/api/models/save')
async def model_save(request: Request):
    _a.guard_admin(request)
    body = await request.json()
    provider_id = body.get('provider_id', 'custom')
    provider_name = body.get('provider_name', '')
    base_url = body.get('base_url', '')
    api_key = body.get('api_key', '')
    model = body.get('model', '')
    agent_routing = body.get('agent_routing', {})
    configured_models = body.get('configured_models')
    # R12：默认不激活(保存≠激活);激活走显式 set_active 或前端「设为主网关」
    is_set_active = bool(body.get('is_set_active', False))
    params = body.get('params', {})
    from core import llm
    ok = llm.save_provider_config(provider_id, base_url, api_key, model, agent_routing, params, configured_models=configured_models, provider_name=provider_name, is_set_active=is_set_active)
    return {'ok': ok, 'msg': '模型服务与多Agent路由配置已持久化保存并立即热生效！'}

@router.post('/api/models/provider/set_active')
async def model_set_active_provider(request: Request):
    _a.guard_admin(request)
    body = await request.json()
    provider_id = body.get('provider_id', '')
    if not provider_id:
        raise HTTPException(400, 'provider_id 不能为空')
    from core import llm
    ok = llm.set_active_provider(provider_id)
    return {'ok': ok, 'msg': f'已成功切换当前主活动网关为 [{provider_id}]'}

@router.post('/api/models/provider/delete')
async def model_delete_provider(request: Request):
    _a.guard_admin(request)
    body = await request.json()
    provider_id = body.get('provider_id', '')
    provider_ids = body.get('provider_ids', [])
    from core import llm
    if provider_ids and isinstance(provider_ids, list):
        del_count = 0
        for pid in provider_ids:
            if pid and llm.delete_provider(str(pid)):
                del_count += 1
        return {'ok': True, 'msg': f'已成功批量删除 {del_count} 家模型服务配置', 'count': del_count}
    if not provider_id:
        raise HTTPException(400, 'provider_id 或 provider_ids 不能为空')
    ok = llm.delete_provider(provider_id)
    return {'ok': ok, 'msg': f'已成功删除模型服务 [{provider_id}]'}

