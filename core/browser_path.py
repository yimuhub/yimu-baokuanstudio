# SPDX-License-Identifier: BUSL-1.1
"""内置 Chromium 定位与启动（A2 完全自给分发包）。

全功能离线包自带一份 Chrome for Testing，同时供两处使用：
  * 桌面窗口（``desktop.py`` 的独立应用模式）；
  * Playwright 无头渲染（卡片截图、热榜抓取）。

开发模式没有 ``chromium/`` 目录时本模块完全透明：``bundled_chromium()`` 返回空串，
``launch_chromium()`` 退化为 Playwright 原来的启动逻辑（系统 Chrome / 已安装内核）。

V15.9.3：修掉内置内核"启动即崩"的真因。此前判断是 ad-hoc 签名问题，实测不是：
``ZipFile.extractall()`` 不还原 ``external_attr`` 里的权限位，解压后除了主可执行
文件之外，``chrome_crashpad_handler`` 与 Renderer/GPU Helper 等 13 个 Mach-O 全是
``0644``。Chromium 启动第一步 spawn crashpad handler 就 ``EACCES``，``CHECK``
失败触发 ``__builtin_trap()``——就是客户机看到的「意外退出 / EXC_BREAKPOINT」。
现在打包侧解压即还原权限并作出厂断言，运行期再由
:func:`heal_executable_perms` 兜一层自愈。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent
BUNDLE = Path(os.environ.get("YIMU_BUNDLE_ROOT") or BASE.parent)
MARKER = BUNDLE / "chromium" / "EXECUTABLE"

# 可执行映像魔数（Mach-O 各种字节序 + Linux ELF）
_EXEC_MAGICS = (
    b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
    b"\xfe\xed\xfa\xcf", b"\x7fELF",
)
_PERMS_HEALED = False


def heal_executable_perms(root: Path) -> int:
    """给内置浏览器目录里缺 ``x`` 位的可执行映像补权限，返回修复个数。

    为什么需要运行期也做一遍：``ZipFile.extractall()`` 不还原 ``external_attr``
    里的权限位，解压出来一律 ``0644``。V15.9.2 及之前只对主可执行文件单点
    ``chmod``，于是 ``chrome_crashpad_handler`` 与 Renderer/GPU Helper 等 13 个
    Mach-O 都不可执行 —— Chromium 启动第一步 spawn crashpad handler 就
    ``EACCES``，``CHECK`` 失败 ``__builtin_trap()``，客户机看到的是
    「意外退出 / EXC_BREAKPOINT / crashed on child side of fork pre-exec」。

    打包侧已在 ``scripts/build_full_bundle.py`` 根治（解压即还原权限 + 出厂断言），
    这里再兜一层：老版本装过的目录、用第三方工具二次解压过的目录，都能自愈。
    """
    fixed = 0
    if sys.platform == "win32":
        return 0
    try:
        for p in root.rglob("*"):
            if p.is_symlink() or not p.is_file():
                continue
            try:
                if os.access(p, os.X_OK):
                    continue
                with open(p, "rb") as f:
                    head = f.read(4)
            except OSError:
                continue
            if head in _EXEC_MAGICS:
                try:
                    p.chmod(p.stat().st_mode | 0o555)
                    fixed += 1
                except OSError:
                    pass
    except Exception as e:  # 目录不可读等，绝不影响主流程
        logger.warning("内置浏览器权限自愈跳过：%r", e)
    return fixed


def bundled_chromium() -> str:
    """返回内置浏览器可执行文件的绝对路径；不存在则返回空串。"""
    global _PERMS_HEALED
    p = os.environ.get("YIMU_CHROMIUM_PATH", "").strip()
    if p and Path(p).is_file():
        if not _PERMS_HEALED:
            _PERMS_HEALED = True
            heal_executable_perms(Path(p).parent.parent.parent.parent)
        return p
    if MARKER.is_file():
        try:
            rel = MARKER.read_text(encoding="utf-8").strip()
            exe = (MARKER.parent / rel).resolve()
            if exe.is_file():
                if not _PERMS_HEALED:
                    _PERMS_HEALED = True
                    n = heal_executable_perms(MARKER.parent)
                    if n:
                        logger.warning("内置浏览器补齐执行位 %d 个（解压丢权限）", n)
                return str(exe)
        except Exception:
            pass
    return ""


def _probe_browser(browser, timeout_ms: int = 8000) -> bool:
    """开一个空白页再关掉，验证渲染子进程真的能起来。

    为什么需要这一步：内置内核即使主进程起得来，子进程也可能起不来（V15.9.3
    之前的执行位缺失就是这样——主 exe 被单独 chmod 过，helper 全没 x 位）。
    此时 Playwright 的 ``launch()`` 是**成功返回**的：连接已经建立，死的是后面
    的子进程。只有真正建 page / 导航一次才能暴露，也才能及时降级。
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


def _broken_mark() -> Path:
    return MARKER.parent / ".broken"


def _is_marked_broken() -> bool:
    return _broken_mark().is_file()


def _mark_broken() -> None:
    """内置内核探活失败后落标记，后续进程不再反复重试（避免反复弹崩溃窗）。"""
    try:
        _broken_mark().write_text(
            "内置浏览器启动后渲染子进程不可用，已自动改用系统浏览器。\n"
            "删掉本文件可重新尝试内置内核。\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def launch_chromium(browser_type, **kwargs):
    """启动浏览器：内置内核 → 系统浏览器 → 默认内核，每个候选都做探活。

    V15.9.3：内置内核重新回到第一候选。V15.9.2 之所以把它降为兜底，是因为它
    在客户机上必崩 —— 而那个崩溃的真因是解压丢了执行位（见
    :func:`heal_executable_perms`），已根治。现在内置内核版本可控、离线可用，
    仍是"完全自给"的正确选择。

    仍然保留探活与降级：万一某台机器上另有原因起不来，第一次会记下
    ``chromium/.broken`` 标记，之后不再反复重试，直接走系统浏览器。
    """
    opts = dict(kwargs)
    exe = bundled_chromium()

    plans = []
    if exe and not _is_marked_broken():
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
        if name == "内置内核":
            _mark_broken()
        last_err = RuntimeError(f"{name} 启动后渲染子进程不可用")

    raise last_err or RuntimeError("没有可用的浏览器内核")
