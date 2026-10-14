# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 爆款工作室 · 版本更新与发布历史展示页 (Releases & Version Evolution).

展示内容：
1. 当前系统运行版本（单一真源 V9.0.0 万象生 · Infinite Worlds）；
2. 新老版本（V8.3.33 vs V9.0.0）核心差异对比矩阵与升级演进说明；
3. 历史里程碑时间轴（V9.0.0、V8.3.33、V8.3.2）详细功能说明；
4. Git 标签归档说明与多版本按需切换指引。
"""
from __future__ import annotations
import version

def get_releases_html() -> str:
    cur_ver = version.__version__
    codename = getattr(version, "__codename__", "万象生")
    slogan_cn = getattr(version, "__slogan_cn__", "一念起 一幕开 万象生")
    slogan_en = getattr(version, "__slogan_en__", "One Thought. One Scene. Infinite Worlds.")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>版本更新展示 · 一幕·YIMU V{cur_ver}</title>
<style>
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: #090d16;
  color: #e2e8f0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.6;
}}
.wrap {{
  max-width: 1040px;
  margin: 0 auto;
  padding: 36px 20px 80px;
}}
header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding-bottom: 20px;
  margin-bottom: 30px;
  flex-wrap: wrap;
  gap: 16px;
}}
.brand {{
  display: flex;
  align-items: center;
  gap: 12px;
}}
.brand-title {{
  font-size: 20px;
  font-weight: 800;
  color: #fff;
  letter-spacing: 0.5px;
}}
.brand-sub {{
  font-size: 12px;
  color: #94a3b8;
  margin-top: 2px;
}}
.nav-actions {{
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}}
.btn {{
  background: #f0883e;
  color: #fff;
  text-decoration: none;
  font-size: 13px;
  font-weight: 700;
  padding: 7px 16px;
  border-radius: 8px;
  border: 1px solid rgba(240,136,62,0.4);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all .2s;
  cursor: pointer;
}}
.btn:hover {{
  background: #ff9d55;
  box-shadow: 0 4px 12px rgba(240,136,62,0.3);
}}
.btn.ghost {{
  background: rgba(255,255,255,0.05);
  color: #cbd5e1;
  border: 1px solid rgba(255,255,255,0.15);
}}
.btn.ghost:hover {{
  background: rgba(255,255,255,0.1);
  color: #fff;
}}

/* Banner */
.hero {{
  background: linear-gradient(135deg, rgba(240,136,62,0.12) 0%, rgba(168,85,247,0.15) 100%);
  border: 1px solid rgba(240,136,62,0.3);
  border-radius: 16px;
  padding: 28px 30px;
  margin-bottom: 34px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.3);
  position: relative;
  overflow: hidden;
}}
.hero-tag {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(16,185,129,0.18);
  color: #34d399;
  border: 1px solid rgba(16,185,129,0.35);
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 12px;
}}
.hero h1 {{
  margin: 0 0 8px;
  font-size: 26px;
  color: #fff;
  font-weight: 800;
}}
.hero-slogan {{
  color: #cbd5e1;
  font-size: 14.5px;
  margin-bottom: 18px;
}}
.hero-meta {{
  display: flex;
  gap: 20px;
  font-size: 12.5px;
  color: #94a3b8;
  flex-wrap: wrap;
}}
.hero-meta b {{
  color: #f0883e;
}}

/* 对比矩阵表 */
.card {{
  background: #131926;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 24px;
  margin-bottom: 32px;
}}
.card-header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  padding-bottom: 12px;
}}
.card-title {{
  font-size: 17px;
  font-weight: 800;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 8px;
}}
.table-wrap {{
  overflow-x: auto;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}}
th, td {{
  padding: 12px 14px;
  text-align: left;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}}
th {{
  background: rgba(255,255,255,0.03);
  color: #94a3b8;
  font-weight: 700;
}}
tr:hover td {{
  background: rgba(255,255,255,0.02);
}}
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
}}
.badge.orange {{ background: rgba(240,136,62,0.2); color: #f0883e; border: 1px solid rgba(240,136,62,0.3); }}
.badge.green {{ background: rgba(16,185,129,0.2); color: #10b981; border: 1px solid rgba(16,185,129,0.3); }}
.badge.purple {{ background: rgba(168,85,247,0.2); color: #c084fc; border: 1px solid rgba(168,85,247,0.3); }}
.badge.blue {{ background: rgba(56,189,248,0.2); color: #38bdf8; border: 1px solid rgba(56,189,248,0.3); }}

/* 时间轴 */
.timeline {{
  display: flex;
  flex-direction: column;
  gap: 20px;
}}
.timeline-item {{
  border-left: 3px solid #38bdf8;
  padding-left: 20px;
  margin-left: 8px;
  position: relative;
}}
.timeline-item.active {{
  border-color: #f0883e;
}}
.timeline-item:before {{
  content: "";
  position: absolute;
  left: -8px;
  top: 4px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #38bdf8;
  border: 3px solid #090d16;
}}
.timeline-item.active:before {{
  background: #f0883e;
}}
.t-head {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}}
.t-ver {{
  font-size: 16px;
  font-weight: 800;
  color: #fff;
}}
.t-date {{
  font-size: 12px;
  color: #64748b;
}}
.t-desc {{
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 10px;
}}
.t-list {{
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: #cbd5e1;
}}
.t-list li {{
  margin-bottom: 5px;
}}

/* 底部操作与终端命令 */
.codebox {{
  background: #06090e;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 14px 18px;
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 12.5px;
  color: #7ee787;
  overflow-x: auto;
  line-height: 1.7;
}}
footer {{
  margin-top: 50px;
  border-top: 1px solid rgba(255,255,255,0.06);
  padding-top: 24px;
  text-align: center;
  font-size: 12px;
  color: #64748b;
}}
</style>
</head>
<body>

<div class="wrap">
  <header>
    <div class="brand">
      <span style="font-size:28px">🎬</span>
      <div>
        <div class="brand-title">一幕·YIMU 爆款工作室 · Releases</div>
        <div class="brand-sub">全生命周期版本更新与演进展示 (Version Showcase) · Licensor: yimu.hyipf.com</div>
      </div>
    </div>
    <div class="nav-actions">
      <a class="btn" href="/">🏠 进入工作台</a>
      <a class="btn ghost" href="https://github.com/yimuhub/yimu-baokuanstudio" target="_blank" rel="noopener">🌐 GitHub 仓库</a>
      <a class="btn ghost" href="https://github.com/yimuhub/yimu-baokuanstudio/tags" target="_blank" rel="noopener">🏷️ GitHub Tags</a>
    </div>
  </header>

  <!-- 当前最新旗舰版本 Hero Banner -->
  <div class="hero">
    <div class="hero-tag">🌟 当前系统运行 · 最新旗舰版本 (Latest Active Release)</div>
    <h1>Version {cur_ver} · {codename} (Infinite Worlds)</h1>
    <div class="hero-slogan"><b>{slogan_cn}</b> &nbsp;|&nbsp; <i>{slogan_en}</i></div>
    <div class="hero-meta">
      <div>发布日期: <b>2026-10-13</b></div>
      <div>许可授权方 (Licensor): <b>yimu.hyipf.com</b></div>
      <div>开源协议: <b>BSL 1.1 (Business Source License)</b></div>
      <div>代码质量门禁: <b>439 测试全绿 · CI 4/4 通过</b></div>
    </div>
  </div>

  <!-- 新老版本核心对比矩阵 -->
  <div class="card">
    <div class="card-header">
      <div class="card-title">📊 核心版本差异演进矩阵 (V8.3.33 vs V9.0.0)</div>
      <span class="badge orange">老版本保持冻结 · 新版本直推发布</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>核心维度</th>
            <th>V8.3.33 (上一稳定归档版本)</th>
            <th>V9.0.0 (最新旗舰大版本)</th>
            <th>升级演进说明与收益</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>配图默认分辨率</b></td>
            <td>1024x1024 (标准 1K)</td>
            <td><span class="badge orange">2048x1152 / 1152x2048 (原生 2K)</span></td>
            <td>极简模式与灵感选题配图清晰度翻倍，细节锐利无损</td>
          </tr>
          <tr>
            <td><b>画面通透感与滤镜</b></td>
            <td>易产生灰蒙蒙的雾感与烟雾朦胧</td>
            <td><span class="badge green">零烟雾通透滤镜 (Zero-Haze)</span></td>
            <td>强力注入高饱和高锐度提示词，负向剔除 fog/smoke/blur</td>
          </tr>
          <tr>
            <td><b>图像大模型适配</b></td>
            <td>基础生图通道，易触发 400 size 限制</td>
            <td><span class="badge purple">Agnes 图像模型深度对齐</span></td>
            <td>严格规范长宽比尺寸，内置 400 智能自愈与容错保护</td>
          </tr>
          <tr>
            <td><b>商业化与算力入口</b></td>
            <td>顶栏按钮割裂、包含独立外部跳转链接</td>
            <td><span class="badge blue">算力与套餐价格深度合并统一胶囊</span></td>
            <td>彻底下线冗余跳转页，算力/套餐/卡密一站式极速弹窗</td>
          </tr>
          <tr>
            <td><b>国际化多语言</b></td>
            <td>仅支持简体中文单语言</td>
            <td><span class="badge green">中英双语 (i18n) 全域即时热切换</span></td>
            <td>Desktop 与 Mobile 双端支持，GitHub 纯英文专业说明</td>
          </tr>
          <tr>
            <td><b>账号安全与管理</b></td>
            <td>无法自主修改登录口令</td>
            <td><span class="badge blue">个人中心与口令弹窗集成修改密码</span></td>
            <td>后端 /api/auth/change_password 严格校验加密更新</td>
          </tr>
          <tr>
            <td><b>GitHub 归档管理</b></td>
            <td><code>git tag v8.3.33</code> 独立归档冻结</td>
            <td><code>git tag v9.0.0</code> (Latest 旗舰版)</td>
            <td>老版本保持冻结原貌不变，新版本直接上传发布</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 历史里程碑时间轴 -->
  <div class="card">
    <div class="card-header">
      <div class="card-title">🗂️ 核心版本里程碑时间轴 (Milestones & Changelog)</div>
      <span class="badge green">规范语义化版本 SemVer</span>
    </div>

    <div class="timeline">
      <!-- V9.4.0 -->
      <div class="timeline-item active">
        <div class="t-head">
          <span class="t-ver">🌟 V9.4.0 · 浮光录 (Luminous Chronicles)</span>
          <span class="badge orange">当前版本 · 最新</span>
          <span class="t-date">2026-10-14</span>
        </div>
        <div class="t-desc">全栈安全加固、BYOK 与免费体验主链贯通、6 维数字画像全域注入与数据库 10 倍提速。</div>
        <ul class="t-list">
          <li><b>🛡️ 全链路安全与反代加固</b>：反代转发头识别防免密穿透、跨站 Drive-by CSRF 拦截、按需 HTTPS CSP、API Key Vault 随机 Nonce+HMAC 加密（v2）；</li>
          <li><b>🔗 身份鉴权与 BYOK 计费贯通</b>：全仓 Agent 自动透传 <code>user_id</code>，自备 Key 模式自动免扣平台算力，统一 V6/V7 双会话 Cookie；</li>
          <li><b>🎭 6 维数字画像与小红书指令精修</b>：写作/导演/广告 Agent 自动挂载工作区 6 维人设与声纹记忆，修复小红书单平台改写指令透传；</li>
          <li><b>⚡ 数据库 10 倍提速与无冲突热更新</b>：SQLite 建表与迁移改为进程级缓存，在线升级自动保护本地 <code>config.yaml</code>，补齐注册与首稿增长漏斗埋点。</li>
        </ul>
      </div>

      <!-- V9.3.2 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V9.3.2 · 扶风翼 (Free First, Pay Later)</span>
          <span class="badge green">稳定归档版</span>
          <span class="t-date">2026-10-14</span>
        </div>
        <div class="t-desc">官方通道每日免费体验额度 + 首次登录 3 步引导 Wizard + 双层数据访问合并，让第一次成功先于第一次付费。</div>
        <ul class="t-list">
          <li><b>🎁 官方通道免费体验额度</b>：新用户（Free 档）每日 3 次免费轻量 AI 生成，单次 ≤512 tokens，无需自备 API Key；耗尽自动回落正常算力扣费，不额外计费；</li>
          <li><b>🚀 首次登录 3 步引导 Wizard</b>：30 秒完成设置——认识免费额度、选主链路（官方通道 / 自备 Key）、完成引导，关闭即持久化，绝不反复打扰；</li>
          <li><b>🏛️ 双层数据访问合并（P0 债务清偿）</b>：<code>users</code> / <code>user_api_keys</code> 表统一由 SQLAlchemy 真源声明，时间列统一 ISO-8601，彻底杜绝混存崩溃；</li>
          <li><b>🌐 1,835+ 词条双语零残留</b>：新增引导 Wizard 全量词条，英文模式中文残留数严格为 0。</li>
        </ul>
      </div>

      <!-- V9.3.1 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V9.3.1 · 万象融 (Server One-Click Deploy)</span>
          <span class="badge green">稳定归档版</span>
          <span class="t-date">2026-10-14</span>
        </div>
        <div class="t-desc">服务器生产环境一键部署脚本、Systemd 开机自启服务守护、GitHub Releases 自动化无缝发布。</div>
        <ul class="t-list">
          <li><b>🖥️ 服务器生产级一键部署</b>：全新推出 <code>服务器一键部署.sh</code>（软链 <code>一键部署.sh</code> / <code>deploy.sh</code>），支持一键 curl 管道直接执行，覆盖多主流 Linux 发行版底层依赖自愈与 Systemd 开机自启；</li>
          <li><b>🐧 原生 Linux 跨端与无版本号脚本</b>：macOS (<code>一键启动.command</code>)、Windows (<code>一键启动.bat</code>) 与 Linux (<code>一键启动_linux.sh</code>) 全端统一规范；</li>
          <li><b>🚀 GitHub Releases 自动化实时同步</b>：代码推送与版本更新全自动化同步至 GitHub Release 列表页，保证最新稳定版随时可检测与同步升级；</li>
          <li><b>🛡️ 版本更新中枢防回退加固</b>：完善语义化版本比对引擎，彻底杜绝历史版本覆盖最新版本的异常。</li>
        </ul>
      </div>

      <!-- V9.3.0 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V9.3.0 · 万象融 (Cross-Platform Unified)</span>
          <span class="badge green">稳定归档版</span>
          <span class="t-date">2026-10-13</span>
        </div>
        <div class="t-desc">原生 Linux 生产环境就绪、全端一键脚本无版本化规范、GitHub Releases 自动化流水线。</div>
        <ul class="t-list">
          <li><b>🐧 原生 Linux 生产引擎就绪</b>：新增 <code>一键启动_linux.sh</code> 与 <code>一键升级_linux.sh</code>，全面支持 Ubuntu/Debian/CentOS/RHEL 等环境，支持守护进程与状态健康检查；</li>
          <li><b>⚡ 全端一键脚本无版本号规范化</b>：彻底告别遗留版本号后缀，Windows (<code>一键启动.bat</code>)、macOS (<code>一键启动.command</code>) 与 Linux 全端统一规范；</li>
          <li><b>🚀 GitHub Releases 自动化实时同步</b>：代码推送与版本更新全自动化同步至 GitHub Release 列表页；</li>
          <li><b>🛡️ 全代码历史版本残留清理统一</b>：彻底清理废弃版本字眼与陈旧包，全仓代码对齐至最新 9.3 统一标准。</li>
        </ul>
      </div>

      <!-- V9.2.0 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V9.2.0 · 天工开 (Divine Forge)</span>
          <span class="badge green">稳定归档版</span>
          <span class="t-date">2026-10-13</span>
        </div>
        <div class="t-desc">自定义内容分发派生平台中枢、Agent 排版技能自学习自蒸馏与全域纯净「一幕·YIMU」锁定。</div>
        <ul class="t-list">
          <li><b>🌐 自定义内容分发派生平台中枢</b>：支持在个人中心添加全网任意内容平台网址（URL），自动智能识别平台名称、域名与图标；</li>
          <li><b>🔴 今日头条高密度资讯流排版规范</b>：自定义分发平台默认统一采用今日头条高密度资讯流排版模式，主标题突出、节奏紧凑、红框金句；</li>
          <li><b>🤖 Agent 专属排版技能模块自学习</b>：支持输入任意样例网址，Agent 自动深度读取其排版样式（色调/边框/引用/字号），自蒸馏生成专属排版技能与 CSS；</li>
          <li><b>🛡️ 全域「一幕·YIMU」品牌翻译纠错锁定</b>：彻底清除多语言反向翻译导致的「一幕·一幕」瑕疵，中文模式绝对呈现纯正「一幕·YIMU」；</li>
          <li><b>🧭 Releases 页面纯净化升级</b>：彻底移除版本演进顶栏「商业化价格」菜单，纯粹呈现代码演进与里程碑。</li>
        </ul>
      </div>

      <!-- V9.1.1 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V9.1.1 · 流光澈 (Crystal Clarity)</span>
          <span class="badge green">稳定归档版</span>
          <span class="t-date">2026-10-13</span>
        </div>
        <div class="t-desc">全域双语零残留覆盖、1,768 词条多语言字典与全系统弹窗国际化覆盖。</div>
        <ul class="t-list">
          <li><b>1,768 词条全域双语</b>：覆盖全站各级页面所有弹窗、卡片、按钮与提示词；</li>
          <li><b>版权主体统一</b>：全站统一标识版权主体为 yimu.hyipf.com；</li>
          <li><b>专属版本命名规范</b>：在根目录建立 DEVELOPMENT.md 版本规划与寓意库。</li>
        </ul>
      </div>

      <!-- V9.1.0 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V9.1.0 · 凌云破 (Soaring Sky)</span>
          <span class="badge blue">已归档稳定版</span>
          <span class="t-date">2026-10-13</span>
        </div>
        <div class="t-desc">全站 i18n 双语绝对统一、GitHub Releases 官方发布展示与全仓代码版本号统一。</div>
        <ul class="t-list">
          <li><b>全站 i18n 双语绝对统一</b>：深度 DOM 自动翻译引擎，英文模式下 100% 全英文，中文模式下 100% 全中文，绝无半中半英；</li>
          <li><b>GitHub Releases 官方发布展示</b>：通过 GitHub 官方 REST API 自动化打标与展示版本更新演进；</li>
          <li><b>全仓代码版本号单一真源统一步进</b>：全仓代码版本号严格对齐；</li>
          <li><b>2K 原生超清分镜与 Agnes 零烟雾通透滤镜</b>：默认 2K 尺寸，强力清除朦胧烟雾感；</li>
          <li><b>商业化算力中枢统一</b>：顶栏算力余额与套餐价格整合为统一直达胶囊。</li>
        </ul>
      </div>

      <!-- V9.0.0 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V9.0.0 · 万象生 (Infinite Worlds)</span>
          <span class="badge green">大版本里程碑</span>
          <span class="t-date">2026-10-13</span>
        </div>
        <div class="t-desc">划时代生产力飞跃：原生 2K 视觉引擎、零烟雾通透画质、中英双语国际化与商业化算力中枢统合。</div>
        <ul class="t-list">
          <li><b>2K 原生超清视觉分镜</b>：文章与灵感模式默认 2K（横屏 2048x1152，竖屏 1152x2048，方图 2048x2048）；</li>
          <li><b>Agnes 图像大模型零烟雾提示词滤镜</b>：注入 crystal-clear, vibrant, sharp focus 等高质修饰，强力排除雾气烟雾模糊；</li>
          <li><b>商业化中枢深度合并</b>：顶栏算力余额与套餐价格整合为统一直达胶囊，一键打开充值、换套餐与卡密兑换；</li>
          <li><b>全局 i18n 国际化引擎</b>：支持 PC 端与移动端即时一键热切换中/英文，配齐纯英文 GitHub 说明书；</li>
          <li><b>账号安全自我改密</b>：通行证与个人中心支持安全验证旧密码并热更新新密码。</li>
        </ul>
      </div>

      <!-- V8.3.33 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V8.3.33 · 星河引 (Galactic Beacon)</span>
          <span class="badge blue">已归档稳定版</span>
          <span class="t-date">2026-10-13</span>
        </div>
        <div class="t-desc">个人中心深度重构，算力套餐可点击交互与通行证改密打通。</div>
        <ul class="t-list">
          <li><b>会员与账本迁入个人中心</b>：独立 #p-profile 面板集成会员档位、调用账本表格与卡密核销；</li>
          <li><b>套餐卡片点击交互</b>：商业化弹窗与个人中心 Free/Pro/Studio 卡片支持点击高亮选中；</li>
          <li><b>永久归档 Git Tag</b>：代码与资产永久冻结在 <code>v8.3.33</code> 标签，老用户可永久拉取。</li>
        </ul>
      </div>

      <!-- V8.3.2 -->
      <div class="timeline-item">
        <div class="t-head">
          <span class="t-ver">🏷️ V8.3.2 · 视觉大跃迁 (Visual Quantum Leap)</span>
          <span class="badge blue">已归档稳定版</span>
          <span class="t-date">2026-10-12</span>
        </div>
        <div class="t-desc">影视级分镜头美学法则建立，创作 Agent 聊天一键换图。</div>
        <ul class="t-list">
          <li><b>十大前沿视觉美学系统</b>：纪实摄影、瑞士极简、杂志编辑、赛博科技、古风雅韵、新海诚动漫等；</li>
          <li><b>分镜精准回填</b>：H2/H3 标题小节插图与正文毫秒级匹配并实时热重载；</li>
          <li><b>小红书 5 幕磨砂卡片工坊</b>：离线压制 3:4 竖屏高清全景毛玻璃卡片。</li>
        </ul>
      </div>
    </div>
  </div>

  <!-- 多版本切换命令 -->
  <div class="card">
    <div class="card-header">
      <div class="card-title">🧭 如何在 GitHub / 本地终端切换与使用不同版本</div>
    </div>
    <p style="font-size:13px;color:#94a3b8;margin-top:0">
      老版本在 GitHub 永久冻结保留，新版本直接上传发布。您可以在本地根据需要随时检出任意版本：
    </p>
    <div class="codebox">
# 1. 检出使用当前最新旗舰大版本 V9.0.0（万象生）：
git checkout v9.0.0

# 2. 检出回滚至老版本 V8.3.33（保持老版原貌，绝无任何改动）：
git checkout v8.3.33

# 3. 查看所有已归档版本标签列表：
git tag -l -n
    </div>
  </div>

  <footer>
    一幕·YIMU 爆款工作室 · 版权主体 (Copyright & Licensor): <a href="https://yimu.hyipf.com" style="color:#f0883e;text-decoration:none">yimu.hyipf.com</a> · © 2026 yimu.hyipf.com. All Rights Reserved.
  </footer>
</div>

</body>
</html>
"""
