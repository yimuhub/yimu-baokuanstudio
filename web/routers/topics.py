# SPDX-License-Identifier: BUSL-1.1
"""热点选题路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

from core import db, judge, orchestrator  # noqa: E402,F811
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
import asyncio  # noqa: E402,F811

@router.get('/api/topics')
def get_topics(request: Request):
    """获取热榜/热搜选题列表（按当前工作空间隔离）"""
    _a.guard(request)
    cur_ws_id = db.get_active_workspace().get('id', 'ws-default')
    return {'ok': True, 'topics': db.list_topics(workspace_id=cur_ws_id)}

@router.post('/api/topics/collect')
async def topics_collect(request: Request):
    u = _a.guard(request)
    _allowed, _reason, _tier = _a._tier_quota_check(u, 'hot_daily')
    if not _allowed:
        raise HTTPException(402, _reason)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, orchestrator.run_once)
        return res
    except Exception as e:
        print(f'[热榜采集] 异常已兜底，改用已有热榜: {e}')
        return {'total': 0, 'matched': 0, 'keywords': [], 'per_source': {'error': str(e)}, 'blocked': 0, 'blocked_titles': [], 'warn': f'热榜网络抓取受阻已自动兜底: {str(e)[:100]}'}

@router.post('/api/topics/manual')
async def topics_manual(request: Request):
    _a.guard(request)
    body = await request.json()
    title = (body.get('title') or '').strip()
    if not title:
        raise HTTPException(400, '标题不能为空')
    cur_ws_id = db.get_active_workspace().get('id', 'ws-default')
    return db.add_topic('manual', title, body.get('reason', ''), True, workspace_id=cur_ws_id)

@router.post('/api/topics/clean')
async def topics_clean(request: Request):
    """自动清理 N 天前的热榜条目。"""
    _a.guard(request)
    body = await request.json()
    days = int(body.get('days', 3))
    if days < 1:
        raise HTTPException(400, 'days 必须 >= 1')
    cnt = db.delete_old_topics(days)
    return {'ok': True, 'deleted': cnt, 'msg': f'已清理 {cnt} 条 {days} 天前的热榜记录'}

@router.post('/api/topics/clear_all')
async def topics_clear_all(request: Request):
    """立即清空全部热榜库。"""
    _a.guard(request)
    cnt = db.clear_all_topics()
    return {'ok': True, 'deleted': cnt, 'msg': f'已清空热榜库，共删除 {cnt} 条记录'}

@router.get('/api/topics/stats')
async def topics_stats(request: Request):
    """热榜库统计概况。"""
    _a.guard(request)
    return db.count_topics()

@router.post('/api/topics/{tid}/{action}')
async def topic_action(tid: str, action: str, request: Request):
    user = _a.guard(request)
    if action == 'approve':
        db.set_topic_status(tid, 'approved')
        return {'ok': True}
    if action == 'reject':
        db.set_topic_status(tid, 'rejected')
        return {'ok': True}
    if action == 'generate':
        try:
            return await asyncio.get_event_loop().run_in_executor(None, lambda: orchestrator.generate_draft(tid, user_id=_current_user_id(user)))
        except Exception as e:
            raise HTTPException(500, str(e))
    if action == 'generate_job':
        import uuid
        jid = f'art-{tid[:8]}-{uuid.uuid4().hex[:4]}'
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        media_name = (body.get('media_name') or '').strip() or '一幕·YIMU 爆款工作室'
        platforms = body.get('platforms')
        image_style = (body.get('image_style') or '').strip()
        plat_desc = f'({len(platforms)}端)' if platforms else ''
        _a.start_async_job(jid, name=f'爆款文章智能生成{plat_desc} #{tid[:8]}', task_type='article_gen', target_id=tid, params={'topic_id': tid, 'media_name': media_name, 'platforms': platforms, 'image_style': image_style}, initial_step='AI 选题解析与框架构思中…')

        def _run():
            try:
                update_async_job(jid, step='AI 主笔深度创作中…', progress=30)
                res = orchestrator.generate_draft(tid, emit=lambda m: update_async_job(jid, step=m), media_name=media_name, platforms=platforms, user_id=_current_user_id(user), image_style=image_style)
                draft_info = res.get('draft') or {}
                d_title = draft_info.get('title') or '新生成文章'
                update_async_job(jid, status='done', step='文章生成完成', progress=100, result={'draft_id': draft_info.get('id'), 'score': res.get('score'), 'title': d_title})
            except Exception as e:
                update_async_job(jid, status='failed', error=str(e)[:400], step='文章生成失败')
        asyncio.get_event_loop().run_in_executor(None, _run)
        return {'job': jid}
    raise HTTPException(404, action)

@router.post('/api/topics/evaluate')
async def topic_evaluate(request: Request):
    """借鉴 Easel: 选题爆款潜力五维多维评分卡 (Topic Evaluator)。"""
    _a.guard(request)
    body = await request.json()
    topic = (body.get('topic') or body.get('title') or '').strip()
    if not topic:
        raise HTTPException(400, '选题内容不能为空')
    from core import agents
    prompt = f'你是顶级新媒体爆款主编。请对以下选题的爆款潜力进行五维量化评估，并输出纯 JSON。\n\n【待评估选题】：{topic}\n\n打分维度（各项满分20分，总分100）：\n1. viral_potential: 流量广谱度（是否能击中广泛大众的好奇心/共鸣）\n2. pain_point: 痛点穿透力（是否直击现实刚需痛点）\n3. novelty: 认知反差/新颖度（是否颠覆常识）\n4. feasibility: 交付实操性（是否容易落地）\n5. monetization: 商业/变现空间（是否有种草或转化潜力）\n\n严格输出 JSON：\n{{\n  "total_score": 88,\n  "grade": "S级爆款",\n  "scores": {{"viral_potential": 18, "pain_point": 19, "novelty": 17, "feasibility": 18, "monetization": 16}},\n  "verdict": "立刻执行",\n  "advice": "建议重点从反常识误区切入，增加具体对比案例"\n}}'
    try:
        raw = agents.chat_for('review', [{'role': 'system', 'content': '只输出纯 JSON'}, {'role': 'user', 'content': prompt}], temperature=0.3)
        import re, json
        cleaned = raw.strip()
        if cleaned.startswith('```'):
            cleaned = re.sub('^```(?:json)?\\s*', '', cleaned)
            cleaned = re.sub('\\s*```$', '', cleaned)
        m = re.search('\\{.*\\}', cleaned, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {'total_score': 80, 'verdict': '建议执行', 'advice': '主题具备潜力'}
    except Exception as e:
        return {'total_score': 75, 'verdict': '待定', 'advice': str(e)}

@router.post('/api/topics/one_sentence_viral')
async def api_one_sentence_viral(request: Request):
    _a.guard(request)
    body = await request.json()
    body['_owner_user_id'] = str((_a.get_current_user(request) or {}).get('id') or '')
    sentence = (body.get('sentence') or '').strip()
    if not sentence:
        raise HTTPException(400, '请输入创作灵感或一句话需求')
    import uuid
    jid = f'vir-{uuid.uuid4().hex[:8]}'
    _a.start_async_job(jid, name=f'一句话爆款创作: {sentence[:14]}', task_type='article_gen', params={'sentence': sentence}, initial_step='正在理解创作意图…')
    asyncio.get_event_loop().run_in_executor(None, _a._run_one_sentence_viral_job, jid, body)
    return {'job': jid}

