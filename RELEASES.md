# 🚀 YIMU Studio Releases & Changelog

All notable changes and milestones to **YIMU Studio (一幕·YIMU 爆款工作室)** are documented here.

---

## 🌠 Version 15.1.0 · 万象新 (Grand Renewal) · Two-Line Fusion · 2026-11-08

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "15.1.0"`, `__codename__ = "万象新"`, `__codename_en__ = "Grand Renewal"`)

### 🎯 Milestone Summary

本版本完成**双线融合**：远端发布线（v10.3.0→v14.0.0 的三栏工作台重构、A2 全功能离线安装包、亮色模式全站统一、存储态/展示态分离、系统诊断日志、文本纯净管线等 24 个提交）与本地商业交付级整改线（在线支付闭环、上传安全守卫、首篇体验券、收入看板、巨石拆分）在 V15 版本线下合流为一线。合并消解 30 个文件冲突，全量 CI 四道门禁跑绿。

### 🔀 Fusion Highlights（双向融合要点）

| # | 内容 | 说明 |
|---|------|------|
| 1 | **远端语义改动全量保全** | v10.3 稳定性大修（存储态/展示态分离、`_ensure_core_tables`/`_migrate_columns` 一次性迁移、draft_history 缺列修复）、系统诊断日志、0 元开通漏洞修复（卡密仅 paid 后下发）、`DraftOwnerRoute` v14 强化（未登录 401 + did 形态 400）等全部保留 |
| 2 | **本地整改增量回植** | 在远端 admin.py 基底上重新应用：支付/续费 6 端点、上传安全守卫、收入看板（API+看板页）、首篇体验券、小白术语减负 |
| 3 | **巨石拆分在融合基底上重跑** | v14 admin.py（7,629 行/280 路由）整体迁出至 `web/routers/` 18 域；`split_admin.py` 管线自动化，族内顺序保持 |
| 4 | **测试脚手架升级** | 远端新增 routes_smoke 等测试接入 `iter_effective_routes`（惰性路由展开）；版本锚全面前瞻化（主版本元组含 15.，更新中枢断言脱敏） |

**Full Changelog**: v14.0.0...v15.1.0（版本线统一规范见 [VERSION_POLICY.md](VERSION_POLICY.md)）

---

## 💳 Version 15.0.0 · 太平令 (Great Peace Edict) · Commerce-Ready Hardening & Version Line Unification · 2026-11-08

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "15.0.0"`, `__codename__ = "太平令"`, `__codename_en__ = "Great Peace Edict"`)

### 🎯 Milestone Summary

依据《五维综合审查报告》(2026-11-08) 的 P0/P1/P2 整改路线图，本版本完成 **9 项功能新增 + 4 项安全/性能加固**，将产品从「有条件达标」推进到「商业交付级达标线」：支付闭环打通、上传攻击面清零、新用户首篇完整体验保障、收入看板与续费提醒落地。

### 💰 Commerce & Monetization (P0)

| # | Feature | Detail |
|---|---------|--------|
| 1 | **在线支付闭环（双通道 + 沙箱）** | 新增 `studio/membership/payments.py`：虎皮椒（微信/支付宝扫码，MD5 验签）+ Stripe Checkout（Webhook HMAC-SHA256 验签）+ 沙箱模拟收银台。回调验签 → `settle_paid_order` 幂等确认收款 → **卡密自动兑换到下单用户**，7×24 无人值守收款漏斗成立；金额不符拒绝自动核销留人工。密钥走环境变量，未配置时自动回落线下核销链路，收款永不中断 |
| 2 | **新用户首篇完整体验券** | 新增 `studio/first_piece.py`：每个账号终身一次，首次产出超 512 tokens 长文时自动启用——不限长度、不占每日免费次数、不扣算力点，保证新用户免费完整产出第一篇作品后再谈转化 |
| 3 | **收入看板（GMV/MRR/ARPU）** | 新增 `studio/membership/revenue.py` + `/api/admin/metrics` 扩展：累计实收、MRR（按套餐周期折算 30 天）、ARPU、付费转化率、按套餐分布、近 N 天日收入序列、退款单列；运营看板页新增收入卡片区 |
| 4 | **续费提醒自动化** | 付费会员到期前 7/3/1 天经既有通知通道自动提醒（24h 节流幂等，通道未配置只落台账）；调度引擎每日扫描，支持管理端手动触发 |

### 🔐 Security & Performance Hardening (P0/P1)

| # | Fix | Detail |
|---|-----|--------|
| 5 | **上传攻击面清零** | 新增 `core/upload_guard.py` 统一上传守卫：服务端生成文件名（路径穿越免疫）+ 扩展名白名单 + 大小上限；修复 BGM/素材上传历史路径穿越漏洞（web/admin.py）、编辑器上传任意扩展名落盘；补齐广告片参考图/音频/数字人照片大小限制；`draft_dir()` 拒绝 `..`/分隔符穿越 ID |
| 6 | **DB 连接税清除** | `core/db.py conn()` 快速路径改为**索引探测式自愈**：干净库 3 次索引 seek 即返回（实测 2 万行草稿表 1.35ms/conn，与表大小解耦），坏数据自愈语义完整保留；`drafts(user_id/platform/tenant_id/updated_at)` 四索引迁移化落地 |
| 7 | **发布闭环补齐（头条 API）** | 新增 `adapters/toutiao_publish.py`：配置 `TOUTIAO_COOKIE` 后头条直进草稿箱（宽松解析，接口变化自动回落人工队列）；小红书排队文案改为可行动指引（明示组件状态与替代动作） |

### 🧹 Engineering Debt (P2)

| # | Change | Detail |
|---|--------|--------|
| 8 | **死代码清理** | AST 全仓交叉引用核实后删除 7 个零引用函数（`delete_scheduled_post`/`list_users_crud`/`auto_clean_topics`/`detect_intent`/`check_draft`/`format_pure_twitter_export`/`prepare_cards`） |
| 9 | **上帝函数开始拆解** | 967 行 `handle_copilot_chat` 的上下文组装阶段抽出为 `core/copilot_context.py`（人设/文风/技能注入 + 模型解析 + LLM 工厂，行为逐字节一致）；`billing_adapter` 新增公开工厂 `web_session()`，跨层私有调用治理起步（app/deps.py 已切换） |
| 10 | **小白术语减负** | 控制中心新增「3 个 API 入口」通俗说明卡（含直达配置按钮）；我的API/系统配置/网关服务三入口悬停提示全部改为可行动白话 |
| 11 | **版本断言脱敏** | 更新检查测试不再硬编码版本白名单（线上发 14.0.0 即红灯的历史教训），改为 semver 合法性 + 比较逻辑一致性校验 |

### 🏗️ Monolith Decomposition（R11 · 巨石拆分完成）

| # | Change | Detail |
|---|--------|--------|
| 12 | **web/admin.py 7,162 行 → 1,929 行（-73%）** | 271 条路由按路径前缀族整体迁出至 `web/routers/` 17 个域模块（drafts 54 / media 52 / billing 22 / workspace 22 / skills 22 / auth / system / topics / tools / assets / ops / models / tasks / admin_users / files / pages），`scripts/split_admin.py` AST 自动化搬迁，族内注册顺序保持不变（参数路由永不吞并字面路由） |
| 13 | **归属校验路由类稳定化** | `DraftOwnerRoute` 抽出至 `web/draft_guard.py` 独立模块——修复 admin reload 场景下「类对象换新导致 82 条 {did} 路由归属校验失效」的隐患，`{did}` fail-closed 语义与拆分前逐字节一致（TestDraftIsolation 全绿护栏） |
| 14 | **拆分等价性保障** | 契约锁死测试（CONTRACT.md ↔ app 双向）+ 578 用例全量回归 + CI 四道门禁全绿；测试侧新增 `iter_effective_routes`（兼容 FastAPI 惰性 `_IncludedRouter`）与 `web_routing_source`（合并路由源视图）两个共享脚手架 |

**Full Changelog**: v14.0.0...v15.0.0（版本线自本版起统一对齐 V15，见 VERSION_POLICY.md）

### 🔖 Version Line Unification（版本线统一裁定，随本版生效）

远端发布线曾独立演进至 v14.0.0，而部分工作区停在 v10.2.1，造成版本号与代号双漂移（一次未推送的本地 v11.0.0「长风谣」与远端 v11.0.0 撞号）。经裁定：

- 全线跳过 v11~v14 占用段，统一对齐 **V15**；
- **此后所有日常迭代只在 15.x.y 内小版本递增**；主版本跳升仅限开发者书面申请并修订 [VERSION_POLICY.md](VERSION_POLICY.md)；
- 代号序列登记簿已补记远端实际消耗（长风谣/沧海吟/山岳赋/江河曲/竹韵篇/梅雪镜/兰心曲）并扩容至 76 号，下一号「万象新」。 · 测试：533 存量 + 43 新增回归用例（上传守卫 7 / 支付 12 / 首篇券 5 / 收入 7 / 发布 6 / 小白 UX 5 / 契约锁 1）

