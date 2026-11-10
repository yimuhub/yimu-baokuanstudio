# SPDX-License-Identifier: BUSL-1.1
"""文件与分享展示(/s /card /img /audio /video /preview)路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

@router.get('/audio/drama/{did}/{filename}')
def drama_audio_file(did: str, filename: str):
    f = db.draft_dir(did) / 'drama' / 'audio' / filename
    if not f.exists():
        raise HTTPException(404, '音频未找到')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='audio/mpeg')

@router.get('/img/drama/{did}/images/{filename}')
def drama_image_file(did: str, filename: str):
    f = db.draft_dir(did) / 'drama' / 'images' / filename
    if not f.exists():
        raise HTTPException(404, '图片未找到')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='image/png')

@router.get('/img/storyboard/{did}/images/{filename}')
def storyboard_image_file(did: str, filename: str):
    f = db.draft_dir(did) / 'storyboard_images' / filename
    if not f.exists():
        raise HTTPException(404, '分镜图片未找到')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='image/png')

@router.get('/img/drama/{did}/assets/{filename}')
def drama_asset_file(did: str, filename: str):
    f = db.draft_dir(did) / 'drama' / 'assets' / filename
    if not f.exists():
        raise HTTPException(404, '资产图片未找到')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='image/png')

@router.get('/img/drama/{did}/shots/{filename}')
def drama_shot_image_file(did: str, filename: str):
    f = db.draft_dir(did) / 'drama' / 'shots' / filename
    if not f.exists():
        raise HTTPException(404, '分镜图片未找到')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='image/png')

@router.get('/video/drama/{did}/shots/{filename}')
def drama_shot_video_file(did: str, filename: str):
    f = db.draft_dir(did) / 'drama' / 'shots' / filename
    if not f.exists():
        raise HTTPException(404, '分镜视频未找到')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='video/mp4')

@router.get('/video/drama/{did}/{filename}')
def drama_video_file(did: str, filename: str):
    f = db.draft_dir(did) / 'drama' / filename
    if not f.exists():
        raise HTTPException(404, '短剧视频未找到')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='video/mp4')

@router.get('/preview/{did}/{platform}')
def preview(did: str, platform: str):
    """分平台 HTML 预览（V15.8：六平台统一，缺失时懒生成，老草稿自动自愈）。"""
    from adapters.base import SUPPORTED_PREVIEW_PLATFORMS
    from core import previews
    if platform not in SUPPORTED_PREVIEW_PLATFORMS:
        raise HTTPException(400, '不支持的预览平台')
    f = previews.ensure_preview(did, platform)
    if not f:
        raise HTTPException(404, '预览未生成')
    return FileResponse(f)

@router.get('/s/{token}')
def share_page(token: str):
    """分享页：用令牌换取已排版产物并渲染。

    令牌无效 / 过期 / 已吊销 / 产物丢失，一律404——不区分具体原因，
    避免被拿去探测「某篇稿件是否存在」。
    """
    from core import share as _share
    rec = _share.resolve(token)
    if not rec:
        raise HTTPException(404, '分享链接无效或已失效')
    f = db.draft_dir(rec['draft_id']) / f"preview-{rec['platform']}.html"
    if not f.exists():
        raise HTTPException(404, '分享链接无效或已失效')
    return HTMLResponse(_share.render_share_page(rec, f.read_text(encoding='utf-8')))

@router.get('/s/{token}/qr.svg')
def share_qr(token: str):
    """分享链接的二维码（SVG，矢量、体积小）。"""
    from core import qrcode_min, share as _share
    if not _share.resolve(token):
        raise HTTPException(404, '分享链接无效或已失效')
    svg = qrcode_min.encode_svg(f'{_share._base_url()}/s/{token}')
    return Response(svg, media_type='image/svg+xml', headers={'Cache-Control': 'public, max-age=3600'})

@router.get('/s/{token}/qr.png')
def share_qr_png(token: str):
    """分享链接的二维码（PNG，便于不支持 SVG 的场景）。"""
    from core import qrcode_min, share as _share
    if not _share.resolve(token):
        raise HTTPException(404, '分享链接无效或已失效')
    png = qrcode_min.encode_png(f'{_share._base_url()}/s/{token}')
    return Response(png, media_type='image/png', headers={'Cache-Control': 'public, max-age=3600'})

@router.get('/s/{token}/poster.svg')
def share_poster(token: str):
    """分享海报（标题 + 二维码 + 品牌署名，可直接发社群）。"""
    from core import share as _share
    rec = _share.resolve(token)
    if not rec:
        raise HTTPException(404, '分享链接无效或已失效')
    svg = _share.build_poster(rec['draft_id'], token)
    return Response(svg, media_type='image/svg+xml')

@router.get('/s/{token}/img/{name}')
def share_media_img(token: str, name: str):
    """分享页配图（令牌作用域）。

    ⭐ 为什么要这条路由：`/img/{did}/{name}` 现在是 fail-closed 的，
       匿名访客会 401。分享页由 :func:`core.share.rewrite_media_urls`
       把图片地址改写成这里，令牌 → 稿件映射在服务端库，
       因此「令牌有效」即可读图，无法通过改 did 拿别人的图。
    """
    from core import share as _share
    if '/' in name or '\\' in name or '..' in name:
        raise HTTPException(400, 'bad name')
    rec = _share.resolve(token, count_hit=False)
    if not rec:
        raise HTTPException(404, '分享链接无效或已失效')
    f = db.draft_dir(str(rec['draft_id'])) / 'img' / name
    if not f.is_file():
        raise HTTPException(404, '图片不存在')
    resp = FileResponse(f, media_type='image/png')
    resp.headers['Cache-Control'] = 'public, max-age=600'
    return resp

@router.get('/s/{token}/card/{name}')
def share_media_card(token: str, name: str):
    """分享页卡片图（令牌作用域），语义同 :func:`share_media_img`。"""
    from core import share as _share
    if '/' in name or '\\' in name or '..' in name or (not name.startswith('card-')):
        raise HTTPException(400, 'bad name')
    rec = _share.resolve(token, count_hit=False)
    if not rec:
        raise HTTPException(404, '分享链接无效或已失效')
    f = db.draft_dir(str(rec['draft_id'])) / name
    if not f.is_file():
        raise HTTPException(404, '卡片不存在')
    resp = FileResponse(f, media_type='image/png')
    resp.headers['Cache-Control'] = 'public, max-age=600'
    return resp

@router.get('/card/{did}/{name}')
def card(did: str, name: str):
    if '/' in name or not name.startswith('card-'):
        raise HTTPException(400, 'bad name')
    f = db.draft_dir(did) / name
    if not f.exists():
        raise HTTPException(404, '卡片未生成')
    return FileResponse(f, media_type='image/png')

@router.get('/img/{did}/{name}')
def draft_img(did: str, name: str):
    if '/' in name or '..' in name:
        raise HTTPException(400, 'bad name')
    f = db.draft_dir(did) / 'img' / name
    if not f.exists():
        raise HTTPException(404, '图片未生成')
    resp = FileResponse(f, media_type='image/png')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

