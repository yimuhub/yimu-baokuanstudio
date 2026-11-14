# SPDX-License-Identifier: BUSL-1.1
"""系统健康 / 版本 / 更新 / 合规闸路由(R11 巨石拆分,自 web/admin.py 整体迁出)。

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

from adapters.base import PLATFORMS, NAMES  # noqa: E402,F811
from core import agents as AG  # noqa: E402,F811
from core import db, judge, orchestrator  # noqa: E402,F811
from core import layouter  # noqa: E402,F811
from core.llm import load_config, load_env  # noqa: E402,F811
from core import provider_registry as _reg  # noqa: E402,F811
from core.themes import WECHAT_THEMES, XHS_CARD_STYLES  # noqa: E402,F811
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form  # noqa: E402,F811
import asyncio  # noqa: E402,F811

@router.get('/api/health')
def api_health():
    # /health 本体在 pages.py(R11 拆分归属);V7 契约:/api/health 是其规范别名
    from web.routers.pages import health as _pages_health
    return _pages_health()

@router.get('/api/version')
def api_version():
    info = _a.get_app_version_info()
    return {'version': info.get('version', _a.get_app_version()), 'details': info}

@router.get('/api/system/check_update')
def api_system_check_update(force: bool=False):
    """访问 GitHub 仓库检测是否有新版本。"""
    from core import updater
    return updater.check_for_updates(force=force)

@router.post('/api/system/upgrade')
def api_system_upgrade(request: Request):
    """一键从 GitHub 同步升级最新代码（**仅管理员**）。

    🔴 注释一直写「需要管理员权限」，代码却是 guard(request)——
       任何登录用户都能触发 git pull + 重启，等于把服务端代码替换权
       交给所有注册用户。现已改为 guard_admin。
    """
    _a.guard_admin(request)
    from core import updater
    return updater.perform_upgrade()

@router.get('/api/compliance/guard')
def guard_stats(request: Request):
    """内容安全闸概况：开关状态、各词库条目数、白名单规模。"""
    _a.guard(request)
    from core import content_guard
    return content_guard.library_stats()

@router.get('/api/compliance/settings')
def compliance_settings(request: Request):
    """文字审核设置读取：开关状态 + 词库规模（设置页「内容与质量」卡片数据源）。"""
    _a.guard(request)
    from core import content_guard
    cfg = load_config()
    cg = cfg.get('content_guard') if isinstance(cfg.get('content_guard'), dict) else {}
    env_override = bool(str(load_env().get('CONTENT_GUARD_ENABLED') or '').strip())
    return {'ok': True, 'enabled': content_guard.is_enabled(), 'env_override': env_override,
            'config_enabled': bool(cg.get('enabled', True)), **content_guard.library_stats()}


@router.post('/api/compliance/settings')
async def compliance_settings_save(request: Request):
    """文字审核开关（**仅管理员**）：写入 config.yaml content_guard.enabled 并热生效。"""
    _a.guard_admin(request)
    body = await request.json()
    enabled = bool(body.get('enabled', True))
    cfg = _reg.raw_config()
    cfg['content_guard'] = {**cfg.get('content_guard', {}), 'enabled': enabled}
    _reg.write_config(cfg)
    from core import content_guard
    return {'ok': True, 'enabled': content_guard.is_enabled(),
            'msg': '文字审核已开启，发布前将自动拦截违规内容' if enabled
            else '文字审核已关闭（环境变量 CONTENT_GUARD_ENABLED 仍可强制覆盖）'}


@router.post('/api/compliance/topics/sweep')
async def guard_sweep_topics(request: Request):
    """扫描选题池，把命中内容安全闸的条目标记 blocked（**不删除**）。

    body: {"apply": false} 预演；true 真正标记。等价于 `python -m scripts.r4_cleanup --apply`。
    """
    _a.guard(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = db.sweep_blocked_topics(apply=bool(body.get('apply')))
    return {'ok': True, **res}

@router.get('/api/compliance/topics/blocked')
def guard_blocked_topics(request: Request):
    """列出被内容安全闸拦下的选题（供人工复核）。"""
    _a.guard(request)
    items = db.list_blocked_topics()
    return {'ok': True, 'total': len(items), 'items': items}

@router.post('/api/compliance/drafts/sweep')
async def guard_sweep_drafts(request: Request):
    """扫描草稿箱，把命中内容安全闸的条目标记 needs_review（**不删除**）。"""
    _a.guard(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = db.sweep_drafts_needs_review(apply=bool(body.get('apply')))
    return {'ok': True, **res}

@router.get('/api/compliance/drafts/review')
def guard_drafts_review(request: Request):
    """列出待人工复核的草稿。"""
    _a.guard(request)
    items = db.list_drafts_needs_review()
    return {'ok': True, 'total': len(items), 'items': items}

@router.post('/api/compliance/drafts/{did}/clear_review')
async def guard_clear_review(did: str, request: Request):
    """人工复核通过：清除 needs_review 标记（草稿本身保留）。"""
    _a.guard(request)
    if not db.get_draft(did):
        raise HTTPException(404, '草稿不存在')
    return {'ok': db.clear_draft_needs_review(did)}

@router.post('/api/compliance/drafts/{did}/check')
async def guard_check_draft(did: str, request: Request):
    """对单篇草稿做发布前内容安全检查（不写库，仅返回可读结论）。"""
    _a.guard(request)
    from core import content_guard
    d = db.get_draft(did)
    if not d:
        raise HTTPException(404, '草稿不存在')
    res = content_guard.pre_publish_check(d.get('body_md'), d.get('title'))
    return res.to_dict()

_EXPIRE_SWEEP_INTERVAL_S = 3600
_expire_last_sweep: list[float] = [0.0]


@router.get('/api/status')
def status(request: Request):
    user = _a.guard(request)
    cfg = load_config()
    env = load_env()
    cr = cfg.get('creation', {})
    exp_days = int(cr.get('draft_expire_days', 0))
    # v15.9.1 性能修复：过期清理从「每次 /api/status 轮询都全表扫描」节流为
    # 每小时最多一次——状态轮询是高频调用，不该附带全局写副作用。
    if exp_days > 0:
        import time as _time
        now = _time.time()
        if now - _expire_last_sweep[0] >= _EXPIRE_SWEEP_INTERVAL_S:
            _expire_last_sweep[0] = now
            try:
                db.delete_old_drafts(exp_days)
            except Exception:
                pass
    cur_ws_id = db.get_active_workspace().get('id', 'ws-default')
    # 6.3：新装环境官方通道 Key 为空时要给出明确的可执行提示，而不是让用户先撞 401。
    # V15.8.1：客户端不再联网申领试用凭证；缺 Key 时引导「管理员配置内置官方凭证 / 用户填自备 Key」。
    # V15.8.3：状态统一取 llm.diagnose()，与真正发请求时的解析结果**同源**，
    # 杜绝「界面显示已配置、一点就 401」这种两边口径不一致。
    _diag = orchestrator.llm.diagnose()
    # v15.9.1：水印配置随 /api/status 回显——此前移动端/个人中心读不到，
    # 保存与回显双断链（UI 却提示已生效）。
    from core.content_guard import is_enabled as _cg_enabled
    _guard_cfg = cfg.get('content_guard') if isinstance(cfg.get('content_guard'), dict) else {}
    # 客户支持口径：任何「用不了」的提示都必须指到设置入口，并说明随包通道的获取方式
    _guide = ('请在「设置 → 模型服务」填入自己的 API Key 并保存；'
              '若使用内置官方凭证，请联系管理员获取已开通的版本')
    _key_hint = '' if _diag['ready'] else f"{_diag.get('advice') or '当前 AI 通道尚未配置密钥。'} {_guide}"
    return {'topics': db.list_topics(workspace_id=cur_ws_id), 'drafts': [_a._draft_view(d) for d in db.list_drafts(_a._current_user_id(user), is_admin=_a._is_admin_user(user), workspace_id=cur_ws_id)], 'workspace_id': cur_ws_id, 'jobs': db.list_jobs(), 'gateway': {'base_url': _diag['base_url'], 'model': _diag['model'], 'provider_id': _diag['provider_id'], 'configured_models': orchestrator.llm.get_configured_models(), 'agent_routing': cfg.get('gateway', {}).get('agent_routing', {}), 'key_set': _diag['key_present'], 'active_key_set': _diag['key_present'], 'key_hint': _key_hint, 'llm_ok': _diag['ready'], 'diagnosis': _diag}, 'keywords': cfg.get('topics', {}).get('keywords', []), 'platform_names': NAMES, 'themes': {'wechat': {**{k: v['name'] + '（规则）' for k, v in WECHAT_THEMES.items()}, **{k: v['name'] for k, v in layouter.list_themes().items() if v.get('has_prompt')}}, 'card': {k: v['name'] for k, v in XHS_CARD_STYLES.items()}, 'current': {'wechat_theme': cr.get('wechat_theme', 'caozhou'), 'card_style': cr.get('card_style', 'magazine')}}, 'target_platforms': cr.get('target_platforms') or ['wechat_mp', 'xhs', 'toutiao', 'zhihu', 'weibo', 'twitter'], 'draft_expire_days': int(cr.get('draft_expire_days', 0)), 'quality': judge.quality_cfg(), 'image': cfg.get('image', {}), 'watermark': cfg.get('watermark', {}), 'content_guard': {'enabled': _cg_enabled(), 'configured': bool(_guard_cfg)}, 'ticket': {'enabled': env.get('TICKET_ENABLED') == '1', 'time': env.get('TICKET_TIME', '07:30'), 'dingtalk': _a.notify_ok()}, 'imgbed': {'configured': bool(env.get('GITHUB_IMGBED_TOKEN') and env.get('GITHUB_IMGBED_REPO')), 'repo': env.get('GITHUB_IMGBED_REPO', '')}, 'agents': AG.agents_cfg(), 'stages': AG.STAGES, 'skills': {k: v['description'] for k, v in AG.list_skills().items()}, 'search_sources': {'xhs': '小红书', 'toutiao': '今日头条', 'douyin': '抖音', 'weibo': '微博', 'kuaishou': '快手', 'bilibili': 'B站'}}

@router.get('/api/health/services')
def health_services(request: Request):
    """本地依赖组件探活。

    前端渲染用的是 `s.status` 与 `s.detail`，而后端此前只回 `ok`，
    于是界面永远显示「端口/状态: undefined」。这里补齐两个展示字段
    （status 给中文状态，detail 给实际探测的地址，便于用户排查端口冲突）。
    """
    _a.guard(request)
    import httpx
    out = []
    for svc in _a.HEALTH_SERVICES:
        addr = f"127.0.0.1:{svc['port']}{svc['path']}"
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                r = client.get(f'http://{addr}')
                ok = r.status_code < 500
                status = f'在线 (HTTP {r.status_code})' if ok else f'异常 (HTTP {r.status_code})'
        except Exception:
            ok = False
            status = '未启动 / 无法连接'
        out.append({**svc, 'ok': ok, 'status': status, 'detail': addr})
    return {'services': out, 'mediaflow': True}

@router.post('/api/health/repair')
async def health_repair(request: Request):
    """重启某个本地依赖组件（**仅管理员**）。

    ⭐ 修复三件事：
       1. 原来是 guard() —— 普通用户就能让服务端起/杀本机进程；
       2. 原代码硬编码了作者本机的 launchd 标签（com.czmj.apipool / com.czmj.wae），
          在别人机器上 100% 失败且报错不可读；现在从环境变量读标签，
          没配置就明确回 501（而不是静默失败）；
       3. 原来的 time.sleep(4/3/1) + subprocess.run 直接跑在 async 路由里，
          一次点击阻塞事件循环 8 秒以上（期间全站无响应），现在整体丢线程池。
    """
    _a.guard_admin(request)
    body = await request.json()
    name = str(body.get('name') or '')

    def _run() -> dict:
        import subprocess as sp
        launchd = {'apipool': ('YIMU_LAUNCHD_APIPOOL', 4), 'exporter': ('YIMU_LAUNCHD_EXPORTER', 3)}
        if name in launchd:
            env_name, wait_s = launchd[name]
            label = (_a._os.environ.get(env_name) or '').strip()
            if not label:
                raise HTTPException(501, f'当前环境未注册该组件的后台服务（缺少 {env_name}），请手动重启对应程序后重试')
            uid_ = sp.run(['id', '-u'], capture_output=True, text=True).stdout.strip()
            sp.run(['launchctl', 'kickstart', '-k', f'gui/{uid_}/{label}'], capture_output=True)
            time.sleep(wait_s)
            return {'ok': True}
        if name == 'xhsmcp':
            xb = _a.BASE / 'vendors/xhs-mcp/xiaohongshu-mcp'
            if not xb.exists():
                raise HTTPException(400, '组件未安装')
            sp.run(['pkill', '-f', 'xiaohongshu-mcp'], capture_output=True)
            time.sleep(1)
            log_dir = _a.BASE / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / 'xhsmcp.out', 'w') as _log:
                sp.Popen([str(xb), '-headless=true'], cwd=str(xb.parent), stdout=_log, stderr=sp.STDOUT)
            time.sleep(3)
            return {'ok': True}
        raise HTTPException(404, f'未知组件: {name}')
    return await asyncio.get_event_loop().run_in_executor(None, _run)