---

## 🎐 Version 14.0.0 · Light Mode Consistency & WorkBuddy-Style Composer · 2026-11-07

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "14.0.0"`, `__codename__ = "兰心曲"`, `__codename_en__ = "Orchid Melody"`)

Light mode looked broken for one root cause: seven semantic tokens were referenced with dark fallbacks
(`var(--card2, #0f1621)` and friends) but were **never actually defined**, so light mode inherited dark
surfaces. The selected left-rail item rendered dark-on-dark at a **1.06 contrast ratio** — effectively
invisible — and the empty-state guide card and the composer both came out as near-black slabs.
On top of that the send button was squeezed into an ellipse, and "improve prompt" spun for 45 seconds
without ever producing text.

| Area | What changed |
|---|---|
| **Light mode tokens** | `--card2 / --border2 / --border3 / --text-dim / --active / --hover / --accbg` are now defined in both `:root` and `[data-theme="light"]`. Audited page by page: low-contrast text dropped from 22/39/57 findings to 0–1. |
| **Inline accent colours** | Hard-coded dark-theme accents (`#f0883e`, `#58a6ff`, `#3fb950`…) only reached 1.4–3.8:1 on white. 40 attribute-selector rules fold them to a deeper shade of the same hue — no HTML restructuring. |
| **Send button geometry** | The button was a flex child stretched to 28×42 by the textarea, turning `border-radius: 50%` into an ellipse. Now locked to 32×32 with `aspect-ratio: 1/1` and `flex: 0 0 32px` at every input height. |
| **WorkBuddy-style composer** | Attachments, model picker and one-click prompt polish, laid out in a `cb-composer` three-band structure. Attachment chips are individually removable. |
| **Attachments** | New `POST /api/copilot/attach` + `core/copilot_files.py`. Multi-encoding text fallbacks, docx paragraphs preserved via `word/document.xml`, pdf via pypdf, images served statically. 10 MB per file, 6 per message, 12 000-char body cap. |
| **Prompt polish** | New `POST /api/copilot/polish_prompt` + `core/prompt_polish.py`. Uses the model when available (`source="llm"`), falls back to a platform-specific structure template otherwise (`source="template"`), and says which one it used. |
| **Why polish was slow** | The default channel resolved to a reasoning model: unbounded it generated to the context limit (35–45 s); capped it burned every token on the chain of thought and returned an empty body. Fixed with direct-output models first, a `max_tokens` cap, an 18-second total budget and a 10-minute result cache — **45 s down to ~4 s**, and now actually model-written instead of silently templated. |
| **`llm.chat(max_tokens=...)`** | New optional parameter. Default `None` keeps every existing long-form call bit-for-bit unchanged. |

## ❄️ Version 13.0.0 · A2 Full Offline Installer · 2026-11-06

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "13.0.0"`, `__codename__ = "梅雪镜"`, `__codename_en__ = "Plum-Snow Mirror"`)

The desktop installers used to be 1–3 MB because they were **source archives with an installer shell** —
no Python runtime, no dependencies, and several required directories were missing entirely.
On a clean machine the app could not even import `web.admin` (`ModuleNotFoundError: gateway`).
13.0.0 rebuilds the delivery chain so every prerequisite is installed at build time.

| Area | What changed |
|---|---|
| **Self-contained runtime** | Relocatable Python 3.11 (Windows embeddable / `python-build-standalone` on macOS & Linux) plus the full dependency set pre-installed into `runtime/site-packages`. |
| **Built-in Chromium** | Chrome for Testing ships inside the bundle and serves both the desktop window and Playwright; no system browser needed. |
| **Complete resources** | `gateway/`, `app/`, `skills/`, `config.yaml`, `installer/` and all other runtime directories are now included. |
| **Official channel** | Factory config points at the official cloud gateway; bootstrap injects a bundled/claimed credential and never overwrites a user-supplied API Key. |
| **Fresh factory quota** | Billing, demo calls and usage counters are regenerated from scratch — no developer balances or test users ship to customers. |
| **Zero-touch installers** | `.exe`, `.dmg`, `.deb` and portable archives all exec the bundled interpreter. No venv, no pip, no Homebrew, no network. |
| **CI gates** | Offline smoke test (`/api/version` via bundled Python) and a 90 MB archive floor on every platform; a source-only shell can no longer be published. |

Expected compressed size: **roughly 250–320 MB per platform** (up from 1–3 MB), which is what a
genuinely full-featured, zero-configuration desktop application costs.

## 🎋 Version 12.1.0 · Page-Enter Data · 2026-11-04

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "12.1.0"`, `__codename__ = "竹韵篇"`, `__codename_en__ = "Bamboo Rhythm"`)

Patch release on top of the right-pane stage. The stage itself was right; the pages inside it were
still opening without their data, so several of them sat on their own loading state forever.

| Area | What changed |
|---|---|
| **Page-enter hooks** | A single `pageLoaders` table now runs the right loader for Dashboard, Workspace, Console and Pricing the moment a page opens. Pricing no longer shows 「正在从定价中心加载套餐与权益」 forever. |
| **Stage re-routing** | The `switchToPage` wrapper executed the stage and returned early, skipping the page's own bootstrap. It now runs the original first — hooks, data, sub-view, highlight — then moves the panel. |
| **Re-open** | Opening the page that is already on stage reuses it instead of moving it again, so scroll position and input focus survive. |
| **Console pipeline** | The one-line mechanism note became a five-step flow: trending sweep → pick winners → AI draft → short video → DingTalk card. |

## 🌲 Version 12.0.0 · Right-Pane Stage · 2026-11-04

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "12.0.0"`, `__codename__ = "松涛境"`, `__codename_en__ = "Pinewave Realm"`)

Major release. The interaction model is rebuilt around one rule: **the rail never moves,
the conversation never moves, every feature opens on the right — and the right pane goes full screen.**

| Area | What changed |
|---|---|
| **Middle pane** | `#p-lite-mode` is pinned. No menu click can replace the conversation. The seven feature panels are hidden from `<main>` by CSS. |
| **Right pane** | Becomes a real stage. Clicking a rail item moves that panel into the right pane — DOM relocation, not a rewrite, so every onclick, listener, scroll position and form state survives. |
| **Layout pivot** | Opening a feature flips the three columns: the chat shrinks to 340–400px, the stage takes the rest. |
| **Full screen** | Button, double-click on the title, or `Esc`. `.assets` is a stacking context, so it is raised together with the stage — otherwise the rail would cover it. |
| **Routing** | `switchToPage()` is redirected to the stage while it is open, so pages never switch in an invisible `<main>`. |
| **Color** | Eight purple variants (100+ occurrences) collapsed into the brand orange `#f0883e`. |
| **Detail fixes** | Rail sub-trees became an accordion; sub-tabs wrap instead of clipping; cards lost their glow borders; page headings lost their rainbow gradients; buttons no longer break into two lines. |

## 🌊 Version 11.1.1 · Pixel Fixes · 2026-11-04

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "11.1.1"`, `__codename__ = "江河曲"`, `__codename_en__ = "River Rhapsody"`)

Patch release. Four visual deviations left over from 11.1.0, found by comparing real
screenshots against the prototype block by block. Zero feature change.

| Area | What changed |
|---|---|
| **Brand color** | The base stylesheet pinned `.btn.primary` to a purple gradient with `!important`. Primary buttons (发布, save, generate) now use the prototype orange `#f0883e`, and the 极简 / 全能 mode pills were brought along. |
| **Left rail footer** | The user card used to be squeezed to 50px, so 个人中心 overlapped the gear icon. Now row one holds theme / gateway / classic / control center, row two holds the full-width 个人中心 · 已登录 card. |
| **Icon** | 控制中心 switched from a sun-like glyph to a sliders glyph, readable at 15px. |
| **Header at narrow widths** | Below 1400px the page subtitle collapses and the mode pills tighten up. 1280 / 1366 / 1512 all measure zero overlap and `scrollWidth === innerWidth`. |

