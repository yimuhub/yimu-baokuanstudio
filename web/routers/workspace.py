# SPDX-License-Identifier: BUSL-1.1
"""排期 / 水印 / 设置 / 编辑器 / 分享 / 自定义平台 / 内容复盘路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

⭐ 拆分约定:
- `_a` 指向 web.admin 模块对象,凡引用 admin 模块级 helper/常量一律走 `_a.X`
  (晚绑定:测试对 web_admin.* 的 monkeypatch 继续生效);
- 族内路由保持与拆分前完全一致的注册顺序;
- admin.py 底部统一 include 本 router。"""
from __future__ import annotations

from typing import Optional  # noqa: E402

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

from core import diagnostics as diag  # noqa: E402,F811
from core.llm import load_config, load_env  # noqa: E402,F811
from core import provider_registry as _reg  # noqa: E402
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
import time  # noqa: E402,F811
import yaml  # noqa: E402,F811

@router.get('/api/platforms')
def platforms_list(request: Request):
    _a.guard(request)
    from core.platforms import list_packs
    return {'packs': list_packs()}

@router.get('/api/platforms/custom')
def platforms_custom_list(request: Request):
    _a.guard(request)
    from core.custom_platforms import get_custom_platforms
    return {'ok': True, 'platforms': get_custom_platforms()}

@router.post('/api/platforms/custom')
async def platforms_custom_save(request: Request):
    _a.guard(request)
    body = await request.json()
    from core.custom_platforms import add_or_update_platform
    try:
        saved = add_or_update_platform(body)
        return {'ok': True, 'platform': saved}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.delete('/api/platforms/custom/{platform_id}')
def platforms_custom_delete(platform_id: str, request: Request):
    _a.guard(request)
    from core.custom_platforms import delete_custom_platform
    ok = delete_custom_platform(platform_id)
    return {'ok': ok}

@router.post('/api/platforms/detect')
async def platforms_detect(request: Request):
    _a.guard(request)
    body = await request.json()
    url = body.get('url', '')
    from core.custom_platforms import detect_platform_from_url
    result = detect_platform_from_url(url)
    return {'ok': True, 'data': result}

@router.post('/api/platforms/analyze_style')
async def platforms_analyze_style(request: Request):
    _a.guard(request)
    body = await request.json()
    url = body.get('url', '')
    custom_name = body.get('name', '')
    from core.custom_platforms import analyze_url_layout_style
    result = analyze_url_layout_style(url, custom_name=custom_name)
    return {'ok': True, 'skill': result}

@router.get('/api/workspace/profile')
def api_get_workspace_profile(request: Request, wid: Optional[str]=None):
    """获取当前活动工作区（或指定工作区）的 6 维数字人格档案"""
    _a.guard(request)
    from core import workspace
    return {'ok': True, 'profile': workspace.get_workspace_profile(wid)}

@router.post('/api/workspace/profile')
async def api_update_workspace_profile(request: Request):
    """更新 6 维数字人格档案（定位/声纹/受众/平台偏好/禁忌/长期记忆）"""
    _a.guard(request)
    body = await request.json()
    wid = body.get('workspace_id')
    profile_data = body.get('profile') or {}
    from core import workspace
    active_ws = workspace.get_active_workspace()
    target_wid = wid or (active_ws.get('id') if active_ws else 'ws-default')
    res = workspace.update_workspace_profile(target_wid, profile_data)
    return {'ok': True, 'profile': res, 'msg': '6 维数字人格档案已更新，后续创作将自动注入该声纹指纹！'}

@router.get('/api/workspace/voiceprint')
def api_get_workspace_voiceprint(request: Request, wid: Optional[str]=None):
    """获取指定或当前活动工作区的声纹记忆档案（音色/声线特征/参考音频）"""
    _a.guard(request)
    from core import workspace
    return {'ok': True, 'voiceprint': workspace.get_workspace_voiceprint(wid)}

@router.post('/api/workspace/voiceprint')
async def api_update_workspace_voiceprint(request: Request):
    """更新工作区专属声纹记忆档案"""
    _a.guard(request)
    body = await request.json()
    wid = body.get('workspace_id')
    vp_data = body.get('voiceprint') or {}
    from core import workspace
    active_ws = workspace.get_active_workspace()
    target_wid = wid or (active_ws.get('id') if active_ws else 'ws-default')
    res = workspace.update_workspace_voiceprint(target_wid, vp_data)
    return {'ok': True, 'voiceprint': res, 'msg': '空间声纹记忆档案已更新！'}

