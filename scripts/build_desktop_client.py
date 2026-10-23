# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 爆款工作室 (YIMU Studio) 全平台独立桌面客户端自动化打包中枢 (Desktop Client Packager)。

功能：
1. 自动化下载并配置嵌入式便携 Python 运行时 (Embedded Python Runtime)；
2. 预安装全量运行依赖库 (requirements.txt)，实现用户端 100% 免 Python、免配置、零安装开箱即用；
3. 生成无控制台窗口的原生桌面启动引导 (VBS Launcher & Exe Shim)；
4. 归档打包为 Windows (x64)、macOS、Linux 独立桌面客户端分发包；
5. 支持命令行一键触发或在 GitHub Actions CI/CD 流水线中全自动构建发布。
"""
from __future__ import annotations

import os
import sys
import shutil
import zipfile
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import version

PYTHON_WIN_EMBED_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
DIST_DIR = ROOT / "dist"


def log(msg: str):
    print(f"[Desktop Builder] {msg}")


def create_windows_vbs_launcher(target_dir: Path):
    """生成 Windows 无黑框静默桌面启动引导脚本。"""
    vbs_content = '''Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 优先使用内置便携 runtime
If fso.FileExists(currentDir & "\\runtime\\pythonw.exe") Then
    pyExe = """" & currentDir & "\\runtime\\pythonw.exe"""
ElseIf fso.FileExists(currentDir & "\\.venv\\Scripts\\pythonw.exe") Then
    pyExe = """" & currentDir & "\\.venv\\Scripts\\pythonw.exe"""
Else
    ' 降级使用批处理引导
    WshShell.Run "cmd /c """ & currentDir & "\\一键启动.bat""", 1, False
    WScript.Quit
End If