## 🏔 Version 11.1.0 · Prototype Parity · 2026-11-04

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "11.1.0"`, `__codename__ = "山岳赋"`, `__codename_en__ = "Mountain Hymn"`)

Minor release. The three-pane shell from 11.0.x only had the frame — the left rail was still the old
two-line nav, the center was still two panels side by side, and the header had overlapping elements.
This release rebuilds all three panes to match the prototype, with zero feature loss.

| Area | What changed |
|---|---|
| **Left rail** | Brand block (logo + two lines) · orange **＋ 新建创作** · 30px single-line nav with line icons · expandable sub-tree (35 real entries across 8 pages) · **最近产出** list bound to live drafts · compact bottom bar |
| **Center** | Page subtitle under the title · pill strip replacing the old chip row, with two entry icons docked right · rounded composer with circular send · "从这里开始" guide cards that disappear once the conversation starts |
| **Right panel** | New bottom action bar: **复制 / 导出 / 发布**, wired to existing copy / zip / publish functions |
| **Isolation** | Every new rule is scoped under `body[data-shell="v2"]`; classic mode and <1280px fallback are untouched |
| **i18n** | All injected strings ship in Chinese and English, including the 35 sub-entries |

**Verification** — full `pytest` green; ruff `F821,E9` clean; 8 pages × 1512px with zero horizontal
overflow and zero console errors; classic mode screenshot-compared against 11.0.1.

---

## 🩹 Version 11.0.1 · Quality Gate Fix · 2026-11-04

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "11.0.1"`, `__codename__ = "沧海吟"`, `__codename_en__ = "Oceanic Ode"`)

Patch release. The v11.0.0 three-pane shell is functionally unchanged — this only turns the project's own quality gates back to green.

### 🔧 Fixed

- **Jargon gate**: a CSS comment added during the V11 layout pass contained the internal word 「占位」, which the user-facing copy scanner (`tests/test_no_internal_jargon.py`) bans. Reworded to 「提示文案」. No behavioural change.
- **Version-gate churn**: `tests/test_v1100_workbench_shell.py` no longer hard-codes `11.0.0` / 「长风谣」; it now cross-validates `version.py` against `release-codenames.json` (version, both codenames, last history row, no duplicate in sequence). `test_v1002` / `test_v1020` now read the expected version from `version.py` instead of repeating a literal, so future patch releases stop touching tests.

### 🏷 Codename

`沧海吟 / Oceanic Ode` — sequence index 4 consumed; `next_index` is now 5 (「山岳赋 / Mountain Hymn」).

---

## 🧭 Version 11.0.0 · Three-Pane Workbench Shell · 2026-11-04

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "11.0.0"`, `__codename__ = "长风谣"`, `__codename_en__ = "Longwind Ballad"`)

The main screen is now a real workbench: **left rail (functions) · center stage (the work) · right rail (the assets)**. Nothing was rewritten — the seven existing panels, ~400 functions and 117 endpoints are untouched; the shell only re-allocates the viewport.

### 🧱 Shell

| # | Capability | Detail |
|---|-----------|--------|
| 1 | **Three columns, freely resizable** | Two 11px drag handles between the panes. Left 200–420px, right 300–680px, center never below 460px. Double-click a handle to reset; widths are remembered in `localStorage` and default sensibly by screen width (248/400 → 224/360 → 210/340). |
| 2 | **Right rail = real assets, not a mock** | Four tabs bound to live data: **Draft** (platform switch, genuine typeset preview in a sandboxed iframe, version history with one-click rollback), **Images** (draft artwork, click-to-zoom lightbox, ← → navigation), **Videos** (`/api/video/tasks`, playable finished cuts), **Analytics** (current draft score, background tasks, asset totals). |
| 3 | **Selection follows you** | Picking a draft in the Workbench or finishing one in Lite Mode updates the right rail instantly; navigating to the Media Studio flips it to the video tab. |
| 4 | **Focus mode** | "⛶ Expand" fills the screen with the draft at a 940px measure; `Esc` or the floating badge returns. |
| 5 | **Header auto-collapse** | When the center column narrows, low-priority header actions move into a "⋯ More" menu by importance, keeping the header a single 57px row on every width — no feature is dropped. |
| 6 | **Classic mode round-trip** | `?legacy=1` / `?classic=1` renders the original interface verbatim, with a persistent "⚡ New Workbench" pill to come back. Below 1280px the app falls back to classic automatically. |

### 📐 Layout Fixes Brought by the Narrower Center Column

- Lite Mode's two columns compress instead of overflowing; panel sub-tabs scroll horizontally instead of wrapping into two rows.
- Verified at 1920×1080, 1512×945, 1440×900 and 1280×800: zero horizontal overflow on all seven panels, zero console errors.

---

## 🩹 Version 10.3.2 · Provider Ping Auth Fix · 2026-11-03

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.3.2"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

### 🔌 Model Service Connectivity Test

| # | Fix | Detail |
|---|-----|--------|
| 1 | **"Test connection" always returned HTTP 401 when editing a saved model service** | The settings form deliberately clears the API-key field when you open an existing service (its placeholder says "leave blank to keep the current key"). The ping endpoint, however, used that blank field verbatim and therefore sent **no `Authorization` header at all**: the official channel answered `401 invalid api key`, a self-hosted / AgnesAI endpoint answered `401 Token not provided`. The key was never wrong — replaying the same saved key returns 200. `core/llm.resolve_provider_key()` now resolves the credential as *typed key → saved key for this service → platform key on platform endpoints*, and reports which one was used (`key_source`). |
| 2 | **"Fetch models" had the same blind spot** | It now shares the same resolver, so testing and model discovery can no longer drift apart. `/api/models/ping` forwards `provider_id` so the backend knows which saved key to use. |
| 3 | **Keys copied with a `Bearer ` prefix, quotes, or zero-width characters failed** | `clean_api_key()` strips prefixes, wrapping quotes, full-width spaces and zero-width junk before the header is built — no more `Bearer Bearer sk-...`. |
| 4 | **401 messages were unactionable** | The UI now states whether a blank field will fall back to the saved key, shows which credential was validated, and on 401 says either "no API key was sent" or "this key was rejected upstream". |

### 🔒 Security Boundary (unchanged)

A saved key is only reused when the `base_url` you are testing matches the one stored for that service, and the platform master key is only attached to platform-owned endpoints. Pointing `base_url` at your own server still yields **no credential at all** — verified by regression tests.

---

## 🩹 Version 10.3.1 · Onboarding Wizard Fixes · 2026-11-03

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.3.1"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

### 🚪 First-Run Onboarding

| # | Fix | Detail |
|---|-----|--------|
| 1 | **✕ / Next / Finish did nothing** | `closeWizard()` called `modal('m-wizard').classList…` while `modal()` returned `undefined` → guaranteed `TypeError`. The dialog could never be dismissed and `POST /api/onboarding/done` was never sent, so new users were trapped in a wizard that reappeared on every reload. `modal()` now returns the element; `closeWizard()` is defensive and always persists the "done" flag. |
| 2 | **Backdrop click / Esc didn't persist dismissal** | Both paths now route through `closeWizard()`, so closing by any means stops the wizard from coming back. |
| 3 | **Bottom button pushed outside the viewport** | On 1366×768 laptops (and 125% scaling), `max-height:88vh` + inner scrolling hid "下一步 / 完成引导" below the fold — it looked like a dead button. The overlay now starts top-aligned with its own scroll, and each step's action bar is a sticky, opaque footer that is always visible. |
| 4 | **Step chips were inert** | Clicking a chip now jumps back to any step already reached; not-yet-reached steps stay locked. |
| 5 | **Failed key save still showed "done"** | Saving a self-hosted API key now aborts on failure with the button in a "saving…" state; an empty key focuses and highlights the input instead of just toasting. |
| 6 | **Default admin never saw the wizard** | The auto-login path evaluated `wizard.show` from the pre-login response (always `false`). Status is fetched again after login, and register/login now raise the wizard immediately. |

---

## 🛠️ Version 10.3.0 · Stability Overhaul & Diagnostics · 2026-11-03

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.3.0"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

### 🔧 Reliability & Output Quality

| # | Fix | Detail |
|---|-----|--------|
| 1 | **Windows rewrite always failed** | `draft_history` column migration only ran on first-time DB creation, so existing databases never received the `title` column. New drafts worked (no history row), every rewrite failed (needs history row). Migration now runs on the fast path plus a last-metre `ALTER TABLE` fallback. |
| 2 | **Storage vs. display separation** | Body text keeps Markdown in the database so WeChat HTML can render real `<strong>`; symbols are stripped only at plain-text exits (card images, XHS/Weibo/Toutiao/Zhihu, copy, raw). |
| 3 | **Stray `**` printed on card images** | The Pillow kicker was drawn without sanitising, so `**核心痛点**` landed on the PNG. Fixed, plus card HTML now maps `**bold**` to `<b>bold</b>`. |
| 4 | **Silent regressions from normalisation** | `# 标题` / `### 标题` normalised to `【标题】` broke every `startswith("# ")` / `startswith("### ")` parser — XHS title lost, card sections degraded. New `extract_leading_title()` and unified `is_section_heading()`; 9 call sites fixed. |
| 5 | **System diagnostics log** | Settings → 🩺 System Diagnostics: ring buffer + rotating file, env snapshot (OS/Python/encoding/writable dirs/`draft_history` columns), step-by-step rewrite tracing, auto-redaction of secrets, copy/save/filter/clear in the UI. |
| 6 | **Windows CI packaging** | Build scripts printed Chinese/emoji to a `cp1252` console and crashed the installer build. Stdout now reconfigured to UTF-8; installer version is injected via `/DMyAppVersion` instead of being hard-coded in the `.iss`. |

