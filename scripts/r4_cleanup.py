#!/usr/bin/env python
# SPDX-License-Identifier: BUSL-1.1
"""R4 存量合规清理脚本（一次性 / 可重复执行，幂等）。

做三件事，**都不删用户数据**：
1. 选题池：把命中内容安全闸的 pending/approved 选题标记为 ``blocked``。
2. 草稿箱：把命中内容安全闸的草稿标记 ``needs_review=1`` + 写入可读原因。
3. 打印词库概况与误伤抽样，便于人工复核。

用法
----
    # 预演（默认，只看不改）
    python -m scripts.r4_cleanup

    # 真正执行
    python -m scripts.r4_cleanup --apply

⚠️ 生产库请先备份（本脚本只做 UPDATE 标记，不做 DELETE）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def main() -> int:
    ap = argparse.ArgumentParser(description="R4 内容合规存量清理（标记，不删除）")
    ap.add_argument("--apply", action="store_true",
                    help="真正写入数据库；缺省为预演模式")
    args = ap.parse_args()

    from core import content_guard, db

    stats = content_guard.library_stats()
    print("=" * 68)
    print("R4 内容安全闸 · 词库概况")
    print("=" * 68)
    print(f"闸门启用: {stats['enabled']}    检测条目总数: {stats['total']}    "
          f"白名单短语: {stats['whitelist']}")
    for name, v in stats["libraries"].items():
        print(f"  - {name}: 阻断 {v['block']} 条 / 待审 {v['review']} 条")
    print(f"\n模式: {'执行写入 (--apply)' if args.apply else '预演（不写库，加 --apply 生效）'}")

    topic_res = db.sweep_blocked_topics(apply=args.apply)
    print("\n" + "=" * 68)
    print("① 选题池敏感过滤")
    print("=" * 68)
    print(f"扫描 {topic_res['total']} 条待处理选题，命中 {topic_res['would_block']} 条，"
          f"已标记 blocked {topic_res['blocked']} 条")
    for it in topic_res["items"][:40]:
        print(f"  [blocked] {it['title'][:44]}")
        print(f"            原因: {it['reason'][:80]}")

    draft_res = db.sweep_drafts_needs_review(apply=args.apply)
    print("\n" + "=" * 68)
    print("② 草稿箱待审标记")
    print("=" * 68)
    print(f"扫描 {draft_res['total']} 条草稿，命中 {draft_res['flagged']} 条，"
          f"已标记 needs_review {draft_res['marked']} 条")
    for it in draft_res["items"]:
        flag = "🚫阻断档" if it["level"] == "block" else "⚠️待审档"
        print(f"  {flag} {it['id']}  {it['title'][:40]}")
        print(f"            原因: {it['reason'][:80]}")

    print("\n" + "=" * 68)
    print("③ 当前待处理清单")
    print("=" * 68)
    blocked = db.list_blocked_topics()
    review = db.list_drafts_needs_review()
    print(f"选题 blocked: {len(blocked)} 条")
    print(f"草稿 needs_review: {len(review)} 条")
    print("\n提示：以上条目均**保留在库中**，可在管理界面人工复核后放行或改写。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
