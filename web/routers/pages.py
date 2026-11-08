# SPDX-License-Identifier: BUSL-1.1
"""页面路由(/ /m /pricing /admin 页 /releases /favicon)路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse  # noqa: E402,F811
import time  # noqa: E402,F811

@router.get('/favicon.ico')
def get_favicon():
    fav = _a.BASE / 'web' / 'static' / 'img' / 'favicon.ico'
    if fav.is_file():
        return FileResponse(str(fav), media_type='image/x-icon')
    return Response(status_code=404)

@router.post('/login')
async def login(request: Request):
    return await _a.api_login(request)

@router.get('/health')
def health():
    return {'ok': True, 'ts': time.time(), 'version': _a.get_app_version()}

@router.api_route('/m', methods=['GET', 'HEAD'])
def mobile_index(request: Request):
    """V6 专属全新设计的原生手机端页面"""
    resp = HTMLResponse(_a.get_mobile_html_page(), headers={'Cache-Control': 'no-store, must-revalidate'})
    if _a._is_loopback(request) and _a._loopback_admin_allowed():
        resp.set_cookie('mf_token', _a._token(), httponly=True, samesite='lax', max_age=30 * 86400, path='/')
    return resp

@router.api_route('/', methods=['GET', 'HEAD'])
def index(request: Request):
    ua = (request.headers.get('user-agent') or '').lower()
    is_mobile = any((m in ua for m in ('iphone', 'android', 'mobile', 'ipod', 'harmonyos', 'micromessenger')))
    html = _a.get_mobile_html_page() if is_mobile else _a.get_html_page()
    resp = HTMLResponse(html, headers={'Cache-Control': 'no-store, must-revalidate'})
    if _a._is_loopback(request) and _a._loopback_admin_allowed():
        resp.set_cookie('mf_token', _a._token(), httponly=True, samesite='lax', max_age=30 * 86400, path='/')
    return resp

@router.get('/admin/metrics')
def admin_metrics_page(request: Request):
    """运营漏斗看板页面（管理员）。纯前端拉接口，无构建步骤。"""
    _a.guard_admin(request)
    return HTMLResponse(_a.render_dynamic_html(_a._METRICS_PAGE_HTML))

@router.get('/pricing', response_class=HTMLResponse)
def pricing_page(request: Request):
    """R3-1：价格页（自包含 HTML，前端拉 /api/pricing 渲染）。

    与项目「无构建步骤」的现状一致：不引前端框架，双击即可用。
    """
    raw_html = (_a.BASE / 'web/templates/pages/pricing.html').read_text(encoding='utf-8') if (_a.BASE / 'web/templates/pages/pricing.html').exists() else _a._PRICING_PAGE_HTML
    return HTMLResponse(_a.render_dynamic_html(raw_html))

@router.get('/releases', response_class=HTMLResponse)
def releases_page(request: Request):
    """版本更新与发布历史展示页【V9.1.0】"""
    from studio.releases_page import get_releases_html
    return HTMLResponse(get_releases_html())

@router.get('/admin/releases', response_class=HTMLResponse)
def admin_releases_page(request: Request):
    """版本更新总览展示页（兼容后台路径）【V9.1.0】"""
    from studio.releases_page import get_releases_html
    return HTMLResponse(get_releases_html())

@router.get('/api/releases')
def api_releases():
    """获取版本更新与发布历史数据【V10.1】"""
    cur_ver = _a.get_app_version()
    info = _a.get_app_version_info()
    return {'ok': True, 'current_version': cur_ver, 'codename': info.get('codename', '鸿蒙始'), 'licensor': 'yimu.hyipf.com', 'releases': [{'version': '10.1', 'codename': '鸿蒙始', 'date': '2026-10-15', 'status': 'latest', 'highlights': ['全端全页面动态版本提取架构重构，彻底移除各页面写死旧版本号', '构建前端统一定义与自执行版本同步管理库 (web/static/js/version-sync.js)', '后端服务与模板渲染拦截器自动执行动态 SSR 注入与版本对齐，杜绝任何页面版本展示错误', '彻底移除前端硬编码 floorVer 地板下限保护，版本由单一真源 version.py 统一驱动']}, {'version': '10.0.1', 'codename': '鸿蒙始', 'date': '2026-10-15', 'status': 'stable', 'highlights': ['移动端与 PC 端算力 Token 统计全面拉齐，统一以 PC 端 memberships 算力账本为唯一真源', '移动端顶部导航栏新增实时算力与会员等级胶囊组件，打通与个人中心即时同步', '升级 /api/auth/me 与 /api/billing/ui/me 契约对齐，消灭移动端静态假额度与统计口径偏差']}, {'version': '10.0.0', 'codename': '鸿蒙始', 'date': '2026-10-15', 'status': 'stable', 'highlights': ['大厂级 Clean Architecture 四层工程架构重塑（app / domain / infra / web）', '/pricing 页面深度融入系统左侧固定菜单栏，打通下单、确认收款、一步核销到账与退款全流程', '抽离 web/admin.py 内联 HTML 页面为标准模板，解耦双语 JSON 词典与全局 CSS 设计变量', '统一百分制 7 维评分与 80+ 分自动重写门禁、微信公众号插图去重防连贴、浏览器弹窗单次熔断']}, {'version': '9.4.3', 'codename': '流云赋', 'date': '2026-10-14', 'status': 'stable', 'highlights': ['修复左侧菜单栏中文版「套餐与价格」显示英文键名问题，补齐双语词典与守卫', '订单「确认收款并立即激活到账（一步走通）」直连内置核销链路，彻底消除 Not Found', '/api/version 动态热加载磁盘版本与前端版本地板保护，全站版本号强一致']}, {'version': '9.4.2', 'codename': '回响曲', 'date': '2026-10-14', 'status': 'stable', 'highlights': ['/pricing 页面配备固定左侧菜单栏并内嵌至主界面 #p-pricing 面板', '四步可视化购买路径与订单收银台核销、撤单、退款闭环']}, {'version': '9.4.1', 'codename': '沉影吟', 'date': '2026-10-14', 'status': 'stable', 'highlights': ['修复极简模式微信公众号插图重复与连贴问题', '浏览器弹窗单次熔断拦截（只弹一回，未选择直接拦截）', '统一 100 分制评分标准（消除 7.3分 vs 73分不一致）与低于 80 分自动重写']}, {'version': '9.4.0', 'codename': '破阵子', 'date': '2026-10-14', 'status': 'stable', 'highlights': ['反代免密防护、CSRF 防护与 API Vault v2 加密加固', 'BYOK 自备 Key 免扣额度主链贯通与 6 维数字画像自动注入', 'SQLite 建连缓存 10 倍提速与 config.yaml 无损热更新保护']}, {'version': '9.3.1', 'codename': '万象融', 'date': '2026-10-14', 'status': 'archived', 'highlights': ['服务器生产级一键部署脚本与 Systemd 开机自启常驻守护', 'GitHub Releases 自动化同步与语义化版本防回退']}, {'version': '9.2.0', 'codename': '天工开', 'date': '2026-10-13', 'status': 'archived', 'highlights': ['自定义内容分发派生平台中枢与今日头条高密度资讯流排版规范', 'Agent 专属排版技能自学习与蒸馏']}, {'version': '9.1.1', 'codename': '流光澈', 'date': '2026-10-13', 'status': 'archived', 'highlights': ['1,768 条全量 UI 词典编译与双向可逆无损恢复机制']}, {'version': '9.0.0', 'codename': '万象生', 'date': '2026-10-13', 'status': 'milestone', 'highlights': ['原生 2K 视觉分镜引擎与零烟雾通透滤镜', '全局 i18n 国际化双语热切换']}, {'version': '8.3.33', 'codename': '灵犀汇', 'date': '2026-10-12', 'status': 'archived', 'highlights': ['独立个人中心面板与账号密码自主修改']}, {'version': '8.3.2', 'codename': '智瞳境', 'date': '2026-10-11', 'status': 'archived', 'highlights': ['十大影视级分镜视觉美学体系与小红书 5 幕磨砂卡片工坊']}]}

@router.get('/admin/users', response_class=HTMLResponse)
def admin_users_page(request: Request):
    """R3-7：用户管理页（管理员），含搜索/封禁操作。"""
    _a.guard_admin(request)
    raw_html = (_a.BASE / 'web/templates/pages/users_admin.html').read_text(encoding='utf-8') if (_a.BASE / 'web/templates/pages/users_admin.html').exists() else _a._USERS_PAGE_HTML
    return HTMLResponse(_a.render_dynamic_html(raw_html))

@router.get('/admin/audit', response_class=HTMLResponse)
def admin_audit_page(request: Request):
    """R3-8：审计日志查询页（管理员）。"""
    _a.guard_admin(request)
    raw_html = (_a.BASE / 'web/templates/pages/audit_admin.html').read_text(encoding='utf-8') if (_a.BASE / 'web/templates/pages/audit_admin.html').exists() else _a._AUDIT_PAGE_HTML
    return HTMLResponse(_a.render_dynamic_html(raw_html))

