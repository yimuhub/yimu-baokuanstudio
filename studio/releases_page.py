# SPDX-License-Identifier: BUSL-1.1
"""7.1 升级总览页：把本次商业化升级的34 项改动与全部新增入口集中展示。

为什么需要这个页面
------------------
7.1 的新功能大多挂在二级路径（``/pricing``、``/admin/metrics`` …），
而首页是升级前的旧版式、没有版本号、也没有升级入口 ——
结果是"功能做了但用户看不见"。本页提供单一入口，把
「改了什么 / 在哪 / 怎么验证」一次性讲清楚。

设计约束：单文件自包含 HTML，无构建步骤，与项目既有
``_PRICING_PAGE_HTML`` / ``_METRICS_PAGE_HTML`` 风格保持一致。
"""
from __future__ import annotations

from fastapi.responses import HTMLResponse

# ── 本次升级的批次清单（与 docs/商业化升级改进方案-20261009.md 一一对应）──
_RELEASES = [
    {
        "code": "R1",
        "name": "止血",
        "icon": "🚨",
        "color": "#ff7b72",
        "desc": "堵住 7 个正在漏钱的漏洞。这是升级里最要紧的一批。",
        "items": [
            ("删除卡密万能后门", "core/billing.py",
             "VIP999 / MEDIAFLOW888 / PRO2026 三个硬编码码 + TOKEN-/PRO-/MCN- 任意前缀放行，"
             "全部删除。现在只能兑换真实存在的卡密。"),
            ("兑换改走真实账本", "web/admin.py",
             "/api/billing/redeem 改调 billing_adapter（此前那个修复版是死代码，生产从未调用，"
             "所以上次修后门没生效）。"),
            ("发卡密要管理员权限", "web/admin.py",
             "gen_keys 原来只验登录不验角色，普通用户就能批量生成任意面额卡密。"),
            ("15 处扣费全部前置校验", "web/admin.py",
             "原来 14 处扣费调用 0 处检查返回值——余额耗尽后功能照常可用。现在不足即 402 + 升级引导。"),
            ("默认口令不再放行", "web/admin.py",
             "loopback 免密此前在未配置口令时恒为真，token 还是可推导的常量。现改为 fail-closed + 随机 token。"),
            ("前端 XSS 收口", "index.html",
             "toast 从 innerHTML 改 textContent，另修 9 处 AI 内容裸插值。"),
            ("修好 5 个死按钮", "index.html",
             "Cmd+K 里「一键配图/7维评审/导出剪映」三个核心卖点命令调用的函数根本不存在，"
             "点了没反应。已接到真实实现。"),
        ],
    },
    {
        "code": "R2",
        "name": "计价归一",
        "icon": "⚖️",
        "color": "#f0883e",
        "desc": "三套 credits 计价口径差250~500 倍，同一份额度能算出完全不同的价值。现在只有一套。",
        "items": [
            ("建立定价唯一真源", "studio/pricing.py",
             "1 credit = 0.01 元。三档额度从 10000/500000/6000000 下调到 3000/30000/200000"
             "（降 20~50 倍，此前注册白送约 25000 元额度）。"),
            ("token 口径改 per-1k", "llm_metering.py",
             "原本 1 个 token 记1 点，与网关口径差 250~500 倍。"),
            ("三套账本收敛为一套", "core/billing.py",
             "原本 JSON 单例与 SQLite 账本并存、互不对账。余额真源统一为 memberships，明细在 ledger。"),
            ("账本单位统一", "image_forge/generate.py",
             "生图原本按 1 点=100 分记账，跨来源汇总会算出无意义数字。"),
            ("生图现在真扣额度", "image_forge/generate.py",
             "原本只记账不扣余额——账记了，钱没扣。"),
            ("额度周期会重置了", "membership/service.py",
             "period_end 原本恒为 NULL，额度永不过期 = 一次性售卖无限期使用。"),
            ("Free 不再承诺完整短剧", "capabilities.py",
             "一条短剧实测 12000 点，而 Free 只有 3000 点——承诺「每周1 条」但跑一条就见底。"),
        ],
    },
    {
        "code": "R3",
        "name": "变现通路",
        "icon": "💰",
        "color": "#7ee787",
        "desc": "升级前产品没有任何直接收款能力，用户被告知要付费后就没有下一步。现在能收钱了。",
        "items": [
            ("价格页上线", "/pricing",
             "三档权益与价格明码标价，并且把「Free 跑不完一条完整短剧」写在明面上，"
             "而不是让人付了钱才发现限制。"),
            ("购买闭环打通", "/api/billing/order",
             "下单 → 生成卡密 → 线下转账 → 管理员核销 → 兑换到账。"
             "⚠️ 未接微信/支付宝：仓库无商户资质，做不了「一键支付」。"),
            ("升级弹窗接通购买", "index.html",
             "原来点「升级」弹出的窗里只有一个「我知道了」，是条死胡同。"),
            ("额度墙给购买引导", "web/admin.py",
             "额度不足时展示套餐对比与入口，而不是只抛一句报错。"),
            ("可给用户发额度", "/api/admin/grant_credits",
             "此前只能改代码发版，运营没有 HTTP 入口。"),
            ("可以退款了", "/api/admin/orders/{id}/refund",
             "此前全仓搜 refund 零命中。按可用余额实际减少量扣回，差额如实记账。"),
            ("用户列表 + 封禁", "/admin/users",
             "此前没有用户管理，只能开 SQLite 查。现在可封禁（有审计，防锁死管理员）。"),
            ("审计日志可查询", "/api/admin/audit_logs",
             "此前审计表只写不查。"),
            ("草稿按用户隔离", "web/admin.py",
             "⚠️ 此前 drafts 表 user_id 全为空串，任何登录用户可访问任意 did。"
             "现用路由基类覆盖 85 条含 did 的路由，新增路由自动受保护。"),
        ],
    },
    {
        "code": "R4",
        "name": "合规与信任",
        "icon": "🛡️",
        "color": "#58a6ff",
        "desc": "BSL 协议下公司承担主体责任。此前系统零合规检测，已在生产违规内容。",
        "items": [
            ("内容安全前置闸", "core/content_guard.py",
             "在质量评分之前独立拦截。已接入成稿与发布两个入口。"),
            ("词库 384 条", "core/blocklists/",
             "涉黄擦边 / 伪医疗 / 广告法极限词 / 政治敏感，分block 与 review 两级+ 46 条白名单。"),
            ("选题池敏感过滤", "core/topics.py",
             "存量 364 条选题中 35 条（含俄乌/导弹/不明原因肺炎类）已标记 blocked。"),
            ("已有草稿标待审", "core/db.py",
             "6 条草稿全部标 needs_review，一条没删。"),
            ("data/ 不再对外暴露", "web/admin.py",
             "此前整个 data/ 目录挂成 HTTP 可访问，含明文 API Key 与数据库文件。现仅保留编辑器上传目录。"),
            ("排期不再假成功", "core/scheduler.py",
             "此前非小红书平台一律标记为「模拟分发成功完成」。现改为「待手动发布」+ 诚实文案。"),
            ("首页假数据清零", "index.html",
             "98.6% 达标率（永不变化）、平均 88.6 分、写死的图表日期，已全部清除，改为引导态。"),
            ("CSRF + 安全头", "core/security_middleware.py",
             "此前 csrf 全仓零命中，诱导用户 POST 可让系统向公众号真实发布内容。"),
        ],
    },
    {
        "code": "R5",
        "name": "留存与增长",
        "icon": "📈",
        "color": "#c9a0ff",
        "desc": "此前留存靠用户自己记得回来；一稿六端裂变引擎完整，但产物只落在服务器本地目录。",
        "items": [
            ("用户侧通知通道", "core/notify.py",
             "新增邮件通道（钉钉保留给运营）。配额墙会触发召回，这是最有效的转化触点。"),
            ("每日工单改应用内定时", "core/scheduler.py",
             "此前依赖 macOS launchd，云端部署全线失效。"),
            ("推荐奖励 20%", "membership/service.py",
             "invites 加 inviter_id。运营码与自邀不发奖，伪造 inviter_id 被拒。"),
            ("裂变产物可分享", "/s/{token}",
             "令牌制链接 + 纯标准库二维码 + SVG 海报。did 不进 URL，"
             "改别人的 did 拿不到别人的稿件。"),
            ("运营漏斗看板", "/admin/metrics",
             "此前埋点全仓零命中，任何运营判断全靠猜。现在能算五步漏斗转化。"),
            ("自动发布频控", "core/pubguard.py",
             "1 小时超 3 条即拦截。此前 xhspub 注释自认要控频但无任何实现。"),
        ],
    },
]

