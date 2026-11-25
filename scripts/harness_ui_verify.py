#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
"""Harness 外壳重建 · 只读验收脚本（基线采集与后续复验复用）。

检查项（对应 design/harness-shell-contract.md）：
  1. 契约清单内静态资源 HTTP 200（css/js，含 core/rail/thread/stage/collect/settings）
  2. node --check 全部 harness JS 模块（契约 §6：纯 ES5 + IIFE，语法必须通过）
  3. 违规模式扫描：
       - harness 模块内写死 http:// 假数据/外链
       - 写死“已完成 n/n”演示进度（契约 §5：必须由真实任务状态推导）
       - 裸 <iframe> 且无“外部打开”降级（契约 §7.5）
       - eval / new Function / 字符串形式 setTimeout/setInterval（契约 §6：不得 eval 内联作用域变量）
  4. 隔离规则抽查（契约 §6）：CSS 选择器必须挂 body[data-shell="harness"]；JS 模块必须有外壳守卫早退
  5. 模板挂载引用：index.html 必须按序引用 6 个 JS + 5 个 CSS
  6. 相关 pytest 子集：先 --collect-only 按文件名筛选 shell/harness/workbench/rail/stage，不全量跑
  7. 真实接口探针：/api/status、/api/tasks 返回 200 且为真实 JSON

只读约束：不修改 web/static/**、web/templates/**，不重启服务，不提交 git。

用法：
  python3 scripts/harness_ui_verify.py [--base-url http://127.0.0.1:8790] [--json PATH]

退出码：硬检查失败（资源非 200 / node 语法错 / pytest 失败）返回 1；否则 0。
扫描类问题以 WARN/FAIL 分级记录在 JSON 与 stdout 报告中。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_STATIC = REPO_ROOT / "web" / "static"
TEMPLATE = REPO_ROOT / "web" / "templates" / "index.html"
DESIGN_DIR = REPO_ROOT / "design"

# 契约 §2 文件所有权表（互斥清单）
CONTRACT_CSS = [
    "harness-ui.css",
    "harness-thread.css",
    "harness-stage.css",
    "harness-collect.css",
    "harness-settings.css",
]
CONTRACT_JS = [
    "harness-core.js",
    "harness-rail.js",
    "harness-thread.js",
    "harness-stage.js",
    "harness-collect.js",
    "harness-settings.js",
]

# 违规模式：(id, 级别, 说明, 正则)
PATTERNS = [
    ("hardcoded_http", "FAIL", "模块内写死 http:// 外链/假数据（应走相对路径 /api）",
     re.compile(r'http://[^\s"\'<>)]+')),
    ("fake_progress", "FAIL", "写死“已完成 n/n”演示进度（必须由 /api/tasks 等真实状态推导）",
     re.compile(r'已完成\s*\d+\s*/\s*\d+')),
    ("bare_done_text", "WARN", "出现写死“已完成”文案，需人工确认是否真实状态推导",
     re.compile(r'已完成')),
    ("bare_iframe", "FAIL", "裸 <iframe>；契约要求浏览器页签先内嵌阅读，禁 iframe 时给“外部打开”降级",
     re.compile(r'<iframe\b', re.I)),
    ("eval_call", "FAIL", "eval( 调用（契约 §6 禁止 eval 模板内联作用域变量）",
     re.compile(r'\beval\s*\(')),
    ("new_function", "FAIL", "new Function( 动态构造（等价 eval 风险）",
     re.compile(r'new\s+Function\s*\(')),
    ("string_timer", "FAIL", "字符串形式 setTimeout/setInterval（会间接 eval）",
     re.compile(r'(?:setTimeout|setInterval)\s*\(\s*["\']')),
]

IFRAME_FALLBACK_KEYWORDS = ["外部打开", "external", "sandbox="]

PYTEST_FILE_RE = re.compile(r"shell|harness|workbench|rail|stage", re.I)
COLLECT_LINE_RE = re.compile(r"^(?P<file>tests/[^:]+\.py):\s*\d+\s*$")


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

def http_get(url: str, timeout: float = 10.0) -> dict:
    """只读 GET，返回状态/字节数/类型/错误，不抛异常。"""
    rec = {"url": url, "status": None, "bytes": None, "content_type": None, "error": None}
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            rec["status"] = resp.status
            rec["bytes"] = len(body)
            rec["content_type"] = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        rec["status"] = e.code
        rec["error"] = str(e)
    except Exception as e:  # noqa: BLE001 - 验收脚本需兜底记录一切异常
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"__READ_ERROR__: {e}"


# --------------------------------------------------------------------------- #
# 检查 1：静态资源 200
# --------------------------------------------------------------------------- #

def check_static(base_url: str) -> dict:
    cb = int(time.time())
    assets = [f"/static/css/{n}" for n in CONTRACT_CSS] + [f"/static/js/{n}" for n in CONTRACT_JS]
    records = []
    fails = 0
    for path in assets:
        rec = http_get(f"{base_url}{path}?cb={cb}")
        rec["path"] = path
        ok = rec["status"] == 200
        rec["ok"] = ok
        if not ok:
            fails += 1
        records.append(rec)
    return {"title": "静态资源 HTTP 200", "fails": fails, "records": records}


# --------------------------------------------------------------------------- #
# 检查 2：node --check
# --------------------------------------------------------------------------- #

def node_check() -> dict:
    node = shutil.which("node")
    records = []
    fails = 0
    if not node:
        return {"title": "node --check", "fails": len(CONTRACT_JS),
                "records": [{"file": n, "ok": False, "error": "未找到 node 可执行文件"} for n in CONTRACT_JS]}
    for name in CONTRACT_JS:
        f = WEB_STATIC / "js" / name
        rec = {"file": name, "exists": f.exists(), "ok": False, "rc": None, "detail": ""}
        if not f.exists():
            rec["detail"] = "文件不存在"
            fails += 1
            records.append(rec)
            continue
        proc = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        rec["rc"] = proc.returncode
        rec["ok"] = proc.returncode == 0
        rec["detail"] = (proc.stderr or proc.stdout).strip()
        if not rec["ok"]:
            fails += 1
        records.append(rec)
    return {"title": "node --check 语法检查", "fails": fails, "records": records}


# --------------------------------------------------------------------------- #
# 检查 3：违规模式扫描
# --------------------------------------------------------------------------- #

def scan_violations() -> dict:
    files = [WEB_STATIC / "css" / n for n in CONTRACT_CSS] + [WEB_STATIC / "js" / n for n in CONTRACT_JS]
    findings = []
    fail = warn = 0
    for f in files:
        if not f.exists():
            findings.append({"file": f.name, "level": "FAIL", "rule": "missing",
                              "line": 0, "detail": "文件不存在"})
            fail += 1
            continue
        text = read_text(f)
        for rule_id, level, label, rx in PATTERNS:
            for m in rx.finditer(text):
                line = text[: m.start()].count("\n") + 1
                snippet = m.group(0)[:80]
                # iframe 降级豁免：文件内存在外部打开/沙箱降级关键字
                if rule_id == "bare_iframe" and any(k in text for k in IFRAME_FALLBACK_KEYWORDS):
                    level = "WARN"
                    label += "（含降级关键字，需人工复核）"
                findings.append({"file": f.name, "level": level, "rule": rule_id,
                                 "line": line, "match": snippet, "label": label})
                if level == "FAIL":
                    fail += 1
                else:
                    warn += 1
    return {"title": "违规模式扫描", "fails": fail, "warns": warn, "findings": findings}


# --------------------------------------------------------------------------- #
# 检查 4：隔离规则抽查
# --------------------------------------------------------------------------- #

def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _iter_css_rules(css: str):
    """按花括号深度遍历 CSS 规则，跳过 @keyframes 整块；@media 内层递归。"""
    i, n = 0, len(css)
    while i < n:
        while i < n and css[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        start, depth = i, 0
        while i < n and (css[i] != "{" or depth > 0):
            if css[i] in "([":
                depth += 1
            elif css[i] in ")]":
                depth -= 1
            i += 1
        selector = css[start:i].strip()
        if i >= n:
            break
        depth, j = 1, i + 1
        while j < n and depth > 0:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[i + 1:j - 1]
        i = j
        if selector.startswith("@keyframes"):
            continue
        yield selector, body
        if selector.startswith("@media"):
            yield from _iter_css_rules(body)


def _split_selectors(sel: str) -> list[str]:
    """逗号切分选择器，尊重 [] () 与引号内的逗号。"""
    parts, buf, depth, quote = [], [], 0, None
    for ch in sel:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "[(":
            depth += 1
            buf.append(ch)
        elif ch in ")]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _looks_like_selector(sel: str) -> bool:
    if not sel or ";" in sel:
        return False
    # 声明泄漏：含冒号且冒号后是颜色/数字/长度值
    if re.search(r":\s*(#|rgba?\(|\d)", sel):
        return False
    return bool(re.match(r"^[a-zA-Z#.\[\*:]", sel.strip()))


def check_isolation() -> dict:
    findings = []
    fails = 0

    # CSS：每条规则选择器必须含 body[data-shell="harness"]（可叠加 html[data-ui-shell="harness"]）
    for name in CONTRACT_CSS:
        f = WEB_STATIC / "css" / name
        if not f.exists():
            findings.append({"file": name, "level": "FAIL", "detail": "文件不存在"})
            fails += 1
            continue
        css = _strip_css_comments(read_text(f))
        for selector, _body in _iter_css_rules(css):
            if not selector:
                continue
            for sel in _split_selectors(selector):
                if not _looks_like_selector(sel):
                    continue
                scoped = ('body[data-shell="harness"]' in sel
                          or "body[data-shell='harness']" in sel
                          or "html[data-ui-shell=\"harness\"]" in sel)
                if not scoped:
                    findings.append({"file": name, "level": "FAIL",
                                     "detail": f"选择器未收在 harness 作用域下: {sel[:90]}"})
                    fails += 1

    # JS：模块必须读取 data-shell 并在非 harness 下早退（允许内联判断或 helper 函数封装）
    guard_attr_re = re.compile(r"getAttribute\(\s*['\"]data-shell['\"]\)")
    for name in CONTRACT_JS:
        f = WEB_STATIC / "js" / name
        if not f.exists():
            findings.append({"file": name, "level": "FAIL", "detail": "文件不存在"})
            fails += 1
            continue
        text = read_text(f)
        has_attr = guard_attr_re.search(text) is not None
        # 守卫 helper 形式：isHarness()/shellOk()/harnessOn() 等，函数体内读 data-shell，顶部 if(!fn()) return
        has_early_return = re.search(r"if\s*\(\s*!\s*[A-Za-z_$][\w$]*\(\s*\)\s*\)\s*return", text) is not None
        if not (has_attr and has_early_return):
            findings.append({"file": name, "level": "WARN",
                             "detail": "未发现 data-shell 守卫早退（占位桩可忽略，落地后必须补齐）"})
    return {"title": "隔离规则抽查（契约 §6）", "fails": fails, "findings": findings}


# --------------------------------------------------------------------------- #
# 检查 5：模板挂载引用 + 孤儿文件
# --------------------------------------------------------------------------- #

def check_template_refs() -> dict:
    findings = []
    fails = 0
    html = read_text(TEMPLATE)
    for name in CONTRACT_JS:
        if f"/static/js/{name}" not in html:
            findings.append({"level": "FAIL", "detail": f"模板未引用 /static/js/{name}"})
            fails += 1
    for name in CONTRACT_CSS:
        if f"/static/css/{name}" not in html:
            findings.append({"level": "FAIL", "detail": f"模板未引用 /static/css/{name}"})
            fails += 1

    # 加载顺序：core → rail → thread → stage → collect → settings
    order = [html.find(f"/static/js/{n}") for n in CONTRACT_JS]
    if all(i >= 0 for i in order) and order != sorted(order):
        findings.append({"level": "FAIL", "detail": "JS 加载顺序不符合 core→rail→thread→stage→collect→settings"})
        fails += 1

    # 孤儿文件：harness-shell.js 在磁盘但模板未引用
    orphan = WEB_STATIC / "js" / "harness-shell.js"
    orphan_note = None
    if orphan.exists() and "/static/js/harness-shell.js" not in html:
        orphan_note = "harness-shell.js 存在于磁盘但模板未挂载（早期单体实现遗留，验收时不计入契约清单，仅提示）"
    return {"title": "模板挂载引用", "fails": fails, "findings": findings, "orphan": orphan_note}


# --------------------------------------------------------------------------- #
# 检查 6：相关 pytest 子集
# --------------------------------------------------------------------------- #

def _pytest_bin() -> str | None:
    venv = REPO_ROOT / ".venv" / "bin" / "pytest"
    if venv.exists():
        return str(venv)
    return shutil.which("pytest")


def check_pytest() -> dict:
    pytest_bin = _pytest_bin()
    if not pytest_bin:
        return {"title": "相关 pytest 子集", "fails": 1, "selected": [],
                "rc": None, "summary": "未找到 pytest"}

    # 第一步：collect-only，按文件名关键词筛选相关用例文件
    collect = subprocess.run([pytest_bin, "--collect-only", "-q"], cwd=REPO_ROOT,
                             capture_output=True, text=True)
    selected = []
    for line in collect.stdout.splitlines():
        m = COLLECT_LINE_RE.match(line.strip())
        if m and PYTEST_FILE_RE.search(m.group("file")):
            rel = m.group("file")
            if rel not in selected:
                selected.append(rel)

    if not selected:
        return {"title": "相关 pytest 子集", "fails": 1, "selected": [],
                "rc": None, "summary": "collect-only 未筛出任何外壳相关用例"}

    proc = subprocess.run([pytest_bin, "-q", *selected], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    tail = "\n".join(proc.stdout.strip().splitlines()[-15:])
    return {
        "title": "相关 pytest 子集（非全量）",
        "fails": 0 if proc.returncode == 0 else 1,
        "selected": selected,
        "rc": proc.returncode,
        "summary": tail,
    }


# --------------------------------------------------------------------------- #
# 检查 7：真实接口探针
# --------------------------------------------------------------------------- #

def probe_api(base_url: str) -> dict:
    out = {}
    for endpoint in ["/api/status", "/api/tasks"]:
        rec = http_get(f"{base_url}{endpoint}")
        info = {"status": rec["status"], "bytes": rec["bytes"], "error": rec["error"]}
        if rec["status"] == 200:
            try:
                data = json.loads(urllib.request.urlopen(
                    urllib.request.Request(f"{base_url}{endpoint}", headers={"Cache-Control": "no-cache"}),
                    timeout=10).read())
                if isinstance(data, dict):
                    info["keys"] = sorted(data.keys())
                    for k in ("topics", "drafts", "tasks", "assets"):
                        if k in data and isinstance(data[k], list):
                            info[f"{k}_count"] = len(data[k])
                    if "capabilities" in data:
                        info["capabilities"] = list(data["capabilities"].keys())
                elif isinstance(data, list):
                    info["list_count"] = len(data)
            except Exception as e:  # noqa: BLE001
                info["parse_error"] = f"{type(e).__name__}: {e}"
        out[endpoint] = info
    return {"title": "真实接口探针", "records": out}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# 检查 8：双主题 + 品牌 Logo（第二轮补充）
# --------------------------------------------------------------------------- #

LAYOUT_TOKENS = {"--hx-railw", "--hx-stagew", "--hx-bar", "--hx-radius", "--hx-font", "--hx-serif"}
LIGHT_SCOPE_RX = re.compile(r'body\[data-shell="harness"\]\s*\{(.*?)\}', re.S)
DARK_SCOPE_RX = re.compile(r'html\[data-theme="dark"\]\s*body\[data-shell="harness"\]\s*\{(.*?)\}', re.S)
TOKEN_RX = re.compile(r'(--hx-[a-z0-9-]+)\s*:\s*([^;]+);')
HEX_RX = re.compile(r'#[0-9a-fA-F]{3,8}\b')
TOKEN_DECL_RX = re.compile(r'^\s*--hx-[a-z0-9-]+\s*:')
LOGO_ASSET = "/static/img/logo-icon.png"


def _scope_tokens(css: str, rx: re.Pattern) -> dict[str, str]:
    m = rx.search(css)
    if not m:
        return {}
    return {k: v.strip() for k, v in TOKEN_RX.findall(m.group(1))}


def check_theme_logo() -> dict:
    checks: list[dict] = []
    fails = 0
    warns = 0

    def rec(name: str, ok: bool, detail: str, level: str = "FAIL") -> None:
        nonlocal fails, warns
        checks.append({"name": name, "level": "PASS" if ok else level, "detail": detail})
        if not ok:
            if level == "FAIL":
                fails += 1
            else:
                warns += 1

    tpl = read_text(TEMPLATE) if TEMPLATE.exists() else ""

    # 1) 模板不得再把 harness 主题锁成浅色
    forced = "setAttribute('data-theme', 'light')" in tpl
    rec("模板未强制 harness 浅色", not forced,
        "仍有 setAttribute('data-theme','light')，主题会被锁死" if forced else "未发现强制 light 调用")

    # 2) 品牌位使用用户真实 Logo
    core = read_text(WEB_STATIC / "js" / "harness-core.js") if (WEB_STATIC / "js" / "harness-core.js").exists() else ""
    rail = read_text(WEB_STATIC / "js" / "harness-rail.js") if (WEB_STATIC / "js" / "harness-rail.js").exists() else ""
    rec("顶栏使用真实 Logo", LOGO_ASSET in core,
        "harness-core.js 已引用 logo-icon.png" if LOGO_ASSET in core else "顶栏未引用用户 Logo")
    rec("左栏使用真实 Logo", LOGO_ASSET in rail,
        "harness-rail.js 已引用 logo-icon.png" if LOGO_ASSET in rail else "左栏未引用用户 Logo")
    placeholder_free = "hx-tb-mark" not in core and 'viewBox="0 0 32 32"' not in rail
    rec("原型光球占位已清除", placeholder_free,
        "未发现 hx-tb-mark / 32×32 原型 SVG 占位" if placeholder_free
        else "仍存在原型光球/字母占位，品牌 Logo 未恢复")
    rec("favicon/apple-touch 指向用户 Logo", 'rel="apple-touch-icon"' in tpl and LOGO_ASSET in tpl,
        "apple-touch-icon 已指向 logo-icon.png")

    # 3) 顶栏外观入口复用站点既有切换 API
    rec("外观入口复用既有主题 API", "cycleThemeMode" in core,
        "harness-core.js 已调用 cycleThemeMode()" if "cycleThemeMode" in core else "未找到既有主题 API 调用")

    # 4) 双主题 token：深色块必须覆盖浅色块的全部颜色 token
    ui_css = read_text(WEB_STATIC / "css" / "harness-ui.css") if (WEB_STATIC / "css" / "harness-ui.css").exists() else ""
    light = _scope_tokens(ui_css, LIGHT_SCOPE_RX)
    dark = _scope_tokens(ui_css, DARK_SCOPE_RX)
    required = {k for k in light if k not in LAYOUT_TOKENS}
    missing = sorted(required - set(dark))
    rec("深色 token 覆盖完整", bool(dark) and not missing,
        f"深色缺 {len(missing)} 个：{', '.join(missing[:8])}" if missing else f"深色覆盖 {len(dark)} 个 token")
    rec("浅色 token 数量达标", len(light) >= 34, f"浅色 token {len(light)} 个")

    # 5) 五个 CSS 模块的裸色值审计（token 声明行不计），残留多则告警
    raw_report = []
    for name in CONTRACT_CSS:
        f = WEB_STATIC / "css" / name
        if not f.exists():
            continue
        keep = [ln for ln in read_text(f).splitlines() if not TOKEN_DECL_RX.match(ln)]
        hexes = HEX_RX.findall("\n".join(keep))
        raw_report.append({"file": name, "raw_hex": len(hexes), "sample": hexes[:4]})
    worst = max((r["raw_hex"] for r in raw_report), default=0)
    rec("CSS 半语义化残留", worst <= 8,
        f"单文件最多 {worst} 处裸色值（>8 视为未走 token）", level="WARN")

    return {"title": "双主题与品牌 Logo", "fails": fails, "warns": warns,
            "checks": checks, "raw_hex": raw_report}


def main() -> int:
    ap = argparse.ArgumentParser(description="Harness 外壳只读验收脚本")
    ap.add_argument("--base-url", default="http://127.0.0.1:8790")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    result = {
        "started": started,
        "base_url": args.base_url,
        "viewport_note": "浏览器实测视口以复验阶段为准；契约基准 1440×900，当前本机视口约 1231×761（等效宽度按 CSS 像素折算）",
        "checks": {},
    }

    result["checks"]["static"] = check_static(args.base_url)
    result["checks"]["node"] = node_check()
    result["checks"]["scan"] = scan_violations()
    result["checks"]["isolation"] = check_isolation()
    result["checks"]["template"] = check_template_refs()
    result["checks"]["theme"] = check_theme_logo()
    result["checks"]["pytest"] = check_pytest()
    result["checks"]["api"] = probe_api(args.base_url)

    # 汇总
    hard_fail = (
        result["checks"]["static"]["fails"]
        + result["checks"]["node"]["fails"]
        + result["checks"]["scan"]["fails"]
        + result["checks"]["isolation"]["fails"]
        + result["checks"]["template"]["fails"]
        + result["checks"]["theme"]["fails"]
        + result["checks"]["pytest"]["fails"]
    )
    result["summary"] = {
        "hard_fail": hard_fail,
        "scan_warns": result["checks"]["scan"]["warns"],
        "pytest_selected": result["checks"]["pytest"].get("selected", []),
    }

    # stdout 可读报告
    print("=" * 72)
    print(f"Harness 外壳验收 · {started} · base={args.base_url}")
    print("=" * 72)

    def line(ok: bool, label: str, extra: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {extra}" if extra else ""))

    s = result["checks"]["static"]
    line(s["fails"] == 0, "静态资源 200", f"{len(s['records'])} 项，失败 {s['fails']}")
    for r in s["records"]:
        if not r["ok"]:
            print(f"        ✗ {r['path']} -> {r['status']} {r['error'] or ''}")

    n = result["checks"]["node"]
    line(n["fails"] == 0, "node --check", f"失败 {n['fails']}")
    for r in n["records"]:
        if not r["ok"]:
            print(f"        ✗ {r['file']}: {r['detail'][:120]}")

    sc = result["checks"]["scan"]
    line(sc["fails"] == 0, "违规模式扫描", f"FAIL {sc['fails']} / WARN {sc['warns']}")
    for f in sc["findings"]:
        detail = f.get("match") or f.get("detail") or f.get("label", "")
        print(f"        [{f.get('level')}] {f.get('file', '?')}:{f.get('line', '?')} "
              f"{f.get('rule', '?')} :: {detail}")

    iso = result["checks"]["isolation"]
    line(iso["fails"] == 0, "隔离规则抽查", f"失败 {iso['fails']}")
    for f in iso["findings"]:
        print(f"        [{f.get('level')}] {f.get('file', '-')}: {f.get('detail', '')}")

    tpl = result["checks"]["template"]
    line(tpl["fails"] == 0, "模板挂载引用", f"失败 {tpl['fails']}")
    for f in tpl["findings"]:
        print(f"        [{f['level']}] {f['detail']}")
    if tpl["orphan"]:
        print(f"        [INFO] {tpl['orphan']}")

    pt = result["checks"]["pytest"]
    line(pt["fails"] == 0, "pytest 子集", f"rc={pt['rc']} 用例文件 {len(pt['selected'])} 个")
    print("        选中文件: " + ", ".join(pt["selected"]))
    if pt["summary"]:
        print("        " + pt["summary"].replace("\n", "\n        "))

    th = result["checks"]["theme"]
    line(th["fails"] == 0, "双主题与品牌 Logo", f"FAIL {th['fails']} / WARN {th['warns']}")
    for c in th["checks"]:
        print(f"        [{c['level']}] {c['name']}: {c['detail']}")
    for r in th.get("raw_hex", []):
        if r["raw_hex"]:
            print(f"        [INFO] {r['file']} 裸色值 {r['raw_hex']} 处 例: {r['sample']}")

    api = result["checks"]["api"]
    for ep, rec in api["records"].items():
        line(rec["status"] == 200, f"API {ep}", json.dumps({k: v for k, v in rec.items() if k != "error"}, ensure_ascii=False)[:160])

    print("=" * 72)
    print(f"汇总：hard_fail={hard_fail} scan_warns={result['summary']['scan_warns']}")

    # JSON 落盘
    json_path = args.json
    if not json_path:
        DESIGN_DIR.mkdir(parents=True, exist_ok=True)
        out_dir = DESIGN_DIR / "harness-verify-results"
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"verify-{time.strftime('%Y%m%d-%H%M%S')}.json"
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(json_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON 结果：{Path(json_path).resolve()}")

    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