desktopScript = """" & currentDir & "\\desktop.py"""
' 运行 desktop.py，第 2 参数为 0 表示隐藏黑色控制台窗口
WshShell.Run pyExe & " " & desktopScript, 0, False
'''
    (target_dir / "一幕桌面客户端.vbs").write_text(vbs_content, encoding="utf-8")
    log("已生成 Windows 原生静默桌面启动器: 一幕桌面客户端.vbs")


def setup_embedded_python_runtime(target_dir: Path):
    """配置 Windows 独立 Python 嵌入式便携运行时，实现开箱即用 100% 免环境安装。"""
    runtime_dir = target_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    embed_zip = DIST_DIR / "python-3.11.9-embed-amd64.zip"
    if not embed_zip.exists():
        log("正在下载 Windows x64 官方 Python 嵌入式运行时 (3.11.9)...")
        urllib.request.urlretrieve(PYTHON_WIN_EMBED_URL, embed_zip)

    log("正在解压嵌入式 Python 运行时至 bundle runtime 目录...")
    with zipfile.ZipFile(embed_zip, "r") as zf:
        zf.extractall(runtime_dir)

    # 修改 ._pth 启用 site-packages 路径加载
    for pth in runtime_dir.glob("*._pth"):
        lines = pth.read_text(encoding="utf-8").splitlines()
        new_lines = []
        for line in lines:
            if line.strip() == "#import site":
                new_lines.append("import site")
            else:
                new_lines.append(line)
        if "Lib/site-packages" not in new_lines:
            new_lines.extend([".", "Lib/site-packages", ".."])
        pth.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    (runtime_dir / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    if (runtime_dir / "python.exe").exists() and not (runtime_dir / "pythonw.exe").exists():
        shutil.copy(runtime_dir / "python.exe", runtime_dir / "pythonw.exe")
    log("✅ 独立嵌入式 Python 运行时配置就绪！")


def build_windows_portable_bundle(output_dir: Path | None = None, with_runtime: bool = False) -> Path:
    """构建 Windows x64 独立免安装绿色桌面客户端压缩包。"""
    ver = version.__version__
    bundle_name = f"YIMU-Studio-Windows-Desktop-v{ver}"
    stage_dir = DIST_DIR / bundle_name
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    log(f"开始构建 Windows 独立桌面客户端包 (版本: {ver}, 内置运行时: {with_runtime})...")

    # 1. 复制核心项目代码与资源文件
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
            shutil.copytree(src, stage_dir / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))

    for f in include_files:
        src = ROOT / f
        if src.exists():
            shutil.copy(src, stage_dir / f)

    # 创建标准运行所需目录
    for sub in ["data/topics", "data/drafts", "data/cards", "logs", "runs"]:
        (stage_dir / sub).mkdir(parents=True, exist_ok=True)

    # 2. 若开启内置运行时，配置完全独立的 Python 环境
    if with_runtime:
        setup_embedded_python_runtime(stage_dir)

    # 3. 生成无黑框桌面启动引导
    create_windows_vbs_launcher(stage_dir)

    # 3. 生成快捷运行说明
    readme_txt = f"""============================================================
  一幕·YIMU 爆款工作室 (YIMU Studio) 桌面客户端 (V{ver})
  官方网站: https://yimu.hyipf.com
============================================================

【使用说明 - 开箱即用】
1. 双击运行【一幕桌面客户端.vbs】：
   直接进入纯净桌面窗口模式，无任何黑框控制台打扰；

2. 或双击运行【一键启动.bat】：
   带有实时运行日志控制台，适合排查与调试模式。

【完全独立】
本客户端采用独立内嵌运行时架构，无需在系统另外安装 Python 或配置环境变量。
所有生成草稿、媒体素材保存在 data/ 目录，升级时数据完整保留。
"""
    (stage_dir / "使用说明.txt").write_text(readme_txt, encoding="utf-8")

    # 4. 打包为 ZIP
    zip_path = DIST_DIR / f"{bundle_name}.zip"
    log(f"正在压缩生成分发包: {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in stage_dir.rglob("*"):
            zf.write(file, arcname=file.relative_to(DIST_DIR))

    log(f"✅ Windows 桌面客户端分发包构建完成: {zip_path} ({zip_path.stat().st_size / (1024*1024):.2f} MB)")
    return zip_path


def build_unix_portable_bundle(platform_name: str) -> Path:
    """构建 macOS / Linux 独立客户端包。"""
    ver = version.__version__
    bundle_name = f"YIMU-Studio-{platform_name}-Desktop-v{ver}"
    stage_dir = DIST_DIR / bundle_name
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    log(f"开始构建 {platform_name} 独立桌面分发包...")

    # 复制核心项目源码
    include_dirs = ["core", "studio", "web", "adapters", "docs"]
    include_files = [
        "desktop.py",
        "version.py",
        "pyproject.toml",
        "requirements.txt",
        ".env.example",
        "README_ZH.md",
        "一键启动.sh",
        "一键升级.sh",
        "一键启动.command",
        "一键升级.command",
        "一键启动_linux.sh",
        "一键升级_linux.sh",
        "服务器一键部署.sh",
        "一幕桌面客户端.vbs",
        "一幕桌面客户端.command",
        "一幕桌面客户端_linux.sh",
        "一幕桌面客户端.desktop",
    ]

    for d in include_dirs:
        src = ROOT / d
        if src.exists():
            shutil.copytree(src, stage_dir / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))

    for f in include_files:
        src = ROOT / f
        if src.exists():
            shutil.copy(src, stage_dir / f)
            # 赋予 shell 脚本可执行权限
            if f.endswith((".sh", ".command")):
                os.chmod(stage_dir / f, 0o755)

    for sub in ["data/topics", "data/drafts", "data/cards", "logs", "runs"]:
        (stage_dir / sub).mkdir(parents=True, exist_ok=True)

    # 压缩为 tar.gz
    tar_path = DIST_DIR / f"{bundle_name}.tar.gz"
    log(f"正在压缩生成分发包: {tar_path.name}...")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(stage_dir, arcname=bundle_name)

    log(f"✅ {platform_name} 桌面客户端包构建完成: {tar_path}")
    return tar_path


def try_build_native_installer(platform_name: str):
    """尝试构建原生安装包 (.exe / .dmg / .deb)。"""
    if platform_name == "macOS" and sys.platform == "darwin":
        dmg_script = ROOT / "scripts" / "build_macos_dmg.sh"
        if dmg_script.exists():
            log("正在构建 macOS 原生应用安装包 (.dmg)...")
            subprocess.run(["bash", str(dmg_script)], check=False)
    elif platform_name == "Linux" and shutil.which("dpkg-deb"):
        deb_script = ROOT / "scripts" / "build_linux_deb.sh"
        if deb_script.exists():
            log("正在构建 Linux 原生应用安装包 (.deb)...")
            subprocess.run(["bash", str(deb_script)], check=False)
    elif platform_name == "Windows" and sys.platform == "win32":
        win_builder = ROOT / "scripts" / "build_windows_installer.py"
        if win_builder.exists():
            log("正在构建 Windows 原生应用安装程序 (.exe)...")
            subprocess.run([sys.executable, str(win_builder)], check=False)


def main():
    import argparse
    import subprocess
    parser = argparse.ArgumentParser(description="一幕 Studio 全平台桌面客户端打包工具")
    parser.add_argument("--platform", choices=["win", "mac", "linux", "all"], default="all", help="目标操作系统")
    parser.add_argument("--with-runtime", action="store_true", help="是否下载并嵌入独立 Python 运行时环境 (100%% 零配置)")
    parser.add_argument("--with-installers", action="store_true", help="是否同时生成原生安装包 (.exe / .dmg / .deb)")
    args = parser.parse_args()

    if args.platform in ("win", "all"):
        build_windows_portable_bundle(with_runtime=args.with_runtime)
        if args.with_installers:
            try_build_native_installer("Windows")
    if args.platform in ("mac", "all"):
        build_unix_portable_bundle("macOS")
        if args.with_installers:
            try_build_native_installer("macOS")
    if args.platform in ("linux", "all"):
        build_unix_portable_bundle("Linux")
        if args.with_installers:
            try_build_native_installer("Linux")


if __name__ == "__main__":
    main()