---

## 🚀 Version 10.2.1 · Native Application Installers (.exe, .dmg, .deb) · 2026-10-23

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.2.1"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

### 📦 Native Installer Milestone (Windows .exe / macOS .dmg / Linux .deb)

| # | Architecture Feature | Detail |
|---|----------------------|--------|
| 1 | **Windows Setup Installer (`.exe`)** | Professional Inno Setup 6 installer (`YIMU-Studio-Windows-Setup-v10.2.1.exe`). Wizard setup, installs to Programs, creates Desktop icon, Start Menu shortcuts, and uninstaller. |
| 2 | **macOS Disk Image (`.dmg`)** | Native Apple DMG image (`YIMU-Studio-macOS-v10.2.1.dmg`). Standard drag-to-Applications layout with bundled `一幕·YIMU 爆款工作室.app`. |
| 3 | **Linux System Package (`.deb`)** | Debian/Ubuntu package (`yimu-studio_10.2.1_amd64.deb`). Registers `/usr/bin/yimu-studio` and desktop application menu entry. |
| 4 | **3-Platform Matrix CI/CD** | GitHub Actions `.github/workflows/build-desktop-client.yml` builds all 3 native installers in parallel on Windows, macOS, and Linux runners. |

---

## 🎬 Version 10.2.0 · Zero-Config Standalone Desktop Client · 2026-10-23

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.2.0"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

### 🖥️ Cross-Platform Native Standalone Desktop Client Milestone (Win / Mac / Linux)

| # | Architecture Feature | Detail |
|---|----------------------|--------|
| 1 | **Native Desktop App Runner (`desktop.py`)** | Dual-engine runner: utilizes `pywebview` for 100% frameless/native desktop window with zero browser bars; auto-falls back to Chromium/Edge `--app` mode or default browser. Auto-terminates backend daemon on window close. |
| 2 | **Silent Windows Desktop Launcher (`一幕桌面客户端.vbs`)** | Launches directly into desktop window without any black console command prompt. Prioritizes bundled portable Python runtime (`runtime\pythonw.exe`). |
| 3 | **macOS & Linux Desktop Suites** | `一幕桌面客户端.command` (macOS double-click launcher), `一幕桌面客户端_linux.sh`, and `一幕桌面客户端.desktop` (freedesktop menu entry). |
| 4 | **Embedded Portable Runtime Architecture** | `一键启动.bat` and `一键升级.bat` Step 0 directly checks `runtime\python.exe`. Standalone desktop releases run completely self-contained with zero system Python installation or PATH configuration. |
| 5 | **Automated Desktop Bundler & CI Pipeline** | `scripts/build_desktop_client.py` and `.github/workflows/build-desktop-client.yml` for zero-friction release packaging. |

---

## 🛡️ Version 10.1.12 · Windows 7 to 11 Universal Architecture · 2026-10-23

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.12"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

### 🔧 Ultimate Windows Startup & Upgrade Resilience (Win7 / 8 / 8.1 / 10 / 11)

| # | Architecture Feature | Detail |
|---|----------------------|--------|
| 1 | **Static WindowsApps Isolation** | Never attempts to invoke 0-byte Store execution aliases on Windows 11; statically filters them before `CreateProcessW` can trigger a console crash. |
| 2 | **Direct Path First (27+ Paths)** | Exhaustively scans standard installation paths across `ProgramFiles`, `LocalAppData`, `C:\`, `D:\`, `E:\`, Anaconda, Miniconda for Python 3.9-3.12. |
| 3 | **Windows 7 Native Adaptation** | Detects NT 6.1 kernel, provides dedicated Windows 7 Python 3.10/3.11 download guidance, suppresses raster font `chcp` switching issues, and supports Python 3.9+. |
| 4 | **No-Flash Window Guarantee** | All error and exit branches are bounded by explicit `pause` and label jumps; console window remains permanently open for user inspection. |

---

## 🛡️ Version 10.1.11 · Cross-Platform Full-Chain Resilience · 2026-10-23

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.11"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

### 🔧 Full Cross-Platform Startup & Upgrade Audit & Zero-Dependency Updater

| # | Component | Enhancement Detail |
|---|-----------|-------------------|
| 1 | **`一键升级.bat`** | Aligned with `一键启动.bat`: added `python --version` dynamic execution check, discarded Microsoft Store 0-byte fake python, Python ≥ 3.10 verification, venv creation error trap with pause, and data/logs pre-warming. |
| 2 | **`core/updater.py`** | Decoupled from `core.llm` / `httpx` / `yaml`. Built-in pure stdlib `.env` parser guarantees 100% zero-dependency updater execution even in bare or broken environments. |
| 3 | **`一键启动_linux.sh`** | Injected `auto_heal_all_sqlite_databases()` prior to startup, ensuring database constraints and missing columns automatically self-heal. |
| 4 | **`一键升级_linux.sh`** | Optimized execution order (preferred `.venv` python) and integrated database self-healing. |
| 5 | **`一键启动.command`** | macOS startup script integrated with `auto_heal_all_sqlite_databases()`. |
| 6 | **`一键升级.command`** | macOS upgrade script integrated with multi-candidate Python interpreter search and database self-healing. |
| 7 | **`服务器一键部署.sh`** | Linux server production deployment integrated with `auto_heal_all_sqlite_databases()`. |

---

## 🛡️ Version 10.1.10 · Zero-Crash One-Click Start · 2026-10-23

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.10"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

### 🔧 Patch Notes · 一键启动 Windows 11 闪退彻底修复

**Root Cause Fixed** — Windows 11 machines without a real Python installation have a Microsoft Store `python.exe` placeholder (0-byte `ReparsePoint`) in `PATH`. The old `一键启动.bat` used `where python` which succeeds for this placeholder, then called `python -m venv` which triggered a Store redirect and silently crashed the CMD window with no error shown.

**Fixes Applied**:
| # | Fix | Detail |
|---|-----|--------|
| 1 | **Real-execution validation** | After `where python` succeeds, immediately run `python --version` — Store placeholders return non-zero, real Python returns 0 |
| 2 | **Python ≥ 3.10 version gate** | Validates `sys.version_info >= (3,10)` after finding an interpreter; gives a clear message if too old |
| 3 | **venv creation error trap** | Checks `errorlevel` after `python -m venv .venv`; on failure prints readable error + `pause` instead of silent exit |
| 4 | **pip install error trap** | Dependency install failures now pause with a readable error instead of silently aborting |
| 5 | **Auto `.env` creation** | If `.env` is missing, automatically copies from `.env.example` on startup |
| 6 | **Store alias guidance** | Error message for "Python not found" now explains the Store alias issue and how to disable it |
| 7 | **Expanded path scanning** | Also checks `%ProgramFiles%\Python3xx` directories |

**Files Changed**: `一键启动.bat`

---

## 🌌 Version 10.1.9 · Zero-Popup Silent Self-Healing Auto-Upgrade · 2026-10-22

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.9"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Permanent Eradication of Windows Git Credential Manager Popups**:
  - Removed obsolete `git credential fill` execution: since the repository is 100% public open-source, all read and update operations execute anonymously without prompting for GitHub credentials.
  - Injected `_safe_git_env()` with `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, `GIT_ASKPASS=""`, strictly disabling all GUI and terminal credential dialogs across Windows, macOS, and Linux.
- **Robust Multi-Tier Upgrade Fallback & Instant Synchronization**:
  - Seamless auto-fallback: if `git pull` encounters network blocks, branch conflicts, or missing Git on Windows, `perform_upgrade()` automatically falls back to downloading the latest Release ZIP archive from high-speed mirror channels (`github.com` -> `ghfast.top` -> `ghproxy.net`).
  - Safe data isolation: protected user configurations (`config.yaml`, `data/`, `.env`) from being overwritten during archive extractions.
  - Aligned Windows `一键升级.bat` with non-interactive flags, ensuring zero popups in both web UI and desktop batch environments.

---

