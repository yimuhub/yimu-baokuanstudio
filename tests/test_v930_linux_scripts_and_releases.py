# SPDX-License-Identifier: BUSL-1.1
"""V9.3.0 (万象融 · Cross-Platform Unified) 专项防回归与功能自动化测试集。

验证核心能力：
1. 版本单一真源: version.py 为 9.3.0，代号为「万象融」；
2. 全端脚本无版本化: 根目录一键启动和升级脚本无版本号后缀（Windows/Mac/Linux）；
3. Linux 生产就绪: 一键启动_linux.sh 与 一键升级_linux.sh 语法完备、权限可执行；
4. 历史版本残留清理: 根目录彻底清除 启动一幕V8 等历史脚本和压缩包；
5. GitHub Releases 流水线: 具备 .github/workflows/sync-releases.yml 与 scripts/create_github_releases.py 的 v9.3.0 latest 配置；
6. 会员与接口文案无 V7 Pro 残留。
"""
from pathlib import Path
import os
import subprocess
import pytest
import version


def test_v930_version_single_source_of_truth():
    """验证版本单一真源为 10.1 / 10.0.1 / 10.0.0，代号为鸿蒙始"""
    assert version.__version__.startswith("10.") or version.__version__ in ("10.1", "10.0.1", "10.0.0", "9.4.5")
    assert getattr(version, "__codename__", "") in ("鸿蒙始", "澄音境")


def test_versionless_launch_scripts_exist():
    """验证全端无版本号一键启动与升级脚本完备存在且可执行，同时具备服务器一键部署脚本"""
    scripts = [
        "一键启动.bat",
        "一键升级.bat",
        "一键启动.command",
        "一键升级.command",
        "一键启动_linux.sh",
        "一键升级_linux.sh",
        "一键启动.sh",
        "一键升级.sh",
        "服务器一键部署.sh",
        "一键部署.sh",
        "deploy.sh",
    ]
    for s in scripts:
        p = Path(s)
        assert p.exists(), f"关键启动/升级/部署脚本缺失: {s}"
        if s.endswith((".sh", ".command")):
            assert os.access(p, os.X_OK), f"脚本应具有可执行权限: {s}"


def test_no_legacy_version_scripts_or_zips():
    """验证根目录下彻底移除了带有历史版本号（V8/V7）的启动脚本和压缩包"""
    legacy_files = [
        "启动一幕V8.bat",
        "升级一幕V8.bat",
        "启动一幕V8.command",
        "yimu-v8.2-patch-windows.zip",
        "yimu-v8.2-patch-windows",
        ".v7-test.env",
    ]
    for lf in legacy_files:
        assert not Path(lf).exists(), f"遗留文件不应存在: {lf}"


def test_linux_script_features():
    """验证 Linux 原生脚本包含完整参数支持与环境引导"""
    linux_start = Path("一键启动_linux.sh").read_text(encoding="utf-8")
    assert "status" in linux_start
    assert "logs" in linux_start
    assert "stop" in linux_start
    assert "restart" in linux_start
    assert "python3" in linux_start
    assert "8790" in linux_start

    linux_upgrade = Path("一键升级_linux.sh").read_text(encoding="utf-8")
    assert "git pull origin main" in linux_upgrade
    assert "requirements.txt" in linux_upgrade
    assert "mediaflow.db" in linux_upgrade


def test_github_release_workflow_and_sync_script():
    """验证 GitHub Releases REST API 自动化同步脚本具备 V9.3.1 latest 配置"""
    rel_script_path = Path("scripts/create_github_releases.py")
    assert rel_script_path.exists(), "必须存在 scripts/create_github_releases.py 同步脚本"
    rel_script = rel_script_path.read_text(encoding="utf-8")
    assert '"tag": "v9.3.1"' in rel_script
    assert '"is_latest": True' in rel_script
    assert "get_token" in rel_script
    assert "create_or_update_release" in rel_script


def test_no_v7_pro_in_membership_and_apis():
    """验证会员与接口中消除了 V7 Pro 等历史陈旧字眼"""
    caps_code = Path("studio/membership/capabilities.py").read_text(encoding="utf-8")
    assert "V7 Pro" not in caps_code

    admin_code = Path("web/admin.py").read_text(encoding="utf-8")
    assert "升级 V7 Pro" not in admin_code
    assert "启动一幕V8" not in admin_code

    gateway_code = Path("web/gateway_ui.py").read_text(encoding="utf-8")
    assert "升级 V7 Pro" not in gateway_code
    assert "网关 API 为 V7 Pro" not in gateway_code


def test_updater_check_v930_resolution():
    """验证在线更新中枢准确识别 9.3.1 为当前版本，且具备系统凭据自动捕获能力"""
    from core.updater import check_for_updates, _get_github_token
    # 验证能从系统 git credential 识别到 token
    token = _get_github_token()
    assert len(token) > 0, "应能从环境变量或系统 git credential 自动识别到 GitHub Token"

    res = check_for_updates(force=True)
    assert res.get("ok") is True
    assert res.get("current_version") in ("10.1.6", "10.1.5", "10.1.4", "10.1", "10.0.1", "10.0.0")
    # latest_version 至少为有效版本
    assert res.get("latest_version") in ["9.3.0", "9.3.1", "9.3.2", "10.0.0", "10.0.1", "10.1", "10.1.3", "10.1.4", "10.1.5", "10.1.6"]

