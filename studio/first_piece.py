# SPDX-License-Identifier: BUSL-1.1
"""新用户「首篇完整体验券」（First-Piece-Free Entitlement）。

===========================================================================
解决什么问题
===========================================================================
R10 审查结论：免费体验每日 3 次且单次输出 ≤512 tokens，注册送的 3000 点
又只够 1/4 条短剧——新用户在**产出第一条完整作品之前**就撞上付费墙，
成就感为零，转化无从谈起。

本模块给每个账号一张**终身一次**的「首篇完整体验券」：

- 触发时机：free 档用户某次生成输出超过免费体验的 512 token 上限时自动启用
  （即第一次想写长文的时刻，恰是最需要成就感的时刻）；
- 权益内容：该次调用不受 512 上限限制、不占用每日免费次数、不扣算力点，
  完整跑通「选题→成稿→配图」一整篇；
- 用完即止：一张券终身一次，用完后回落到原有免费体验规则。

===========================================================================
设计约束
===========================================================================
1. 状态落 ``data/first_piece_free.json``（与 free_demo_calls.json 同级的
   单机自托管口径），文件损坏按「未使用」兜底——权益宁可多发一次，
   不能把用户卡死在半截文章上；
2. 领取不需要任何操作：账号天然持有，首次触发长文时自动核销；
3. 永不影响付费档（pro/studio 走正常扣费，不经过本模块）。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

log = __import__("logging").getLogger("yimu.first_piece")

_PATH = Path(__file__).resolve().parent.parent / "data" / "first_piece_free.json"
_LOCK = threading.Lock()

__all__ = ["first_piece_available", "consume_first_piece", "first_piece_status"]


def _read() -> dict:
    try:
        if _PATH.exists():
            data = json.loads(_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:  # 文件损坏按「未使用」兜底：宁可多发，不可错杀
        log.warning("[first_piece] 状态文件读取失败，按未使用处理: %s", exc)
    return {}


def _write(data: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
    except Exception as exc:
        log.warning("[first_piece] 状态文件写入失败: %s", exc)


def first_piece_available(user_id: str) -> bool:
    """该账号是否还持有首篇体验券（不在已用名单 = 持有）。"""
    return bool(user_id) and str(user_id) not in _read()


def first_piece_status(user_id: str) -> dict:
    """券状态（供 UI / 接口展示）。"""
    used_at = (_read().get(str(user_id)) or {}).get("used_at", "")
    return {"available": first_piece_available(user_id), "used_at": used_at}


def consume_first_piece(user_id: str, meta: dict | None = None) -> bool:
    """核销首篇体验券。返回 True=本次成功用券；False=无券（幂等，重复核销安全）。"""
    if not user_id:
        return False
    uid = str(user_id)
    with _LOCK:
        data = _read()
        if uid in data:
            return False
        data[uid] = {
            "used_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "meta": {k: v for k, v in (meta or {}).items() if k in ("completion_tokens", "model")},
        }
        _write(data)
    log.info("[first_piece] 首篇完整体验券已核销 user=%s meta=%s", uid, meta or {})
    try:
        from core import analytics
        analytics.track("first_piece_used", uid, {"completion_tokens": int((meta or {}).get("completion_tokens") or 0)})
    except Exception:
        pass
    return True
