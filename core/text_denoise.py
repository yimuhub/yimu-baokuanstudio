"""
文本去噪与排版规范化引擎（Text Denoise Engine）- V9.4.5 澄音境 / Pristine Rhythm

核心职责：
1. 彻底清除正文中的 ***、---、___、* * * 等粗糙分割线标记；
2. 规范化星号标记：将 ***文本*** (加粗斜体) 降噪为标准的 **文本** (加粗)，清理行首行尾及孤立的 *** 符号；
3. 规范化标题与小节标记：
   - 杜绝正文充斥 ### / ## / #### 等粗糙的 Markdown 符号；
   - 带有中文序号或数字序号的标题（如 `### 一、核心观点` 或 `### 1. 实战指南`）平滑转换为自然编号或 `【1. 实战指南】`；
   - 无序号的普通小节标题（如 `### 核心优势`）规范化转为高颜值 `【核心优势】`；
   - 去除 4 级及以上标题的 # 符号；
4. 规范化 # 符号边界：
   - 严格且仅保留合法的文末话题标签（如 `#自媒体 #写作`、`#标签1，#标签2`）与成对社交话题（如 `#今日热点#`）；
   - 正文混杂的孤立无意义 #（如 `关于#AI 的演进`、`第#1点`）进行无损去噪；
5. 提供统一的小节提取与判定函数（is_section_heading, extract_section_title, extract_section_headings），
   确保排版与配图引擎无需依赖 ### 也能精准对齐小节。
"""
from __future__ import annotations

import re

# 独占一行的分割线匹配（***、---、___、* * * 等）
DIVIDER_RE = re.compile(r"^\s*(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})\s*$")

# 纯话题标签行（例如 #自媒体 #爆款 #深度思考）
TAG_LINE_RE = re.compile(r"^\s*(?:#[^\s#]+[\s,，、]*)+$")

# 成对出现的社交媒体话题标签（例如 #今日热点#）
PAIRED_TOPIC_RE = re.compile(r"#[^#\s\n]{2,30}#")

# 中文及序号开头的小节标题（如 一、xxx、1. xxx、第一章 xxx、（一）xxx）
CHINESE_NUMBERED_HEADING_RE = re.compile(
    r"^(?:第[一二三四五六七八九十0-9]+[章节篇部分]|(?:[一二三四五六七八九十]+)[、.．]|（[一二三四五六七八九十\d]+）)\s*[\u4e00-\u9fa5\w\s]{2,40}$"
)

# 标准方头括号标题（如 【核心优势】）
BRACKET_HEADING_RE = re.compile(r"^【.+?】$")


def is_section_heading(line: str) -> bool:
    """判定某行是否为文章小节标题（小节标题为 H2/H3/H4、方头括号与中文序号标题，不含文章主标题 H1 '# '）。"""
    if not line:
        return False
    s = line.strip()
    if not s:
        return False
    # 如果是纯标签行，不算小节标题
    if TAG_LINE_RE.match(s):
        return False
    # Markdown 小节标题语法（仅匹配 H2/H3/H4，不匹配主标题 H1 '# '）
    if s.startswith("### ") or s.startswith("## ") or s.startswith("#### "):
        return True
    # 方头括号小节（2~45字内）
    if s.startswith("【") and s.endswith("】") and 2 <= len(s) <= 45:
        return True
    # 中文序号或章节小节
    if CHINESE_NUMBERED_HEADING_RE.match(s):
        return True
    return False


def extract_section_title(line: str, strip_brackets: bool = False) -> str:
    """从标题行中提取纯净的小节名称，默认保留【】以便统一排版，可按需剥离。"""
    if not line:
        return ""
    s = line.strip()
    # 剥离 Markdown # 标记
    s = re.sub(r"^#{1,6}\s*", "", s).strip()
    if strip_brackets:
        s = s.strip("【】").strip()
    return s


