# SPDX-License-Identifier: BUSL-1.1
"""图片质量专项（WS-C）路由适配层：注册表 + 纯函数 handler。

⭐ 硬规则：
- 模块顶层绝不 import fastapi；build_router() 在函数内懒加载 fastapi，
  fastapi 缺失时抛 ImportError("fastapi 未安装，WS-D 集成时安装")。
- 业务模块（studio.promptforge / studio.image_forge.*）在 handler 函数内
  懒加载：接口签名以锁定的版本为准，并行开发骨架期不互相阻塞。
- handler 均为纯函数 ``(body: dict, ctx: dict) -> dict``，只返回统一响应体
  （studio.errors.ok / err），不依赖任何 Web 框架，便于单测与 WS-D 挂载。
- ⭐ generate / judge / forge 三个 handler 开头必须做租户校验：
  ctx 缺 tenant_id → 抛 BadRequest("缺少租户信息")。
- ⭐ handle_generate 不捕获 UpstreamNotReady：上游图片服务未就绪必须冒泡，
  由 handle_request 统一转错误体，禁止静默返回假成功。

ctx 约定（dict）：
    tenant_id: str        租户 id（generate/judge/forge 必填）
    request_id: str|None  链路 id（透传；缺失时自动生成）
    db_url: str|None      数据库 URL（generate 落账本用）
    image_client: object|None  图片客户端：测试注入桩；生产由 WS-D 传入网关客户端；
                               缺失时 generate 内部抛 UpstreamNotReady
"""

from __future__ import annotations

from studio.errors import BadRequest, Code, err, ok

# ⭐ 路由注册表：与 docs/CONTRACT.md §6 逐字对齐，供 WS-D 挂载 FastAPI 用。
# 格式：(HTTP 方法, 路径, handler 名)
ROUTES: list[tuple[str, str, str]] = [
    ("POST", "/api/image/forge", "forge"),
    ("GET", "/api/image/styles", "styles"),
    ("POST", "/api/image/generate", "generate"),
    ("POST", "/api/image/judge", "judge"),
    ("GET", "/api/image/benchmark", "benchmark"),
]


def _require_tenant(ctx: dict) -> str:
    """⭐ 租户校验：ctx 缺 tenant_id → 抛 BadRequest("缺少租户信息")。"""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else None
    if not tenant_id:
        raise BadRequest("缺少租户信息", hint="请先登录后再试")
    return tenant_id


def _request_id(ctx: dict) -> str | None:
    """从 ctx 透传 request_id（缺失时由 ok/err 自动生成）。"""
    return ctx.get("request_id") if isinstance(ctx, dict) else None


def handle_forge(body: dict, ctx: dict) -> dict:
    """POST /api/image/forge：贫瘠输入 → 结构化提示词（四维 + 否定词）。"""
    # ⭐ 租户校验：ctx 缺 tenant_id → BadRequest("缺少租户信息")
    _require_tenant(ctx)
    from studio.promptforge import forge_prompt

    data = body if isinstance(body, dict) else {}
    thin_input = data.get("thin_input") or ""
    style = data.get("style") or "cinematic"
    return ok(
        {"forge": forge_prompt(thin_input, style)},
        request_id=_request_id(ctx),
    )


def handle_styles(body: dict, ctx: dict) -> dict:
    """GET /api/image/styles：12 风格库列表（含示例图 URL、适用场景）。"""
    # ⭐ 租户校验：本接口可匿名访问，仍建议透传 tenant_id 便于统计。
    from studio.image_forge.styles import list_styles

    styles = list_styles()
    return ok(
        {"styles": styles, "count": len(styles)},
        request_id=_request_id(ctx),
    )


def handle_generate(body: dict, ctx: dict) -> dict:
    """POST /api/image/generate：走网关 n=3 赛马 → 优选图 + 候选列表。

    ⭐ 本 handler 不捕获 UpstreamNotReady：ctx 缺 image_client 时由
    generate 内部抛出，冒泡到 handle_request 统一转错误体。
    """
    # ⭐ 租户校验：ctx 缺 tenant_id → BadRequest("缺少租户信息")
    _require_tenant(ctx)

    data = body if isinstance(body, dict) else {}
    prompt = data.get("prompt")
    if not prompt or not str(prompt).strip():
        raise BadRequest("请提供生图提示词", hint="prompt 不能为空")
    try:
        n = int(data.get("n", 3))
    except (TypeError, ValueError):
        raise BadRequest("n 必须为整数", hint="n 取值范围 1～4") from None
    n = max(1, min(4, n))  # 契约 §3.2：网关 n ≤ 4

    from studio.image_forge.generate import generate

    result = generate(
        prompt=prompt,
        style_id=data.get("style_id") or "cinematic",
        n=n,
        tenant_id=ctx["tenant_id"],
        db_url=ctx.get("db_url"),
        client=ctx.get("image_client"),
        size="1024x1024",
    )
    return ok(result, request_id=_request_id(ctx))


