# SPDX-License-Identifier: BUSL-1.1
"""全功能离线桌面分发包构建器（A2 完全自给 / Zero-touch Installer）。

与旧 ``build_desktop_client.py`` 的根本区别
-------------------------------------------
旧脚本只复制源码，客户机上现装 Python、现跑 pip、现找浏览器，甚至漏掉
``gateway/`` ``app/`` ``skills/`` ``config.yaml`` —— 装完连服务都起不来。
本构建器把**全部运行条件**在构建机一次装好：

  ``runtime/``   可重定位 Python 3.11 + site-packages（全量依赖，含 pywebview）
  ``chromium/``  Chrome for Testing（窗口与 Playwright 共用，客户机无需装浏览器）
  ``app/``       全量源码与资源（含 gateway / app / skills / config.yaml）
  ``app/data/``  **重新生成**的出厂配额，不携带开发机的余额与测试用户
  启动器         直接 exec 自带解释器，没有任何 venv / pip / brew 步骤

布局（``app/`` 必须作为源码根，因为 core/llm.py 的 BASE = app/）::

    <stage>/
      app/  runtime/  chromium/  MANIFEST.json  一幕桌面客户端.*

用法::

    python scripts/build_full_bundle.py --platform win|mac|linux [--skip-download]

``--skip-download`` 只生成结构与清单，用于本地门禁测试；CI 必须完整下载。
官方凭证由环境变量 ``YIMU_OFFICIAL_BOOTSTRAP_KEY``（GitHub Secrets）在构建期注入，
仓库里绝不保存可扣费的真实 Key；未注入时运行时会向官方网关申领设备试用凭证。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DIST = ROOT / "dist"
#: 三平台应用图标（由 web/static/img/logo-master.png 裁出纯图形生成）
ICON_DIR = ROOT / "installer" / "icons"

import version  # noqa: E402

#: 全量运行资源。旧脚本只带前 5 个，导致 gateway/app/skills/config.yaml 缺失。
INCLUDE_DIRS = [
    "core", "studio", "web", "adapters", "docs",
    "gateway", "app", "domain", "infra", "scripts", "skills", "installer",
]
INCLUDE_FILES = [
    "desktop.py", "version.py", "pyproject.toml", "requirements.txt",
    "config.yaml", ".env.example", "README.md", "README_EN.md",
]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store", ".pytest_cache", "*.log")

OFFICIAL_GATEWAY = "https://gateway.yimu.studio/v1"
PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
PBS_RELEASES = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
CFT_JSON = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"

#: 出厂赠送额度（重新生成配额，不复制开发机 billing.json 的 999999 与测试记录）
FACTORY_TRIAL_CREDITS = 200000
#: 全功能包压缩后体积下限（MB）。低于此值说明又退化成源码壳，CI 直接失败。
MIN_ARCHIVE_MB = 90
UA = {"User-Agent": "YIMU-Studio-Builder/13.0"}


def ensure_dir(p: Path) -> None:
    """某些托管环境的 sitecustomize 会劫持 Path.mkdir 并忽略 exist_ok，显式判存在最稳。"""
    if not p.is_dir():
        p.mkdir(parents=True)


def log(msg: str) -> None:
    print(f"[FullBundle] {msg}", flush=True)


def stage_for(plat: str) -> Path:
    return DIST / {"win": "bundle_win", "mac": "bundle_mac", "linux": "bundle_linux"}[plat]


def _download(url: str, dest: Path, timeout: int = 180) -> Path:
    ensure_dir(dest.parent)
    if dest.exists() and dest.stat().st_size > 1024:
        log(f"复用缓存 {dest.name}")
        return dest
    log(f"下载 {url}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)
    return dest


def _get_json(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# 1. 源码与资源
# ---------------------------------------------------------------------------

def copy_sources(stage: Path) -> None:
    app = stage / "app"
    ensure_dir(app)
    for d in INCLUDE_DIRS:
        src = ROOT / d
        if src.is_dir():
            shutil.copytree(src, app / d, ignore=IGNORE, dirs_exist_ok=True)
    for f in INCLUDE_FILES:
        src = ROOT / f
        if src.is_file():
            shutil.copy2(src, app / f)
    for sub in ("data/topics", "data/drafts", "data/cards", "logs", "runs"):
        ensure_dir(app / sub)
    log("全量源码与资源已复制（含 gateway / app / skills / config.yaml）")


def copy_app_icons(stage: Path) -> None:
    """把应用图标放进 app/web/static/img，供 Windows 快捷方式 / 便携包 / 窗口图标引用。

    图标真源在 installer/icons/：AppIcon.icns（macOS）、app.ico（Windows，含 256px）、
    hicolor/*（Linux）。macOS 的 .app 另外使用自己的 Contents/Resources/AppIcon.icns。
    """
    dst = stage / "app" / "web" / "static" / "img"
    ensure_dir(dst)
    copied = []
    for name in ("AppIcon.icns", "app.ico", "icon-1024.png"):
        src = ICON_DIR / name
        if src.is_file():
            shutil.copy2(src, dst / name)
            copied.append(name)
    if not copied:
        log("⚠️ 未找到 installer/icons 下的应用图标，安装器图标将保持空白")
        return
    log("应用图标已注入: " + ", ".join(copied))


def write_factory_config(stage: Path) -> None:
    """生成出厂配置：官方通道指向云端网关，而不是开发机的 127.0.0.1:8787。"""
    import yaml
    cfg_path = stage / "app" / "config.yaml"
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    gw = cfg.setdefault("gateway", {})
    if not isinstance(gw, dict):
        gw = {}
        cfg["gateway"] = gw
    gw["provider_id"] = "yimu_official"
    gw["base_url"] = OFFICIAL_GATEWAY
    providers = gw.get("providers") or {}
    if not isinstance(providers, dict):
        providers = {}
    official = providers.get("yimu_official") or {}
    if not isinstance(official, dict):
        official = {}
    official["base_url"] = OFFICIAL_GATEWAY
    official["name"] = "一幕·YIMU 官方（内置云端通道）"
    official["model"] = official.get("model") or "yimu-chat"
    providers["yimu_official"] = official
    gw["providers"] = providers
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    log("出厂配置已生成：官方通道 → gateway.yimu.studio")


def reset_factory_quota(stage: Path) -> None:
    """重新生成配额：干净余额、空消费记录、空体验次数，不带任何开发数据。"""
    data = stage / "app" / "data"
    files = {
        "billing.json": {
            "tier": "free",
            "balance": FACTORY_TRIAL_CREDITS,
            "total_consumed": 0,
            "history": [],
            "cdkeys": {},
        },
        "free_demo_calls.json": {},
        "llm_usage.json": {},
        "user_onboarding_done.json": {},
        "video_model_rules.json": {},
    }
    for name, value in files.items():
        (data / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"出厂配额已重新生成（free / {FACTORY_TRIAL_CREDITS} 额度 / 零历史）")


def inject_official_key(stage: Path) -> str:
    """构建期从环境变量注入官方凭证。仓库里永远不存真实 Key。"""
    key = os.environ.get("YIMU_OFFICIAL_BOOTSTRAP_KEY", "").strip()
    if not key:
        return "trial-claim"
    p = stage / "app" / ".bootstrap"
    ensure_dir(p)
    f = p / "official_key"
    f.write_text(key, encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except Exception:
        pass
    log("官方凭证已随包注入（来自构建期 Secrets）")
    return "ci-secret"


# ---------------------------------------------------------------------------
# 2. 自带 Python runtime + 全量依赖
# ---------------------------------------------------------------------------

def _triple(plat: str) -> str:
    if plat == "mac":
        return "aarch64-apple-darwin" if platform.machine() == "arm64" else "x86_64-apple-darwin"
    return "x86_64-unknown-linux-gnu"


def setup_runtime(stage: Path, plat: str, skip: bool) -> dict:
    runtime = stage / "runtime"
    site = runtime / "site-packages"
    ensure_dir(site)
    info = {"platform": plat, "python": "3.11.9", "site_packages": "runtime/site-packages", "deps": "skipped" if skip else "installed"}
    if skip:
        (site / ".keep").write_text("", encoding="utf-8")
        return info

    if plat == "win":
        z = _download(PYTHON_EMBED_URL, DIST / "cache" / "python-3.11.9-embed-amd64.zip")
        with zipfile.ZipFile(z) as zf:
            zf.extractall(runtime)
        for pth in runtime.glob("*._pth"):
            lines = [x for x in pth.read_text(encoding="utf-8").splitlines() if x.strip() != "#import site"]
            lines.insert(0, "import site")
            for extra in ("Lib/site-packages", "../runtime/site-packages", "../app"):
                if extra not in lines:
                    lines.append(extra)
            pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
        gp = _download(GET_PIP_URL, DIST / "cache" / "get-pip.py")
        subprocess.run([str(runtime / "python.exe"), str(gp), "--no-warn-script-location"], check=True)
        py = runtime / "python.exe"
    else:
        rel = _get_json(PBS_RELEASES)
        triple = _triple(plat)
        asset = next(
            (a for a in rel.get("assets", [])
             if a["name"].startswith("cpython-3.11.") and triple in a["name"] and "install_only.tar.gz" in a["name"]),
            None,
        )
        if not asset:
            raise RuntimeError(f"未找到 {triple} 的 Python 3.11 install_only 构建产物")
        arc = _download(asset["browser_download_url"], DIST / "cache" / asset["name"])
        # 解压到 dist/cache 而非 stage 内：既不触发批量删除保护，也不会被打进分发包
        tmp = DIST / "cache" / f"pbs_{plat}_{os.getpid()}"
        ensure_dir(tmp)
        with tarfile.open(arc) as tf:
            tf.extractall(tmp)
        inner = tmp / "python"
        if not inner.is_dir():
            raise RuntimeError("python-build-standalone 解压结构异常")
        for item in inner.iterdir():
            dest = runtime / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        py = next(p for p in (runtime / "bin" / "python3", runtime / "bin" / "python") if p.exists())
        try:
            py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass

    info["executable"] = str(py.relative_to(stage))
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    reqs = [r.split("#")[0].strip() for r in reqs if r.strip() and not r.strip().startswith("#")]
    reqs.append("pywebview")
    log("预装全量依赖到 runtime/site-packages ...")
    cmd = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
           "--target", str(site), *reqs]
    subprocess.run(cmd, check=True)
    info["deps"] = "installed"
    info["package_count"] = len(reqs)
    return info


# ---------------------------------------------------------------------------
# 3. 内置 Chromium（窗口 + Playwright 共用）
# ---------------------------------------------------------------------------

def setup_chromium(stage: Path, plat: str, skip: bool) -> dict:
    out = stage / "chromium"
    ensure_dir(out)
    info = {"platform": plat, "bundled": not skip}
    if skip:
        return info
    want = {"win": "win64", "linux": "linux64"}.get(plat)
    if plat == "mac":
        want = "mac-arm64" if platform.machine() == "arm64" else "mac-x64"
    meta = _get_json(CFT_JSON)
    downloads = (meta.get("channels", {}).get("Stable", {}).get("downloads", {}).get("chrome", []))
    entry = next((d for d in downloads if d.get("platform") == want), None)
    if not entry:
        raise RuntimeError(f"Chrome for Testing 没有 {want} 的下载项")
    info["version"] = meta["channels"]["Stable"]["version"]
    z = _download(entry["url"], DIST / "cache" / f"chrome-{want}.zip", timeout=300)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(out)
    rel = {
        "win64": "chrome-win64/chrome.exe",
        "linux64": "chrome-linux64/chrome",
        "mac-arm64": "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "mac-x64": "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    }[want]
    exe = out / rel
    if not exe.is_file():
        raise RuntimeError(f"内置浏览器可执行文件缺失: {exe}")
    try:
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass
    (out / "EXECUTABLE").write_text(rel, encoding="utf-8")
    info["executable"] = "chromium/" + rel
    log(f"内置 Chrome for Testing {info['version']} 就绪")
    return info


# ---------------------------------------------------------------------------
# 4. 启动器（只有自带解释器一条路径，不存在任何客户机安装步骤）
# ---------------------------------------------------------------------------

def write_launchers(stage: Path, plat: str) -> None:
    if plat == "win":
        # V15.8: window style 0 (SW_HIDE) hid the pywebview main window and
        # pythonw.exe has no stdout. Use 1 + launcher shim + UTF-8 env.
        vbs = '''Option Explicit
' YIMU Studio desktop launcher. ASCII-only + CRLF + no BOM for WSH ANSI parsing.
Dim WshShell, fso, root, pyExe, launcher
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
WshShell.Environment("PROCESS")("PYTHONUTF8") = "1"
pyExe = root & "\\runtime\\pythonw.exe"
If Not fso.FileExists(pyExe) Then pyExe = root & "\\runtime\\python.exe"
WshShell.CurrentDirectory = root & "\\app"
launcher = root & "\\app\\launch_desktop.py"
If Not fso.FileExists(launcher) Then launcher = root & "\\app\\desktop.py"
WshShell.Run """" & pyExe & """ """ & launcher & """", 1, False
'''
        (stage / "一幕桌面客户端.vbs").write_bytes(vbs.replace("\n", "\r\n").encode("ascii"))
        (stage / "一键启动.bat").write_text('''@echo off
chcp 65001 >nul 2>nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0app"
if exist "%~dp0app\\launch_desktop.py" (
  "%~dp0runtime\\python.exe" "%~dp0app\\launch_desktop.py"
) else (
  "%~dp0runtime\\python.exe" "%~dp0app\\desktop.py"
)
pause
''', encoding="utf-8")
    else:
        script = '''#!/bin/bash
# 全功能离线包启动器：直接 exec 自带 Python，无需系统 Python / venv / pip
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/app" || exit 1
if [ -f "$ROOT/app/launch_desktop.py" ]; then
  exec "$ROOT/runtime/bin/python3" "$ROOT/app/launch_desktop.py" "$@"
fi
exec "$ROOT/runtime/bin/python3" "$ROOT/app/desktop.py" "$@"
'''
        name = "一幕桌面客户端.command" if plat == "mac" else "一幕桌面客户端.sh"
        p = stage / name
        p.write_text(script, encoding="utf-8")
        p.chmod(0o755)
        (stage / "一幕桌面客户端.desktop").write_text(f'''[Desktop Entry]
Type=Application
Name=一幕·YIMU 爆款工作室
Exec={stage / name}
Terminal=false
Categories=AudioVideo;Development;
''', encoding="utf-8")
    (stage / "使用说明.txt").write_text(f'''一幕·YIMU 爆款工作室 V{version.__version__} · 全功能离线包

双击「一幕桌面客户端」即可启动。本包已内置：
  · Python 3.11 运行时与全部依赖（无需安装 Python、无需联网 pip）
  · 浏览器内核（无需安装 Chrome / Edge）
  · 全量功能资源与技能库
  · 官方云端通道与出厂赠送额度

首次启动会自动生成本地配置与管理员口令（保存在用户数据目录的 secrets.env，
权限 0600；安装目录内不再明文存放任何密钥）。
如需使用自己的 API Key，在「设置 → 模型服务 / 我的凭证」中添加即可，
删除自定义凭证后会自动切回官方通道。
''', encoding="utf-8")


def write_manifest(stage: Path, plat: str, runtime: dict, chromium: dict, key_source: str) -> dict:
    files = [p for p in stage.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    m = {
        "product": "YIMU Studio",
        "version": version.__version__,
        "codename": version.__codename__,
        "platform": plat,
        "layout": "A2-full-offline",
        "files": len(files),
        "bytes_uncompressed": total,
        "runtime": runtime,
        "chromium": chromium,
        "official_key_source": key_source,
        "factory_credits": FACTORY_TRIAL_CREDITS,
        "min_archive_mb": MIN_ARCHIVE_MB,
        "checksum": hashlib.sha256(
            "|".join(sorted(str(p.relative_to(stage)) for p in files)).encode("utf-8")
        ).hexdigest()[:16],
    }
    (stage / "MANIFEST.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return m


def pack_archive(stage: Path, plat: str) -> Path:
    ver = version.__version__
    name = f"YIMU-Studio-{ {'win':'Windows','mac':'macOS','linux':'Linux'}[plat] }-Full-v{ver}"
    if plat == "win":
        out = DIST / f"{name}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in stage.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=str(Path(name) / f.relative_to(stage)))
    else:
        out = DIST / f"{name}.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            tf.add(stage, arcname=name)
    mb = out.stat().st_size / 1048576
    log(f"便携包完成: {out.name} ({mb:.1f} MB)")
    if mb < MIN_ARCHIVE_MB:
        raise RuntimeError(f"包体积 {mb:.1f} MB 低于下限 {MIN_ARCHIVE_MB} MB，疑似退化成源码壳")
    return out


def build(plat: str, skip: bool = False, pack: bool = True, fresh: bool = False) -> dict:
    ensure_dir(DIST)
    stage = stage_for(plat)
    # 默认覆盖式重建（幂等），避免删除上千文件触发托管环境的批量删除保护；
    # CI 使用全新 runner，本来就没有旧 stage；需要严格干净构建时传 --fresh。
    if fresh and stage.exists():
        shutil.rmtree(stage)
    ensure_dir(stage)
    log(f"开始构建 {plat} 全功能离线包 (V{version.__version__})")

    copy_sources(stage)
    copy_app_icons(stage)
    write_factory_config(stage)
    reset_factory_quota(stage)
    key_source = inject_official_key(stage)
    runtime = setup_runtime(stage, plat, skip)
    chromium = setup_chromium(stage, plat, skip)
    write_launchers(stage, plat)
    manifest = write_manifest(stage, plat, runtime, chromium, key_source)

    if pack and not skip:
        manifest["archive"] = str(pack_archive(stage, plat))
        (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"完成: {stage} · {manifest['files']} 个文件")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="一幕 Studio 全功能离线桌面分发包构建器")
    ap.add_argument("--platform", choices=["win", "mac", "linux", "all"], default="all")
    ap.add_argument("--skip-download", action="store_true", help="只生成结构（本地门禁测试用）")
    ap.add_argument("--no-pack", action="store_true", help="不生成便携包，由安装器脚本负责")
    ap.add_argument("--fresh", action="store_true", help="先清空旧 stage 再构建（需允许批量删除）")
    args = ap.parse_args()
    plats = ["win", "mac", "linux"] if args.platform == "all" else [args.platform]
    for p in plats:
        build(p, skip=args.skip_download, pack=not args.no_pack, fresh=args.fresh)


if __name__ == "__main__":
    main()
