"""免费素材 API 集成：Pexels / Pixabay。

设计原则：
- API key 优先读视频合成配置（studio/video_config.py，可在控制中心配置），
  环境变量（PEXELS_API_KEY / PIXABAY_API_KEY）兜底，不硬编码
- 任一 key 缺失 → 对应引擎静默跳过，不抛异常
- 所有网络调用带超时 + 异常捕获，失败返回空列表
- 下载到本地缓存目录，避免重复下载

Pexels 免费额度：200 req/hour，20000 req/month（无需信用卡）
Pixabay 免费额度：100 req/min（需注册拿 key）
"""
import hashlib
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# 缓存目录：项目根 / runs/stock_cache/
_CACHE_DIR = Path(__file__).resolve().parent.parent / "runs" / "stock_cache"

_TIMEOUT_S = 15  # 单次 API 调用超时


def _cache_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _pexels_key() -> str:
    """配置优先，环境变量兜底（见 studio/video_config.py）。"""
    try:
        from studio import video_config as _vc
        return _vc.get_pexels_key()
    except Exception:  # noqa: BLE001
        return os.environ.get("PEXELS_API_KEY", "").strip()


def _pixabay_key() -> str:
    """配置优先，环境变量兜底（见 studio/video_config.py）。"""
    try:
        from studio import video_config as _vc
        return _vc.get_pixabay_key()
    except Exception:  # noqa: BLE001
        return os.environ.get("PIXABAY_API_KEY", "").strip()


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _http_get_json(url: str, headers: dict | None = None) -> dict | None:
    """GET JSON，超时/异常返回 None（不抛）。"""
    try:
        req_headers = {"User-Agent": _DEFAULT_UA}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            import json as _json
            return _json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — 素材是增强项，失败只打日志
        log.warning("[stock] API 请求失败 %s: %s: %s", url[:80], type(exc).__name__, exc)
        return None


def _download(url: str, suffix: str) -> Path | None:
    """下载远程文件到缓存，返回本地路径；失败返回 None。"""
    try:
        name = hashlib.md5(url.encode()).hexdigest()[:16] + suffix
        dest = _cache_dir() / name
        if dest.exists() and dest.stat().st_size > 1024:
            return dest  # 缓存命中
        req = urllib.request.Request(url, headers={"User-Agent": _DEFAULT_UA})
        with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        if dest.stat().st_size < 1024:
            dest.unlink(missing_ok=True)
            return None
        return dest
    except Exception as exc:  # noqa: BLE001
        log.warning("[stock] 下载失败 %s: %s", url[:80], exc)
        return None


# ---------------------------------------------------------------- Pexels ---

def _pexels_search_videos(keywords: str, n: int, orientation: str) -> list[str]:
    """Pexels 视频搜索，返回可直接下载的 mp4 URL 列表。"""
    key = _pexels_key()
    if not key:
        return []
    q = urllib.parse.quote(keywords)
    url = (f"https://api.pexels.com/videos/search?query={q}"
           f"&per_page={min(n, 10)}&orientation={orientation}")
    data = _http_get_json(url, {"Authorization": key})
    if not data:
        return []
    urls: list[str] = []
    for v in data.get("videos", [])[:n]:
        files = v.get("video_files", [])
        # 选一个中等清晰度的 mp4（link 字段）
        best = None
        for f in files:
            if f.get("file_type") == "video/mp4" and f.get("link"):
                w = f.get("width", 0)
                if best is None or abs(w - 720) < abs(best.get("width", 0) - 720):
                    best = f
        if best:
            urls.append(best["link"])
    return urls


def _pexels_search_images(keywords: str, n: int) -> list[str]:
    """Pexels 图片搜索，返回原图 URL 列表。"""
    key = _pexels_key()
    if not key:
        return []
    q = urllib.parse.quote(keywords)
    url = f"https://api.pexels.com/v1/search?query={q}&per_page={min(n, 10)}"
    data = _http_get_json(url, {"Authorization": key})
    if not data:
        return []
    urls = []
    for p in data.get("photos", [])[:n]:
        src = p.get("src", {})
        u = src.get("large") or src.get("original")
        if u:
            urls.append(u)
    return urls


# --------------------------------------------------------------- Pixabay ---

def _pixabay_search_videos(keywords: str, n: int) -> list[str]:
    """Pixabay 视频搜索（fallback），返回 mp4 URL 列表。"""
    key = _pixabay_key()
    if not key:
        return []
    q = urllib.parse.quote(keywords)
    url = (f"https://pixabay.com/api/videos/?key={key}&q={q}"
           f"&per_page={min(n, 10)}")
    data = _http_get_json(url)
    if not data:
        return []
    urls = []
    for v in data.get("hits", [])[:n]:
        vids = v.get("videos", {})
        # 取 medium 档（720p 左右）
        best = vids.get("medium") or vids.get("small") or vids.get("large")
        if best and best.get("url"):
            urls.append(best["url"])
    return urls


def _pixabay_search_images(keywords: str, n: int) -> list[str]:
    """Pixabay 图片搜索（fallback），返回 URL 列表。"""
    key = _pixabay_key()
    if not key:
        return []
    q = urllib.parse.quote(keywords)
    url = (f"https://pixabay.com/api/?key={key}&q={q}"
           f"&per_page={min(n, 10)}&image_type=photo")
    data = _http_get_json(url)
    if not data:
        return []
    urls = []
    for p in data.get("hits", [])[:n]:
        u = p.get("largeImageURL") or p.get("webformatURL")
        if u:
            urls.append(u)
    return urls


# --------------------------------------------------------------- 对外接口 ---

def search_videos(keywords: str, n: int = 3, orientation: str = "portrait") -> list[Path]:
    """搜索免费视频并下载到本地，返回本地路径列表。

    优先级：Pexels → Pixabay。两个 key 都没有时返回 []（不抛异常，
    上层用 AI 图片兜底）。
    """
    urls = _pexels_search_videos(keywords, n, orientation)
    if not urls:
        urls = _pixabay_search_videos(keywords, n)
    paths: list[Path] = []
    for u in urls[:n]:
        p = _download(u, ".mp4")
        if p:
            paths.append(p)
        time.sleep(0.2)  # 礼貌间隔，避免触发限流
    return paths


def search_images(keywords: str, n: int = 3) -> list[Path]:
    """搜索免费图片并下载到本地，返回本地路径列表。"""
    urls = _pexels_search_images(keywords, n)
    if not urls:
        urls = _pixabay_search_images(keywords, n)
    paths: list[Path] = []
    for u in urls[:n]:
        p = _download(u, ".jpg")
        if p:
            paths.append(p)
        time.sleep(0.2)
    return paths


def stock_available() -> dict:
    """返回各素材引擎可用状态（供 UI/诊断用）。"""
    return {
        "pexels": bool(_pexels_key()),
        "pixabay": bool(_pixabay_key()),
    }