# ── 可直接点开的入口 ──
_PORTS = [
    ("🏠", "主工作台", "/", "对话成稿、内容工作台、影音工坊", "#58a6ff"),
    ("💰", "价格页", "/pricing", "三档权益与售价，R3 新增", "#7ee787"),
    ("📊", "运营漏斗", "/admin/metrics", "五步转化看板，R5 新增", "#c9a0ff"),
    ("👥", "用户管理", "/admin/users", "列表 / 封禁 / 发额度，R3 新增", "#58a6ff"),
    ("📋", "审计日志", "/admin/audit", "所有资金与权限操作留痕，R3 新增", "#f0883e"),
    ("💳", "会员账本", "/admin/billing", "额度 / 卡密 / 邀请码", "#f0883e"),
    ("🔌", "API 网关", "/admin/gateway", "Key 管理 / 上游状态", "#7ee787"),
    ("📱", "移动版", "/m", "手机端独立界面", "#58a6ff"),
]

_RELEASES_PAGE_HTML = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>7.1 升级总览 · 一幕 YIMU</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;background:#0f1220;color:#e8ecf8;
      font-family:PingFang SC,Microsoft YaHei,sans-serif;line-height:1.7}
 .wrap{max-width:1080px;margin:0 auto;padding:32px 20px 80px}
 .hero{background:linear-gradient(140deg,#1b2440,#141a2c);
       border:1px solid #2c3446;border-radius:16px;padding:26px 28px;margin-bottom:26px}
 .vtag{display:inline-block;background:#f0883e;color:#fff;font-size:12px;font-weight:800;
       padding:4px 11px;border-radius:20px;margin-bottom:12px}
 h1{margin:0 0 8px;font-size:28px}
 .hero .sub{color:#9aa3bd;font-size:13.5px}
 .stats{display:flex;gap:26px;flex-wrap:wrap;margin-top:18px;padding-top:18px;
        border-top:1px solid #2c3446}
 .stat b{display:block;font-size:24px;color:#f0883e;line-height:1.3}
 .stat span{font-size:12px;color:#8b93ad}
 h2{font-size:17px;margin:34px 0 14px;display:flex;align-items:center;gap:9px}
 .ports{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:12px}
 .port{display:block;text-decoration:none;background:#161c28;border:1px solid #262d3d;
       border-radius:12px;padding:15px 17px;transition:.15s}
 .port:hover{border-color:#f0883e;transform:translateY(-2px)}
 .port .ic{font-size:19px}
 .port .nm{font-size:14.5px;font-weight:800;margin:6px 0 3px}
 .port .ds{font-size:12px;color:#8b93ad;line-height:1.6}
 .rel{background:#161c28;border:1px solid #262d3d;border-radius:14px;
      padding:20px 22px;margin-bottom:16px}
 .rel .hd{display:flex;align-items:center;gap:11px;margin-bottom:6px;flex-wrap:wrap}
 .rc{font-size:12px;font-weight:800;padding:3px 10px;border-radius:6px}
 .rn{font-size:17px;font-weight:800}
 .rcount{font-size:12px;color:#8b93ad;margin-left:auto}
 .rel .ds{font-size:13px;color:#9aa3bd;margin-bottom:14px}
 .it{border-top:1px solid #232b3b;padding:13px 0}
 .it:first-of-type{border-top:0}
 .it .t{font-size:14px;font-weight:700;margin-bottom:3px}
 .it .t .ok{color:#7ee787;font-size:12.5px;margin-right:6px}
 .it .d{font-size:12.8px;color:#8b93ad;line-height:1.75}
 code{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;background:#0d1117;
      padding:2px 7px;border-radius:5px;color:#79c0ff;margin-left:6px}
 .warn{background:rgba(240,136,62,.1);border:1px solid rgba(240,136,62,.35);
       border-radius:11px;padding:14px 17px;font-size:13px;line-height:1.85;margin-bottom:20px}
 .foot{margin-top:34px;padding-top:18px;border-top:1px solid #262d3d;
       font-size:12px;color:#6f7896;line-height:1.9}
 @media(max-width:640px){.wrap{padding:20px 14px 60px}h1{font-size:22px}
   .rel{padding:16px}.stats{gap:18px}}
</style>
</head><body>
<div class="wrap">

 <div class="hero">
  <span class="vtag">VERSION __VERSION__</span>
  <h1>7.1 商业化升级总览</h1>
  <div class="sub">
   从 7.0.0-dev 到 7.1.0：把「能白嫖的半成品」改造成「能收钱的产品」。<br>
   34 项改动分 5 批，测试从 156 项通过提升到 379 项通过。
  </div>
  <div class="stats">
   <div class="stat"><b>34</b><span>项改动</span></div>
   <div class="stat"><b>5</b><span>个批次</span></div>
   <div class="stat"><b>7</b><span>个资损漏洞已堵</span></div>
   <div class="stat"><b>223</b><span>项测试净增</span></div>
   <div class="stat"><b>0</b><span>个新增回归</span></div>
  </div>
 </div>

 <div class="warn">
  <b>⚠️ 三件需要你知道的事：</b><br>
  1. <b>收款目前是手工核销</b>——仓库没有微信/支付宝商户资质，做不了「一键支付」。
  真实链路是：下单 → 生成卡密 → 线下转账 → 管理员核销 → 用户兑换到账。
  卡密在下单时就发给用户，运营核销前请先确认是否真的收到款。<br>
  2. <b>Free 档跑不完一条完整短剧</b>（3000 点< 一条短剧 12000 点），这是刻意设计，
  价格页已如实标注。要让 Free 能跑一条，需把额度提到 12000 以上。<br>
  3. <b>分享链接需要配置 PUBLIC_BASE_URL</b>，否则链接是相对路径，外网打不开。
 </div>

 <h2>🔗 所有可点开的入口</h2>
 <div class="ports">
__PORTS__
 </div>

 <h2>📋 本次改了什么（点开每项能看到具体位置）</h2>
__RELEASES__

 <div class="foot">
  一幕·YIMU 爆款工作室 · <b>7.1.0</b><br>
  完整方案见仓库 <code>docs/商业化升级改进方案-20261009.md</code>，
  五维审查报告见 <code>docs/五维深度审查报告-20261008.md</code>。<br>
  本页只读，不含任何写操作。
 </div>

</div>
<script>
 // 版本号从后端接口取，避免与 version.py 脱节
 fetch('/api/version', {credentials:'same-origin'})
   .then(r => r.ok ? r.json() : null)
   .then(d => { if (d && d.version) {
       document.querySelector('.vtag').textContent = 'VERSION ' + d.version;
   }});
</script>
</body></html>"""


def _render_releases_page() -> str:
    """把批次清单渲染成 HTML（保持模板与数据分离，便于后续增删批次）。"""
    ports_html = "\n".join(
        f'  <a class="port" href="{path}"><div class="ic">{icon}</div>'
        f'<div class="nm">{name}</div><div class="ds">{desc}</div></a>'
        for icon, name, path, desc, _c in _PORTS
    )

    rel_html = []
    for rel in _RELEASES:
        items = "\n".join(
            f'  <div class="it"><div class="t"><span class="ok">✔</span>{title}'
            f'<code>{loc}</code></div><div class="d">{desc}</div></div>'
            for title, loc, desc in rel["items"]
        )
        rel_html.append(
            f'<div class="rel">\n'
            f'  <div class="hd">\n'
            f'    <span class="rc" style="background:{rel["color"]}22;color:{rel["color"]}">'
            f'{rel["code"]}</span>\n'
            f'    <span class="rn">{rel["icon"]} {rel["name"]}</span>\n'
            f'    <span class="rcount">{len(rel["items"])} 项</span>\n'
            f'  </div>\n'
            f'  <div class="ds">{rel["desc"]}</div>\n'
            f'{items}\n'
            f'</div>'
        )

    try:
        from version import __version__ as _v
    except Exception:  # noqa: BLE001 — 版本真源不可用时不阻塞页面渲染
        try:
            from web.admin import APP_VERSION as _v  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            _v = "7.1.0"

    return (
        _RELEASES_PAGE_HTML
        .replace("__PORTS__", ports_html)
        .replace("__RELEASES__", "\n".join(rel_html))
        .replace("__VERSION__", _v)
    )


def releases_page(request):
    """7.1 升级总览页。

    ⭐ 面向用户与运营的「改了什么 / 在哪 / 怎么看」单一入口。
    只读页面，不做任何写操作，故只要求登录、不要求管理员。
    """
    from web.admin import guard  # 局部导入避免模块级循环依赖

    guard(request)
    return HTMLResponse(_render_releases_page())