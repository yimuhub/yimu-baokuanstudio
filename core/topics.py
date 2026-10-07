"""热榜选题抓取（借鉴 TrendRadar 的公开接口方案，零成本零依赖）。

内置四源（均为公开接口，2026-09-12 实测可用）：
- toutiao 头条热榜  https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc
- weibo  微博热搜  https://weibo.com/ajax/statuses/hot_band
- baidu  百度热搜  https://top.baidu.com/api/board?platform=wise&tab=realtime
- douyin 抖音热榜  https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/
另保留 dailyhotapi 源（imsyy/DailyHotApi，可选）。
关键词命中 → matched=1；未命中保留（matched=0）供人工翻看。

v3.33新增功能：
- 抓取每个平台热榜 Top5 的文章摘要内容存入热榜库
- 自动清理过期热榜（按天数）
- 立即清空热榜库
"""
import re
import httpx

from core.db import add_topic, save_topic_content
from core.llm import load_config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HEADERS = {"User-Agent": UA}


def _get(url: str, extra_headers: dict | None = None, **kw):
    headers = {**HEADERS, **(extra_headers or {})}
    r = httpx.get(url, headers=headers, timeout=15, **kw)
    r.raise_for_status()
    return r.json()


def _get_text(url: str, extra_headers: dict | None = None) -> str:
    """抓取网页文本内容，用于获取文章摘要。"""
    try:
        headers = {**HEADERS, **(extra_headers or {})}
        r = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        r.raise_for_status()
        text = r.text
        # 简单提取正文：去掉 HTML 标签，截取前1000字
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:1000]
    except Exception:
        return ""


def fetch_toutiao() -> list[dict]:
    d = _get("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc")
    items = []
    for it in d.get("data", []):
        if it.get("Title"):
            items.append({
                "title": (it.get("Title") or "").strip(),
                "hot": it.get("HotValue", ""),
                "url": it.get("Url") or it.get("url") or ""
            })
    return items


def fetch_weibo() -> list[dict]:
    d = _get("https://weibo.com/ajax/statuses/hot_band",
             extra_headers={"Referer": "https://weibo.com/hot/search"})
    items = []
    for it in d.get("data", {}).get("band_list", []):
        if it.get("note"):
            items.append({
                "title": (it.get("note") or "").strip(),
                "hot": it.get("num", ""),
                "url": f"https://s.weibo.com/weibo?q={it.get('note', '')}"
            })
    return items


def fetch_baidu() -> list[dict]:
    d = _get("https://top.baidu.com/api/board?platform=wise&tab=realtime",
             extra_headers={"Referer": "https://top.baidu.com/board"})
    cards = d.get("data", {}).get("cards", [])
    items = []
    for c in cards:  # 百度结构双层嵌套: cards[].content[].content[]
        for sub in c.get("content", []):
            inner = sub.get("content")
            raw = inner if isinstance(inner, list) else [sub]
            for it in raw:
                if it.get("word"):
                    items.append({
                        "title": (it.get("word") or "").strip(),
                        "hot": it.get("hotScore", ""),
                        "url": it.get("url") or f"https://www.baidu.com/s?wd={it.get('word', '')}"
                    })
    return items


def fetch_douyin() -> list[dict]:
    d = _get("https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/")
    items = []
    for it in d.get("word_list", []):
        if it.get("word"):
            items.append({
                "title": (it.get("word") or "").strip(),
                "hot": it.get("hot_value", ""),
                "url": f"https://www.douyin.com/search/{it.get('word', '')}"
            })
    return items


BUILTIN = {"toutiao": fetch_toutiao, "weibo": fetch_weibo,
           "baidu": fetch_baidu, "douyin": fetch_douyin}


def _fetch_dailyhotapi(source: dict) -> list[dict]:
    base = source["url"].rstrip("/")
    out = []
    for plat in source.get("platforms", []):
        try:
            d = _get(f"{base}/{plat}")
            out += [{"title": (it.get("title") or "").strip(),
                     "hot": it.get("hot", ""),
                     "url": it.get("url", "")} for it in d.get("data", []) if it.get("title")]
        except Exception:
            continue
    return out


def fetch_article_content(items: list[dict], top_n: int = 5) -> dict[str, str]:
    """抓取热榜前N条的文章内容摘要。
    
    返回: {title: content_text}
    """
    contents = {}
    for it in items[:top_n]:
        url = it.get("url", "")
        title = it.get("title", "")
        if url and title:
            text = _get_text(url)
            if text:
                contents[title] = text
    return contents


def collect_topics() -> dict:
    """按 config.topics.sources 抓取并入库，返回统计。
    
    v3.33: 同时抓取每平台前5条的文章内容存入热榜库。
    """
    import time
    from core import db

    cfg = load_config().get("topics", {})
    keywords = cfg.get("keywords", [])
    total = hit = 0
    per_source = {}

    c = db.conn()
    recent_titles = {r[0] for r in c.execute("SELECT title FROM topics WHERE created_at > ?", (time.time() - 86400,)).fetchall()}
    c.close()

    for src in cfg.get("sources", []):
        stype = src.get("type")
        if not src.get("enabled", True):
            continue

        if stype == "dailyhotapi":
            items = _fetch_dailyhotapi(src)
            # 抓取前5文章内容
            article_map = {}
            try:
                article_map = fetch_article_content(items, top_n=5)
            except Exception:
                pass
            for i, it in enumerate(items):
                title = (it.get("title") or "").strip()
                if not title or title in recent_titles:
                    continue
                recent_titles.add(title)
                matched = any(k in title for k in keywords) if keywords else False
                hot_str = f" 热度{it.get('hot', '')}" if it.get("hot") else ""
                topic = db.add_topic("dailyhotapi", title, f"热榜第{i+1}位{hot_str}", matched)
                # 如果是前5，保存文章内容
                if i < 5 and title in article_map:
                    try:
                        db.save_topic_content(topic["id"], article_map[title])
                    except Exception:
                        pass
                total += 1
                hit += int(matched)
            per_source["dailyhotapi"] = f"ok({len(items)})"
        else:
            for name in src.get("platforms", []):
                fn = BUILTIN.get(name)
                if not fn:
                    continue
                try:
                    got = fn()
                    per_source[name] = f"ok({len(got)})"
                    # 抓取前5文章内容（异步友好：失败不影响主流程）
                    article_map = {}
                    try:
                        article_map = fetch_article_content(got, top_n=5)
                    except Exception:
                        pass
                    for i, it in enumerate(got):
                        title = (it.get("title") or "").strip()
                        if not title or title in recent_titles:
                            continue
                        recent_titles.add(title)
                        matched = any(k in title for k in keywords) if keywords else False
                        hot_val = it.get("hot", "")
                        hot_str = f" 热度{hot_val}" if hot_val else ""
                        topic = db.add_topic(name, title, f"热榜第{i+1}位{hot_str}", matched)
                        # 如果是前5，保存文章内容
                        if i < 5 and title in article_map:
                            try:
                                db.save_topic_content(topic["id"], article_map[title])
                            except Exception:
                                pass
                        total += 1
                        hit += int(matched)
                except Exception as e:
                    per_source[name] = f"fail({str(e)[:60]})"

    return {"total": total, "matched": hit, "keywords": keywords,
            "per_source": per_source}


def auto_clean_topics(days: int) -> int:
    """自动清理 days 天前的热榜条目，返回清理数量。"""
    from core import db
    return db.delete_old_topics(days)
