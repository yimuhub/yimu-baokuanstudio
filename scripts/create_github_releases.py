#!/usr/bin/env python3
"""Create and sync GitHub Releases via GitHub REST API."""
import json
import subprocess
import urllib.request
import sys

def get_token():
    auth_out = subprocess.check_output(
        ['git', 'credential', 'fill'],
        input='url=https://github.com/yimuhub/yimu-baokuanstudio.git\n',
        text=True
    )
    for line in auth_out.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1]
    raise RuntimeError("No token found from git credential helper")

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
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
        print(f"[{method}] Release {tag}: {res.get('html_url')}")
        return res

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
""",
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
