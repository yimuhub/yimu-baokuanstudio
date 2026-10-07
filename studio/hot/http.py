# SPDX-License-Identifier: BUSL-1.1
"""采集器 HTTP 底座（移植自项目 A app/collectors/base.py 的 _request/warmup 思想）。

纯标准库：urllib + cookie jar + gzip + 重试 + 浏览器 UA。
反爬要点：warmup 先拿风控 cookie（如 B 站 buvid3）；失败静默忽略。
"""

from __future__ import annotations

import gzip
import http.cookiejar
import json
import random
import re
import ssl
import time
from typing import Any
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


class HttpClient:
    """单个采集器实例持有一个，cookie 在多次请求间复用。"""

    def __init__(self, timeout: int = 15, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries
        self._cj = http.cookiejar.CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._cj), HTTPSHandler(context=_CTX))
        self._warmed: set[str] = set()

    def warmup(self, url: str, referer: str = "") -> None:
        """先访问一次拿风控 cookie；失败静默忽略。"""
        if url in self._warmed:
            return
        self._warmed.add(url)
        try:
            req = Request(url, headers={"User-Agent": UA, "Referer": referer} if referer else {"User-Agent": UA})
            with self._opener.open(req, timeout=self.timeout) as r:
                r.read(2048)
        except Exception:  # noqa: BLE001 — warmup 失败不影响主流程
            pass

    def request(self, url: str, *, method: str = "GET", referer: str = "",
                headers: dict | None = None, data: bytes | None = None) -> bytes:
        """带重试的请求；最后一次失败把异常抛给 pipeline 做失败隔离。"""
        h = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, text/html, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        }
        if referer:
            h["Referer"] = referer
        if headers:
            h.update(headers)
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = Request(url, headers=h, data=data, method=method)
                with self._opener.open(req, timeout=self.timeout) as r:
                    raw = r.read()
                    enc = (r.headers.get("Content-Encoding") or "").lower()
                if "gzip" in enc:
                    raw = gzip.decompress(raw)
                return raw
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < self.retries:
                    time.sleep(0.6 * (attempt + 1) + random.random() * 0.4)
        raise last  # type: ignore[misc]

    def get_json(self, url: str, **kw) -> Any:
        return json.loads(self.request(url, **kw).decode("utf-8", "ignore"))

    def post_json(self, url: str, payload: dict, **kw) -> Any:
        body = json.dumps(payload).encode("utf-8")
        return json.loads(
            self.request(url, method="POST", data=body,
                         headers={"Content-Type": "application/json"}, **kw).decode("utf-8", "ignore")
        )

    def get_text(self, url: str, **kw) -> str:
        return self.request(url, **kw).decode("utf-8", "ignore")


def strip_html(s: Any) -> str:
    """去 HTML 标签（采集器字段清洗通用）。"""
    if not s:
        return ""
    return re.sub(r"<[^>]+>", "", str(s)).strip()


def to_int(v: Any) -> int:
    try:
        return int(float(str(v).strip().replace(",", "")))
    except (TypeError, ValueError):
        return 0


def abs_url(base: str, url: Any) -> str:
    if not url or not isinstance(url, str):
        return ""
    u = url.strip()
    if u.startswith("http"):
        return u
    return urljoin(base, u)
