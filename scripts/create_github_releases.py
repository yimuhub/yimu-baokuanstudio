#!/usr/bin/env python3
"""Create and sync GitHub Releases via GitHub REST API."""
import json
import subprocess
import urllib.request
import sys

import os

def get_token():
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        return token.strip()
    try:
        auth_out = subprocess.check_output(
            ['git', 'credential', 'fill'],
            input='url=https://github.com/yimuhub/yimu-baokuanstudio.git\n',
            text=True
        )
        for line in auth_out.splitlines():
            if line.startswith('password='):
                return line.split('=', 1)[1]
    except Exception:
        pass
    raise RuntimeError("No token found from GITHUB_TOKEN env or git credential helper")

def get_existing_releases(token):
    req = urllib.request.Request(
        'https://api.github.com/repos/yimuhub/yimu-baokuanstudio/releases',
        headers={
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'YimuStudio-Release-Manager'
        }
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def create_or_update_release(token, tag, name, body, is_latest=False):
    existing = get_existing_releases(token)
    found_id = None
    for r in existing:
        if r.get('tag_name') == tag:
            found_id = r.get('id')
            break

    payload = {
        'tag_name': tag,
        'name': name,
        'body': body,
        'draft': False,
        'prerelease': False,
    }
    if is_latest:
        payload['make_latest'] = 'true'

    data = json.dumps(payload).encode('utf-8')
    if found_id:
        url = f'https://api.github.com/repos/yimuhub/yimu-baokuanstudio/releases/{found_id}'
        method = 'PATCH'
    else:
        url = 'https://api.github.com/repos/yimuhub/yimu-baokuanstudio/releases'
        method = 'POST'

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'YimuStudio-Release-Manager',
            'Content-Type': 'application/json'
        },
        method=method
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                res = json.loads(resp.read().decode())
                print(f"[{method}] Release {tag}: {res.get('html_url')}")
                return res
        except Exception as e:
            if attempt == 3:
                raise
            import time
            time.sleep(2)

