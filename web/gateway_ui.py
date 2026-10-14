# SPDX-License-Identifier: BUSL-1.1
"""V7「网关管理 / 会员与账本」功能页与 UI 专用 API（WS1 交付）。

页面（需 B 主应用 Cookie 登录态）：
- GET /admin/gateway  网关管理：模型服务状态表（13 个预设服务：名称 / 是否已配置 Key /
  缺 Key 时的配置指引）、网关 Key 管理区（创建 / 列表 / 吊销）、测试调用。
- GET /admin/billing  会员与账本：当前登录用户的档位卡（档位中文名 / 剩余额度 /
  累计使用）、账本历史表（最近 50 条）、管理员区（邀请码创建与列表、
  launch_mode 查看与切换）。

UI 专用 API（统一错误体 {ok,code,message,hint,request_id}；金额整数；账本只 INSERT）：
- POST /api/gw/ui/keys                 创建网关 Key（明文只在本次响应返回）
- GET  /api/gw/ui/keys                 Key 列表（永不返回明文与哈希）
- POST /api/gw/ui/keys/{id}/revoke     吊销（status=revoked，不删行）
- POST /api/gw/ui/test-call            用指定 Key 调一次 chat，走网关流水线
                                       （鉴权→限速→扣费→模型服务）；无可用服务
                                       时用 echo 回显并明确标注
- GET  /api/billing/ui/me              我的档位 / 剩余额度 / 累计使用
- POST /api/billing/ui/init            一键初始化会员（studio 用户不存在时）
- GET  /api/billing/ui/ledger          账本历史（limit/offset 分页）
- POST /api/billing/ui/invites         管理员：创建邀请码
- GET  /api/billing/ui/invites         管理员：邀请码列表
- GET /api/billing/ui/launch_mode      管理员：查看 launch_mode
- PUT /api/billing/ui/launch_mode      管理员：切换 invite-only | public

复用（不重写）：
- 网关流水线函数：gateway/limits.py（check_rate_limit / check_key_quota /
  charge_or_429 / write_ledger_rows）、gateway/config.py（定价 / 错误体）、
  gateway/routers_openai.py 的 _call_upstream（模型服务调用实现）与 echo。
- 会员逻辑：studio/membership/service.py。
- 模型服务清单与 Key 配置状态：core/llm.py（MODEL_PROVIDERS /
  get_all_configured_providers）。
- 数据：与主应用共用同一 sqlite 文件（core/db.py 的 DB_PATH），studio 侧
  用 sqlite:///<同一文件> 建引擎，init_db 幂等建表；租户统一用 'default'。
- 鉴权：B 主应用 Cookie 登录态。函数内 from core import auth 做
  verify_token（模块顶层不引 web.admin，避免循环导入）；未携带有效
  Cookie 时回退 web.admin.get_current_user（兼容 loopback 免密与旧 token）。

用户→会员映射：web 登录的 user_id 在 studio users 表可能不存在；
查不到时 /api/billing/ui/me 返回 initialized=false 与明确指引，
由「一键初始化」按钮调 POST /api/billing/ui/init 建用户 + 建会员，
绝不伪造额度数字。
"""
from __future__ import annotations

import functools
import html
import logging
import os
import secrets
import threading
import time
from datetime import timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from core.db import DB_PATH as MAIN_DB_PATH
from core.llm import MODEL_PROVIDERS, get_all_configured_providers
from gateway import routers_openai as _openai
from gateway.config import (
    CODE_HTTP,
    GatewayError,
    UpstreamConfig,
    credits_for_tokens,
    err_body,
    estimate_tokens,
    load_pricing,
    load_settings,
    new_request_id,
    ok_body,
)
from gateway.deps import key_public_dict
from gateway.limits import (
    RateLimiter,
    charge_or_429,
    check_key_quota,
    check_rate_limit,
    write_ledger_rows,
)
from studio.db import get_engine, get_session_factory, init_db
from studio.db_models import (
    GatewayKey,
    Invite,
    Ledger,
    Membership,
    Tenant,
    User,
    hash_gateway_key,
    new_id,
    utcnow,
)
from studio.membership.service import (
    create_invite,
    credits_left,
    ensure_membership,
    tier_name,
)

router = APIRouter()
log = logging.getLogger("yimu.gateway_ui")

# 租户：V7.0 单工作室部署统一用 'default'
TENANT_ID = "default"
# UI 管理员判定：web 登录态 role 为 admin / owner
ADMIN_ROLES = ("admin", "owner")


# ---------------------------------------------------------------------------
# DB：与主应用共用同一 sqlite 文件（YIMU_DB_URL 优先，用于测试隔离）
# ---------------------------------------------------------------------------

_factory = None
_factory_url: str | None = None
_factory_lock = threading.Lock()


def _db_url() -> str:
    """studio 侧数据库 URL：环境变量优先，否则复用主应用的 sqlite 文件。"""
    url = (os.environ.get("YIMU_DB_URL") or "").strip()
    if url:
        return url
    # MAIN_DB_PATH 为绝对路径 → sqlite:////abs/path（4 斜杠）
    return "sqlite:///" + str(MAIN_DB_PATH)


def _session_factory():
    """惰性单例：建引擎 + 幂等建表 + 确保 default 租户行存在。"""
    global _factory, _factory_url
    url = _db_url()
    if _factory is None or _factory_url != url:
        with _factory_lock:
            if _factory is None or _factory_url != url:
                if url.startswith("sqlite:///"):
                    parent = os.path.dirname(os.path.abspath(url[len("sqlite:///"):]))
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                engine = get_engine(url)
                init_db(engine)
                fac = get_session_factory(engine)
                s = fac()
                try:
                    if s.get(Tenant, TENANT_ID) is None:
                        s.add(Tenant(id=TENANT_ID, name="default", plan="free",
                                     launch_mode="invite-only", is_active=True,
                                     created_at=utcnow()))
                        s.commit()
                finally:
                    s.close()
                _factory = fac
                _factory_url = url
    return _factory


def _db():
    """取一个新 Session（调用方负责 close）。"""
    return _session_factory()()


# ---------------------------------------------------------------------------
# 统一错误体与鉴权
# ---------------------------------------------------------------------------


def _fail(code: str, message: str, hint: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=CODE_HTTP.get(code, 500),
        content=err_body(code, message, hint, new_request_id()),
    )


def _api(fn):
    """API 统一错误转换装饰器：业务异常 → 统一错误体；未预期异常脱敏为 500。"""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except GatewayError as e:
            return JSONResponse(
                status_code=CODE_HTTP.get(e.code, 500),
                content=err_body(e.code, e.message, e.hint, new_request_id(), **e.extra),
            )
        except HTTPException as e:
            # studio.errors.raise_err 抛出：detail 即统一错误体 dict
            if isinstance(e.detail, dict) and "ok" in e.detail:
                return JSONResponse(status_code=e.status_code, content=e.detail)
            return _fail("INTERNAL", str(e.detail) if e.detail else "请求处理失败")
        except Exception:
            log.exception("gateway_ui 未预期异常")
            return _fail("INTERNAL", "服务内部出现问题，请稍后重试", "如持续失败请联系管理员")
    return wrapper


