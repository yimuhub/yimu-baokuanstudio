# SPDX-License-Identifier: BUSL-1.1
"""内置 Chromium 定位与启动（A2 完全自给分发包）。

全功能离线包自带一份 Chrome for Testing，同时供两处使用：
  * 桌面窗口（``desktop.py`` 的独立应用模式）；
  * Playwright 无头渲染（卡片截图、热榜抓取）。

开发模式没有 ``chromium/`` 目录时本模块完全透明：``bundled_chromium()`` 返回空串，
``launch_chromium()`` 退化为 Playwright 原来的启动逻辑（系统 Chrome / 已安装内核）。

V15.9.2：内置内核由"首选"降为"兜底"，并新增启动后探活。原因见
:func:`_probe_browser` 的说明——ad-hoc 签名的 CfT 在部分新版 macOS 上连渲染子
进程都 fork 不出来，而 Playwright 的 ``launch()`` 此时仍会"成功"返回。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent
BUNDLE = Path(os.environ.get("YIMU_BUNDLE_ROOT") or BASE.parent)
MARKER = BUNDLE / "chromium" / "EXECUTABLE"


def bundled_chromium() -> str:
    """返回内置浏览器可执行文件的绝对路径；不存在则返回空串。"""
    p = os.environ.get("YIMU_CHROMIUM_PATH", "").strip()
    if p and Path(p).is_file():
        return p
    if MARKER.is_file():
        try:
            rel = MARKER.read_text(encoding="utf-8").strip()
            exe = (MARKER.parent / rel).resolve()
            if exe.is_file():
                return str(exe)
        except Exception:
            pass
    return ""


def _probe_browser(browser, timeout_ms: int = 8000) -> bool:
    """开一个空白页再关掉，验证渲染子进程真的能起来。

    为什么需要这一步：macOS 上 ad-hoc 签名的 Chrome for Testing，在主进程
    ``fork`` 出渲染子进程时可能被系统直接 SIGTRAP 掉（``EXC_BREAKPOINT``，
    子进程连 ``exec`` 都没走到）。此时 Playwright 的 ``launch()`` 是**成功返回**
    的——连接已经建立，死的是后面的子进程。只有真正建 page / 导航一次才能暴露。
    """
    ctx = None
    try:
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("about:blank", timeout=timeout_ms, wait_until="domcontentloaded")
        return True
    except Exception as e:
        logger.warning("浏览器启动后探活失败（渲染子进程不可用）：%r", e)
        return False
    finally:
        try:
            if ctx is not None:
                ctx.close()
        except Exception:
            pass


def launch_chromium(browser_type, **kwargs):
    """启动浏览器：内置内核（若有）→ 系统浏览器 → 默认内核，每个候选都做探活。

    V15.9.2 之前只在 ``launch()`` **抛异常**时降级。问题在于 ad-hoc 签名的内置
    内核在部分系统上 ``launch()`` 不抛异常、随后渲染子进程被系统杀掉，于是任务
    白跑一次才报错。现在：

    1. 每个候选启动后必须通过 :func:`_probe_browser` 才算成功，否则关闭换下一个；
    2. ``channel`` 与 ``executable_path`` 不能同时传，命中内置内核时会摘掉 channel；
    3. 全部失败才抛最后一次异常，调用方行为不变。
    """
    opts = dict(kwargs)
    exe = bundled_chromium()

    plans = []
    if exe:
        builtin_opts = dict(opts)
        builtin_opts.pop("channel", None)
        plans.append(("内置内核", lambda o=builtin_opts: browser_type.launch(executable_path=exe, **o)))

    channel = opts.pop("channel", None)
    if channel:
        plans.append((f"系统浏览器({channel})", lambda c=channel: browser_type.launch(channel=c, **opts)))
    plans.append(("默认内核", lambda: browser_type.launch(**opts)))

    last_err: Exception | None = None
    for name, start in plans:
        browser = None
        try:
            browser = start()
        except Exception as e:
            last_err = e
            logger.warning("%s 启动失败，尝试下一个候选：%r", name, e)
            continue

        if _probe_browser(browser):
            return browser

        logger.warning("%s 启动后渲染子进程不可用，已关闭并降级", name)
        try:
            browser.close()
        except Exception:
            pass
        last_err = RuntimeError(f"{name} 启动后渲染子进程不可用")

    raise last_err or RuntimeError("没有可用的浏览器内核")