@router.post('/api/content/postmortem')
async def api_content_postmortem(request: Request):
    """借鉴 Easel skill-content-postmortem: 爆款/发布效果深度归因与策略顾问。"""
    _a.guard(request)
    body = await request.json()
    title = (body.get('title') or '').strip()
    platform = (body.get('platform') or 'xhs').strip()
    metrics = body.get('metrics') or {}
    content_sample = (body.get('content') or '').strip()
    if not title:
        raise HTTPException(400, '标题不能为空')
    from core import agents
    prompt = f"""你是顶级社媒操盘手与内容归因专家。请对以下已发布的社媒内容及其实际传播数据进行【深度归因复盘 (Content Postmortem)】，拆解其之所以产生该数据的底层原因，并提炼为可复用的爆款认知公式，输出纯 JSON：\n\n【发布平台】：{platform}\n【内容标题】：{title}\n【互动表现数据】：点赞 {metrics.get('likes', 0)} / 收藏 {metrics.get('collects', 0)} / 评论 {metrics.get('comments', 0)} / 浏览量 {metrics.get('views', 0)}\n【正文片段】：\n{content_sample[:1500]}\n\n请从以下 4 个维度进行透彻归因分析：\n1. performance_diagnosis: 数据综合定级 (S/A/B/C) 与爆款成因或平淡原因核心诊断；\n2. hook_attribution: 开篇与标题的吸睛率与点击心理归因；\n3. engagement_drivers: 驱动读者收藏（干货留存欲）与评论（互动槽点/争议/共鸣）的关键推手；\n4. replicable_formula: 提炼一条极其精炼、可在未来稿件中直接复用的【爆款打法公式】。\n\n严格只输出纯 JSON：\n{{\n  "grade": "S",\n  "diagnosis": "高收藏比表明实操干货密度极大，切中大众避坑刚需",\n  "hook_attribution": "反常识数字制造认知缺口",\n  "engagement_drivers": "清单化避坑指南触发强收藏心智",\n  "replicable_formula": "反常识结论 + 场景化踩坑还原 + 3步可执行清单"\n}}"""
    try:
        raw = agents.chat_for('review', [{'role': 'system', 'content': '只输出纯 JSON'}, {'role': 'user', 'content': prompt}], temperature=0.3)
        import re, json
        cleaned = raw.strip()
        if cleaned.startswith('```'):
            cleaned = re.sub('^```(?:json)?\\s*', '', cleaned)
            cleaned = re.sub('\\s*```$', '', cleaned)
        m = re.search('\\{.*\\}', cleaned, re.DOTALL)
        if m:
            return {'ok': True, 'postmortem': json.loads(m.group(0))}
        return {'ok': True, 'postmortem': {'grade': 'A', 'diagnosis': '表现优异', 'replicable_formula': '强化反差 Hook'}}
    except Exception as e:
        raise HTTPException(500, f'归因分析失败: {e}')

@router.post('/api/short_drama/shots/reroll')
async def drama_reroll_shot_endpoint(request: Request):
    _a.guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get('draft_id')
    shot_id = int(body.get('shot_id', 1))
    prompt_en = body.get('prompt_en', '')
    aspect = body.get('aspect', '9:16')
    res = short_drama.reroll_shot_frame(draft_id, shot_id, prompt_en=prompt_en, aspect=aspect)
    return res

@router.post('/api/short_drama/shots/retake_voice')
async def drama_retake_voice_endpoint(request: Request):
    _a.guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get('draft_id')
    shot_id = int(body.get('shot_id', 1))
    script_text = body.get('script_text', '')
    voice = body.get('voice', '')
    res = short_drama.retake_shot_voice(draft_id, shot_id, script_text=script_text, voice=voice)
    return res

@router.post('/api/short_drama/reorder_and_restitch')
async def drama_reorder_and_restitch_endpoint(request: Request):
    _a.guard(request)
    from core import short_drama
    body = await request.json()
    draft_id = body.get('draft_id')
    new_order = body.get('new_order')
    subtitle_enabled = body.get('subtitle_enabled')
    res = short_drama.reorder_and_restitch_drama(draft_id, new_order=new_order, subtitle_enabled=subtitle_enabled)
    return res

@router.get('/api/schedule/posts')
def list_scheduled_posts_endpoint(request: Request, status: Optional[str]=None):
    _a.guard(request)
    from core import scheduler
    return {'posts': scheduler.list_scheduled(status=status)}

@router.post('/api/schedule/post')
async def schedule_post_endpoint(request: Request):
    _a.guard(request)
    from core import scheduler
    body = await request.json()
    draft_id = body.get('draft_id')
    platform = body.get('platform', 'xhs')
    target_time = float(body.get('target_time', time.time() + 3600))
    pid = scheduler.schedule_post(draft_id, platform, target_time)
    return {'ok': True, 'id': pid, 'target_time': target_time}

@router.post('/api/schedule/cancel')
async def cancel_scheduled_post_endpoint(request: Request):
    _a.guard(request)
    from core import scheduler
    body = await request.json()
    pid = body.get('id')
    ok = scheduler.cancel_scheduled(pid)
    return {'ok': ok}

@router.get('/api/watermark/settings')
def get_watermark_settings(request: Request):
    _a.guard(request)
    from core import watermark
    return watermark.get_watermark_config()

