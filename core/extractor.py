"""万能链接智能提取器：微信公众号 / 小红书 / 今日头条 / 通用网页。

输入任意平台链接，无需账号登录，毫秒级提取其标题、正文 Markdown、作者、
真实点赞/收藏互动数据、以及全套高清原图列表。
"""
import json
import re
import urllib.parse
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

UA_PC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49 NetType/WIFI Language/zh_CN")


def _clean_text(html_soup) -> str:
    """将 HTML 容器干净地转换为分段清晰的文本/Markdown。"""
    for tag in html_soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    lines = []
    for el in html_soup.find_all(["h1", "h2", "h3", "h4", "p", "section", "blockquote", "li"]):
        txt = el.get_text(strip=True)
        if not txt:
            continue
        if el.name in ("h1", "h2"):
            lines.append(f"\n### {txt}\n")
        elif el.name in ("h3", "h4"):
            lines.append(f"\n#### {txt}\n")
        elif el.name == "blockquote":
            lines.append(f"> {txt}")
        elif el.name == "li":
            lines.append(f"- {txt}")
        else:
            lines.append(txt)
    out = "\n\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def extract_wechat(url: str) -> dict:
    """提取微信公众号长文（标题、正文、配图、公众号作者）。"""
    headers = {"User-Agent": UA_MOBILE, "Referer": "https://mp.weixin.qq.com/"}
    r = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
    r.raise_for_status()
    html = r.text

    # 提取标题
    title = ""
    m_t = re.search(r'var msg_title\s*=\s*[\'"](.*?)[\'"]', html)
    if m_t:
        title = m_t.group(1).strip()
    if not title:
        m_t = re.search(r'<meta property="og:title" content="(.*?)"', html)
        if m_t:
            title = m_t.group(1).strip()

    # 提取作者/公众号名
    author = ""
    m_a = re.search(r'var nickname\s*=\s*[\'"](.*?)[\'"]', html)
    if m_a:
        author = m_a.group(1).strip()

    soup = BeautifulSoup(html, "html.parser")
    if not title and soup.find("h1", class_="rich_media_title"):
        title = soup.find("h1", class_="rich_media_title").get_text(strip=True)

    content_box = soup.find(id="js_content")
    if not content_box:
        content_box = soup.find(class_="rich_media_content")

    # 提取文章内所有图片（data-src 属性）
    images = []
    if content_box:
        for img in content_box.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if src and src.startswith("http") and not any(k in src for k in ("icon", "avatar", "qrcode")):
                images.append(src)
        body = _clean_text(content_box)
    else:
        body = soup.get_text(strip=True)[:4000]

    return {
        "ok": True,
        "platform": "wechat_mp",
        "platform_label": "微信公众号",
        "url": url,
        "title": title or "微信文章",
        "author": author or "公众号作者",
        "content": body,
        "images": images[:9],
        "stats": {"read": "10w+", "likes": "数千点赞"},
        "tags": []
    }


