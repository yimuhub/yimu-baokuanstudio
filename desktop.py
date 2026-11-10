# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 爆款工作室 (YIMU Studio) 跨平台原生桌面客户端启动器 (Desktop App Runner)。

支持能力：
1. 后台自动拉起并健康监测 FastAPI/Uvicorn 核心服务 (127.0.0.1:8790)；
2. 优先采用 pywebview 呈现 100% 原生桌面软件窗口（无地址栏、独占窗口、原生菜单）；
3. 若未安装 pywebview，自动降级为 Chromium / Edge「独立应用模式 (--app)」；
4. 若系统无独立 Chromium，安全回退至系统默认浏览器打开；
5. 监听窗口关闭事件，实现服务随窗口关闭平滑退出，释放端口与资源。

V15.8 启动可靠性（客户缺陷报告 R1/R2/R8/F4 + 6.6）：
- 进程一开头就把 stdout/stderr 接到日志文件：pythonw.exe 没有标准输出时，
  任何 print / uvicorn 日志写入都不再抛异常打断主流程；
- 日志目录出厂即建，首行写入时间戳、版本、路径、解释器，启动类故障可自证；
- 跨平台单实例锁：重复双击不再并存多个窗口 / 多个进程 / 争用同一个 SQLite，
  而是唤起已有窗口后退出；
- 8790 被无关进程占用时自动挑选备用端口，不再误判「服务已就绪」。
"""
from __future__ import annotations

import os
import sys
import time
import json
import socket
import atexit
import threading
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# 0. 启动日志垫片（必须在任何 import / print / 第三方库之前完成）
# ---------------------------------------------------------------------------

class _StreamTee:
    """把输出同时写给原流与日志文件；任一目标不可用都不影响主流程。"""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, original, sink):
        self._original = original
        self._sink = sink

    def write(self, data: str) -> int:
        text = str(data)
        try:
            if self._original is not None:
                self._original.write(text)
        except Exception:
            pass  # 控制台编码问题（GBK 写不出 emoji）绝不阻断启动
        try:
            self._sink.write(text)
            self._sink.flush()
        except Exception:
            pass
        return len(text)

    def flush(self) -> None:
        for stream in (self._original, self._sink):
            try:
                if stream is not None:
                    stream.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)

    @property
    def closed(self) -> bool:
        return False


def _user_data_dir() -> Path:
    """跨平台的用户级数据目录（单实例锁与敏感配置的落点）。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "YIMU-Studio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "YIMU-Studio"
    return Path(os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")) / "yimu-studio"


def _log_paths() -> list[Path]:
    """优先写安装目录 logs/（客户最容易找到），只读安装时回落用户目录。"""
    candidates = [ROOT / "logs" / "desktop_launcher.log", _user_data_dir() / "logs" / "desktop_launcher.log"]
    out = []
    for p in candidates:
        if p not in out:
            out.append(p)
    return out


def _setup_streams() -> str:
    """重定向 stdout/stderr，并写入第一条带时间戳的启动记录。

    pythonw.exe 下 sys.stdout / sys.stderr 为 None；历史版本里第一个 print
    就会抛 AttributeError，导致 uvicorn 线程根本没起来（客户报告 R2）。
    """
    sink = None
    used = ""
    for p in _log_paths():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            sink = p.open("a", encoding="utf-8", errors="replace", buffering=1)
            used = str(p)
            break
        except Exception:
            continue
    if sink is None:
        # 所有位置都不可写：至少保证 print 不抛异常
        class _Null:
            def write(self, _text):
                return 0

            def flush(self):
                pass

        sys.stdout = _Null() if sys.stdout is None else sys.stdout
        sys.stderr = _Null() if sys.stderr is None else sys.stderr
        return ""

    sys.stdout = _StreamTee(sys.stdout, sink)
    sys.stderr = _StreamTee(sys.stderr, sink)
    atexit.register(lambda: sink.close())
    return used


LAUNCH_LOG = _setup_streams()

import version  # noqa: E402

_ts = datetime.now().isoformat(timespec="seconds")
print(f"[{_ts}] === 一幕·YIMU 爆款工作室启动 V{version.__version__} ===", flush=True)
print(f"[{_ts}] platform={sys.platform} exe={sys.executable} root={ROOT} cwd={os.getcwd()}", flush=True)
print(f"[{_ts}] stdout_was={'None' if not hasattr(sys.stdout, '_original') or sys.stdout._original is None else 'ok'} "
      f"log={LAUNCH_LOG or '(不可写)'}", flush=True)

# 全功能离线分发包：必须在任何第三方 import 之前完成自举——激活自带 site-packages、
# 生成出厂配额、写入内置官方凭证、创建数据目录。开发模式没有 runtime/ 时自动跳过。
try:
    from scripts.first_run_bootstrap import bootstrap as _first_run_bootstrap
    BOOTSTRAP = _first_run_bootstrap()
    print(f"[首次启动] 自举完成: {BOOTSTRAP}", flush=True)
except Exception as _boot_err:  # 自举失败绝不阻断桌面启动，但必须留痕
    BOOTSTRAP = {}
    print(f"[首次启动] 自举跳过: {_boot_err!r}", flush=True)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("PORT", "8790"))
