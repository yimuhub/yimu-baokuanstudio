# SPDX-License-Identifier: BUSL-1.1
"""技能库 / Agent / 习惯进化 / 名家音色 / IP 角色 / 工作区路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse  # noqa: E402,F811
from pathlib import Path  # noqa: E402,F811
import asyncio  # noqa: E402,F811
import yaml  # noqa: E402,F811

@router.get('/api/skills/all')
def skills_all(request: Request):
    _a.guard(request)
    from core.agents import STAGES
    full = _a._skills_full()
    refs = {}
    rd = _a.BASE / 'skills' / 'refs'
    if rd.exists():
        for lib in sorted(rd.iterdir()):
            if lib.is_dir():
                refs[lib.name] = sorted((f.name for f in lib.rglob('*.md')))
    return {**full, 'stages': STAGES, 'refs': refs}

@router.get('/api/agents/config')
def agents_config(request: Request):
    """获取所有 13 个 Agent 与 岗位阶段配置信息"""
    _a.guard(request)
    from core import agents as AG
    return {'ok': True, 'stages': AG.STAGES, 'agents': AG.agents_cfg(), 'skills': {k: v['description'] for k, v in AG.list_skills().items()}}

@router.post('/api/skills/save')
async def skills_save(request: Request):
    _a.guard(request)
    import re as _re
    body = await request.json()
    name = _re.sub('[^a-z0-9-]', '', (body.get('name') or '').lower())
    if not name:
        raise HTTPException(400, '技能名只能是英文/数字/连字符')
    desc = (body.get('description') or '').strip()
    text = (body.get('body') or '').strip()
    if len(text) < 10:
        raise HTTPException(400, '技能内容太短')
    (_a.SKILL_AGENTS_DIR / f'{name}.md').write_text(f'---\nname: {name}\ndescription: {desc}\n---\n\n{text}\n', encoding='utf-8')
    return {'ok': True, 'name': name}

@router.post('/api/skills/delete')
async def skills_delete(request: Request):
    _a.guard(request)
    body = await request.json()
    name = (body.get('name') or '').strip()
    f = _a.SKILL_AGENTS_DIR / f'{name}.md'
    if not f.exists():
        raise HTTPException(404, '技能不存在')
    import shutil
    trash = Path.home() / '.Trash'
    trash.mkdir(exist_ok=True)
    shutil.move(str(f), str(trash / f'skill-{name}.md'))
    from core import provider_registry as _reg
    cfg = _reg.raw_config()
    for stage, a in cfg.get('agents', {}).items():
        if name in (a.get('skills') or []):
            a['skills'] = [x for x in a['skills'] if x != name]
    _reg.write_config(cfg)
    return {'ok': True}

@router.post('/api/skills/distill')
async def skills_distill(request: Request):
    """蒸馏：贴入爆款文章/名人文风 → AI 提炼成结构化技能文件。"""
    _a.guard(request)
    body = await request.json()
    name_raw = (body.get('name') or '').strip()
    text = (body.get('text') or '').strip()
    if not text or len(text) < 50:
        raise HTTPException(400, '请贴入至少 50 字的文章/语录')
    import re as _re
    import uuid
    jid = f'dist-{uuid.uuid4().hex[:8]}'
    _a.start_async_job(jid, name=f'名家文风语料蒸馏: {name_raw[:14]}', task_type='voice_distill', params={'name': name_raw}, initial_step='AI 蒸馏风格规则与写作指纹中…')

    def _run():
        try:
            from core import agents as AG
            slug = _re.sub('[^a-z0-9-]', '', name_raw.lower().replace(' ', '-')) or f'distill-{jid[:6]}'
            raw = AG.chat_for('analyze', [{'role': 'user', 'content': f'把下面内容蒸馏成一份可复用的中文写作技能。\n输出格式（严格遵守）：\nDESC: <一句话技能描述，30字内>\nRULES:\n<8~12条具体可执行的写作规则，每条一行，涵盖：标题钩子手法/开头套路/句式节奏/用词偏好/结尾方式/情绪策略>\n\n【待蒸馏内容】\n{text[:4000]}'}], temperature=0.4)
            desc, rules = ('', '')
            m = re.search('DESC\\s*[:：]\\s*(.+)', raw)
            if m:
                desc = m.group(1).strip()
            mr = re.search('RULES:\\s*([\\s\\S]+)', raw)
            if mr:
                rules = mr.group(1).strip()
            if not rules:
                raise ValueError('蒸馏解析失败：' + raw[:150])
            (_a.SKILL_AGENTS_DIR / f'{slug}.md').write_text(f'---\nname: {slug}\ndescription: 蒸馏技能·{name_raw}：{desc}\n---\n\n# 蒸馏自「{name_raw}」\n\n{rules}\n', encoding='utf-8')
            _a.update_async_job(jid, status='done', step='文风蒸馏完成并已入库！', progress=100, result={'slug': slug, 'desc': desc})
        except Exception as e:
            _a.update_async_job(jid, status='failed', error=str(e)[:300], step='蒸馏失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.get('/api/skills/ref')
def skills_ref(request: Request, path: str=''):
    _a.guard(request)
    base = (_a.BASE / 'skills' / 'refs').resolve()
    f = (base / path).resolve()
    if not str(f).startswith(str(base)) or not f.exists() or f.suffix != '.md':
        raise HTTPException(404, '文件不存在')
    return FileResponse(f)

@router.get('/api/habit/status')
def habit_status(request: Request):
    """获取当前创作者自主进化习惯技能的状态与特征规则"""
    _a.guard(request)
    from core import habit_learner
    return habit_learner.get_habit_status()

@router.post('/api/habit/evolve')
async def habit_evolve(request: Request):
    """从近期定稿/修改内容中提取语言习惯并自主进化技能"""
    _a.guard(request)
    body = await request.json() if request.headers.get('content-type') == 'application/json' else {}
    limit = int(body.get('limit', 5)) if isinstance(body, dict) else 5
    from core import habit_learner
    return habit_learner.evolve_from_drafts(limit=limit)

@router.post('/api/habit/reset')
def habit_reset(request: Request):
    """重置自主进化习惯为初始基线"""
    _a.guard(request)
    from core import habit_learner
    return habit_learner.reset_habit_skill()

@router.get('/api/voices/all')
def voices_all(request: Request):
    _a.guard(request)
    return orchestrator.list_famous_voices()

@router.post('/api/skills/distill_deep')
async def skills_distill_deep(request: Request):
    _a.guard(request)
    body = await request.json()
    content = body.get('content', '')
    distill_type = body.get('distill_type', 'all')
    author_name = body.get('author_name', '')
    _a.require_credits('deep_distill', 1, f'深度逆向蒸馏 [{author_name}]')

    def _run():
        return orchestrator.deep_distill_anything(content, distill_type, author_name)
    try:
        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f'深度蒸馏失败: {e}')

@router.get('/api/ip_characters')
def list_ip_characters_endpoint(request: Request):
    _a.guard(request)
    from core import db
    return {'characters': db.list_ip_characters()}

@router.post('/api/ip_characters/save')
async def save_ip_character_endpoint(request: Request):
    _a.guard(request)
    from core import db
    body = await request.json()
    res = db.save_ip_character(name=body.get('name', '新角色'), gender=body.get('gender', ''), age_group=body.get('age_group', ''), style=body.get('style', ''), avatar_url=body.get('avatar_url', ''), turnaround_sheet_url=body.get('turnaround_sheet_url', ''), features_en=body.get('features_en', ''), dialogue_tone=body.get('dialogue_tone', ''), cid=body.get('id'))
    return {'ok': True, 'character': res}

@router.post('/api/ip_characters/export_from_drama')
async def export_ip_character_from_drama_endpoint(request: Request):
    _a.guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get('draft_id')
    char_id = body.get('char_id')
    res = short_drama.export_character_to_ip_hub(draft_id, char_id)
    return res

@router.post('/api/ip_characters/bind_to_drama')
async def bind_ip_character_to_drama_endpoint(request: Request):
    _a.guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get('draft_id')
    char_id = body.get('char_id')
    ip_char_id = body.get('ip_char_id')
    res = short_drama.bind_ip_character_to_draft(draft_id, char_id, ip_char_id)
    return res

@router.post('/api/ip_characters/delete')
async def delete_ip_character_endpoint(request: Request):
    _a.guard(request)
    from core import db
    body = await request.json()
    cid = body.get('id')
    ok = db.delete_ip_character(cid)
    return {'ok': ok}

@router.get('/api/workspaces')
def list_workspaces_endpoint(request: Request):
    _a.guard(request)
    from core import workspace
    from core.agents import get_catalog_skills
    return {'workspaces': workspace.list_all_workspaces(), 'active': workspace.get_current_workspace(), 'available_skills': get_catalog_skills()}

@router.get('/api/workspaces/skills')
def workspace_skills_endpoint(request: Request):
    _a.guard(request)
    from core.agents import get_catalog_skills
    return {'ok': True, 'skills': get_catalog_skills()}

@router.post('/api/workspaces/switch')
async def switch_workspace_endpoint(request: Request):
    _a.guard(request)
    from core import workspace
    body = await request.json()
    wid = body.get('workspace_id')
    active = workspace.switch_workspace(wid)
    return {'ok': True, 'active': active}

@router.post('/api/workspaces/create')
async def create_workspace_endpoint(request: Request):
    _a.guard(request)
    from core import workspace
    body = await request.json()
    name = body.get('name')
    desc = body.get('desc', '')
    config = body.get('config') or {}
    try:
        res = workspace.create_new_workspace(name, desc, config=config)
        return {'ok': True, 'workspace': res}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post('/api/workspaces/update')
async def update_workspace_endpoint(request: Request):
    _a.guard(request)
    from core import workspace
    body = await request.json()
    wid = body.get('workspace_id') or body.get('id')
    name = body.get('name')
    desc = body.get('desc', '')
    config = body.get('config')
    try:
        res = workspace.update_workspace_info(wid, name, desc, config=config)
        return {'ok': True, 'workspace': res}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post('/api/workspaces/delete')
async def delete_workspace_endpoint(request: Request):
    _a.guard(request)
    from core import workspace
    body = await request.json()
    wid = body.get('workspace_id') or body.get('id')
    try:
        res = workspace.delete_workspace_by_id(wid)
        return {'ok': True, **res}
    except Exception as e:
        raise HTTPException(400, str(e))