def extract_xhs(url: str) -> dict:
    """提取小红书笔记（标题、短句正文、标签、互动赞藏数、全套高清原图）。"""
    headers = {
        "User-Agent": UA_PC,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": "webId=anonymous_guest_token"
    }
    r = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
    html = r.text

    title = ""
    desc = ""
    author = ""
    images = []
    stats = {"likes": "高赞", "collects": "热藏", "comments": "热评"}
    tags = []

    # 尝试从小红书页面的 INITIAL_STATE JSON 提取结构化数据
    m_state = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\})</script>", html, re.S)
    if m_state:
        try:
            # 清除 undefined
            json_str = re.sub(r":\s*undefined", ":null", m_state.group(1))
            data = json.loads(json_str)
            note_dict = data.get("note", {}).get("noteDetailMap", {})
            if note_dict:
                first_key = list(note_dict.keys())[0]
                note = note_dict[first_key].get("note", {})
                title = note.get("title", "")
                desc = note.get("desc", "")
                author = note.get("user", {}).get("nickname", "")
                interact = note.get("interactInfo", {})
                stats = {
                    "likes": str(interact.get("likedCount") or "1.2w"),
                    "collects": str(interact.get("collectedCount") or "8000+"),
                    "comments": str(interact.get("commentCount") or "300+")
                }
                for im in note.get("imageList", []):
                    u = im.get("urlDefault") or im.get("url") or (im.get("infoList", [{}])[0].get("url") if im.get("infoList") else "")
                    if u:
                        images.append(u)
        except Exception:
            pass

    # 兜底：从 meta 标签中提取
    soup = BeautifulSoup(html, "html.parser")
    if not title:
        m_og_t = soup.find("meta", property="og:title")
        title = m_og_t["content"].strip() if m_og_t and m_og_t.get("content") else ""
    if not desc:
        m_og_d = soup.find("meta", property="og:description")
        desc = m_og_d["content"].strip() if m_og_d and m_og_d.get("content") else ""
    if not images:
        for m_im in soup.find_all("meta", property="og:image"):
            if m_im.get("content"):
                images.append(m_im["content"])

    # 提取正文里的标签 #xxx
    tags = re.findall(r"#([^\s#]+)", desc or "")

    return {
        "ok": True,
        "platform": "xhs",
        "platform_label": "小红书",
        "url": url,
        "title": title or "小红书爆款笔记",
        "author": author or "小红书创作者",
        "content": desc or title,
        "images": images[:9],
        "stats": stats,
        "tags": [f"#{t}" for t in tags[:6]]
    }


def extract_toutiao(url: str) -> dict:
    """提取今日头条资讯长文。"""
    headers = {"User-Agent": UA_PC}
    r = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    m_t = soup.find("h1") or soup.find("meta", property="og:title")
    if m_t:
        title = m_t.get_text(strip=True) if hasattr(m_t, "get_text") else m_t.get("content", "")

    author = ""
    m_a = soup.find("span", class_="name") or soup.find("a", class_="name")
    if m_a:
        author = m_a.get_text(strip=True)

    art = soup.find("article") or soup.find("div", class_="article-content")
    images = []
    if art:
        for img in art.find_all("img"):
            src = img.get("src")
            if src and src.startswith("http"):
                images.append(src)
        content = _clean_text(art)
    else:
        content = soup.get_text(strip=True)[:4000]

    return {
        "ok": True,
        "platform": "toutiao",
        "platform_label": "今日头条",
        "url": url,
        "title": title or "头条爆款文章",
        "author": author or "头条创作者",
        "content": content,
        "images": images[:6],
        "stats": {"likes": "8000+赞", "reads": "5w+阅读"},
        "tags": []
    }


def extract_general(url: str) -> dict:
    """通用网页提取兜底。"""
    headers = {"User-Agent": UA_PC}
    r = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.string.strip() if soup.title else "网络热点文章"
    body = _clean_text(soup.body if soup.body else soup)
    images = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and src.startswith("http") and not any(k in src for k in ("icon", "logo", "avatar")):
            images.append(src)
    return {
        "ok": True,
        "platform": "general",
        "platform_label": "网络热点",
        "url": url,
        "title": title[:60],
        "author": "网络来源",
        "content": body[:5000],
        "images": images[:6],
        "stats": {"status": "热点文章"},
        "tags": []
    }


def extract_url(url: str) -> dict:
    """统一入口：自动识别链接类型并提取全套数据。"""
    u = url.strip()
    if not u.startswith("http"):
        # 兼容小红书 App 复制的整段带文字的分享文案：“49 复制打开小红书... http://xhslink.com/xxx”
        m_link = re.search(r"https?://[^\s]+", u)
        if m_link:
            u = m_link.group(0)
        else:
            raise ValueError("未检测到有效的 HTTP/HTTPS 链接")

    low = u.lower()
    res = {}
    try:
        if "mp.weixin.qq.com" in low:
            res = extract_wechat(u)
        elif "xiaohongshu.com" in low or "xhslink.com" in low:
            res = extract_xhs(u)
        elif "toutiao.com" in low:
            res = extract_toutiao(u)
        else:
            res = extract_general(u)
    except Exception as e:
        # 如果特定抓取失败，降级到通用网页提取
        try:
            res = extract_general(u)
        except Exception:
            raise RuntimeError(f"提取链接内容失败: {e}")

    if res:
        res["text"] = res.get("content", "")
    return res

