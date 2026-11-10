# SPDX-License-Identifier: BUSL-1.1
"""成稿净化引擎（Text Purity）—— 成品正文与标题的"零符号杂音"总闸。

设计目标（来自产品要求，非技术取舍）：

* 成品里**只允许**两类标记：中文语句标点（，。！？：；——……「」（））与
  话题标签（`#话题`，仅限单个 `#` 直接跟话题词）。
* 其余一律视为噪音：`**加粗**`、`### 标题`、`- 列表`、`> 引用`、表格 `|`、
  `[文字](链接)`、行内 `` `code` ``、`~~删除线~~`、`***分割线***`、HTML 标签、
  零宽字符等。
* 图片语法 `![alt](url)` 与裸 URL 属于"内容"而非"噪音"，必须原样保留——
  公众号/小红书排版要靠它出图。

## 两种形态，不能混用（V10.3 架构纠偏）

产品要求是「**成品**不能有符号杂音」，不是「数据不能有 Markdown」。二者必须分开：

| 形态 | 函数 | 用在哪 | 是否保留 `**` |
|------|------|--------|---------------|
| 存储态 | :func:`to_storage` | 数据库 `drafts.body_md`、`.md` 源文件 | **保留** |
| 纯文本成品 | :func:`purify_body` | 卡片图、小红书/微博文案、复制、导出、raw 接口 | 剥掉 |
| 富文本成品 | `core.themes.md_to_wechat_html` | 公众号 HTML | 转成 `<strong>` |

为什么存储态必须保留 `**`：公众号成品的加粗，正是靠渲染时把 `**x**` 转成
`<strong>x</strong>` 得来的。数据层一旦把标记剥掉，加粗能力就**永久丢失**，
再高明的渲染器也变不回来。所以符号的清除必须发生在**每一个展示出口**，
而不是把源头洗干净。卡片图属于「纯文本成品」——图片上的字没法加粗，
星号只会被原样印在图上，因此那里必须走 :func:`purify_body`。

函数必须**幂等**：重复调用不改变已处理的文本。
"""
from __future__ import annotations

import html
import re

# ── 保护性 token ────────────────────────────────────────────────────
# 用私用区字符做占位，避免与正文任何可见字符冲突，也避免被后续正则误伤。
_SAFE = "\ue000{}\ue001"
_SAFE_RE = re.compile(r"\ue000(\d+)\ue001")

#: 必须原样保留的片段：Markdown 图片 / 裸 URL
_KEEP_RE = re.compile(r"!\[[^\]]*\]\([^)\s]*\)|https?://[^\s<>\"'）)】]+")

#: 独占一行的分割线（***、---、___、* * *）
_DIVIDER_RE = re.compile(r"^\s*(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})\s*$")

#: 标题行 `### xxx`
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s*(.+?)\s*#*\s*$")

#: 行首列表/引用标记
_BULLET_RE = re.compile(r"^\s*(?:[-*+•·●▪◆※>＞]+\s*)+")

#: 纯话题标签行（`#自媒体 #干货`）——整行保留
_TAG_LINE_RE = re.compile(r"^\s*(?:#[^\s#]+[\s,，、]*)+$")

#: 行内话题标签（`#话题` 或成对的 `#话题#`）——保留
_INLINE_TAG_RE = re.compile(r"#[^\s#，。！？；：、（）()\[\]{}<>\"]{1,24}#?")

#: HTML 标签
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]{0,10}(?:\s[^<>]{0,120})?/?>")

#: HTML 实体
_ENTITY_MAP = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
}

#: 幕后制作说明行（配图/镜头/排版提示）——读者不该看到，整行丢弃
_META_LINE_RE = re.compile(
    r"^[【\[（(]?\s*(?:图\s*\d+|配图|封面图?|视觉|画面|镜头|分镜|版式|排版|设计说明|插图)"
    r"[^】\]）)\n]{0,80}[】\]）)]?$"
)

#: 零宽 / 控制字符（保留换行与制表）
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff\u00ad]")

#: 三个及以上连续换行
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

