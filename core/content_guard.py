# SPDX-License-Identifier: BUSL-1.1
"""内容安全前置闸：在 7 维质量评分【之前】独立拦截违规内容。

设计要点
--------
1. **独立可测**：本模块不依赖 core.judge / LLM / DB，纯字符串 + 词库匹配，
   可单独 import 与单测（R4 通用要求 2）。
2. **前置拦截**：`core/judge.py` 的 7 维评分只回答「内容好不好」，
   本模块只回答「内容能不能发」。命中阻断档时调用方**不进入评分**。
3. **分级**：
   - ``block``  明确违规 → 阻断发布（R4-1 验收：伪医疗、绝对化用语命中即拦）
   - ``review`` 灰区     → 不阻断，但标记 needs_review 交人工审
   - ``pass``   无命中   → 放行
4. **可读原因**：面向小白用户，不吐开发者黑话（R4-1 要求）。
5. **可配置**：环境变量开关 + 自定义词库目录 + 白名单。

开关（环境变量）
----------------
- ``CONTENT_GUARD_ENABLED``      设 ``0``/``false``/``off`` 关闭整个闸门（默认开）
- ``CONTENT_GUARD_LEVEL``        设 ``review`` 则全部降级为「只标记不阻断」
- ``CONTENT_GUARD_BLOCKLIST_DIR`` 自定义词库目录（放同名 json 覆盖内置词库）
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

BASE = Path(__file__).resolve().parent.parent
BLOCKLIST_DIR = Path(
    os.environ.get("CONTENT_GUARD_BLOCKLIST_DIR") or (BASE / "core" / "blocklists")
)

# 命中分级
LEVEL_PASS = "pass"
LEVEL_REVIEW = "review"
LEVEL_BLOCK = "block"

# 只有显式设置为下列值才视为「关闭」；未设置（None）= 启用
_FALSE_VALUES = {"0", "false", "off", "no", "disabled"}

# 词库文件名 → 展示名（用于给用户看的分类标题）
_LIBRARY_FILES = {
    "porn_terms.json": "涉黄擦边内容",
    "medical_terms.json": "伪医疗与医疗擦边",
    "ad_terms.json": "广告法极限词",
    "political_terms.json": "政治敏感与灾难疫情",
}

# 各分类给出的整改建议（面向小白，不使用开发者黑话）
_ADVICE = {
    "涉黄擦边内容": "请删除或改写涉性暗示、低俗擦边的表述，只保留正常的生活/情感内容。",
    "伪医疗与医疗擦边": "请删除「根治/治好/三天见效」这类疗效承诺；介绍健康知识时请注明「科普不能替代就医」。",
    "广告法极限词": "请把「最/第一/唯一/国家级」等极限词换成有依据的相对表述，例如「我们做的」「众多品牌中的」。",
    "政治敏感与灾难疫情": "请不要蹭国际军事冲突、疫情、灾害与逝者话题；这类内容在平台极易被限流甚至封号。",
}


@dataclass
class GuardHit:
    """单条命中记录。"""

    category: str      # 分类展示名，如「广告法极限词」
    word: str          # 命中的词条或正则说明
    level: str         # block / review
    advice: str = ""   # 给小白看的整改建议

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "word": self.word,
            "level": self.level,
            "advice": self.advice or _ADVICE.get(self.category, "请人工复核这段内容。"),
        }


@dataclass
class GuardResult:
    """内容安全检查结果。"""

    level: str = LEVEL_PASS
    hits: list[GuardHit] = field(default_factory=list)
    whitelisted: bool = False          # 是否因命中白名单而整体放行
    enabled: bool = True               # 闸门是否处于启用状态
    text_len: int = 0

    @property
    def blocked(self) -> bool:
        """是否应当阻断发布。"""
        return self.level == LEVEL_BLOCK

    @property
    def needs_review(self) -> bool:
        """是否需要人工复核（灰区或被降级的阻断项）。"""
        return self.level in (LEVEL_REVIEW, LEVEL_BLOCK)

    @property
    def ok(self) -> bool:
        """是否可以继续进入后续流程（评分/成稿）。"""
        return self.level != LEVEL_BLOCK

    def reason(self) -> str:
        """面向小白用户的一句话拦截/复核原因（无命中返回空串）。"""
        if self.level == LEVEL_PASS:
            return ""
        if not self.enabled:
            return ""
        cats = []
        for h in self.hits:
            if h.category not in cats:
                cats.append(h.category)
        verb = "不能发布" if self.level == LEVEL_BLOCK else "需要你人工确认后再发布"
        return f"检测到{('、'.join(cats))}相关表述，{verb}：" + self._detail()

    def _detail(self) -> str:
        parts = []
        for h in self.hits[:5]:
            parts.append(f"「{h.word}」")
        more = len(self.hits) - 5
        if more > 0:
            parts.append(f"等 {len(self.hits)} 处")
        return "、".join(parts)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "blocked": self.blocked,
            "needs_review": self.needs_review,
            "whitelisted": self.whitelisted,
            "enabled": self.enabled,
            "reason": self.reason(),
            "hits": [h.to_dict() for h in self.hits],
        }


# ---------------------------------------------------------------------------
# 词库加载
# ---------------------------------------------------------------------------

_cache: dict | None = None


def _load_library() -> dict:
    """加载全部词库文件，返回 {展示名: {level: {...}}}。结果进程内缓存。"""
    global _cache
    if _cache is not None:
        return _cache
    lib: dict[str, dict] = {}
    for filename, title in _LIBRARY_FILES.items():
        path = BLOCKLIST_DIR / filename
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            # 词库缺失/损坏时静默跳过——闸门不得因词库问题把服务拖垮
            continue
        entry: dict[str, dict] = {}
        for tier in ("block", "review"):
            blob = data.get(tier) or {}
            terms = [t for t in (blob.get("terms") or []) if isinstance(t, str) and t]
            patterns = []
            for pat in (blob.get("patterns") or []):
                if isinstance(pat, str):
                    patterns.append((pat, blob.get("reason", "")))
                elif isinstance(pat, dict) and pat.get("regex"):
                    try:
                        patterns.append((pat["regex"], pat.get("reason", "")))
                    except Exception:
                        continue
            entry[tier] = {
                "reason": blob.get("reason", "命中敏感词"),
                "terms": terms,
                "patterns": [(re.compile(p), r) for p, r in patterns],
            }
        if entry:
            lib[title] = entry
    _cache = lib
    return lib


def _load_whitelist() -> list[str]:
    """加载白名单短语。"""
    try:
        data = json.loads((BLOCKLIST_DIR / "whitelist.json").read_text(encoding="utf-8"))
        return [p for p in (data.get("phrases") or []) if isinstance(p, str) and p]
    except Exception:
        return []


def reload_library() -> None:
    """清空词库缓存（词库热更新或测试用）。"""
    global _cache
    _cache = None


# ---------------------------------------------------------------------------
# 开关
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    """内容安全闸是否启用（CONTENT_GUARD_ENABLED，默认启用）。"""
    raw = os.environ.get("CONTENT_GUARD_ENABLED", "")
    return raw.strip().lower() not in _FALSE_VALUES


def _review_only() -> bool:
    """是否把所有命中降级为「只标记不阻断」（CONTENT_GUARD_LEVEL=review）。"""
    return os.environ.get("CONTENT_GUARD_LEVEL", "").strip().lower() == LEVEL_REVIEW


# ---------------------------------------------------------------------------
# 核心检测
# ---------------------------------------------------------------------------

def _scan(text: str) -> list[GuardHit]:
    """对文本执行全部词库匹配，返回命中列表。"""
    hits: list[GuardHit] = []
    for title, entry in _load_library().items():
        advice = _ADVICE.get(title, "")
        for tier in (LEVEL_BLOCK, LEVEL_REVIEW):
            blob = entry.get(tier)
            if not blob:
                continue
            seen: set[str] = set()
            for term in blob["terms"]:
                if term in text and term not in seen:
                    seen.add(term)
                    hits.append(GuardHit(title, term, tier, advice))
            for regex, reason in blob["patterns"]:
                m = regex.search(text)
                if m:
                    label = m.group(0)[:40]
                    if label in seen:
                        continue
                    seen.add(label)
                    hits.append(GuardHit(title, reason or label, tier, advice))
    return hits


def pre_publish_check(text: str | None, title: str | None = None) -> GuardResult:
    """发布前内容安全检查——**必须在 7 维质量评分之前调用**。

    参数
    ----
    text : 正文（Markdown 或纯文本）
    title: 标题；单独传入以便标题与正文拼接后统一检测

    返回
    ----
    GuardResult：
      ``.blocked``       True 时调用方必须停止，不得进入评分与发布
      ``.needs_review``  True 时建议置 needs_review 标记交人工审
      ``.reason()``      面向小白的中文原因，可直接展示给用户

    示例
    ----
    >>> r = pre_publish_check("三天见效，降压不用吃药", title="养生神器")
    >>> r.blocked
    True
    >>> r.reason()
    '检测到伪医疗与医疗擦边相关表述，不能发布：「三天见效，降压不用吃药」…'
    """
    full = f"{title or ''}\n{text or ''}".strip()
    if not full:
        return GuardResult(level=LEVEL_PASS, enabled=is_enabled(), text_len=0)

    enabled = is_enabled()
    if not enabled:
        return GuardResult(level=LEVEL_PASS, enabled=False, text_len=len(full))

    # 白名单：命中任一短语整篇放行（正常医疗科普/历史人文不被误杀）
    for phrase in _load_whitelist():
        if phrase in full:
            return GuardResult(
                level=LEVEL_PASS, whitelisted=True, enabled=True, text_len=len(full)
            )

    hits = _scan(full)
    if _review_only() and hits:
        for h in hits:
            h.level = LEVEL_REVIEW
        return GuardResult(
            level=LEVEL_REVIEW, hits=hits, enabled=True, text_len=len(full)
        )
    if not hits:
        return GuardResult(level=LEVEL_PASS, enabled=True, text_len=len(full))
    level = LEVEL_BLOCK if any(h.level == LEVEL_BLOCK for h in hits) else LEVEL_REVIEW
    return GuardResult(level=level, hits=hits, enabled=True, text_len=len(full))


def check_draft(draft: dict | None) -> GuardResult:
    """对草稿 dict（需含 title / body_md）做发布前检查。"""
    if not draft:
        return GuardResult(level=LEVEL_PASS)
    return pre_publish_check(draft.get("body_md"), draft.get("title"))


def check_topic_title(topic_title: str | None) -> GuardResult:
    """选题入池前的敏感过滤（热榜标题通常只有标题，没有正文）。

    与正文检测的一个区别：**广告法极限词在热榜标题里只标记不阻断**。
    依据是《广告法》约束商业广告，新闻/资讯类标题（如「某企业全球第一」）
    属 factual reporting，直接阻断会误杀大量正常资讯选题。
    涉黄擦边 / 伪医疗 / 政治敏感三类仍然阻断。
    """
    res = pre_publish_check("", topic_title)
    if res.level == LEVEL_BLOCK and res.hits:
        downgraded = [h for h in res.hits if h.category != "广告法极限词"]
        if not downgraded:
            # 只因广告法极限词被拦 → 降级为待审
            for h in res.hits:
                h.level = LEVEL_REVIEW
            return GuardResult(level=LEVEL_REVIEW, hits=res.hits,
                               enabled=res.enabled, text_len=res.text_len)
        # 另有更严重的命中 → 只保留非广告法命中，避免原因里掺入无关极限词
        return GuardResult(level=LEVEL_BLOCK, hits=downgraded,
                           enabled=res.enabled, text_len=res.text_len)
    return res


def library_stats() -> dict:
    """词库统计（供管理界面/自检展示）。"""
    lib = _load_library()
    out = {}
    total = 0
    for title, entry in lib.items():
        b = entry.get(LEVEL_BLOCK) or {}
        r = entry.get(LEVEL_REVIEW) or {}
        n = len(b.get("terms", [])) + len(b.get("patterns", [])) + \
            len(r.get("terms", [])) + len(r.get("patterns", []))
        total += n
        out[title] = {
            "block": len(b.get("terms", [])) + len(b.get("patterns", [])),
            "review": len(r.get("terms", [])) + len(r.get("patterns", [])),
        }
    return {"enabled": is_enabled(), "total": total, "libraries": out,
            "whitelist": len(_load_whitelist())}


def describe_warnings(hits: Iterable[GuardHit]) -> list[str]:
    """把命中列表转成一句一句的中文提示（给前端弹窗用）。"""
    msgs = []
    for h in hits:
        msgs.append(f"{h.category}：命中「{h.word}」——{h.to_dict()['advice']}")
    return msgs
