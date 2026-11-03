# SPDX-License-Identifier: BUSL-1.1
"""系统诊断日志：把"用户看不见的失败"固化成可复制的文本。

背景
----
终端用户在 Windows 上遇到「改写失败」时，前端只弹一句
「重写失败: xxx」，真正的 traceback 打在服务端控制台里 —— 用户拿不到，
开发者也只能靠猜。本模块把失败现场留在进程内（环形缓冲）和磁盘上
（``data/logs/diagnostics.log``），用户点「设置 → 系统诊断日志 → 复制」
就能把完整现场发出来。

记录四类信息
------------
1. 环境快照：OS / Python / 默认编码 / 路径 / 目录可写性 —— Windows 上的
   绝大多数"玄学失败"（GBK 编码、路径权限、只读目录）一眼可见；
2. 步骤轨迹：业务链路（改写、生成、发布）走到哪一步断的；
3. 异常现场：异常类型 + 完整 traceback（含文件与行号）；
4. HTTP 失败：4xx/5xx 的路径、状态码、耗时 —— 前端报错与后端日志对得上。

设计约束
--------
- **绝不影响主流程**：所有写入都 try/except 吞掉，日志系统本身不能成为故障源；
- **脱敏**：字段名含 key/token/password/secret/cookie/auth 的值一律打码；
- **有界**：内存环形缓冲 2000 条，磁盘文件超 2MB 自动轮转。
"""
from __future__ import annotations

import datetime as _dt
import json
import locale
import logging
import os
import platform
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
# 测试用 YIMU_LOG_DIR 指向临时目录，避免把测试噪音写进用户真实的日志文件
LOG_DIR = Path(os.environ.get("YIMU_LOG_DIR") or (BASE / "data" / "logs"))
LOG_FILE = LOG_DIR / "diagnostics.log"
LOG_MAX_BYTES = 2 * 1024 * 1024
RING_SIZE = 2000

_LOCK = threading.RLock()
_EVENTS: deque = deque(maxlen=RING_SIZE)
_START_TS = time.time()
_INSTALLED = False

# 字段名里出现这些词的值一律打码，避免用户把 API Key 一起发出来
_SECRET_HINTS = ("key", "token", "password", "passwd", "secret", "cookie", "auth", "credential")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _mask(value: Any) -> Any:
    s = str(value)
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}***{s[-2:]}"


