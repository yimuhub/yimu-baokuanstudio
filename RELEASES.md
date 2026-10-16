# 🚀 YIMU Studio Releases & Changelog

All notable changes and milestones to **YIMU Studio (一幕·YIMU 爆款工作室)** are documented here.

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