APP_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
APP_TITLE = f"一幕·YIMU 爆款工作室 (V{version.__version__})"
LOCK_FILE = _user_data_dir() / "instance.lock"


# ---------------------------------------------------------------------------
# 1. 单实例保护（R8 / F4）
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True  # 判不准时保守认为还活着，避免双开
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock() -> dict:
    try:
        return json.loads(LOCK_FILE.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


def release_single_instance() -> None:
    """只删除属于自己的锁，避免误删后来实例的锁。"""
    try:
        if _read_lock().get("pid") == os.getpid():
            LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def acquire_single_instance() -> bool:
    """O_EXCL 原子锁；True=本次获得，False=已有实例在运行。"""
    for _ in range(3):
        try:
            LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(LOCK_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            time.sleep(0.15)
            info = _read_lock()
            pid = int(info.get("pid") or 0)
            if _pid_alive(pid):
                return False
            # 进程已死（崩溃 / 强杀）→ 清理陈旧锁后重试
            try:
                LOCK_FILE.unlink()
            except OSError:
                time.sleep(0.1)
                if _pid_alive(int(_read_lock().get("pid") or 0)):
                    return False
            continue
        except OSError:
            return True  # 锁目录不可写时 fail-open，不让用户完全打不开
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "port": DEFAULT_PORT,
                           "title": APP_TITLE, "started_at": time.time()}, f)
        except Exception:
            pass
        atexit.register(release_single_instance)
        return True
    return False


def activate_existing_window() -> bool:
    """把已有实例的主窗体唤到前台；失败则至少用默认浏览器打开同一服务。"""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            found = []

            def _cb(hwnd, _lparam):
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if "一幕" in buf.value or "YIMU" in buf.value:
                        found.append((hwnd, buf.value))
                return True

            user32.EnumWindows(WNDENUMPROC(_cb), 0)
            for hwnd, _title in found:
                user32.ShowWindow(hwnd, 9)   # SW_RESTORE：解除 SW_HIDE 造成的不可见
                user32.SetForegroundWindow(hwnd)
                return True
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to set frontmost of '
                 '(first process whose name contains "Python") to true'],
                timeout=3, capture_output=True,
            )
        except Exception:
            pass
    else:
        for cmd in (["wmctrl", "-a", "一幕"], ["wmctrl", "-a", "YIMU"]):
            try:
                if subprocess.run(cmd, timeout=3, capture_output=True).returncode == 0:
                    return True
            except Exception:
                continue
    try:
        webbrowser.open(APP_URL)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 2. 服务探测与启动
# ---------------------------------------------------------------------------