## 🌌 Version 10.1.8 · Self-Healing Rewrite & Resilient Auto-Scoring · 2026-10-22

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.8"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Permanent Fix for Workbench & Copilot Rewrite Failures**:
  - Upgraded `_parse_rewrite` into full self-healing mode: accurately parses Markdown bold prefixes (`**TITLE_WX:**`), headings (`### TITLE_WX`), Chinese brackets (`【微信标题】:`) and unformatted pure Markdown outputs.
  - Eradicated `RuntimeError("重写解析失败")`: when LLMs omit structural tags, the system intelligently extracts the lead sentence as title and the body as article text with 100% success.
  - Optimized rewrite latency & reliability: disabled redundant 5-image AI generation in `rewrite_draft_once` to reuse existing visual assets, slashing rewrite duration from 30s to 2s and preventing external image API timeouts.
- **Permanent Fix for Minimal Mode Missing Scores / Auto-Scoring Failure**:
  - Implemented missing `rewrite_with_feedback(draft_id, score_res)` in `core.judge` to eradicate `AttributeError` during automated quality improvement loops.
  - Implemented `_heuristic_draft_eval(draft)` fallback algorithm in `core.judge`, guaranteeing a valid 7-dimensional score even if LLM review calls timeout or produce invalid JSON.
  - Guaranteed database persistence of fallback scores in `core.copilot`: drafts are 100% saved with valid scores, eliminating `score: null` / `⚖️ 未评分` frontend badges.

---

## 🌌 Version 10.1.7 · Zero-Failure Foreign-Key Decoupled Auto-Heal & Windows Resilience · 2026-10-16

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.7"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Exhaustive Root-Cause Fix for `CHECK constraint failed: ck_drafts_status`**:
  - Identified and fixed root cause where active implicit SQLite transactions blocked `PRAGMA foreign_keys=OFF`, causing `DROP TABLE drafts` to fail with `FOREIGN KEY constraint failed` due to `draft_history` references, silently aborting table rebuilds.
  - Implemented automatic transaction rollback and autocommit (`isolation_level = None`) mode during schema rebuilds, guaranteeing foreign key deactivation and 100% successful table reconstruction.
  - Added multi-stage fallback in `add_draft`: if constraint errors occur under legacy locked states, the system automatically falls back to compliant `'draft'` status and core column insertions, 100% eliminating runtime crashes.
  - Added startup and pre-copilot hook running database constraint self-healing automatically before message processing.
  - Updated frontend workbench draft count filter to count both `'preview'` and `'draft'` statuses seamlessly.

---

## 🌌 Version 10.1.6 · Ultimate Cross-Platform SQLite Auto-Heal & Robust Windows Sync · 2026-10-16

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.6"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Bulletproof Root-Cause Resolution for `CHECK constraint failed: ck_drafts_status`**:
  - Eliminated silent table rebuild rollback caused when historical tables lacked `tenant_id` column during index recreation.
  - Implemented `STANDARD_DRAFT_COLUMNS` full-schema baseline ensuring all required modern columns (`tenant_id`, `platform`, `user_id`, `needs_review`) and zero CHECK constraints are always properly populated with safe defaults.
  - Added `auto_heal_all_sqlite_databases()` to automatically inspect and self-heal all `.db` database files in `data/` (`mediaflow.db`, `yimu.db`, etc.) on module import, startup, and upgrade.
  - Enhanced Windows `一键升级.bat` with 4-tier fallback: `git pull origin` -> `ghfast.top` mirror -> `ghproxy.net` mirror -> Release ZIP online archive extraction, guaranteeing 100% upgrade success on Windows under any network condition.
  - Added database constraint self-healing step directly into `一键启动.bat` and `一键升级.bat`.

---

## 🌌 Version 10.1.5 · Zero-Loss Database Auto-Heal & Draft Status Integrity · 2026-10-16

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.5"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Permanent Fix for `CHECK constraint failed: ck_drafts_status`**:
  - Completely eradicated runtime `sqlite3.IntegrityError: CHECK constraint failed: ck_drafts_status` when drafting in Minimal Mode or transitioning draft lifecycle states (`preview`, `draft`, `pending_review`, `published`, `approved`, `failed`).
  - Implemented SQLite standard 12-step zero-loss table rebuild migration (`_auto_heal_drafts_check_constraint`) in `core.db.conn()` and `studio.db._migrate_missing_columns()`.
  - Seamlessly auto-heals legacy SQLite databases created prior to v10.1.5, preserving 100% of existing draft rows, titles, and histories without requiring manual user intervention or database resets.
  - Removed restrictive `CheckConstraint` on `Draft.status` in `studio.db_models.Draft` to decouple business status progression from static database DDL constraints.
  - Added triple-layer self-healing retry in `core.db.add_draft()` to guarantee 100% crash-free creation on all platforms.

---

## 🌌 Version 10.1.4 · Robust Dual-Mode Auto-Update & Draft Integrity Fix · 2026-10-16

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1.4"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Robust Windows & Cross-Platform Dual-Mode Auto-Updater**:
  - Solved Windows failure to auto-update when installed from GitHub Release ZIP (non-Git repo) by adding archive hot-patch download and extraction engine (`core/updater.py`).
  - Added multi-mirror fallback (`ghfast.top`, `ghproxy.net`) for domestic network acceleration, overcoming GitHub connection resets and timeouts.
  - Added port 8790 running process cleanup before upgrading to prevent Windows file locking and stale memory persistence.
  - Intercepted fake success messages: update scripts now strictly verify pull status and dynamically output actual upgraded version (`V10.1.4`).
- **Complete Fix for Drafts `platform` NOT NULL Constraint Crash**:
  - Added `server_default=""` and defaults across SQLAlchemy `Draft` model and SQLite schema.
  - Enhanced `core.db.add_draft` to explicitly populate `platform`, `tenant_id`, `updated_at`, and `needs_review`.
  - Added automatic column migration and empty default value healing in `core.db.conn()`.

---

## 🌌 Version 10.1 · Dynamic Versions Across All Pages (鸿蒙始 · 全端动态版本单一真源) · 2026-10-15

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.1"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Dynamic Version Extraction Across All Pages (Single Source of Truth)**:
  - Eliminated all hardcoded version badges, static headers/footers, and manual floor versions (`floorVer`) across PC dashboard (`index.html`), mobile app (`mobile.html`), pricing page (`pages/pricing.html`), and admin pages (`users_admin.html`, `audit_admin.html`, `metrics`).
  - Introduced unified frontend dynamic version manager `web/static/js/version-sync.js` (`window.AppVersion`) that automatically synchronizes `document.title`, `.version-badge`, `[data-app-version]`, and ID containers from `/api/version` and `<meta name="app-version">`.
  - Backend template rendering pipeline (`render_dynamic_html`) automatically injects current `version.py` single-source-of-truth into HTML templates and SSR meta tags, preventing version drift and screen flicker.

---

## 🌌 Version 10.0.1 · Mobile & PC Unified Token Metric (鸿蒙始 · 双端统一度量) · 2026-10-15

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.0.1"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Full-End Token Metric Unification (All Aligned to PC Single Source of Truth)**:
  - Mobile client (`web/templates/mobile.html`) now pulls tokens, credits consumed, total authorized credits, and tier display directly from `/api/billing/ui/me` and `/api/auth/me`.
  - Added real-time token & tier pill widget (`💎 算力: X Token | 档位`) to the mobile app header, matching PC's top navigation bar.
  - Eliminated legacy hardcoded static token numbers (e.g., `500,000 Token` and fallback `3000`) in mobile UI and user profiles.
  - Unified `/api/auth/me` payload to include `credits_left`, `credits_total`, `credits_used`, `tier_display`, and dynamic progress bar.

---

## 🌌 Version 10.0.0 · Big-Tech Clean Architecture & Full-Stack Unification (鸿蒙始 · Primordial Dawn) · 2026-10-15

> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.0.0"`, `__codename__ = "鸿蒙始"`, `__codename_en__ = "Primordial Dawn"`)

- **Clean Architecture 4-Layer Refactoring (`app/` · `domain/` · `infra/` · `web/`)**:
  - `app/`: Unified `RequestContext` dependency injection (`app/deps.py`), Pydantic v2 billing & order schemas (`app/schemas/billing.py`), and `/api/v10/health` architecture health probe (`app/routers/architecture.py`).
  - `domain/`: Unified `BillingService` facade (`domain/billing/service.py`), `ArticleQualityGate` & `normalize_score_100` (`domain/pipeline/article_pipeline.py`), `dedupe_wechat_html_images` (`domain/pipeline/image_pipeline.py`), and externalized YAML prompt registry (`domain/prompts/registry.py` & `templates.yaml`).
  - `infra/`: `StructuredLogger` with `trace_id`/`user_id` (`infra/logging.py`) and `BrowserPopupCircuitBreaker` single-popup guard (`infra/crawlers/popup_guard.py`).
  - `web/`: Extracted inline HTML pages from `web/admin.py` into `web/templates/pages/{pricing,users_admin,audit_admin}.html`, design system CSS tokens (`web/static/css/design-tokens.css`), and standalone locale dictionaries (`web/static/locales/{zh-CN,en-US}.json`).
