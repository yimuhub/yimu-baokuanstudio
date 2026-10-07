"""关键词爆款搜索：小红书 / 今日头条 / 抖音 三源统一接口。

- toutiao：无头 Chrome 抓 so.toutiao.com 搜索页（免登录，已实测）
- xhs：本地 xiaohongshu-mcp（vendors/xhs-mcp，MCP over HTTP :18060，需首次扫码登录）
- douyin：MediaCrawler（vendors/MediaCrawler，关键词搜索，需首次扫码登录）

返回统一结构：{"platform","title","author","likes","date","url","snippet","extra"}
"""
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VENDORS = BASE / "vendors"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

XHS_MCP = "http://localhost:18060/mcp"


# ---------------- 小红书（xiaohongshu-mcp） ----------------

def _mcp_rpc(session: list, payload: dict) -> dict | None:
    req = urllib.request.Request(
        XHS_MCP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 **({"Mcp-Session-Id": session[0]} if session else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        sid = r.headers.get("Mcp-Session-Id")
        if sid and not session:
            session.append(sid)
        raw = r.read().decode()
    for line in raw.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            break
    try:
        return json.loads(raw)
    except Exception:
        return None


def xhs_available() -> bool:
    try:
        s: list = []
        r = _mcp_rpc(s, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "mediaflow", "version": "0.1"}}})
        if r is None:
            return False
        tools = _mcp_rpc(s, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        return bool(tools)
    except Exception:
        return False


def _xhs_tools(session: list) -> dict:
    r = _mcp_rpc(session, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    return {t["name"]: t for t in (r or {}).get("result", {}).get("tools", [])}


def xhs_search(keyword: str, limit: int = 12) -> list[dict]:
    s: list = []
    _mcp_rpc(s, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "mediaflow", "version": "0.1"}}})
    tools = _xhs_tools(s)
    name = next((n for n in tools if "search" in n.lower()), None)
    if not name:
        raise RuntimeError(f"xhs-mcp 无搜索工具，现有: {list(tools)}")
    r = _mcp_rpc(s, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": name,
                                "arguments": {"keyword": keyword}}})
    content = ((r or {}).get("result", {}).get("content") or [{}])[0].get("text", "")
    data = json.loads(content) if content.strip().startswith(("[", "{")) else []
    items = data if isinstance(data, list) else data.get("notes") or data.get("items") or []
    out = []
    for it in items[:limit]:
        # xhs-mcp 返回字段: title/desc/liked/collected/author/note_id/xsec_token/note_url
        out.append({
            "platform": "xhs", "title": (it.get("title") or it.get("desc") or "")[:60],
            "author": it.get("author") or it.get("nickname") or "",
            "likes": it.get("liked") or it.get("likes") or "",
            "url": it.get("note_url") or it.get("url") or "",
            "snippet": (it.get("desc") or "")[:200],
            "extra": {"note_id": it.get("note_id") or it.get("id") or "",
                      "xsec_token": it.get("xsec_token") or ""},
        })
    return out


