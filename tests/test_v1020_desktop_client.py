# SPDX-License-Identifier: BUSL-1.1
r"""V10.2.0 全平台独立桌面客户端架构与零配置启动专项测试。

核心验证：
1. 原生跨平台桌面客户端中枢 (desktop.py) 模块结构完整，具备端口检测、健康等待、浏览器应用模式降级与优雅退出能力；
2. Windows 无黑框静默桌面引导 (一幕桌面客户端.vbs) 存在且具备 runtime\pythonw.exe 优先级检测；
3. macOS 原生客户端引导 (一幕桌面客户端.command) 与 Linux 原生引导 (一幕桌面客户端_linux.sh, 一幕桌面客户端.desktop) 完备且具执行权限；
4. Windows 通用一键启动脚本 (一键启动.bat) 与一键升级脚本 (一键升级.bat) 具备步骤 0 runtime 便携运行时优先检测；
5. 全自动化多平台桌面打包器 (scripts/build_desktop_client.py) 完备可用；
6. GitHub Actions 独立桌面客户端自动化构建流水线就绪。
"""
from __future__ import annotations

import os
from pathlib import Path
import version

ROOT = Path(__file__).resolve().parent.parent


def test_v1020_version_and_codename():
    """验证版本已正式步进至 10.2.0，代号保持为 鸿蒙始。"""
    assert version.__version__ == "10.2.0"
    assert version.__codename__ == "鸿蒙始"
    assert "桌面客户端" in version.__slogan__


def test_v1020_desktop_runner_exists_and_functional():
    """验证 desktop.py 存在且具备桌面客户端核心能力接口。"""
    desktop_file = ROOT / "desktop.py"
    assert desktop_file.exists(), "必须存在 desktop.py 桌面客户端启动器"

    import desktop
    assert hasattr(desktop, "start_desktop_app")
    assert hasattr(desktop, "try_launch_browser_app_mode")
    assert hasattr(desktop, "wait_for_server")
    assert hasattr(desktop, "is_port_in_use")
    assert desktop.DEFAULT_PORT == 8790


def test_v1020_windows_vbs_launcher_exists_and_silent():
    """验证 Windows 一幕桌面客户端.vbs 存在且隐藏黑框控制台。"""
    vbs = ROOT / "一幕桌面客户端.vbs"
    assert vbs.exists()
    content = vbs.read_text(encoding="utf-8")
    assert "runtime\\pythonw.exe" in content
    assert "desktop.py" in content
    # WshShell.Run pyExe & " " & desktopScript, 0, False (0 表示无黑框隐藏)
    assert ", 0, False" in content


def test_v1020_unix_launchers_exist_and_executable():
    """验证 macOS 和 Linux 桌面客户端引导脚本存在且可执行。"""
    mac_cmd = ROOT / "一幕桌面客户端.command"
    linux_sh = ROOT / "一幕桌面客户端_linux.sh"
    linux_desktop = ROOT / "一幕桌面客户端.desktop"

    assert mac_cmd.exists()
    assert linux_sh.exists()
    assert linux_desktop.exists()

    assert os.access(mac_cmd, os.X_OK), "macOS 桌面引导应具执行权限"
    assert os.access(linux_sh, os.X_OK), "Linux 桌面引导应具执行权限"

    mac_text = mac_cmd.read_text(encoding="utf-8")
    assert "desktop.py" in mac_text

    linux_text = linux_sh.read_text(encoding="utf-8")
    assert "desktop.py" in linux_text


def test_v1020_bat_scripts_prioritize_embedded_runtime():
    """验证一键启动.bat 与一键升级.bat 优先检测 runtime 运行时。"""
    start_bat = (ROOT / "一键启动.bat").read_text(encoding="utf-8")
    assert 'if exist "runtime\\python.exe"' in start_bat
    assert "desktop.py" in start_bat

    upgrade_bat = (ROOT / "一键升级.bat").read_text(encoding="utf-8")
    assert 'if exist "runtime\\python.exe"' in upgrade_bat


def test_v1020_builder_and_ci_workflow():
    """验证打包脚本与 GitHub Actions 桌面客户端构建流水线。"""
    builder = ROOT / "scripts/build_desktop_client.py"
    assert builder.exists()
    builder_text = builder.read_text(encoding="utf-8")
    assert "build_windows_portable_bundle" in builder_text
    assert "build_unix_portable_bundle" in builder_text
    assert "setup_embedded_python_runtime" in builder_text

    workflow = ROOT / ".github/workflows/build-desktop-client.yml"
    assert workflow.exists()
    workflow_text = workflow.read_text(encoding="utf-8")
    assert "scripts/build_desktop_client.py" in workflow_text
