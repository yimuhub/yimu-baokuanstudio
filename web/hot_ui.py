# SPDX-License-Identifier: BUSL-1.1
"""热榜采集真实 API + 「热榜采集」页面（WS2：A 的 studio/hot 采集 pipeline 真正接线）。

替代 web/admin.py 中「V7.1 预留」的两个 501 桩（GET /api/hot/trends、POST /api/hot/collect）。
⭐ 失败隔离语义由 studio/hot/pipeline.collect_all 保证：单平台失败只记入 detail，
绝不抛错中断其他平台；本模块只叠加 60 秒总体超时保护。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

#: 采集总体超时（秒）。超过后如实返回 COLLECT_TIMEOUT，不伪装成功。
COLLECT_TIMEOUT_SECONDS = 60.0


def _guard(request: Request):
    """复用 B 主应用 cookie 鉴权；函数内延迟导入，避免与 web.admin 循环导入（WS1 约定）。"""
    from web.admin import guard

    return guard(request)


def _request_id() -> str:
    return uuid.uuid4().hex


def _err(code: str, message: str, hint: str = "", status: int = 500) -> JSONResponse:
    """统一错误体：{ok, code, message, hint, request_id}。"""
    return JSONResponse(
        status_code=status,
        content={"ok": False, "code": code, "message": message,
                 "hint": hint, "request_id": _request_id()},
    )


def _platform_catalog() -> list[dict]:
    from studio.hot.base import platform_catalog

    return platform_catalog()


def _catalog_names() -> dict[str, str]:
    return {p["name"]: p.get("display_name") or p["name"] for p in _platform_catalog()}


def _normalize_platforms(raw: Any) -> Optional[list[str]]:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [raw]
    names = [str(p).strip() for p in raw if str(p).strip()]
    return names or None


async def _collect(platforms: Optional[list[str]], timeout: float = COLLECT_TIMEOUT_SECONDS) -> dict:
    """跑 studio/hot pipeline，带总体超时；超时返回 {"__timeout__": True}。"""
    from studio.hot.pipeline import collect_all

    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: collect_all(platforms)),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {"__timeout__": True}


@router.get("/api/hot/platforms")
async def hot_platforms(request: Request):
    """平台清单：平台码 + 中文名（从 studio/hot 注册表读取）。"""
    _guard(request)
    catalog = _platform_catalog()
    return {"ok": True, "request_id": _request_id(), "count": len(catalog),
            "platforms": catalog}


@router.get("/api/hot/trends")
async def hot_trends(request: Request, platforms: Optional[str] = None):
    """话题热度趋势（真实实现）：采集后按平台聚合 top 条目。

    platforms 可选，逗号分隔的平台码；不传则采全部平台。
    """
    _guard(request)
    names = _normalize_platforms(platforms.split(",") if platforms else None)
    try:
        summary = await _collect(names)
    except ValueError as exc:  # 未知平台码（pipeline 抛 ValueError）
        return _err("INVALID_PLATFORM", str(exc),
                    "可用平台码见 GET /api/hot/platforms", 400)
    if summary.get("__timeout__"):
        return _err("COLLECT_TIMEOUT", "部分平台超时，详见明细",
                    f"采集超过 {int(COLLECT_TIMEOUT_SECONDS)} 秒，已终止等待；可缩小平台范围后重试")
    names_zh = _catalog_names()
    trends = []
    for name, det in summary["detail"].items():
        entry: dict[str, Any] = {"platform": name,
                                 "platform_name": names_zh.get(name, name)}
        if "error" in det:
            entry.update({"status": "error", "count": 0, "top": [],
                          "error": det["error"]})
        elif "skipped" in det:
            entry.update({"status": "skipped", "count": 0, "top": [],
                          "reason": det["skipped"]})
        else:
            items = [it for it in summary["items"] if it.get("platform") == name]
            items.sort(key=lambda it: it.get("hot_score", 0) or 0, reverse=True)
            entry.update({"status": "ok", "count": det.get("count", 0),
                          "top": items[:5]})
        trends.append(entry)
    return {"ok": True, "request_id": _request_id(),
            "stats": {k: summary[k] for k in
                      ("ok_count", "fail_count", "skip_count",
                       "total_items", "new_count", "duration_ms")},
            "trends": trends}


@router.post("/api/hot/collect")
async def hot_collect(request: Request):
    """触发采集（真实实现）：body 可选 {"platforms": ["weibo", ...]}，不传则采全部。

    会员配额：free 每日 1 次、单次最多 5 个平台；超限返回 402 + 升级引导。
    """
    user = _guard(request)
    user_id = str((user or {}).get("id") or "")
    # ⭐ 会员配额检查（V7 Free 每日 1 次）
    try:
        from studio.membership import capabilities as _caps

        db = _caps.get_db_session()
        try:
            tier = _caps.get_user_tier(db, tenant_id="default", user_id=user_id)
            allowed, reason = _caps.check_and_consume(
                db, tenant_id="default", user_id=user_id,
                tier=tier, capability="hot_daily",
            )
            if not allowed:
                return _err("QUOTA_EXCEEDED", reason, "升级 V7 Pro 解锁不限次", 402)
            _tier_for_platforms = tier
        finally:
            db.close()
    except Exception:
        # 配额系统异常时直接放行，不阻塞主功能（配额是体验限制非资金）
        _tier_for_platforms = "pro"
    try:
        body = await request.json()
    except Exception:
        body = {}
    names = _normalize_platforms((body or {}).get("platforms"))
    # ⭐ 平台数量按档位截断（free 最多 5 个）
    try:
        from studio.membership import capabilities as _caps2

        _plimit = _caps2.capability_limit(_tier_for_platforms, "hot_platforms")
    except Exception:
        _plimit = -1
    _truncated = False
    if isinstance(_plimit, int) and _plimit > 0 and names and len(names) > _plimit:
        names = names[:_plimit]
        _truncated = True
    try:
        summary = await _collect(names)
    except ValueError as exc:
        return _err("INVALID_PLATFORM", str(exc),
                    "可用平台码见 GET /api/hot/platforms", 400)
    if summary.get("__timeout__"):
        return _err("COLLECT_TIMEOUT", "部分平台超时，详见明细",
                    f"采集超过 {int(COLLECT_TIMEOUT_SECONDS)} 秒，已终止等待；可缩小平台范围后重试")
    out = dict(summary)
    out["ok"] = True
    out["request_id"] = _request_id()
    if _truncated:
        out["platforms_truncated"] = True
        out["platforms_truncated_hint"] = (
            f"当前档位单次最多采集 {_plimit} 个平台，升级 V7 Pro 解锁 24 平台全开"
        )
    return JSONResponse(content=out)


@router.get("/admin/hot", response_class=HTMLResponse)
async def hot_page(request: Request):
    """「热榜采集」页面：平台复选框 + 开始采集 + 结果表格。"""
    _guard(request)
    catalog = _platform_catalog()
    boxes = "\n".join(
        f'      <label class="plat"><input type="checkbox" name="plat" value="{p["name"]}" checked>'
        f'<span>{p.get("display_name") or p["name"]}</span></label>'
        for p in catalog
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>热榜采集 · 一幕·YIMU V7</title>
<link rel="stylesheet" href="/static/css/modern_studio.css">
<style>
:root{{
  --bg:#07090e; --card:#121824; --border:#232d3d;
  --primary:#f0883e; --primary-hover:#ff9d55; --primary-subtle:rgba(240,136,62,.16);
  --text:#f0f6fc; --text-muted:#8b98a8;
  --success:#3fb950; --info:#58a6ff; --warn:#d29922; --danger:#f85149;
  --radius:14px; --radius-sm:8px;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
}}
body{{font-family:var(--font);background:var(--bg);color:var(--text);min-height:100vh;
  background-image:radial-gradient(circle at 50% 0%,rgba(240,136,62,.06) 0%,transparent 60%)}}
.page-wrap{{max-width:1100px;margin:0 auto;padding:28px 22px 64px}}
.page-top{{display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap}}
.page-top h1{{font-size:22px;margin:0}}
.page-back{{color:var(--primary);text-decoration:none;font-size:14px;white-space:nowrap}}
.page-back:hover{{color:var(--primary-hover)}}
.page-nav{{display:flex;gap:6px}}
.page-nav a{{color:var(--text-muted);text-decoration:none;font-size:13px;padding:6px 12px;border-radius:var(--radius-sm)}}
.page-nav a:hover{{color:var(--text);background:rgba(255,255,255,.04)}}
.page-nav a.on{{color:var(--primary);background:var(--primary-subtle);font-weight:600}}
.page-user{{margin-left:auto;font-size:13px;color:var(--text-muted)}}
.ver-badge{{font-size:11px;color:var(--text-muted);border:1px solid var(--border);border-radius:999px;padding:2px 10px;white-space:nowrap}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px 22px;margin-bottom:18px}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:8px 16px;border-radius:var(--radius-sm);font-size:13.5px;font-weight:600;cursor:pointer;border:1px solid transparent;transition:all .15s ease;background:var(--primary);color:#fff;font-family:inherit}}
.btn:hover{{background:var(--primary-hover)}}
.btn:active{{transform:scale(.98)}}
.btn[disabled]{{opacity:.5;cursor:not-allowed}}
.badge{{display:inline-flex;align-items:center;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:600;white-space:nowrap}}
.badge.green{{background:rgba(63,185,80,.18);color:#56d364;border:1px solid rgba(63,185,80,.3)}}
.badge.red{{background:rgba(248,81,73,.18);color:#ff7b72;border:1px solid rgba(248,81,73,.3)}}
.badge.gold{{background:rgba(227,179,65,.18);color:#f2cc60;border:1px solid rgba(227,179,65,.3)}}
.tbl{{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}}
.tbl th,.tbl td{{border-bottom:1px solid var(--border);padding:8px;text-align:left;vertical-align:top}}
.tbl th{{color:var(--text-muted);font-weight:600;font-size:12px}}
.plat-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin:12px 0}}
.plat{{display:flex;align-items:center;gap:6px;padding:8px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);cursor:pointer;font-size:13px;color:var(--text)}}
.plat:hover{{border-color:var(--primary)}}
.plat input{{accent-color:var(--primary)}}
#collect-btn.loading{{opacity:.6;pointer-events:none}}
.toolbar{{display:flex;gap:10px;align-items:center;margin:10px 0;flex-wrap:wrap}}
</style></head>
<body><div class="page-wrap">
<div class="page-top"><a class="page-back" href="/">← 返回工作台</a><h1>🔥 热榜采集</h1>
<span class="ver-badge">V7</span>
<nav class="page-nav"><a href="/admin/gateway">网关管理</a><a href="/admin/billing">会员与账本</a><a href="/admin/hot" class="on">热榜采集</a></nav></div>
<div class="card">
  <p style="color:var(--text-muted,#8b949e);font-size:13px;margin:0 0 8px">
    勾选平台后开始采集 · 单平台失败不影响其他平台 · 超过 {int(COLLECT_TIMEOUT_SECONDS)} 秒如实提示超时</p>
  <div class="plat-grid">{boxes}</div>
  <div class="toolbar">
    <button id="collect-btn" class="btn" onclick="doCollect()">开始采集</button>
    <span id="status" style="font-size:13px;color:var(--text-muted,#8b949e)"></span>
  </div>
  <div id="summary"></div>
  <table id="result-table" class="tbl" style="display:none">
    <thead><tr><th>平台</th><th>标题</th><th>热度</th><th>链接</th><th>状态</th></tr></thead>
    <tbody id="result-body"></tbody>
  </table>
</div>
</div>
<script>
function esc(s){{return String(s??"").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]))}}
async function doCollect(){{
  const btn=document.getElementById("collect-btn"),st=document.getElementById("status");
  const plats=[...document.querySelectorAll('input[name=plat]:checked')].map(i=>i.value);
  if(!plats.length){{st.textContent="请至少勾选一个平台";return}}
  btn.classList.add("loading");btn.textContent="采集中…";st.textContent="正在采集 "+plats.length+" 个平台…";
  document.getElementById("result-table").style.display="none";
  const ctrl=new AbortController();const timer=setTimeout(()=>ctrl.abort(), {int((COLLECT_TIMEOUT_SECONDS+5)*1000)});
  try{{
    const r=await fetch("/api/hot/collect",{{method:"POST",headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{platforms:plats}}),signal:ctrl.signal}});
    const d=await r.json();
    if(!r.ok||!d.ok){{st.textContent="⚠️ "+(d.message||("HTTP "+r.status));renderSummary(d);return}}
    st.textContent="✅ 完成："+d.ok_count+" 成功 / "+d.fail_count+" 失败 / "+d.skip_count+" 未配置，共 "+d.new_count+" 条";
    renderSummary(d);renderRows(d);
  }}catch(e){{
    st.textContent=e.name==="AbortError"?"⚠️ 部分平台超时，详见明细":"⚠️ 请求失败："+e.message;
  }}finally{{
    clearTimeout(timer);btn.classList.remove("loading");btn.textContent="开始采集";
  }}
}}
function renderSummary(d){{
  const el=document.getElementById("summary");if(!d||!d.detail){{el.innerHTML="";return}}
  el.innerHTML="<p style='font-size:12px;color:var(--text-muted,#8b949e)'>耗时 "+(d.duration_ms||0)+"ms · 明细："+
    Object.entries(d.detail).map(([k,v])=>
      "<span class='"+(v.error?"st-err":v.skipped?"st-skip":"st-ok")+"'>"+esc(k)+
      (v.error?" 失败":v.skipped?" 未配置("+esc(v.skipped)+")":" "+v.count+"条")+"</span>").join(" · ")+"</p>";
}}
function renderRows(d){{
  const tb=document.getElementById("result-body");
  const rows=(d.items||[]).map(it=>
    "<tr><td>"+esc(it.platform_name||it.platform)+"</td><td>"+esc(it.title)+"</td>"+
    "<td>"+esc(it.hot_score??it.hot_raw??"")+"</td>"+
    "<td>"+(it.url?'<a href="'+esc(it.url)+'" target="_blank" rel="noopener">🔗</a>':"—")+"</td>"+
    "<td class='st-ok'>成功</td></tr>").join("");
  tb.innerHTML=rows||"<tr><td colspan=5 style='text-align:center;color:var(--text-muted)'>暂无条目（各平台均未配置或采集失败，见上方明细）</td></tr>";
  document.getElementById("result-table").style.display="";
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)
