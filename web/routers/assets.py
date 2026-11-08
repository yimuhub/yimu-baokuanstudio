# SPDX-License-Identifier: BUSL-1.1
"""视觉资产库路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

@router.get('/api/assets/library')
def get_asset_library(request: Request, q: str='', page: int=1, per_page: int=60):
    """扫描所有草稿图片，返回全局素材库（支持关键词过滤和分页）

    ⭐ R3-9：素材库只扫**当前用户自己**的草稿目录。素材是稿件的派生物，
       扫全库等于把别人的图片素材也交出来，与草稿正文同级别机密。
    """
    user = _a.guard(request)
    import pathlib, time as _time
    drafts_dir = pathlib.Path('data/drafts')
    if not drafts_dir.exists():
        return {'ok': True, 'assets': [], 'total': 0}
    all_drafts = {}
    try:
        _mine = {d.get('id', ''): d.get('title', '') for d in db.list_drafts(_a._current_user_id(user), is_admin=_a._is_admin_user(user))}
        all_drafts = _mine
    except Exception:
        pass
    assets = []
    for draft_dir in sorted(drafts_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not draft_dir.is_dir():
            continue
        img_dir = draft_dir / 'img'
        if not img_dir.exists():
            continue
        did = draft_dir.name
        if did not in all_drafts:
            continue
        draft_title = all_drafts.get(did, did)
        for img_file in sorted(img_dir.glob('*.png'), key=lambda f: f.stat().st_mtime, reverse=True):
            name = img_file.stem
            if q and q.lower() not in draft_title.lower() and (q.lower() not in name.lower()):
                continue
            stat = img_file.stat()
            assets.append({'draft_id': did, 'draft_title': draft_title, 'name': name, 'url': f'/img/{did}/{img_file.name}', 'size': stat.st_size, 'mtime': round(stat.st_mtime)})
    total = len(assets)
    start = (page - 1) * per_page
    return {'ok': True, 'assets': assets[start:start + per_page], 'total': total, 'page': page, 'per_page': per_page}

@router.post('/api/assets/batch_delete')
async def batch_delete_assets(request: Request):
    """批量删除素材库图片资产"""
    _a.guard(request)
    body = await request.json()
    items = body.get('items') or []
    if not items:
        raise HTTPException(400, '请提供要删除的素材列表')
    deleted = 0
    failed = []
    import pathlib
    for item in items:
        did = item.get('draft_id', '')
        name = item.get('name', '')
        if not did or not name:
            continue
        p = pathlib.Path(f'data/drafts/{did}/img/{name}.png')
        if p.exists() and p.is_file():
            try:
                p.unlink()
                deleted += 1
            except Exception as e:
                failed.append({'did': did, 'name': name, 'error': str(e)})
        else:
            deleted += 1
    return {'ok': True, 'deleted_count': deleted, 'failed': failed}

@router.post('/api/assets/delete')
async def delete_single_asset(request: Request):
    """删除单张素材库图片资产"""
    _a.guard(request)
    body = await request.json()
    did = body.get('draft_id', '')
    name = body.get('name', '')
    url = body.get('url', '')
    if url and (not (did and name)):
        import re
        m = re.search('/api/drafts/([^/]+)/img/([^/?#]+)', url)
        if m:
            did = m.group(1)
            name = m.group(2).replace('.png', '')
    if not did or not name:
        return {'ok': False, 'error': '缺少 draft_id 或 name 参数'}
    import pathlib
    p = pathlib.Path(f'data/drafts/{did}/img/{name}.png')
    if p.exists() and p.is_file():
        try:
            p.unlink()
        except Exception as e:
            return {'ok': False, 'error': str(e)}
    return {'ok': True, 'deleted': True}

@router.post('/api/assets/generate_hyper_real')
async def generate_hyper_real_asset(request: Request):
    """电影级普利策超写实文生图接口：调用当前配置的顶级大模型与生图通道生成逼真写真照片。"""
    user = _a.guard(request)
    body = await request.json()
    prompt = (body.get('prompt') or body.get('scene') or '').strip()
    if not prompt:
        raise HTTPException(400, '请输入生成画面的描述')
    did = str(body.get('draft_id') or '')
    all_d = db.list_drafts(_a._current_user_id(user), is_admin=_a._is_admin_user(user))
    if did and (not any((d.get('id') == did for d in all_d))):
        did = ''
    if not did and all_d:
        did = all_d[0]['id']
    if not did:
        did = 'global_assets'
    ddir = db.draft_dir(did)
    img_d = ddir / 'img'
    img_d.mkdir(parents=True, exist_ok=True)
    import time
    ts = int(time.time())
    out_file = img_d / f'custom-{ts}.png'
    from core.imagegen import gen_image
    ok = gen_image(prompt, out_file, size='1024x1024', context_title='超写实摄影', context_sub=prompt[:40])
    if not ok or not out_file.exists():
        raise HTTPException(500, '超写实生图失败，请检查模型网关连接')
    return {'ok': True, 'url': f'/img/{did}/{out_file.name}', 'name': out_file.stem, 'msg': '🎉 电影级真实摄影大片已生成完毕，已自动收入素材库！'}

@router.post('/api/assets/use_in_draft')
async def use_asset_in_draft(request: Request):
    """将素材库图片替换到当前草稿的指定插槽（复制文件 + 更新 body_md）"""
    _a.guard(request)
    body = await request.json()
    src_did = body.get('src_did', '')
    src_name = body.get('src_name', '')
    dst_did = body.get('dst_did', '')
    dst_slot = body.get('dst_slot', '')
    if not all([src_did, src_name, dst_did, dst_slot]):
        raise HTTPException(400, '参数不完整')
    import pathlib, shutil
    src_path = pathlib.Path(f'data/drafts/{src_did}/img/{src_name}.png')
    dst_dir = pathlib.Path(f'data/drafts/{dst_did}/img')
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_path = dst_dir / f'{dst_slot}.png'
    if not src_path.exists():
        raise HTTPException(404, f'源图片不存在: {src_path}')
    shutil.copy2(str(src_path), str(dst_path))
    try:
        from core.imagegen import recompile_previews
        recompile_previews(dst_did)
    except Exception:
        pass
    return {'ok': True, 'dst_url': f'/img/{dst_did}/{dst_slot}.png'}

