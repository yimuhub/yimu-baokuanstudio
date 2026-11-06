# SPDX-License-Identifier: BUSL-1.1
"""全功能离线包验收：结构门禁 + 本地服务冒烟 + 体积下限。

CI 在打包前调用一次，防止打包链路哪天又悄悄退化成「源码壳」::

    python scripts/verify_bundle.py --platform win [--skip-binaries]

``--skip-binaries`` 用于本地结构测试（没有下载 runtime / Chromium 的真实二进制）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.build_full_bundle import MIN_ARCHIVE_MB, FACTORY_TRIAL_CREDITS, stage_for  # noqa: E402

REQUIRED_DIRS = ["core", "studio", "web", "adapters", "gateway", "app", "skills", "scripts"]
REQUIRED_PACKAGES = ["fastapi", "uvicorn", "playwright", "PIL", "yaml", "sqlalchemy"]
FORBIDDEN_PATTERNS = ["python3 -m venv", "pip install -r requirements.txt", "brew install python"]


def fail(msg: str) -> None:
    raise SystemExit(f"[验收失败] {msg}")


def check_structure(stage: Path) -> dict:
    manifest = stage / "MANIFEST.json"
    if not manifest.is_file():
        fail("缺少 MANIFEST.json")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    app = stage / "app"
    for d in REQUIRED_DIRS:
        if not (app / d).is_dir():
            fail(f"运行资源目录缺失: app/{d}（客户机启动会 ModuleNotFoundError）")
    for f in ("desktop.py", "version.py", "requirements.txt", "config.yaml"):
        if not (app / f).is_file():
            fail(f"运行文件缺失: app/{f}")
    if not (app / "scripts" / "first_run_bootstrap.py").is_file():
        fail("缺少首次启动自举脚本")
    if not (app / "core" / "browser_path.py").is_file():
        fail("缺少内置浏览器定位模块")
    if not (stage / "runtime" / "site-packages").is_dir():
        fail("缺少自带 site-packages")
    if not (stage / "chromium").is_dir():
        fail("缺少内置 Chromium 目录")

    cfg = (app / "config.yaml").read_text(encoding="utf-8")
    if "127.0.0.1:8787" in cfg:
        fail("出厂配置仍指向开发机 127.0.0.1:8787，官方通道不可用")
    if "gateway.yimu.studio" not in cfg:
        fail("出厂配置没有内置官方云端通道")

    # 配额必须是全新生成的，不能带开发机数据
    billing = json.loads((app / "data" / "billing.json").read_text(encoding="utf-8"))
    if billing.get("balance") != FACTORY_TRIAL_CREDITS or billing.get("total_consumed") != 0 or billing.get("history"):
        fail("出厂配额未重新生成（携带了开发机余额或消费记录）")
    for name in ("free_demo_calls.json", "llm_usage.json", "user_onboarding_done.json"):
        if json.loads((app / "data" / name).read_text(encoding="utf-8")) != {}:
            fail(f"出厂 {name} 携带了开发机数据")

    # 启动器与安装器里不能残留「客户机现装」
    for p in list(stage.glob("*")) + list((ROOT / "scripts").glob("build_*deb.sh")) + list((ROOT / "scripts").glob("build_macos_dmg.sh")):
        if not p.is_file() or p.suffix.lower() not in (".vbs", ".bat", ".sh", ".command"):
            continue
        # 只看可执行语句；注释里写「不再要求客户 brew install python」不该被误判
        lines = [l for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()
                 if not l.lstrip().startswith("#") and not l.lstrip().startswith("rem ")]
        text = "\n".join(lines)
        for pat in FORBIDDEN_PATTERNS:
            if pat in text:
                fail(f"{p.name} 仍含客户机安装步骤: {pat}")
    return m


def check_binaries(stage: Path, plat: str, strict: bool) -> None:
    site = stage / "runtime" / "site-packages"
    for pkg in REQUIRED_PACKAGES:
        if not any(site.glob(pkg)) and not any(site.glob(pkg + "*.dist-info")):
            fail(f"预装依赖缺失: {pkg}")
    marker = stage / "chromium" / "EXECUTABLE"
    if not marker.is_file():
        fail("缺少 chromium/EXECUTABLE 路径标记")
    exe = stage / "chromium" / marker.read_text(encoding="utf-8").strip()
    if not exe.is_file():
        fail(f"内置浏览器不存在: {exe}")
    if strict:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            fail(f"内置浏览器无法执行: {r.stderr[:200]}")


def smoke_offline(stage: Path, plat: str, strict: bool) -> None:
    """用**自带解释器**启动后端并请求 /api/version，全程只走 127.0.0.1。"""
    if not strict:
        return
    py = (stage / "runtime" / "python.exe") if plat == "win" else (stage / "runtime" / "bin" / "python3")
    if not py.is_file():
        fail(f"自带 Python 不存在: {py}")
    app = stage / "app"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(app), str(stage / "runtime" / "site-packages")])
    env["YIMU_SKIP_TRIAL_CLAIM"] = "1"  # 离线冒烟不等官方网关
    env["YIMU_DB_PATH"] = str(app / "data" / "smoke.db")
    env["PORT"] = "8899"
    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "web.admin:app", "--host", "127.0.0.1", "--port", "8899", "--log-level", "error"],
        cwd=str(app), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8899/api/version", timeout=2) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if data.get("version"):
                    print(f"[验收] 离线冒烟通过 · /api/version = {data['version']}")
                    return
            except Exception:
                if proc.poll() is not None:
                    break
                time.sleep(0.75)
        out = ""
        try:
            out = proc.communicate(timeout=2)[0] or ""
        except Exception:
            pass
        fail(f"离线冒烟失败，服务未就绪: {out[-800:]}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", choices=["win", "mac", "linux"], default="linux")
    ap.add_argument("--skip-binaries", action="store_true", help="跳过真实二进制检查与离线冒烟")
    ap.add_argument("--strict-chromium", action="store_true")
    args = ap.parse_args()
    stage = stage_for(args.platform)
    if not stage.is_dir():
        fail(f"stage 不存在: {stage}")
    m = check_structure(stage)
    if not args.skip_binaries:
        check_binaries(stage, args.platform, args.strict_chromium)
        smoke_offline(stage, args.platform, True)
        mb = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) / 1048576
        if mb < MIN_ARCHIVE_MB:
            fail(f"未压缩体积 {mb:.1f} MB 低于下限 {MIN_ARCHIVE_MB} MB")
        print(f"[验收] 体积 {mb:.1f} MB · {m['files']} 文件 · 官方凭证来源 {m['official_key_source']}")
    print("[验收] 全部通过")
    print(json.dumps(m, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