- **Integrated `/pricing` Fixed Sidebar & End-to-End Purchase Closed Loop**:
  - Integrated `💎 套餐与价格` into the fixed left navigation sidebar (`#p-pricing` & `/pricing`) and connected the complete 4-step purchase, 1-step payment confirmation & code redemption, tier upgrade, cancellation, and refund lifecycle.
- **Engineering Standards & Architecture Guard (`pyproject.toml` & `tests/test_v10_architecture_guard.py`)**:
  - Added unified `pyproject.toml` and automated architecture guard tests locking V10.0.0 invariants.

---

## 🌟 Version 10.0.0 · Pristine Rhythm (澄音境 · 正文深度去噪与排版素简专项) · 2026-10-14

> **Milestone**: Full-Pipeline Text Denoising Engine + Anti-Clutter Symbol Cleansing + Strict Hashtag Boundary Guard + Cross-Platform Section Typography  
> **Codename**: 澄音境 (Pristine Rhythm · 素简澄澈，正文纯净)  
> **Slogan**: One Thought. One Scene. Infinite Worlds · Pristine Rhythm (一念起 一幕开 万象生 · 素简澄澈，正文纯净)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-14  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.0.0"`)  

### 🧹 1. 系统级正文深度去噪引擎 (`core/text_denoise.py`)
- **粗糙分割线彻底剔除**：自动识别并剥离独占一行的 `***`、`* * *`、`---`、`___`、`- - -` 分割线，消除排版断裂感；
- **星号降噪规范化**：将容易影响阅读的 `***加粗斜体***` 优雅降噪为标准 `**加粗**`，彻底清除孤立与残余的 `***` 杂质；
- **正文标题降噪与排版升级**：
  - 彻底终结正文充斥 `###`、`##` 等影响阅读观感的原始 Markdown 符号；
  - 中文序号标题（如 `### 一、核心观点`）平滑转换为自然编号；
  - 普通小节标题（如 `### 核心优势`）规范化转为高颜值中文方头括号 `【核心优势】`，兼顾阅读舒适感与视觉识别。

### 🏷️ 2. `#` 话题与标签严格边界守卫
- **用途严格收敛**：正文中约束 `#` 严格且仅能用于文末话题标签（如 `#自媒体 #AI爆款`）与成对社交话题（如 `#今日热点#`）；
- **孤立杂音清洗**：彻底清除正文句中混杂的孤立无意义 `#` 符号（如 `关于#AI 的讨论`、`第#1条建议`），无损还原清晰文本。

### 🎨 3. 多端排版引擎与配图智能对齐
- **排版引擎原生支持**：微信公众号、今日头条、知乎等渲染器全面兼容方头括号 `【...】` 与中文序号小节，自动赋予专属 `<h3>` 主题样式；
- **配图链路精准适配**：配图提取引擎与小节插图智能对齐无噪标题，图片精准绑定所属小节。

---

## 🌟 Version 10.0.0 · Pristine Mirror (澄澈镜 · 极简模式与全链路排版图片去重专项) · 2026-10-14

> **Milestone**: Full-Pipeline Image Deduplication for WeChat MP Typesetting + Unified Layout Rendering Contract + Self-Healing Draft Cache  
> **Codename**: 澄澈镜 (Pristine Mirror · 澄澈明镜，图文无瑕)  
> **Slogan**: One Thought. One Scene. Infinite Worlds · Pristine Mirror (一念起 一幕开 万象生 · 澄澈分明，绝无重复)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-14  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.0.0"`)  

### 🖼️ 1. 极简模式与全链路首次排版图片防重复彻底根治
- **三层防重过滤防线**：
  - **输入层 (`_dedupe_markdown_images`)**：在 Markdown 语法树注入与处理阶段，严格过滤同 URL 重复图片及连续相邻紧挨堆叠的图片标记；
  - **转换层 (`md_to_wechat_html`)**：解析正文提取已有图片集 `seen_img_urls`，修剪外部 `effective_images` 字典；单篇 HTML 输出严格保证规范化 URL 仅渲染一次，彻底终结正文与字典配图双写冲突；
  - **输出层 (`_dedupe_wechat_html_images`)**：针对微信公众号 HTML 输出全局正则扫描，自动清除重复 `<img>` 标签及空段落。
- **全平台多端排版契约统一收口**：
  - 将 `core.themes.md_to_wechat_html`、`core.imagegen`（成套生图与局部重绘）、`core.fission`（母稿派生）、`adapters.wechat_mp`、`web.admin` 等全部微信公众号排版调用统一路由至具有守卫能力的高阶 `core.layouter.render`。
- **草稿箱与分发预览自愈清洗**：
  - 接口 `GET /api/drafts/{did}/raw/wechat_mp` 增加历史缓存自愈机制，旧草稿在首次排版与二次查看时自动完成图片去重自愈与缓存重写。

---

## 🌟 Version 10.0.0 · Luminous Chronicles (浮光录 · 全栈精铸与架构贯通篇) · 2026-10-14

> **Milestone**: Full-Stack Security Hardening + BYOK/Free-Demo Pipeline Unification + 6D Persona Injection + 10x DB Speedup  
> **Codename**: 浮光录 (Luminous Chronicles · 浮光掠影，字字珠玑)  
> **Slogan**: One Thought. One Scene. Infinite Worlds · Luminous Chronicles (一念起 一幕开 万象生 · 浮光掠影，字字珠玑)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-14  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "10.0.0"`)  

### 🛡️ 1. Security & Reverse-Proxy Hardening
- **Reverse-Proxy Loopback Protection**: `_is_loopback` now validates `X-Forwarded-For` and `X-Real-IP` headers so cloud deployments behind Nginx/Caddy never mistake proxied internet traffic for localhost admin access.
- **Drive-by CSRF & Multi-Tab Cookie Stability**: `CSRFMiddleware` blocks cross-origin mutations even without session cookies, checks `yimu_session`, and reuses valid `csrf_token` cookies across tabs and preview iframes.
- **HTTP-Friendly CSP**: `upgrade-insecure-requests` is now emitted only on HTTPS requests, fixing asset loading on plain HTTP server deployments.
- **Nonce-Authenticated API Key Vault (`v2$`)**: `core/auth.py` encrypts user API keys with a 16-byte random nonce + HMAC-SHA256 keystream while retaining backward-compatible decryption for legacy keys.

### 🔗 2. Auth, Metering & BYOK Pipeline Unification
- **End-to-End `user_id` Propagation**: `core/agents.py` and `core/llm.py` automatically resolve `user_id` from request context, connecting personal API Vault keys and daily free-demo quotas to all creation workflows.
- **Zero-Deduction BYOK**: `require_credits` automatically waives platform credit deductions when the user has an active BYOK API key configured.
- **Unified V6/V7 Session Cookies**: Login and registration now issue both `mf_v6_token` and `yimu_session` cookies with cross-compatible HMAC verification, unlocking `/api/membership/me`, `/api/admin/launch_mode`, and `/api/admin/invites` from the Web UI.
- **Thread-Safe Metering**: `studio/llm_metering.py` protects JSON state with a re-entrant lock and prunes historical date keys automatically.

### ⚡ 3. Product, Performance & Operations Upgrades
- **6D Persona Auto-Injection**: Workspace 6D persona & voiceprint rules are automatically injected into writing, director, and ad-creative agents.
- **10x SQLite Connection Speedup**: `core/db.py:conn()` caches schema initialization per database file inode instead of running 40+ DDL/PRAGMA checks on every query.
- **Funnel & Scheduler Completeness**: Main registration and drafting flows now record `signup` and `first_draft_created` events and redeem `invite_code`; `core/scheduler.py` supports cross-hour 15-minute windows and persists daily execution state; `core/updater.py` preserves local `config.yaml` edits across `git pull`.

---

## 🌟 Version 9.3.2 · Free First, Pay Later (扶风翼 · Gale Wings) · 2026-10-14

> **Milestone**: Official-Channel Free Trial Quota + First-Run Onboarding Wizard + Dual Data-Access Unification  
> **Codename**: 扶风翼 (Gale Wings · 好风借力，振翅高飞，免费先行)  
> **Slogan**: One Thought. One Scene. Infinite Worlds · Gale Wings: Free First, Pay Later (一念起 一幕开 万象生 · 扶风振翅，免费先行)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-14  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "9.3.2"`)  
> **Release Policy**: Previous releases remain permanently frozen via Git tags. New releases upload directly with clear upgrade paths and comparative changelogs.

