"""GitHub 图床（免费）：把配图上传到用户 GitHub 仓库，换 jsdelivr CDN 公网直链。

配置（.env）：GITHUB_IMGBED_TOKEN（PAT, repo 权限）、GITHUB_IMGBED_REPO（user/repo）。
上传后返回 https://cdn.jsdelivr.net/gh/{repo}@main/{path} —— 国内可直连、可被公众号转存。
"""
import base64
from pathlib import Path

import httpx

from core.llm import load_env


def imgbed_cfg() -> dict:
    env = load_env()
    return {"token": env.get("GITHUB_IMGBED_TOKEN", ""),
            "repo": env.get("GITHUB_IMGBED_REPO", "")}


def available() -> bool:
    c = imgbed_cfg()
    return bool(c["token"] and c["repo"])


def upload(img_path: str, did: str) -> str:
    c = imgbed_cfg()
    if not available():
        raise RuntimeError("图床未配置（.env 缺 GITHUB_IMGBED_TOKEN/REPO）")
    p = Path(img_path)
    path = f"mediaflow/{did}/{p.name}"
    content = base64.b64encode(p.read_bytes()).decode()
    api = f"https://api.github.com/repos/{c['repo']}/contents/{path}"
    r = httpx.put(api,
                  json={"message": f"mediaflow {did}/{p.name}",
                        "content": content, "branch": "main"},
                  headers={"Authorization": f"Bearer {c['token']}",
                           "Accept": "application/vnd.github+json"},
                  timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub 上传失败 {r.status_code}: {r.text[:150]}")
    raw = r.json().get("content", {}).get("download_url", "")
    # raw.githubusercontent.com → jsdelivr（国内可达）
    jsd = raw.replace("https://raw.githubusercontent.com/", "https://cdn.jsdelivr.net/gh/")
    if "@" not in jsd.split("/gh/")[1].split("/")[0]:
        # user/repo/path → user/repo@main/path
        head, rest = jsd.split("/gh/")[1].split("/", 1)
        jsd = jsd.replace(f"/gh/{head}/", f"/gh/{head}@main/")
    return jsd
