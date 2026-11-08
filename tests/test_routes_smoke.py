# SPDX-License-Identifier: BUSL-1.1
"""路由鉴权冒烟：未登录访问全站路由，除白名单外不得返回 200。

背景（V10.2.1 安全审查）：
    历史上有 14 个带 `{did}` 的 handler 体内**根本没有调用 guard()**，
    导致匿名用户可以 `GET /api/drafts/{did}/raw/wechat` 下载任意用户稿件、
    `GET /img/{did}/xxx.png` 下载任意配图。修复方式是鉴权收口到
    `DraftOwnerRoute`（见 web/admin.py），而不是靠每个 handler 记得写。

    这类缺陷极易在新增路由时复发，因此本测试用「反向白名单」把它锁死：
    遍历 `app.routes`，未登录发一次请求，**只有登记在 PUBLIC_ALLOWED
    里的端点**允许 200/204，其余一律不允许。

维护约定：
    真的需要公开的新端点（落地页、健康检查、价格页…），
    必须显式加进 PUBLIC_ALLOWED，并在此处注释说明为何可公开。
    如果一时加不进去——说明它本来就不该公开。
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from web.admin import app

#: 未登录合法可达的端点。每一条都必须是「给匿名用户看的」东西。
PUBLIC_ALLOWED = {
    ("GET", "/"),                      # 落地页
    ("GET", "/m"),                     # 移动端落地页
    ("GET", "/pricing"),               # 价格页
    ("GET", "/releases"),              # 更新日志页
    ("GET", "/admin/releases"),        # 同上（历史别名）
    ("GET", "/favicon.ico"),
    ("GET", "/health"),                # 存活探针（不含敏感信息）
    ("GET", "/api/health"),
    ("GET", "/api/v10/health"),
    ("GET", "/api/version"),
    ("GET", "/api/pricing"),           # 档位与价格，营销所需
    ("GET", "/api/releases"),
    ("GET", "/api/auth/status"),       # 前端首屏判断「我登录了吗」
    ("GET", "/api/system/check_update"),
    ("GET", "/docs"),                  # OpenAPI 交互文档
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
    ("GET", "/openapi.json"),
    ("POST", "/api/auth/logout"),      # 登出必须允许幂等（未登录也能调）
}

#: 静态资源挂载，路径不存在时返回 404，不属于「越权」范畴。
_SKIP_PREFIXES = ("/static", "/static-img")

#: 路径参数占位值：只用 [A-Za-z0-9_-]，避免被 id 白名单拦成 400 而测不到鉴权。
_PARAM_PLACEHOLDER = "smoke1"


def _iter_endpoints():
    """展开 app.routes 为 (method, url, route) 三元组。"""
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/") or path.startswith(_SKIP_PREFIXES):
            continue
        url = re.sub(r"\{[^}]+\}", _PARAM_PLACEHOLDER, path)
        for method in sorted(set(getattr(route, "methods", None) or [])):
            if method in ("HEAD", "OPTIONS"):
                continue
            yield method, url, route


@pytest.fixture(scope="module")
def anon_client() -> TestClient:
    """不带任何 Cookie / Header 的客户端 = 完全匿名。"""
    return TestClient(app)


def test_no_anonymous_200_outside_whitelist(anon_client: TestClient):
    """核心契约：白名单之外，匿名请求一律不给 200。"""
    offenders: list[str] = []
    for method, url, _route in _iter_endpoints():
        if (method, url) in PUBLIC_ALLOWED:
            continue
        try:
            resp = anon_client.request(method, url)
        except Exception as exc:  # 404/405 等由路由层抛出的异常不算越权
            print(f"[smoke] {method} {url} -> 抛出异常（跳过）: {exc}")
            continue
        if resp.status_code in (200, 204):
            offenders.append(f"{method} {url} -> {resp.status_code}")

    assert not offenders, (
        "以下端点未登录即可访问（返回 200），存在越权风险：\n  "
        + "\n  ".join(offenders)
        + "\n\n若确实需要公开，请把它加入 tests/test_routes_smoke.py 的 PUBLIC_ALLOWED 并写明理由；"
        "否则请在 handler 内补 guard()/guard_admin()。"
    )


def test_did_routes_require_login(anon_client: TestClient):
    """所有带 {did} 的路由，未登录必须是 401（不是 404/200）。

    用 401 而非 404 是有意的：401 明确告诉前端「该去登录了」，
    而 404 会让前端误判「稿件被删了」。
    """
    bad: list[str] = []
    checked = 0
    from tests.wsb_common import iter_effective_routes  # R11 拆分后路由经 include 惰性挂载
    for route in iter_effective_routes(app):
        path = getattr(route, "path", "")
        if "{did}" not in path or path.startswith("/s/"):
            continue
        url = re.sub(r"\{[^}]+\}", _PARAM_PLACEHOLDER, path)
        for method in sorted(set(getattr(route, "methods", None) or [])):
            if method in ("HEAD", "OPTIONS"):
                continue
            checked += 1
            resp = anon_client.request(method, url)
            if resp.status_code != 401:
                bad.append(f"{method} {url} -> {resp.status_code}")

    assert checked >= 60, f"带 {{did}} 的路由只测到 {checked} 条，路由表可能异常"
    assert not bad, "以下带 {did} 的路由未登录时不是 401：\n  " + "\n  ".join(bad)


def test_share_token_still_public(anon_client: TestClient):
    """分享链路不能被鉴权收口误伤。

    匿名访问 /s/{token}，合法令牌应拿到 200 页面、非法令牌应 404；
    两者都**不能**是 401 —— 401 意味着分享链接对未登录访客失效。
    """
    resp = anon_client.get("/s/definitely-not-a-real-token")
    assert resp.status_code == 404, f"/s/{{token}} 对未知令牌应 404，实际 {resp.status_code}"


def test_share_page_media_routes_are_token_scoped(anon_client: TestClient):
    """分享页内引用的媒体必须走 /s/{token}/img|card，而不是 /img/{did}。

    否则拿到分享链接的人虽然能看图，图片地址却暴露了内部 did。
    """
    for path in ("/s/tok1/img/a.png", "/s/tok1/card/a.png"):
        resp = anon_client.get(path)
        # 令牌不存在 → 404；关键是「不能因为没登录就 401」
        assert resp.status_code != 401, f"{path} 不应要求登录（分享页需匿名可读）"
