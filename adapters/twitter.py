"""
Twitter / 𝕏 平台排版与适配器
支持纯净直发文本清洗、单推金句卡片与 Thread 连击串推 (1/N ~ N/N) 排版渲染
"""
import re
import html


def clean_twitter_text(text: str) -> str:
    """
    清洗并纯净化 Twitter / 𝕏 文本：
    1. 彻底去除 Markdown 粗体 (**xx** / __xx__) 与斜体 (*xx* / _xx_)，杜绝星号噪音；
    2. 彻底去除 Markdown 标题语法 (# xxx, ## xxx, ### xxx)，杜绝井号堆叠；
    3. 彻底去除多余的 AI 包装前后缀（如“【Twitter串推】”、“以下是推文：”、“如需发布请复制”等）；
    4. 严格控制 Hashtag 数量：避免大面积堆砌标签，全文/单条末尾最多保留 1~2 个精准标签；
    5. 规范推文间分割线与段落呼吸感，确保复制即发，零干扰。
    """
    if not text:
        return ""

    # 1. 移除 AI 开头前言与结尾废话
    text = re.sub(
        r'^(?:(?:以下是|为你生成的|根据母稿|矩阵派生|【Twitter.*?】|【𝕏.*?】|Twitter Thread|推文串|🧵.*?Thread).*?[:：]?\s*\n+)+',
        '', text, flags=re.IGNORECASE
    )
    text = re.sub(
        r'\n+(?:(?:以上是|如需发布|希望对您有帮助|复制上方|点击复制).*?)$',
        '', text, flags=re.IGNORECASE
    )

    # 2. 移除推文包装方括号标签如 【推文 1】、【Tweet 1】等
    text = re.sub(r'【(?:推文\s*\d+|Tweet\s*\d+)】[:：]?', '', text, flags=re.IGNORECASE)

    # 3. 彻底清除 Markdown 粗体、斜体、删除线、下划线中的星号与符号
    text = re.sub(r'\*\*\*(.*?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'___(.*?)___', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'~~(.*?)~~', r'\1', text)

    # 4. 移除 Markdown 标题标记（行首的 #、##、###）并转换星号列表项
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # 识别独立分割线
        if stripped in ["---", "***", "___", "– – –", "——"]:
            cleaned_lines.append("---")
            continue
        # 去除行首的 ### 或 #（Markdown 标题语法）
        cleaned = re.sub(r'^\s*#{1,6}\s+', '', line)
        # 将行首星号列表转换为清爽的项目符号 •
        cleaned = re.sub(r'^\s*[*]\s+', '• ', cleaned)
        # 去除行内任何残留的孤立星号
        cleaned = re.sub(r'\*+', '', cleaned)
        cleaned_lines.append(cleaned)
    text = "\n".join(cleaned_lines)

    # 5. 清洗过度堆砌的 Hashtag 井号（连续超过 2 个的 hashtag 压缩为最多 2 个）
    def limit_hashtags(match):
        full_match = match.group(0)
        ws_match = re.search(r'[\r\n\s]+$', full_match)
        trailing_ws = ws_match.group(0) if ws_match else ''
        tags = re.findall(r'#[^\s#]+', full_match)
        return ' '.join(tags[:2]) + trailing_ws
    text = re.sub(r'(?:#[^\s#]+[\s\r\n]*){3,}', limit_hashtags, text)

    # 6. 清理多余连续空行
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def clean_single_tweet(t: str) -> str:
    """清理单条推文，去除分割线与多余符号，确保复制后可直接在 X 发布"""
    t = clean_twitter_text(t)
    # 移除行首可能残留的推文标记如 "Tweet 1:"
    t = re.sub(r'^(?:Tweet\s*\d+[:：]?|【推文\s*\d+】[:：]?)\s*', '', t, flags=re.IGNORECASE)
    # 移除分割线
    lines = [line for line in t.split("\n") if line.strip() not in ["---", "***", "___"]]
    return "\n".join(lines).strip()


def parse_twitter_thread(content: str) -> list[dict]:
    """
    将 Twitter 派生文本解析为纯净推文列表 (Thread)
    支持格式：1/N 序号、--- 分割线 或段落自适应拆分
    """
    cleaned_content = clean_twitter_text(content)
    if not cleaned_content:
        return []

    lines = cleaned_content.strip().split("\n")
    tweets = []
    current_tweet = []

    # 正则检测推文开头，如 "1/", "1/8", "[1/8]", "1️⃣", "1."
    tweet_start_pattern = re.compile(
        r'^(?:(?:\d+[\/／]\d*)|(?:\[\d+[\/／]\d*\])|(?:\d+[\.、]\s*)|(?:[1-9]️⃣))\s*',
        re.IGNORECASE
    )

    for line in lines:
        stripped = line.strip()
        if stripped == "---" or stripped == "___" or stripped == "***":
            if current_tweet:
                raw_t = "\n".join(current_tweet).strip()
                if raw_t:
                    tweets.append(clean_single_tweet(raw_t))
                current_tweet = []
            continue

        match = tweet_start_pattern.match(stripped)
        if match and current_tweet and len("\n".join(current_tweet).strip()) > 30:
            raw_t = "\n".join(current_tweet).strip()
            if raw_t:
                tweets.append(clean_single_tweet(raw_t))
            current_tweet = [stripped]
        else:
            current_tweet.append(line)

    if current_tweet:
        raw_t = "\n".join(current_tweet).strip()
        if raw_t:
            tweets.append(clean_single_tweet(raw_t))

    # 如果拆分结果只有一条且篇幅较长，按双换行段落尝试拆分成 240 字符左右的 Thread
    if len(tweets) <= 1 and len(cleaned_content) > 320:
        paras = [p.strip() for p in cleaned_content.split("\n\n") if p.strip()]
        if len(paras) > 1:
            tweets = []
            chunk = []
            for p in paras:
                if sum(len(x) for x in chunk) + len(p) > 220 and chunk:
                    tweets.append(clean_single_tweet("\n\n".join(chunk)))
                    chunk = [p]
                else:
                    chunk.append(p)
            if chunk:
                tweets.append(clean_single_tweet("\n\n".join(chunk)))

    result = []
    total = len(tweets)
    for idx, t in enumerate(tweets, 1):
        clean_t = clean_single_tweet(t)
        char_count = len(clean_t)
        result.append({
            "index": idx,
            "total": total,
            "content": clean_t,
            "char_count": char_count,
            "is_hook": (idx == 1),
            "is_cta": (idx == total and total > 1)
        })
    return result


def format_pure_twitter_export(content: str) -> str:
    """导出用于一键复制的完整纯净推文串（无任何 Markdown 噪音或头尾包装）"""
    thread = parse_twitter_thread(content)
    if not thread:
        return clean_twitter_text(content)
    return "\n\n---\n\n".join(t["content"] for t in thread)


def render_twitter_html(content: str, title: str = "") -> str:
    """
    渲染 Twitter / 𝕏 现代深色/浅色卡片预览流
    推文纯净无 Markdown 噪音，支持单条与全串 100% 纯净复制
    """
    thread = parse_twitter_thread(content)
    if not thread:
        return "<div class='text-zinc-500 p-8 text-center'>暂无 Twitter 推文内容</div>"

    cards_html = []
    total = len(thread)

    for t in thread:
        idx = t["index"]
        clean_text = t["content"]
        escaped_for_display = html.escape(clean_text)

        # 高亮 Hashtag 和 @mention 用于卡片美化
        escaped_for_display = re.sub(
            r'(#[\w\u4e00-\u9fa5]+)',
            r'<span class="text-sky-400 font-medium">\1</span>',
            escaped_for_display
        )
        escaped_for_display = re.sub(
            r'(@[\w_]+)',
            r'<span class="text-sky-400 font-medium">\1</span>',
            escaped_for_display
        )
        formatted_body = escaped_for_display.replace("\n", "<br>")

        badge = ""
        if t["is_hook"]:
            badge = '<span class="px-2 py-0.5 text-[11px] font-bold rounded bg-sky-500/20 text-sky-400 border border-sky-500/30">🔥 Hook 破题推</span>'
        elif t["is_cta"]:
            badge = '<span class="px-2 py-0.5 text-[11px] font-bold rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">🎯 CTA 结尾推</span>'
        else:
            badge = f'<span class="px-2 py-0.5 text-[11px] font-medium rounded bg-zinc-800 text-zinc-400 border border-zinc-700">{idx}/{total}</span>'

        # 安全转义内容供 data 属性使用，直接读取属性可获纯净原始文本
        safe_copy_text = html.escape(clean_text, quote=True)

        card = f"""
        <div class="twitter-tweet-card relative bg-[#11161d] border border-zinc-800/80 rounded-2xl p-4.5 mb-3.5 hover:border-zinc-700 transition-all shadow-sm">
            <div class="flex items-center justify-between mb-2.5">
                <div class="flex items-center gap-2.5">
                    <div class="w-9 h-9 rounded-full bg-gradient-to-tr from-sky-600 to-indigo-600 flex items-center justify-center font-bold text-white text-xs shadow-inner">𝕏</div>
                    <div>
                        <div class="flex items-center gap-1.5">
                            <span class="font-bold text-zinc-100 text-sm">一幕创作者</span>
                            <span class="text-sky-400 text-xs">✓</span>
                            <span class="text-zinc-500 text-xs">@yimu_creator</span>
                        </div>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    {badge}
                    <button onclick="navigator.clipboard.writeText(this.getAttribute('data-tweet')); if(typeof showToast==='function'){{showToast('已复制第 {idx} 条纯净推文');}}else if(typeof toast==='function'){{toast('已复制第 {idx} 条纯净推文');}}" data-tweet="{safe_copy_text}" class="text-xs px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 transition-colors flex items-center gap-1" title="复制单条纯净内容（直接粘贴发布）">
                        <span>📋</span> <span>复制</span>
                    </button>
                </div>
            </div>
            <div class="text-[14.5px] leading-relaxed text-zinc-200 font-sans select-text whitespace-pre-line break-words">
                {formatted_body}
            </div>
            <div class="mt-3.5 pt-2.5 border-t border-zinc-850 flex items-center justify-between text-xs text-zinc-500 font-mono">
                <span>{t['char_count']} 字符</span>
                <div class="flex items-center gap-4 text-zinc-500">
                    <span>💬 12</span>
                    <span>🔁 48</span>
                    <span>❤️ 196</span>
                    <span>📊 4.2k</span>
                </div>
            </div>
        </div>
        """
        cards_html.append(card)

    return "\n".join(cards_html)

