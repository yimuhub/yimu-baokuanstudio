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
from core.blocking import run_blocking  # noqa: E402,F811  (受界阻塞池)

from web.draft_guard import DraftOwnerRoute  # noqa: E402  稳定类身份
router = APIRouter(route_class=DraftOwnerRoute)  # {did} 归属校验路由类

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse  # noqa: E402,F811
from pathlib import Path  # noqa: E402,F811
import asyncio  # noqa: E402,F811
import time  # noqa: E402,F811
import uuid  # noqa: E402,F811

def _assert_task_visible(task: dict, user: dict) -> None:
    """任务归属校验：非 admin 只能看到 / 取消自己的任务（越权按 404 表现）。

    why：/api/tasks 此前是全局列表——任何登录用户都能看到（并取消）别人的
    渲染/生图任务。与草稿归属（_assert_draft_owner）同一口径：404 而非 403，
    不给遍历探测的口子。owner 为空的条目视为系统/历史任务，仅 admin 可见。
    """
    if _a._is_admin_user(user):
        return
    owner = str((task or {}).get('owner') or '')
    if owner != str((user or {}).get('id') or ''):
        raise HTTPException(404, '任务不存在')


#: /api/tasks 列表保留的字段：只留展示/轮询需要的列（v15.9.9 效率整改）。
# why：list_tasks 底层 SELECT * 携带 params_json / result_json / params /
# result 大内容，30 条列表动辄数百 KB，而列表页只显示状态、进度与错误行。
_TASK_LIST_KEEP_FIELDS = (
    'id', 'name', 'task_type', 'target_id', 'owner', 'status', 'progress',
    'message', 'step', 'error', 'created_at', 'created_at_fmt',
    'started_at', 'completed_at', 'duration_s', 'current_step', 'total_steps',
)


def _trim_task_row(t: dict) -> dict:
    """列表行裁剪：剥掉 params/result 大列，error 截断到 200 字（详情端点保留全量）。"""
    view = {k: t[k] for k in _TASK_LIST_KEEP_FIELDS if k in t}
    if view.get('error'):
        view['error'] = str(view['error'])[:200]
    return view


@router.get('/api/tasks')
def list_active_tasks(request: Request, active_only: bool=False):
    user = _a.guard(request)
    from core import task_queue
    tasks = task_queue.list_tasks(limit=30, active_only=active_only)
    # 按当前用户过滤（admin 全量）：owner 为空的系统/历史任务对普通用户不可见
    if not _a._is_admin_user(user):
        uid = str((user or {}).get('id') or '')
        tasks = [t for t in tasks if str(t.get('owner') or '') == uid]
    # 归属过滤后再裁剪，避免把别人的大字段读进内存又丢掉
    return {'tasks': [_trim_task_row(t) for t in tasks]}

@router.get('/api/tasks/{task_id}')
def get_task_status(task_id: str, request: Request):
    user = _a.guard(request)
    # v15.9.9（重复 R6）：与 /api/jobs、/api/rewrite/job 统一走 _get_task_view
    # （持久化 task_queue 优先、JOBS 兜底），三条读路径返回同一形状
    task = _a._get_task_view(task_id)
    if not task:
        raise HTTPException(404, 'Task not found')
    _assert_task_visible(task, user)
    return {'task': task}

@router.post('/api/tasks/{task_id}/cancel')
def cancel_task_endpoint(task_id: str, request: Request):
    user = _a.guard(request)
    from core import task_queue
    # 存在性与归属判定走统一视图：JOBS 型旁路任务同样可见可取消
    # （task_queue.cancel 会联动把 JOBS 条目写为 cancelled）
    task = _a._get_task_view(task_id)
    if not task:
        raise HTTPException(404, '任务不存在')
    _assert_task_visible(task, user)
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

def _sanitize_copilot_result(res):
    """统一剥掉模型塞进回复里的包装标签（如 ``<WritingBlock …>``）。

    模型偶尔会把整段内容包一层 ``<WritingBlock id="…" variant="document">``，
    这层壳对读者毫无意义，但会原样显示在聊天气泡开头和结尾。这里只剥壳，
    不动 ``**加粗**`` 等仍有渲染意义的标记。
    """
    try:
        from core.text_purity import strip_model_wrappers
        if isinstance(res, dict) and isinstance(res.get('reply'), str):
            res['reply'] = strip_model_wrappers(res['reply'])
    except Exception:
        pass
    return res


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
        res = await run_blocking(lambda: copilot.handle_copilot_chat(message, draft_id=draft_id, history=history, target_platform=platform, model=model, provider=provider, style=style, persona=persona, image_model=image_model, skills=skills, user_id=str(u.get('id') or '')))
        return _sanitize_copilot_result(res)
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
            q.put({'type': 'result', 'data': _sanitize_copilot_result(res)})
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
    res = await run_blocking(lambda: prompt_polish.polish(text, platform=platform, user_id=str(u.get('id') or '')))
    return res