_CJK = r"\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef"


def _strip_markdown_marks(s: str) -> str:
    """清掉行内的强调/代码/删除线标记，只留文字。"""
    # 三星号 / 三下划线（加粗斜体）
    s = re.sub(r"\*{3,}(.+?)\*{3,}", r"\1", s)
    s = re.sub(r"(?<!\w)_{3,}(.+?)_{3,}(?!\w)", r"\1", s)
    # 双星号 / 双下划线（加粗）
    s = re.sub(r"\*{2,}(.+?)\*{2,}", r"\1", s)
    s = re.sub(r"(?<!\w)_{2,}(.+?)_{2,}(?!\w)", r"\1", s)
    # 删除线
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    # 行内代码
    s = re.sub(r"`+([^`]*)`+", r"\1", s)
    # 单星号斜体（要求两侧不是空白，避免误伤乘法与指针）
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", s)
    # 残余星号（中文正文里星号没有其他合法用途）
    s = re.sub(r"\*+", "", s)
    # 孤立的 ~~ 与反引号（不成对时上面两步清不掉）
    s = re.sub(r"~{2,}", "", s)
    s = s.replace("`", "")
    # 下划线只在紧邻中文时清掉，保留 `user_id` 这类标识
    s = re.sub(rf"_(?=[{_CJK}])", "", s)
    s = re.sub(rf"(?<=[{_CJK}])_", "", s)
    return s


def _strip_links(s: str) -> str:
    """`[文字](链接)` → `文字`；`[文字][ref]` → `文字`。"""
    s = re.sub(r"\[([^\[\]]{0,200})\]\((?:[^()\s]*)\)", r"\1", s)
    s = re.sub(r"\[([^\[\]]{0,200})\]\[[^\[\]]{0,80}\]", r"\1", s)
    return s


def _strip_tables(s: str) -> str:
    """表格竖线换成分隔逗号——保留信息，去掉符号。"""
    if s.count("|") < 2:
        return s
    # 对齐行 |---|:--:|
    if re.fullmatch(r"[\s|:\-]+", s):
        return ""
    cells = [c.strip() for c in s.strip().strip("|").split("|")]
    cells = [c for c in cells if c]
    return "，".join(cells)


def _normalize_punct(s: str) -> str:
    """把英文标点换成中文标点——仅在紧邻中文时替换，避免破坏数字、英文与版本号。"""
    # 省略号 / 破折号
    s = s.replace("...", "……").replace("。。。", "……")
    s = re.sub(r"(?<!-)-{2,}(?![-\d])", "——", s)
    # 逗号
    s = re.sub(rf"(?<=[{_CJK}]),\s*", "，", s)
    s = re.sub(rf",\s*(?=[{_CJK}])", "，", s)
    # 句号：避开小数点、版本号、域名
    s = re.sub(rf"(?<=[{_CJK}])\.(?!\d)(?=\s|$|[^\w])", "。", s)
    s = re.sub(rf"\.(?=[{_CJK}])", "。", s)
    # 分号 / 冒号
    s = re.sub(rf"(?<=[{_CJK}]);\s*", "；", s)
    s = re.sub(rf";\s*(?=[{_CJK}])", "；", s)
    s = re.sub(rf"(?<=[{_CJK}]):\s*", "：", s)
    s = re.sub(rf":\s*(?=[{_CJK}])", "：", s)
    # 问号 / 叹号（`\w` 在 Python 里会匹配中文，这里只排除 ASCII 标识符与 `!=` `!important`）
    s = re.sub(rf"(?<=[{_CJK}])\?(?![=A-Za-z0-9_])", "？", s)
    s = re.sub(rf"(?<=[{_CJK}])!(?![=A-Za-z0-9_])", "！", s)
    # 括号：仅当括号内含中文
    s = re.sub(rf"\(([^()]*[{_CJK}][^()]*)\)", r"（\1）", s)
    # 连续标点去重
    for mark in ("，", "。", "！", "？", "；", "：", "、"):
        s = re.sub(rf"{mark}{{2,}}", mark, s)
    s = s.replace("，。", "。").replace("。，", "。")
    return s


