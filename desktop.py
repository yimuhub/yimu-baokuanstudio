# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 爆款工作室 (YIMU Studio) 跨平台原生桌面客户端启动器 (Desktop App Runner)。

支持能力：
1. 后台自动拉起并健康监测 FastAPI/Uvicorn 核心服务 (127.0.0.1:8790)；
2. 优先采用 pywebview 呈现 100% 原生桌面软件窗口（无地址栏、独占窗口、原生菜单）；
3. 若未安装 pywebview，自动降级为 Chromium / Edge「独立应用模式 (--app)」，呈现纯净桌面窗体；
4. 若系统无独立 Chromium，安全回退至系统默认浏览器打开；
5. 监听窗口关闭事件，实现服务随窗口关闭平滑退出，释放端口与资源。
"""
from __future__ import annotations

import os
import sys
import time
import socket
import threading
import subprocess
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import version

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("PORT", "8790"))
APP_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
APP_TITLE = f"一幕·YIMU 爆款工作室 (V{version.__version__})"


def is_port_in_use(port: int, host: str = DEFAULT_HOST) -> bool:
    """检查指定端口是否处于监听状态。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


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
        # Windows Edge 与 Chrome 路径
        candidates.extend([
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ])
    elif sys.platform == "darwin":
        # macOS Chrome 与 Edge 路径
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ])
    elif sys.platform.startswith("linux"):
        # Linux Chrome 与 Chromium
        candidates.extend([
            "google-chrome",
            "google-chrome-stable",
            "chromium-browser",
            "chromium",
            "microsoft-edge-stable",
        ])

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
    # 1. 确保数据目录与数据库自愈
    try:
        from core.db import auto_heal_all_sqlite_databases
        auto_heal_all_sqlite_databases()
    except Exception:
        pass

    # 2. 如果服务尚未启动，则拉起 Uvicorn 后台服务线程
    if not is_port_in_use(DEFAULT_PORT):
        print(f"🎬 正在启动一幕工作室后端服务 (V{version.__version__})...")
        t = threading.Thread(target=run_uvicorn_server, daemon=True)
        t.start()
        if not wait_for_server(APP_URL, timeout=20.0):
            print("⚠️ 后端服务启动响应超时，尝试直接连接界面...")
    else:
        print(f"ℹ️ 检测到端口 {DEFAULT_PORT} 服务已在运行中，直接接入桌面窗口...")

    # 3. 优先尝试 pywebview 渲染原生无缝桌面窗口
    try:
        import webview
        print("🖥️ 正在通过原生 WebView 引擎呈现独立桌面窗体...")
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
        print("👋 桌面窗口已关闭，服务已安全退出。")
        sys.exit(0)
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️ pywebview 启动异常: {e}，正在切换至应用窗口模式...")

    # 4. 降级尝试 Chrome/Edge --app 独立窗口模式
    if try_launch_browser_app_mode(APP_URL):
        print(f"🚀 已在独立桌面应用模式中打开: {APP_URL}")
        print("💡 您可以随时关闭控制台窗口以结束服务。")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 收到退出信号，服务已停止。")
        return

    # 5. 兜底使用系统默认浏览器
    print(f"🌐 正在通过系统浏览器打开创作控制台: {APP_URL}")
    webbrowser.open(APP_URL)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 收到退出信号，服务已停止。")


if __name__ == "__main__":
    start_desktop_app()
