# SPDX-License-Identifier: BUSL-1.1
"""系统健康 / 版本 / 更新 / 合规闸路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

from adapters.base import PLATFORMS, NAMES  # noqa: E402,F811
from core import agents as AG  # noqa: E402,F811
from core import db, judge, orchestrator  # noqa: E402,F811
from core import layouter  # noqa: E402,F811
from core.llm import load_config, load_env  # noqa: E402,F811
from core.themes import WECHAT_THEMES, XHS_CARD_STYLES  # noqa: E402,F811
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
import time  # noqa: E402,F811

@router.get('/api/health')
def api_health():
    # /health 本体在 pages.py(R11 拆分归属);V7 契约:/api/health 是其规范别名
    from web.routers.pages import health as _pages_health
    return _pages_health()

@router.get('/api/version')
def api_version():
    info = _a.get_app_version_info()
    return {'version': info.get('version', _a.get_app_version()), 'details': info}

@router.get('/api/system/check_update')
def api_system_check_update(force: bool=False):
    """访问 GitHub 仓库检测是否有新版本。"""
    from core import updater
    return updater.check_for_updates(force=force)

@router.post('/api/system/upgrade')
def api_system_upgrade(request: Request):
    """一键从 GitHub 同步升级最新代码（需要管理员权限）。"""
    _a.guard(request)
    from core import updater
    return updater.perform_upgrade()

@router.get('/api/compliance/guard')
def guard_stats(request: Request):
    """内容安全闸概况：开关状态、各词库条目数、白名单规模。"""
    _a.guard(request)
    from core import content_guard
    return content_guard.library_stats()

@router.post('/api/compliance/topics/sweep')
async def guard_sweep_topics(request: Request):
    """扫描选题池，把命中内容安全闸的条目标记 blocked（**不删除**）。

    body: {"apply": false} 预演；true 真正标记。等价于 `python -m scripts.r4_cleanup --apply`。
    """
    _a.guard(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = db.sweep_blocked_topics(apply=bool(body.get('apply')))
    return {'ok': True, **res}

@router.get('/api/compliance/topics/blocked')
def guard_blocked_topics(request: Request):
    """列出被内容安全闸拦下的选题（供人工复核）。"""
    _a.guard(request)
    items = db.list_blocked_topics()
    return {'ok': True, 'total': len(items), 'items': items}

@router.post('/api/compliance/drafts/sweep')
async def guard_sweep_drafts(request: Request):
    """扫描草稿箱，把命中内容安全闸的条目标记 needs_review（**不删除**）。"""
    _a.guard(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = db.sweep_drafts_needs_review(apply=bool(body.get('apply')))
    return {'ok': True, **res}

@router.get('/api/compliance/drafts/review')
def guard_drafts_review(request: Request):
    """列出待人工复核的草稿。"""
    _a.guard(request)
    items = db.list_drafts_needs_review()
    return {'ok': True, 'total': len(items), 'items': items}

@router.post('/api/compliance/drafts/{did}/clear_review')
async def guard_clear_review(did: str, request: Request):
    """人工复核通过：清除 needs_review 标记（草稿本身保留）。"""
    _a.guard(request)
    if not db.get_draft(did):
        raise HTTPException(404, '草稿不存在')
    return {'ok': db.clear_draft_needs_review(did)}

@router.post('/api/compliance/drafts/{did}/check')
async def guard_check_draft(did: str, request: Request):
    """对单篇草稿做发布前内容安全检查（不写库，仅返回可读结论）。"""
    _a.guard(request)
    from core import content_guard
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    res = content_guard.pre_publish_check(d.get('body_md'), d.get('title'))
    return res.to_dict()

@router.get('/api/status')
def status(request: Request):
    user = _a.guard(request)
    cfg = load_config()
    env = load_env()
    cr = cfg.get('creation', {})
    exp_days = int(cr.get('draft_expire_days', 0))
    if exp_days > 0:
        try:
            db.delete_old_drafts(exp_days)
        except Exception:
            pass
    cur_ws_id = db.get_active_workspace().get('id', 'ws-default')
    return {'topics': db.list_topics(workspace_id=cur_ws_id), 'drafts': [_a._draft_view(d) for d in db.list_drafts(_a._current_user_id(user), is_admin=_a._is_admin_user(user), workspace_id=cur_ws_id)], 'workspace_id': cur_ws_id, 'jobs': db.list_jobs(), 'gateway': {'base_url': cfg.get('gateway', {}).get('base_url', ''), 'model': cfg.get('gateway', {}).get('model', ''), 'provider_id': cfg.get('gateway', {}).get('provider_id', 'custom'), 'configured_models': orchestrator.llm.get_configured_models(), 'agent_routing': cfg.get('gateway', {}).get('agent_routing', {}), 'key_set': bool(env.get('MEDIAFLOW_APIPOOL_KEY')), 'llm_ok': orchestrator.llm.available()}, 'keywords': cfg.get('topics', {}).get('keywords', []), 'platform_names': NAMES, 'themes': {'wechat': {**{k: v['name'] + '（规则）' for k, v in WECHAT_THEMES.items()}, **{k: v['name'] for k, v in layouter.list_themes().items() if v.get('has_prompt')}}, 'card': {k: v['name'] for k, v in XHS_CARD_STYLES.items()}, 'current': {'wechat_theme': cr.get('wechat_theme', 'caozhou'), 'card_style': cr.get('card_style', 'magazine')}}, 'target_platforms': cr.get('target_platforms') or ['wechat_mp', 'xhs', 'toutiao', 'zhihu', 'weibo', 'twitter'], 'draft_expire_days': int(cr.get('draft_expire_days', 0)), 'quality': judge.quality_cfg(), 'image': cfg.get('image', {}), 'ticket': {'enabled': env.get('TICKET_ENABLED') == '1', 'time': env.get('TICKET_TIME', '07:30'), 'dingtalk': _a.notify_ok()}, 'imgbed': {'configured': bool(env.get('GITHUB_IMGBED_TOKEN') and env.get('GITHUB_IMGBED_REPO')), 'repo': env.get('GITHUB_IMGBED_REPO', '')}, 'agents': AG.agents_cfg(), 'stages': AG.STAGES, 'skills': {k: v['description'] for k, v in AG.list_skills().items()}, 'search_sources': {'xhs': '小红书', 'toutiao': '今日头条', 'douyin': '抖音', 'weibo': '微博', 'kuaishou': '快手', 'bilibili': 'B站'}}

@router.get('/api/health/services')
def health_services(request: Request):
    _a.guard(request)
    import httpx
    out = []
    for svc in _a.HEALTH_SERVICES:
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                r = client.get(f"http://127.0.0.1:{svc['port']}{svc['path']}")
                ok = r.status_code < 500
        except Exception:
            ok = False
        out.append({**svc, 'ok': ok})
    return {'services': out, 'mediaflow': True}

@router.post('/api/health/repair')
async def health_repair(request: Request):
    _a.guard(request)
    body = await request.json()
    name = body.get('name')
    import subprocess as sp
    uid = sp.run(['id', '-u'], capture_output=True, text=True).stdout.strip()
    if name == 'apipool':
        sp.run(['launchctl', 'kickstart', '-k', f'gui/{uid}/com.czmj.apipool'], capture_output=True)
        time.sleep(4)
    elif name == 'exporter':
        sp.run(['launchctl', 'kickstart', '-k', f'gui/{uid}/com.czmj.wae'], capture_output=True)
        time.sleep(3)
    elif name == 'xhsmcp':
        xb = _a.BASE / 'vendors/xhs-mcp/xiaohongshu-mcp'
        if xb.exists():
            sp.run(['pkill', '-f', 'xiaohongshu-mcp'], capture_output=True)
            time.sleep(1)
            sp.Popen([str(xb), '-headless=true'], cwd=str(xb.parent), stdout=open(_a.BASE / 'logs/xhsmcp.out', 'w'), stderr=sp.STDOUT)
            time.sleep(3)
        else:
            raise HTTPException(400, '组件未安装')
    else:
        raise HTTPException(404, name)
    return {'ok': True}

