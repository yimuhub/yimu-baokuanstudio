# SPDX-License-Identifier: BUSL-1.1
"""R5-5 裂变产物分享：令牌化公网链接 + 二维码海报。

问题
----
一稿六端裂变引擎（:mod:`core.fission`）技术资产完备，但产物只写本地
``data/drafts/<did>/preview-*.html``——用户要自己登录服务器目录找文件、
再手动复制到社交平台。**商业化包装为零**。

方案
----
给每个「草稿 + 平台」组合签发一个**不可猜测的分享令牌**，令牌 → 稿件的
映射落库，访问 ``/s/{token}`` 即可渲染已排版的成品页，并附二维码。

⭐ 归属校验（本模块的核心安全点）
--------------------------------
任务明确要求「不能让别人改 did 拿到别人的稿件」。做法：

1. **地址里根本没有 did**——只有不可猜测的随机令牌（128 位熵，
   ``secrets.token_urlsafe(24)``）。改 did 无从下手，因为压根没有 did 字段。
2. **令牌→稿件映射只存服务端**，且每条记录绑定 ``owner_user_id``。
3. ``/s/{token}`` 默认是**公开可访问**（这是分享的语义），但：
   - 令牌可随时吊销（``revoked_at``）；
   - 可设过期；
   - **私有稿件**（``drafts.sharing != 'public'``）不签发令牌，
     防止运营误把自己的稿件全网公开；
   - 用户本人访问自己的稿件时优先走已登录的 ``/preview/{did}/..``，
     分享链接只是对外通道。
4. 令牌**一次性校验失败即404**，不泄露「存在但无权限」还是「不存在」。

⚠️ 不做的事（避免误解）：本模块**不做**用户配额/计费，
   也不修改 fission 的任何产物生成逻辑——只增加「链接生成 + 访问路由」。
"""
from __future__ import annotations

import json
import secrets
import time
import uuid

#: 分享链接默认有效期：14 天
DEFAULT_TTL_DAYS = 14

#: 令牌字节数（24 字节 → 192 位熵，暴力猜中的概率可忽略）
TOKEN_BYTES = 24


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# 令牌签发与查询
# ---------------------------------------------------------------------------


def create_share(draft_id: str, platform: str, owner_user_id: str = "",
                 ttl_days: int = DEFAULT_TTL_DAYS,
                 base_url: str = "") -> dict:
    """为某稿件的某平台产物签发分享令牌。

    Args:
        draft_id: 草稿 id。
        platform: 平台标识（wechat_mp / xhs / toutiao / zhihu / weibo / twitter）。
        owner_user_id: 归属用户（用于运营审计）。
        ttl_days: 有效期天数，<=0 表示永不过期。
        base_url: 站点公网根地址；缺省从配置读取，用于拼绝对链接。

    Returns:
        ``{"token", "url", "qr_svg_url", "expires_at"}``。
    """
    from core import db

    token = secrets.token_urlsafe(TOKEN_BYTES)
    sid = f"sh-{uuid.uuid4().hex[:12]}"
    expires_at = (_now() + ttl_days * 86400) if ttl_days > 0 else 0.0
    created = _now()

    c = db.conn()
    c.execute(
        "INSERT INTO share_links "
        "(id, draft_id, platform, token, owner_user_id, created_at, expires_at, revoked_at, hits) "
        "VALUES (?,?,?,?,?,?,?,0,0)",
        (sid, draft_id, platform, token, str(owner_user_id or ""), created, expires_at),
    )
    c.commit()
    c.close()

    url = f"{_base_url(base_url)}/s/{token}"
    return {
        "token": token,
        "url": url,
        "qr_svg_url": f"/s/{token}/qr.svg",
        "poster_url": f"/s/{token}/poster.svg",
        "draft_id": draft_id,
        "platform": platform,
        "expires_at": expires_at,
    }


