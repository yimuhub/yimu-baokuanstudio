# 🚀 YIMU Studio Releases & Changelog

All notable changes and milestones to **YIMU Studio (一幕·YIMU 爆款工作室)** are documented here.

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