def _current_user(request: Request) -> dict | None:
    """取当前登录用户（B 主应用 Cookie 登录态）。

    1) 优先验 mf_v6_token / mf_token 的签名 Token（函数内导入 core.auth，
       避免模块顶层循环导入）；
    2) 回退 web.admin.get_current_user（兼容 loopback 免密与旧版 token）。
    返回 {"user_id","username","role"} 或 None。
    """
    try:
        from core import auth  # noqa: E402  函数内导入，避免循环导入
        token = request.cookies.get("mf_v6_token") or request.cookies.get("mf_token", "")
        payload = auth.verify_token(token)
    except Exception:
        payload = None
    if payload and payload.get("user_id"):
        return {
            "user_id": str(payload["user_id"]),
            "username": str(payload.get("username", "")),
            "role": str(payload.get("role", "user")),
        }
    try:
        from web.admin import get_current_user  # noqa: E402  函数内导入，避免循环导入
        u = get_current_user(request)
    except Exception:
        u = None
    if u:
        return {
            "user_id": str(u.get("id", "")),
            "username": str(u.get("username", "")),
            "role": str(u.get("role", "user")),
        }
    return None


def _require_login(request: Request) -> dict:
    """API 鉴权：未登录 → 401 统一错误体。"""
    user = _current_user(request)
    if not user or not user.get("user_id"):
        raise GatewayError("UNAUTHORIZED", "未登录或登录态已失效，请先登录",
                           "请返回工作台完成登录后重试")
    return user


def _require_admin(request: Request) -> dict:
    """管理员鉴权：非管理员 → 403 统一错误体。"""
    user = _require_login(request)
    if user.get("role") not in ADMIN_ROLES:
        raise GatewayError("FORBIDDEN", "需要管理员权限", "请使用管理员账号登录后重试")
    return user


def _studio_user(db, user: dict) -> User | None:
    """按 web user_id 查 studio 用户行（租户隔离）。"""
    return (
        db.query(User)
        .filter(User.id == user["user_id"], User.tenant_id == TENANT_ID)
        .first()
    )


def _dt_str(dt) -> str:
    if not dt:
        return ""
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)


# ---------------------------------------------------------------------------
# 模型服务池（测试调用用）：与 gateway/main.py 同源的上游组装逻辑
# ---------------------------------------------------------------------------

_pool = None
_pool_lock = threading.Lock()
_limiter = RateLimiter()


def _upstream_pool():
    """惰性构建上游池：配置来自环境变量（YIMU_UPSTREAMS），Key 只读内存。"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                settings = load_settings()
                pool = []
                for cfg in settings.upstreams:
                    api_key = os.environ.get(cfg.api_key_env) if cfg.api_key_env else None
                    pool.append(_openai.UpstreamEntry(
                        cfg=cfg,
                        breaker=_openai.CircuitBreaker(
                            cfg.id,
                            fail_threshold=settings.circuit_fail_threshold,
                            open_seconds=settings.circuit_open_seconds,
                        ),
                        api_key=api_key,
                    ))
                _pool = (pool, settings)
    return _pool


def _echo_entry(model: str) -> _openai.UpstreamEntry:
    """本地 echo 条目：无可用模型服务时用于测试链路（明确标注回显）。"""
    cfg = UpstreamConfig(
        id="echo",
        base_url="echo://local",
        api_key_env="",
        models=[model],
        timeout_sec=5.0,
        capabilities={model: ["chat"]},
        echo=True,
    )
    return _openai.UpstreamEntry(cfg=cfg, breaker=_openai.CircuitBreaker("echo"), api_key=None)


def _pick_test_entry(model: str):
    """测试调用选服务：有 Key 的真实服务优先，否则 echo（返回 entry, 是否回显）。"""
    pool, _settings = _upstream_pool()
    for e in pool:
        if e.api_key and model in e.cfg.models and e.breaker.allow():
            return e, False
    return _echo_entry(model), True


# ---------------------------------------------------------------------------
# 页面：HTML 骨架与两个功能页
# ---------------------------------------------------------------------------

_PAGE_CSS = """
/* 一幕·YIMU V7 功能页设计语言：与 B 主站（web/templates/index.html）对齐。
   主色 --primary #f0883e（橙），卡片/边框/圆角/按钮/徽章/输入框全部复用 B 主站组件类。 */
:root{
  --bg:#07090e; --card:#121824; --card-hover:#192233; --border:#232d3d; --border-light:#303b4d;
  --primary:#f0883e; --primary-hover:#ff9d55; --primary-subtle:rgba(240,136,62,.16);
  --text:#f0f6fc; --text-muted:#8b98a8;
  --success:#3fb950; --info:#58a6ff; --warn:#d29922; --danger:#f85149;
  --radius:14px; --radius-sm:8px;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--bg);color:var(--text);min-height:100vh;
  background-image:radial-gradient(circle at 50% 0%,rgba(240,136,62,.06) 0%,transparent 60%),radial-gradient(circle at 100% 100%,rgba(168,85,247,.05) 0%,transparent 50%)}