def xhs_detail(note_id: str, xsec_token: str) -> str:
    s: list = []
    _mcp_rpc(s, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "mediaflow", "version": "0.1"}}})
    tools = _xhs_tools(s)
    name = next((n for n in tools if "detail" in n.lower() or "feed" in n.lower()), None)
    if not name:
        return ""
    args = {"feed_id": note_id, "xsec_token": xsec_token}
    # 兼容不同参数命名
    for t in tools.get(name, {}).get("inputSchema", {}).get("properties", {}):
        pass
    r = _mcp_rpc(s, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": name, "arguments": args}})
    return ((r or {}).get("result", {}).get("content") or [{}])[0].get("text", "")


# ---------------- 今日头条（无头 Chrome 抓搜索页） ----------------

def toutiao_search(keyword: str, limit: int = 12) -> list[dict]:
    from playwright.sync_api import sync_playwright
    kw = urllib.parse.quote(keyword)
    out, seen = [], set()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.goto(f"https://so.toutiao.com/search?dvpf=pc&source=input&keyword={kw}",
                timeout=30000, wait_until="domcontentloaded")
        pg.wait_for_timeout(7000)
        pg.mouse.wheel(0, 1800)
        pg.wait_for_timeout(2200)
        pg.mouse.wheel(0, 1800)
        pg.wait_for_timeout(2200)
        blocks = pg.evaluate("""() => {
          const all = [...document.querySelectorAll('div,article,li,section')];
          const cand = all.filter(d => {
            const t = d.innerText || '';
            return t.length > 30 && t.length < 600 && !t.includes('换一换') &&
                   !t.includes('头条热榜') &&
                   (t.includes('评论') || t.includes('赞') || t.includes('阅读') || t.includes('转发'));
          });
          const inner = cand.filter(d => !cand.some(o => o !== d && d.contains(o)));
          return inner.map(d => (d.innerText || '').trim());
        }""")
        body_text = "" if len(blocks) >= 3 else pg.inner_text("body")
        browser.close()
    import re
    # 双保险：DOM 抓不到时按文本结构解析（条目以日期行结尾）
    if not blocks and body_text:
        lines = [x.strip() for x in body_text.splitlines() if x.strip()]
        date_re = re.compile(r"^(\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}|\d+天前|\d+小时前|\d+分钟前|昨天|前天)$")
        idxs = [i for i, x in enumerate(lines) if date_re.match(x)]
        segs = []
        for a, b in zip([-1] + idxs, idxs + [len(lines)]):
            seg = lines[a + 1:b]
            if len(seg) >= 3:
                segs.append(seg)
        for seg in segs[:limit * 2]:
            title = seg[0]
            stats = next((x for x in seg if re.search(r"\d+\s*(评论|赞|阅读|转发)", x)), "")
            m = re.search(r"([\d.]+[万亿wW]?)\s*赞", stats)
            src = seg[-2] if len(seg) >= 3 and "评论" not in seg[-2] and "赞" not in seg[-2] else ""
            if len(title) < 8 or "热榜" in title:
                continue
            out.append({"platform": "toutiao", "title": title[:60],
                        "author": src, "likes": m.group(1) if m else "",
                        "url": "", "snippet": " ".join(seg[1:4])[:200], "extra": {}})
        return out[:limit]
    for t in blocks:
        lines = [x.strip() for x in t.splitlines() if x.strip()]
        if not lines or lines[0] in seen:
            continue
        seen.add(lines[0])
        likes = m.group(1) if (m := re.search(r"([\d.]+[万亿wW]?)\s*赞", t)) else ""
        date = next((x for x in lines if re.match(r"^[\d月日年昨天前-]+$", x)), "")
        out.append({"platform": "toutiao", "title": lines[0][:60],
                    "author": lines[1] if len(lines) > 2 else "",
                    "likes": likes, "date": date, "url": "",
                    "snippet": t[:200], "extra": {}})
        if len(out) >= limit:
            break
    return out


def toutiao_detail(url: str) -> str:
    """打开文章页取正文（搜索页拿不到全文时用）。"""
    if not url:
        return ""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        pg = browser.new_context(user_agent=UA).new_page()
        try:
            pg.goto(url, timeout=25000, wait_until="domcontentloaded")
            pg.wait_for_timeout(3000)
            return pg.inner_text("article, .article-content, main")[:6000] or pg.inner_text("body")[:6000]
        except Exception:
            return ""
        finally:
            browser.close()


# ---------------- 抖音（MediaCrawler） ----------------

MC_DIR = VENDORS / "MediaCrawler"


def douyin_available() -> bool:
    return (MC_DIR / "main.py").exists()


def douyin_search(keyword: str, limit: int = 12) -> list[dict]:
    if not douyin_available():
        raise RuntimeError("MediaCrawler 未安装：先运行 vendors/setup_douyin.command 并扫码登录")
    out_dir = BASE / "data" / "douyin"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(MC_DIR / ".venv" / "bin" / "python") if (MC_DIR / ".venv" / "bin" / "python").exists()
           else sys.executable, str(MC_DIR / "main.py"),
           "--platform", "douyin", "--lt", "qrcode", "--type", "search",
           "--keywords", keyword, "--save-data-option", "json",
           "--get-comment", "false"]
    subprocess.run(cmd, cwd=str(MC_DIR), timeout=420, capture_output=True)
    import re
    files = sorted(MC_DIR.rglob("json/*search*.json"), key=lambda p: p.stat().st_mtime)
    items = []
    for f in files[-3:]:
        try:
            data = json.loads(f.read_text())
            items += data if isinstance(data, list) else []
        except Exception:
            pass
    out = []
    for it in items:
        if keyword.split()[0] not in (it.get("title") or "") + (it.get("desc") or ""):
            continue
        out.append({"platform": "douyin",
                    "title": (it.get("title") or it.get("desc") or "")[:60],
                    "author": it.get("nickname") or "",
                    "likes": it.get("liked_count") or "",
                    "url": it.get("note_url") or "",
                    "snippet": (it.get("desc") or "")[:200], "extra": {}})
        if len(out) >= limit:
            break
    return out