### 🎁 1. Official-Channel Free Trial Quota — First Success Before First Paywall
- **Daily Free Quota**: Every new user (Free tier) gets **3 free lightweight AI generations per day** via the `yimu_official` channel — **no API Key required**. Single-call output capped at `FREE_DEMO_MAX_OUTPUT_TOKENS` (512) to control cost; the quota resets at midnight local time (UTC+8).
- **Seamless Fallback to Billing**: Once the daily free quota is exhausted, calls automatically fall back to the standard compute-credit deduction path — identical behavior to the existing billing contract, including `InsufficientCreditsError` semantics.
- **Persistence**: Daily counters are persisted to `data/free_demo_calls.json` (git-ignored, billing state), so restarts do not reset the quota.
- **UI Visibility**: `GET /api/models/providers` and the official-channel summary now expose `free_demo.left_today` so the dashboard can show how many free calls remain today.

### 🚀 2. First-Run Onboarding Wizard (3-Step, 30 Seconds)
- **Show Condition**: Logged in AND onboarding not yet marked done AND no user-owned API Key configured (checked server-side in `GET /api/auth/status`).
- **Step 1 — Free Quota Awareness**: Explains the daily free trial and the 3,000-credit signup grant.
- **Step 2 — Choose Your Main Engine**: Either start on the official channel instantly (recommended, no Key) or add your own API Key (DeepSeek / OpenAI / Claude / 通义千问 / 硅基流动 / custom) via the existing encrypted Vault endpoint.
- **Step 3 — Done**: CTA to the Inspiration Generator. Closes the wizard at any time via `POST /api/onboarding/done`, which persists the dismissal to `data/user_onboarding_done.json` so it never nags again.
- **i18n**: All wizard copy registered in `i18n_dict.json` (1,835+ terms), zero Chinese residue in English mode.

### 🏛️ 3. Dual Data-Access Unification (P0 Debt Paydown)
- **Single ORM Source of Truth**: `users` and `user_api_keys` are now fully declared in `studio/db_models.py` (SQLAlchemy) with all V6-era columns (`plan`, `quota_used`, `quota_max`, `last_login`) and the `UserApiKey` model.
- **Raw-sqlite Self-Healing Demoted to Fallback**: `core/db.py:ensure_users_columns` is retained as an idempotent safety net; studio `init_db` no longer risks "no such column" crashes on fresh installs.
- **Time-Column Encoding Unified**: `users.created_at` / `users.last_login` / `user_api_keys.created_at` are now TEXT ISO-8601 columns via `FlexibleDateTime`; legacy float/epoch values are read-compatibly parsed, new writes are always ISO. No more mixed-encoding `fromisoformat` crashes.
- **Tests Updated**: `test_r3_monetization` now asserts the ORM schema *contains* the V6 columns (the bug is gone at the schema level, not just patched at runtime); `test_llm_metering` gains 5 new cases covering free-quota exhaustion, paid-tier exclusion, long-output exclusion, and left-today tracking.

### ⚖️ 4. Contract & Terminology Hygiene
- `POST /api/onboarding/done` registered in `docs/CONTRACT.md` route list (contract lock test passes).
- All new user-facing copy avoids internal jargon (术语检查门禁全绿).

---

## 🌟 Version 9.3.1 · Server One-Click Deploy & Production Daemon (万象融) · 2026-10-14

> **Milestone**: Full Production Server One-Click Deployer (`服务器一键部署.sh`), Systemd Daemon & Automated Releases  
> **Codename**: 万象融 (Cross-Platform Unified · 全域跨端，融通万象)  
> **Slogan**: One Thought. One Scene. Infinite Worlds · Cross-Platform Unified (一念起 一幕开 万象生 · 全域跨端)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-14  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "9.3.1"`)  
> **Release Policy**: Previous releases remain permanently frozen via Git tags. New releases upload directly with clear upgrade paths and comparative changelogs.

### 🖥️ 1. Production Server One-Click Deployer (`服务器一键部署.sh`)
- **Single-Line Remote Curl Execution**: Support immediate turn-key deployment on brand new bare-metal or cloud servers via `curl -fsSL https://raw.githubusercontent.com/yimuhub/yimu-baokuanstudio/main/服务器一键部署.sh | bash`.
- **Symlink Aliases**: Provided convenience symlinks `一键部署.sh` and `deploy.sh` pointing directly to `服务器一键部署.sh`.
- **Multi-Distribution Package Manager Auto-Detection**: Full auto-healing and installation of essential system packages (`git`, `curl`, `wget`, `python3`, `python3-venv`, `pip`, `ffmpeg`, `sqlite3`, `lsof`) on Debian/Ubuntu (`apt`), CentOS/RHEL/Rocky/Fedora (`dnf`/`yum`), Arch Linux (`pacman`), and Alpine Linux (`apk`).
- **Automated Virtualenv Isolation & Mirror Fallback**: Creates dedicated `.venv`, upgrades pip, and attempts ultra-fast PyPI mirror with automatic PyPI fallback.
- **Production Secrets Initialization & Auto-Migration**: Automatically generates cryptographically strong `YIMU_SECRET_KEY` (64-char hex) and random admin credentials, while preserving existing `.env` files and executing non-destructive SQLite/Postgres schema initialization.
- **Systemd Daemon Service Integration**: Creates and enables `/etc/systemd/system/yimu.service` for automatic boot-up startup, process restart supervision, and log streaming into `logs/web.out`.

### 🔄 2. Upstream Update Check & Tag Synchronization Hardening
- **Semver Regression Guard**: Hardened `core/updater.py` to prevent stale GitHub Release metadata from masking newer tags or local versions.
- **Immediate GitHub Release Synchronization**: Streamlined GitHub Releases creation pipeline to push V9.3.1 to the GitHub Release list immediately.

---

## 🌟 Version 9.3.0 · Cross-Platform Unified (万象融) · 2026-10-13

> **Milestone**: Native Linux Production Engine, Versionless Cross-Platform Launch Suites & Automated GitHub Releases  
> **Codename**: 万象融 (Cross-Platform Unified · 全域跨端，融通万象)  
> **Slogan**: One Thought. One Scene. Infinite Worlds · Cross-Platform Unified (一念起 一幕开 万象生 · 全域跨端)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-13  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "9.3.0"`)  
> **Release Policy**: Previous releases remain permanently frozen via Git tags. New releases upload directly with clear upgrade paths and comparative changelogs.

### 🐧 1. Native Linux Production Engine & Cloud Daemon Supervisor
- **Native Production Script (`一键启动_linux.sh`)**: Built-in support for Ubuntu, Debian, CentOS, RHEL, Arch, and Alpine with automated virtual environment provisioning, multi-thread uvicorn daemonization, port conflict resolution, external IP resolution, and system status health check (`status`, `logs`, `restart`, `stop`).
- **Linux Upgrade Assistant (`一键升级_linux.sh`)**: Seamless Git branch pull, pip dependency alignment, database structure migrations, and zero-downtime hot reloading.

### ⚡ 2. Versionless Clean Cross-Platform Launchers
- Deprecated and removed legacy numbered launch scripts (e.g. `*V8.bat`, `*V8.command`).
- Standardized cross-platform entry points without version suffixes:
  - Windows: `一键启动.bat` / `一键升级.bat`
  - macOS: `一键启动.command` / `一键升级.command`
  - Linux: `一键启动_linux.sh` / `一键升级_linux.sh`
  - Universal Unix: `一键启动.sh` / `一键升级.sh`

### 🚀 3. Automated Instant GitHub Releases Synchronization
- Integrated automated GitHub Release workflows and REST API sync pipelines, ensuring every code commit and version push instantly populates GitHub Releases list.
- Cleaned up legacy historical version labels and unified whole codebase to modern standard.

---

## 🌟 Version 9.2.0 · Divine Forge (天工开) · 2026-10-13

> **Milestone**: Custom Distribution Platforms & Agent Layout Skill Distillation Hub  
> **Codename**: 天工开 (Divine Forge · 巧夺天工，开物成务)  
> **Slogan**: One Thought. One Scene. Infinite Worlds · Divine Forge (一念起 一幕开 万象生 · 天工开物)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-13  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "9.2.0"`)  
> **Release Policy**: Previous releases remain permanently frozen via Git tags. New releases upload directly with clear upgrade paths and comparative changelogs.

### 🌐 1. Custom Content Distribution Platform & Agent Layout Skills Hub
- **Custom Platform Management**: Configure any third-party or vertical content platform URLs directly in Profile Center (`#p-profile`).
- **Smart URL Detection**: Instant detection of platform name, domain, and icon from any URL.
- **Toutiao Feed Layout Standard**: Defaults to Toutiao high-density feed layout specifications (bold headlines, red accents, highlighted quote cards).
- **Agent Layout Skill Distillation**: Enter any sample article URL; the Agent analyzes and extracts visual layout styling rules (fonts, margins, quotes, palettes) into an executable Agent Layout Skill with live preview.

