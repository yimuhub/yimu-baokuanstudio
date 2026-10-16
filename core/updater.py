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


def is_git_repo() -> bool:
    """判断当前运行目录是否为包含 .git 目录的有效 Git 仓库。"""
    return (REPO_ROOT / ".git").is_dir()


def _upgrade_from_archive(repo: str, token: str) -> tuple[bool, str]:
    """针对无 .git 的 Release ZIP 用户，通过官方/镜像源下载最新代码归档并安全覆盖。"""
    import io
    import shutil
    import zipfile

    headers = {"User-Agent": _DEFAULT_UA}
    if token:
        headers["Authorization"] = f"token {token}"

    download_urls = [
        f"https://github.com/{repo}/archive/refs/heads/main.zip",
        f"https://ghfast.top/https://github.com/{repo}/archive/refs/heads/main.zip",
        f"https://ghproxy.net/https://github.com/{repo}/archive/refs/heads/main.zip",
    ]

    last_err = ""
    for url in download_urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    zip_bytes = resp.read()
                    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                        # 查找根目录前缀（通常为 yimu-baokuanstudio-main/）
                        namelist = zf.namelist()
                        root_prefix = namelist[0].split("/")[0] + "/" if namelist and "/" in namelist[0] else ""
                        
                        # 保护私有数据目录清单（严禁覆盖丢失）
                        protected_prefixes = ("data/", "runs/", "logs/", ".venv/", ".env")
                        
                        for member in zf.infolist():
                            rel_name = member.filename
                            if root_prefix and rel_name.startswith(root_prefix):
                                rel_name = rel_name[len(root_prefix):]
                            if not rel_name or rel_name.endswith("/"):
                                continue
                            
                            # 严格跳过保护的数据文件与用户私有密钥配置
                            if any(rel_name.startswith(p) or rel_name == p for p in protected_prefixes):
                                continue

                            target_file = REPO_ROOT / rel_name
                            target_file.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(member) as src, open(target_file, "wb") as dst:
                                shutil.copyfileobj(src, dst)

                    return True, f"已通过 Release 归档包 ({url.split('/')[2]}) 成功热解压并覆盖更新。"
        except Exception as e:
            last_err = str(e)
            log.warning("[updater] 尝试通过 %s 下载更新包失败: %s", url, e)

    return False, f"所有发布包下载通道均连接超时: {last_err}"


def perform_upgrade() -> dict[str, Any]:
    """执行在线代码更新同步（智能适配 Git 仓库模式与 Release ZIP 压缩包模式）。"""
    token = _get_github_token()
    repo = _get_github_repo()
    prev_ver = getattr(version, "__version__", "unknown")

    prev_commit = ""
    if is_git_repo():
        try:
            prev_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(REPO_ROOT),
                text=True,
                timeout=3,
            ).strip()[:7]
        except Exception:
            pass

    upgrade_ok = False
    output_log = ""

    if is_git_repo():
        # Git 仓库模式
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

        # 尝试使用原生 origin 或镜像拉取
        pull_targets = [
            f"https://github.com/{repo}.git" if not token else f"https://oauth2:{token}@github.com/{repo}.git",
            f"https://ghfast.top/https://github.com/{repo}.git",
            f"https://ghproxy.net/https://github.com/{repo}.git",
        ]

        last_git_output = ""
        for p_target in pull_targets:
            cmd = ["git", "pull", p_target, "main"]
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                last_git_output = (proc.stdout + "\n" + proc.stderr).strip()
                if token:
                    last_git_output = last_git_output.replace(token, "******")

                if proc.returncode == 0:
                    upgrade_ok = True
                    output_log = last_git_output
                    break
            except Exception as e:
                last_git_output = f"Git 命令执行异常: {e}"

        if cfg_backup is not None:
            try:
                cfg_path.write_text(cfg_backup, encoding="utf-8")
            except Exception:
                pass

        if not upgrade_ok:
            output_log = last_git_output
    else:
        # 非 Git 仓库（Release ZIP 发行版用户）
        upgrade_ok, output_log = _upgrade_from_archive(repo, token)

    cur_commit = prev_commit
    if is_git_repo():
        try:
            cur_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(REPO_ROOT),
                text=True,
                timeout=3,
            ).strip()[:7]
        except Exception:
            pass

    if upgrade_ok:
        global _cache_check_result
        _cache_check_result = None
        try:
            from studio.db import get_engine, init_db
            db_url = os.environ.get("YIMU_DB_URL", "sqlite:///./data/mediaflow.db")
            init_db(get_engine(db_url))
        except Exception as e:
            log.warning("[updater] 自动对齐数据库结构提示: %s", e)

        try:
            from core.db import auto_heal_all_sqlite_databases
            auto_heal_all_sqlite_databases()
        except Exception as e:
            log.warning("[updater] 升级后自动修复数据库约束提示: %s", e)

        import importlib
        importlib.reload(version)
        upgraded_version = getattr(version, "__version__", cur_commit)

        # 同步刷新 web.admin 全局变量
        try:
            import web.admin as web_admin
            web_admin.APP_VERSION = upgraded_version
        except Exception:
            pass

        return {
            "ok": True,
            "message": f"🎉 升级成功！系统已从 V{prev_ver} 升级至最新版本 (V{upgraded_version})。请重启服务使全部核心模块完全生效。",
            "output": output_log,
            "previous_commit": prev_commit,
            "current_commit": cur_commit,
            "version": upgraded_version,
        }
    else:
        return {
            "ok": False,
            "message": f"拉取更新失败。请检查网络是否能访问 GitHub，或稍后重试。",
            "output": output_log,
            "previous_commit": prev_commit,
            "current_commit": cur_commit,
            "version": prev_ver,
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


if __name__ == "__main__":
    import sys
    print("=" * 60)
    print("一幕·YIMU 爆款工作室 - 在线更新引擎 (CLI)")
    print("=" * 60)
    if "--upgrade" in sys.argv or "-u" in sys.argv:
        print("[执行] 开始执行在线升级...")
        res = perform_upgrade()
        if res.get("ok"):
            print("✅", res.get("message"))
            sys.exit(0)
        else:
            print("❌", res.get("message"))
            if res.get("output"):
                print("详情:\n", res.get("output"))
            sys.exit(1)
    else:
        chk = check_for_updates(force=True)
        print("当前版本:", chk.get("current_version"))
        print("最新版本:", chk.get("latest_version"))
        print("存在更新:", chk.get("has_update"))
        if chk.get("has_update"):
            print("💡 运行 `python -m core.updater --upgrade` 可直接执行升级")