SOURCES = {"xhs": xhs_search, "toutiao": toutiao_search, "douyin": douyin_search}


def _mc_search_factory(platform: str):
    def _fn(keyword: str, limit: int = 12) -> list[dict]:
        from core import mc
        return mc.search(platform, keyword, limit)
    return _fn


for _p in ("weibo", "kuaishou", "bilibili"):
    SOURCES[_p] = _mc_search_factory(_p)


def douyin_search_mc(keyword: str, limit: int = 12) -> list[dict]:
    """抖音优先 MediaCrawler（更强），未安装回落内置热榜接口。"""
    from core import mc
    if mc.available():
        return mc.search("douyin", keyword, limit)
    return douyin_search(keyword, limit)


SOURCES["douyin"] = douyin_search_mc


def xhs_search_fb(keyword: str, limit: int = 12) -> list[dict]:
    """小红书：xhs-mcp 失败回落 MediaCrawler。"""
    try:
        return xhs_search(keyword, limit)
    except Exception:
        from core import mc
        if mc.available():
            return mc.search("xhs", keyword, limit)
        raise


SOURCES["xhs"] = xhs_search_fb


def _likes_num(v) -> float:
    """likes 字段转数值（支持 万/w 后缀）。"""
    import re
    if v in (None, ""):
        return 0.0
    m = re.search(r"([\d.]+)\s*([万亿wW]?)", str(v))
    if not m:
        return 0.0
    n = float(m.group(1))
    unit = m.group(2)
    if unit in ("万", "w", "W"):
        n *= 10000
    elif unit == "亿":
        n *= 100000000
    return n


def expand_keyword(keyword: str, n: int = 3) -> list[str]:
    """采集 Agent 把关键词扩成 n 个相关搜索词。"""
    from core import agents
    try:
        raw = agents.chat_for("collect", [
            {"role": "user", "content":
                f"把搜索词「{keyword}」扩成 {n} 个更容易出爆款内容的相关搜索词，"
                "只输出 JSON 数组，如 [\"词1\",\"词2\",\"词3\"]"}], temperature=0.6)
        import json as _json
        m = re.search(r"\[.*\]", raw, re.S)
        words = _json.loads(m.group(0)) if m else []
        words = [w.strip() for w in words if isinstance(w, str) and w.strip()][:n]
        return words
    except Exception:
        return []


def search_expanded(keyword: str, sources: list[str], limit: int = 16,
                    expand: bool = True) -> tuple[dict, list[str]]:
    """扩展关键词并行搜索 + 合并去重 + 按热度排序（历史高浏览优先）。

    返回 (各源结果, 实际使用的搜索词列表)
    """
    words = [keyword]
    if expand:
        words += [w for w in expand_keyword(keyword) if w and w != keyword]
    merged = {s: {} for s in sources}
    for w in words:
        res = search_all(w, sources, limit)
        for s, blk in res.items():
            for it in blk.get("items", []):
                key = (it.get("title") or "")[:30]
                if key and key not in merged[s]:
                    it = {**it, "query": w}
                    merged[s][key] = it
    out = {}
    for s in sources:
        items = sorted(merged.get(s, {}).values(),
                       key=lambda x: _likes_num(x.get("likes")), reverse=True)[:limit]
        out[s] = {"ok": bool(items), "items": items,
                  "queries": words}
    return out, words


