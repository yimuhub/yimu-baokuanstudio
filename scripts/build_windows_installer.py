#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
"""Windows 原生应用安装包 (.exe) 自动化构建器。

功能：
1. 准备 Windows 分发文件与嵌入式 Python 运行时目录 (dist/bundle_win)；
2. 调度 Inno Setup (ISCC) 将其编译为专业的现代化 Windows 单文件安装包 (Setup.exe)；
3. 支持本地 Windows 环境与 GitHub Actions CI/CD 流水线无缝执行。
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import version
from scripts.build_desktop_client import setup_embedded_python_runtime

DIST_DIR = ROOT / "dist"
BUNDLE_WIN = DIST_DIR / "bundle_win"
ISS_FILE = ROOT / "installer" / "windows" / "yimu_installer.iss"


def prepare_windows_bundle(with_runtime: bool = True):
    """准备 Windows 独立运行包。"""
    print(f"📦 正在准备 Windows 安装包资源 (版本: {version.__version__})...")
    if BUNDLE_WIN.exists():
        shutil.rmtree(BUNDLE_WIN)
    BUNDLE_WIN.mkdir(parents=True)

    include_dirs = ["core", "studio", "web", "adapters", "docs"]
    include_files = [
        "desktop.py",
        "version.py",
        "pyproject.toml",
        "requirements.txt",
        ".env.example",
        "README_ZH.md",
        "一键启动.bat",
        "一键升级.bat",
        "一幕桌面客户端.vbs",
    ]

    for d in include_dirs:
        src = ROOT / d
        if src.exists():
            shutil.copytree(src, BUNDLE_WIN / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))

    for f in include_files:
        src = ROOT / f
        if src.exists():
            shutil.copy(src, BUNDLE_WIN / f)

    for sub in ["data/topics", "data/drafts", "data/cards", "logs", "runs"]:
        (BUNDLE_WIN / sub).mkdir(parents=True, exist_ok=True)

    if with_runtime:
        try:
            setup_embedded_python_runtime(BUNDLE_WIN)
        except Exception as e:
            print(f"⚠️ 下载内嵌运行时提示: {e}，跳过直接打包代码。")

    print(f"✅ Windows bundle 准备就绪: {BUNDLE_WIN}")


def compile_inno_setup():
    """调用 ISCC 编译 Inno Setup 脚本生成 setup .exe。"""
    iscc_candidates = [
        "ISCC",
        "iscc",
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    iscc_bin = None
    for cand in iscc_candidates:
        if shutil.which(cand) or (os.path.exists(cand) and os.path.isfile(cand)):
            iscc_bin = cand
            break

    if not iscc_bin:
        print("⚠️ 未找到 Inno Setup 编译器 (ISCC)。")
        print("💡 在 Windows 环境下请安装 Inno Setup 6 (https://jrsoftware.org/isdl.php)，或在 GitHub Actions CI 中自动编译。")
        return False

    print(f"🔨 正在调用 Inno Setup 编译 Windows 原生应用安装程序 (.exe)...")
    res = subprocess.run([iscc_bin, str(ISS_FILE)], cwd=str(ISS_FILE.parent))
    if res.returncode == 0:
        exe_path = DIST_DIR / f"YIMU-Studio-Windows-Setup-v{version.__version__}.exe"
        print(f"🎉 Windows 安装包构建成功: {exe_path}")
        return True
    else:
        print("❌ Inno Setup 编译失败。")
        return False


def main():
    prepare_windows_bundle(with_runtime=False)
    compile_inno_setup()


if __name__ == "__main__":
    main()
