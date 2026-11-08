# SPDX-License-Identifier: BUSL-1.1
"""搜索 / 仿写 / 提取 / 渲染路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

from core import db, judge, orchestrator  # noqa: E402,F811
from core.themes import WECHAT_THEMES, XHS_CARD_STYLES  # noqa: E402,F811
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
import asyncio  # noqa: E402,F811

@router.post('/api/render')
async def api_render(request: Request):
    """实时渲染：markdown → 微信兼容行内样式 HTML（规则主题，毫秒级）。"""
    _a.guard(request)
    body = await request.json()
    from core.themes import md_to_wechat_html
    from core.layouter import _inject_cover
    theme = body.get('theme', 'caozhou')
    if theme not in WECHAT_THEMES:
        theme = 'caozhou'
    body_md = body.get('body_md', '')
    title = body.get('title', '')
    did = body.get('did', '')
    images, cover = ({}, None)
    if did:
        ddir = db.draft_dir(did)
        if (ddir / 'img').exists():
            from core.text_denoise import extract_section_headings
            sec_titles = [t.strip('【】').strip() for t, _ in extract_section_headings(body_md)]
            pngs = sorted((ddir / 'img').glob('sec-*.png'))
            images = {t: f'/img/{did}/{p.name}' for t, p in zip(sec_titles, pngs)}
            if (ddir / 'img' / 'cover.png').exists():
                cover = f'/img/{did}/cover.png'
    meta = (body.get('meta') or body.get('media_name') or '').strip() or '一幕·YIMU 爆款工作室'
    from core.layouter import render as layout_render
    html = layout_render(body_md, title=title, theme=theme, meta=meta, images=images, cover=cover)
    return {'html': html}

@router.get('/api/search/status')
def search_status(request: Request):
    _a.guard(request)
    from core import search as S
    return {'xhs': S.xhs_available(), 'douyin': S.douyin_available(), 'toutiao': True}

@router.post('/api/search')
async def do_search(request: Request):
    _a.guard(request)
    body = await request.json()
    kw = (body.get('keyword') or '').strip()
    if not kw:
        raise HTTPException(400, '关键词不能为空')
    sources = body.get('sources') or ['xhs', 'toutiao', 'douyin']
    from core.search import search_expanded

    def _run():
        res, words = search_expanded(kw, sources, int(body.get('limit', 16)), expand=bool(body.get('expand', True)))
        res['_queries'] = words
        return res
    return await asyncio.get_event_loop().run_in_executor(None, _run)

@router.post('/api/rewrite')
async def do_rewrite(request: Request):
    _a.guard(request)
    body = await request.json()
    try:
        return await asyncio.get_event_loop().run_in_executor(None, lambda: orchestrator.benchmark_and_rewrite(body.get('platform', ''), body.get('title', ''), body.get('url', ''), (body.get('theme') or '').strip(), body.get('extra') or {}, source_text=body.get('source_text') or body.get('text') or '', user_id=_current_user_id(_a.guard(request))))
    except Exception as e:
        raise HTTPException(500, f'拆解仿写失败: {e}')

@router.post('/api/extract')
async def do_extract(request: Request):
    _a.guard(request)
    body = await request.json()
    raw_url = (body.get('url') or '').strip()
    if not raw_url:
        raise HTTPException(400, '链接不能为空')
    from core.extractor import extract_url

    def _run():
        return extract_url(raw_url)
    try:
        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f'提取失败: {e}')

@router.post('/api/rewrite/job')
async def rewrite_job(request: Request):
    _a.guard(request)
    body = await request.json()
    user = _a.get_current_user(request) or {}
    body['_owner_user_id'] = str(user.get('id') or '')
    import uuid
    title = (body.get('title') or (body.get('extra') or {}).get('title') or '爆款仿写')[:16]
    jid = f'rw-{uuid.uuid4().hex[:8]}'
    _a.start_async_job(jid, name=f'爆款文章仿写: {title}', task_type='article_gen', params=body, initial_step='排队分析中…')
    asyncio.get_event_loop().run_in_executor(None, _a._run_rewrite_job, jid, body)
    return {'job': jid}