def search_all(keyword: str, sources: list[str], limit: int = 12) -> dict:
    """并行搜索多源（各源独立线程，总耗时约等于最慢一源）。"""
    from concurrent.futures import ThreadPoolExecutor
    fns = {s: SOURCES[s] for s in sources if s in SOURCES}

    def run(s):
        try:
            return s, {"ok": True, "items": fns[s](keyword, limit)}
        except Exception as e:
            return s, {"ok": False, "items": [], "error": str(e)[:200]}

    res = {}
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(fns)))) as ex:
        for s, r in ex.map(run, fns):
            res[s] = r
    return res


def fetch_topic_multisource_references(query: str, limit: int = 5) -> list[dict]:
    """根据主题关键词，从全网检索并深度抓取 3~5 篇主流网页的真实标题、正文摘要与核心论点。
    支持微信公众号、百度全网深度文章、今日头条，返回结构：
    [{"title": ..., "source": ..., "snippet": ..., "url": ...}, ...]
    """
    import urllib.parse
    import httpx
    from bs4 import BeautifulSoup

    kw = (query or "").strip()
    if not kw:
        return []

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }
    articles = []
    seen_titles = set()

    # 1. 抓取百度全网深度研报与长文
    try:
        b_url = f"https://www.baidu.com/s?wd={urllib.parse.quote(kw)}"
        r = httpx.get(b_url, headers=headers, timeout=5.0, follow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for res in soup.select(".result, .c-container"):
                t_el = res.select_one("h3")
                if not t_el:
                    continue
                title = t_el.get_text(strip=True)
                if not title or title in seen_titles or "百度百科" in title:
                    continue
                # 获取该结果的完整文本段落
                text_block = res.get_text(" ", strip=True)
                # 清洗多余空格和常见标签
                text_clean = " ".join(text_block.split())
                seen_titles.add(title)
                a_tag = t_el.select_one("a")
                target_url = a_tag.get("href", "") if a_tag else ""
                articles.append({
                    "title": title,
                    "source": "全网深度文章",
                    "snippet": text_clean[:600],
                    "url": target_url
                })
                if len(articles) >= 3:
                    break
    except Exception:
        pass

    # 2. 抓取搜狗微信文章库（最具新媒体文案参考价值）
    try:
        url = f"https://weixin.sogou.com/weixin?type=2&query={urllib.parse.quote(kw)}"
        r = httpx.get(url, headers=headers, timeout=5.0, follow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for li in soup.select("ul.news-list li"):
                t_el = li.select_one("h3 a")
                p_el = li.select_one("p.txt-info")
                src_el = li.select_one("a.account") or li.select_one(".s-p a")
                if t_el:
                    title = t_el.get_text(strip=True)
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)
                    snippet = p_el.get_text(strip=True) if p_el else ""
                    src_name = src_el.get_text(strip=True) if src_el else "微信公众号热文"
                    articles.append({
                        "title": title,
                        "source": f"微信公众号 · {src_name}",
                        "snippet": snippet,
                        "url": t_el.get("href", "")
                    })
                if len(articles) >= limit + 2:
                    break
    except Exception:
        pass

    # 3. 补充今日头条或资讯热搜搜索
    if len(articles) < limit:
        try:
            tt_items = toutiao_search(kw, limit=limit)
            for it in tt_items:
                if it["title"] in seen_titles:
                    continue
                seen_titles.add(it["title"])
                articles.append({
                    "title": it["title"],
                    "source": f"今日头条 · {it.get('author') or '热点资讯'}",
                    "snippet": it.get("snippet", ""),
                    "url": it.get("url", "")
                })
                if len(articles) >= limit + 2:
                    break
        except Exception:
            pass

    return articles[:limit]