def _protect(text: str) -> tuple[str, list[str]]:
    """把图片、URL、话题标签替换成占位符，返回 (文本, 还原表)。"""
    kept: list[str] = []

    def _sub(m: re.Match) -> str:
        kept.append(m.group(0))
        return _SAFE.format(len(kept) - 1)

    text = _KEEP_RE.sub(_sub, text)
    text = _INLINE_TAG_RE.sub(_sub, text)
    return text, kept




def to_storage(text: str) -> str:
    """存储态清洗：**保留 Markdown 排版标记**，只清「结构性垃圾」。

    清除：`<think>` 思考块、YAML frontmatter、代码围栏行、HTML 标签、零宽字符、
          幕后制作说明行（【图1：…】【配图建议：…】）、3 个以上连续空行。
    保留：`**加粗**`、`## 标题`、`- 列表`、`> 引用`、`| 表格`、`[文字](链接)`、
          `![图片](url)`、`#话题` —— 这些是排版信息，渲染层要靠它们出效果。

    这是数据层（`drafts.body_md`、源 `.md`）唯一该用的清洗函数。
    文本能不能给读者看，由**展示出口**决定，不由这里决定。
    """
    if not text:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = _ZERO_WIDTH_RE.sub("", s)
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I)
    s = re.sub(r"^\s*---\s*\n[\s\S]*?\n---\s*\n", "", s)
    for ent, ch in _ENTITY_MAP.items():
        s = s.replace(ent, ch)
    # `<img src="x">` → `![图片](x)`，先于通用标签清理，避免把配图一起删掉
    s = re.sub(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"][^>]*/?>",
               lambda m: f"![图片]({m.group(1)})", s, flags=re.I)
    s = _HTML_TAG_RE.sub("", s)

    out: list[str] = []
    fence: list[str] | None = None
    for line in s.split("\n"):
        if line.strip().startswith("```"):
            if fence is None:
                fence = []
            else:
                out.extend(fence)
                fence = None
            continue
        if fence is not None:
            fence.append(line)
            continue
        # 幕后制作说明（【图1：…】）不是读者内容，存储层就丢掉，免得下游反复兜底
        if _META_LINE_RE.match(line.strip()):
            continue
        out.append(line.rstrip())
    if fence:
        out.extend(fence)

    cleaned = _MULTI_BLANK_RE.sub("\n\n", "\n".join(out)).strip()
    # V15.8 契约：模型自造的图片文件名（workflow.png 等）在落库前改写成
    # {{IMG:N}} 占位符，避免死链一路传到预览 HTML。真实地址与外链原样保留。
    try:
        from core.image_contract import storage_normalize
        return storage_normalize(cleaned)
    except Exception:
        return cleaned