@router.post('/api/watermark/settings')
async def save_watermark_settings(request: Request):
    _a.guard(request)
    body = await request.json()
    # 写盘必须用 raw_config：load_config 返回的是派生视图（gateway.base_url 等
    # 由当前活动通道现算），直接 dump 会把派生字段重新写回文件，又造出第二份事实。
    cfg = _reg.raw_config()
    cfg['watermark'] = {'enabled': bool(body.get('enabled', False)), 'text': str(body.get('text', 'Designed with 一幕 YIMU')).strip(), 'position': str(body.get('position', 'bottom-right')), 'opacity': float(body.get('opacity', 0.45)), 'show_on_cards': bool(body.get('show_on_cards', True)), 'show_on_cover': bool(body.get('show_on_cover', True)), 'show_on_video': bool(body.get('show_on_video', True))}
    _reg.write_config(cfg)
    return {'ok': True, 'msg': '水印设置已保存'}

@router.post('/api/editor/upload')
async def editor_upload_file(request: Request, file: UploadFile=File(...)):
    _a.guard(request)
    import uuid
    upload_dir = _a.BASE / 'data' / 'editor_uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    from core.upload_guard import IMAGE_EXTS, save_upload
    try:
        dest, _orig = await save_upload(file, upload_dir, 'ed', IMAGE_EXTS, max_mb=20)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f'编辑器上传失败: {e}')
    return {'url': f'/static-img/editor_uploads/{dest.name}', 'size': dest.stat().st_size}

@router.post('/api/share/revoke')
async def share_revoke(request: Request):
    """吊销一个分享链接（立即失效）。"""
    _a.guard(request)
    body = await request.json()
    token = (body.get('token') or '').strip()
    if not token:
        raise HTTPException(400, '缺少 token')
    from core import share as _share
    return {'ok': _share.revoke(token)}

@router.post('/api/settings')
async def settings(request: Request):
    _a.guard_admin(request)
    body = await request.json()
    # V15.8.3：设置页的「网关地址/模型」合并写入通道池，不再往 gateway 顶层
    # 写第二份快照——两个表单各写一份正是「改了地址还打老地址」的来源。
    cfg = _reg.raw_config()
    cfg, _ = _reg.normalize(cfg)
    gw = body.get('gateway') or {}
    if gw.get('base_url') or gw.get('model'):
        _pid = _reg.active_provider_id(cfg)
        _entry = (cfg.setdefault('gateway', {}).setdefault('providers', {})
                  .setdefault(_pid, {}))
        if gw.get('base_url'):
            _entry['base_url'] = gw['base_url'].strip().rstrip('/')
        if gw.get('model'):
            _entry['model'] = gw['model'].strip()
    if body.get('keywords') is not None:
        cfg.setdefault('topics', {})['keywords'] = [k.strip() for k in body['keywords'] if k.strip()]
    if body.get('image'):
        cfg['image'] = {**cfg.get('image', {}), **body['image']}
    if body.get('quality'):
        cfg['quality'] = {**cfg.get('quality', {}), **body['quality']}
    if body.get('creation'):
        cfg['creation'] = {**cfg.get('creation', {}), **body['creation']}
    if 'draft_expire_days' in body:
        cfg.setdefault('creation', {})['draft_expire_days'] = int(body['draft_expire_days'])
    if body.get('imgbed'):
        ib = body['imgbed']
        if ib.get('token'):
            _a.write_env('GITHUB_IMGBED_TOKEN', ib['token'].strip())
        if ib.get('repo'):
            _a.write_env('GITHUB_IMGBED_REPO', ib['repo'].strip())
    if body.get('dingtalk'):
        if body['dingtalk'].get('webhook'):
            _a.write_env('DINGTALK_WEBHOOK', body['dingtalk']['webhook'].strip())
        if body['dingtalk'].get('secret'):
            _a.write_env('DINGTALK_SECRET', body['dingtalk']['secret'].strip())
    if body.get('agents'):
        base = cfg.get('agents', {})
        for stage, patch in body['agents'].items():
            base[stage] = {**base.get(stage, {}), **patch}
        cfg['agents'] = base
    _reg.write_config(cfg)
    if body.get('apipool_key'):
        # 全局键位统一由 registry 写入（用户目录 0600），避免再出现「写一处、读一处」
        _reg.set_key(_reg.active_provider_id(cfg), body['apipool_key'].strip(), also_global=True)
    return {'ok': True}

@router.get('/api/diagnostics/stats')
def diagnostics_stats(request: Request):
    _a.guard(request)
    return {'ok': True, **diag.stats()}

@router.get('/api/diagnostics/log')
def diagnostics_log(request: Request, limit: int=300, only_problems: int=0):
    """导出诊断日志文本（供「设置 → 系统诊断日志」一键复制）。"""
    _a.guard(request)
    limit = max(20, min(int(limit or 300), 2000))
    text = diag.snapshot(limit=limit, only_problems=bool(only_problems))
    return {'ok': True, 'text': text, 'stats': diag.stats()}

@router.post('/api/diagnostics/clear')
def diagnostics_clear(request: Request):
    _a.guard(request)
    diag.clear()
    diag.record('system', 'diagnostics_cleared', status='ok', detail='用户手动清空诊断日志')
    return {'ok': True}

