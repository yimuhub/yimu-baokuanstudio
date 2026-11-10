# SPDX-License-Identifier: BUSL-1.1
"""成稿产物的统一收口（V15.8 · 客户报告「先生成文件、再写正文、最后编译预览」）。

所有成稿路径（选题池逐级生成、copilot 对话式成稿、一句话成稿、分平台改写、
矩阵拆分、手动编辑正文）最终都应经过这里，保证：
1. 正文里没有指向不存在文件的图片链接；
2. 六平台预览产物齐备，含 ``preview-xhs.html``；
3. 老草稿打开时自动自愈（客户机器上已有的坏草稿无需手工改数据库）。
"""
from __future__ import annotations

from core import db, image_contract, previews




def heal_draft(draft_id: str) -> dict:
    """打开草稿时的轻量自愈：只在检测到死链或预览缺失时才重新编译。

    判定只做一次字符串扫描 + 6 次 stat，干净草稿几乎零开销。
    """
    d = db.get_draft(draft_id)
    if not d:
        return {"changed": False, "reason": "draft_not_found"}
    ddir = db.draft_dir(draft_id)
    body = d.get("body_md") or ""
    bad_links = image_contract.needs_healing(body, draft_id, ddir)
    missing = [p for p in previews.PREVIEW_PLATFORMS
               if not (ddir / f"preview-{p}.html").is_file()]
    if not bad_links and not missing:
        return {"changed": False, "reason": "clean"}
    built = previews.build_all_previews(draft_id, body_md=body)
    return {"changed": True, "bad_links": bad_links,
            "missing_previews": missing, "previews": built}


def quality_gate(draft_id: str) -> dict:
    """发布 / 状态变更前的自检：正文里还有缺失配图就阻止并给出序号提示。"""
    d = db.get_draft(draft_id)
    if not d:
        return {"ok": False, "reason": "草稿不存在"}
    ddir = db.draft_dir(draft_id)
    missing = image_contract.validate(d.get("body_md") or "", draft_id, ddir)
    if missing:
        return {
            "ok": False,
            "reason": "第 N 张配图缺失",
            "missing": missing,
            "hint": "请在创作台点击「生成配图」，或删除正文中失效的图片链接后再发布。",
        }
    return {"ok": True, "missing": []}
