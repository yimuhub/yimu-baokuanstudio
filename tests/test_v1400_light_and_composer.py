# SPDX-License-Identifier: BUSL-1.1
"""V14 亮色模式 + WorkBuddy 风格输入框回归门禁。

锁死本轮四类修复，任何一个回退都会在这里红：

1. **亮色语义 token**：三栏 V2 壳层用了 7 个 ``var(--xxx, 深色兜底)``，
   但它们一直没在 ``:root`` / ``[data-theme="light"]`` 里定义，导致亮色模式下
   左栏选中项是「深底压深字」（实测对比度 1.06）、空态引导卡与输入条整块发黑。
2. **发送键几何**：``#btn-copilot-send`` 是 flex 子项，曾被 textarea 撑成 28×42，
   ``border-radius:50%`` 在非正方形上变成椭圆。现在必须锁定 32×32 正圆。
3. **composer 三件套**：附件 / 模型直选 / 提示词优化，缺一个就不是 WorkBuddy 形态。
4. **提示词优化不许无限等**：必须有 max_tokens 上限、总时间预算与结果缓存。
   历史问题是推理型模型把 token 全烧在思维链上，正文为空，一次调用卡满 45 秒。
"""
from __future__ import annotations

import inspect
import io
import re
import zipfile
from pathlib import Path

import pytest

# 亮色模式必须显式给出的语义 token —— 缺任何一个都会落回深色兜底值
LIGHT_TOKENS = [
    "--card2",
    "--border2",
    "--border3",
    "--text-dim",
    "--active",
    "--hover",
    "--accbg",
]

# 深色兜底值：亮色块里出现这些说明只是复制了旧值，等于没修
DARK_FALLBACK_VALUES = {"#0f1621", "#26313f", "#33415a", "#161d29"}


@pytest.fixture(scope="module")
def html() -> str:
    from web.admin import get_html_page

    page = get_html_page()
    assert "<html" in page.lower(), "模板渲染异常，拿不到完整页面"
    return page


def _light_blocks(html: str) -> list[str]:
    """抽出所有 [data-theme="light"] 声明块的声明体。"""
    pattern = r'\[data-theme=["\']light["\']\][^{]*\{([^{}]*)\}'
    return re.findall(pattern, html)


# ── 1. 亮色主题 token ──────────────────────────────────────────────────────


def test_light_theme_blocks_exist(html: str) -> None:
    """亮色主题必须真的有样式块，否则下面所有断言都失去意义。"""
    blocks = _light_blocks(html)
    assert blocks, "找不到任何 [data-theme=\"light\"] CSS 块"


def test_light_theme_declares_all_semantic_tokens(html: str) -> None:
    """7 个 v2 语义 token 必须在亮色块里有显式值。"""
    merged = "\n".join(_light_blocks(html))
    missing = [t for t in LIGHT_TOKENS if not re.search(re.escape(t) + r"\s*:", merged)]
    assert not missing, f"亮色主题缺少这些 token，会落回深色兜底导致低对比: {missing}"


def test_light_tokens_are_not_dark_fallbacks(html: str) -> None:
    """亮色 token 的值不能照抄深色兜底值（那就是没改）。"""
    merged = "\n".join(_light_blocks(html))
    offenders = []
    for token in LIGHT_TOKENS:
        m = re.search(re.escape(token) + r"\s*:\s*([^;]+);", merged)
        if not m:
            continue
        value = m.group(1).strip().lower()
        if value in DARK_FALLBACK_VALUES:
            offenders.append(f"{token}={value}")
    assert not offenders, f"这些亮色 token 仍沿用深色值: {offenders}"


def test_root_defines_v2_tokens_so_dark_mode_is_stable(html: str) -> None:
    """:root 也要有默认值，避免深色模式下同样落到无定义兜底。"""
    blocks = re.findall(r":root\s*\{([^{}]*)\}", html)
    assert blocks, "找不到 :root 声明块"
    merged = "\n".join(blocks)
    missing = [t for t in LIGHT_TOKENS if not re.search(re.escape(t) + r"\s*:", merged)]
    assert not missing, f":root 缺少这些 token: {missing}"