def is_port_in_use(port: int, host: str = DEFAULT_HOST) -> bool:
    """检查指定端口是否处于监听状态。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def probe_service() -> str:
    """返回 free / yimu / foreign：区分「本应用已在跑」与「端口被别的程序占了」。"""
    if not is_port_in_use(DEFAULT_PORT):
        return "free"
    try:
        import urllib.request
        with urllib.request.urlopen(f"{APP_URL}/api/version", timeout=1.0) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
        if resp.status == 200 and (payload.get("version") or payload.get("details", {}).get("version")):
            return "yimu"
    except Exception:
        pass
    return "foreign"


def select_free_port() -> int:
    """8790 被无关进程占用时，在 8791..8810 里挑一个可用端口。"""
    global DEFAULT_PORT, APP_URL
    if probe_service() != "foreign":
        return DEFAULT_PORT
    for candidate in range(DEFAULT_PORT + 1, DEFAULT_PORT + 21):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((DEFAULT_HOST, candidate)) != 0:
                print(f"⚠️ 端口 {DEFAULT_PORT} 被其它程序占用，自动切换到 {candidate}", flush=True)
                DEFAULT_PORT = candidate
                APP_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
                os.environ["PORT"] = str(candidate)
                return candidate
    return DEFAULT_PORT


def wait_for_server(url: str, timeout: float = 15.0) -> bool:
    """轮询等待 Web 后端服务就绪。"""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{url}/api/version", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def run_uvicorn_server():
    """在后台线程中运行 Uvicorn 服务端。"""
    import uvicorn
    from web.admin import app

    config = uvicorn.Config(
        app=app,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


def try_launch_browser_app_mode(url: str) -> bool:
    """尝试使用 Chrome / Edge 的应用模式 (--app) 打开独立窗体。"""
    candidates = []
    if sys.platform == "win32":
        candidates.extend([
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ])
    elif sys.platform == "darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ])
    elif sys.platform.startswith("linux"):
        candidates.extend([
            "google-chrome", "google-chrome-stable", "chromium-browser",
            "chromium", "microsoft-edge-stable",
        ])

    # A2 离线包自带 Chrome for Testing，优先于系统浏览器（客户机无需安装任何浏览器）
    try:
        from core.browser_path import bundled_chromium
        _builtin = bundled_chromium()
        if _builtin:
            candidates.insert(0, _builtin)
    except Exception:
        pass

    for exe in candidates:
        if sys.platform.startswith("linux"):
            import shutil
            if shutil.which(exe):
                try:
                    subprocess.Popen([exe, f"--app={url}"])
                    return True
                except Exception:
                    pass
        elif os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}"])
                return True
            except Exception:
                pass
    return False


def start_desktop_app():
    """主桌面启动入口。"""
    # 1. 单实例：重复双击时唤起已有窗口，不再并存多个进程 / 多个 SQLite 使用者
    if not acquire_single_instance():
        print(f"ℹ️ 已有实例在运行（锁文件 {LOCK_FILE}），唤起已有窗口后退出。", flush=True)
        activate_existing_window()
        return

    # 2. 端口冲突自动避让，避免把无关进程误判为「服务已就绪」
    select_free_port()
    state = probe_service()
    if state == "free":
        print(f"🎬 正在启动一幕工作室后端服务 (V{version.__version__}) @ {DEFAULT_PORT}...", flush=True)
        t = threading.Thread(target=run_uvicorn_server, daemon=True)
        t.start()
        if not wait_for_server(APP_URL, timeout=20.0):
            print("⚠️ 后端服务启动响应超时，尝试直接连接界面...", flush=True)
    elif state == "yimu":
        print(f"ℹ️ 检测到端口 {DEFAULT_PORT} 上已有本应用服务，直接接入桌面窗口...", flush=True)
    else:
        print(f"⚠️ 端口 {DEFAULT_PORT} 被未知服务占用，界面可能无法正常工作。", flush=True)

    # 3. 优先尝试 pywebview 渲染原生无缝桌面窗口
    try:
        import webview
        print("🖥️ 正在通过原生 WebView 引擎呈现独立桌面窗体...", flush=True)
        webview.create_window(
            title=APP_TITLE,
            url=APP_URL,
            width=1366,
            height=860,
            min_size=(1024, 680),
            text_select=True,
            zoomable=True,
        )
        webview.start()
        print("👋 桌面窗口已关闭，服务已安全退出。", flush=True)
        sys.exit(0)
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️ pywebview 启动异常: {e!r}，正在切换至应用窗口模式...", flush=True)

    # 4. 降级尝试 Chrome/Edge --app 独立窗口模式
    if try_launch_browser_app_mode(APP_URL):
        print(f"🚀 已在独立桌面应用模式中打开: {APP_URL}", flush=True)
        print("💡 您可以随时关闭控制台窗口以结束服务。", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 收到退出信号，服务已停止。", flush=True)
        return

    # 5. 兜底使用系统默认浏览器
    print(f"🌐 正在通过系统浏览器打开创作控制台: {APP_URL}", flush=True)
    webbrowser.open(APP_URL)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 收到退出信号，服务已停止。", flush=True)


if __name__ == "__main__":
    start_desktop_app()
