"""排版 Agent：用 md2wechat 的主题提示词让 LLM 产出微信兼容行内样式 HTML。

主题库：skills/themes/*.yaml（源自 geekjourneyx/md2wechat-skill，15 套）。
LLM 失败时回落 core/themes.md_to_wechat_html 规则渲染。

图片机制（防重复插图的硬保证）：
- 提示词只允许模型写占位符 [[IMG:i]]，每张图恰好一次
- 渲染后统一消毒：删光模型自插的 <img>，占位符各替换一次真实 <img>
- 未被放置的图自动补到最后；规则渲染回落路径同样只插给定图片
"""
import re
from pathlib import Path

import yaml

from core.themes import md_to_wechat_html

THEMES_DIR = Path(__file__).resolve().parent.parent / "skills" / "themes"
IMG_STYLE = "width:100%;border-radius:12px;margin:16px 0;display:block;"


def list_themes() -> dict:
    """{key: {"name","description"}}"""
    out = {}
    if THEMES_DIR.exists():
        for f in sorted(THEMES_DIR.glob("*.yaml")):
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                out[f.stem] = {"name": d.get("description") or d.get("name", f.stem),
                               "has_prompt": bool(d.get("prompt"))}
            except Exception:
                continue
    return out


def _theme_prompt(key: str) -> str | None:
    f = THEMES_DIR / f"{key}.yaml"
    if not f.exists():
        return None
    d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return d.get("prompt")


def _strip_fence(text: str) -> str:
    m = re.search(r"<!doctype html.*?</html>|<html.*?</html>|<div.*", text, re.S | re.I)
    return m.group(0) if m else text


def render(body_md: str, title: str, theme: str = "caozhou", meta: str = "一幕·YIMU 爆款工作室",
           images: dict | None = None, cover: str | None = None, use_llm: bool = False) -> str:
    """排版渲染引擎：默认采用 100% 保真纯规则排版（零篡改、零大模型延迟、毫秒级响应）。"""
    if not use_llm:
        html = md_to_wechat_html(body_md, title, theme=theme, meta=meta, images=images)
        return _inject_cover(html, cover)

    from core import agents
    prompt = _theme_prompt(theme)
    if not prompt:
        html = md_to_wechat_html(body_md, title, theme=theme, meta=meta, images=images)
        return _inject_cover(html, cover)
    # 图片清单：0 号=封面（若有），其余=小节配图
    img_list = []
    if cover:
        img_list.append((cover, "封面主视觉，放在标题与引言之后"))
    for t, u in (images or {}).items():
        img_list.append((u, f"配图，插入到小节「{t}」的末尾"))
    img_note = ""
    if img_list:
        lines = "\n".join(f"- [[IMG:{i}]] {desc}" for i, (_, desc) in enumerate(img_list))
        img_note = ("\n\n【配图位置标记（重要，必须遵守）】\n"
                    f"{lines}\n"
                    "在 HTML 中需要插图的位置写下对应的占位符文本（如 [[IMG:0]]），"
                    "每张图恰好使用一次；禁止自己输出任何 <img> 标签；不要发明其它图片。")
    try:
        raw = agents.chat_for("layout", [
            {"role": "user", "content":
                f"{prompt}\n\n【文章标题】{title}\n【副标题署名】{meta}\n"
                f"【正文 markdown】\n{body_md}{img_note}\n\n只输出最终 HTML，不要解释。"}],
            temperature=0.3, timeout_s=15)
        html = _strip_fence(raw)
        if "<div" in html or "<p" in html:
            return _wechat_compat(_materialize_images(html, img_list, images or {}))
    except Exception:
        pass
    html = md_to_wechat_html(body_md, title, theme=theme, meta=meta, images=images)
    return _inject_cover(html, cover)


def _materialize_images(html: str, img_list: list, images: dict | None = None) -> str:
    """确定性图文交错（不信任模型摆图）：

    1. 删光模型自插的 <img> 和占位符；
    2. 封面插在第一段之后；
    3. 小节配图优先匹配标题对应的小节，匹配不到就按顺序轮转分配到未占用的小节；
    4. 全部插在小节标题之后 → 文字图片严格交替。
    """
    html = re.sub(r"<img[^>]*>/?>", "", html)
    html = re.sub(r"\[\[IMG:\d+\]\]", "", html)
    heads = [(m.start(), m.end(), re.sub(r"<[^>]+>", "", m.group(0)))
             for m in re.finditer(r"<h[23][^>]*>.*?</h[23]>", html, re.S)]
    url2title = {u: t for t, u in (images or {}).items()}

    def _norm(x: str) -> str:
        return re.sub(r"[\s#*·、，,。！!？?：:（）()「」]", "", x or "")

    inserts = []
    rest = list(img_list)
    # 封面：第一段之后
    if rest and "封面" in rest[0][1]:
        m = re.search(r"</p>", html)
        pos = m.end() if m else 0
        inserts.append((pos, f"<img src='{rest[0][0]}' style='{IMG_STYLE}'/>"))
        rest = rest[1:]
    # 小节图：标题匹配 → 轮转分配
    taken = set()
    assigns = []
    unmatched = []
    for url, _ in rest:
        title = _norm(url2title.get(url, ""))[:10]
        hit = -1
        for hi, (_, _, txt) in enumerate(heads):
            if hi in taken:
                continue
            t = _norm(txt)[:10]
            if title and (title in t or t in title):
                hit = hi
                break
        if hit >= 0:
            assigns.append((hit, url))
            taken.add(hit)
        else:
            unmatched.append(url)
    for url in unmatched:
        for hi in range(len(heads)):
            if hi not in taken:
                assigns.append((hi, url))
                taken.add(hi)
                break
    for hi, url in sorted(assigns):
        inserts.append((heads[hi][1], f"<img src='{url}' style='{IMG_STYLE}'/>"))
    for pos, tag in sorted(inserts, key=lambda x: -x[0]):
        html = html[:pos] + tag + html[pos:]
    return html


def _find_section_end(html: str, title: str) -> int:
    """找到包含小节标题文字的 h2/h3 标签结束位置（在其后插图）。"""
    for tag in ("h3", "h2"):
        for m in re.finditer(rf"<{tag}[^>]*>.*?</{tag}>", html, re.S):
            if title[:12] in re.sub(r"<[^>]+>", "", m.group(0)):
                return m.end()
    return -1


def _wechat_compat(html: str) -> str:
    """微信兼容消毒：公众号编辑器不支持 flex/grid 布局，替换为 block + 间距。"""
    html = re.sub(r'display\s*:\s*flex[^;"]*', 'display:block', html, flags=re.I)
    html = re.sub(r'display\s*:\s*grid[^;"]*', 'display:block', html, flags=re.I)
    html = re.sub(r'\bgap\s*:\s*[^;"]+;?', '', html, flags=re.I)
    html = re.sub(r'justify-content\s*:\s*[^;"]+;?', '', html, flags=re.I)
    html = re.sub(r'align-items\s*:\s*[^;"]+;?', '', html, flags=re.I)
    html = re.sub(r'flex(-direction)?\s*:\s*[^;"]+;?', '', html, flags=re.I)
    return html


def _inject_cover(html: str, cover: str | None) -> str:
    """规则渲染路径：封面图插到署名行之后。"""
    if not cover:
        return html
    tag = f"<img src='{cover}' style='{IMG_STYLE}'/>"
    m = re.search(r"<p[^>]*>[^<]*</p>", html)
    if m:
        return html[:m.end()] + tag + html[m.end():]
    return html + tag