def denoise_body_text(text: str) -> str:
    """全系统级正文深度去噪清洗引擎：
    - 消除粗糙分割线（***、---、___）；
    - 规范化 ***加粗斜体*** 为标准 **加粗**，清理残余 ***；
    - 标题降噪：剥离 ### / ## 符号，转换为自然序号或【小节标题】；
    - 严格保留文末话题标签（#标签）与成对社交话题（#话题#），消除正文中混杂的孤立 #。
    """
    if not text:
        return ""

    # 1. 预处理：降级三星号 ***文本*** 为标准加粗 **文本**
    text = re.sub(r"\*{3,}(.+?)\*{3,}", r"**\1**", text)
    text = re.sub(r"_{3,}(.+?)_{3,}", r"**\1**", text)
    text = re.sub(r"\*{3}(.+?)\*{2}", r"**\1**", text)
    text = re.sub(r"\*{2}(.+?)\*{3}", r"**\1**", text)

    lines = text.splitlines()
    out_lines: list[str] = []
    in_code_fence = False

    for line in lines:
        s = line.strip()

        # 保护代码块中的内容（不改动代码注释或缩进）
        if s.startswith("```"):
            in_code_fence = not in_code_fence
            out_lines.append(line)
            continue
        if in_code_fence:
            out_lines.append(line)
            continue

        if not s:
            out_lines.append("")
            continue

        # 2. 剔除独占一行的分割线（***、---、___、* * * 等）
        if DIVIDER_RE.match(s):
            continue

        # 3. 检查是否为纯标签行（如 #自媒体 #干货 #AI），纯标签行完整保留
        if TAG_LINE_RE.match(s):
            out_lines.append(s)
            continue

        # 4. 标题行降噪与规范化（消除 ###、##、# 杂音）
        if s.startswith("#"):
            m_hdr = re.match(r"^(#{1,6})\s*(.*)$", s)
            if m_hdr:
                hdr_level = len(m_hdr.group(1))
                hdr_text = m_hdr.group(2).strip()
                # 带有中文序号或括号的自然标题直接保留自然形式
                if re.match(r"^(?:[一二三四五六七八九十]+[、.．]|（[一二三四五六七八九十\d]+）)", hdr_text):
                    s = hdr_text
                elif hdr_text.startswith("【") and hdr_text.endswith("】"):
                    s = hdr_text
                elif hdr_text:
                    s = f"【{hdr_text}】"
                else:
                    continue

        # 5. 清理孤立的三星号或残余星号杂质
        s = re.sub(r"(?<!\*)\*{3}(?!\*)", "", s)

        # 6. 正文内的 # 符号去噪：
        # 保护机制：保护成对话题（#话题#）、URL链接中的锚点(#anchor)、Markdown图片、以及末尾话题标签
        protected_items: list[str] = []

        def _protect(val: str) -> str:
            idx = len(protected_items)
            protected_items.append(val)
            return f"__SAFE_TOKEN_{idx}__"

        # 保护 URL
        s = re.sub(r"https?://[^\s<>\"\'\)]+", lambda m: _protect(m.group(0)), s)

        # 保护 Markdown 图片
        s = re.sub(r"!\[.*?\]\(.*?\)", lambda m: _protect(m.group(0)), s)

        # 保护成对社交媒体话题（如 #今日热点#）
        s = PAIRED_TOPIC_RE.sub(lambda m: _protect(m.group(0)), s)

        # 保护行尾连续的话题标签（如 ...。 #自媒体 #AI爆款）
        trailing_tags_m = re.search(r"((?:\s+#[^\s#]+)+)$", s)
        trailing_tags = ""
        if trailing_tags_m:
            trailing_tags = trailing_tags_m.group(1)
            s = s[:trailing_tags_m.start()]

        # 清理正文中混杂的孤立无意义 #（如 关于#AI的看法 -> 关于AI的看法；第#1条 -> 第1条）
        s = re.sub(r"#+([a-zA-Z0-9_\u4e00-\u9fa5]+)", r"\1", s)
        s = re.sub(r"#+", "", s)

        # 还原被保护的有效话题与链接
        if trailing_tags:
            s = s + trailing_tags
        for idx, item in enumerate(protected_items):
            s = s.replace(f"__SAFE_TOKEN_{idx}__", item)

        out_lines.append(s)

    cleaned_text = "\n".join(out_lines)
    # 消除多余连续空行
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()


def extract_section_headings(body_md: str) -> list[tuple[str, list[str]]]:
    """通读正文，提取所有小节及其正文段落列表（支持自然序号、方头括号与 Markdown 标题）。"""
    if not body_md:
        return []
    lines = body_md.splitlines()
    sec_meta: list[list] = []
    cur: list | None = None

    for line in lines:
        s = line.strip()
        if not s:
            continue
        if is_section_heading(s):
            title = extract_section_title(s, strip_brackets=False)
            cur = [title, []]
            sec_meta.append(cur)
        elif cur is not None and s:
            # 去除列表符号（仅匹配单个 - / • / * 引导符），保留纯净文本
            clean_para = re.sub(r"^[\-•*]\s+", "", s).strip()
            cur[1].append(clean_para)

    return [(item[0], item[1]) for item in sec_meta]