def purify_body(text: str) -> str:
    """净化成品正文。幂等；空输入返回空串。"""
    if not text:
        return ""

    text = str(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _ZERO_WIDTH_RE.sub("", text)
    for ent, ch in _ENTITY_MAP.items():
        text = text.replace(ent, ch)

    # 模型思考标签、YAML frontmatter
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    text = re.sub(r"^\s*---\s*\n[\s\S]*?\n---\s*\n", "", text)

    # 代码围栏：去掉围栏行，保留围栏内文字（围栏内不参与后续符号清理）
    lines = text.split("\n")
    out: list[str] = []
    fence_buf: list[str] | None = None
    for line in lines:
        if line.strip().startswith("```"):
            if fence_buf is None:
                fence_buf = []
            else:
                out.extend(fence_buf)
                fence_buf = None
            continue
        if fence_buf is not None:
            fence_buf.append(line)
            continue
        out.append(line)
    if fence_buf:
        out.extend(fence_buf)

    kept: list[str] = []

    def _keep(m: re.Match) -> str:
        kept.append(m.group(0))
        return _SAFE.format(len(kept) - 1)

    result: list[str] = []
    for raw in out:
        s = raw.strip()
        if not s:
            result.append("")
            continue
        if _DIVIDER_RE.match(s):
            continue
        # 幕后制作说明（【图1：…】【配图建议：…】）不属于读者内容，整行丢弃
        if _META_LINE_RE.match(s):
            continue
        # 纯话题标签行原样保留
        if _TAG_LINE_RE.match(s):
            result.append(s)
            continue

        # 标题：### 小节 → 【小节】
        m_h = _HEADING_RE.match(s)
        if m_h and len(m_h.group(1)) >= 1:
            body = m_h.group(2).strip()
            body = _strip_markdown_marks(body)
            if not body:
                continue
            if body.startswith("【") and body.endswith("】"):
                s = body
            else:
                s = f"【{body}】"
        else:
            # 行首引用/列表标记
            s = _BULLET_RE.sub("", s)

        # ⚠️ 必须最先保护图片 / 裸 URL / 话题标签：
        #    `_strip_links` 会把 `![封面](url)` 拆成 `!封面`，`_normalize_punct` 会改写 URL 里的标点。
        s = _KEEP_RE.sub(_keep, s)
        s = _INLINE_TAG_RE.sub(_keep, s)

        s = _strip_markdown_marks(s)
        s = _HTML_TAG_RE.sub("", s)
        s = _strip_links(s)
        s = _strip_tables(s)
        if not s.strip():
            continue

        s = _normalize_punct(s)
        s = re.sub(r"[ \t]{2,}", " ", s).strip()
        result.append(s)

    text = "\n".join(result)

    def _restore_local(m: re.Match) -> str:
        idx = int(m.group(1))
        return kept[idx] if 0 <= idx < len(kept) else ""

    text = _SAFE_RE.sub(_restore_local, text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def purify_title(text: str) -> str:
    """净化标题：单行、无任何标记、无话题标签。"""
    if not text:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ").strip()
    s = _ZERO_WIDTH_RE.sub("", s)
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I)
    s = _HTML_TAG_RE.sub("", s)
    s = _HEADING_RE.sub(lambda m: m.group(2).strip(), s)
    s = _BULLET_RE.sub("", s)
    s = _strip_links(s)
    s = _strip_markdown_marks(s)
    # 标题里不该出现话题标签
    s = re.sub(r"#[^\s#]{1,24}", "", s)
    s = _normalize_punct(s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    # 只裁掉首尾的纯符号垃圾，保留 ！？ 等正常语尾标点
    s = s.strip(" 　\t#*_`~>|·•./\\")
    s = re.sub(r"^[,，。、；：:;]+", "", s)
    return s.strip()




def card_inline_html(text: str) -> str:
    """卡片（小红书图片）用行内 HTML 片段：**排版保留，画面零符号**。

    `**重点**` → `<b>重点</b>`（HTML 渲染路径下图上依然是加粗的），
    其余一切标记（`##`、`- `、`|`、`[]()`、反引号…）全部剥离——
    图片上的字一旦带上星号就是可见事故，且无法靠 CSS 补救。

    返回值已做 HTML 转义，可直接嵌入 `<p>` / `<div>`，调用方**不要**再 escape 一次。
    """
    if not text:
        return ""
    s = str(text)
    # 先把成对加粗换成私用区占位，避免被后面的一致性净化拆掉
    s = re.sub(r"\*\*(.+?)\*\*", "\ue010\\1\ue011", s)
    s = purify_body(s)
    s = html.escape(s, quote=False)
    return s.replace("\ue010", "<b>").replace("\ue011", "</b>")


def has_noise(text: str) -> bool:
    """检测文本是否残留噪音标记（供测试与自检使用）。"""
    if not text:
        return False
    noise = [
        r"\*\*",                     # 加粗
        r"^#{1,6}\s",                # Markdown 标题
        r"^\s*[-*+]\s",              # 列表符
        r"^\s*>\s",                  # 引用
        r"(?<!!)\[[^\]]*\]\([^)]*\)",  # 普通链接（图片语法 ![]() 不算）
        r"~~",                       # 删除线
        r"`",                        # 行内代码
    ]
    return any(re.search(pat, text, flags=re.M) for pat in noise)
