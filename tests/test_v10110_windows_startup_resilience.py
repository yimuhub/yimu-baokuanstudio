# SPDX-License-Identifier: BUSL-1.1
"""V10.1.10 Windows 一键启动闪退防御专项测试。

核心验证：
1. 一键启动.bat 必须使用"真实运行验证"来检测 Python，而不只是文件存在检测。
2. 脚本在 PATH 中只有 Microsoft Store 占位符时，必须走到友好报错而不是闪退。
3. 脚本对 venv 创建失败和 pip 安装失败都有错误兜底。
4. 自动复制 .env.example → .env 逻辑存在。
5. 版本升级到 10.1.10。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_v10110_bat_validates_python_actually_runs():
    """bat 脚本必须用 --version 真正运行 Python，而不只是 where 文件检测。"""
    bat = (ROOT / "一键启动.bat").read_text(encoding="utf-8", errors="replace")
    # 关键修复：用 python --version 验证真实可执行（排除 Store 占位符）
    assert "python --version" in bat or "--version" in bat, (
        "一键启动.bat 必须包含 --version 执行验证，排除 Microsoft Store 占位符"
    )


def test_v10110_bat_has_venv_creation_error_trap():
    """bat 脚本在 venv 创建失败时不能无声闪退，必须有错误提示。"""
    bat = (ROOT / "一键启动.bat").read_text(encoding="utf-8", errors="replace")
    # 应有 errorlevel 检查 + pause（错误兜底）
    assert "errorlevel" in bat, "bat 脚本必须检查 errorlevel 以捕获 venv 创建失败"
    assert "pause" in bat, "bat 脚本在出错后必须暂停，让用户看到错误信息"


def test_v10110_bat_has_store_placeholder_guidance():
    """bat 脚本的错误提示必须解释 Microsoft Store 占位符问题。"""
    bat = (ROOT / "一键启动.bat").read_text(encoding="utf-8", errors="replace")
    # 应提及 Store 或应用执行别名
    assert "Store" in bat or "别名" in bat or "占位符" in bat, (
        "bat 脚本错误提示应解释 Microsoft Store python.exe 占位符问题"
    )


def test_v10110_bat_auto_creates_env_file():
    """bat 脚本应在 .env 不存在时自动复制 .env.example。"""
    bat = (ROOT / "一键启动.bat").read_text(encoding="utf-8", errors="replace")
    assert ".env.example" in bat and ".env" in bat, (
        "bat 脚本应包含自动复制 .env.example → .env 的逻辑"
    )


def test_v10110_bat_scans_multiple_python_paths():
    """bat 脚本应扫描多个常见 Python 安装路径（LocalAppData, C:\\Python*, ProgramFiles）。"""
    bat = (ROOT / "一键启动.bat").read_text(encoding="utf-8", errors="replace")
    assert "Python312" in bat or "Python311" in bat, "bat 脚本应检查常见 Python 安装路径"
    assert "LocalAppData" in bat, "bat 脚本应检查 LocalAppData 下的 Python"


def test_v10110_version_bumped():
    """版本已升级到 10.1.10。"""
    import version as v
    assert v.__version__ == "10.1.10", f"期望 10.1.10，实际 {v.__version__}"
    assert v.__codename__ == "鸿蒙始"
