# SPDX-License-Identifier: BUSL-1.1
"""今日头条草稿箱推送适配器（R10 发布闭环补齐 · 头条侧）。

===========================================================================
解决什么问题
===========================================================================
R10 审查结论：六平台裂变只到「预览/复制」，真实推送仅微信公众号。
本模块把头条接入「API 直进草稿箱」通道（与公众号同级），模式由
``config.yaml → publish.toutiao_mode`` 控制：

- ``manual``（默认，现状不变）：Markdown 备好待人工粘贴；
- ``api``：调用头条创作平台草稿接口直接建稿，作者在头条 App/网页
  草稿箱里确认排版与封面后一键发布——**机器不替人点发布**，
  这既是平台合规要求，也是账号安全边界。

===========================================================================
配置（.env，绝不入库）
===========================================================================
- ``TOUTIAO_COOKIE``：mp.toutiao.com 登录态 Cookie（浏览器 F12 复制整串）。
  缺失时 :func:`available` 返回 False，编排层自动回落 manual 队列。
- ``TOUTIAO_DRAFT_API``：草稿接口地址（选填；默认头条创作平台 Web 端点）。

⚠️ 平台接口属非公开契约，字段以实际响应为准：本适配器对响应做宽松解析
  （任何失败都自动回落为 manual 排队并附可行动提示），绝不因头条侧变化炸掉
  主发布流程。
"""
from __future__ import annotations

import httpx

from core.llm import load_env

__all__ = ["available", "push_draft"]

_DEFAULT_DRAFT_API = "https://mp.toutiao.com/api/article/create/draft"
_TIMEOUT = 20


def _cookie() -> str:
    return (load_env().get("TOUTIAO_COOKIE") or "").strip()


def available() -> tuple[bool, str]:
    """头条 API 通道是否可用（缺失 Cookie 时给出可行动提示）。"""
    if _cookie():
        return True, "已配置登录态"
    return False, "未配置 TOUTIAO_COOKIE（浏览器登录 mp.toutiao.com 后 F12 复制 Cookie 填入 .env）"


def push_draft(title: str, body_html: str, *, cover_url: str = "") -> dict:
    """把成稿推入头条草稿箱。

    Returns:
        ``{"ok": bool, "detail": str, "draft_id": str}``。

    Raises:
        RuntimeError: 网络层失败（调用方编排层捕获后回落 manual 队列，不中断主流程）。
    """
    ck = _cookie()
    if not ck:
        return {"ok": False, "detail": "未配置 TOUTIAO_COOKIE，无法直进草稿箱", "draft_id": ""}
    api = (load_env().get("TOUTIAO_DRAFT_API") or "").strip() or _DEFAULT_DRAFT_API
    payload: dict = {
        "title": (title or "").strip()[:80],  # 头条标题上限 5-30 字，超长截断保护
        "content": body_html or "",
        "save": 1,  # 存草稿而非直接发表
    }
    if cover_url:
        payload["cover_url"] = cover_url
    try:
        resp = httpx.post(
            api,
            json=payload,
            headers={
                "Cookie": ck,
                "Referer": "https://mp.toutiao.com/profile/graphic/publish",
                "User-Agent": "Mozilla/5.0 (YIMU-Studio Publisher)",
            },
            timeout=_TIMEOUT,
        )
    except Exception as e:  # 网络失败 → 回落排队信号
        raise RuntimeError(f"头条接口连接失败：{e}") from e
    # 宽松解析：头条各版本响应含 code/message/data 或 data.draft_id
    try:
        data = resp.json()
    except Exception:
        data = {}
    ok = resp.status_code == 200 and int(data.get("code", data.get("status_code", 0)) or 0) in (0, 200)
    draft_id = ""
    d = data.get("data") or {}
    if isinstance(d, dict):
        draft_id = str(d.get("draft_id") or d.get("article_id") or d.get("id") or "")
    if ok:
        detail = f"已进头条草稿箱{(' draft_id=' + draft_id) if draft_id else ''}，请在头条创作平台确认后发布"
        return {"ok": True, "detail": detail, "draft_id": draft_id}
    msg = str(data.get("message") or data.get("status_msg") or f"HTTP {resp.status_code}")[:200]
    return {"ok": False, "detail": f"头条接口返回：{msg}（已自动回落人工队列）", "draft_id": ""}