# ── 2. 发送键必须是正圆 ────────────────────────────────────────────────────


def test_send_button_has_square_lock(html: str) -> None:
    """发送键必须同时有固定尺寸、aspect-ratio 与不可伸缩的 flex 基准。

    注意：模板里存在多条 #btn-copilot-send 规则（旧的 28px 那条仍保留给别处），
    这里要校验的是「真正生效的正圆规则」，所以按 aspect-ratio 反查所在声明块。
    """
    anchors = [m.start() for m in re.finditer(r"aspect-ratio\s*:\s*1\s*/\s*1", html)]
    assert anchors, "模板里没有任何 aspect-ratio: 1 / 1 规则"

    hit = None
    for pos in anchors:
        block = html[max(0, pos - 700): pos + 400]
        if "#btn-copilot-send" in block:
            hit = block
            break
    assert hit is not None, "aspect-ratio: 1 / 1 没有落在发送键的规则上"

    assert re.search(r"width\s*:\s*32px", hit), "缺少固定宽度 32px"
    assert re.search(r"height\s*:\s*32px", hit), "缺少固定高度 32px"
    assert re.search(r"flex\s*:\s*0\s+0\s+32px", hit), "缺少 flex: 0 0 32px，会被 textarea 拉高"
    assert re.search(r"border-radius\s*:\s*50%", hit), "缺少 border-radius: 50%"


def test_send_button_text_arrow_is_disabled(html: str) -> None:
    """旧实现用 ::after 塞文字箭头，会在小尺寸下错位；必须存在清空覆盖。"""
    assert re.search(
        r"#btn-copilot-send\.rail-send::after\s*\{\s*content:\s*none\s*!important;?\s*\}",
        html,
    ), "缺少 ::after { content: none !important } 覆盖，文字箭头会重新出现"


# ── 3. composer 结构三件套 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "needle",
    [
        'id="copilot-composer"',      # 外框
        'id="copilot-attach-list"',   # 附件 chip 容器
        'id="copilot-file-input"',    # 隐藏的文件选择器
        'id="copilot-model-quick"',   # 模型直选下拉
        'id="copilot-polish-btn"',    # 提示词优化
        'id="copilot-input"',         # 输入区
        'id="btn-copilot-send"',      # 发送
        'id="btn-copilot-stop"',      # 停止
    ],
)
def test_composer_has_required_parts(html: str, needle: str) -> None:
    assert needle in html, f"composer 缺少必要元素: {needle}"


def test_composer_accepts_documents_and_images(html: str) -> None:
    """附件选择器必须同时放行文档与图片。"""
    m = re.search(r'id="copilot-file-input"[^>]*accept="([^"]+)"', html)
    assert m, "文件选择器缺少 accept 白名单"
    accept = m.group(1)
    for ext in (".docx", ".pdf", ".txt", ".png"):
        assert ext in accept, f"accept 未放行 {ext}"


# ── 4. 两个新接口已注册 ────────────────────────────────────────────────────


def test_copilot_endpoints_registered() -> None:
    from web.admin import app

    from tests.wsb_common import iter_effective_routes
    paths = {getattr(r, "path", "") for r in iter_effective_routes(app)}
    assert "/api/copilot/attach" in paths, "附件解析接口未注册"
    assert "/api/copilot/polish_prompt" in paths, "提示词优化接口未注册"


# ── 5. 附件解析：docx 必须保留段落 ────────────────────────────────────────


def _mini_docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_docx_extraction_keeps_paragraph_breaks() -> None:
    """第一版实现把段内 <w:t> 直接 join，两段被拼成一行；这里锁死换行。"""
    from core import copilot_files

    info = copilot_files.extract("demo.docx", _mini_docx(["第一段内容", "第二段内容"]))
    assert info["kind"] == "docx"
    assert "第一段内容" in info["text"] and "第二段内容" in info["text"]
    assert "\n" in info["text"], "段落之间必须保留换行，不能拼成一行"