def _scrub(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (fields or {}).items():
        try:
            if any(h in str(k).lower() for h in _SECRET_HINTS) and v not in (None, "", 0):
                out[k] = _mask(v)
            else:
                out[k] = v
        except Exception:
            out[k] = "<unserializable>"
    return out


def _now() -> float:
    return time.time()


def _clock(ts: float) -> str:
    d = _dt.datetime.fromtimestamp(ts)
    return d.strftime("%m-%d %H:%M:%S") + f".{int((ts % 1) * 1000):03d}"


def _write_file(payload: dict) -> None:
    """追加一行 JSON 到磁盘；失败静默（磁盘满/只读不能拖垮业务）。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
                backup = LOG_FILE.with_suffix(".log.1")
                try:
                    if backup.exists():
                        backup.unlink()
                    LOG_FILE.rename(backup)
                except Exception:
                    pass
        except Exception:
            pass
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _push(payload: dict) -> None:
    with _LOCK:
        _EVENTS.append(payload)
    _write_file(payload)


def _event(level: str, scope: str, action: str, status: str,
           detail: str = "", elapsed: float | None = None,
           fields: dict[str, Any] | None = None) -> dict:
    payload = {
        "ts": _now(),
        "level": level,
        "scope": scope,
        "action": action,
        "status": status,
        "elapsed": round(elapsed, 3) if isinstance(elapsed, (int, float)) else None,
        "detail": (detail or "").strip()[:8000],
        "fields": _scrub(fields or {}),
        "thread": threading.current_thread().name,
    }
    _push(payload)
    return payload


# ---------------------------------------------------------------------------
# 写入接口
# ---------------------------------------------------------------------------

def record(scope: str, action: str, status: str = "ok",
           detail: str = "", level: str = "info",
           elapsed: float | None = None, **fields: Any) -> None:
    """记录一条业务事件（正常路径也用，便于对比"成功"和"失败"的差异）。"""
    try:
        _event(level, scope, action, status, detail, elapsed, fields)
    except Exception:
        pass


def step(scope: str, action: str, name: str, **fields: Any) -> None:
    """记录链路推进到的步骤。失败时能看出最后完成到哪一步。"""
    record(scope, action, status="step", detail=name, level="debug", **fields)


def capture_exc(scope: str, action: str, exc: BaseException | None = None,
                detail: str = "", elapsed: float | None = None,
                **fields: Any) -> str:
    """捕获异常现场（含完整 traceback），返回可直接展示的一句摘要。"""
    if exc is None:
        exc = sys.exc_info()[1]
    tb = traceback.format_exc()
    if not tb or tb.strip() == "NoneType: None":
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else ""
    text = f"{type(exc).__name__}: {exc}" if exc else "unknown error"
    try:
        _event("error", scope, action, "failed",
               detail=(detail + "\n" + tb).strip(), elapsed=elapsed, fields=fields)
    except Exception:
        pass
    return text


def http_event(method: str, path: str, status: int, elapsed: float,
               detail: str = "", **fields: Any) -> None:
    level = "error" if status >= 500 else "warning"
    _event(level, "http", f"{method} {path}", f"status={status}", detail, elapsed, fields)


# ---------------------------------------------------------------------------
# 环境快照
# ---------------------------------------------------------------------------

def _writable(path: Path) -> str:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".diag_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return "可写"
    except Exception as e:
        return f"不可写({type(e).__name__}: {e})"


def _file_state(path: Path) -> str:
    try:
        if not path.exists():
            return "不存在"
        return f"存在({path.stat().st_size / 1024 / 1024:.1f}MB, {_writable(path.parent)})"
    except Exception as e:
        return f"探测失败({e})"


def env_report() -> str:
    lines: list[str] = []
    add = lines.append
    add(f"操作系统 : {platform.system()} {platform.release()} (build {platform.version()})")
    add(f"机器架构 : {platform.machine()}")
    add(f"Python   : {sys.version.split()[0]} ({platform.python_implementation()})")
    add(f"解释器   : {sys.executable}")
    try:
        add(f"默认编码 : {locale.getpreferredencoding(False)} | "
            f"文件系统编码: {sys.getfilesystemencoding()} | "
            f"stdout: {getattr(sys.stdout, 'encoding', '?')}")
    except Exception:
        pass
    try:
        add(f"时区     : {time.strftime('%Z %z')}")
    except Exception:
        pass
    add(f"工作目录 : {os.getcwd()}")
    add(f"程序目录 : {BASE}")
    add(f"数据目录 : {BASE / 'data'} -> {_writable(BASE / 'data')}")
    add(f"草稿目录 : {BASE / 'data' / 'drafts'} -> {_writable(BASE / 'data' / 'drafts')}")
    try:
        from core.db import DB_PATH  # 延迟导入，避免循环依赖

        add(f"数据库   : {DB_PATH} -> {_file_state(Path(DB_PATH))}")
    except Exception as e:
        add(f"数据库   : 探测失败({type(e).__name__}: {e})")
    try:
        import version  # type: ignore

        add(f"应用版本 : {getattr(version, '__version__', '?')} "
            f"({getattr(version, '__codename__', '')})")
    except Exception:
        pass
    try:
        from core import llm

        cfg = llm.load_config() or {}
        provider = cfg.get("provider") or cfg.get("model") or "未配置"
        add(f"模型配置 : provider={provider} | 可用={llm.available()}")
    except Exception as e:
        add(f"模型配置 : 探测失败({type(e).__name__}: {e})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 快照输出
# ---------------------------------------------------------------------------

def _render(payload: dict) -> str:
    ts = payload.get("ts") or 0
    level = str(payload.get("level", "info")).upper().ljust(5)
    scope = payload.get("scope", "-")
    action = payload.get("action", "-")
    status = payload.get("status", "")
    elapsed = payload.get("elapsed")
    head = f"[{_clock(ts)}] {level} {scope}/{action} {status}"
    if elapsed is not None:
        head += f" ({elapsed}s)"
    fields = payload.get("fields") or {}
    if fields:
        kv = " ".join(f"{k}={v}" for k, v in fields.items())
        head += f"\n    {kv[:600]}"
    detail = payload.get("detail") or ""
    if detail:
        body = "\n".join("    " + ln for ln in detail.splitlines()[:60])
        head += "\n" + body
    return head


def snapshot(limit: int = 300, only_problems: bool = False) -> str:
    """导出成一段人可读、机器可解析的文本。"""
    with _LOCK:
        events = list(_EVENTS)

    if only_problems:
        events = [e for e in events
                  if e.get("level") in ("error", "warning") or e.get("status") == "failed"]
    events = events[-max(1, limit):]

    head = [
        "=" * 68,
        "一幕·YIMU 系统诊断日志",
        "=" * 68,
        f"导出时间 : {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"进程启动 : {_dt.datetime.fromtimestamp(_START_TS).strftime('%Y-%m-%d %H:%M:%S')}"
        f"（已运行 {int((time.time() - _START_TS) // 60)} 分钟）",
        f"日志文件 : {LOG_FILE}",
        "",
        "---------------- 环境快照 ----------------",
        env_report(),
        "",
        f"---------------- 事件记录（{len(events)} 条） ----------------",
    ]
    if not events:
        head.append("（暂无记录。请先复现一次失败，再回来导出）")
    head.extend(_render(e) for e in events)
    head.append("=" * 68)
    return "\n".join(head)


def clear() -> None:
    with _LOCK:
        _EVENTS.clear()
    try:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
    except Exception:
        pass


def stats() -> dict:
    with _LOCK:
        total = len(_EVENTS)
        errors = sum(1 for e in _EVENTS if e.get("level") == "error")
        warns = sum(1 for e in _EVENTS if e.get("level") == "warning")
    return {
        "events": total,
        "errors": errors,
        "warnings": warns,
        "size": LOG_FILE.stat().st_size if LOG_FILE.exists() else 0,
        "path": str(LOG_FILE),
        "uptime": int(time.time() - _START_TS),
    }


# ---------------------------------------------------------------------------
# 自动收集：logging / 线程 / 全局异常
# ---------------------------------------------------------------------------

class _CaptureHandler(logging.Handler):
    """把项目里已有的 ``logger.exception`` 自动收进诊断日志，零侵入。"""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith("uvicorn"):
                return
            detail = ""
            if record.exc_info:
                detail = "".join(traceback.format_exception(*record.exc_info))
            else:
                detail = record.getMessage()
            _event("error" if record.levelno >= logging.ERROR else "warning",
                   "log", f"{record.name}:{record.lineno}",
                   record.levelname.lower(), detail=detail[:8000],
                   fields={"func": record.funcName})
        except Exception:
            pass


def install() -> None:
    """安装全局钩子。重复调用安全。"""
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True

    try:
        root = logging.getLogger()
        if not any(isinstance(h, _CaptureHandler) for h in root.handlers):
            root.addHandler(_CaptureHandler())
        # 没有配置过 logging 时，WARNING 默认输出到 stderr；补一个基本配置，
        # 让「控制台能看到」和「诊断日志留档」同时成立。
        if root.level > logging.INFO:
            root.setLevel(logging.INFO)
    except Exception:
        pass

    try:
        _prev_hook = sys.excepthook

        def _hook(exc_type, exc, tb):
            try:
                detail = "".join(traceback.format_exception(exc_type, exc, tb))
                _event("error", "process", "uncaught", "failed", detail=detail)
            except Exception:
                pass
            try:
                _prev_hook(exc_type, exc, tb)
            except Exception:
                pass

        sys.excepthook = _hook
    except Exception:
        pass

    try:
        def _thread_hook(args):
            try:
                detail = "".join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback))
                _event("error", "thread", getattr(args.thread, "name", "?"), "failed",
                       detail=detail)
            except Exception:
                pass

        threading.excepthook = _thread_hook
    except Exception:
        pass

    record("system", "diagnostics_installed", status="ok",
           detail=f"诊断日志已启用 -> {LOG_FILE}")


def install_asyncio(loop) -> None:
    """把 asyncio 未处理异常也收进来（后台任务挂掉时最容易静默）。"""
    try:
        prev = loop.get_exception_handler()

        def _handler(_loop, context):
            try:
                exc = context.get("exception")
                detail = context.get("message", "")
                if exc is not None:
                    detail += "\n" + "".join(traceback.format_exception(
                        type(exc), exc, exc.__traceback__))
                _event("error", "asyncio", "unhandled", "failed", detail=detail)
            except Exception:
                pass
            if prev:
                try:
                    prev(_loop, context)
                except Exception:
                    pass

        loop.set_exception_handler(_handler)
    except Exception:
        pass