def _stream_credit_preflight(user_id: str, model, messages: list) -> None:
    """官方通道流式计费预检（不扣费，仅验余额能否覆盖本次估算成本）。

    why：/api/stream/write 此前只做登录 guard——官方通道真正的扣费发生在流
    结束后的 ``_meter_call``，额度不足也要等模型跑完才知道，用户白白等待；
    且此前 ``chat_stream`` 根本没把 user_id 传下去，官方通道整条流式链路
    「只记统计不扣费」（资损）。这里复用 studio 现有估算法
    （llm_metering.estimate_tokens + pricing.credits_for_call）在开流前
    校验一次余额；不足直接抛 402，前端已有失败气泡展示。
    """
    from core import llm
    from studio import llm_metering, pricing

    base, key, target_model, pid = llm.resolve_llm_endpoint(model, user_id=user_id)
    if pid != llm_metering.OFFICIAL_PROVIDER_ID:
        # BYOK / 自备 Key 通道不消耗平台算力额度（与 require_credits 口径一致）
        return
    # 今日免费体验次数还有余量时放行（与 record_llm_call 的免单判定同源）
    try:
        if llm_metering.free_demo_left_today(user_id) > 0:
            return
    except Exception:
        pass
    prompt_text = "\n".join(str(m.get('content', '')) for m in messages if isinstance(m, dict))
    est_in = llm_metering.estimate_tokens(prompt_text)
    est_out = 1024  # 单次流式写作常规输出的经验估算（超长会实际计费，此处只是开流前的余额检查）
    in_credits, out_credits = pricing.credits_for_call(target_model, est_in, est_out)
    need = int(in_credits) + int(out_credits)
    if need <= 0:
        return
    from studio import billing_adapter
    db = billing_adapter._web_session()
    try:
        tenant_id = _a._web_tenant_id(db, user_id)
        status = billing_adapter.get_billing_status(db, tenant_id, user_id)
        balance = int((status or {}).get('balance') or 0)
    finally:
        db.close()
    if balance < need:
        raise HTTPException(
            402,
            f"算力额度不足：本次流式写作预计至少需要 {need:,} 点，"
            f"你的账户还剩 {balance:,} 点。可升级套餐，或到「设置 → 模型服务」"
            "填入自备 API Key（自备 Key 不扣会员额度）。")


@router.post('/api/stream/write')
async def stream_write_endpoint(request: Request):
    u = _a.guard(request)
    from core import llm
    body = await request.json()
    prompt = body.get('prompt', '')
    system_prompt = body.get('system', '你是专业资深的新媒体爆款主笔。')
    model = body.get('model')
    messages = [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': prompt}]
    user_id = str((u or {}).get('id') or '')
    # v15.9.8：开流前按官方通道做额度预检（不足直接 402，不再等跑完才发现）
    try:
        _stream_credit_preflight(user_id, model, messages)
    except HTTPException:
        raise
    except Exception as e:
        # 预检自身异常不阻断业务：真正扣费仍由流结束的 _meter_call 兜底
        import logging as _logging
        _logging.getLogger(__name__).warning(f"[stream] 流式额度预检异常（放行）: {e}")

    def event_generator():
        try:
            for chunk in llm.chat_stream(messages, model=model, user_id=user_id):
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
    """任务详情（三条读路径统一实现，v15.9.9 重复 R6 整改）。

    过去只查 JOBS 内存字典：任务一旦只登记在持久化队列（或 JOBS 被过期清理）
    就 404，前端轮询「任务消失」。现在统一走 _get_task_view——
    先查持久化 task_queue 再回退 JOBS，返回形状与 /api/tasks/{id} 一致
    （同时保留 status/step/result/error 等 JOBS 旧消费方依赖的键）。
    """
    u = _a.guard(request)
    j = _a._get_task_view(jid)
    if not j:
        raise HTTPException(404, '任务不存在')
    # 归属隔离（与 /api/tasks 同口径）：非 admin 只能看自己的任务
    _assert_task_visible(j, u)
    return j

