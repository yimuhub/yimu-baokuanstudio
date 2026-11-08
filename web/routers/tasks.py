# SPDX-License-Identifier: BUSL-1.1
"""异步任务 / Copilot / 流式 / 批量路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse  # noqa: E402,F811
from pathlib import Path  # noqa: E402,F811
import asyncio  # noqa: E402,F811
import time  # noqa: E402,F811
import uuid  # noqa: E402,F811

@router.get('/api/tasks')
def list_active_tasks(request: Request, active_only: bool=False):
    _a.guard(request)
    from core import task_queue
    return {'tasks': task_queue.list_tasks(limit=30, active_only=active_only)}

@router.get('/api/tasks/{task_id}')
def get_task_status(task_id: str, request: Request):
    _a.guard(request)
    from core import task_queue
    task = task_queue.get_task(task_id)
    if not task:
        raise HTTPException(404, 'Task not found')
    tdict = task.to_dict() if hasattr(task, 'to_dict') else task
    return {'task': tdict}

@router.post('/api/tasks/{task_id}/cancel')
def cancel_task_endpoint(task_id: str, request: Request):
    _a.guard(request)
    from core import task_queue
    ok = task_queue.cancel_task(task_id)
    return {'ok': ok, 'msg': '任务已取消' if ok else '无法取消任务（可能已结束或不存在）'}

@router.post('/api/tasks/clear')
async def clear_tasks_endpoint(request: Request):
    """清理任务：清除 N 天前的失败/已完成任务（不碰 running/queued）。"""
    _a.guard(request)
    body = await request.json()
    status_filter = (body.get('status') or 'failed').strip().lower()
    if status_filter not in ('failed', 'completed'):
        status_filter = 'failed'
    try:
        days = int(body.get('days', 7))
    except (TypeError, ValueError):
        days = 7
    if days not in (1, 3, 5, 7):
        days = 7
    from core import task_queue
    return task_queue.clear_tasks(status_filter, days)

@router.post('/api/copilot/chat')
async def copilot_chat_endpoint(request: Request):
    u = _a.guard(request)
    _allowed, _reason, _tier = _a._tier_quota_check(u, 'copilot_daily')
    if not _allowed:
        raise HTTPException(402, _reason)
    from core import copilot
    body = await request.json()
    message = (body.get('message') or '').strip()
    if not message:
        raise HTTPException(400, '聊天内容不能为空')
    draft_id = body.get('draft_id')
    history = body.get('history') or []
    platform = body.get('platform', 'xhs')
    model = body.get('model')
    provider = body.get('provider')
    style = body.get('style')
    persona = body.get('persona')
    image_model = body.get('image_model')
    skills = body.get('skills')
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, lambda: copilot.handle_copilot_chat(message, draft_id=draft_id, history=history, target_platform=platform, model=model, provider=provider, style=style, persona=persona, image_model=image_model, skills=skills, user_id=str(u.get('id') or '')))
        return res
    except Exception as e:
        raise HTTPException(500, f'Copilot 响应失败: {str(e)}')

@router.post('/api/copilot/chat_stream')
async def copilot_chat_stream_endpoint(request: Request):
    u = _a.guard(request)
    _allowed, _reason, _tier = _a._tier_quota_check(u, 'copilot_daily')
    if not _allowed:
        raise HTTPException(402, _reason)
    from core import copilot
    body = await request.json()
    message = (body.get('message') or '').strip()
    if not message:
        raise HTTPException(400, '聊天内容不能为空')
    draft_id = body.get('draft_id')
    history = body.get('history') or []
    platform = body.get('platform', 'xhs')
    model = body.get('model')
    provider = body.get('provider')
    style = body.get('style')
    persona = body.get('persona')
    image_model = body.get('image_model')
    skills = body.get('skills')
    import queue
    import threading
    q = queue.Queue()

    def _worker():
        try:
            try:
                from core.db import auto_heal_drafts_check_constraint, conn as _db_conn
                _c = _db_conn()
                auto_heal_drafts_check_constraint(_c)
                _c.close()
            except Exception:
                pass

            def _emit(step_txt, prog):
                q.put({'type': 'step', 'step': step_txt, 'progress': prog})
            res = copilot.handle_copilot_chat(message, draft_id=draft_id, history=history, target_platform=platform, model=model, provider=provider, style=style, persona=persona, image_model=image_model, skills=skills, user_id=str(u.get('id') or ''), emit_step=_emit)
            q.put({'type': 'result', 'data': res})
        except Exception as e:
            q.put({'type': 'error', 'error': str(e)})
        finally:
            q.put(None)
    threading.Thread(target=_worker, daemon=True).start()

    async def event_generator():
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.06)
                continue
            if item is None:
                break
            yield f'data: {json.dumps(item, ensure_ascii=False)}\n\n'
    return StreamingResponse(event_generator(), media_type='text/event-stream')

@router.post('/api/copilot/attach')
async def copilot_attach_endpoint(request: Request, file: UploadFile=File(...)):
    """接收对话附件：文档/表格解析成正文，图片落盘后返回可回显地址。"""
    _a.guard(request)
    from core import copilot_files
    data = await file.read()
    if len(data) > copilot_files.MAX_BYTES:
        raise HTTPException(413, '附件超过 10MB，请压缩后再上传')
    if not data:
        raise HTTPException(400, '附件内容为空')
    info = copilot_files.extract(file.filename or '附件', data)
    url = ''
    if info['kind'] == 'image':
        ext = Path(file.filename or '').suffix.lower() or '.png'
        safe = f'cp_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}'
        (_a._COPILOT_UPLOAD_DIR / safe).write_bytes(data)
        url = f'/static-img/copilot_uploads/{safe}'
    return {'name': info['name'], 'kind': info['kind'], 'size': info['size'], 'text': info['text'], 'truncated': info['truncated'], 'url': url}

@router.post('/api/copilot/polish_prompt')
async def copilot_polish_prompt_endpoint(request: Request):
    """把一句话想法扩写成结构完整的创作提示词（大模型优先，模板兜底）。"""
    u = _a.guard(request)
    body = await request.json()
    text = (body.get('text') or '').strip()
    if not text:
        raise HTTPException(400, '请先输入一句话想法')
    platform = body.get('platform') or 'xhs'
    from core import prompt_polish
    res = await asyncio.get_event_loop().run_in_executor(None, lambda: prompt_polish.polish(text, platform=platform, user_id=str(u.get('id') or '')))
    return res

@router.post('/api/stream/write')
async def stream_write_endpoint(request: Request):
    _a.guard(request)
    from core import llm
    body = await request.json()
    prompt = body.get('prompt', '')
    system_prompt = body.get('system', '你是专业资深的新媒体爆款主笔。')
    model = body.get('model')
    messages = [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': prompt}]

    def event_generator():
        try:
            for chunk in llm.chat_stream(messages, model=model):
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            yield 'data: [DONE]\n\n'
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_generator(), media_type='text/event-stream')

@router.post('/api/batch/submit')
async def batch_submit_endpoint(request: Request):
    _a.guard(request)
    body = await request.json()
    items = body.get('items', [])
    options = body.get('options', {})
    if not items:
        raise HTTPException(400, '批量选题列表不能为空')
    from core import task_queue, orchestrator
    batch_name = f'批量矩阵生产 ({len(items)} 篇)'

    def _run_batch(task):
        return orchestrator.batch_create_drafts(items, options, emit=task.update_progress, task=task)
    task = task_queue.submit_task(name=batch_name, task_type='batch_creation', fn=_run_batch, params={'count': len(items), 'options': options})
    return {'ok': True, 'task_id': task.id, 'count': len(items), 'msg': '批量矩阵生产任务已提交后台持久化队列'}

@router.get('/api/jobs/{jid}')
@router.get('/api/rewrite/job/{jid}')
def rewrite_job_status(jid: str, request: Request):
    _a.guard(request)
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, '任务不存在')
    return j

