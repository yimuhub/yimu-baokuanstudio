# SPDX-License-Identifier: BUSL-1.1
"""内置 Chromium 定位与启动（A2 完全自给分发包）。

全功能离线包自带一份 Chrome for Testing，同时供两处使用：
  * 桌面窗口（``desktop.py`` 的独立应用模式）；
  * Playwright 无头渲染（卡片截图、热榜抓取）。

开发模式没有 ``chromium/`` 目录时本模块完全透明：``bundled_chromium()`` 返回空串，
``launch_chromium()`` 退化为 Playwright 原来的启动逻辑（系统 Chrome / 已安装内核）。
"""
from __future__ import annotations

import os
from pathlib import Path

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


def launch_chromium(browser_type, **kwargs):
    """优先用内置内核启动；失败时逐级退回系统 Chrome / Playwright 自带内核。

    ``channel`` 与 ``executable_path`` 不能同时传给 Playwright，因此命中内置内核时
    会把 ``channel`` 摘掉。调用方原有的 try/except 两级回退被收拢到这里。
    """
    opts = dict(kwargs)
    exe = bundled_chromium()
    if exe:
        opts.pop("channel", None)
        try:
            return browser_type.launch(executable_path=exe, **opts)
        except Exception:
            pass
    channel = opts.pop("channel", None)
    if channel:
        try:
            return browser_type.launch(channel=channel, **opts)
        except Exception:
            pass
    return browser_type.launch(**opts)
