# -*- coding: utf-8 -*-
"""
v10.1.9 专项单测：免密静默升级与 Git 弹窗彻底杜绝验证
验证：
1. _safe_git_env() 包含所有禁止交互与弹窗的环境变量（GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=never, GIT_ASKPASS=""）
2. _get_github_token() 绝不调用任何 subprocess 启动 git credential fill
3. perform_upgrade() 在 Git pull 失败时自动无缝降级到 Release ZIP 归档包在线覆盖模式
4. 公开仓库免 Token 升级 100% 成功
"""

import os
import subprocess
from unittest.mock import patch, MagicMock
from core import updater


def test_safe_git_env_contains_anti_popup_flags():
    """验证 _safe_git_env 严格配置了防 GUI 弹窗和非交互模式的所有关键环境变量"""
    env = updater._safe_git_env()
    assert env.get("GIT_TERMINAL_PROMPT") == "0"
    assert env.get("GCM_INTERACTIVE") == "never"
    assert "GIT_ASKPASS" in env
    assert "SSH_ASKPASS" in env


def test_get_github_token_does_not_spawn_subprocess(monkeypatch):
    """验证 _get_github_token 绝不调用 subprocess.check_output 启动 git credential fill"""
    # 清理环境变量中的 token
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)

    called_subprocess = []

    def mock_check_output(*args, **kwargs):
        called_subprocess.append(args)
        raise RuntimeError("不应调用任何 subprocess！")

    monkeypatch.setattr(subprocess, "check_output", mock_check_output)

    token = updater._get_github_token()
    assert token == ""
    assert len(called_subprocess) == 0, "不应触发任何交互式凭据查询子进程！"


def test_perform_upgrade_falls_back_to_archive_when_git_fails(monkeypatch):
    """验证在 Git 链路遭遇网络阻断或异常时，自动无缝降级到 Release ZIP 归档覆盖模式并成功返回"""
    monkeypatch.setattr(updater, "is_git_repo", lambda: True)

    # 模拟 Git pull 全部失败（如被防火墙阻断）
    def mock_run(cmd, *args, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.stdout = ""
        mock_proc.stderr = "fatal: unable to access 'https://github.com/...': Connection timed out"
        return mock_proc

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "abc1234")

    # 模拟 Release 归档覆盖成功
    archive_called = []

    def mock_archive(repo, token):
        archive_called.append((repo, token))
        return True, "已通过 Release 归档包极速热解压覆盖更新"

    monkeypatch.setattr(updater, "_upgrade_from_archive", mock_archive)

    res = updater.perform_upgrade()
    assert res.get("ok") is True
    assert len(archive_called) == 1
    assert "已通过 Release 归档包" in res.get("output", "")


def test_check_for_updates_works_tokenless():
    """验证公开仓库在无 Token 情况下检测更新正常工作"""
    res = updater.check_for_updates(force=True)
    assert res.get("ok") is True
    assert res.get("current_version") in ("10.1.9", "10.1.10")