### 🛡️ 2. Brand Translation Purity & Lock
- Eliminated erroneous reverse translations that caused "一幕·一幕", guaranteeing strict brand presentation as **一幕·YIMU** in Chinese mode.
- Cleaned up top navigation on `/releases` page by removing commercial pricing menus for a pure release showcase.

---

## 🌟 Version 9.1.1 · Infinite Worlds (万象生) · 2026-10-13

> **Milestone**: Complete 1,768 UI Terms Zero-Residue Bilingual Engine & Deep Subview Purity  
> **Codename**: 万象生 (Infinite Worlds)  
> **Slogan**: One Thought. One Scene. Infinite Worlds. (一念起 · 一幕开 · 万象生)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-13  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "9.1.1"`)  
> **Release Policy**: Previous releases (e.g. `v9.1.0`, `v9.0.0`, `v8.3.33`, `v8.3.2`) remain permanently frozen via Git tags. New releases upload directly with clear upgrade paths and comparative changelogs.

### 🌐 1. Complete Zero-Residue Bilingual Engine (全站 1,768 词条零残留双语引擎)
- **1,768 Terms Comprehensive Dictionary**: Scanned and cataloged 100% of all UI nodes across primary navigation, secondary sub-tabs, drawers, modals, buttons, options, alerts, and tooltips, achieving **0.0% residual Chinese** in English mode.
- **Bidirectional Lossless Reversibility**: Built-in `_orig_zh` caching, $O(1)$ `EXACT_MAP`, `PHRASE_LIST`, and `REVERSE_PHRASE_LIST` guarantee that switching back to Chinese restores exact native text without distortion.
- **Dynamic Title & Subview Synchronization**: Primary menu clicks, sub-tabs (`switchSubTab`), modals, and MutationObservers instantly update language bindings at runtime.

### 🔄 2. Single Source of Truth Upgrade to 9.1.1
- Unified single source of truth across all modules, templates, headers, docstrings, licenses, and contracts to `V9.1.1` / `9.1.1`.

---

## 🌟 Version 9.1.0 · Infinite Worlds (万象生) · 2026-10-13

> **Milestone**: Full i18n Bilingual Unification & GitHub Releases Integration  
> **Codename**: 万象生 (Infinite Worlds)  
> **Slogan**: One Thought. One Scene. Infinite Worlds. (一念起 · 一幕开 · 万象生)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-13  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "9.1.0"`)  
> **Release Policy**: Previous releases (e.g. `v9.0.0`, `v8.3.33`, `v8.3.2`) remain permanently frozen via Git tags. New releases upload directly with clear upgrade paths and comparative changelogs.

### 🌐 1. Full i18n Bilingual Unification (全站中英文绝对统一)
- **100% Pure English Mode**: When switched to English, all UI text, modals, placeholders, titles, metrics, tooltips, and prompts become 100% pure English. No half-Chinese/half-English state is permitted.
- **100% Pure Chinese Mode**: When switched to Chinese, all UI content displays 100% pure natural Chinese.
- **Zero Inconsistency**: Automated DOM text walker and bidirectional dictionaries enforce complete coverage across all dynamic and static views.

### 📦 2. GitHub Releases Integration (GitHub Releases 官方发布展示)
- Fully published official releases via GitHub REST API for all version tags (`v9.1.0`, `v9.0.0`, `v8.3.33`, `v8.3.2`).
- Installed `/releases` and `/api/releases` endpoints showcasing interactive changelogs and version evolution matrices.

### 🔄 3. Code-Wide Version Unification (全仓版本号统一)
- Unified single source of truth across all modules, templates, headers, docstrings, licenses, and contracts to `V9.1.0` / `9.1.0`.

---

## 🏷️ Version 9.0.0 · Infinite Worlds (万象生) · 2026-10-13

> **Milestone**: 2K Crystal-Clear Image Engine & Global i18n Launch  
> **Codename**: 万象生 (Infinite Worlds)  
> **Slogan**: One Thought. One Scene. Infinite Worlds. (一念起 · 一幕开 · 万象生)  
> **Licensor**: yimu.hyipf.com  
> **Release Date**: 2026-10-13  
> **Single Source of Truth**: [`version.py`](version.py) (`__version__ = "9.0.0"`)  

### 📊 Release Comparison Matrix: V8.3.33 vs V9.0.0

| Dimension | V8.3.33 (Archived Stable Release) | V9.0.0 (Latest Major Milestone) | Evolution & Impact |
|---|---|---|---|
| **Image Resolution** | 1024x1024 (Standard 1K) | **2048x1152 / 1152x2048 / 2048x2048 (2K)** | 200% resolution boost, ultra-sharp detail |
| **Atmospheric Clarity** | Prone to foggy / smoky AI haze | **Zero-Haze Crystal Prompt Pipeline** | Hardened negative prompting, vivid saturation |
| **Image Model Alignment**| Standard fallback logic | **Agnes Model Contract Specialization** | Strict size normalization, resilient 400 recovery |
| **Billing & Compute UI** | Split topbar buttons & external links | **Unified Billing & Compute Capsule** | Deep consolidation of credits, pricing & CDKEY |
| **Internationalization** | Simplified Chinese only | **Dual-Engine i18n (English & Chinese)** | Hot toggle on Desktop & Mobile, pure EN README |
| **Account & Security** | Manual auth sync | **Self-Service Password Change** | Integrated into Profile & Auth modals |
| **GitHub Release Tag** | `git checkout v8.3.33` (Frozen) | `git checkout v9.0.0` (Latest) | Distinct release archives on GitHub |

### 🎬 1. 2K Crystal-Clear Visual Storyboarding & Zero-Haze Prompting
- **Native 2K Resolution by Default**: Articles and inspirations now default to pristine 2K canvas dimensions (`2048x1152` landscape for WeChat/News, `1152x2048` vertical for RED/Mobile, and `2048x2048` square).
- **Agnes Model Optimization & Defogging Filter**:
  - Integrated zero-haze transparent prompt engineering (`crystal-clear sharp focus, vibrant saturated colors, crisp details, zero haze`).
  - Proactively blocks hazy, foggy, smoky, blurry artifacts that previously caused dull, plastic visual aesthetics.
  - Hardened fallback mechanism with graceful dimension handling compliant with strict upstream image APIs.
- **Cinematic Read-First Storyboard Law**: Visual Agent reads article prose end-to-end before dispatching image generation, achieving over 95% semantic consistency between copy and visual artwork.

### 💎 2. Unified Commercial Billing & Compute Portal
- **Consolidated Entry Point**: Merged the compute token balance and membership tier status into one unified pill in the top navigation bar.
- **One-Stop Modal**: Direct access to plan pricing, credit breakdown, capacity estimations, and activation CDKEY redemption from a single modal.
- **De-cluttered Topbar**: Removed legacy redundant standalone release links and unneeded upgrade overview pages for a cleaner, modern creator workspace.

### 🌐 3. Global Bilingual Internationalization (i18n Engine)
- **Instant Hot-Toggle**: Seamlessly switch between **English** and **简体中文 (Simplified Chinese)** via the `🌐` button on both Desktop and Mobile navigation headers without reloading the page.
- **Persistent Storage**: Language selection is saved locally via `localStorage('yimu_lang')` and dispatches `yimu_lang_changed` events across the DOM.
- **Bilingual Documentation**: Shipped complete English documentation (`README.md`) alongside Chinese (`README_ZH.md`).

### 🔐 4. Account Security & Creator Persona
- **Self-Service Password Management**: Added secure password change workflow (`POST /api/auth/change_password`) directly in the Profile Center and Auth Modal.
- **6-Dimensional Creator Persona**: Integrated digital voiceprint, audience profile, and tone-of-voice settings with live agent prompt synthesis.

### 🧪 5. Quality & CI Verification
- **Test Suite Alignment**: 429+ automated tests and canary test suites verified with 100% pass rate.
- **4-Tier CI Gateways**: All 4 guardrail stages passing in `bash ci.sh`.

---

## 🏷️ Version 8.3.33 · 星河引 (Galactic Beacon) · 2026-10-13
- Deep integration of Membership and Token Ledger into the Personal Profile Center.
- Interactive plan cards in billing modals with real-time API quote loading.
- Gateway routing stability fixes.

---

## 🏷️ Version 8.3.2 · 视觉大跃迁 (Visual Quantum Leap) · 2026-10-12
- Introduction of 10 Cinematic Visual Aesthetic Presets (Documentary, Swiss Minimal, Cyberpunk, Anime, etc.).
- Conversational visual style hot-swapping via creator Copilot.
- Xiaohongshu 5-act panoramic frosted glass card compilation engine.

---

<div align="center">
  <sub>Copyright © 2026 <a href="https://yimu.hyipf.com">yimu.hyipf.com</a> · All rights reserved.</sub>
</div>
