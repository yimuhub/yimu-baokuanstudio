#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web/admin.py 巨石拆分执行器(R11)。

把 271 条路由按「路径前缀族」整体迁移到 web/routers/<family>.py,
- 保持族内注册顺序(避免参数路由吞并字面路由);
- 自由变量自动改写:admin 模块级 def/assign → `_a.NAME`(晚绑定,测试 monkeypatch 安全);
  admin 顶部的 import → 原样复制到 router;
- 带 `global` 语句或非路由装饰器的函数留在 admin.py 并报告;
- admin.py 底部追加 include_router(此时 admin 已完整定义,循环导入安全);
- 幂等保护:web/routers 已存在 admin.py 来的迁移标记时拒绝重跑。

用法:  .venv/bin/python scripts/split_admin.py --apply
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ROOT / "web" / "admin.py"
ROUTER_DIR = ROOT / "web" / "routers"

DRY = "--apply" not in sys.argv

# ---------------------------------------------------------------------------
# 族划分:返回 (router 模块名, 说明)。键为路由 path 字面量的前缀匹配规则。
# ---------------------------------------------------------------------------

def family_of(path: str) -> str:
    if not path.startswith("/api"):
        if path.startswith(("/s/", "/s", "/card/", "/img/", "/audio/", "/video/", "/preview/")):
            return "files"          # 静态/文件/分享展示类
        return "pages"              # /, /m, /pricing, /admin/* 页面, /favicon.ico
    rest = path[len("/api/"):].split("/")
    head = rest[0] if rest and rest[0] else ""
    if head in ("auth", "user", "onboarding"):
        return "auth"               # /login 非 api 已归 pages;/api/onboarding 归 auth
    if head in ("health", "version", "system", "status", "compliance"):
        return "system"
    if head == "topics":
        return "topics"
    if head in ("search", "rewrite", "extract", "render"):
        return "tools"              # /api/render 与 /api/rewrite/job 有归属冲突,见下
    if head == "drafts":
        return "drafts"
    if head == "assets":
        return "assets"
    if head in ("audio", "video", "advideo", "aivideo"):
        return "media"
    if head in ("skills", "agents", "habit", "voices", "ip_characters", "workspaces"):
        return "skills"
    if head in ("ticket",):
        return "ops"
    if head == "billing" or (head == "admin" and any(
            k in path for k in ("orders", "pricing", "grant_credits"))):
        return "billing"
    if head == "llm":
        return "billing"            # /api/llm/usage 计量,归计费域
    if head == "admin" and any(k in path for k in ("users", "audit")):
        return "admin_users"
    if head == "admin" and "metrics" in path:
        return "ops"
    if head == "models":
        return "models"
    if head in ("tasks", "jobs", "batch", "copilot", "stream"):
        return "tasks"
    if head in ("schedule", "watermark", "settings", "content", "editor", "share", "platforms",
                "workspace", "short_drama"):
        return "workspace"
    if head == "admin" and "renewal" in path:
        return "ops"
    if head == "pricing":
        return "billing"
    if head == "releases":
        return "pages"
    if head == "xhspub":
        return "media"              # 小红书发布与发布域同置
    return "misc"

FAMILY_DESC = {
    "auth": "认证 / 账号 / Key 保险箱 / 引导",
    "system": "系统健康 / 版本 / 更新 / 合规闸",
    "pages": "页面路由(/ /m /pricing /admin 页 /releases /favicon)",
    "topics": "热点选题",
    "tools": "搜索 / 仿写 / 提取 / 渲染",
    "drafts": "草稿工作台(含配图/排版/发布/短剧分镜)",
    "assets": "视觉资产库",
    "media": "音视频 / 广告片 / AI 视频 / 数字人 / 小红书发布",
    "skills": "技能库 / Agent / 习惯进化 / 名家音色 / IP 角色 / 工作区",
    "ops": "每日工单 / 运营看板 / 续费提醒",
    "billing": "计费 / 支付 / 订单 / 定价 / 计量",
    "admin_users": "后台用户与审计",
    "models": "模型服务配置",
    "tasks": "异步任务 / Copilot / 流式 / 批量",
    "workspace": "排期 / 水印 / 设置 / 编辑器 / 分享 / 自定义平台 / 内容复盘",
    "files": "文件与分享展示(/s /card /img /audio /video /preview)",
    "misc": "未归类",
}