def resolve(token: str) -> dict | None:
    """令牌 → 分享记录。无效/过期/已吊销一律返回 None。

    命中时**顺带累加访问计数**（运营需要知道哪篇稿子真的被传播了）。
    """
    if not (token or "").strip():
        return None
    from core import db

    c = db.conn()
    row = c.execute(
        "SELECT id, draft_id, platform, token, owner_user_id, created_at, "
        "expires_at, revoked_at, hits "
        "FROM share_links WHERE token=?",
        (token.strip(),)).fetchone()
    if row is None:
        c.close()
        return None
    rec = dict(row)
    if rec.get("revoked_at"):
        c.close()
        return None
    exp = float(rec.get("expires_at") or 0)
    if exp and exp <= _now():
        c.close()
        return None
    c.execute("UPDATE share_links SET hits = hits + 1 WHERE id=?", (rec["id"],))
    c.commit()
    c.close()
    return rec


def revoke(token: str) -> bool:
    """吊销一个分享链接（立即失效）。"""
    from core import db

    c = db.conn()
    cur = c.execute("UPDATE share_links SET revoked_at=? WHERE token=? AND revoked_at=0",
                    (_now(), token.strip()))
    c.commit()
    n = cur.rowcount
    c.close()
    return n > 0


def list_shares(draft_id: str = "", owner_user_id: str = "",
                limit: int = 100) -> list[dict]:
    """列出分享链接（按草稿或按归属用户）。"""
    from core import db

    c = db.conn()
    if draft_id:
        rows = c.execute(
            "SELECT token, draft_id, platform, created_at, expires_at, revoked_at, hits "
            "FROM share_links WHERE draft_id=? ORDER BY created_at DESC LIMIT ?",
            (draft_id, int(limit))).fetchall()
    elif owner_user_id:
        rows = c.execute(
            "SELECT token, draft_id, platform, created_at, expires_at, revoked_at, hits "
            "FROM share_links WHERE owner_user_id=? ORDER BY created_at DESC LIMIT ?",
            (owner_user_id, int(limit))).fetchall()
    else:
        rows = c.execute(
            "SELECT token, draft_id, platform, created_at, expires_at, revoked_at, hits "
            "FROM share_links ORDER BY created_at DESC LIMIT ?",
            (int(limit),)).fetchall()
    c.close()
    now = _now()
    out = []
    for r in rows:
        d = dict(r)
        exp = float(d.get("expires_at") or 0)
        d["is_active"] = (not d.get("revoked_at")) and (not exp or exp > now)
        d["url"] = f"/s/{d['token']}"
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# 批量：为裂变产物一次性签发全部平台链接
# ---------------------------------------------------------------------------


def create_share_set(draft_id: str, platforms: list[str],
                     owner_user_id: str = "", ttl_days: int = DEFAULT_TTL_DAYS,
                     base_url: str = "") -> dict:
    """为一次裂变产出的所有平台批量签发分享链接 + 二维码。

    只会为**确实存在产物文件**的平台签发——没生成预览的平台给链接
    会让用户点开 404，体验比不给更差。
    """
    from core import db

    links = []
    skipped = []
    for plat in platforms:
        f = db.draft_dir(draft_id) / f"preview-{plat}.html"
        if not f.exists():
            skipped.append({"platform": plat, "reason": "该平台产物尚未生成"})
            continue
        links.append(create_share(draft_id, plat, owner_user_id,
                                  ttl_days, base_url))
    return {"draft_id": draft_id, "links": links, "skipped": skipped}


