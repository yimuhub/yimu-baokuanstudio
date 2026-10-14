"""GitHub 在线升级检测与自动热更新中枢。

功能：
1. 访问 GitHub 仓库检测最新版本与提交（结合 Git 原生网络协议与 GitHub API 双通道，彻底免除未登录 Rate Limit 限制）；
2. 比对本地当前版本（version.__version__）与远程最新提交；
3. 支持一键拉取（git pull）代码热更新（自动暂存并恢复用户本地 config.yaml 配置，杜绝合并冲突）；
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
    token = (
        env.get("GITHUB_TOKEN")
        or env.get("GITHUB_PERSONAL_ACCESS_TOKEN")
        or env.get("GH_TOKEN")
        or env.get("GITHUB_IMGBED_TOKEN")
        or ""
    ).strip()
    if token:
        return token
    try:
        auth_out = subprocess.check_output(
            ["git", "credential", "fill"],
            input=f"url=https://github.com/{_get_github_repo()}.git\n",
            text=True,
            timeout=3,
        )
        for line in auth_out.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def check_for_updates(force: bool = False) -> dict[str, Any]:
    """检测 GitHub 仓库是否存在最新版本。"""
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

    remote_target = "origin"
    if token:
        remote_target = f"https://oauth2:{token}@github.com/{repo}.git"

    try:
        ls_out = subprocess.check_output(
            ["git", "ls-remote", remote_target, "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
            timeout=8,
        )
        for line in ls_out.splitlines():
            parts = line.strip().split()
            if len(parts) >= 1:
                res["latest_commit"] = parts[0][:7]
                break

        ls_tags = subprocess.check_output(
            ["git", "ls-remote", "--tags", remote_target],
            cwd=str(REPO_ROOT),
            text=True,
            timeout=8,
        )
        found_tags: list[str] = []
        for line in ls_tags.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1].startswith("refs/tags/"):
                raw_tag = parts[1].replace("refs/tags/", "").replace("^{}", "").strip()
                v_clean = raw_tag.lstrip("vV").strip()
                if v_clean and any(c.isdigit() for c in v_clean):
                    found_tags.append(v_clean)
        if found_tags:
            found_tags.sort(key=lambda x: [int(n) for n in re.findall(r"\d+", x) or [0]])
            res["latest_version"] = found_tags[-1]
    except Exception as exc:
        log.debug("[updater] git ls-remote 探测略过: %s", exc)

    headers = {"User-Agent": _DEFAULT_UA, "Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        rel_data: dict[str, Any] = {}
        try:
            rel_req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/releases/latest",
                headers=headers,
            )
            with urllib.request.urlopen(rel_req, timeout=6) as resp:
                if resp.status == 200:
                    rel_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            if he.code == 404:
                list_req = urllib.request.Request(
                    f"https://api.github.com/repos/{repo}/releases?per_page=1",
                    headers=headers,
                )
                with urllib.request.urlopen(list_req, timeout=6) as resp:
                    if resp.status == 200:
                        items = json.loads(resp.read().decode("utf-8"))
                        if items and isinstance(items, list):
                            rel_data = items[0]
            else:
                raise

        if rel_data:
            tag_name = (rel_data.get("tag_name") or "").lstrip("vV").strip()
            if tag_name:
                if _compare_versions(tag_name, res.get("latest_version", cur_ver)) >= 0:
                    res["latest_version"] = tag_name
                res["release_notes"] = rel_data.get("body") or ""
                res["published_at"] = rel_data.get("published_at") or ""
                res["channel"] = "release"
    except Exception as exc:
        log.debug("[updater] GitHub Release API 获取略过: %s", exc)

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
    """执行在线代码更新同步（自动暂存并恢复用户本地 config.yaml 修改，避免 git pull 冲突）。"""
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

    # 若 config.yaml 有本地改动，先备份内容以免阻断 git pull
    cfg_path = REPO_ROOT / "config.yaml"
    cfg_backup: str | None = None
    try:
        diff_proc = subprocess.run(
            ["git", "diff", "--quiet", "--", "config.yaml"],
            cwd=str(REPO_ROOT),
            timeout=3,
        )
        if diff_proc.returncode != 0 and cfg_path.exists():
            cfg_backup = cfg_path.read_text(encoding="utf-8")
            subprocess.run(
                ["git", "checkout", "--", "config.yaml"],
                cwd=str(REPO_ROOT),
                timeout=3,
            )
    except Exception:
        pass

    cmd = ["git", "pull", pull_url, "main"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=40,
        )
        # 无论拉取成功与否，恢复用户的本地 config.yaml
        if cfg_backup is not None:
            try:
                cfg_path.write_text(cfg_backup, encoding="utf-8")
            except Exception:
                pass

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
            try:
                from studio.db import get_engine, init_db
                db_url = os.environ.get("YIMU_DB_URL", "sqlite:///./data/mediaflow.db")
                init_db(get_engine(db_url))
            except Exception as e:
                log.warning("[updater] 自动对齐数据库结构提示: %s", e)

            import importlib
            importlib.reload(version)
            upgraded_version = getattr(version, "__version__", cur_commit)

            return {
                "ok": True,
                "message": f"🎉 升级成功！系统已同步至最新版本 (V{upgraded_version})，建议重启服务使全部模块生效。",
                "output": output,
                "previous_commit": prev_commit,
                "current_commit": cur_commit,
                "version": upgraded_version,
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
        if cfg_backup is not None:
            try:
                cfg_path.write_text(cfg_backup, encoding="utf-8")
            except Exception:
                pass
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
    max_len = max(len(p1), len(p2))
    p1.extend([0] * (max_len - len(p1)))
    p2.extend([0] * (max_len - len(p2)))
    for a, b in zip(p1, p2):
        if a > b:
            return 1
        if a < b:
            return -1
    return 0