def test_plain_text_decodes_gbk() -> None:
    """Windows 复制来的 txt 常是 GBK，不能变乱码。"""
    from core import copilot_files

    info = copilot_files.extract("note.txt", "中文内容测试".encode("gb18030"))
    assert info["kind"] == "text"
    assert "中文内容测试" in info["text"]


def test_image_returns_kind_without_text() -> None:
    from core import copilot_files

    info = copilot_files.extract("pic.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    assert info["kind"] == "image"
    assert info["text"] == ""


# ── 6. 提示词优化：不许无限等 ──────────────────────────────────────────────


def test_polish_has_time_budget_and_token_cap() -> None:
    from core import prompt_polish as pp

    assert pp.LLM_MAX_TOKENS > 0, "必须给 max_tokens 上限，否则推理模型会写到上下文尽头"
    assert pp.LLM_MAX_TOKENS <= 1500, "上限过大等于没有上限"
    assert pp.TOTAL_BUDGET_S <= 30, "总预算过长，用户会以为按钮卡死"
    assert pp.LLM_TIMEOUT_S <= pp.TOTAL_BUDGET_S, "单次超时不能超过总预算"


def test_polish_prefers_direct_output_models() -> None:
    """改写链模型链契约（V15.9.1 更新）。

    旧实现硬编码 Agnes 测试模型作为「直出型优先链」；出厂配置清洗后默认链为空，
    只走「默认通道」（活动模型服务主模型——运营选择的主模型即直出型），
    仍允许用 YIMU_POLISH_MODELS 环境变量覆盖；正文过短时降级到模板补全，
    「直出」保障由模板兜底 + 运营主模型共同承担，不再依赖写死的测试模型。
    """
    from core import prompt_polish as pp

    assert pp.PREFERRED_MODELS == [], "出厂不得预置任何具体模型（Agnes 是测试通道）"
    src = Path("core/prompt_polish.py").read_text(encoding="utf-8")
    assert "YIMU_POLISH_MODELS" in src, "必须保留环境变量覆盖能力"


def test_polish_cache_roundtrip() -> None:
    from core import prompt_polish as pp

    key = ("门禁用的缓存文本", "xhs")
    pp._cache_put(key, {"text": "x" * 80, "source": "llm"})
    hit = pp._cache_get(key)
    assert hit is not None, "缓存写入后应能读到"
    assert hit["text"].startswith("xxx")

    pp._cache_put(("会过期的文本", "xhs"), {"text": "y" * 80, "source": "llm"})
    ts, val = pp._cache[("会过期的文本", "xhs")]
    pp._cache[("会过期的文本", "xhs")] = (ts - pp.CACHE_TTL_S - 1, val)
    assert pp._cache_get(("会过期的文本", "xhs")) is None, "过期条目必须失效"


def test_polish_empty_input_short_circuits() -> None:
    """空输入不应发起任何模型请求。"""
    from core import prompt_polish as pp

    assert pp.polish("   ", "xhs") == {"text": "", "source": "empty"}


def test_polish_template_fallback_is_honest() -> None:
    """模型不可用时的模板补全必须能被识别，前端要如实告知用户。"""
    from core import prompt_polish as pp

    out = pp._template("通勤穿搭", "xhs")
    assert "小红书笔记" in out
    assert "通勤穿搭" in out
    assert len(out) >= 100, "模板补全太短就不能怪用户觉得被敷衍"


# ── 7. llm.chat 支持 max_tokens ───────────────────────────────────────────


def test_llm_chat_accepts_max_tokens() -> None:
    from core import llm

    sig = inspect.signature(llm.chat)
    assert "max_tokens" in sig.parameters, "llm.chat 未暴露 max_tokens，短任务无法限制生成长度"
    assert sig.parameters["max_tokens"].default is None, "默认必须是 None，保持长文创作链路行为不变"


def test_llm_chat_body_carries_max_tokens() -> None:
    src = Path("core/llm.py").read_text(encoding="utf-8")
    assert 'body["max_tokens"]' in src, "max_tokens 参数没有真正写进请求体"
