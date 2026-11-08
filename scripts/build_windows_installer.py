#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
"""Windows 原生安装包 (.exe) 构建器 —— 基于全功能离线 bundle。

旧版自己 ``shutil.copytree`` 只拷 5 个源码目录，还把 ``with_runtime=False`` 写死，
装出来的 exe 只是「把源码放进 Program Files」。现在统一以
``scripts/build_full_bundle.py`` 产出的 ``dist/bundle_win`` 为唯一来源：
自带 Python、预装依赖、内置 Chromium、全量资源、出厂配额全都在里面。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _ensure_utf8_stdio() -> None:
    """Windows 控制台默认 cp1252 / cp936，打印中文或 emoji 会抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_ensure_utf8_stdio()

import version  # noqa: E402
from scripts.build_full_bundle import build, stage_for  # noqa: E402

DIST_DIR = ROOT / "dist"
ISS_FILE = ROOT / "installer" / "windows" / "yimu_installer.iss"


def prepare_windows_bundle() -> Path:
    """确保 dist/bundle_win 是完整离线包；CI 里通常由 build_full_bundle 先行生成。"""
    stage = stage_for("win")
    if not (stage / "MANIFEST.json").is_file():
        print("未发现完整 bundle，先构建全功能离线包 ...")
        build("win", skip=False, pack=False)
    manifest = (stage / "MANIFEST.json").read_text(encoding="utf-8")
    if '"layout": "A2-full-offline"' not in manifest:
        raise SystemExit("dist/bundle_win 不是 A2 全功能离线包，拒绝产出只有源码的安装器")
    print(f"Windows 全功能 bundle 就绪: {stage}")
    return stage


def compile_inno_setup() -> bool:
    iscc_candidates = [
        "ISCC", "iscc",
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    iscc_bin = next((c for c in iscc_candidates if shutil.which(c) or os.path.isfile(c)), None)
    if not iscc_bin:
        print("未找到 Inno Setup 编译器 (ISCC)，跳过 .exe 产出。")
        return False
    print("正在调用 Inno Setup 编译 Windows 原生应用安装程序 (.exe) ...")
    res = subprocess.run(
        [iscc_bin, f"/DMyAppVersion={version.__version__}", str(ISS_FILE)],
        cwd=str(ISS_FILE.parent),
    )
    if res.returncode == 0:
        print(f"Windows 安装包构建成功: {DIST_DIR / f'YIMU-Studio-Windows-Setup-v{version.__version__}.exe'}")
        return True
    print("Inno Setup 编译失败。")
    return False


def main() -> None:
    prepare_windows_bundle()
    ok = compile_inno_setup()
    # Windows 上编译失败必须让构建红掉：历史上 main() 丢弃返回值，
    # 导致 .exe 根本没产出、CI 照样绿，最后发布出去的 Release 里缺安装包。
    if not ok and os.name == "nt":
        sys.exit(1)


if __name__ == "__main__":
    main()
