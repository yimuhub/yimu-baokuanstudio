# SPDX-License-Identifier: BUSL-1.1
"""GitHub 趋势采集器（移植自项目 A global_.GithubTrendingCollector）。

用官方搜索 API（近 7 天创建按 star 排序），不抓 trending 网页。
未认证限流很严（约 10 次/分钟），403 时抛清晰异常交 pipeline 隔离。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

from ..base import PlatformCollector, register
from ..http import HttpClient, strip_html, to_int
from ..models import HotItem


@register
class GithubCollector(PlatformCollector):
    name = "github"
    display_name = "GitHub 趋势"
    category = "global"

    BASE = "https://api.github.com/search/repositories"
    HEADERS = {"Accept": "application/vnd.github+json"}

    def collect(self) -> list[HotItem]:
        http = HttpClient()
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"{self.BASE}?q=created:>{since}&sort=stars&order=desc&per_page=25"
        try:
            data = http.get_json(url, headers=self.HEADERS)
        except HTTPError as e:
            if e.code == 403:
                raise RuntimeError("GitHub 搜索 API 限流/拒绝访问 (HTTP 403)，请稍后重试或配置 Token") from e
            raise RuntimeError(f"GitHub 搜索 API 请求失败 (HTTP {e.code})") from e
        rows = data.get("items") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        items: list[HotItem] = []
        for idx, repo in enumerate(rows, 1):
            if not isinstance(repo, dict):
                continue
            title = (repo.get("full_name") or "").strip()
            if not title:
                continue
            owner = repo.get("owner") if isinstance(repo.get("owner"), dict) else {}
            stars = to_int(repo.get("stargazers_count"))
            items.append(HotItem(
                platform=self.name, platform_name=self.display_name,
                title=title, url=(repo.get("html_url") or "").strip(),
                author=(owner.get("login") or "").strip(),
                body=strip_html(repo.get("description") or ""), rank=idx,
                likes=stars, collects=to_int(repo.get("forks_count")),
                hot_raw=float(stars),
            ))
        return items