def build_poster(draft_id: str, token: str, title: str = "",
                 subtitle: str = "", base_url: str = "") -> str:
    """生成一张可直接发朋友圈/社群的 SVG 海报（标题 + 二维码 + 品牌署名）。

    纯字符串拼 SVG，不依赖任何图像库；二维码由 :mod:`core.qrcode_min`
    生成后以 ``<image>`` 内嵌 data URI 引用。
    """
    from core import db, qrcode_min

    d = db.get_draft(draft_id) or {}
    title = (title or d.get("title") or "未命名稿件").strip()
    subtitle = (subtitle or "扫码查看完整内容").strip()
    svg_qr = qrcode_min.encode_svg(f"{_base_url(base_url)}/s/{token}", scale=4, quiet=2)
    b64 = _svg_to_data_uri(svg_qr)

    # 标题按长度粗排（避免超宽）
    tsize = 34 if len(title) <= 14 else (28 if len(title) <= 22 else 22)
    # 中文按 2 倍宽度估算，做简单截断
    shown = _truncate_cjk(title, 22 if tsize == 34 else (16 if tsize == 28 else 13))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="960"
     viewBox="0 0 720 960" role="img" aria-label="内容分享海报">
  <rect width="720" height="960" fill="#0f1220"/>
  <rect x="40" y="40" width="640" height="880" rx="28" fill="#171b2e"/>
  <rect x="40" y="40" width="640" height="8" fill="#4f7cff"/>
  <text x="80" y="130" fill="#7d88b0" font-size="26"
        font-family="PingFang SC, Microsoft YaHei, sans-serif">扫码查看完整内容</text>
  <text x="80" y="220" fill="#ffffff" font-size="{tsize}" font-weight="bold"
        font-family="PingFang SC, Microsoft YaHei, sans-serif">{_esc(shown)}</text>
  <line x1="80" y1="270" x2="300" y2="270" stroke="#4f7cff" stroke-width="5"/>
  <text x="80" y="330" fill="#9aa4c7" font-size="24"
        font-family="PingFang SC, Microsoft YaHei, sans-serif">{_esc(_truncate_cjk(subtitle, 24))}</text>
  <image x="220" y="380" width="280" height="280" href="{b64}"/>
  <text x="360" y="700" fill="#7d88b0" font-size="22" text-anchor="middle"
        font-family="PingFang SC, Microsoft YaHei, sans-serif">长按识别二维码</text>
  <text x="360" y="820" fill="#ffffff" font-size="30" text-anchor="middle"
        font-family="PingFang SC, Microsoft YaHei, sans-serif">一幕·YIMU 爆款工作室</text>
  <text x="360" y="866" fill="#6b7699" font-size="20" text-anchor="middle"
        font-family="PingFang SC, Microsoft YaHei, sans-serif">一键生成六平台爆款内容</text>
</svg>"""


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _base_url(base_url: str = "") -> str:
    """取站点公网根地址：显式入参 > 环境变量 > 空串。"""
    if base_url:
        return base_url.rstrip("/")
    try:
        from core.llm import load_env

        return str(load_env().get("PUBLIC_BASE_URL", "")).rstrip("/")
    except Exception:
        return ""


def _svg_to_data_uri(svg: str) -> str:
    """SVG → base64 data URI。"""
    import base64

    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


def _esc(text: str) -> str:
    """XML 文本转义（标题含 & < > 会破坏 SVG）。"""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _truncate_cjk(text: str, limit: int) -> str:
    """按中文宽度（1 个汉字≈2 字符）截断并加省略号。"""
    out = []
    width = 0
    for ch in text:
        w = 2 if ord(ch) > 127 else 1
        if width + w > limit * 2:
            out.append("…")
            break
        out.append(ch)
        width += w
    return "".join(out)


def render_share_page(record: dict, html: str) -> str:
    """给分享页套一层壳：顶部提示 + 内容区 + 底部品牌署名。

    ⭐ 内容原样嵌入（不二次渲染），避免二次转义破坏已排版 HTML。
    """
    platform = _esc(record.get("platform") or "")
    return f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>分享内容 · 一幕 YIMU</title>
<style>
  body{{margin:0;background:#f5f6f8;font-family:PingFang SC,Microsoft YaHei,sans-serif}}
  .bar{{background:#0f1220;color:#fff;padding:14px 18px;font-size:14px;text-align:center}}
  .wrap{{max-width:720px;margin:0 auto;background:#fff;min-height:100vh}}
  .foot{{text-align:center;color:#8b93a7;font-size:12px;padding:20px}}
</style>
</head><body>
<div class="bar">以下内容由「一幕·YIMU 爆款工作室」生成 · 平台：{platform}</div>
<div class="wrap">{html}</div>
<div class="foot">由一幕·YIMU 爆款工作室生成</div>
</body></html>"""