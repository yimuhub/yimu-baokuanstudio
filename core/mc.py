"""MediaCrawler 统一搜索集成（小红书/抖音/快手/B站/微博/贴吧/知乎）。

调用 vendors/MediaCrawler（--lt qrcode 首次扫码，登录态保存在其 browser_data/），
输出 JSON 解析为统一条目。首次使用运行 vendors/setup_mc.command 安装+登录。
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
MC_DIR = BASE / "vendors" / "MediaCrawler"

# mediaflow 平台名 → MediaCrawler platform 参数
MC_PLATFORMS = {"xhs": "xhs", "douyin": "dy", "weibo": "wb",
                "kuaishou": "ks", "bilibili": "bili", "zhihu": "zhihu", "tieba": "tieba"}
# 各平台 json 字段映射
FIELDS = {
    "xhs": {"title": "title", "desc": "desc", "likes": "liked_count", "author": "nickname"},
    "dy": {"title": "title", "desc": "desc", "likes": "liked_count", "author": "nickname"},
    "wb": {"title": "content", "desc": "content", "likes": "liked_count", "author": "nickname"},
    "ks": {"title": "title", "desc": "caption", "likes": "liked_count", "author": "author_name"},
    "bili": {"title": "title", "desc": "desc", "likes": "liked_count", "author": "author_name"},
    "zhihu": {"title": "title", "desc": "content", "likes": "voteup_count", "author": "author_name"},
}


def available() -> bool:
    return (MC_DIR / "main.py").exists()


def platform_ok(platform: str) -> bool:
    """该平台是否有登录态（browser_data 下有 profile 目录即视为已登录过）。"""
    return (MC_DIR / "browser_data" / MC_PLATFORMS.get(platform, platform)).exists()


def _venv_python() -> Path:
    vp = MC_DIR / ".venv" / "bin" / "python"
    return vp if vp.exists() else Path(sys.executable)


def search(platform: str, keyword: str, limit: int = 12) -> list[dict]:
    """跑一次 MediaCrawler 关键词搜索并解析（同步，60~180s）。"""
    if not available():
        raise RuntimeError("MediaCrawler 未安装：双击 vendors/setup_mc.command 安装并扫码登录")
    mc_platform = MC_PLATFORMS.get(platform)
    if not mc_platform:
        raise RuntimeError(f"不支持的源: {platform}")
    if not platform_ok(platform):
        raise RuntimeError(f"{platform} 未登录：在 vendors/MediaCrawler 目录运行 "
                           f"`.venv/bin/python main.py --platform {mc_platform} --lt qrcode --type search --keywords 测试` 扫码一次")
    before = set(MC_DIR.rglob("*.json"))
    cmd = [str(_venv_python()), "main.py", "--platform", mc_platform,
           "--lt", "qrcode", "--type", "search", "--keywords", keyword,
           "--save-data-option", "json"]
    subprocess.run(cmd, cwd=str(MC_DIR), timeout=600, capture_output=True)
    files = sorted(set(MC_DIR.rglob("*.json")) - before, key=lambda p: p.stat().st_mtime)
    items = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            items += data if isinstance(data, list) else []
        except Exception:
            continue
    fl = FIELDS.get(mc_platform, FIELDS["xhs"])
    out = []
    for it in items:
        title = (it.get(fl["title"]) or it.get("title") or it.get("desc") or "").strip()
        if not title:
            continue
        out.append({"platform": platform, "title": title[:60],
                    "author": str(it.get(fl["author"]) or "")[:30],
                    "likes": it.get(fl["likes"]) or "",
                    "url": it.get("note_url") or it.get("content_url") or "",
                    "snippet": str(it.get(fl["desc"]) or "")[:200],
                    "extra": {"note_id": it.get("note_id") or it.get("id") or "",
                              "xsec_token": it.get("xsec_token") or ""}})
        if len(out) >= limit:
            break
    return out