ROUTE_DECOS = {"get", "post", "put", "delete", "patch", "api_route"}


def main() -> None:
    src = ADMIN.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)

    # -- 模块级名字登记 -----------------------------------------------------
    mod_names: dict[str, str] = {}   # name -> 'import' | 'def' | 'assign'
    mod_imports: dict[str, str] = {} # name -> import 语句源码
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mod_names[node.name] = "def"
        elif isinstance(node, ast.Import):
            for a in node.names:
                nm = a.asname or a.name.split(".")[0]
                mod_names[nm] = "import"
                mod_imports[nm] = ast.unparse(node)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                nm = a.asname or a.name
                mod_names[nm] = "import"
                mod_imports[nm] = ast.unparse(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    mod_names[t.id] = "assign"

    # -- 收集路由函数 -------------------------------------------------------
    routes = []  # (path, node)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id == "app" and dec.func.attr in ROUTE_DECOS):
                path = ast.literal_eval(dec.args[0]) if dec.args else ""
                routes.append((path, node))
                break

    # -- 分族(保持原顺序) ---------------------------------------------------
    fam_routes: dict[str, list] = {}
    stay: list[str] = []
    for path, node in routes:
        if any(isinstance(n, ast.Global) for n in ast.walk(node)):
            stay.append(f"global-stmt {path}")
            continue
        fam_routes.setdefault(family_of(path), []).append((path, node))

    if DRY:
        total = sum(len(v) for v in fam_routes.values())
        print(f"[dry] 路由总数 {len(routes)};可迁移 {total};留守 {len(stay)}")
        for fam in sorted(fam_routes):
            print(f"  {fam:12s} {len(fam_routes[fam]):3d} 条  — {FAMILY_DESC.get(fam, '')}")
        for s in stay:
            print("  [stay]", s)
        return

    if ROUTER_DIR.exists() and any(ROUTER_DIR.glob("*.py")):
        sys.exit("拒绝执行:web/routers 已有内容,拆分器不是幂等的。请先还原。")

    # -- 自由变量分析(symtable) --------------------------------------------
    import symtable
    table = symtable.symtable(src, "admin.py", "exec")
    bltn = set(dir(builtins))
    tables: dict[tuple[str, int], object] = {}
    def walk(t):
        tables[(t.get_name(), t.get_lineno())] = t
        for c in t.get_children():
            walk(c)
    walk(table)

    def free_names(fn_node) -> set[str]:
        """函数体引用的、解析到 admin 模块作用域的名字。"""
        t = tables.get((fn_node.name, fn_node.lineno))
        if t is None:
            return set()
        out = set()
        for s in t.get_symbols():
            if s.is_global() and s.get_name() in mod_names and s.get_name() not in bltn:
                out.add(s.get_name())
        return out

    # -- 生成 router 文件 ---------------------------------------------------
    moved_paths: list[str] = []
    spans_to_delete: list[tuple[int, int]] = []  # (lineno0, end_lineno)
    imports_needed_all: dict[str, set[str]] = {}
    rewrite_counts: dict[str, int] = {}

    ROUTER_DIR.mkdir(parents=True, exist_ok=True)
    (ROUTER_DIR / "__init__.py").write_text(
        '# SPDX-License-Identifier: BUSL-1.1\n'
        '"""web 路由域包(R11 巨石拆分)。由 scripts/split_admin.py 生成,改动请同步脚本。"""\n',
        encoding="utf-8")

    for fam, items in fam_routes.items():
        buf: list[str] = []
        buf.append(f'# SPDX-License-Identifier: BUSL-1.1\n')
        buf.append(f'"""{FAMILY_DESC.get(fam, fam)}路由(R11 巨石拆分,自 web/admin.py 整体迁出)。\n\n'
                   f'⭐ 拆分约定:\n'
                   f'- `_a` 指向 web.admin 模块对象,凡引用 admin 模块级 helper/常量一律走 `_a.X`\n'
                   f'  (晚绑定:测试对 web_admin.* 的 monkeypatch 继续生效);\n'
                   f'- 族内路由保持与拆分前完全一致的注册顺序;\n'
                   f'- admin.py 底部统一 include 本 router。"""\n')
        buf.append("from __future__ import annotations\n\n")
        # 标准导入块:覆盖路由处理函数常用的 fastapi/stdlib 名(注解名 symtable 不上报,统一预置)
        buf.append("import asyncio  # noqa: F401\n")
        buf.append("import base64  # noqa: F401\n")
        buf.append("import hashlib  # noqa: F401\n")
        buf.append("import json  # noqa: F401\n")
        buf.append("import re  # noqa: F401\n")
        buf.append("import time  # noqa: F401\n")
        buf.append("import uuid  # noqa: F401\n")
        buf.append("from pathlib import Path  # noqa: F401\n")
        buf.append("from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form  # noqa: E402\n")
        buf.append("from fastapi.responses import (FileResponse, HTMLResponse,  # noqa: E402,F401\n")
        buf.append("                               JSONResponse, Response, StreamingResponse)\n\n")
        buf.append("from web import admin as _a  # noqa: E402  (循环安全:admin 底部才 include 本模块)\n\n")
        buf.append("from web.draft_guard import DraftOwnerRoute  # noqa: E402  稳定类身份\n")
    buf.append("router = APIRouter(route_class=DraftOwnerRoute)  # {did} 归属校验路由类\n\n")

        fam_imports: set[str] = set()
        fam_rewrite: set[str] = set()
        for _path, node in items:
            free = free_names(node)
            for nm in free:
                if mod_names[nm] == "import":
                    fam_imports.add(mod_imports[nm])
                else:
                    fam_rewrite.add(nm)
        fam_rewrite.discard("app")
        # import 排序输出
        for imp in sorted(fam_imports):
            buf.append(imp + "  # noqa: E402,F811\n")
        if fam_imports:
            buf.append("\n")

        for path, node in items:
            seg = ast.parse(ast.unparse(node))  # 用 unparse 归一化行号
            fn = seg.body[0]
            # 装饰器 app.→router.
            for dec in fn.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) \
                        and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app":
                    dec.func.value.id = "router"
            # 自由变量 Name → Attribute(_a, NAME)(真正的模块对象晚绑定)
            class _Rw(ast.NodeTransformer):
                def visit_Name(self, n: ast.Name):
                    if n.id in fam_rewrite and isinstance(n.ctx, ast.Load):
                        return ast.copy_location(
                            ast.Attribute(value=ast.Name(id="_a", ctx=ast.Load()),
                                          attr=n.id, ctx=n.ctx), n)
                    return n
            fn = _Rw().visit(fn)
            ast.fix_missing_locations(fn)
            buf.append(ast.unparse(fn))
            buf.append("\n\n")
            moved_paths.append(path)
            spans_to_delete.append((node.decorator_list[0].lineno - 1
                                    if node.decorator_list else node.lineno - 1,
                                    node.end_lineno))
            rewrite_counts[path] = len(fam_rewrite)
        (ROUTER_DIR / f"{fam}.py").write_text("".join(buf), encoding="utf-8")
        print(f"[gen] web/routers/{fam}.py  {len(items)} 路由  rewrite={sorted(fam_rewrite)}")

    print(f"[done] 迁移 {len(moved_paths)} 条;待删除块 {len(spans_to_delete)} 个")
    if not DRY:
        # 删除被迁移块(从后往前)
        spans = sorted(set(spans_to_delete), reverse=True)
        for a, b in spans:
            del lines[a:b]
        ADMIN.write_text("".join(lines), encoding="utf-8")
        # 追加 include
        inc = ["\n\n# =========================================================================\n"
               "# R11 巨石拆分:路由域已整体迁出至 web/routers/,此处统一挂载。\n"
               "# ⭐ 必须放在模块最底部:router 模块 import web.admin 时本模块已完整定义。\n"
               "# =========================================================================\n"]
        for fam in sorted(fam_routes):
            inc.append(f"from web.routers import {fam} as _r_{fam}  # noqa: E402\n")
        for fam in sorted(fam_routes):
            inc.append(f"app.include_router(_r_{fam}.router)\n")
        with ADMIN.open("a", encoding="utf-8") as f:
            f.write("".join(inc))
        print("[done] admin.py 已裁剪并挂载 routers")


if __name__ == "__main__":
    main()
