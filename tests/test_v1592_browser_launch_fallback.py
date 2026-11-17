# SPDX-License-Identifier: BUSL-1.1
"""V15.9.1：浏览器启动的候选顺序、存活探测与降级。

背景：macOS 上 ad-hoc 签名的内置 Chrome for Testing 会在 fork 渲染子进程时被
系统以 SIGTRAP 终止（EXC_BREAKPOINT，0.15ms 内结束）。旧实现两个漏洞：

1. ``desktop.py`` 的 ``Popen`` 不抛异常就 return True —— 进程随后暴毙，界面
   毫不知情，用户只看到崩溃弹窗；
2. ``launch_chromium()`` 只在 ``launch()`` 抛异常时降级 —— Playwright 此时
   连接已建立，死的是后面的渲染子进程，于是任务白跑一次才报错。

本文件锁死两条修复的行为，防止回退。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# desktop.py：窗口启动
# ---------------------------------------------------------------------------

class _FakeProc:
    """模拟 Popen 返回值：code=None 表示还活着，其它表示已退出。"""

    def __init__(self, code=None):
        self.returncode = code

    def poll(self):
        return self.returncode


def test_v1592_window_prefers_system_browser(monkeypatch):
    """有系统浏览器时不得动用内置内核（内置是兜底，不是首选）。"""
    import desktop

    seen = []

    def fake_probe(exe, url, extra, probe=1.2):
        seen.append((exe, tuple(extra)))
        return True

    monkeypatch.setattr(desktop, "_resolve_exe", lambda e: "/fake/Google Chrome")
    monkeypatch.setattr(desktop, "_launch_and_probe", fake_probe)

    assert desktop.try_launch_browser_app_mode("http://127.0.0.1:8790") is True
    assert seen and seen[0][0] == "/fake/Google Chrome"
    assert seen[0][1] == (), "系统浏览器不应被加上 --no-sandbox 之类的降级参数"


def test_v1592_window_falls_back_to_builtin_with_no_sandbox(monkeypatch):
    """系统浏览器全都起不来时，才用内置内核，且必须带 --no-sandbox。"""
    import desktop
    import core.browser_path as bp

    seen = []

    def fake_probe(exe, url, extra, probe=1.2):
        seen.append((exe, tuple(extra)))
        return exe == "/bundle/chrome"

    monkeypatch.setattr(desktop, "_resolve_exe", lambda e: e if "Chrome" in e else "")
    monkeypatch.setattr(desktop, "_launch_and_probe", fake_probe)
    monkeypatch.setattr(bp, "bundled_chromium", lambda: "/bundle/chrome")

    assert desktop.try_launch_browser_app_mode("http://127.0.0.1:8790") is True
    builtin_calls = [c for c in seen if c[0] == "/bundle/chrome"]
    assert builtin_calls, "内置内核应被尝试"
    assert builtin_calls[0][1] == ("--no-sandbox",)


def test_v1592_window_returns_false_when_every_candidate_dies(monkeypatch):
    """全部候选都失败时返回 False，让调用方退回系统默认浏览器，而不是干等。"""
    import desktop
    import core.browser_path as bp

    monkeypatch.setattr(desktop, "_resolve_exe", lambda e: e)
    monkeypatch.setattr(desktop, "_launch_and_probe", lambda *a, **k: False)
    monkeypatch.setattr(bp, "bundled_chromium", lambda: "/bundle/chrome")

    assert desktop.try_launch_browser_app_mode("http://127.0.0.1:8790") is False


def test_v1592_probe_rejects_process_that_dies_immediately(monkeypatch):
    """Popen 成功但进程立刻退出 —— 必须判定失败（这正是崩溃报告里的形态）。"""
    import desktop

    monkeypatch.setattr(desktop, "_app_mode_profile_dir", lambda: "")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: _FakeProc(code=5))

    assert desktop._launch_and_probe("/x/chrome", "http://127.0.0.1:8790", [], probe=0.2) is False


def test_v1592_probe_accepts_surviving_process(monkeypatch):
    """进程挺过探测窗口即视为启动成功。"""
    import desktop

    monkeypatch.setattr(desktop, "_app_mode_profile_dir", lambda: "")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: _FakeProc(code=None))

    assert desktop._launch_and_probe("/x/chrome", "http://127.0.0.1:8790", [], probe=0.2) is True


def test_v1592_probe_passes_profile_and_common_flags(monkeypatch):
    """启动参数必须带独立 profile 与免首启向导参数，且 cmd 结构可被审查。"""
    import desktop

    captured = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = list(cmd)
        return _FakeProc(code=5)

    monkeypatch.setattr(desktop, "_app_mode_profile_dir", lambda: "/tmp/yimu-profile")
    monkeypatch.setattr(desktop.subprocess, "Popen", fake_popen)

    desktop._launch_and_probe("/x/chrome", "http://127.0.0.1:8790", ["--no-sandbox"], probe=0.1)

    cmd = captured["cmd"]
    assert cmd[0] == "/x/chrome"
    assert "--app=http://127.0.0.1:8790" in cmd
    assert "--user-data-dir=/tmp/yimu-profile" in cmd
    assert "--no-first-run" in cmd
    assert "--no-default-browser-check" in cmd
    assert "--no-sandbox" in cmd


# ---------------------------------------------------------------------------
# core/browser_path.py：Playwright 内核降级
# ---------------------------------------------------------------------------

class _FakePage:
    def __init__(self, broken: bool):
        self.broken = broken

    def goto(self, *a, **kw):
        if self.broken:
            raise RuntimeError("Target page, context or browser has been closed")
        return None


class _FakeCtx:
    def __init__(self, broken: bool):
        self.broken = broken
        self.closed = False

    def new_page(self):
        return _FakePage(self.broken)

    def close(self):
        self.closed = True


class _FakeBrowser:
    """broken=True 模拟"launch 成功但渲染子进程被系统杀掉"。"""

    def __init__(self, broken: bool):
        self.broken = broken
        self.closed = False

    def new_context(self, *a, **kw):
        return _FakeCtx(self.broken)

    def close(self):
        self.closed = True


class _FakeBrowserType:
    def __init__(self, browsers):
        self._browsers = list(browsers)
        self.calls = []

    def launch(self, **kw):
        self.calls.append(kw)
        return self._browsers.pop(0)


@pytest.fixture()
def _with_builtin(monkeypatch):
    import core.browser_path as bp
    monkeypatch.setattr(bp, "bundled_chromium", lambda: "/bundle/chrome")
    return bp


def test_v1592_playwright_degrades_when_builtin_renderer_dies(_with_builtin):
    """内置内核探活失败 → 关闭它 → 降级到系统浏览器，且返回可用的那个。"""
    bp = _with_builtin
    good = _FakeBrowser(broken=False)
    broken = _FakeBrowser(broken=True)
    bt = _FakeBrowserType([broken, good])

    browser = bp.launch_chromium(bt, headless=True, channel="chrome", args=["--no-sandbox"])

    assert browser is good
    assert broken.closed is True, "探活失败的内核必须被关闭，不能泄漏进程"
    assert bt.calls[0]["executable_path"] == "/bundle/chrome"
    assert "channel" not in bt.calls[0], "executable_path 与 channel 不能同时传"
    assert bt.calls[1]["channel"] == "chrome"


def test_v1592_playwright_raises_when_all_candidates_die(_with_builtin):
    """三个候选全崩时才抛异常，异常信息要能指认最后一次失败。"""
    bp = _with_builtin
    bt = _FakeBrowserType([
        _FakeBrowser(broken=True),
        _FakeBrowser(broken=True),
        _FakeBrowser(broken=True),
    ])

    with pytest.raises(RuntimeError):
        bp.launch_chromium(bt, headless=True, channel="chrome")

    assert len(bt.calls) == 3, "内置 / 系统 / 默认三个候选都要试过"


def test_v1592_playwright_without_bundle_keeps_old_behaviour(monkeypatch):
    """开发模式（无内置内核）不改变原有链路：channel 直接生效。"""
    import core.browser_path as bp
    monkeypatch.setattr(bp, "bundled_chromium", lambda: "")
    good = _FakeBrowser(broken=False)
    bt = _FakeBrowserType([good])

    browser = bp.launch_chromium(bt, headless=True, channel="chrome")

    assert browser is good
    assert bt.calls[0]["channel"] == "chrome"