RELEASES_DATA = [
    {
        "tag": "v8.3.2",
        "name": "v8.3.2 - 智瞳境 · Visual Storyboard & Dual Pipeline Engine",
        "body": """# 🎬 一幕 · 爆款工坊 (YIMU Studio) V8.3.2

> **版本代号 / Codename**: 智瞳境 · Visual Storyboard  
> **发布日期 / Release Date**: 2026-10-11  
> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1  
> **发布类型 / Release Type**: 视觉分镜核心引擎基线里程碑

---

### 🌟 版本概述 (Overview)
V8.3.2 正式奠定了爆款工坊的影视级视觉分镜能力，实现了文章草稿生成与段落视觉插图的全自动编排。

---

### 🆕 新增功能 (New Features)
1. **AI 视觉分镜编排系统 (Visual Storyboard Injection)**:
   - 自动解析长文中的二级标题 (H2) 与核心情绪拐点；
   - 提取段落关键语义，生成多级镜头语言、光影构图与配图提示词；
   - 自动在 Markdown 正文中精准注入配图 Markdown 标记。
2. **十大视觉美学风格预设 (10 Aesthetic Presets)**:
   - 预设纪录片写实、新海诚动漫、极简 3D、赛博朋克、瑞士平面排版等 10 套电影级风格矩阵；
   - 支持根据文章主题自适应匹配画风色调。
3. **双通道生图调度引擎 (Dual Pipeline Engine)**:
   - 支持本地/云端 API 双引擎调度，保障生图链路的高可用性。

---

### 🛠️ 功能优化与更新 (Updates & Enhancements)
- **提示词模块化组装**: 重构提示词拼装逻辑，将主体、环境、构图、光效分层解耦；
- **渲染进度可视化**: 配图生成时提供段落级任务状态反馈。

---

### 🐛 修复说明 (Bug Fixes)
- 修复长文多图并发生成时容易发生网络超时导致的整篇生成失败；
- 修复 Markdown 复杂特殊字符在插图注入时破坏原本排版结构的问题。

---

### ⚖️ 与上一版本升级区分 (Differences vs Previous Version)
- **视觉插图**: 从纯文本写作演进为“图文一体化”的视觉分镜写作；
- **画风控制**: 从零散提示词升级为 10 大标准化美学系统。

---

### 📦 获取与使用 (How to Access)
```bash
git checkout v8.3.2
```

---

> **版权声明**: Copyright © 2026 [yimu.hyipf.com](https://yimu.hyipf.com). All rights reserved.
""",
        "is_latest": False
    },
    {
        "tag": "v8.3.33",
        "name": "v8.3.33 - 灵犀汇 · Unified Identity & Profile Center",
        "body": """# 👤 一幕 · 爆款工坊 (YIMU Studio) V8.3.33

> **版本代号 / Codename**: 灵犀汇 · Unified Identity & Profile Center  
> **发布日期 / Release Date**: 2026-10-12  
> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1  
> **发布类型 / Release Type**: 个人中心与多租户隔离稳定归档版

---

### 🌟 版本概述 (Overview)
V8.3.33 重点重构了用户身份鉴权、个人中心面板与会员算力体系，将分散的配置项与账本记录彻底整合。

---

### 🆕 新增功能 (New Features)
1. **独立统一个人中心面板 (Personal Profile Center)**:
   - 在主界面新增现代化个人中心视图 (`#p-profile`)，解耦原有的杂乱弹窗；
   - 集中展示用户当前会员等级（体验版、专业版、工作室版）、账号状态与算力余额。
2. **算力调用账本与充值交互 (Compute Ledger)**:
   - 完整展示每次文本生成与生图扣减的流水明细；
   - 会员套餐卡片支持交互式点击、权益高亮对比。
3. **账号密码自主修改安全功能 (Password Self-Service)**:
   - 新增修改密码模态弹窗，打通后端 `/api/auth/change_password` 鉴权更新。

---

### 🛠️ 功能优化与更新 (Updates & Enhancements)
- **侧边栏常驻抽屉同步**: 侧边栏左下角常驻展示个人中心入口与登录状态指示；
- **算力事务强一致性**: 账本全面启用 SQLite WAL 模式，确保并发扣点时的强原子性。

---

### 🐛 修复说明 (Bug Fixes)
- 修复登录态切换时侧边栏头像徽章未能即时刷新的展示延迟缺陷；
- 修复高频并发调用下账本偶尔可能发生脏读或重试超时的边界异常。

---

### ⚖️ 与上一版本 (V8.3.2) 升级区分 (Differences vs V8.3.2)
- **个人中心**: V8.3.2 缺乏统一身份视窗，V8.3.33 建立专属现代化个人中心；
- **安全管理**: V8.3.2 无法修改口令，V8.3.33 支持完整的用户密码修改与验证流程。

---

### 📦 获取与使用 (How to Access)
```bash
git checkout v8.3.33
```

---

> **版权声明**: Copyright © 2026 [yimu.hyipf.com](https://yimu.hyipf.com). All rights reserved.
""",
        "is_latest": False
    },
    {
        "tag": "v9.0.0",
        "name": "v9.0.0 - 万象生 · Infinite Worlds (AI Storyboard & Global i18n Launch)",
        "body": """# 🌍 一幕 · 爆款工坊 (YIMU Studio) V9.0.0

> **版本代号 / Codename**: 万象生 · Infinite Worlds  
> **发布日期 / Release Date**: 2026-10-13  
> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1  
> **发布类型 / Release Type**: 2K超清生图与全站多语言架构里程碑

---

### 🌟 版本概述 (Overview)
V9.0.0 代表一幕工坊迈向全球化与影视级画质的重大升级，原生全面拥抱 2K 超清生图与中英双语国际化。

---

### 🆕 新增功能 (New Features)
1. **原生 2K 影视级视觉分镜引擎 (2K Resolution Upgrade)**:
   - 配图默认分辨率全面提升至 2K（横屏 `2048x1152`、竖屏 `1152x2048`、正方 `2048x2048`），出图清晰度与细节纤毫毕现；
   - 智能适配文章、小红书图文与视频分镜多种应用场景。
2. **全球化中英双语国际化引擎 (Global i18n Architecture)**:
   - 引入双语中英文即时切换机制，PC 端顶栏与移动端抽屉栏均可一键无缝热切换；
   - 官方中英文双语核心文档（`README.md` 与 `README_ZH.md`）双向对齐互通。
3. **商业化算力与套餐购买统一胶囊**:
   - 深度合并顶栏价格入口与算力显示，下线多余页面，实现极速一站式算力充值。

---

### 🛠️ 功能优化与更新 (Updates & Enhancements)
- **去雾通透画质优化 (Zero-Haze Pipeline)**: 注入高饱和、高锐度色彩，并在负向提示词中强力压制 `fog/haze/smoke`，使生成画面通透鲜艳；
- **版本单一真源体系**: `version.py` 定义统一步进规范。

---

### 🐛 修复说明 (Bug Fixes)
- 修复 AI 生图在复杂提示词下画面灰蒙蒙、模糊不清、浓雾弥漫的严重通病；
- 修复顶栏多处外部失效跳转链接与已废弃页面。

---

### ⚖️ 与上一版本 (V8.3.33) 升级区分 (Differences vs V8.3.33)
- **配图分辨率**: 从 V8.3.33 的 1K (1024x1024) 提升为 V9.0.0 的原生 2K (2048x1152 等)；
- **语言支持**: 从单一中文升级为完整中英双语切换体系；
- **视觉通透度**: 彻底解决画面灰蒙发灰难题，画质饱和度与清晰度大幅提升。

---

### 📦 获取与使用 (How to Access)
```bash
git checkout v9.0.0
```

---

> **版权声明**: Copyright © 2026 [yimu.hyipf.com](https://yimu.hyipf.com). All rights reserved.
""",
        "is_latest": False
    },
    {
        "tag": "v9.1.0",
        "name": "v9.1.0 - 万象生 · Infinite Worlds (100% Bilingual & Unified Versioning)",
        "body": """# 🚀 一幕 · 爆款工坊 (YIMU Studio) V9.1.0 [最新旗舰版 / Latest]

> **版本代号 / Codename**: 万象生 · Infinite Worlds  
> **发布日期 / Release Date**: 2026-10-13  
> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1  
> **发布类型 / Release Type**: 全站纯英文/纯中文绝对统一 & 代码版本全栈对齐

---

### 🌟 版本概述 (Overview)
V9.1.0 是官方最新正式发布版本。本次更新彻底解决了界面语言“半中半英”混杂的历史痛点，实现了全站 100% 纯英文与 100% 纯中文的绝对统一；同时全栈所有代码层级统一步进至 9.1.0，针对 Agnes 图像大模型新规进行了深度规避修复，并正式提供 GitHub 官方 Releases 升级展示。

---

### 🆕 新增功能 (New Features)
1. **全站 100% 纯英文 / 100% 纯中文深度双语引擎 (Zero Half-Bilingualism & Sub-view Coverage)**:
   - 全面覆盖全站 984 个 UI 文本词条（`web/static/js/i18n_dict.json`），纯英文对应率 100.0%，零中文残留；
   - 重构 `web/static/js/i18n.js`，采用 `EXACT_MAP`（$O(1)$ 高速哈希匹配）与 `PHRASE_LIST`（长短语降序安全替换），并具备 100% 可逆恢复 `REVERSE_MAP`；
   - 各级一级菜单（操盘大屏、极简模式、灵感选题、内容工作台、影音工坊、控制中心、个人中心）点击切换时实时适配英文顶栏标题；
   - 所有二级子页面、子标签（`switchSubTab`）与懒加载面板实时挂载递归翻译钩子，彻底消灭“半中半英”或二级子页面漏翻/回跳中文；
   - 增加动态变动监听器 (`MutationObserver`)，毫秒级捕获异步接口返回的内容和弹窗，确保英文模式下 100% 纯英文，中文模式下 100% 纯中文。
2. **应用内版本演进看板与接口 (In-App Releases Showcase)**:
   - 挂载路由 `GET /releases` 与 `GET /admin/releases`，提供全屏版本演化时间轴与特性对照表；
   - 开放接口 `GET /api/releases`，返回各版本详细结构化演进数据。
3. **GitHub Releases 官方发布机制**:
   - 依托 GitHub REST API 建立从 V8.3.2 到 V9.1.0 的正式 Releases 发布与说明体系，告别单纯 Tags 展现。

---

### 🛠️ 功能优化与更新 (Updates & Enhancements)
- **全栈代码版本号统一升级为 9.1.0**:
  - 单一真源 `version.py` 统一定义 `9.1.0`；
  - 核心模块 `web/admin.py`, `web/gateway_ui.py`, `index.html`, `mobile.html`, `studio/__init__.py`, `studio/db_models.py`, `studio/ledger.py`, `core/imagegen.py` 所有层级完全统一为 `9.1.0`，杜绝任何历史旧版本残留；
- **版权主体法务对齐**:
  - `LICENSE` 文件中 Licensor 正式规范变更为 `yimu.hyipf.com`，版本明确标注为 `V9.1.0`。
- **色彩与画面质感深度调优**:
  - 提示词全面升级为高清晰、高饱和、写实通透，杜绝模糊雾化。

---

### 🐛 修复说明 (Bug Fixes)
- 🐛 **修复 Agnes 图像大模型 400 校验报错与参数不兼容**:
  - **画幅规格强制归一化**: 修复了 Agnes 生图模型因接收画幅比例字符串（如 `9:16`、`16:9`）直接抛出 HTTP 400 Bad Request 的严重问题，自动转换为规范的像素尺寸（如 `1152x2048`、`2048x1152`）；
  - **智能剔除 quality 字段并建立容错兜底**: 修复了旧版异常重试中未过滤 quality 导致重试仍报错的隐患，在发生校验异常时自动降解至标准 1024x1024 并剥离不兼容参数重试自愈；
- 🐛 **修复用户文案内部黑话拦截**:
  - 修复发布页面用词，避免触发自动化 CI 黑话与禁用词规则。

---

### ⚖️ 与上一版本 (V9.0.0) 升级区分 (Differences vs V9.0.0)
- **多语言一致性**: V9.0.0 在部分动态异步渲染区域存在中英文混杂，V9.1.0 借助递归 DOM 遍历与监听器实现 100% 绝对纯正中英文；
- **图像模型兼容**: V9.0.0 未适配 Agnes 大模型最新参数规则，易报 400；V9.1.0 具备完善的尺寸映射与智能自愈重试保护；
- **版本号规范**: V9.0.0 各层级存在部分历史徽章残留，V9.1.0 全栈所有文件 100% 统一为 9.1.0；
- **版本展示**: 实现了 GitHub Releases 官方版本详情展示，每个版本均有清晰的更新与修复说明。

---

### 📦 获取与使用 (How to Access)
```bash
# 获取最新 9.1.0 代码
git checkout v9.1.0
# 或者拉取最新 main 分支
git pull origin main
```

---

> **版权声明**: Copyright © 2026 [yimu.hyipf.com](https://yimu.hyipf.com). All rights reserved.
""",
        "is_latest": False
    },
    {
        "tag": "v9.1.1",
        "name": "v9.1.1 - 流光澈 · 万象生篇 (Crystal Clarity · 1,768 UI Terms Zero-Residue Bilingualism)",
        "body": """# 🚀 一幕 · 爆款工坊 (YIMU Studio) V9.1.1 [最新旗舰版 / Latest]

> **版本代号 / Codename**: 流光澈 · 万象生篇 (Crystal Clarity · Infinite Worlds)  
> **发布日期 / Release Date**: 2026-10-13  
> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1  
> **发布类型 / Release Type**: 1,768 词条全量零死角双语系统 & 深度子页面/弹窗绝对纯净

---

### 🌟 版本概述 (Overview)
V9.1.1 彻底消除了顶栏快捷栏、各大功能弹窗、底层配置表单以及移动端抽屉栏中残留的中文，将国际化字典从 984 条扩充并全量编译至 **1,768 条**，真正做到全站 100% 纯英文与 100% 纯中文的双向可逆无死角切换；同时版本单一真源全域升级为 **9.1.1**。

---

### 🆕 新增功能 (New Features)
1. **1,768 个 UI 词条全域零残留 (Zero Residue Bilingual Coverage)**:
   - 全面收录包括 6 维画像弹窗、API Vault 密码箱、商业化算力中枢、水印设置、任务抽屉、IP 资产库等全部功能弹窗中的 784 个专业词条；
   - 英文模式下经 BeautifulSoup 与 DOM 递归检验，全站残留中文数量降为 **0**。
2. **双向可逆恢复与长短语逆向字典 (Reversible Engine)**:
   - 升级 `_orig_zh` 智能缓存，杜绝英文覆盖中文原始值；
   - 增加 `REVERSE_PHRASE_LIST`，支持英文短语一键安全恢复为原汁原味纯中文。
3. **顶栏快捷按键与标题即时联动**:
   - 修复了 `top_profile_6d` 与 `top_my_api` 的 `data-i18n` 映射，更新 `<title>` 页面标题与导航栏标题的即时国际化响应。

---

### 🛠️ 功能优化与更新 (Updates & Enhancements)
- **版本号统一步进至 9.1.1**:
  - `version.py` 单一真源升级为 `9.1.1`；
  - `web/admin.py`, `gateway_ui.py`, `index.html`, `mobile.html`, `README.md`, `LICENSE` 等全域对齐为 `9.1.1`。

---

### 🐛 修复说明 (Bug Fixes)
- 🐛 修复切换英文模式后，顶栏画像按钮、系统主题切换指示器、弹窗标题和表单占位符仍有部分中文残留的缺陷；
- 🐛 修复切回中文模式时部分动态长短语未能完全复原的问题；
- 🐛 修复 MutationObserver 在异步事件处理中的递归触发隐患。

---

### 📦 获取与使用 (How to Access)
```bash
# 获取最新 9.1.1 代码
git checkout v9.1.1
# 或者拉取最新 main 分支
git pull origin main
```

---

> **版权声明**: Copyright © 2026 [yimu.hyipf.com](https://yimu.hyipf.com). All rights reserved.
""",
        "is_latest": False
    },
    {
        "tag": "v9.2.0",
        "name": "v9.2.0 - 天工开 · Divine Forge (Custom Content Platforms & Agent Layout Skills)",
        "body": """# 🎬 一幕 · 爆款工坊 (YIMU Studio) V9.2.0

> **版本代号 / Codename**: 天工开 · Divine Forge  
> **发布日期 / Release Date**: 2026-10-13  
> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1  
> **发布类型 / Release Type**: 自定义内容派生平台与排版技能大版本升级

---

### 🌟 版本概述 (Overview)
V9.2.0 正式上线全网任意内容分发平台的自定义添加与智能识别体系，支持一键自学习任意文章网址的排版风格并自蒸馏生成专属 Agent 技能模块；同时锁死全域中文品牌名「一幕·YIMU」，移除版本展示页的商业化冗余。

---

### 🆕 新增功能 (New Features)
1. **自定义内容分发派生平台中枢 (Custom Platforms Hub)**:
   - 支持在个人中心任意添加垂直平台或新兴自媒体平台网址；
   - 智能识别目标平台名称、域名、Favicon 与发布适配接口。
2. **今日头条高密度资讯流排版规范 (Toutiao Feed Standard)**:
   - 自定义平台默认统一采用今日头条成熟排版范式：醒目标题、精练段落、金句卡片与重点高亮。
3. **Agent 专属排版技能自学习与蒸馏 (Layout Skill Distillation)**:
   - 支持粘贴任意范文网址，Agent 深度解析其排版节奏、色彩与构图规范，自动生成可复用技能。
4. **品牌翻译锁死与页面纯净化**:
   - 彻底解决反向翻译导致的「一幕·一幕」错漏，统一呈现「一幕·YIMU」；
   - 移除 Releases 页面顶部的价格冗余菜单。

---

> **版权声明**: Copyright © 2026 [yimu.hyipf.com](https://yimu.hyipf.com). All rights reserved.
""",
        "is_latest": False
    },
    {
        "tag": "v9.3.0",
        "name": "v9.3.0 - 万象融 · Cross-Platform Unified (Native Linux & Automated Releases)",
        "body": """# 🎬 一幕 · 爆款工坊 (YIMU Studio) V9.3.0

> **版本代号 / Codename**: 万象融 · Cross-Platform Unified  
> **发布日期 / Release Date**: 2026-10-13  
> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1  
> **发布类型 / Release Type**: Linux 原生生产支持、全端脚本无版本化与自动发布核心里程碑

---

### 🌟 版本概述 (Overview)
V9.3.0 带来全面的跨平台生产级就绪能力，原生支持 Linux 服务器与云原生环境，全端一键启动与升级脚本彻底脱离历史版本号羁绊；同时引入全自动化 GitHub Releases 流水线，保证每一次代码推送第一时间同步最新 Release 列表。

---

### 🆕 新增功能 (New Features)
1. **Linux 原生生产级运行套件 (Native Linux Engine)**:
   - 新增 `一键启动_linux.sh`：自动检测 Python 3.10+、自动创建 `.venv` 虚拟环境、一键后台多进程守护运行、端口占用自愈、公网/局域网访问 IP 智能探测与系统健康检查；
   - 新增 `一键升级_linux.sh`：自动从官方 GitHub 拉取最新代码、同步依赖、安全备份数据库并对齐架构、无缝热重启。
2. **启动与升级脚本全域无版本化规范 (Clean Unified Launchers)**:
   - 彻底废弃所有历史版本号后缀脚本（如 `*V8.bat`、`*V8.command`）；
   - Windows 规范为：`一键启动.bat` / `一键升级.bat`；
   - macOS 规范为：`一键启动.command` / `一键升级.command`；
   - Linux 规范为：`一键启动_linux.sh` / `一键升级_linux.sh`；
   - Unix 跨平台通用：`一键启动.sh` / `一键升级.sh`。
3. **GitHub Releases 自动化工作流 (Automated GitHub Releases)**:
   - 配置 GitHub Actions 自动发布工作流，代码提交或推送第一时间无缝更新至 GitHub Releases 列表页；
   - 同步更新官方 Releases API，确保永远指向最新版本。
4. **历史代码旧版本残留全域统一**:
   - 彻底清理全工程中遗留的过时版本字眼、测试桩与临时产物，单一真源统一步进至 **9.3.0**。

---

### 📦 获取与使用 (How to Access)
```bash
# 获取最新 9.3.0 代码
git checkout v9.3.0
# 或者拉取最新 main 分支
git pull origin main
```

---

> **版权声明**: Copyright © 2026 [yimu.hyipf.com](https://yimu.hyipf.com). All rights reserved.
""",
        "is_latest": False
    },
    {
        "tag": "v9.3.1",
        "name": "v9.3.1 - 万象融 · Server One-Click Deploy (Production Stack & Auto Releases)",
        "body": """# 🎬 一幕 · 爆款工坊 (YIMU Studio) V9.3.1

> **版本代号 / Codename**: 万象融 · Cross-Platform Unified  
> **发布日期 / Release Date**: 2026-10-14  
> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1  
> **发布类型 / Release Type**: 服务器生产级一键部署、Systemd 守护进程与全自动化发布核心里程碑

---

### 🌟 版本概述 (Overview)
V9.3.1 推出生产级服务器一键部署套件，支持裸服务器单行命令直接执行（`curl | bash`），全自动完成操作系统依赖自愈、隔离虚拟环境搭建、高强度随机密钥初始化、数据库无损迁移与 Systemd 开机自启常驻守护；同时加固系统在线更新中枢，确保 Releases 列表第一时间无缝检测与同步最新稳定版。

---

### 🆕 新增功能 (New Features)
1. **服务器生产级一键部署套件 (Server Auto-Deployer)**:
   - 新增 `服务器一键部署.sh`（软链 `一键部署.sh`、`deploy.sh`）；
   - 支持单行 curl 命令极速自动化部署：`curl -fsSL https://raw.githubusercontent.com/yimuhub/yimu-baokuanstudio/main/服务器一键部署.sh | bash`；
   - 跨发行版包管理器智能适配（Ubuntu/Debian `apt`、CentOS/Rocky/RHEL `dnf`/`yum`、Arch `pacman`、Alpine `apk`）；
   - 自动检测并安装 Python 3.10+、Git、Curl、FFmpeg 与 SQLite 底层依赖；
   - 自动生成高强度安全凭证与随机管理员口令；
   - 自动无损初始化迁移数据库结构；
   - 自动创建并启用 Systemd 开机自启服务 (`yimu.service`)，提供高可靠进程守护与自动重启。
2. **在线更新中枢语义版本防回退加固**:
   - 升级 `core/updater.py` 语义化版本算法，杜绝因旧 Release 元数据导致的版本误降级；
   - 确保系统点击检查更新时精准拉取最新 `9.3.1` 稳定版。
3. **版本单一真源全域统一至 V9.3.1**:
   - 全栈模块、接口契约、多语言字典与前后端页面版本统一步进为 **9.3.1**。

---

### 📦 获取与使用 (How to Access)
```bash
# 全新服务器单行极速全自动部署：
curl -fsSL https://raw.githubusercontent.com/yimuhub/yimu-baokuanstudio/main/服务器一键部署.sh | bash

# 本地仓库一键更新：
git pull origin main
git checkout v9.3.1
```

---

> **版权声明**: Copyright © 2026 [yimu.hyipf.com](https://yimu.hyipf.com). All rights reserved.
""",
        "is_latest": False
    },
    {
        "tag": "v9.3.2",
        "name": "v9.3.2 - 扶风翼 · Gale Wings (Free First, Pay Later)",
        "body": "# 🎬 一幕 · 爆款工坊 (YIMU Studio) V9.3.2\n\n- 官方通道每日免费体验额度（3次/日）\n- 首次登录 3 步引导 Wizard\n- 双层数据访问合并（SQLAlchemy 真源）\n",
        "is_latest": False
    },
    {
        "tag": "v9.4.1",
        "name": "v9.4.1 - 浮光录 · Luminous Chronicles (Full-Stack Security, BYOK & 6D Persona Unification)",
        "body": "# 🎬 一幕 · 爆款工坊 (YIMU Studio) V9.4.1 [最新旗舰版 / Latest]\n\n> **版本代号 / Codename**: 浮光录 · Luminous Chronicles\n> **发布日期 / Release Date**: 2026-10-14\n> **版权主体 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1\n\n### 🌟 核心升级与修复亮点\n1. **全链路安全加固**：反代 `X-Forwarded-For`/`X-Real-IP` 识别防免密超管穿透、跨站 Drive-by CSRF 拦截、按需 HTTPS CSP、API Key Vault 随机 Nonce+HMAC 认证加密 (`v2$`)；\n2. **BYOK 与免费体验主链贯通**：`core/agents.py` 与 `core/llm.py` 自动从上下文提取 `user_id`，自备 Key 模式自动免除 `require_credits` 平台算力扣除，统一 V6/V7 双会话 Cookie (`mf_v6_token` + `yimu_session`)；\n3. **6 维人设自动注入与小红书指令精修**：写作/导演/广告 Agent 自动挂载当前工作区 6 维数字画像与声纹记忆，修复小红书单平台改写指令透传；\n4. **数据库 10 倍提速与无冲突热更新**：`core/db.py` 连接初始化缓存化，在线升级自动保护本地 `config.yaml`，补齐注册与首稿增长漏斗埋点，支持每日工单跨整点 15 分钟窗口与状态持久化。\n",
        "is_latest": True
    }
]

if __name__ == '__main__':
    token = get_token()
    print("Fetched GitHub Token successfully.")
    for rel in RELEASES_DATA:
        create_or_update_release(
            token=token,
            tag=rel["tag"],
            name=rel["name"],
            body=rel["body"],
            is_latest=rel.get("is_latest", False)
        )
    print("All GitHub Releases created / updated successfully!")
