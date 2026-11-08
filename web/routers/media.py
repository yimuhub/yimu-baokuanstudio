# SPDX-License-Identifier: BUSL-1.1
"""音视频 / 广告片 / AI 视频 / 数字人 / 小红书发布路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

@router.get('/api/xhspub/status')
def xhspub_status(request: Request):
    _a.guard(request)
    from core import xhspub
    return {'available': xhspub.available(), 'logged': xhspub.logged_in()}

@router.get('/api/xhspub/qrcode')
async def xhspub_qrcode(request: Request):
    _a.guard(request)
    from core import xhspub
    return await asyncio.get_event_loop().run_in_executor(None, xhspub.get_qrcode)

@router.post('/api/xhspub/login')
async def xhspub_login(request: Request):
    _a.guard(request)
    from core import xhspub
    import uuid
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {'step': '弹出浏览器中…', 'status': 'running', 'result': None, 'error': ''}

    def _run():
        try:
            res = xhspub.login(emit=lambda m: JOBS[jid].update(step=m))
            JOBS[jid].update(status='done', step='完成', result=res)
        except Exception as e:
            JOBS[jid].update(status='failed', error=str(e)[:300], step='失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.get('/api/video/tasks')
def video_tasks(request: Request):
    _a.guard(request)
    from core import video
    return {'tasks': video.recent_tasks()}

@router.get('/api/video/file/{tid}')
def video_file(tid: str, request: Request):
    _a.guard(request)
    if '/' in tid or '..' in tid:
        raise HTTPException(400, 'bad tid')
    candidates = []
    native_dir = _a.BASE / 'runs' / 'videos' / tid
    if native_dir.exists():
        candidates.extend(sorted(native_dir.glob('final-*.mp4')))
    aiv_dir = _a.BASE / 'runs' / 'ai_video' / tid
    if not candidates and aiv_dir.exists():
        candidates.extend(sorted(aiv_dir.glob('final-*.mp4')))
    f = candidates[0] if candidates else None
    if not f or not f.exists():
        raise HTTPException(404, '成片不存在')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='video/mp4', filename=f'{tid}.mp4')

@router.post('/api/audio/make')
async def audio_make(request: Request):
    u = _a.guard(request)
    body = await request.json()
    did = body.get('draft_id')
    if not did:
        raise HTTPException(400, '请选择草稿')
    script = body.get('script', '')
    _allowed, _reason, _tier = _a._tier_quota_check(u, 'tts_daily')
    if not _allowed:
        raise HTTPException(402, _reason)
    _max_chars = _a._tier_capability_limit(u, 'tts_max_chars')
    if isinstance(_max_chars, int) and _max_chars > 0 and (len(script) > _max_chars):
        raise HTTPException(400, f'当前档位单次配音最多 {_max_chars} 字（本次 {len(script)} 字），升级 Pro 解锁不限字数')
    d = db.get_draft(did) or {}
    d_title = d.get('title', did[:8])
    import uuid
    jid = f'aud-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'AI 配音TTS合成: {d_title[:16]}', task_type='audio_tts', target_id=did, params={'draft_id': did}, initial_step='AI 配音合成初始化中…')

    def _run():
        try:
            from core import audio
            res = audio.make_audio(did, int(body.get('seconds', 30)), body.get('platform', 'xhs'), body.get('subject', ''), emit=lambda m: update_async_job(jid, step=m), custom_script=script)
            update_async_job(jid, status='done', step='AI 配音TTS合成完成', progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status='failed', error=str(e)[:300], step='配音合成失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.get('/api/audio/file/{did}/{name}')
def audio_file(did: str, name: str, request: Request):
    _a.guard(request)
    if '/' in name or '..' in name or (not name.startswith('audio-')):
        raise HTTPException(400, 'bad name')
    f = db.draft_dir(did) / name
    if not f.exists():
        raise HTTPException(404, '音频不存在')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='audio/mpeg', filename=name)

@router.post('/api/video/upload_bgm')
async def video_upload_bgm(request: Request, file: UploadFile=File(...)):
    """上传本地背景音乐（.mp3, .wav 等）。R10.0：经统一上传守卫落盘，修复历史路径穿越。"""
    _a.guard(request)
    import pathlib
    from core.upload_guard import AUDIO_EXTS, save_upload
    bgm_dir = pathlib.Path('data/bgm_uploads')
    try:
        dest, orig_name = await save_upload(file, bgm_dir, 'bgm', AUDIO_EXTS, max_mb=80)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f'BGM上传失败: {e}')
    return {'ok': True, 'filename': dest.name, 'path': str(dest.resolve()), 'name': orig_name}

@router.post('/api/video/upload_material')
async def video_upload_material(request: Request, file: UploadFile=File(...)):
    """上传本地图片或视频素材作为画面来源。R10.0：经统一上传守卫落盘，修复历史路径穿越。"""
    _a.guard(request)
    import pathlib
    from core.upload_guard import IMAGE_EXTS, VIDEO_EXTS, save_upload
    mat_dir = pathlib.Path('data/material_uploads')
    try:
        dest, orig_name = await save_upload(file, mat_dir, 'mat', IMAGE_EXTS + VIDEO_EXTS, max_mb=200)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f'素材上传失败: {e}')
    return {'ok': True, 'filename': dest.name, 'path': str(dest.resolve()), 'name': orig_name}

@router.post('/api/video/make')
async def video_make(request: Request):
    _a.guard(request)
    body = await request.json()
    did = body.get('draft_id')
    if not did:
        raise HTTPException(400, '请选择草稿')
    script = body.get('script', '')
    bgm_type = body.get('bgm_type', 'random')
    bgm_volume = float(body.get('bgm_volume', 0.2))
    bgm_file = body.get('bgm_file', '')
    subtitle_enabled = body.get('subtitle_enabled', True)
    subtitle_position = body.get('subtitle_position', 'bottom')
    text_fore_color = body.get('text_fore_color', '#FFFFFF')
    material_source = body.get('material_source', 'pexels')
    custom_materials = body.get('video_materials', [])
    materials = []
    if material_source == 'draft_images':
        import pathlib
        draft_img_dir = pathlib.Path(f'data/drafts/{did}/img')
        if draft_img_dir.exists():
            for img in sorted(draft_img_dir.glob('*.png')):
                materials.append(str(img.resolve()))
    elif material_source == 'asset_library':
        import pathlib
        drafts_dir = pathlib.Path('data/drafts')
        if drafts_dir.exists():
            for ddir in sorted(drafts_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                img_dir = ddir / 'img'
                if img_dir.exists():
                    for img in sorted(img_dir.glob('*.png')):
                        materials.append(str(img.resolve()))
    elif material_source == 'local' and custom_materials:
        materials = custom_materials
    d = db.get_draft(did) or {}
    d_title = d.get('title', did[:8])
    import uuid
    jid = f'vid-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'短视频合成: {d_title[:16]}', task_type='video_render', target_id=did, params={'draft_id': did}, initial_step='短视频渲染管线初始化…')

    def _run():
        try:
            from core import video
            res = video.make_video(did, int(body.get('seconds', 15)), body.get('subject', ''), emit=lambda m: update_async_job(jid, step=m), platform=body.get('platform', 'douyin'), aspect=body.get('aspect', ''), voice=body.get('voice', ''), custom_script=script, bgm_type=bgm_type, bgm_volume=bgm_volume, bgm_file=bgm_file, subtitle_enabled=subtitle_enabled, subtitle_position=subtitle_position, text_fore_color=text_fore_color, video_materials=materials)
            update_async_job(jid, status='done', step='短视频混剪合成完成！', progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status='failed', error=str(e)[:300], step='短视频生成失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.get('/api/advideo/ref_file')
def advideo_ref_file(request: Request, path: str=''):
    """AI 广告短片：serving 上传的参考图/音频（预览用）。"""
    _a.guard(request)
    import pathlib
    from fastapi.responses import FileResponse
    p = pathlib.Path(path)
    try:
        rp = p.resolve()
        allowed = [pathlib.Path('runs/advideo_refs').resolve(), pathlib.Path('runs/advideo_audio').resolve(), pathlib.Path('runs/avatars').resolve()]
        if not any((str(rp).startswith(str(a)) for a in allowed)):
            raise HTTPException(403, '非法路径')
        if not rp.exists():
            raise HTTPException(404, '文件不存在')
        return FileResponse(str(rp))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f'读取失败: {e}')

@router.post('/api/advideo/selling_points')
async def advideo_selling_points(request: Request):
    """AI 广告短片：单独生成卖点（供前端预览/编辑/重新生成）。"""
    _a.guard(request)
    body = await request.json()
    product_name = (body.get('product_name') or '').strip()
    product_desc = (body.get('product_desc') or '').strip()
    audience = (body.get('audience') or '大众消费者').strip()
    if not product_name or not product_desc:
        raise HTTPException(400, '请填写产品名称和产品描述')
    from core import ad_video
    sp = ad_video.extract_selling_points(product_name, product_desc, audience)
    return {'points': sp['points'], 'pain': sp.get('pain', '')}

@router.post('/api/advideo/upload_ref')
async def advideo_upload_ref(request: Request, file: UploadFile=File(...)):
    """AI 广告短片：上传产品/人物参考图。"""
    _a.guard(request)
    import pathlib, shutil, uuid
    ref_dir = pathlib.Path('runs/advideo_refs')
    ref_dir.mkdir(parents=True, exist_ok=True)
    ext = pathlib.Path(file.filename or '').suffix.lower() or '.jpg'
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        raise HTTPException(400, '只支持 jpg/png/webp 图片')
    safe_name = f'ref_{uuid.uuid4().hex[:8]}{ext}'
    dest = ref_dir / safe_name
    try:
        contents = await file.read()
        if len(contents) > 20 * 1024 * 1024:
            raise HTTPException(400, '参考图超过 20MB 限制')
        dest.write_bytes(contents)
        return {'ok': True, 'path': str(dest.resolve()), 'name': file.filename}
    except Exception as e:
        raise HTTPException(500, f'参考图上传失败: {e}')

@router.post('/api/advideo/upload_audio')
async def advideo_upload_audio(request: Request, file: UploadFile=File(...)):
    """AI 广告短片：上传配音音频（mp3/wav）。"""
    _a.guard(request)
    import pathlib, shutil, uuid
    audio_dir = pathlib.Path('runs/advideo_audio')
    audio_dir.mkdir(parents=True, exist_ok=True)
    ext = pathlib.Path(file.filename or '').suffix.lower() or '.mp3'
    if ext not in ('.mp3', '.wav', '.m4a'):
        raise HTTPException(400, '只支持 mp3/wav/m4a 音频')
    safe_name = f'audio_{uuid.uuid4().hex[:8]}{ext}'
    dest = audio_dir / safe_name
    try:
        contents = await file.read()
        if len(contents) > 80 * 1024 * 1024:
            raise HTTPException(400, '配音音频超过 80MB 限制')
        dest.write_bytes(contents)
        return {'ok': True, 'path': str(dest.resolve()), 'name': file.filename}
    except Exception as e:
        raise HTTPException(500, f'音频上传失败: {e}')

@router.post('/api/advideo/script_rewrite')
async def advideo_script_rewrite(request: Request):
    """AI 广告短片：一键改写/生成高转化数字人口播话术。"""
    _a.guard(request)
    body = await request.json()
    product_name = (body.get('product_name') or '').strip()
    product_desc = (body.get('product_desc') or '').strip()
    if not product_name:
        raise HTTPException(400, '请填写产品名称')
    selling_points = body.get('selling_points') or None
    audience = body.get('audience') or '大众消费者'
    ad_mode = body.get('ad_mode') or 'avatar'
    seconds = int(body.get('seconds') or 15)
    from core import ad_video
    try:
        res = ad_video.rewrite_ad_script(product_name=product_name, product_desc=product_desc, selling_points=selling_points, audience=audience, ad_mode=ad_mode, seconds=seconds)
        return res
    except Exception as e:
        log.exception('[admin] advideo script_rewrite 异常: %s', e)
        raise HTTPException(500, f'广告话术生成失败: {e}')

@router.post('/api/advideo/create')
async def advideo_create(request: Request):
    """AI 产品广告短片：一键生成（卖点提炼→广告脚本/数字人口播→分镜→合成）。"""
    _a.guard(request)
    body = await request.json()
    product_name = (body.get('product_name') or '').strip()
    if not product_name:
        raise HTTPException(400, '请填写产品名称')
    product_desc = (body.get('product_desc') or '').strip()
    if not product_desc:
        raise HTTPException(400, '请填写产品描述')
    seconds = int(body.get('seconds', 15))
    aspect = body.get('aspect', '9:16')
    audience = body.get('audience', '大众消费者')
    voice = body.get('voice', 'zh-CN-XiaoxiaoNeural')
    selling_points = body.get('selling_points') or None
    ref_images = body.get('ref_images') or None
    person_ref_image = body.get('person_ref_image') or None
    voice_mode = body.get('voice_mode', 'auto')
    custom_audio_path = body.get('custom_audio_path') or None
    ad_mode = body.get('ad_mode', 'avatar')
    custom_script = (body.get('custom_script') or '').strip()
    video_model = (body.get('video_model') or '').strip()
    import uuid
    jid = f'ad-{uuid.uuid4().hex[:8]}'
    _a.start_async_job(jid, name=f'AI 广告短片: {product_name[:16]}', task_type='ad_video_render', target_id=product_name, params={'product_name': product_name, 'ad_mode': ad_mode, 'video_model': video_model}, initial_step='广告创意生成中…')

    def _run():
        try:
            from core import ad_video
            res = ad_video.make_ad_video(product_name, product_desc, seconds=seconds, aspect=aspect, audience=audience, voice=voice, selling_points=selling_points, ref_images=ref_images, person_ref_image=person_ref_image, voice_mode=voice_mode, custom_audio_path=custom_audio_path, ad_mode=ad_mode, custom_script=custom_script, video_model=video_model, emit=lambda m: update_async_job(jid, step=m))
            update_async_job(jid, status='done', step='广告短片合成完成！', progress=100, result=res)
        except Exception as e:
            log_exc = str(e)[:300]
            update_async_job(jid, status='failed', error=log_exc, step='广告短片生成失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.get('/api/aivideo/rewrite/modes')
def aivideo_rewrite_modes(request: Request):
    """获取所有 AI 短视频改写模式列表及说明。"""
    _a.guard(request)
    from core import video_script_rewriter
    return {'ok': True, 'modes': video_script_rewriter.get_rewrite_modes()}

@router.post('/api/aivideo/rewrite')
async def aivideo_rewrite(request: Request):
    """AI 短视频文案多模式智能改写：新闻播报/数字人口播/视频堆积切片/悬念反转/带货种草等。"""
    u = _a.guard(request)
    body = await request.json()
    content = (body.get('content') or '').strip()
    if not content:
        raise HTTPException(400, '请提供待改写的原文或草稿文案')
    mode = (body.get('mode') or 'avatar').strip()
    target_seconds = int(body.get('target_seconds') or 30)
    custom_instruction = (body.get('custom_instruction') or '').strip()
    model = (body.get('model') or '').strip()
    user_id = str((u or {}).get('id') or '')
    from core import video_script_rewriter
    try:
        res = video_script_rewriter.rewrite_video_script(content=content, mode=mode, target_seconds=target_seconds, custom_instruction=custom_instruction, model=model if model else None, user_id=user_id if user_id else None)
        return res
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        log.exception('[admin] aivideo rewrite 失败: %s', e)
        raise HTTPException(500, f'AI 文案改写失败: {e}')

@router.post('/api/aivideo/upload_avatar')
@router.post('/api/video/upload_avatar')
@router.post('/api/advideo/upload_avatar')
async def aivideo_upload_avatar(request: Request, file: UploadFile=File(...)):
    """AI 短视频/数字人：上传出镜肖像照片。"""
    _a.guard(request)
    import pathlib, shutil, uuid
    av_dir = pathlib.Path('runs/avatars')
    av_dir.mkdir(parents=True, exist_ok=True)
    ext = pathlib.Path(file.filename or '').suffix.lower() or '.jpg'
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        raise HTTPException(400, '仅支持 jpg/jpeg/png/webp 格式的人物照片')
    safe_name = f'avatar_{uuid.uuid4().hex[:10]}{ext}'
    dest = av_dir / safe_name
    try:
        contents = await file.read()
        if len(contents) > 20 * 1024 * 1024:
            raise HTTPException(400, '人物照片超过 20MB 限制')
        dest.write_bytes(contents)
        desc = ''
        try:
            from core.ad_video import analyze_reference_images
            vinfo = analyze_reference_images(person_ref_image=str(dest.resolve()))
            desc = vinfo.get('person_desc') or vinfo.get('style_desc') or ''
        except Exception:
            pass
        try:
            from studio import avatar_memory
            avatar_memory.save_avatar(path=str(dest.resolve()), filename=dest.name, url=f'/api/aivideo/avatar/{dest.name}', name=f'形象 {file.filename[:12]}', person_desc=desc or '专属定制 AI 数字人出镜肖像')
        except Exception:
            pass
        return {'ok': True, 'path': str(dest.resolve()), 'url': f'/api/aivideo/avatar/{dest.name}', 'filename': file.filename, 'person_desc': desc}
    except Exception as e:
        raise HTTPException(500, f'照片上传失败: {e}')

@router.get('/api/aivideo/avatars')
def aivideo_list_avatars(request: Request):
    """获取所有历史已记住的数字人形象列表（按最近使用排序）。"""
    _a.guard(request)
    from studio import avatar_memory
    items = avatar_memory.list_avatars()
    return {'ok': True, 'items': items}

@router.post('/api/aivideo/avatars/use')
async def aivideo_use_avatar(request: Request):
    """一键复用选中的历史数字人形象。"""
    _a.guard(request)
    body = await request.json()
    av_id = (body.get('id') or '').strip()
    from studio import avatar_memory
    item = avatar_memory.use_avatar(av_id)
    if not item:
        raise HTTPException(404, '数字人形象不存在')
    return {'ok': True, 'item': item}

@router.post('/api/aivideo/avatars/update')
async def aivideo_update_avatar(request: Request):
    """更新数字人形象名称或特征描述。"""
    _a.guard(request)
    body = await request.json()
    av_id = (body.get('id') or '').strip()
    name = (body.get('name') or '').strip()
    desc = (body.get('person_desc') or '').strip()
    from studio import avatar_memory
    item = avatar_memory.update_avatar(av_id, name=name, person_desc=desc)
    if not item:
        raise HTTPException(404, '数字人形象不存在')
    return {'ok': True, 'item': item}

@router.delete('/api/aivideo/avatars/{avatar_id}')
def aivideo_delete_avatar(avatar_id: str, request: Request):
    """从形象记忆库删除数字人。"""
    _a.guard(request)
    from studio import avatar_memory
    ok = avatar_memory.delete_avatar(avatar_id)
    return {'ok': ok}

@router.post('/api/video/test_voice_clone')
async def video_test_voice_clone(request: Request):
    """测试声音克隆 API 连接并生成简短测试试听音频。"""
    _a.guard(request)
    body = await request.json()
    api_url = (body.get('api_url') or '').strip()
    api_key = (body.get('api_key') or '').strip()
    provider = (body.get('provider') or 'custom').strip().lower()
    model = (body.get('model') or '').strip()
    voice_id = (body.get('voice_id') or '').strip()
    text = (body.get('text') or '您好，这是一幕爆款工作室声音克隆 API 的实时连通性测试语音。').strip()
    from studio import video_config as _vc
    cur_cfg = _vc.get_config()
    final_url = api_url or cur_cfg.get('voice_clone_api_url')
    final_key = api_key or cur_cfg.get('voice_clone_api_key')
    final_prov = provider or cur_cfg.get('voice_clone_provider') or 'custom'
    final_model = model or cur_cfg.get('voice_clone_model')
    final_voice = voice_id or cur_cfg.get('voice_clone_voice_id') or 'default'
    if not final_url:
        raise HTTPException(400, '请先填写声音克隆 API 地址')
    import pathlib, uuid, httpx, json as _json, base64 as _b64
    out_dir = pathlib.Path('runs/advideo_audio')
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f'test_vc_{uuid.uuid4().hex[:8]}.mp3'
    headers = {'Content-Type': 'application/json'}
    if final_key:
        headers['Authorization'] = f'Bearer {final_key}'
    if final_prov == 'minimax':
        payload = {'model': final_model or 'speech-01-turbo', 'text': text, 'voice_setting': {'voice_id': final_voice}, 'audio_setting': {'sample_rate': 24000, 'format': 'mp3'}}
    elif final_prov == 'elevenlabs':
        payload = {'text': text, 'model_id': final_model or 'eleven_multilingual_v2'}
    elif final_prov == 'cosyvoice':
        payload = {'model': final_model or 'cosyvoice-v1', 'input': text, 'voice': final_voice}
    else:
        payload = {'text': text, 'input': text, 'model': final_model, 'voice': final_voice}
    try:
        with httpx.Client(timeout=45, follow_redirects=True) as client:
            resp = client.post(final_url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, f'声音克隆服务返回 HTTP {resp.status_code}: {resp.text[:200]}')
            data = resp.content
            if resp.headers.get('content-type', '').startswith('application/json') or data.startswith(b'{'):
                try:
                    jd = resp.json()
                    b64_str = jd.get('audio') or jd.get('audio_content') or (jd.get('data') or {}).get('audio') or ((jd.get('data') or [{}])[0] if isinstance(jd.get('data'), list) else {}).get('b64_json')
                    if b64_str:
                        data = _b64.b64decode(b64_str)
                except Exception:
                    pass
            if len(data) < 200:
                raise HTTPException(502, '克隆服务返回音频无效或数据过小')
            out_file.write_bytes(data)
            return {'ok': True, 'audio_url': f'/api/advideo/ref_file?path={out_file.resolve()}', 'size_kb': len(data) // 1024, 'msg': f'声音克隆测试成功！已生成试听音频（{len(data) // 1024} KB）'}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f'声音克隆连接测试失败: {exc}')

@router.get('/api/aivideo/avatar/{filename}')
@router.get('/api/video/avatar/{filename}')
def aivideo_avatar_file(filename: str, request: Request):
    """预览上传的数字人照片。"""
    _a.guard(request)
    import pathlib
    from fastapi.responses import FileResponse
    p = (pathlib.Path('runs/avatars') / filename).resolve()
    base = pathlib.Path('runs/avatars').resolve()
    if not str(p).startswith(str(base)) or not p.exists():
        raise HTTPException(404, '照片不存在')
    return FileResponse(p)

@router.post('/api/aivideo/create')
async def aivideo_create(request: Request):
    """AI 短视频生成：口播文案 → 视频大模型分段生成（支持照片参考图驱动数字人与声音克隆） → 拼接成片。"""
    u = _a.guard(request)
    body = await request.json()
    script = (body.get('script') or '').strip()
    if not script:
        raise HTTPException(400, '请填写口播文案')
    total_seconds = int(body.get('total_seconds') or 30)
    aspect = body.get('aspect', '9:16')
    video_model = (body.get('video_model') or '').strip()
    avatar_image = (body.get('avatar_image') or '').strip()
    voice_engine = (body.get('voice_engine') or 'tts').strip()
    voice_audio = (body.get('voice_audio') or '').strip()
    title = (body.get('title') or script[:16]).strip()
    from core import ai_video_gen
    from studio import ai_video_config as _acfg
    _seg_s = int(_acfg.get_config()['segment_seconds'])
    _segs = ai_video_gen.plan_segments(total_seconds if total_seconds > 0 else 30, _seg_s)
    jid = ai_video_gen.start_ai_video_job(script, total_seconds=total_seconds, aspect=aspect, video_model=video_model, title=title, user_id=str((u or {}).get('id') or ''), avatar_image=avatar_image, voice_engine=voice_engine, voice_audio=voice_audio)
    return {'job': jid, 'segments': len(_segs), 'plan': f'将分成 {len(_segs)} 段生成' + ('（基于专属照片驱动数字人）' if avatar_image else '') + ('（声音克隆配音）' if voice_engine == 'voice_clone' else '')}

@router.get('/api/aivideo/config')
def aivideo_config_get(request: Request):
    _a.guard(request)
    from studio import ai_video_config as _acfg
    return _acfg.get_config()

@router.put('/api/aivideo/config')
async def aivideo_config_put(request: Request):
    _a.guard(request)
    body = await request.json()
    from studio import ai_video_config as _acfg
    return _acfg.save_config(body or {})

@router.get('/api/aivideo/file/{jid}')
def aivideo_file(jid: str, request: Request):
    """下载/预览生成的 AI 短视频。"""
    _a.guard(request)
    from pathlib import Path as _P
    base = _P(__file__).resolve().parent.parent / 'runs' / 'ai_video' / jid
    if not str(base.resolve()).startswith(str(base.parent.resolve())):
        raise HTTPException(400, '非法路径')
    for _f in base.glob('final-*.mp4'):
        from fastapi.responses import FileResponse
        return FileResponse(str(_f), media_type='video/mp4', filename=f'ai-video-{jid}.mp4')
    raise HTTPException(404, '成片尚未生成')

@router.get('/api/video/drama/{did}/scenes')
def drama_scenes(did: str, request: Request):
    _a.guard(request)
    from core import short_drama
    return {'scenes': short_drama.get_drama_scenes(did)}

@router.post('/api/video/drama/{did}/decompose')
async def drama_decompose(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    style = body.get('style', 'cinematic')
    script = body.get('script', '')
    mounted_persona = body.get('mounted_persona', '')
    from core import short_drama
    _a.require_credits('drama_decompose', 1, f'短剧分镜解构 [{did}]')

    def _run():
        return short_drama.decompose_draft_to_drama(did, style_key=style, custom_script=script, mounted_persona=mounted_persona)
    try:
        scenes = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'scenes': scenes}
    except Exception as e:
        raise HTTPException(500, f'短剧分镜解构失败: {e}')

@router.post('/api/video/upload_script_file')
async def video_upload_script_file(request: Request, file: UploadFile=File(...)):
    """上传本地文本文档（.txt, .md, .docx 等），提取纯文口播稿内容"""
    _a.guard(request)
    try:
        contents = await file.read()
        filename = (file.filename or '').lower()
        text = ''
        if filename.endswith('.docx'):
            try:
                import io, zipfile, xml.etree.ElementTree as ET
                with zipfile.ZipFile(io.BytesIO(contents)) as z:
                    xml_content = z.read('word/document.xml')
                    tree = ET.fromstring(xml_content)
                    paragraphs = []
                    for p in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                        texts = [node.text for node in p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if node.text]
                        if texts:
                            paragraphs.append(''.join(texts))
                    text = '\n\n'.join(paragraphs)
            except Exception:
                text = contents.decode('utf-8', errors='ignore')
        else:
            text = contents.decode('utf-8', errors='ignore')
        import re
        cleaned = re.sub('!\\[.*?\\]\\(.*?\\)', '', text)
        cleaned = re.sub('\\[([^\\]]*)\\]\\([^)]*\\)', '\\1', cleaned)
        cleaned = re.sub('^#{1,6}\\s+(.+)$', '\\n\\1\\n', cleaned, flags=re.MULTILINE)
        cleaned = re.sub('\\*\\*(.+?)\\*\\*', '\\1', cleaned)
        cleaned = re.sub('\\*(.+?)\\*', '\\1', cleaned)
        cleaned = re.sub('`{1,3}[^`]*`{1,3}', '', cleaned)
        cleaned = re.sub('^[-*>]\\s+', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub('\\n{3,}', '\n\n', cleaned).strip()
        return {'ok': True, 'filename': file.filename, 'text': cleaned, 'char_count': len(cleaned.replace(' ', '').replace('\n', ''))}
    except Exception as e:
        raise HTTPException(500, f'文档解析失败: {e}')

@router.post('/api/video/drama/{did}/gen_image')
async def drama_gen_image(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    shot_id = int(body.get('shot_id', 1))
    prompt_en = body.get('prompt_en', '')
    aspect = body.get('aspect', '9:16')
    from core import short_drama
    _a.require_credits('drama_image', 1, f'短剧分镜生图 #{shot_id}')

    def _run():
        return short_drama.generate_scene_image(did, shot_id, prompt_en, aspect=aspect)
    try:
        url = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'image_url': url, 'shot_id': shot_id}
    except Exception as e:
        raise HTTPException(500, f'分镜参考生图失败: {e}')

@router.post('/api/video/drama/{did}/batch_gen_images')
async def drama_batch_gen_images(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    aspect = body.get('aspect', '9:16')
    from core import short_drama

    def _run():
        return short_drama.batch_generate_drama_images(did, aspect=aspect)
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'results': results}
    except Exception as e:
        raise HTTPException(500, f'批量生图失败: {e}')

@router.post('/api/video/drama/{did}/update_scene')
async def drama_update_scene(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    shot_id = int(body.get('shot_id', 1))
    updates = body.get('updates', {})
    from core import short_drama
    res = short_drama.update_drama_scene(did, shot_id, updates)
    return {'ok': True, 'scene': res}

@router.post('/api/video/drama/{did}/preview_audio')
async def drama_preview_audio(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    shot_id = int(body.get('shot_id', 1))
    script = body.get('script', '')
    voice = body.get('voice', 'zh-CN-YunxiNeural')
    from core import short_drama

    def _run():
        return short_drama.synthesize_scene_tts(did, shot_id, script, voice=voice)
    try:
        url = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'audio_url': url, 'shot_id': shot_id}
    except Exception as e:
        raise HTTPException(500, f'单句语音合成失败: {e}')

@router.post('/api/video/drama/{did}/render')
async def drama_render(did: str, request: Request):
    u = _a.guard(request)
    _allowed, _reason, _tier = _a._tier_quota_check(u, 'drama_weekly')
    if not _allowed:
        raise HTTPException(402, _reason)
    body = await request.json()
    aspect = body.get('aspect', '9:16')
    d = db.get_draft(did) or {}
    d_title = d.get('title', did[:8])
    from core import short_drama
    _a.require_credits('drama_render', 1, f'全AI短剧渲染 [{did}]')
    try:
        from core import analytics
        analytics.track('first_drama_run', str((u or {}).get('id') or ''), {'draft_id': did})
    except Exception:
        pass
    import uuid
    jid = f'drm-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'全AI短剧渲染: {d_title[:16]}', task_type='drama_pipeline', target_id=did, params={'draft_id': did, 'aspect': aspect}, initial_step='短剧视频渲染队列中…')
    _cap = _a._tier_capability_limit(u, 'drama_max_seconds')
    _max_s = _cap if isinstance(_cap, int) and _cap > 0 else None

    def _run():
        try:
            res = short_drama.render_short_drama_video(did, aspect=aspect, max_total_seconds=_max_s, emit=lambda m: update_async_job(jid, step=m))
            update_async_job(jid, status='done', step='短剧成片渲染完成！', progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status='failed', error=str(e)[:400], step='短剧渲染失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.get('/api/video/drama/{did}/pipeline/project')
def drama_pipeline_get_project(did: str, request: Request):
    _a.guard(request)
    from core import short_drama
    return {'ok': True, 'project': short_drama.get_pipeline_project(did), 'styles': short_drama.DRAMA_STYLES}

@router.post('/api/video/drama/{did}/pipeline/save_project')
async def drama_pipeline_save_project(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    project_data = body.get('project', {})
    from core import short_drama
    saved = short_drama.save_pipeline_project(did, project_data)
    return {'ok': True, 'project': saved}

@router.post('/api/video/drama/{did}/pipeline/step1_analyze')
async def drama_pipeline_step1(did: str, request: Request):
    u = _a.guard(request)
    body = await request.json()
    text = body.get('text', '')
    overrides = body.get('overrides', {})
    _is_free = str((u or {}).get('role') or '') not in ('admin', 'owner')
    _pipeline_allowed = True
    if _is_free:
        _pipeline_allowed, _reason, _ = _a._tier_quota_check(u, 'drama_weekly')
        if not _pipeline_allowed:
            _shot_allowed, _shot_reason, _ = _a._tier_quota_check(u, 'drama_shot_weekly')
            if not _shot_allowed:
                raise HTTPException(402, _shot_reason or _reason)
    _cap = _a._tier_capability_limit(u, 'drama_max_seconds')
    if isinstance(_cap, int) and _cap > 0:
        try:
            _dt = int(overrides.get('duration_target') or 45)
        except (TypeError, ValueError):
            _dt = 45
        if _dt > _cap:
            overrides['duration_target'] = _cap
    from core import short_drama
    _a.require_credits('drama_decompose', 1, f'短剧需求分析与剧本改写 [{did}]')

    def _run():
        return short_drama.step1_analyze_and_rewrite(did, text=text, overrides=overrides)
    try:
        proj = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'project': proj}
    except Exception as e:
        raise HTTPException(500, f'剧本需求分析与改写失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step2_outline')
async def drama_pipeline_step2(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    updates = body.get('updates', {})
    from core import short_drama
    proj = short_drama.step2_confirm_outline(did, updates=updates)
    return {'ok': True, 'project': proj}

@router.post('/api/video/drama/{did}/pipeline/step3_assets')
async def drama_pipeline_step3(did: str, request: Request):
    _a.guard(request)
    from core import short_drama

    def _run():
        return short_drama.step3_generate_assets_specs(did)
    try:
        proj = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'project': proj}
    except Exception as e:
        raise HTTPException(500, f'资产设定规格生成失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step4_gen_asset')
async def drama_pipeline_step4_single(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    asset_type = body.get('asset_type', 'character')
    asset_id = body.get('asset_id', '')
    prompt = body.get('prompt', '')
    is_turnaround = bool(body.get('is_turnaround', False))
    aspect = body.get('aspect', '16:9')
    from core import short_drama
    _a.require_credits('drama_image', 1, f'短剧资产出图 [{asset_id}]')

    def _run():
        return short_drama.step4_generate_asset_image(did, asset_type=asset_type, asset_id=asset_id, prompt=prompt, is_turnaround=is_turnaround, aspect=aspect)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f'资产图片生成失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step4_batch_assets')
async def drama_pipeline_step4_batch(did: str, request: Request):
    _a.guard(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    image_model = (body.get('image_model') or '').strip()
    from core import short_drama
    _a.require_credits('drama_image', 2, f'短剧资产批量生成 [{did}]')

    def _run():
        return short_drama.step4_batch_generate_assets(did, image_model=image_model)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f'批量生成资产失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step5_storyboard')
async def drama_pipeline_step5(did: str, request: Request):
    u = _a.guard(request)
    from core import short_drama
    _a.require_credits('drama_decompose', 1, f'短剧好莱坞分镜解构 [{did}]')
    _cap = _a._tier_capability_limit(u, 'drama_max_seconds')
    _max_s = _cap if isinstance(_cap, int) and _cap > 0 else None

    def _run():
        return short_drama.step5_generate_storyboard(did, max_total_seconds=_max_s)
    try:
        shots = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'shots': shots, 'project': short_drama.get_pipeline_project(did)}
    except Exception as e:
        raise HTTPException(500, f'分镜解构失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step6_gen_shot')
async def drama_pipeline_step6_single(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    shot_id = int(body.get('shot_id', 1))
    prompt_en = body.get('prompt_en', '')
    aspect = body.get('aspect', '9:16')
    image_model = (body.get('image_model') or '').strip()
    from core import short_drama
    _a.require_credits('drama_image', 1, f'分镜头 #{shot_id} 生图')

    def _run():
        return short_drama.step6_generate_shot_image(did, shot_id=shot_id, prompt_en=prompt_en, aspect=aspect, image_model=image_model)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f'分镜生图失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step6_batch_shots')
async def drama_pipeline_step6_batch(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    aspect = body.get('aspect', '9:16')
    image_model = (body.get('image_model') or '').strip()
    from core import short_drama

    def _run():
        return short_drama.step6_batch_generate_shots(did, aspect=aspect, image_model=image_model)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f'批量生成分镜图失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step7_gen_video')
async def drama_pipeline_step7_single(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    shot_id = int(body.get('shot_id', 1))
    aspect = body.get('aspect', '9:16')
    subtitle_enabled = body.get('subtitle_enabled', None)
    video_mode = body.get('video_mode', 'ai_video')
    video_model = (body.get('video_model') or '').strip()
    from core import short_drama

    def _run():
        return short_drama.step7_generate_shot_video(did, shot_id=shot_id, aspect=aspect, subtitle_enabled=subtitle_enabled, video_mode=video_mode, video_model=video_model)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f'生成分镜切片视频失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step7_batch_videos')
async def drama_pipeline_step7_batch(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    aspect = body.get('aspect', '9:16')
    subtitle_enabled = body.get('subtitle_enabled', None)
    video_mode = body.get('video_mode', 'ai_video')
    video_model = (body.get('video_model') or '').strip()
    from core import short_drama

    def _run():
        return short_drama.step7_batch_generate_videos(did, aspect=aspect, subtitle_enabled=subtitle_enabled, video_mode=video_mode, video_model=video_model)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f'批量生成镜头视频切片失败: {e}')

@router.post('/api/video/drama/{did}/pipeline/step8_render')
async def drama_pipeline_step8(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    aspect = body.get('aspect', '9:16')
    subtitle_enabled = body.get('subtitle_enabled', None)
    video_mode = body.get('video_mode', 'ai_video')
    video_model = (body.get('video_model') or '').strip()
    d = db.get_draft(did) or {}
    d_title = d.get('title', did[:8])
    from core import short_drama
    _a.require_credits('drama_render', 1, f'8步短剧最终成片合成 [{did}]')
    import uuid
    jid = f'drm-p8-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'8步短剧最终成片合成: {d_title[:16]}', task_type='drama_pipeline', target_id=did, params={'draft_id': did, 'aspect': aspect, 'video_model': video_model}, initial_step='8步短剧流水线成片合成中…')

    def _run():
        try:
            res = short_drama.step8_render_final_drama(did, aspect=aspect, subtitle_enabled=subtitle_enabled, video_mode=video_mode, video_model=video_model, emit=lambda m: update_async_job(jid, step=m))
            update_async_job(jid, status='done', step='短剧全流程流水线成片合成完成！', progress=100, result=res)
        except Exception as e:
            update_async_job(jid, status='failed', error=str(e)[:400], step='短剧合成失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.get('/api/video/status')
def video_status(request: Request):
    _a.guard(request)
    import socket
    running = False
    try:
        with socket.create_connection(('127.0.0.1', 8501), timeout=1):
            running = True
    except Exception:
        pass
    return {'installed': (_a.MPT_DIR / 'webui' / 'Main.py').exists(), 'running': running}

@router.post('/api/video/launch')
async def video_launch(request: Request):
    _a.guard(request)
    if not (_a.MPT_DIR / 'webui' / 'Main.py').exists():
        raise HTTPException(400, 'MoneyPrinterTurbo 未安装')
    import subprocess
    subprocess.Popen([str(_a.MPT_DIR / '.venv' / 'bin' / 'python'), '-m', 'streamlit', 'run', str(_a.MPT_DIR / 'webui' / 'Main.py'), '--server.port', '8501', '--server.headless', 'true'], cwd=str(_a.MPT_DIR), stdout=open(_a.BASE / 'logs' / 'mpt.out', 'w'), stderr=subprocess.STDOUT)
    return {'ok': True, 'url': 'http://127.0.0.1:8501'}

