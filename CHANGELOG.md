# 📝 Changelog · 一幕·YIMU 爆款工作室

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## 🧭 Release Evolution & Version Management Philosophy (版本演进与发布规范)

YIMU Studio maintains strict version discipline:
1. **Permanent Git Tags for Historical Releases**: Every version is permanently tagged (e.g., `v8.3.33`, `v9.0.0`). Older versions remain 100% frozen, unmodified, and downloadable at any time.
2. **Direct Forward Releases**: New features and upgrades are shipped directly under subsequent version increments (Major `X.0.0`, Minor `X.Y.0`, Patch `X.Y.Z`).
3. **Transparent Upgrade Path**: Clear comparative matrices document breaking changes, aesthetic upgrades, and API evolution between milestones.

### 📌 How to Access Different Versions on GitHub:
- **Switch to Archived V8.3.33**:
  ```bash
  git checkout v8.3.33
  ```
- **Switch to Latest V9.0.0 (Infinite Worlds)**:
  ```bash
  git checkout v9.0.0
  # Or track latest main
  git checkout main && git pull origin main
  ```
- **Download Source Bundles on GitHub**:
  Visit [GitHub Releases / Tags](https://github.com/yimuhub/yimu-baokuanstudio/tags) to download exact `.zip` or `.tar.gz` packages for any historical release.

---

## 📊 Major Milestone Comparison: V8.3.33 vs V9.0.0 (核心版本差异矩阵)

| 核心维度 Dimension | V8.3.33 (Archived Stable Release) | V9.0.0 (Latest Major Milestone) | 升级演进说明 Evolution & Impact |
|---|---|---|---|
| **配图默认分辨率 (Image Resolution)** | 1024x1024 (标准 1K 画幅) | **2048x1152 / 1152x2048 / 2048x2048 (原生 2K)** | 极简与灵感模式出图分辨率翻倍，细节极致纤毫毕现 |
| **画面通透感 (Atmospheric Clarity)** | 易产生灰蒙蒙的雾感与烟雾朦胧 | **零烟雾通透滤镜 (Zero-Haze Prompt Pipeline)** | 强力注入高饱和、高锐度，严厉负向剔除 fog/smoke/blur |
| **生图大模型适配 (Model Adaptation)** | 基础生图接口，易触发 400 size 限制 | **Agnes 图像大模型深度协议对齐** | 严格规范画幅尺寸，内置 400 智能自愈与重试保护 |
| **商业化与算力入口 (Billing Portal)** | 顶栏按钮割裂、含外部版本号跳转链接 | **商业化算力与套餐价格深度合并统一胶囊** | 彻底下线冗余跳转页，算力/套餐/卡密一站式极速弹窗 |
| **国际化多语言 (Internationalization)** | 仅支持简体中文单语言 | **中英双语 (i18n) 全域即时热切换** | Desktop 与 Mobile 双端支持，GitHub 纯英文专业说明 |
| **账号安全与管理 (Account Security)** | 无法自主修改登录口令 | **个人中心与口令弹窗集成修改密码** | 后端 `/api/auth/change_password` 严格校验加密更新 |
| **GitHub 归档管理 (Git Release)** | `git tag v8.3.33` 独立归档冻结 | `git tag v9.0.0` (Latest 旗舰版) | 老版本保持冻结原貌不变，新版本直推发布 |

---

## [9.4.1] - 2026-10-14 · 浮光录 (Luminous Chronicles)

### Added & Upgraded
- **Full-Stack `user_id` & BYOK Pipeline Unification**: Automatic context `user_id` propagation across `core/agents.py` (`chat_for`) and `core/llm.py` (`resolve_llm_endpoint`, `chat`), ensuring user-configured API Vault keys (BYOK) and free-demo metering work across all creation, rewriting, and short-drama stages. When an active BYOK key is present, `require_credits` automatically waives platform credit deductions.
- **6D Persona Profile Auto-Injection**: Workspace 6D persona profiles (`build_profile_system_prompt`) are now automatically injected into `compose_system` for writing, director, and ad-creative agents.
- **Local Config Overlay (`data/config.local.yaml`) & Conflict-Free Online Upgrade**: `core/llm.py` supports merging `data/config.local.yaml`, and `core/updater.py` automatically stashes/restores local `config.yaml` edits during `git pull`.
- **Database Connection Initialization Cache**: `core/db.py:conn()` caches schema/migration verification per database file inode, eliminating 40+ redundant DDL/PRAGMA queries per call (10x+ speedup).

### Fixed & Hardened
- **Reverse-Proxy Loopback Guard**: `_is_loopback` in `web/admin.py` now inspects `X-Forwarded-For` / `X-Real-IP` to prevent Nginx/Caddy reverse proxies from unintentionally granting loopback super-admin access to remote clients.
- **CSRF & Dynamic CSP Hardening**: `core/security_middleware.py` now enforces CSRF on cross-origin requests even without cookies (blocking Drive-by Localhost CSRF), checks `yimu_session`, reuses existing valid `csrf_token` cookies across tabs/iframes, and only emits `upgrade-insecure-requests` over HTTPS.
- **V6/V7 Session & Auth Unification**: `core/auth.py` and `studio/auth.py` now share cross-compatible token verification and dual-cookie (`mf_v6_token` + `yimu_session`) issuance; `encrypt_key` upgraded to `v2$` random-nonce HMAC stream cipher with backward compatibility.
- **Growth Funnel & Scheduler Fixes**: `/api/auth/register` and `orchestrator` now emit `signup` and `first_draft_created` funnel events and support `invite_code` referral redemption; `core/scheduler.py` supports cross-hour 15-minute windows and persists daily ticket state; `rewrite_single_platform` respects custom `instruction` on Xiaohongshu rewrites.

---

## [9.3.2] - 2026-10-14 · 扶风翼 (Gale Wings: Free First, Pay Later)

### Added
- **Official-Channel Free Trial Quota (P0-1)**: New users (Free tier) get **3 free lightweight AI generations per day** via the `yimu_official` channel — no API Key required, single-call output capped at 512 tokens, quota resets daily (UTC+8), counters persisted to `data/free_demo_calls.json`. Exhaustion falls back to normal compute-credit billing, preserving the existing `InsufficientCreditsError` contract.
- **First-Run Onboarding Wizard (P1-1)**: 3-step 30-second setup on first login (free-quota awareness → choose main engine: official channel or own API Key → done). Dismissal persisted via `POST /api/onboarding/done` → `data/user_onboarding_done.json`, never nags again. All wizard copy registered in `i18n_dict.json` (now 1,835+ terms).
- **Dual Data-Access Unification (P0-2)**: `users` and `user_api_keys` fully declared in the SQLAlchemy source of truth (`studio/db_models.py`), including V6-era columns (`plan`, `quota_used`, `quota_max`, `last_login`) and the `UserApiKey` model; raw-sqlite self-healing demoted to guarded fallback. Time columns unified to ISO-8601 via `FlexibleDateTime`.
- **Test Coverage**: 5 new `test_llm_metering` cases (free-quota exhaustion, paid-tier exclusion, long-output exclusion, left-today tracking); `test_r3_monetization` updated to assert ORM schema contains V6 columns; `docs/CONTRACT.md` registers the new onboarding route.

### Changed
- **Single Source of Truth (`version.py`)**: `__version__ = "9.3.2"`, `__codename__ = "扶风翼"`, slogan "Gale Wings: Free First, Pay Later".
- **User-facing copy**: internal jargon ("降级") replaced with user-friendly wording across `web/`, `studio/`.
- **All version references** (templates, i18n, license, README, RELEASES) unified to V9.3.2.

---

## [9.1.0] - 2026-10-13 · 万象生 (Infinite Worlds)

### Added
- **Full i18n Bilingual Unification**: Upgraded `web/static/js/i18n.js` with deep DOM auto-translation and comprehensive bidirectional dictionaries. Enforces 100% pure English when in English mode and 100% pure Chinese when in Chinese mode, eliminating any half-English/half-Chinese inconsistencies.
- **GitHub Releases Official Showcase**: Created GitHub Releases via GitHub REST API for all releases (`v9.1.0`, `v9.0.0`, `v8.3.33`, `v8.3.2`).
- **Installed Releases Showcase View & API**: Mounted `GET /releases`, `GET /admin/releases`, and `GET /api/releases` for seamless version tracking.

### Changed
- **Unified Single Source of Truth**: Updated all version references, docstrings, licenses, and contracts to `V9.1.0` / `9.1.0`.
- **Licensor Alignment**: Licensor strictly set to `yimu.hyipf.com` in `LICENSE` and across legal notices.

---

## [9.0.0] - 2026-10-13 · 万象生 (Infinite Worlds)

### Added
- **2K Cinematic Storyboard Visual Engine**: Default canvas dimensions upgraded to 2K resolution (`2048x1152` landscape for articles, `1152x2048` portrait for RED notes, and `2048x2048` square).
- **Agnes Model Zero-Haze Prompt Pipeline**:
  - Positive crystal-clarity prompt engineering: `crystal-clear sharp focus, vibrant saturated colors, crisp details, zero haze`.
  - Negative haze/smoke suppression: Aggressively filters out words causing hazy, foggy, or blurry AI artifacts.
  - Strict parameter normalization ensuring compliance with vision models that require specific size patterns.
- **Global Bilingual Internationalization Engine (`web/static/js/i18n.js`)**:
  - Hot toggle between English and Simplified Chinese on PC topbar and Mobile header.
  - Full DOM translation dictionary with `data-i18n` binding and `localStorage` persistence.
- **Bilingual Documentation**:
  - Full English specification [`README.md`](README.md).
  - Preserved Chinese guide [`README_ZH.md`](README_ZH.md) with two-way cross links.
- **Milestone Release Documentation**:
  - Published [`RELEASES.md`](RELEASES.md) and [`CHANGELOG.md`](CHANGELOG.md).
- **Automated Test Guardrails**:
  - Created [`tests/test_v90_release_and_i18n.py`](tests/test_v90_release_and_i18n.py) covering version single source of truth and legacy version sanitization.

### Changed
- **Unified Billing & Compute Hub**: Merged separate price buttons and token pills into a single consolidated capsule (`.unified-billing-pill`).
- **Single Source of Truth (`version.py`)**: Bumped `__version__ = "9.0.0"`, `__codename__ = "万象生"`, `__slogan_en__ = "One Thought. One Scene. Infinite Worlds."`.
- **System Updater**: User-Agent dynamically reads `version.__version__`.

### Removed
- **Topbar Release Link & Deprecated Pages**: Completely removed legacy release link `<a id="nav-release-entry">` and deprecated `/admin/releases` overview page to maintain a sleek, clean workspace.

---

## [8.3.33] - 2026-10-13 · 星河引 (Galactic Beacon)

### Added
- **Personal Profile Center Integration**: Migrated membership tiers and compute ledgers into the independent Personal Center panel (`#p-profile`).
- **Interactive Billing Plan Selection**: Added interactive clicking and highlighting for Free, Pro, and Studio plan cards in both billing modals and personal profile sections.
- **Account Password Management**: Added change password modal tab and connected backend `POST /api/auth/change_password`.
- **Permanent Tag**: Frozen as git tag `v8.3.33`.

---

## [8.3.2] - 2026-10-12 · 视觉大跃迁 (Visual Quantum Leap)

### Added
- 10 Curated Visual Aesthetic Presets (Documentary, Swiss Minimal, Cyberpunk, Anime, etc.).
- Conversational visual style hot-swapping via creator Copilot.
- Xiaohongshu 5-act panoramic frosted glass card compilation engine.
- Permanent Tag: Frozen as git tag `v8.3.2`.

---

<div align="center">
  <sub>Copyright © 2026 <a href="https://yimu.hyipf.com">yimu.hyipf.com</a> · All rights reserved.</sub>
</div>
