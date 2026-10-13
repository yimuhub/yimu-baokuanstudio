"""GitHub 在线升级检测与自动热更新中枢。

功能：
1. 访问 GitHub 仓库检测最新版本与提交（结合 Git 原生网络协议与 GitHub API 双通道，彻底免除未登录 Rate Limit 限制）；
2. 比对本地当前版本（version.__version__）与远程最新提交；
3. 支持一键拉取（git pull）代码热更新；
4. 全程带有超时保护与安全防穿透，支持配置 GITHUB_TOKEN（读取私有仓库）或公开仓库检测。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from core.llm import load_env
import version

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GITHUB_REPO = "yimuhub/yimu-baokuanstudio"
_DEFAULT_UA = f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) YimuStudio/{version.__version__}"
_CACHE_TIMEOUT_SECONDS = 30  # 30 秒缓存，防频繁触发检测

_cache_check_result: dict[str, Any] | None = None
_cache_check_time: float = 0.0


def _get_github_repo() -> str:
    env = load_env()
    repo = (env.get("GITHUB_REPO") or env.get("GITHUB_UPSTREAM_REPO") or "").strip()
    if repo:
        return repo
    try:
        remote_url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(REPO_ROOT),
            text=True,
            timeout=3,
        ).strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+)(?:\.git)?", remote_url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return DEFAULT_GITHUB_REPO


def _get_github_token() -> str:
    env = load_env()
    return (
        env.get("GITHUB_TOKEN")
        or env.get("GITHUB_PERSONAL_ACCESS_TOKEN")
        or env.get("GH_TOKEN")
        or env.get("GITHUB_IMGBED_TOKEN")
        or ""
    ).strip()


def check_for_updates(force: bool = False) -> dict[str, Any]:
    """检测 GitHub 仓库是否存在最新版本。

    采用双通道策略：
    - 通道 A：Git 原生网络链路（git ls-remote，不消耗 GitHub REST API 配额，响应极速且对私有/公开仓库均有效）；
    - 通道 B：GitHub REST API（获取详细 Release Notes 与 Tag 信息）。
    """
    global _cache_check_result, _cache_check_time
    now = time.time()
    if not force and _cache_check_result and (now - _cache_check_time < _CACHE_TIMEOUT_SECONDS):
        return dict(_cache_check_result)

    cur_ver = version.__version__
    repo = _get_github_repo()
    token = _get_github_token()

    current_commit = ""
    try:
        current_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
            timeout=3,
        ).strip()[:7]
    except Exception:
        pass

    res: dict[str, Any] = {
        "ok": True,
        "current_version": cur_ver,
        "latest_version": cur_ver,
        "has_update": False,
        "repo": repo,
        "latest_commit": current_commit,
        "current_commit": current_commit,
        "commit_message": "已是最新版本",
        "published_at": "",
        "release_notes": "",
        "check_time": int(now),
        "channel": "git",
        "error": None,
    }

    # 1. 优先使用 Git 原生协议探测远端 HEAD（零 Rate Limit 风险）
    remote_head_sha = ""
    try:
        remote_target = "origin"
        if token:
            remote_target = f"https://oauth2:{token}@github.com/{repo}.git"
        ls_out = subprocess.check_output(
            ["git", "ls-remote", remote_target, "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
            timeout=8,
        )
        for line in ls_out.splitlines():
            parts = line.strip().split()
            if len(parts) >= 1:
                remote_head_sha = parts[0][:7]
                res["latest_commit"] = remote_head_sha
                break
    except Exception as exc:
        log.debug("[updater] git ls-remote 探测略过: %s", exc)

    # 2. 如果配置了 Token 或未超限，尝试通过 GitHub API 补充 Release / 提交说明
    headers = {"User-Agent": _DEFAULT_UA, "Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        # 获取最新 Release
        rel_req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers=headers,
        )
        with urllib.request.urlopen(rel_req, timeout=6) as resp:
            if resp.status == 200:
                rel_data = json.loads(resp.read().decode("utf-8"))
                tag_name = (rel_data.get("tag_name") or "").lstrip("vV").strip()
                if tag_name:
                    res["latest_version"] = tag_name
                    res["release_notes"] = rel_data.get("body") or ""
                    res["published_at"] = rel_data.get("published_at") or ""
                    res["channel"] = "release"
    except Exception:
        pass

    # 尝试获取最新 Commit Message
    try:
        cmt_req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/commits?per_page=1",
            headers=headers,
        )
        with urllib.request.urlopen(cmt_req, timeout=6) as resp:
            if resp.status == 200:
                cdata = json.loads(resp.read().decode("utf-8"))
                if cdata and isinstance(cdata, list):
                    top = cdata[0]
                    res["latest_commit"] = (top.get("sha") or "")[:7]
                    cinfo = top.get("commit") or {}
                    res["commit_message"] = (cinfo.get("message") or "").splitlines()[0]
                    if not res["published_at"]:
                        res["published_at"] = (
                            (cinfo.get("committer") or {}).get("date") or ""
                        )
                    res["channel"] = "api"
    except Exception:
        pass

    # 3. 比对更新状态
    has_update = False
    if _compare_versions(res["latest_version"], cur_ver) > 0:
        has_update = True
    elif (
        res["latest_commit"]
        and current_commit
        and res["latest_commit"] != current_commit
    ):
        has_update = True

    res["has_update"] = has_update
    _cache_check_result = dict(res)
    _cache_check_time = now
    return res


def perform_upgrade() -> dict[str, Any]:
    """执行在线代码更新同步（使用 git pull 或回退策略）。"""
    token = _get_github_token()
    repo = _get_github_repo()

    prev_commit = ""
    try:
        prev_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
            timeout=3,
        ).strip()[:7]
    except Exception:
        pass

    pull_url = f"https://github.com/{repo}.git"
    if token:
        pull_url = f"https://oauth2:{token}@github.com/{repo}.git"

    cmd = ["git", "pull", pull_url, "main"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=40,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        if token:
            output = output.replace(token, "******")

        cur_commit = prev_commit
        try:
            cur_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(REPO_ROOT),
                text=True,
                timeout=3,
            ).strip()[:7]
        except Exception:
            pass

        if proc.returncode == 0:
            global _cache_check_result
            _cache_check_result = None
            return {
                "ok": True,
                "message": "更新成功！代码已同步至最新版本。",
                "output": output,
                "previous_commit": prev_commit,
                "current_commit": cur_commit,
            }
        else:
            return {
                "ok": False,
                "message": f"Git 拉取更新失败 (退出码 {proc.returncode})",
                "output": output,
                "previous_commit": prev_commit,
                "current_commit": cur_commit,
            }
    except Exception as exc:
        log.error("[updater] 执行升级异常: %s", exc)
        return {
            "ok": False,
            "message": f"执行升级过程出现异常: {exc}",
            "output": str(exc),
            "previous_commit": prev_commit,
            "current_commit": prev_commit,
        }


def _compare_versions(v1: str, v2: str) -> int:
    """比较两个语义版本号。v1 > v2 返回 1；v1 < v2 返回 -1；相等返回 0。"""
    p1 = [int(x) for x in re.findall(r"\d+", v1 or "0")]
    p2 = [int(x) for x in re.findall(r"\d+", v2 or "0")]
    for a, b in zip(p1, p2):
        if a > b:
            return 1
        if a < b:
            return -1
    if len(p1) > len(p2):
        return 1
    if len(p1) < len(p2):
        return -1
    return 0
