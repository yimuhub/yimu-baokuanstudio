# SPDX-License-Identifier: BUSL-1.1
"""草稿工作台(含配图/排版/发布/短剧分镜)路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

from web.draft_guard import DraftOwnerRoute, SAFE_DID_RE  # noqa: E402  稳定类身份 / did 白名单
router = APIRouter(route_class=DraftOwnerRoute)  # {did} 归属校验路由类

from adapters.base import PLATFORMS, NAMES  # noqa: E402,F811
from core import db, judge, orchestrator  # noqa: E402,F811
from core import diagnostics as diag  # noqa: E402,F811
from core.llm import load_config, load_env  # noqa: E402,F811
from core.themes import WECHAT_THEMES, XHS_CARD_STYLES  # noqa: E402,F811
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse  # noqa: E402,F811
from pathlib import Path  # noqa: E402,F811
import asyncio  # noqa: E402,F811
import re  # noqa: E402,F811
import time  # noqa: E402,F811
import uuid  # noqa: E402,F811

#: 前端平台切换条与预览 / 分享共用的六平台（含小红书）
LIST_PLATFORMS = ('wechat_mp', 'xhs', 'toutiao', 'zhihu', 'weibo', 'twitter')


@router.get('/api/drafts')
def drafts_list(request: Request, limit: int = 50, offset: int = 0):
    """R10 / F6：统一的草稿列表接口。

    历史上 ``GET /api/drafts`` 直接 404，前端只能从 ``/api/status`` 取精简摘要，
    列表与详情取数口径不一致、拿不到缩略图。这里补齐统一摘要（含缩略图地址、
    已生成的预览地址、卡片与配图计数），并保持与 ``/api/status`` 同样的归属过滤。
    """
    user = _a.guard(request)
    try:
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        limit, offset = 50, 0
    cur_ws_id = db.get_active_workspace().get('id', 'ws-default')
    rows = db.list_drafts(_a._current_user_id(user), is_admin=_a._is_admin_user(user),
                          workspace_id=cur_ws_id)
    items = []
    for d in rows[offset:offset + limit]:
        did = str(d.get('id') or '')
        try:
            view = _a._draft_view(d)
        except Exception:
            view = dict(d)
        thumb = ''
        preview_urls = {}
        try:
            ddir = db.draft_dir(did)
            if (ddir / 'img' / 'cover.png').is_file():
                thumb = f'/img/{did}/cover.png'
            else:
                cards = sorted(ddir.glob('card-*.png'))
                if cards:
                    thumb = f'/card/{did}/{cards[0].name}'
            preview_urls = {
                p: f'/preview/{did}/{p}'
                for p in LIST_PLATFORMS
                if (ddir / f'preview-{p}.html').is_file()
            }
        except OSError:
            pass
        view['thumbnail'] = thumb
        view['preview_urls'] = preview_urls
        items.append(view)
    return {'ok': True, 'total': len(rows), 'limit': limit, 'offset': offset, 'drafts': items}


@router.get('/api/drafts/{did}/images')
def draft_images(did: str, request: Request):
    _a.guard(request)
    ddir = db.draft_dir(did)
    out = []
    imgdir = ddir / 'img'
    if imgdir.exists():
        for f in sorted(imgdir.glob('*.png')):
            out.append({'name': f.stem, 'url': f'/img/{did}/{f.name}'})
    return out

@router.get('/api/drafts/{did}/images_detail')
def draft_images_detail(did: str, request: Request):
    _a.guard(request)
    from core.imagegen import get_draft_images_detail
    return get_draft_images_detail(did)

@router.post('/api/drafts/{did}/images/regenerate_one')
async def draft_images_regenerate_one(did: str, request: Request):
    """针对指定的单张配图（如 cover、sec-0、sec-1）使用自定义或默认提示词重新生成"""
    _a.guard(request)
    body = await request.json()
    name = body.get('name', 'cover')
    prompt = body.get('prompt', '')
    title = body.get('title', '')
    aspect = body.get('aspect', '1:1')
    from core import imagegen
    _a.require_credits('drama_image', 1, f'重绘文章配图 [{name}]')

    def _run():
        return imagegen.regenerate_draft_image(did, name=name, prompt=prompt, title=title, aspect=aspect)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return res
    except Exception as e:
        raise HTTPException(500, f'重绘配图失败: {e}')

@router.post('/api/drafts/{did}/images/analyze_prompts')
async def draft_images_analyze_prompts(did: str, request: Request):
    """通读全文并重新提炼生成全套配图的画面要点与结构化提示词"""
    _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    from core.imagegen import analyze_article_visual_prompts
    from core.text_denoise import extract_section_headings
    sec_meta = [(t.strip('【】').strip(), '') for t, _ in extract_section_headings(d['body_md'])]
    if not sec_meta:
        sec_meta = [('核心看点', d['title'])]

    def _run():
        return analyze_article_visual_prompts(d['title'], d['body_md'], sec_meta)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'prompts': res}
    except Exception as e:
        raise HTTPException(500, f'构思提示词失败: {e}')

@router.post('/api/drafts/{did}/images/upload_custom')
async def draft_images_upload_custom(did: str, request: Request, file: UploadFile=File(...), name: str=Form('cover')):
    """上传自定义图片替换指定配图插槽（cover / sec-0 / sec-1 …）"""
    _a.guard(request)
    import shutil, pathlib
    img_dir = pathlib.Path(f'data/drafts/{did}/img')
    img_dir.mkdir(parents=True, exist_ok=True)
    safe_name = name.replace('/', '').replace('..', '').strip() or 'cover'
    dest = img_dir / f'{safe_name}.png'
    try:
        contents = await file.read()
        if len(contents) > 20 * 1024 * 1024:
            raise HTTPException(400, '文件超过 20MB 限制')
        from PIL import Image
        import io
        img_obj = Image.open(io.BytesIO(contents))
        img_obj = img_obj.convert('RGB')
        img_obj.save(str(dest), 'PNG', quality=95)
        try:
            from core.imagegen import recompile_previews
            recompile_previews(did)
        except Exception:
            pass
        return {'ok': True, 'url': f'/img/{did}/{safe_name}.png', 'name': safe_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f'上传图片失败: {e}')

@router.post('/api/drafts/{did}/voiceover_script')
async def draft_voiceover_script(did: str, request: Request):
    """生成口播稿（去除所有图片的纯文版本，可选 AI 润色）"""
    _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    import re
    md = d.get('body_md', '')
    script = md
    script = re.sub('!\\[.*?\\]\\(.*?\\)', '', script)
    script = re.sub('\\[([^\\]]*)\\]\\([^)]*\\)', '\\1', script)
    script = re.sub('^#{1,6}\\s+(.+)$', '\\n\\1\\n', script, flags=re.MULTILINE)
    script = re.sub('\\*\\*(.+?)\\*\\*', '\\1', script)
    script = re.sub('\\*(.+?)\\*', '\\1', script)
    script = re.sub('`{1,3}[^`]*`{1,3}', '', script)
    script = re.sub('^[-*>]\\s+', '', script, flags=re.MULTILINE)
    script = re.sub('\\n{3,}', '\n\n', script)
    script = script.strip()
    return {'ok': True, 'script': script, 'title': d.get('title', ''), 'char_count': len(script.replace(' ', '').replace('\n', ''))}

@router.post('/api/drafts/{did}/images/replace_in_article')
async def draft_replace_image_in_article(did: str, request: Request):
    """将指定配图插槽的新图片 URL 替换/插入到草稿 body_md 中"""
    _a.guard(request)
    body = await request.json()
    name = body.get('name', '')
    new_url = body.get('url', '')
    label = body.get('label', '配图')
    if not name or not new_url:
        raise HTTPException(400, 'name 和 url 不能为空')
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    import re
    md = d.get('body_md', '')
    new_img_md = f'![{label}]({new_url})'
    pattern = f'!\\[[^\\]]*\\]\\(/img/{re.escape(did)}/{re.escape(name)}\\.[a-z]+\\)'
    if re.search(pattern, md):
        md = re.sub(pattern, new_img_md, md)
        action = 'replaced'
    else:
        md = md.rstrip() + f'\n\n{new_img_md}\n'
        action = 'appended'
    db.update_draft_body(did, md)
    try:
        from core.imagegen import recompile_previews
        recompile_previews(did)
    except Exception:
        pass
    return {'ok': True, 'action': action, 'new_url': new_url, 'body_md': md}

@router.get('/api/drafts/image_styles')
def get_image_styles(request: Request):
    """获取系统支持的配图视觉风格清单（古风、科技风、都市风等）"""
    _a.guard(request)
    from core.imagegen import VISUAL_STYLE_PRESETS
    styles = []
    icon_map = {'ancient_chinese': '🏛️', 'tech_cyber': '🤖', 'city_urban': '🏙️', 'swiss_minimal': '💼', 'magazine_editorial': '✨', 'documentary': '📷', 'cinematic_movie': '🎬', 'commercial_premium': '💎', 'anime_cinematic': '🌅', 'minimalist_3d': '🎨'}
    for k, v in VISUAL_STYLE_PRESETS.items():
        if k == 'chinese_ink':
            continue
        styles.append({'key': k, 'name': v.get('name', k), 'icon': icon_map.get(k, '🎨'), 'keywords': v.get('keywords', [])[:5]})
    return {'ok': True, 'styles': styles}

@router.post('/api/drafts/{did}/generate_images')
async def draft_generate_images(did: str, request: Request):
    """一键为全文智能批量生成成套插图与封面，并自动插入正文与重新渲染（支持选择配图风格与一键换图）"""
    _a.guard(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    count = int(body.get('count', 3))
    style = str(body.get('style') or '').strip()
    force_regen = bool(body.get('force_regen', False))
    model = str(body.get('model') or '').strip()
    from core.imagegen import generate_and_inject_images, VISUAL_STYLE_PRESETS
    d = db.get_draft(did) or {}
    d_title = d.get('title', did[:8])
    style_name = VISUAL_STYLE_PRESETS.get(style, {}).get('name', style) if style else '自动匹配'
    import uuid
    jid = f'img-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'全文智能配图 ({count}张·{style_name}): {d_title[:16]}', task_type='image_gen', target_id=did, params={'draft_id': did, 'count': count, 'style': style, 'model': model}, initial_step=f'正在分析段落视觉意境（风格：{style_name}）并生成 {count} 张专属高清配图…')
    try:
        _a.update_async_job(jid, step=f'AI 光学摄影渲染中（风格: {style_name}）…', progress=45)
        res = await asyncio.get_event_loop().run_in_executor(None, lambda: generate_and_inject_images(did, count=count, style=style, force_regen=force_regen or bool(style), model=model))
        _a.update_async_job(jid, status='done', step=f'成功生成 {count} 张【{style_name}】配图并已排版入文', progress=100, result=res)
        return res
    except Exception as e:
        _a.update_async_job(jid, status='failed', error=str(e)[:300], step='生图配图失败')
        raise HTTPException(500, f'生图失败: {str(e)}')

@router.post('/api/drafts/{did}/generate_single_image')
async def draft_generate_single_image(did: str, request: Request):
    """根据输入的主题或段落，单独生成一张专属高清配图"""
    _a.guard(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    title = body.get('title', '核心看点')
    prompt = body.get('prompt', '')
    from core.imagegen import generate_single_image
    import uuid
    jid = f'img-sgl-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'单张配图生成: {title[:16]}', task_type='image_gen', target_id=did, params={'draft_id': did, 'title': title, 'prompt': prompt}, initial_step='AI 摄影抓拍提示词升华与渲染中…')
    try:
        _a.update_async_job(jid, step='极速高清渲染中…', progress=50)
        res = await asyncio.get_event_loop().run_in_executor(None, lambda: generate_single_image(did, title=title, prompt=prompt))
        _a.update_async_job(jid, status='done', step='单张配图生成完成', progress=100, result=res)
        return res
    except Exception as e:
        _a.update_async_job(jid, status='failed', error=str(e)[:300], step='单张生图失败')
        raise HTTPException(500, f'生图失败: {str(e)}')

@router.post('/api/drafts/{did}/save_wechat')
async def draft_save_wechat(did: str, request: Request):
    """保存编辑器里的正文（只更新 body_md 与公众号预览，不动其它平台/AI产物）。"""
    _a.guard(request)
    body = await request.json()
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    body_md = body.get('body_md', d['body_md'])
    c = db.conn()
    c.execute('UPDATE drafts SET body_md=? WHERE id=?', (body_md, did))
    c.commit()
    c.close()
    from core.themes import md_to_wechat_html
    theme = load_config().get('creation', {}).get('wechat_theme', 'caozhou')
    theme = theme if theme in WECHAT_THEMES else 'caozhou'
    ddir = db.draft_dir(did)
    images = {f.name: f'/img/{did}/{f.name}' for f in sorted((ddir / 'img').glob('sec-*.png'))} if (ddir / 'img').exists() else {}
    cover = f'/img/{did}/cover.png' if (ddir / 'img' / 'cover.png').exists() else None
    if not body.get('keep_ai_preview'):
        meta = (body.get('meta') or body.get('media_name') or '').strip() or '一幕·YIMU 爆款工作室'
        from core.layouter import render as layout_render
        html = layout_render(body_md, d['title'], theme=theme, meta=meta, images=images, cover=cover)
        (ddir / 'preview-wechat_mp.html').write_text(html, encoding='utf-8')
        from adapters import toutiao as _tt
        (ddir / 'preview-toutiao.html').write_text(_tt.render_preview(body_md, d['title']), encoding='utf-8')
    tf = ddir / 'toutiao.md'
    old_title = '# ' + d['title']
    if tf.exists():
        from core.text_denoise import extract_leading_title
        _lead = extract_leading_title(tf.read_text(encoding='utf-8'))
        if _lead:
            old_title = _lead
    tf.write_text(f'{old_title}\n\n{body_md}', encoding='utf-8')
    return {'ok': True}

@router.post('/api/drafts/{did}/wx_imgs')
async def draft_wx_imgs(did: str, request: Request):
    """把本篇所有配图上传到公众号素材库，返回 {本地路径: 微信CDN url} 映射。

    需 .env 配置 WECHAT_MP_APPID/SECRET 且本机 IP 在公众号后台白名单内；
    失败返回 ok=False，前端回落 base64 内嵌。
    """
    _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    env = load_env()
    if not (env.get('WECHAT_MP_APPID') and env.get('WECHAT_MP_SECRET')):
        return {'ok': False, 'error': '未配置公众号 AppID/Secret'}
    from adapters import wechat_mp
    mapping = {}
    ddir = db.draft_dir(did)
    imgdir = ddir / 'img'
    if not imgdir.exists():
        return {'ok': False, 'error': '本文没有配图'}
    try:
        for f in sorted(imgdir.glob('*.png')):
            mapping[f'/img/{did}/{f.name}'] = wechat_mp.upload_image(str(f))
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200], 'mapping': mapping}
    return {'ok': True, 'mapping': mapping}

@router.post('/api/drafts/{did}/gh_imgs')
async def draft_gh_imgs(did: str, request: Request):
    """把本篇配图上传 GitHub 图床，返回 {本地路径: jsdelivr 公网 URL} 映射。"""
    _a.guard(request)
    from core import imgbed
    if not imgbed.available():
        return {'ok': False, 'error': '图床未配置'}
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    mapping = {}
    imgdir = db.draft_dir(did) / 'img'
    if not imgdir.exists():
        return {'ok': False, 'error': '本文没有配图'}
    try:
        for f in sorted(imgdir.glob('*.png')):
            mapping[f'/img/{did}/{f.name}'] = imgbed.upload(str(f), did)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200], 'mapping': mapping}
    return {'ok': True, 'mapping': mapping}

@router.post('/api/drafts/{did}/ai_layout')
async def draft_ai_layout(did: str, request: Request):
    """AI 重排版：按最新正文与主题为选定平台重新排版与渲染。"""
    _a.guard(request)
    body = await request.json()
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    theme = body.get('theme') or load_config().get('creation', {}).get('wechat_theme', 'caozhou')
    platform = body.get('platform', 'wechat_mp')
    import uuid
    jid = f'lay-{did[:8]}-{uuid.uuid4().hex[:4]}'
    d_title = d.get('title', '')
    _a.start_async_job(jid, name=f'智能排版美化 [{platform}]: {d_title[:16]}', task_type='article_layout', target_id=did, params={'draft_id': did, 'platform': platform, 'theme': theme}, initial_step=f'【{platform}】排版初始化中…')

    def _run():
        try:
            ddir = db.draft_dir(did)
            body_text = d['body_md']
            if platform == 'xhs':
                _a.update_async_job(jid, step='提取小红书分段大纲与生成卡片…', progress=40)
                f_md = ddir / 'xhs.md'
                xhs_title = d['title']
                if f_md.exists():
                    body_text = f_md.read_text(encoding='utf-8')
                    for _ln in body_text.splitlines():
                        _ln_s = _ln.strip()
                        if _ln_s.startswith('# '):
                            xhs_title = _ln_s[2:].strip() or xhs_title
                            break
                sec_meta, cur = ([], None)
                from core.text_denoise import is_section_heading
                for line in body_text.splitlines():
                    if is_section_heading(line):
                        cur = [line.lstrip('#').strip().strip('【】').strip(), []]
                        sec_meta.append(cur)
                    elif cur is not None and line.strip():
                        cur[1].append(line.strip().lstrip('- '))
                if not sec_meta:
                    paras = [p.strip() for p in body_text.split('\n\n') if p.strip() and (not p.strip().startswith('#'))]
                    sec_meta = [(f'看点 {i + 1}', [p]) for i, p in enumerate(paras[:6])]
                if len(sec_meta) < 3:
                    extra_names = ['🔑 核心要点', '💡 深度解析', '✨ 实战技巧', '🎯 关键洞察']
                    _paras = [p.strip() for p in body_text.split('\n\n') if p.strip() and (not p.strip().startswith('#'))]
                    for _j, _para in enumerate(_paras[:5]):
                        if len(sec_meta) >= 5:
                            break
                        pts = [s.strip()[:35] for s in _para.splitlines() if s.strip()][:3] or [_para[:35]]
                        sec_meta.append((extra_names[_j % len(extra_names)], pts))
                cover_file = ddir / 'img' / 'cover.png' if (ddir / 'img' / 'cover.png').exists() else None
                from core.render_card import render_draft_cards
                render_draft_cards(ddir, xhs_title, sec_meta, cover_img=cover_file)
                cards = sorted([f'/card/{did}/{p.name}' for p in ddir.glob('card-*.png')])
                _a.update_async_job(jid, status='done', step='小红书排版与卡片重渲完成', progress=100, result={'ok': True, 'cards': cards, 'text': body_text})
            elif platform == 'toutiao':
                _a.update_async_job(jid, step='渲染今日头条专属排版…', progress=50)
                f_md = ddir / 'toutiao.md'
                if f_md.exists():
                    body_text = f_md.read_text(encoding='utf-8')
                from adapters import toutiao as _tt
                html = _tt.render_preview(body_text, d['title'])
                (ddir / 'preview-toutiao.html').write_text(html, encoding='utf-8')
                _a.update_async_job(jid, status='done', step='今日头条排版完成', progress=100, result={'html': html, 'text': body_text})
            elif platform == 'zhihu':
                _a.update_async_job(jid, step='渲染知乎硬核问答排版…', progress=50)
                f_md = ddir / 'zhihu.md'
                if f_md.exists():
                    body_text = f_md.read_text(encoding='utf-8')
                from adapters import zhihu as _zh
                html = _zh.render_preview(body_text, d['title'])
                (ddir / 'preview-zhihu.html').write_text(html, encoding='utf-8')
                _a.update_async_job(jid, status='done', step='知乎排版完成', progress=100, result={'html': html, 'text': body_text})
            elif platform == 'weibo':
                _a.update_async_job(jid, step='渲染微博快讯排版…', progress=50)
                f_md = ddir / 'weibo.md'
                if f_md.exists():
                    body_text = f_md.read_text(encoding='utf-8')
                from adapters import weibo as _wb
                html = _wb.render_preview(body_text, d['title'])
                (ddir / 'preview-weibo.html').write_text(html, encoding='utf-8')
                _a.update_async_job(jid, status='done', step='微博快讯排版完成', progress=100, result={'html': html, 'text': body_text})
            else:
                _a.update_async_job(jid, step='渲染微信公众号美学主题…', progress=50)
                from core.layouter import render as layout_render
                images = {f.name: f'/img/{did}/{f.name}' for f in sorted((ddir / 'img').glob('sec-*.png'))} if (ddir / 'img').exists() else {}
                cover = f'/img/{did}/cover.png' if (ddir / 'img' / 'cover.png').exists() else None
                meta = (body.get('meta') or body.get('media_name') or '').strip() or '一幕·YIMU 爆款工作室'
                html = layout_render(body_text, d['title'], theme=theme, meta=meta, images=images, cover=cover)
                (ddir / 'preview-wechat_mp.html').write_text(html, encoding='utf-8')
                _a.update_async_job(jid, status='done', step='微信公众号排版完成', progress=100, result={'html': html, 'text': body_text})
        except Exception as e:
            _a.update_async_job(jid, status='failed', error=str(e)[:400], step='排版失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.post('/api/drafts/{did}/switch_title')
async def draft_switch_title(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    new_title = (body.get('title') or '').strip()
    if not new_title:
        raise HTTPException(400, '标题不能为空')

    def _run():
        return orchestrator.switch_draft_title(did, new_title)
    try:
        updated = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'draft': updated}
    except Exception as e:
        raise HTTPException(500, f'切换标题失败: {e}')

@router.post('/api/drafts/{did}/title')
async def draft_set_title(did: str, request: Request):
    """保存标题（极简画布自动存盘用）。

    🔴 补齐缺失端点：前端 saveLiteCanvasEdits 一直在调 `/title` 与 `/body`，
       后端只有 `/switch_title`，于是两个请求都是 404，而前端是
       `try{...}catch(e){}` 空捕获——画布永远停在「● 正在存盘…」，
       用户以为文件一直在保存中。这里与 switch_title 复用同一套重绘逻辑。
    """
    _a.guard(request)
    body = await request.json()
    title = str(body.get('title') or '').strip()
    if not title:
        raise HTTPException(400, '标题不能为空')
    try:
        updated = await asyncio.get_event_loop().run_in_executor(None, lambda: orchestrator.switch_draft_title(did, title))
        return {'ok': True, 'draft': updated}
    except Exception as e:
        raise HTTPException(500, f'保存标题失败: {e}')

@router.post('/api/drafts/{did}/body')
async def draft_set_body(did: str, request: Request):
    """保存正文（极简画布自动存盘用），并同步刷新各平台排版产物。

    与 `/title` 成对存在——缺任何一条，前端存盘都会 404 静默失败。
    """
    _a.guard(request)
    body = await request.json()
    md = body.get('body_md')
    if md is None:
        md = body.get('body')
    if md is None:
        raise HTTPException(400, '缺少 body_md')

    def _run():
        d = db.get_draft(did)
        if not d:
            raise HTTPException(404, '草稿不存在')
        db.update_draft_body(did, str(md))
        try:
            orchestrator.switch_draft_title(did, d.get('title') or '')
        except Exception as e:
            print(f'[存盘] 正文已保存，但重排版失败（不影响正文）: {e}')
        return {'ok': True, 'chars': len(str(md))}
    return await asyncio.get_event_loop().run_in_executor(None, _run)

@router.post('/api/drafts/{did}/publish')
async def draft_publish(did: str, request: Request):
    u = _a.guard(request)
    body = await request.json()
    platforms = body.get('platforms') or []
    bad = [p for p in platforms if p not in PLATFORMS]
    if bad or not platforms:
        raise HTTPException(400, f'平台非法: {bad}')
    _plimit = _a._tier_capability_limit(u, 'publish_platforms')
    if isinstance(_plimit, int) and _plimit > 0 and (len(platforms) > _plimit):
        raise HTTPException(400, f'当前档位单次最多发布到 {_plimit} 个平台，升级 Pro 解锁全平台发布')
    return await asyncio.get_event_loop().run_in_executor(None, lambda: orchestrator.approve_and_publish(did, platforms))

@router.post('/api/drafts/{did}/rescore')
async def draft_rescore(did: str, request: Request):
    _a.guard(request)
    try:
        body = await request.json()
        platform = body.get('platform')
    except Exception:
        platform = None
    return await asyncio.get_event_loop().run_in_executor(None, lambda: judge.judge_draft(did, platform=platform))

@router.get('/api/drafts/{did}/platform_scores')
async def draft_platform_scores(did: str, request: Request):
    """获取草稿各平台差异化评分估算（v3.33新增）。"""
    _a.guard(request)
    return await asyncio.get_event_loop().run_in_executor(None, lambda: judge.judge_platform_scores(did))

@router.post('/api/drafts/{did}/publish_xhs')
async def draft_publish_xhs(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    import uuid
    jid = uuid.uuid4().hex[:12]
    _a.JOBS[jid] = {'step': '准备发布…', 'status': 'running', 'result': None, 'error': ''}

    def _run():
        try:
            from core import xhspub
            res = xhspub.publish(did, emit=lambda m: _a.JOBS[jid].update(step=m))
            _a.JOBS[jid].update(status='done' if res['ok'] else 'failed', step='完成' if res['ok'] else '失败', result=res, error='' if res['ok'] else res['detail'][:300])
        except Exception as e:
            _a.JOBS[jid].update(status='failed', error=str(e)[:300], step='失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.post('/api/drafts/{did}/storyboard')
async def draft_storyboard(did: str, request: Request):
    _a.guard(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    from core.storyboard import generate_storyboard, get_storyboard
    force = body.get('force', False) if isinstance(body, dict) else False

    def _run():
        return generate_storyboard(did) if force else get_storyboard(did)
    try:
        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f'生成分镜失败: {e}')

@router.get('/api/drafts/{did}/export_jianying')
def draft_export_jianying(did: str, request: Request, aspect: str='9:16'):
    _a.guard(request)
    from core.storyboard import export_jianying_draft
    from fastapi.responses import FileResponse
    try:
        zip_file = export_jianying_draft(did, aspect=aspect)
        filename = f"jianying_{did}_{('16x9' if aspect == '16:9' else '9x16')}.zip"
        return FileResponse(zip_file, media_type='application/zip', filename=filename)
    except Exception as e:
        raise HTTPException(500, f'导出剪映工程失败: {e}')

@router.post('/api/drafts/{did}/storyboard/gen_image')
async def storyboard_gen_image(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    shot_index = int(body.get('shot_index', 1))
    prompt_en = body.get('prompt_en', '')
    aspect = body.get('aspect', '16:9')
    from core import storyboard
    _a.require_credits('drama_image', 1, f'电影分镜生图 #{shot_index}')
    image_model = (body.get('image_model') or '').strip()

    def _run():
        return storyboard.generate_storyboard_image(did, shot_index, prompt_en=prompt_en, aspect=aspect, image_model=image_model)
    try:
        url = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'image_url': url, 'shot_index': shot_index}
    except Exception as e:
        raise HTTPException(500, f'分镜生图失败: {e}')

@router.post('/api/drafts/{did}/storyboard/batch_gen_images')
async def storyboard_batch_gen_images(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    aspect = body.get('aspect', '16:9')
    image_model = (body.get('image_model') or '').strip()
    from core import storyboard

    def _run():
        return storyboard.batch_generate_storyboard_images(did, aspect=aspect, image_model=image_model)
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {'ok': True, 'results': results}
    except Exception as e:
        raise HTTPException(500, f'批量生图失败: {e}')

@router.post('/api/drafts/{did}/ai_xhs')
async def draft_ai_xhs(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    style = body.get('style', 'magazine')
    d = db.get_draft(did) or {}
    d_title = d.get('title', did[:8])
    import uuid
    jid = f'xhs-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'小红书排版与制卡: {d_title[:16]}', task_type='article_layout', target_id=did, params={'draft_id': did, 'style': style}, initial_step='小红书爆款图文卡片排版中…')

    def _run():
        try:
            res = orchestrator.ai_xhs(did, style, emit=lambda m: _a.update_async_job(jid, step=m))
            _a.update_async_job(jid, status='done', step='小红书卡片重排完成！', progress=100, result=res)
        except Exception as e:
            _a.update_async_job(jid, status='failed', error=str(e)[:400], step='小红书排版失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.post('/api/drafts/{did}/ai_xhs_visual')
async def draft_ai_xhs_visual(did: str, request: Request):
    """AI 全套小红书视觉生图与卡片精修制卡任务"""
    _a.guard(request)
    body = await request.json()
    style = body.get('style', 'ai_visual_dark')
    d = db.get_draft(did) or {}
    d_title = d.get('title', did[:8])
    import uuid
    jid = f'xhs-vis-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'小红书 AI 视觉配图制卡: {d_title[:16]}', task_type='image_gen', target_id=did, params={'draft_id': did, 'style': style}, initial_step='AI 视觉大模型通读与配图生成中…')

    def _run():
        try:
            res = orchestrator.ai_xhs_visual(did, style, emit=lambda m: _a.update_async_job(jid, step=m))
            _a.update_async_job(jid, status='done', step='✨ AI 视觉图文卡片生成完成！', progress=100, result=res)
        except Exception as e:
            _a.update_async_job(jid, status='failed', error=str(e)[:400], step='AI 生图制卡失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.post('/api/drafts/{did}/xhs_style')
async def draft_xhs_style(did: str, request: Request):
    """即时快速切换小红书卡片风格（毫秒级重绘已有配图与文本）"""
    _a.guard(request)
    body = await request.json()
    style = body.get('style', 'magazine')
    res = orchestrator.change_xhs_style(did, style=style)
    return res

@router.get('/api/drafts/{did}/xhs/history')
async def get_xhs_history(did: str):
    """获取草稿的小红书专属历史快照列表（包含文案与卡片图）。"""
    try:
        snaps = orchestrator.list_xhs_history(did)
        return {'ok': True, 'draft_id': did, 'snapshots': snaps}
    except Exception as e:
        raise HTTPException(500, f'获取小红书历史失败: {e}')

@router.get('/api/drafts/{did}/xhs/history/{hid}/card/{card_name}')
async def get_xhs_history_card(did: str, hid: str, card_name: str):
    """查看指定小红书历史快照中的卡片图片。"""
    card_file = db.draft_dir(did) / 'xhs_history' / hid / card_name
    if not card_file.exists():
        raise HTTPException(404, '历史卡片不存在')
    return FileResponse(str(card_file), media_type='image/png')

@router.post('/api/drafts/{did}/xhs/history/{hid}/restore')
async def restore_xhs_history_endpoint(did: str, hid: str, request: Request):
    """一键回溯还原指定的小红书版本（同时还原 xhs.md 与全套卡片图）。"""
    _a.guard(request)
    try:
        res = await asyncio.get_event_loop().run_in_executor(None, lambda: orchestrator.restore_xhs_history(did, hid))
        return res
    except Exception as e:
        raise HTTPException(500, f'回溯小红书版本失败: {e}')

@router.get('/api/drafts/{did}/history')
def draft_history(did: str, request: Request):
    _a.guard(request)
    return {'history': db.list_history(did)}

@router.post('/api/drafts/{did}/restore')
async def draft_restore(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    h = db.get_history(body.get('hid', ''))
    if not h or h['draft_id'] != did:
        raise HTTPException(404, '历史版本不存在')
    c = db.conn()
    c.execute('UPDATE drafts SET title=?, body_md=? WHERE id=?', (h['title'], h['body_md'], did))
    c.commit()
    c.close()
    orchestrator._refresh_artifacts(did, {'TITLE_WX': h['title'], 'BODY_WX': h['body_md']}, h['title'], h['body_md'])
    return {'ok': True, 'title': h['title']}

@router.get('/api/drafts/{did}')
def get_draft_detail_endpoint(did: str, request: Request):
    _a.guard(request)
    # V15.8：老草稿打开即自愈——修正模型自造的死链并补齐六平台预览，
    # 客户机器上已有的坏草稿无需手工改数据库或重新生成。
    try:
        from core import artifacts
        artifacts.heal_draft(did)
    except Exception:
        pass
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, f'草稿不存在: {did}')
    return d

@router.get('/api/drafts/{did}/score')
def draft_score(did: str, request: Request):
    _a.guard(request)
    sc = judge.get_score(did)
    if not sc:
        return {'ok': True, 'scored': False, 'total': None, 'grade': '未评分'}
    sc['scored'] = True
    return sc

@router.post('/api/drafts/create')
async def create_draft_endpoint(request: Request):
    """创作者在内容工作台手动新建空白草稿或导入外部草稿"""
    user = _a.guard(request)
    body = await request.json()
    title = (body.get('title') or '').strip()
    body_md = body.get('body_md') or ''
    workspace_id = (body.get('workspace_id') or '').strip()
    _a.require_credits('draft_create', 1, f"新建草稿 [{title[:16] or '未命名'}]")
    if not workspace_id:
        from core import workspace
        active_ws = workspace.get_active_workspace()
        if active_ws:
            workspace_id = active_ws.get('id', '')
    draft = db.create_custom_draft(title=title, body_md=body_md, workspace_id=workspace_id, user_id=_a._current_user_id(user))
    did = draft['id']
    from core import orchestrator
    orchestrator.init_draft_artifacts(did, draft['title'], draft['body_md'])
    from core import judge
    from core import llm as _llm
    score = judge.judge_draft(did) if _llm.available() else {'total': 0, 'grade': '未评分（未配置大模型）'}
    try:
        from core import analytics
        analytics.track('first_draft_created', str((user or {}).get('id') or ''), {'draft_id': did, 'title_len': len(title)})
    except Exception:
        pass
    return {'ok': True, 'draft': db.get_draft(did), 'score': score}

@router.post('/api/drafts/{did}/ai_upgrade')
async def ai_upgrade_draft_endpoint(did: str, request: Request):
    """结合名家文风、专属技能库与黄金钩子对草稿进行一键深度改写提分"""
    _a.guard(request)
    body = await request.json()
    persona = body.get('persona', '')
    skills = body.get('skills')
    focus_targets = body.get('focus_targets')
    instruction = body.get('instruction', '')
    media_name = body.get('media_name', '')
    d = db.get_draft(did) or {}
    d_title = d.get('title', did[:8])
    old_score = (judge.get_score(did) or {}).get('total', 0)
    import uuid
    jid = f'upg-{did[:8]}-{uuid.uuid4().hex[:4]}'
    _a.start_async_job(jid, name=f'AI 深度改写提升: {d_title[:16]}', task_type='ai_rewrite', target_id=did, params={'draft_id': did, 'persona': persona, 'skills': skills}, initial_step='正在融合名家文风、黄金3秒钩子与深度去AI味…')
    try:
        _a.update_async_job(jid, step='深度重塑正文、金句提炼与多端派生中…', progress=40)
        res = await asyncio.get_event_loop().run_in_executor(None, lambda: orchestrator.ai_upgrade_draft(did, persona_id=persona, skills=skills, focus_targets=focus_targets, custom_instruction=instruction, media_name=media_name))
        new_score = (res.get('score') or {}).get('total', 0)
        res['old_score'] = old_score
        res['improvement_delta'] = round(new_score - old_score, 1)
        _a.update_async_job(jid, status='done', step=f"改写提升完成！评分由 {old_score} 跃升至 {new_score} (+{res['improvement_delta']}分)", progress=100, result={'score': new_score, 'delta': res['improvement_delta']})
        return res
    except Exception as e:
        diag.capture_exc('rewrite', 'ai_upgrade_draft', e, draft_id=did, persona=persona, skills=skills, instruction_len=len(instruction or ''))
        _a.update_async_job(jid, status='failed', error=str(e)[:300], step='AI 改写提升失败')
        raise HTTPException(500, f'AI 一键改写提升失败: {e}')

@router.post('/api/drafts/{did}/rewrite')
async def draft_rewrite(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    t0 = time.perf_counter()
    try:
        return await asyncio.get_event_loop().run_in_executor(None, lambda: orchestrator.rewrite_draft_once(did, body.get('instruction', '')))
    except Exception as e:
        diag.capture_exc('rewrite', 'draft_rewrite', e, elapsed=time.perf_counter() - t0, draft_id=did, instruction_len=len(body.get('instruction') or ''))
        raise HTTPException(500, f'重写失败: {e}')

@router.post('/api/drafts/{did}/rewrite_platform')
async def draft_rewrite_platform(did: str, request: Request):
    """单平台专属重写/重排（v3.33新增）。
    
    body: { "platform": "xhs"|"toutiao"|"wechat_mp"|"weibo"|"zhihu"|"twitter", 
            "instruction": "可选的重写指令" }
    只重写并覆盖该平台的内容，不影响其他平台。
    """
    _a.guard(request)
    body = await request.json()
    platform = (body.get('platform') or '').strip()
    if not platform:
        raise HTTPException(400, 'platform 不能为空')
    instruction = body.get('instruction', '')
    PLATFORM_NAMES = {'wechat_mp': '微信公众号', 'xhs': '小红书', 'toutiao': '今日头条', 'weibo': '微博', 'zhihu': '知乎', 'twitter': '推特/X'}
    plat_name = PLATFORM_NAMES.get(platform, platform)
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: orchestrator.rewrite_single_platform(did, platform, instruction))
        result['platform_name'] = plat_name
        return result
    except Exception as e:
        diag.capture_exc('rewrite', 'rewrite_single_platform', e, draft_id=did, platform=platform, instruction_len=len(instruction or ''))
        raise HTTPException(500, f'{plat_name} 重写失败: {e}')

@router.post('/api/drafts/{did}/quality_gate')
async def draft_quality_gate(did: str, request: Request):
    """借鉴 Easel: 发布前双重质量关卡与合规风控体检 (Quality Gate)。
    检测：
    1. 广告法极限词拦截（第一、最强、顶级等）
    2. 平台限流违禁/敏感词
    3. AI 机械感与套路化特征
    4. 标题字数与格式完整性
    """
    _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    # V15.8 / 建议「状态进入 preview 前自检」：正文还有缺失配图时直接拦截，
    # 不让裂图草稿进入发布流程（同时兜住 F2 与未来同类问题）。
    try:
        from core import artifacts
        gate = artifacts.quality_gate(did)
        if not gate.get('ok'):
            return {
                'passed': False, 'score': 0,
                'summary': gate.get('hint', '配图缺失'),
                'ad_violations': [], 'platform_risks': [], 'ai_smell_issues': [],
                'recommendations': [gate.get('hint', '')],
                'missing_images': gate.get('missing', []),
            }
    except Exception:
        pass
    from core import agents
    title = d.get('title', '')
    body = d.get('body_md', '')
    prompt = f"""你是顶级社媒发布合规总监与内容品控专家。请对以下草稿进行严格的【发布前质量风控与合规体检】。\n\n【标题】：{title}\n\n【正文前3000字】：\n{body[:3000]}\n\n请从以下四个维度进行全景式体检，并输出纯 JSON：\n1. ad_violations: 广告法极限违禁词（如最、第一、唯一、顶级、绝对等），指出原句并给出安全合规修改建议；\n2. platform_risks: 平台限流敏感词（夸大宣传、疑似引流导流、封建迷信、诱导关注等）；\n3. ai_smell_issues: AI 机械套路感诊断（是否包含'总而言之、不可否认、在这个快节奏时代'等公文腔排比），给出活人感打磨建议；\n4. completeness: 标题长度、分段呼吸感、结尾行动召唤 (CTA) 是否完备；\n5. score: 0-100 的综合安全与质量合规指数（>=85方可通过发布）；\n6. passed: true/false 是否通过风控关卡。\n\n严格只输出纯 JSON，绝不要包含 markdown 解释：\n{{\n  "score": 92,\n  "passed": true,\n  "summary": "整体合规度高，无触碰广告法红线，文风自然",\n  "ad_violations": [],\n  "platform_risks": [],\n  "ai_smell_issues": [],\n  "recommendations": ["建议将结尾互动提问设为单选，降低留言门槛"]\n}}"""
    try:
        raw = agents.chat_for('review', [{'role': 'system', 'content': '只输出纯 JSON，绝不添加包裹。'}, {'role': 'user', 'content': prompt}], temperature=0.2)
        import re, json
        cleaned = raw.strip()
        if cleaned.startswith('```'):
            cleaned = re.sub('^```(?:json)?\\s*', '', cleaned)
            cleaned = re.sub('\\s*```$', '', cleaned)
        m = re.search('\\{.*\\}', cleaned, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {'passed': True, 'score': 85, 'summary': '体检完成', 'recommendations': []}
    except Exception as e:
        return {'passed': True, 'score': 80, 'summary': f'体检服务返回: {e}', 'recommendations': []}

@router.post('/api/drafts/{did}/refine')
async def draft_refine(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    defects = body.get('defects') or []
    if isinstance(defects, str):
        defects = [defects]
    if not defects:
        raise HTTPException(400, '请提供至少一个待补齐的短板项')
    old_score = (judge.get_score(did) or {}).get('total', 0)

    def _run():
        res = orchestrator.refine_draft_points(did, defects)
        new_score = (res.get('score') or {}).get('total', 0)
        delta = round(new_score - old_score, 1)
        return {'ok': True, 'new_score': new_score, 'old_score': old_score, 'improvement_delta': delta, 'fixed_count': len(defects), 'score': res.get('score')}
    try:
        return await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(500, f'外科手术定点精修失败: {e}')

@router.post('/api/drafts/{did}/evolve')
async def draft_evolve(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    target_score = int(body.get('target_score', 80))
    max_rounds = int(body.get('max_rounds', 3))
    import uuid
    jid = uuid.uuid4().hex[:12]
    _a.JOBS[jid] = {'step': '自进化熔炉初始化…', 'status': 'running', 'result': None, 'error': ''}

    def _run():
        try:
            res = orchestrator.evolve_draft_to_target(did, target_score=target_score, max_rounds=max_rounds, emit=lambda m: _a.JOBS[jid].update(step=m))
            _a.JOBS[jid].update(status='done', step='炼制完成', result=res)
        except Exception as e:
            _a.JOBS[jid].update(status='failed', error=str(e)[:300], step='炼制中断')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.get('/api/drafts/{did}/raw/{platform}')
def draft_raw(did: str, platform: str):
    from core.text_purity import purify_body
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    ddir = db.draft_dir(did)
    if platform == 'wechat_mp':
        f = ddir / 'preview-wechat_mp.html'
        content = f.read_text(encoding='utf-8') if f.exists() else ''
        from core.imagegen import get_draft_images
        d_imgs = get_draft_images(did)
        has_imgs_on_disk = bool(d_imgs.get('cover') or d_imgs.get('sections'))
        from core.layouter import render as layout_render, _dedupe_wechat_html_images
        if not f.exists() or f.stat().st_size < 100 or (has_imgs_on_disk and '<img' not in content):
            images_dict = {f'sec-{i}': u for i, u in enumerate(d_imgs.get('sections', []))}
            from core.text_denoise import extract_section_headings
            sec_meta = [t.strip('【】').strip() for t, _ in extract_section_headings(d['body_md'])]
            for i, sec_t in enumerate(sec_meta):
                if i < len(d_imgs.get('sections', [])):
                    images_dict[sec_t] = d_imgs['sections'][i]
            wx_html = layout_render(d['body_md'], d['title'], theme='spring-fresh', images=images_dict, cover=d_imgs.get('cover'))
            f.write_text(wx_html, encoding='utf-8')
            content = wx_html
        else:
            deduped = _dedupe_wechat_html_images(content)
            if deduped != content:
                content = deduped
                f.write_text(content, encoding='utf-8')
        return {'title': d['title'], 'html': content, 'text': d['body_md']}
    if platform == 'body':
        return {'title': d['title'], 'body_md': d['body_md'], 'text': d['body_md']}
    if platform == 'xhs':
        f_md = ddir / 'xhs.md'
        xhs_title = d['title']
        raw_txt = f_md.read_text(encoding='utf-8') if f_md.exists() else d['body_md']
        from core.text_denoise import extract_leading_title
        xhs_title = extract_leading_title(raw_txt) or xhs_title
        cards = sorted([f'/card/{did}/{p.name}' for p in ddir.glob('card-*.png')])
        if len(cards) < 5:
            try:
                from core.render_card import render_draft_cards
                from core.copilot import extract_xhs_card_selling_points
                pts = extract_xhs_card_selling_points(xhs_title, d['body_md'])
                cov = ddir / 'img' / 'cover.png' if (ddir / 'img' / 'cover.png').exists() else None
                render_draft_cards(ddir, xhs_title, pts, style='ai_visual_dark', cover_img=cov)
                cards = sorted([f'/card/{did}/{p.name}' for p in ddir.glob('card-*.png')])
            except Exception:
                pass
        from core.orchestrator import clean_xhs_text
        cleaned_txt = clean_xhs_text(raw_txt, xhs_title)
        return {'title': xhs_title, 'text': cleaned_txt, 'cards': cards, 'cards_count': len(cards)}
    if platform == 'toutiao':
        f_html = ddir / 'preview-toutiao.html'
        f_md = ddir / 'toutiao.md'
        from adapters import toutiao as _tt
        from core.imagegen import inject_images_to_markdown, get_draft_images
        d_imgs = get_draft_images(did)
        text = f_md.read_text(encoding='utf-8') if f_md.exists() else inject_images_to_markdown(d['body_md'], did)
        text = purify_body(text)
        if not f_md.exists():
            (ddir / 'toutiao.md').write_text(text, encoding='utf-8')
        cur_html = f_html.read_text(encoding='utf-8') if f_html.exists() else ''
        need_rebuild = not f_html.exists() or f_html.stat().st_size < 100
        if not need_rebuild and d_imgs.get('sections') and (cur_html.count('<img') <= 1):
            need_rebuild = True
        if need_rebuild:
            html = _tt.render_preview(text, d['title'], images=d_imgs.get('sections'), cover=d_imgs.get('cover'), draft_id=did)
            f_html.write_text(html, encoding='utf-8')
        else:
            html = cur_html
        return {'title': d['title'], 'html': html, 'text': text}
    if platform == 'zhihu':
        f_html = ddir / 'preview-zhihu.html'
        f_md = ddir / 'zhihu.md'
        from adapters import zhihu as _zh
        from core.imagegen import inject_images_to_markdown, get_draft_images
        text = f_md.read_text(encoding='utf-8') if f_md.exists() else inject_images_to_markdown(d['body_md'], did)
        text = purify_body(text)
        if not f_md.exists():
            (ddir / 'zhihu.md').write_text(text, encoding='utf-8')
        if f_html.exists() and f_html.stat().st_size > 100:
            html = f_html.read_text(encoding='utf-8')
        else:
            d_imgs = get_draft_images(did)
            html = _zh.render_preview(text, d['title'], images=d_imgs.get('sections'), cover=d_imgs.get('cover'), draft_id=did)
            f_html.write_text(html, encoding='utf-8')
        return {'title': d['title'], 'html': html, 'text': text}
    if platform == 'weibo':
        f_html = ddir / 'preview-weibo.html'
        f_md = ddir / 'weibo.md'
        from adapters import weibo as _wb
        from core.imagegen import inject_images_to_markdown, get_draft_images
        text = f_md.read_text(encoding='utf-8') if f_md.exists() else inject_images_to_markdown(d['body_md'], did)
        text = purify_body(text)
        if not f_md.exists():
            (ddir / 'weibo.md').write_text(text, encoding='utf-8')
        if f_html.exists() and f_html.stat().st_size > 100:
            html = f_html.read_text(encoding='utf-8')
        else:
            d_imgs = get_draft_images(did)
            html = _wb.render_preview(text, d['title'], images=d_imgs.get('sections'), cover=d_imgs.get('cover'), draft_id=did)
            f_html.write_text(html, encoding='utf-8')
        return {'title': d['title'], 'html': html, 'text': text}
    if platform == 'twitter':
        f_html = ddir / 'preview-twitter.html'
        f_md = ddir / 'twitter.md'
        from adapters import twitter as _tw
        text = f_md.read_text(encoding='utf-8') if f_md.exists() else d['body_md']
        if not f_md.exists():
            (ddir / 'twitter.md').write_text(text, encoding='utf-8')
        if f_html.exists() and f_html.stat().st_size > 50:
            html = f_html.read_text(encoding='utf-8')
        else:
            html = _tw.render_twitter_html(text, d['title'])
            f_html.write_text(html, encoding='utf-8')
        return {'title': d['title'], 'html': html, 'text': text}
    raise HTTPException(404, f'未知平台: {platform}')

@router.post('/api/drafts/{did}/save_platform')
async def draft_save_platform(did: str, request: Request):
    """多平台通用源文案保存与同步热渲染接口"""
    _a.guard(request)
    body = await request.json()
    platform = body.get('platform', 'wechat_mp')
    text = body.get('text', '')
    from core.text_purity import purify_body, to_storage
    theme = body.get('theme')
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    ddir = db.draft_dir(did)
    if platform == 'wechat_mp':
        text = to_storage(text)
        c = db.conn()
        c.execute('UPDATE drafts SET body_md=? WHERE id=?', (text, did))
        c.commit()
        c.close()
        from core.layouter import render as layout_render
        if not theme:
            theme = load_config().get('creation', {}).get('wechat_theme', 'caozhou')
        theme = theme if theme in WECHAT_THEMES else 'caozhou'
        images = {f.name: f'/img/{did}/{f.name}' for f in sorted((ddir / 'img').glob('sec-*.png'))} if (ddir / 'img').exists() else {}
        cover = f'/img/{did}/cover.png' if (ddir / 'img' / 'cover.png').exists() else None
        meta = (body.get('meta') or body.get('media_name') or '').strip() or '一幕·YIMU 爆款工作室'
        html = layout_render(text, d['title'], theme=theme, meta=meta, images=images, cover=cover)
        (ddir / 'preview-wechat_mp.html').write_text(html, encoding='utf-8')
        return {'ok': True, 'text': text, 'html': html}
    elif platform == 'xhs':
        text = purify_body(text)
        (ddir / 'xhs.md').write_text(text, encoding='utf-8')
        from core.text_denoise import extract_leading_title, is_section_heading
        xhs_title = extract_leading_title(text) or d['title']
        lines = text.splitlines()
        if extract_leading_title(text):
            for _i, _l in enumerate(lines):
                if _l.strip():
                    lines = lines[_i + 1:]
                    break
        sec_meta, cur = ([], None)
        for line in lines:
            if is_section_heading(line):
                cur = [line.lstrip('#').strip().strip('【】').strip(), []]
                sec_meta.append(cur)
            elif cur is not None and line.strip():
                cur[1].append(line.strip().lstrip('- '))
        if not sec_meta:
            paras = [p.strip() for p in text.split('\n\n') if p.strip() and (not p.strip().startswith('#'))]
            sec_meta = [(f'看点 {i + 1}', [p]) for i, p in enumerate(paras[:6])]
        if len(sec_meta) < 3:
            extra_names = ['🔑 核心要点', '💡 深度解析', '✨ 实战技巧', '🎯 关键洞察']
            _paras = [p.strip() for p in text.split('\n\n') if p.strip() and (not p.strip().startswith('#'))]
            for _j, _para in enumerate(_paras[:5]):
                if len(sec_meta) >= 5:
                    break
                pts = [s.strip()[:35] for s in _para.splitlines() if s.strip()][:3] or [_para[:35]]
                sec_meta.append((extra_names[_j % len(extra_names)], pts))
        cover_file = ddir / 'img' / 'cover.png' if (ddir / 'img' / 'cover.png').exists() else None
        from core.render_card import render_draft_cards
        render_draft_cards(ddir, xhs_title, sec_meta, cover_img=cover_file)
        # V15.8 / R7：卡片更新后同步刷新 preview-xhs.html，
        # 否则 /preview/{did}/xhs 与分享页拿到的还是上一版卡片。
        try:
            from core import previews
            previews.build_all_previews(did, platforms=('xhs',))
        except Exception:
            pass
        cards = sorted([f'/card/{did}/{p.name}' for p in ddir.glob('card-*.png')])
        return {'ok': True, 'text': text, 'cards': cards}
    elif platform == 'toutiao':
        text = purify_body(text)
        (ddir / 'toutiao.md').write_text(text, encoding='utf-8')
        from adapters import toutiao as _tt
        from core.imagegen import get_draft_images
        d_imgs = get_draft_images(did)
        html = _tt.render_preview(text, d['title'], images=d_imgs.get('sections'), cover=d_imgs.get('cover'), draft_id=did)
        (ddir / 'preview-toutiao.html').write_text(html, encoding='utf-8')
        return {'ok': True, 'text': text, 'html': html}
    elif platform == 'zhihu':
        text = purify_body(text)
        (ddir / 'zhihu.md').write_text(text, encoding='utf-8')
        from adapters import zhihu as _zh
        from core.imagegen import get_draft_images
        d_imgs = get_draft_images(did)
        html = _zh.render_preview(text, d['title'], images=d_imgs.get('sections'), cover=d_imgs.get('cover'), draft_id=did)
        (ddir / 'preview-zhihu.html').write_text(html, encoding='utf-8')
        return {'ok': True, 'text': text, 'html': html}
    elif platform == 'weibo':
        text = purify_body(text)
        (ddir / 'weibo.md').write_text(text, encoding='utf-8')
        from adapters import weibo as _wb
        from core.imagegen import get_draft_images
        d_imgs = get_draft_images(did)
        html = _wb.render_preview(text, d['title'], images=d_imgs.get('sections'), cover=d_imgs.get('cover'), draft_id=did)
        (ddir / 'preview-weibo.html').write_text(html, encoding='utf-8')
        return {'ok': True, 'text': text, 'html': html}
    elif platform == 'twitter':
        text = purify_body(text)
        (ddir / 'twitter.md').write_text(text, encoding='utf-8')
        from adapters import twitter as _tw
        html = _tw.render_twitter_html(text, d['title'])
        (ddir / 'preview-twitter.html').write_text(html, encoding='utf-8')
        return {'ok': True, 'text': text, 'html': html}
    raise HTTPException(400, f'不支持的平台类型: {platform}')

@router.post('/api/drafts/{did}/fission')
async def draft_fission(did: str, request: Request):
    _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    from core import fission
    _a.require_credits('rewrite', 1, f'全域五端矩阵裂变 [{did}]')
    jid = f'fiss-{did[:8]}-{uuid.uuid4().hex[:4]}'
    d_title = d.get('title', '')
    _a.start_async_job(jid, name=f'全域矩阵裂变: {d_title[:16]}', task_type='omni_fission', target_id=did, params={'draft_id': did}, initial_step='启动全域矩阵裂变引擎…')

    def _run():
        try:
            res = fission.generate_omnichannel_matrix(did, emit=lambda m: _a.update_async_job(jid, step=m))
            _a.update_async_job(jid, status='done', step='全域五端矩阵裂变完成！', progress=100, result=res)
        except Exception as e:
            _a.update_async_job(jid, status='failed', error=str(e)[:300], step='裂变失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.post('/api/drafts/{did}/derive_omni')
async def draft_derive_omni(did: str, request: Request):
    """母稿驱动·全域多端一键派生接口：以当前编辑器母稿为单一基准，保真同步派生选中的矩阵平台。"""
    _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    body = await request.json()
    master_title = body.get('title') or d.get('title', '')
    master_body_md = body.get('body_md')
    theme = body.get('theme')
    media_name = (body.get('media_name') or '').strip()
    card_style = body.get('card_style') or 'magazine'
    platforms = body.get('platforms')
    from core import fission
    _a.require_credits('rewrite', 1, f'母稿驱动全域多端派生 [{did}]')
    jid = f'derive-{did[:8]}-{uuid.uuid4().hex[:4]}'
    plat_str = f'({len(platforms)}端)' if platforms else '(全域)'
    _a.start_async_job(jid, name=f'母稿驱动派生{plat_str}: {master_title[:16]}', task_type='omni_derive', target_id=did, params={'draft_id': did, 'title': master_title, 'theme': theme, 'platforms': platforms}, initial_step='启动母稿驱动派生引擎…')

    def _run():
        try:
            res = fission.derive_all_platforms_from_master(draft_id=did, master_title=master_title, master_body_md=master_body_md, theme=theme, media_name=media_name, card_style=card_style, target_platforms=platforms, emit=lambda m: _a.update_async_job(jid, step=m))
            _a.update_async_job(jid, status='done', step=f"矩阵多端派生完成！共 {len(res.get('selected_platforms', []))} 端", progress=100, result=res)
        except Exception as e:
            _a.update_async_job(jid, status='failed', error=str(e)[:300], step='派生失败')
    asyncio.get_event_loop().run_in_executor(None, _run)
    return {'job': jid}

@router.post('/api/drafts/{did}/switch_theme_pure')
async def draft_switch_theme_pure(did: str, request: Request):
    """零篡改纯排版换肤接口：100% 不调用 LLM，纯规则 CSS 行内样式重排，毫秒级响应。"""
    _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    body = await request.json()
    theme = body.get('theme') or 'caozhou'
    title = body.get('title')
    body_md = body.get('body_md')
    media_name = body.get('media_name')
    from core import fission
    res = fission.switch_theme_pure(draft_id=did, theme=theme, title=title, body_md=body_md, media_name=media_name)
    return res

@router.get('/api/drafts/{did}/matrix')
def draft_matrix(did: str, request: Request):
    _a.guard(request)
    from core import fission
    return fission.get_draft_matrix(did)

@router.get('/api/drafts/{did}/copilot_history')
def get_copilot_history_endpoint(did: str, request: Request):
    _a.guard(request)
    from core import copilot
    return {'history': copilot.get_draft_copilot_history(did)}

@router.get('/api/drafts/{did}/html')
def get_draft_html(did: str, request: Request):
    _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, 'Draft not found')
    body_md = d.get('body_md', '')
    from core.imagegen import inject_images_to_markdown, get_draft_images
    injected_md = inject_images_to_markdown(body_md, did)
    imgs_dict = get_draft_images(did)
    try:
        import markdown
        html = markdown.markdown(injected_md, extensions=['extra', 'tables', 'fenced_code'])
    except Exception:
        try:
            from core.themes import md_to_wechat_html
            html = md_to_wechat_html(injected_md, d.get('title', ''))
        except Exception:
            html = f'<p>{injected_md}</p>'
    html = re.sub('<img\\s+([^>]*?)src="([^"]+)"([^>]*?)>', '<div style="text-align:center;margin:20px 0;"><img \\1src="\\2"\\3 style="max-width:100%;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.15);display:inline-block;"></div>', html)
    return {'html': html, 'title': d.get('title', ''), 'body_md': body_md, 'images': imgs_dict}

@router.post('/api/drafts/{did}/html')
async def save_draft_html(did: str, request: Request):
    _a.guard(request)
    body = await request.json()
    html_content = body.get('html', '')
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, 'Draft not found')
    db.update_draft_body(did, html_content)
    try:
        from core.orchestrator import switch_draft_title
        switch_draft_title(did, d.get('title', ''))
    except Exception:
        pass
    return {'ok': True, 'msg': '一幕富文本与多端排版已成功同步持久化！'}

@router.get('/api/drafts/{did}/zip/xhs')
def draft_zip(did: str):
    import io
    import zipfile
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    ddir = db.draft_dir(did)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        if (ddir / 'xhs.md').exists():
            z.writestr('小红书文案.txt', (ddir / 'xhs.md').read_text(encoding='utf-8'))
        for png in sorted(ddir.glob('card-*.png')):
            z.write(png, png.name)
    buf.seek(0)
    from urllib.parse import quote
    safe = re.sub('[\\\\/:*?"<>|\\s]+', '', d['title'])[:40] or did
    return Response(buf.getvalue(), media_type='application/zip', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(safe)}.zip"})

@router.post('/api/drafts/delete')
async def drafts_delete(request: Request):
    """批量删除草稿（进废纸篓，不物理删除）。

    ⭐ 安全修复（两处，缺一不可）：
       1. **归属校验**：此前只 guard()，ids 里的 did 不校验归属——
          任何登录用户传别人的 did 就能删掉他人全部稿件。
          现在逐条 is_draft_owner，非本人（且非管理员）直接跳过。
       2. **路径穿越**：此前 `BASE/"data"/"drafts"/did` 直接拼，
          did="../.." 会让 shutil.move 把整个仓库移进废纸篓。
          现在先过 id 白名单，再 resolve 校验父子关系。
       被拒绝的 id 不报错、只进 skipped——避免把「无权」与「不存在」
       区分开，也不让一次批量操作因为混入一个坏 id 全盘失败。
    """
    u = _a.guard(request)
    body = await request.json()
    ids = body.get('ids') or []
    if not ids:
        raise HTTPException(400, '未选择草稿')
    import shutil
    uid = _a._current_user_id(u)
    is_admin = _a._is_admin_user(u)
    root = (_a.BASE / 'data' / 'drafts').resolve()
    trash = Path.home() / '.Trash'
    removed: list[str] = []
    skipped: list[str] = []
    for raw_did in ids:
        did = str(raw_did or '').strip()
        if not SAFE_DID_RE.match(did):
            skipped.append(str(raw_did))
            continue
        d = db.get_draft(did)
        if d and (not db.is_draft_owner(d, uid, is_admin=is_admin)):
            skipped.append(did)
            continue
        ddir = (root / did).resolve()
        if root not in ddir.parents:
            skipped.append(did)
            continue
        if d:
            c = db.conn()
            c.execute('DELETE FROM drafts WHERE id=?', (did,))
            c.execute('DELETE FROM jobs WHERE draft_id=?', (did,))
            c.commit()
            c.close()
        if ddir.exists():
            try:
                trash.mkdir(exist_ok=True)
                shutil.move(str(ddir), str(trash / did))
            except Exception:
                pass
        removed.append(did)
    return {'removed': removed, 'skipped': skipped}

@router.post('/api/drafts/clean_old')
async def drafts_clean_old(request: Request):
    """清理超过 N 天的过期草稿。"""
    _a.guard(request)
    body = await request.json()
    days = int(body.get('days', 0))
    if days <= 0:
        return {'ok': True, 'deleted_count': 0, 'msg': '当前设置为永不过期，未执行清理'}
    deleted_ids = db.delete_old_drafts(days)
    return {'ok': True, 'deleted_count': len(deleted_ids), 'deleted_ids': deleted_ids, 'msg': f'已清理 {len(deleted_ids)} 篇超过 {days} 天的过期草稿'}

@router.post('/api/drafts/{did}/share')
async def draft_create_share(did: str, request: Request):
    """为某篇稿件的裂变产物签发分享链接（含二维码与海报地址）。

    只为**产物文件确实存在**的平台签发；没生成的平台会出现在 skipped 里
    并说明原因（而不是给一个点开404 的死链）。
    """
    user = _a.guard(request)
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    platforms = body.get('platforms') or ['wechat_mp', 'xhs', 'toutiao', 'zhihu', 'weibo', 'twitter']
    ttl = int(body.get('ttl_days') or 14)
    from core import share as _share
    res = _share.create_share_set(did, platforms, str(user.get('id') or ''), ttl)
    res['title'] = d.get('title', '')
    return {'ok': True, **res}

@router.get('/api/drafts/{did}/shares')
def draft_list_shares(did: str, request: Request):
    """列出某篇稿件的全部分享链接（含访问次数）。"""
    _a.guard(request)
    from core import share as _share
    return {'ok': True, 'items': _share.list_shares(draft_id=did)}