def handle_judge(body: dict, ctx: dict) -> dict:
    """POST /api/image/judge：对已有图打分（质量分 + 保真分 0–10）+ 缺陷描述。"""
    # ⭐ 租户校验：ctx 缺 tenant_id → BadRequest("缺少租户信息")
    _require_tenant(ctx)

    data = body if isinstance(body, dict) else {}
    url = data.get("url")
    if not url or not str(url).strip():
        raise BadRequest("请提供图片地址")

    from studio.image_forge.judge import judge_image

    image = {
        "url": url,
        "prompt": data.get("prompt"),
        "width": data.get("width"),
        "height": data.get("height"),
    }
    return ok(
        {"judge": judge_image(image)},
        request_id=_request_id(ctx),
    )


def handle_benchmark(body: dict, ctx: dict) -> dict:
    """GET /api/image/benchmark：审美基准集回归结果（CI 读取）。"""
    # ⭐ 租户校验：本接口可匿名访问（CI 读取），仍建议透传 tenant_id。
    from studio.image_forge.benchmark import get_benchmark_report

    return ok(get_benchmark_report(), request_id=_request_id(ctx))


_HANDLERS = {
    "forge": handle_forge,
    "styles": handle_styles,
    "generate": handle_generate,
    "judge": handle_judge,
    "benchmark": handle_benchmark,
}


def handle_request(method: str, path: str, body: dict, ctx: dict) -> dict:
    """按 ROUTES 分发请求，统一收口错误体。

    - 未知路由 → err(Code.NOT_FOUND, ...)。
    - YimuError（含 BadRequest / UpstreamNotReady）→ 其 .body()。
    - 其它未预期异常 → err(Code.INTERNAL, "系统开小差了，请稍后再试")。
    """
    from studio.errors import YimuError

    ctx = ctx if isinstance(ctx, dict) else {}
    request_id = _request_id(ctx)
    target = None
    for route_method, route_path, name in ROUTES:
        if route_method == (method or "").upper() and route_path == path:
            target = name
            break
    if target is None:
        return err(
            Code.NOT_FOUND,
            "接口不存在",
            hint="请检查请求路径与方法是否正确",
            request_id=request_id,
        )
    try:
        return _HANDLERS[target](body if isinstance(body, dict) else {}, ctx)
    except YimuError as exc:
        return exc.body(request_id)
    except Exception:
        return err(Code.INTERNAL, "系统开小差了，请稍后再试", request_id=request_id)


def build_router():
    """把 ROUTES 挂成 FastAPI APIRouter 并返回（供 WS-D 集成）。

    ⭐ fastapi 只在函数内懒加载；模块顶层绝不 import fastapi。
    fastapi 未安装时抛 ImportError("fastapi 未安装，WS-D 集成时安装")。

    说明：端点把请求体与请求头译为 (body, ctx) 后复用 handle_request；
    错误体统一为 {"ok","code","message","hint","request_id"}，
    HTTP 状态码映射由 WS-D 在挂载时按 Code 处理。
    """
    try:
        from fastapi import APIRouter
    except ImportError as exc:
        raise ImportError("fastapi 未安装，WS-D 集成时安装") from exc

    router = APIRouter()

    def _adapt(name: str):
        async def endpoint(request):  # request: fastapi.Request（运行时注入）
            try:
                raw = await request.json()
                req_body = raw if isinstance(raw, dict) else {}
            except Exception:
                req_body = {}
            req_ctx = {
                "tenant_id": request.headers.get("x-tenant-id"),
                "request_id": request.headers.get("x-request-id"),
            }
            return handle_request(request.method, request.url.path, req_body, req_ctx)

        endpoint.__name__ = f"image_{name}"
        return endpoint

    for route_method, route_path, name in ROUTES:
        register = router.get if route_method == "GET" else router.post
        register(route_path, name=f"image_{name}")(_adapt(name))
    return router