.page-wrap{max-width:1180px;margin:0 auto;padding:28px 22px 64px}
.page-top{display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.page-top h1{font-size:22px;margin:0;color:var(--text)}
.page-back{color:var(--primary);text-decoration:none;font-size:14px;white-space:nowrap}
.page-back:hover{color:var(--primary-hover)}
.page-nav{display:flex;gap:6px}
.page-nav a{color:var(--text-muted);text-decoration:none;font-size:13px;padding:6px 12px;border-radius:var(--radius-sm)}
.page-nav a:hover{color:var(--text);background:rgba(255,255,255,.04)}
.page-nav a.on{color:var(--primary);background:var(--primary-subtle);font-weight:600}
.page-user{margin-left:auto;font-size:13px;color:var(--text-muted)}
.ver-badge{font-size:11px;color:var(--text-muted);border:1px solid var(--border);border-radius:999px;padding:2px 10px;white-space:nowrap}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px 22px;margin-bottom:18px}
.card h2{font-size:16px;margin:0 0 6px;color:var(--text)}
.card .sub{font-size:13px;color:var(--text-muted);margin:0 0 16px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:8px 16px;border-radius:var(--radius-sm);font-size:13.5px;font-weight:600;cursor:pointer;border:1px solid transparent;transition:all .15s ease;user-select:none;background:var(--primary);color:#fff;font-family:inherit;text-decoration:none}
.btn:hover{background:var(--primary-hover)}
.btn:active{transform:scale(.98)}
.btn[disabled]{opacity:.5;cursor:not-allowed;transform:none!important}
.btn.ghost{background:transparent;border-color:var(--border);color:var(--text)}
.btn.ghost:hover{background:rgba(255,255,255,.06)}
.btn.warn{background:transparent;border:1px solid rgba(248,81,73,.5);color:var(--danger)}
.btn.warn:hover{background:rgba(248,81,73,.1)}
.btn-sm{padding:5px 10px;font-size:12px}
.badge{display:inline-flex;align-items:center;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:600;letter-spacing:.2px;white-space:nowrap}
.badge.green{background:rgba(63,185,80,.18);color:#56d364;border:1px solid rgba(63,185,80,.3)}
.badge.red{background:rgba(248,81,73,.18);color:#ff7b72;border:1px solid rgba(248,81,73,.3)}
.badge.blue{background:rgba(88,166,255,.18);color:#79c0ff;border:1px solid rgba(88,166,255,.3)}
.badge.gold{background:rgba(227,179,65,.18);color:#f2cc60;border:1px solid rgba(227,179,65,.3)}
.badge.gray{background:rgba(110,118,129,.2);color:#8b949e;border:1px solid var(--border)}
input[type=text],input[type=password],input[type=number],textarea,select{background:#0d1117;border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);padding:8px 12px;font-size:13.5px;font-family:inherit;outline:none;transition:border-color .15s}
input[type=text]:focus,input[type=password]:focus,input[type=number]:focus,textarea:focus,select:focus{border-color:var(--primary)}
textarea{width:100%;min-height:84px;resize:vertical}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;padding:10px 12px;color:var(--text-muted);font-weight:600;border-bottom:1px solid var(--border);white-space:nowrap;font-size:12px}
.tbl td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:top;color:var(--text)}
.tbl tr:last-child td{border-bottom:none}
.form-row{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-bottom:16px}
.field{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--text-muted)}
.result-box{margin-top:14px;background:#0d1117;border:1px solid var(--border);border-radius:var(--radius-sm);padding:16px;font-size:13px;display:none}
.result-box.show{display:block}
.result-box pre{white-space:pre-wrap;word-break:break-word;margin:8px 0 0;color:var(--text);font-family:inherit}
.meta-row{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--text-muted);margin-top:10px}
.note{font-size:12px;color:var(--text-muted);line-height:1.7}
code,.code{font-family:var(--mono);background:rgba(255,255,255,.06);padding:2px 8px;border-radius:6px;font-size:12px;color:var(--text)}
.keybox{background:rgba(63,185,80,.08);border:1px dashed rgba(63,185,80,.5);border-radius:var(--radius-sm);padding:14px 16px;margin:0 0 16px;font-size:13px;display:none}
.keybox.show{display:block}
.tier-row{display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.tier-name{font-size:20px;font-weight:600;color:var(--text)}
.stat{display:flex;flex-direction:column;gap:4px}
.stat .v{font-size:22px;font-weight:600;color:var(--text)}
.stat .k{font-size:12px;color:var(--text-muted)}
.bar{height:8px;background:rgba(255,255,255,.08);border-radius:999px;overflow:hidden;margin-top:12px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--primary),#a855f7);border-radius:999px}
.login-wrap{min-height:60vh;display:flex;align-items:center;justify-content:center}
"""


def _shell(title: str, body: str, username: str = "", active: str = "", embed: bool = False) -> str:
    """功能页外壳：B 主站风格顶栏（返回工作台 + 功能页互链 + V7 徽章 + 登录态）。

    embed=True（控制中心 iframe 内嵌）时隐藏返回按钮和互链导航，只保留标题+V7 徽章。
    """
    user_html = f'<div class="page-user">当前登录：{html.escape(username)}</div>' if username else ""
    if embed:
        top_nav = ""
    else:
        nav = "".join(
            f'<a href="{href}" class="{"on" if active == key else ""}">{label}</a>'
            for key, href, label in (
                ("gateway", "/admin/gateway", "网关管理"),
                ("billing", "/admin/billing", "会员与账本"),
            )
        )
        top_nav = f'<a class="page-back" href="/">← 返回工作台</a><nav class="page-nav">{nav}</nav>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · 一幕·YIMU V9.1.1</title>
<link rel="stylesheet" href="/static/css/modern_studio.css">
<style>{_PAGE_CSS}</style>
</head><body>
<div class="page-wrap">
<div class="page-top">{top_nav}<h1>{html.escape(title)}</h1>
<span class="ver-badge">V9.1.1</span>{user_html}</div>
{body}
</div>
<script>
async function gwFetch(url, opt) {{
  opt = opt || {{}};
  opt.headers = Object.assign({{'Content-Type': 'application/json'}}, opt.headers || {{}});
  const r = await fetch(url, opt);
  let j = null;
  try {{ j = await r.json(); }} catch (e) {{}}
  return {{status: r.status, body: j}};
}}
function gwToast(el, ok, text) {{
  el.className = 'result-box show';
  el.innerHTML = '<span class="badge ' + (ok ? 'green' : 'red') + '">' + (ok ? '成功' : '失败') + '</span><pre></pre>';
  el.querySelector('pre').textContent = text;
}}
</script>
</body></html>"""


def _login_required_page() -> HTMLResponse:
    body = ('<div class="login-wrap"><div class="card" style="text-align:center;max-width:420px">'
            '<h2>请先登录</h2><p class="sub">登录后即可管理网关 Key、查看会员额度与调用账本。</p>'
            '<a class="btn" style="text-decoration:none;display:inline-block" href="/">前往工作台登录</a>'
            '</div></div>')
    return HTMLResponse(_shell("请先登录", body), status_code=401)


def _provider_rows() -> str:
    """13 个预设模型服务的状态行：名称 / Key 配置状态 / 缺 Key 指引。"""
    try:
        states = get_all_configured_providers()
    except Exception:
        states = {}
    rows = []
    for pid, pinfo in MODEL_PROVIDERS.items():
        st = states.get(pid, {}) if isinstance(states, dict) else {}
        name = st.get("name") or pinfo.get("name", pid)
        icon = pinfo.get("icon", "⚡")
        badge = st.get("badge") or pinfo.get("badge", "")
        models = pinfo.get("models", [])
        default_model = pinfo.get("default_model", "")
        has_key = bool(st.get("has_key"))
        doc_url = pinfo.get("doc_url", "")
        tips = st.get("tips") or pinfo.get("tips", "")
        if has_key:
            key_cell = '<span class="badge green">已配置</span>'
            guide = '<span class="note">Key 已就绪，可直接调用。</span>'
        else:
            env_k = f"MEDIAFLOW_KEY_{pid.upper()}"
            guide = (f'<span class="note">尚未配置 Key：<br>1. 在 <span class="code">.env</span> 中添加 '
                     f'<span class="code">{env_k}=你的Key</span> 后重启服务；<br>'
                     f'2. 或前往「设置」页的模型服务配置中填写。</span>')
            if tips:
                guide += f'<br><span class="note">{html.escape(tips)}</span>'
            if doc_url:
                guide += (f'<br><a href="{html.escape(doc_url)}" target="_blank" rel="noopener" '
                          f'style="color:var(--brand-primary);font-size:12px">申请地址 ↗</a>')
            key_cell = '<span class="badge red">未配置</span>'
        rows.append(
            f"<tr><td>{html.escape(icon)} <b>{html.escape(name)}</b>"
            + (f' <span class="badge blue">{html.escape(badge)}</span>' if badge else "")
            + f"<br><span class='note'>{len(models)} 个模型 · 默认 {html.escape(default_model)}</span></td>"
            f"<td>{key_cell}</td><td>{guide}</td></tr>"
        )
    return "\n".join(rows)


_GATEWAY_JS = """
<script>
async function gwLoadKeys() {
  const tb = document.getElementById('gw-keys-tb');
  const r = await gwFetch(tb ? '/api/gw/ui/keys' : '/api/gw/ui/my-keys');
  const sel = document.getElementById('gw-test-key');
  sel.innerHTML = '';
  if (!r.body || !r.body.ok) {
    if (tb) tb.innerHTML = '<tr><td colspan="6">加载失败：' + ((r.body && r.body.message) || r.status) + '</td></tr>';
    return;
  }
  const items = r.body.data.items || [];
  if (!items.length) {
    if (tb) tb.innerHTML = '<tr><td colspan="6" style="color:var(--text-tertiary)">暂无 Key，请先创建一个。</td></tr>';
    return;
  }
  if (tb) tb.innerHTML = items.map(function (k) {
    const st = k.status === 'active' ? '<span class="badge green">有效</span>' : '<span class="badge red">' + k.status + '</span>';
    const op = k.status === 'active'
      ? '<button class="btn warn" onclick="gwRevokeKey(\\'' + k.id + '\\')">吊销</button>' : '—';
    return '<tr><td>' + esc(k.name || '(未命名)') + '</td><td><span class="code">' + esc(k.key_prefix) + '…</span></td>'
      + '<td>' + k.quota_credits + '</td><td>' + k.rate_limit_rpm + ' / ' + k.rate_limit_tpm + '</td>'
      + '<td>' + st + '</td><td>' + op + '</td></tr>';
  }).join('');
  items.filter(function (k) { return k.status === 'active'; }).forEach(function (k) {
    const o = document.createElement('option');
    o.value = k.id;
    o.textContent = (k.name || '(未命名)') + ' (' + k.key_prefix + '…)';
    sel.appendChild(o);
  });
}
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
async function gwCreateKey() {
  const name = document.getElementById('gw-key-name').value.trim();
  const quota = parseInt(document.getElementById('gw-key-quota').value, 10) || 0;
  const box = document.getElementById('gw-key-created');
  const r = await gwFetch('/api/gw/ui/keys', {method: 'POST', body: JSON.stringify({name: name, quota: quota})});
  if (!r.body || !r.body.ok) { gwToast(box, false, (r.body && (r.body.message + (r.body.hint ? '\\n' + r.body.hint : ''))) || ('HTTP ' + r.status)); return; }
  const d = r.body.data;
  box.className = 'keybox show';
  box.innerHTML = '<b>Key 创建成功，请立即复制保存，明文只显示一次：</b><br><br>'
    + '<span class="code" style="font-size:14px;user-select:all">' + esc(d.key) + '</span>'
    + '<br><br><span class="note">刷新或离开页面后将无法再次查看明文。</span>';
  document.getElementById('gw-key-name').value = '';
  gwLoadKeys();
}
async function gwRevokeKey(id) {
  if (!confirm('确定吊销该 Key 吗？吊销后立即失效，历史账本保留。')) return;
  const r = await gwFetch('/api/gw/ui/keys/' + id + '/revoke', {method: 'POST', body: JSON.stringify({})});
  if (!r.body || !r.body.ok) { alert('吊销失败：' + ((r.body && r.body.message) || r.status)); return; }
  gwLoadKeys();
}
async function gwTestCall() {
  const keyId = document.getElementById('gw-test-key').value;
  const model = document.getElementById('gw-test-model').value.trim() || 'yimu-chat';
  const message = document.getElementById('gw-test-msg').value.trim();
  const box = document.getElementById('gw-test-result');
  const btn = document.getElementById('gw-test-btn');
  if (!keyId) { gwToast(box, false, '请先创建一个网关 Key'); return; }
  if (!message) { gwToast(box, false, '请输入要发送的测试消息'); return; }
  btn.disabled = true; btn.textContent = '调用中…';
  try {
    const r = await gwFetch('/api/gw/ui/test-call', {method: 'POST', body: JSON.stringify({key_id: keyId, model: model, message: message})});
    if (!r.body || !r.body.ok) { gwToast(box, false, (r.body && (r.body.message + (r.body.hint ? '\\n' + r.body.hint : ''))) || ('HTTP ' + r.status)); return; }
    const d = r.body.data;
    const echoTag = d.echo ? '<span class="badge gold">回显测试，未走真实上游</span>' : '<span class="badge green">真实服务调用</span>';
    box.className = 'result-box show';
    box.innerHTML = echoTag + ' <span class="badge blue">' + esc(d.model) + '</span><pre></pre>'
      + '<div class="meta-row"><span>本次扣费：<b>' + d.credits_charged + '</b> 点</span>'
      + '<span>输入/输出 Token：' + d.input_tokens + ' / ' + d.output_tokens + '</span>'
      + '<span>账本行：' + d.ledger_ids.length + ' 行已落账</span>'
      + '<span>延迟：' + d.latency_ms + ' ms</span></div>';
    box.querySelector('pre').textContent = d.text;
  } finally {
    btn.disabled = false; btn.textContent = '发起测试调用';
  }
}
document.addEventListener('DOMContentLoaded', gwLoadKeys);
</script>
"""


def _gateway_page(user: dict, embed: bool = False) -> str:
    is_admin = user.get("role") in ADMIN_ROLES
    if is_admin:
        key_card = """
<div class="card"><h2>🔑 网关 Key 管理</h2>
<p class="sub">发放给调用方的凭证。明文 Key 只在创建成功时显示一次，入库仅保存哈希。</p>
<div class="keybox" id="gw-key-created"></div>
<div class="form-row">
  <label class="field">名称<input id="gw-key-name" placeholder="如：公众号推文服务" style="width:220px"></label>
  <label class="field">配额（点）<input id="gw-key-quota" type="number" value="100000" min="0" step="1000" style="width:140px"></label>
  <button class="btn" onclick="gwCreateKey()">创建 Key</button>
</div>
<table class="tbl"><thead><tr><th>名称</th><th>前缀</th><th>配额（点）</th><th>限速 rpm/tpm</th><th>状态</th><th>操作</th></tr></thead>
<tbody id="gw-keys-tb"><tr><td colspan="6">加载中…</td></tr></tbody></table></div>"""
    else:
        key_card = """
<div class="card"><h2>🔑 网关 Key 管理</h2>
<p class="sub">Key 的发放与吊销需要管理员权限。如需调用网关，请联系管理员为你发放 Key。</p></div>"""
    body = f"""
<div class="card"><h2>🌐 模型服务状态</h2>
<p class="sub">以下为内置的 13 个模型服务预设。Key 状态实时读取自当前环境配置。</p>
<table class="tbl"><thead><tr><th>模型服务</th><th>Key 状态</th><th>配置指引</th></tr></thead>
<tbody>{_provider_rows()}</tbody></table></div>
{key_card}
<div class="card"><h2>🧪 测试调用</h2>
<p class="sub">用指定 Key 发起一次真实的 chat 调用，全程走网关流水线：鉴权 → 限速 → 扣费 → 模型服务，并写入调用账本。</p>
<div class="form-row">
  <label class="field">调用 Key<select id="gw-test-key" style="width:240px"></select></label>
  <label class="field">模型<input id="gw-test-model" value="yimu-chat" style="width:200px"></label>
</div>
<label class="field" style="margin-bottom:10px">测试消息<textarea id="gw-test-msg" placeholder="输入一句话，例如：用一句话介绍一幕·YIMU"></textarea></label>
<button class="btn" id="gw-test-btn" onclick="gwTestCall()">发起测试调用</button>
<div class="result-box" id="gw-test-result"></div></div>
{_GATEWAY_JS}"""
    return _shell("网关管理", body, user.get("username", ""), active="gateway", embed=embed)


_BILLING_JS = """
<script>
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
async function blLoadMe() {
  const r = await gwFetch('/api/billing/ui/me');
  const box = document.getElementById('bl-tier');
  if (!r.body || !r.body.ok) { box.innerHTML = '加载失败：' + ((r.body && r.body.message) || r.status); return; }
  const d = r.body.data;
  if (!d.initialized) {
    box.innerHTML = '<p class="sub">' + esc(d.message) + '</p>'
      + '<button class="btn" onclick="blInit()">一键初始化（免费体验档）</button>';
    return;
  }
  const pct = d.credits_total > 0 ? Math.min(100, Math.round(d.credits_used / d.credits_total * 100)) : 0;
  box.innerHTML = '<div class="tier-row">'
    + '<div><div class="tier-name">' + esc(d.tier_display || d.tier_name) + '</div><div class="note">当前档位</div></div>'
    + '<div class="stat"><span class="v">' + d.credits_left + '</span><span class="k">剩余额度（点）</span></div>'
    + '<div class="stat"><span class="v">' + d.credits_used + '</span><span class="k">累计使用（点）</span></div>'
    + '<div class="stat"><span class="v">' + d.credits_total + '</span><span class="k">本周期总额（点）</span></div>'
    + '</div><div class="bar"><i style="width:' + pct + '%"></i></div>'
    + '<p class="note" style="margin-top:10px">会员额度与网关调用额度为同一账本：每次模型调用都会从这里扣减，明细见下方账本。</p>';
}
async function blInit() {
  const r = await gwFetch('/api/billing/ui/init', {method: 'POST', body: JSON.stringify({})});
  if (!r.body || !r.body.ok) { alert('初始化失败：' + ((r.body && r.body.message) || r.status)); return; }
  blLoadMe(); blLoadLedger(true);
}
var blOffset = 0;
async function blLoadLedger(reset) {
  if (reset) blOffset = 0;
  const r = await gwFetch('/api/billing/ui/ledger?limit=50&offset=' + blOffset);
  const tb = document.getElementById('bl-ledger-tb');
  const more = document.getElementById('bl-more');
  if (!r.body || !r.body.ok) {
    tb.innerHTML = '<tr><td colspan="6">加载失败：' + ((r.body && r.body.message) || r.status) + '</td></tr>';
    more.style.display = 'none';
    return;
  }
  const items = r.body.data.items || [];
  if (!items.length && blOffset === 0) {
    tb.innerHTML = '<tr><td colspan="6" style="color:var(--text-tertiary)">暂无调用记录，完成一次测试调用后这里会显示账本。</td></tr>';
    more.style.display = 'none';
    return;
  }
  const html = items.map(function (it) {
    const dir = it.direction === 'input' ? '<span class="badge blue">输入</span>' : '<span class="badge gold">输出</span>';
    return '<tr><td style="white-space:nowrap">' + esc(it.created_at) + '</td><td>' + esc(it.model) + '</td><td>' + dir + '</td>'
      + '<td>' + it.tokens + '</td><td>' + it.cost + '</td><td>' + it.latency_ms + ' ms</td></tr>';
  }).join('');
  tb.innerHTML = reset ? html : tb.innerHTML + html;
  blOffset += items.length;
  more.style.display = (r.body.data.total > blOffset) ? '' : 'none';
}
async function blLoadInvites() {
  const r = await gwFetch('/api/billing/ui/invites');
  const tb = document.getElementById('bl-inv-tb');
  if (!r.body || !r.body.ok) { tb.innerHTML = '<tr><td colspan="5">加载失败：' + ((r.body && r.body.message) || r.status) + '</td></tr>'; return; }
  const items = r.body.data.items || [];
  if (!items.length) { tb.innerHTML = '<tr><td colspan="5" style="color:var(--text-tertiary)">暂无邀请码。</td></tr>'; return; }
  tb.innerHTML = items.map(function (it) {
    return '<tr><td><span class="code">' + esc(it.code) + '</span></td><td>' + it.used_count + ' / ' + it.max_uses + '</td>'
      + '<td>' + it.credits_grant + '</td><td>' + esc(it.status) + '</td><td style="white-space:nowrap">' + esc(it.expires_at || '永不过期') + '</td></tr>';
  }).join('');
}
async function blCreateInvite() {
  const maxUses = parseInt(document.getElementById('bl-inv-uses').value, 10) || 1;
  const grant = parseInt(document.getElementById('bl-inv-grant').value, 10) || 0;
  const days = parseInt(document.getElementById('bl-inv-days').value, 10) || 0;
  const r = await gwFetch('/api/billing/ui/invites', {method: 'POST', body: JSON.stringify({max_uses: maxUses, credits_grant: grant, expires_in_days: days})});
  if (!r.body || !r.body.ok) { alert('创建失败：' + ((r.body && r.body.message) || r.status)); return; }
  alert('邀请码已创建：' + r.body.data.code);
  blLoadInvites();
}
async function blLoadMode() {
  const r = await gwFetch('/api/billing/ui/launch_mode');
  const el = document.getElementById('bl-mode');
  if (!r.body || !r.body.ok) { el.innerHTML = '加载失败'; return; }
  const m = r.body.data.launch_mode;
  el.innerHTML = '<span class="badge ' + (m === 'public' ? 'green' : 'blue') + '">' + (m === 'public' ? '公开注册' : '邀请制') + '</span>'
    + ' <span class="code">' + esc(m) + '</span>';
}
async function blSetMode(mode) {
  if (!confirm('确定切换为「' + (mode === 'public' ? '公开注册' : '邀请制') + '」吗？')) return;
  const r = await gwFetch('/api/billing/ui/launch_mode', {method: 'PUT', body: JSON.stringify({launch_mode: mode})});
  if (!r.body || !r.body.ok) { alert('切换失败：' + ((r.body && r.body.message) || r.status)); return; }
  blLoadMode();
}
document.addEventListener('DOMContentLoaded', function () {
  blLoadMe(); blLoadLedger(true);
  if (document.getElementById('bl-inv-tb')) { blLoadInvites(); blLoadMode(); }
});
</script>
"""


def _billing_page(user: dict, embed: bool = False) -> str:
    is_admin = user.get("role") in ADMIN_ROLES
    if is_admin:
        admin_card = """
<div class="card"><h2>✉️ 邀请码管理</h2>
<p class="sub">邀请制模式下，用于发放注册 / 升级资格，核销后按设定赠送额度。</p>
<div class="form-row">
  <label class="field">可用次数<input id="bl-inv-uses" type="number" value="1" min="1" style="width:110px"></label>
  <label class="field">赠送额度（点）<input id="bl-inv-grant" type="number" value="10000" min="0" step="1000" style="width:140px"></label>
  <label class="field">有效天数（0=永不过期）<input id="bl-inv-days" type="number" value="30" min="0" style="width:150px"></label>
  <button class="btn" onclick="blCreateInvite()">创建邀请码</button>
</div>
<table class="tbl"><thead><tr><th>邀请码</th><th>已用/可用</th><th>赠送额度</th><th>状态</th><th>过期时间</th></tr></thead>
<tbody id="bl-inv-tb"><tr><td colspan="5">加载中…</td></tr></tbody></table></div>
<div class="card"><h2>🚀 上线模式</h2>
<p class="sub">云端首发的注册策略：邀请制（凭邀请码注册）或公开注册。</p>
<p>当前模式：<span id="bl-mode">加载中…</span></p>
<div class="form-row">
  <button class="btn ghost" onclick="blSetMode('invite-only')">切换为邀请制</button>
  <button class="btn ghost" onclick="blSetMode('public')">切换为公开注册</button>
</div></div>"""
    else:
        admin_card = ""
    body = f"""
<div class="card"><h2>👤 我的会员</h2>
<p class="sub">会员额度与网关调用额度为同一账本。</p>
<div id="bl-tier">加载中…</div></div>
<div class="card"><h2>📒 调用账本</h2>
<p class="sub">每次模型调用的计量记录（只增不改），费用为整数点数。</p>
<table class="tbl"><thead><tr><th>时间</th><th>模型</th><th>方向</th><th>Token</th><th>费用（点）</th><th>延迟</th></tr></thead>
<tbody id="bl-ledger-tb"><tr><td colspan="6">加载中…</td></tr></tbody></table>
<div style="text-align:center;margin-top:12px"><button class="btn ghost" id="bl-more" onclick="blLoadLedger(false)">加载更多</button></div></div>
{admin_card}
{_BILLING_JS}"""
    return _shell("会员与账本", body, user.get("username", ""), active="billing", embed=embed)


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------


@router.get("/admin/gateway", response_class=HTMLResponse)
def page_gateway(request: Request):
    """网关管理功能页：模型服务状态 + Key 管理 + 测试调用。"""
    user = _current_user(request)
    if not user:
        return _login_required_page()
    embed = request.query_params.get("embed") == "1"
    return HTMLResponse(_gateway_page(user, embed=embed))


@router.get("/admin/billing", response_class=HTMLResponse)
def page_billing(request: Request):
    """会员与账本功能页：档位卡 + 账本历史 + 管理员区。"""
    user = _current_user(request)
    if not user:
        return _login_required_page()
    embed = request.query_params.get("embed") == "1"
    return HTMLResponse(_billing_page(user, embed=embed))


# ---------------------------------------------------------------------------
# 网关 Key 管理 API（管理员）
# ---------------------------------------------------------------------------


def _key_item_public(k: GatewayKey) -> dict:
    d = key_public_dict(k)
    d.pop("tenant_id", None)
    return d


@router.post("/api/gw/ui/keys")
@_api
async def ui_create_key(request: Request):
    """创建网关 Key：明文只在本次响应返回，入库只存哈希。

    ⭐ 会员分级：网关 API 为 Pro 专属；free 档位直接 403。
    """
    admin = _require_admin(request)
    # ⭐ 会员分级检查：网关 API 为 Pro 专属
    try:
        from studio.membership import capabilities as _caps

        _db2 = _db()
        try:
            _tier = _caps.get_user_tier(
                _db2, tenant_id=TENANT_ID, user_id=str(admin.get("user_id") or "")
            )
        finally:
            _db2.close()
        if not _caps.is_allowed(_tier, "gateway_api"):
            raise GatewayError(
                "FORBIDDEN",
                "网关 API 为 Pro 专属功能",
                "升级 Pro 解锁网关 API（当前档位：" + _caps.tier_display_name(_tier) + "）",
            )
    except GatewayError:
        raise
    except Exception:
        pass  # 配额系统异常时放行，不阻塞管理员操作
    try:
        body = await request.json()
    except Exception:
        raise GatewayError("BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式")
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")
    name = str(body.get("name") or "")[:128]
    quota = body.get("quota", body.get("quota_credits", 100000))
    try:
        quota = int(quota)
    except (TypeError, ValueError):
        raise GatewayError("BAD_REQUEST", "quota 必须为整数", "请传入非负整数（点数）")
    if quota < 0:
        raise GatewayError("BAD_REQUEST", "quota 不能为负数", "请传入非负整数（点数）")
    rpm = int(body.get("rate_limit_rpm", 60) or 60)
    tpm = int(body.get("rate_limit_tpm", 100000) or 100000)
    if rpm <= 0 or tpm <= 0:
        raise GatewayError("BAD_REQUEST", "限速必须为正整数", "请检查 rate_limit_rpm / rate_limit_tpm")
    db = _db()
    try:
        owner_id = str(body.get("user_id") or admin["user_id"])
        owner = (
            db.query(User)
            .filter(User.id == owner_id, User.tenant_id == TENANT_ID)
            .first()
        )
        if owner is None:
            raise GatewayError(
                "BAD_REQUEST", "会员未初始化",
                "请先到「会员与账本」页点击「一键初始化」，再回来创建 Key",
            )
        raw_key = "yimu_sk_" + secrets.token_urlsafe(32)
        key = GatewayKey(
            id=new_id(),
            tenant_id=TENANT_ID,
            user_id=owner.id,
            key_prefix=raw_key[:12],
            key_hash=hash_gateway_key(raw_key),
            name=name,
            quota_credits=quota,
            rate_limit_rpm=rpm,
            rate_limit_tpm=tpm,
            allowed_models=body.get("allowed_models"),
            ip_allowlist=body.get("ip_allowlist"),
            status="active",
            expires_at=None,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(key)
        db.commit()
        data = _key_item_public(key)
        data["key"] = raw_key  # ⭐ 仅此一次返回明文
        data["_warning"] = "请立即保存该 Key，明文不会再次显示"
        return JSONResponse(ok_body(data))
    finally:
        db.close()


@router.get("/api/gw/ui/upstream")
@_api
async def ui_upstream_status(request: Request):
    """上游模型服务状态（JSON 版，供控制中心原生视图使用）。"""
    _require_login(request)
    try:
        states = get_all_configured_providers()
    except Exception:
        states = {}
    items = []
    for pid, pinfo in MODEL_PROVIDERS.items():
        st = states.get(pid, {}) if isinstance(states, dict) else {}
        items.append({
            "id": pid,
            "name": st.get("name") or pinfo.get("name", pid),
            "icon": pinfo.get("icon", "⚡"),
            "badge": st.get("badge") or pinfo.get("badge", ""),
            "models_count": len(pinfo.get("models", [])),
            "default_model": pinfo.get("default_model", ""),
            "has_key": bool(st.get("has_key")),
            "doc_url": pinfo.get("doc_url", ""),
            "tips": st.get("tips") or pinfo.get("tips", ""),
        })
    return JSONResponse(ok_body({"items": items, "total": len(items)}))


@router.get("/api/gw/ui/keys")
@_api
async def ui_list_keys(request: Request):
    """Key 列表（永不返回明文与哈希）。"""
    _require_admin(request)
    db = _db()
    try:
        keys = (
            db.query(GatewayKey)
            .filter(GatewayKey.tenant_id == TENANT_ID)
            .order_by(GatewayKey.created_at.desc())
            .limit(200)
            .all()
        )
        return JSONResponse(ok_body({"items": [_key_item_public(k) for k in keys],
                                     "total": len(keys)}))
    finally:
        db.close()


@router.get("/api/gw/ui/my-keys")
@_api
async def ui_my_keys(request: Request):
    """当前登录用户名下有效的 Key（供测试调用下拉框使用，不含管理操作）。"""
    user = _require_login(request)
    db = _db()
    try:
        keys = (
            db.query(GatewayKey)
            .filter(GatewayKey.tenant_id == TENANT_ID,
                    GatewayKey.user_id == user["user_id"],
                    GatewayKey.status == "active")
            .order_by(GatewayKey.created_at.desc())
            .limit(100)
            .all()
        )
        return JSONResponse(ok_body({"items": [_key_item_public(k) for k in keys],
                                     "total": len(keys)}))
    finally:
        db.close()


@router.post("/api/gw/ui/keys/{key_id}/revoke")
@_api
async def ui_revoke_key(key_id: str, request: Request):
    """吊销 Key：status 置 revoked，不删行（历史账本可追溯）。"""
    _require_admin(request)
    db = _db()
    try:
        key = db.get(GatewayKey, key_id)
        if key is None or key.tenant_id != TENANT_ID:
            raise GatewayError("NOT_FOUND", "该 Key 不存在", "请检查 Key id 是否正确")
        key.status = "revoked"
        key.updated_at = utcnow()
        db.commit()
        return JSONResponse(ok_body(_key_item_public(key)))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 测试调用：走网关流水线（鉴权→限速→扣费→模型服务），账本落 input/output 两行
# ---------------------------------------------------------------------------


@router.post("/api/gw/ui/test-call")
@_api
async def ui_test_call(request: Request):
    """用指定 Key 调一次 chat：鉴权→限速→扣费→模型服务→记账。

    无可用模型服务（未配置 Key）时走 echo 回显，并在响应中明确标注
    "回显测试，未走真实上游"。成功时账本写入 input / output 两行。
    """
    user = _require_login(request)
    try:
        body = await request.json()
    except Exception:
        raise GatewayError("BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式")
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")
    key_id = str(body.get("key_id") or "")
    message = str(body.get("message") or "").strip()
    model = str(body.get("model") or "yimu-chat").strip() or "yimu-chat"
    if not key_id:
        raise GatewayError("BAD_REQUEST", "缺少 key_id 参数", "请先选择要测试的网关 Key")
    if not message:
        raise GatewayError("BAD_REQUEST", "测试消息不能为空", "请输入一句话再发起调用")
    if len(message) > 4000:
        raise GatewayError("BAD_REQUEST", "测试消息过长", "请控制在 4000 字以内")
    try:
        max_tokens = max(16, min(int(body.get("max_tokens", 512)), 2048))
    except (TypeError, ValueError):
        raise GatewayError("BAD_REQUEST", "max_tokens 必须为整数", "请传入 16~2048 的整数")
    db = _db()
    try:
        # ① 鉴权：Key 存在 / 同租户 / 有效 / 未过期 / 白名单
        key = db.get(GatewayKey, key_id)
        if key is None or key.tenant_id != TENANT_ID:
            raise GatewayError("NOT_FOUND", "该 Key 不存在", "请检查 Key id 是否正确")
        if user["role"] not in ADMIN_ROLES and key.user_id != user["user_id"]:
            raise GatewayError("FORBIDDEN", "无权使用该 Key", "请选择归属你自己的 Key，或联系管理员")
        if key.status != "active":
            raise GatewayError("FORBIDDEN", "该 Key 已失效", "请联系管理员重新发放新的 Key")
        if key.expires_at is not None:
            exp = key.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= utcnow():
                raise GatewayError("FORBIDDEN", "该 Key 已过期", "请联系管理员重新发放新的 Key")
        allowed = key.allowed_models
        if allowed and model not in allowed and "yimu-auto" not in allowed:
            raise GatewayError("FORBIDDEN", f"该 Key 未被授权调用模型 {model}",
                               "请联系管理员为该 Key 开通此模型的调用权限")
        # 会员必须已初始化（不伪造额度）
        ms = (
            db.query(Membership)
            .filter(Membership.tenant_id == TENANT_ID,
                    Membership.user_id == key.user_id)
            .first()
        )
        if ms is None:
            raise GatewayError("BAD_REQUEST", "会员未初始化",
                               "请先到「会员与账本」页点击「一键初始化」，再回来测试调用")
        # ② 计费预估 → ③ 限速 → ④ 配额 → ⑤ 原子扣费（失败直接 429，不调服务）
        est_in = estimate_tokens(message) + 4
        est_out = max_tokens
        pricing = load_pricing()
        rates = pricing.get(model) or {"input_credits_per_1k": 2, "output_credits_per_1k": 4}
        in_rate = int(rates["input_credits_per_1k"])
        out_rate = int(rates["output_credits_per_1k"])
        est_credits = credits_for_tokens(est_in, in_rate) + credits_for_tokens(est_out, out_rate)
        rid = new_request_id()
        check_rate_limit(_limiter, key, TENANT_ID, db, est_in + est_out, rid)
        check_key_quota(db, TENANT_ID, key, est_credits, rid)
        charge_or_429(db, TENANT_ID, key.user_id, est_credits)
        # ⑥ 调模型服务（无可用服务时 echo 回显）
        entry, echo_mode = _pick_test_entry(model)
        payload = {"model": model, "messages": [{"role": "user", "content": message}]}
        started = time.monotonic()
        try:
            resp = _openai._call_upstream(entry, "/chat/completions", payload)
        except _openai.UpstreamFailure as e:
            latency_ms = int((time.monotonic() - started) * 1000)
            entry.breaker.record_failure(str(e))
            raise GatewayError(
                "TIMEOUT" if e.timeout else "UPSTREAM_ERROR",
                "模型服务暂时不可用，请稍后重试",
                "已自动尝试其他可用通道；请稍后重试，或更换模型后再次尝试",
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        entry.breaker.record_success()
        in_t, out_t = _openai._usage_or_estimate(resp, est_in, est_out)
        text = ""
        try:
            text = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            text = ""
        if not isinstance(text, str):
            text = str(text)
        # ⑦ 记账：ledger 只 INSERT，input / output 各一行
        t0 = utcnow()
        cost_in, cost_out = write_ledger_rows(
            db, TENANT_ID, key.id, model, in_t, out_t,
            in_rate, out_rate, latency_ms, cached=echo_mode,
        )
        db.commit()
        rows = (
            db.query(Ledger)
            .filter(Ledger.tenant_id == TENANT_ID, Ledger.key_id == key.id,
                    Ledger.created_at >= t0)
            .order_by(Ledger.created_at.desc())
            .limit(2)
            .all()
        )
        return JSONResponse(ok_body({
            "echo": echo_mode,
            "echo_note": "回显测试，未走真实上游" if echo_mode else "",
            "text": text,
            "model": model,
            "input_tokens": in_t,
            "output_tokens": out_t,
            "credits_charged": est_credits,
            "cost_input": cost_in,
            "cost_output": cost_out,
            "ledger_ids": [r.id for r in rows],
            "latency_ms": latency_ms,
        }))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 会员与账本 API
# ---------------------------------------------------------------------------


def _membership_summary(m) -> dict:
    from studio.membership.capabilities import tier_display_name

    return {
        "initialized": True,
        "tier": m.tier,
        "tier_name": tier_name(m.tier),
        "tier_display": tier_display_name(m.tier),
        "credits_total": int(m.credits_total),
        "credits_used": int(m.credits_used),
        "credits_left": credits_left(m),
        "status": m.status,
    }


@router.get("/api/billing/ui/me")
@_api
async def ui_me(request: Request):
    """我的会员：档位 / 剩余额度 / 累计使用。未初始化时自动初始化（幂等）。"""
    user = _require_login(request)
    db = _db()
    try:
        su = _studio_user(db, user)
        if su is None:
            # 自动初始化：建 studio 用户行（此前需手动点「一键初始化」，导致徽章不显示）
            role = "admin" if user.get("role") in ADMIN_ROLES else "user"
            su = User(
                id=user["user_id"],
                tenant_id=TENANT_ID,
                username=user.get("username") or user["user_id"],
                email="",
                password_hash="!",  # studio 侧仅做关联，登录走 B 主应用
                salt="",
                role=role,
                is_active=True,
                created_at=utcnow(),
            )
            db.add(su)
            db.flush()
        m = ensure_membership(db, TENANT_ID, su.id)
        # ⭐ 管理员默认 studio 档（最高权限，基础额度至少 600 万）
        if su.id == "u-admin":
            if not m.tier:
                m.tier = "studio"
            if m.credits_total < 6000000:
                m.credits_total = 6000000
            if int(m.credits_used or 0) > int(m.credits_total or 0):
                m.credits_used = 0
        db.commit()
        return JSONResponse(ok_body(_membership_summary(m)))
    finally:
        db.close()


@router.post("/api/billing/ui/init")
@_api
async def ui_init_membership(request: Request):
    """一键初始化：建 studio 用户行 + 建 free 会员（幂等）。"""
    user = _require_login(request)
    db = _db()
    try:
        su = _studio_user(db, user)
        if su is None:
            role = "admin" if user.get("role") in ADMIN_ROLES else "user"
            su = User(
                id=user["user_id"],
                tenant_id=TENANT_ID,
                username=user.get("username") or user["user_id"],
                email="",
                password_hash="!",  # studio 侧仅做关联，登录走 B 主应用
                salt="",
                role=role,
                is_active=True,
                created_at=utcnow(),
            )
            db.add(su)
            db.flush()
        m = ensure_membership(db, TENANT_ID, su.id)
        # 支持更选/切换至 free 体验档
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        if body.get("switch_to_free"):
            m.tier = "free"
            if int(m.credits_used or 0) > int(m.credits_total or 0):
                m.credits_used = 0
        db.commit()
        return JSONResponse(ok_body(_membership_summary(m)))
    finally:
        db.close()


def _ledger_item(r: Ledger) -> dict:
    return {
        "id": r.id,
        "key_id": r.key_id,
        "model": r.model,
        "direction": r.direction,
        "tokens": int(r.tokens),
        "cost": int(r.cost_cents),  # 整数点数
        "latency_ms": int(r.latency_ms),
        "cached": bool(r.cached),
        "created_at": _dt_str(r.created_at),
    }


@router.get("/api/billing/ui/ledger")
@_api
async def ui_ledger(request: Request, limit: int = 50, offset: int = 0):
    """账本历史：管理员看本租户最近记录；普通用户只看自己 Key 的记录。"""
    user = _require_login(request)
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    db = _db()
    try:
        q = db.query(Ledger).filter(Ledger.tenant_id == TENANT_ID)
        if user["role"] not in ADMIN_ROLES:
            key_ids = [
                k.id for k in
                db.query(GatewayKey.id).filter(
                    GatewayKey.tenant_id == TENANT_ID,
                    GatewayKey.user_id == user["user_id"],
                ).all()
            ]
            q = q.filter(Ledger.key_id.in_(key_ids)) if key_ids else q.filter(False)
        total = q.count()
        rows = (
            q.order_by(Ledger.created_at.desc())
            .offset(offset).limit(limit).all()
        )
        return JSONResponse(ok_body({
            "items": [_ledger_item(r) for r in rows],
            "total": total, "limit": limit, "offset": offset,
        }))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 邀请码与上线模式（管理员）
# ---------------------------------------------------------------------------


def _invite_item(it: Invite) -> dict:
    return {
        "id": it.id,
        "code": it.code,
        "max_uses": int(it.max_uses),
        "used_count": int(it.used_count),
        "credits_grant": int(it.credits_grant),
        "status": it.status,
        "expires_at": _dt_str(it.expires_at),
        "created_at": _dt_str(it.created_at),
    }


@router.post("/api/billing/ui/invites")
@_api
async def ui_create_invite(request: Request):
    """管理员创建邀请码：可用次数 / 赠送额度 / 有效天数（0=永不过期）。"""
    admin = _require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise GatewayError("BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式")
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")
    try:
        max_uses = int(body.get("max_uses", 1))
        credits_grant = int(body.get("credits_grant", 0))
        days = int(body.get("expires_in_days", 0))
    except (TypeError, ValueError):
        raise GatewayError("BAD_REQUEST", "参数必须为整数", "请检查 max_uses / credits_grant / expires_in_days")
    if max_uses < 1:
        raise GatewayError("BAD_REQUEST", "可用次数至少为 1", "请传入正整数")
    if credits_grant < 0:
        raise GatewayError("BAD_REQUEST", "赠送额度不能为负数", "请传入非负整数")
    if days < 0:
        raise GatewayError("BAD_REQUEST", "有效天数不能为负数", "0 表示永不过期")
    expires_at = utcnow() + timedelta(days=days) if days > 0 else None
    db = _db()
    try:
        tenant = db.get(Tenant, TENANT_ID)
        invite = create_invite(
            db, tenant, max_uses=max_uses, credits_grant=credits_grant,
            expires_at=expires_at, actor=admin["user_id"],
        )
        return JSONResponse(ok_body(_invite_item(invite)))
    finally:
        db.close()


@router.get("/api/billing/ui/invites")
@_api
async def ui_list_invites(request: Request):
    """管理员查看邀请码列表。"""
    _require_admin(request)
    db = _db()
    try:
        items = (
            db.query(Invite)
            .filter(Invite.tenant_id == TENANT_ID)
            .order_by(Invite.created_at.desc())
            .limit(100)
            .all()
        )
        return JSONResponse(ok_body({"items": [_invite_item(i) for i in items],
                                     "total": len(items)}))
    finally:
        db.close()


@router.get("/api/billing/ui/launch_mode")
@_api
async def ui_get_launch_mode(request: Request):
    """管理员查看当前上线模式。"""
    _require_admin(request)
    db = _db()
    try:
        tenant = db.get(Tenant, TENANT_ID)
        return JSONResponse(ok_body({"launch_mode": tenant.launch_mode if tenant else "invite-only"}))
    finally:
        db.close()


@router.put("/api/billing/ui/launch_mode")
@_api
async def ui_set_launch_mode(request: Request):
    """管理员切换上线模式：invite-only（邀请制）| public（公开注册）。"""
    _require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise GatewayError("BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式")
    mode = str((body or {}).get("launch_mode") or "")
    if mode not in ("invite-only", "public"):
        raise GatewayError("BAD_REQUEST", "launch_mode 取值非法",
                           "仅支持 invite-only（邀请制）或 public（公开注册）")
    db = _db()
    try:
        tenant = db.get(Tenant, TENANT_ID)
        tenant.launch_mode = mode
        db.commit()
        return JSONResponse(ok_body({"launch_mode": mode}))
    finally:
        db.close()


# ------------------------------------------------- 视频合成配置中心 ---

@router.get("/api/video/config")
@_api
async def video_config_get(request: Request):
    """获取视频合成配置（Key 做掩码显示）。需要管理员权限。"""
    _require_admin(request)
    from studio import video_config as _vc
    from studio import stock as _stock
    cfg = _vc.get_masked_config()
    avail = _stock.stock_available()
    return JSONResponse(ok_body({
        "config": cfg,
        "stock_available": avail,  # 各素材引擎当前是否可用（含环境变量兜底）
        "voice_engines": list(_vc.VOICE_ENGINES),
    }))


@router.put("/api/video/config")
@_api
async def video_config_put(request: Request):
    """增量更新视频合成配置。需要管理员权限。"""
    _require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise GatewayError("BAD_REQUEST", "请求体不是合法的 JSON", "请检查 Content-Type 与请求体格式")
    if not isinstance(body, dict):
        raise GatewayError("BAD_REQUEST", "请求体格式错误", "请求体应为 JSON 对象")
    from studio import video_config as _vc
    try:
        cfg = _vc.save_config(body)
    except ValueError as e:
        raise GatewayError("BAD_REQUEST", str(e), "请检查字段取值")
    masked = _vc.get_masked_config()
    return JSONResponse(ok_body({"config": masked}))


@router.delete("/api/video/config/keys/{provider}")
@_api
async def video_config_delete_key(request: Request, provider: str):
    """删除指定素材站 Key（provider: pexels / pixabay）。需要管理员权限。"""
    _require_admin(request)
    from studio import video_config as _vc
    try:
        _vc.delete_key(provider)
    except ValueError as e:
        raise GatewayError("BAD_REQUEST", str(e), "provider 仅支持 pexels / pixabay")
    return JSONResponse(ok_body({"deleted": provider, "config": _vc.get_masked_config()}))
