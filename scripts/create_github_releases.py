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
        "body": """## 🌟 一幕 · 爆款工坊 (YIMU Studio) V8.3.2

> **代号 / Codename**: 智瞳境 · Visual Storyboard  
> **发布日期 / Release Date**: 2026-10-11  
> **版权与许可 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1

---

### 核心亮点 / Key Highlights
1. **分镜式图文编排 (Visual Storyboard Injection)**:
   - 草稿段落视觉映射与全自动段落插图注入机制；
   - 提取段落关键语义，生成多级镜头语言与视觉意象。

2. **多风格美学体系 (10 Visual Aesthetic Presets)**:
   - 涵盖纪录片写实、新海诚动漫、极简 3D、赛博朋克等 10 款画风预设；
   - 画面色调、质感与构图提示词模块化组装。

3. **双通道生图调度引擎 (Dual Pipeline Engine)**:
   - 支持本地/云端 API 自适应容灾切换；
   - 增强型图像生成异常拦截与提示词清洗。
""",
        "is_latest": False
    },
    {
        "tag": "v8.3.33",
        "name": "v8.3.33 - 灵犀汇 · Unified Identity & Profile Center",
        "body": """## 🌟 一幕 · 爆款工坊 (YIMU Studio) V8.3.33

> **代号 / Codename**: 灵犀汇 · Unified Identity  
> **发布日期 / Release Date**: 2026-10-12  
> **版权与许可 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1

---

### 核心亮点 / Key Highlights
1. **统一个人中心 (Personal Profile Center)**:
   - 统一聚合会员权益等级、算力消耗账本与多租户隔离上下文；
   - 从旧版设置弹窗中彻底解耦，提供专属现代化个人信息面板。

2. **端到端鉴权状态同步 (End-to-End Auth Sync)**:
   - 侧边栏常驻个人资料快捷抽屉与版本实时检测状态指示器；
   - 游客与已登录用户权限无缝切换与自动续期。

3. **算力账本事务强一致 (Ledger Consistency)**:
   - 基于 SQLite WAL 的原子化算力扣减与充值对账体系；
   - 精确记录每一笔生图与文本生成调用明细。
""",
        "is_latest": False
    },
    {
        "tag": "v9.0.0",
        "name": "v9.0.0 - 万象生 · Infinite Worlds (AI Storyboard & Global i18n Launch)",
        "body": """## 🌟 一幕 · 爆款工坊 (YIMU Studio) V9.0.0

> **代号 / Codename**: 万象生 · Infinite Worlds  
> **发布日期 / Release Date**: 2026-10-13  
> **版权与许可 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1

---

### 核心亮点 / Key Highlights
1. **AI 视觉分镜矩阵 (Visual Storyboard Matrix)**:
   - 连贯分镜脚本生成，一键将文案段落转换为电影级视觉镜头与插图提示词；
   - 深度内置十套国际化视觉美学体系预设。

2. **多语言国际化启航 (Global i18n Architecture)**:
   - 引入双语中英文切换架构，为海外开发者与创作者提供完整操作支持；
   - 仓库核心文档（README.md / README_ZH.md）双语精准对齐。

3. **Agnes & Gemini 图像双引擎**:
   - 增强型多模型生图调度，打通高清晰、高饱和写实画面输出管道；
   - 文生图与图生图工作流全面升级。
""",
        "is_latest": False
    },
    {
        "tag": "v9.1.0",
        "name": "v9.1.0 - 万象生 · Infinite Worlds (100% Bilingual & Unified Versioning)",
        "body": """## 🌟 一幕 · 爆款工坊 (YIMU Studio) V9.1.0

> **代号 / Codename**: 万象生 · Infinite Worlds  
> **发布日期 / Release Date**: 2026-10-13  
> **版权与许可 / Licensor**: [yimu.hyipf.com](https://yimu.hyipf.com) | BUSL-1.1

---

### 🚀 核心升级与重磅更新 / Major Upgrades

#### 🌐 1. 全站 100% 纯英文 / 100% 纯中文国际化（彻底告别半中半英）
- **深层递归 DOM 翻译引擎**: `web/static/js/i18n.js` 全新重构，支持递归遍历所有 TextNode、placeholder、title、aria-label 节点。
- **动态内容监听器 (MutationObserver)**: 实时捕获异步渲染与动态弹窗，彻底根除“半中半英”混杂状态。
- **双语绝对纯正**: 英文模式全站所有内容 100% 纯英文，中文模式全站所有内容 100% 纯中文，严禁任何混杂。

#### 🏷️ 2. 全栈代码版本号统一升级为 9.1.0（杜绝旧版遗留）
- **单一真源统一步进**: `version.py` 统一定义 `__version__ = "9.1.0"`, `__codename__ = "万象生"`。
- **全栈层级严格一致**: 涵盖 `web/templates/index.html`、`web/templates/mobile.html`、`web/admin.py`、`web/gateway_ui.py`、`studio/__init__.py`、`studio/db_models.py`、`studio/ledger.py`、`core/imagegen.py`，杜绝任何历史版本写死残留。
- **版权与法务归属**: `LICENSE` 正式统一 Licensor 为 `yimu.hyipf.com`，版本升级至 `V9.1.0`。

#### 🎨 3. Agnes 图像大模型深度优化与画面提质
- **画幅智能映射 (Aspect Ratio Adapter)**: 严格对齐 Agnes 图像模型 `1K / 2K / 3K / 4K` 与 `WIDTHxHEIGHT` 规则（如 16:9 映射为 `2048x1152`，9:16 映射为 `1152x2048`），彻底规避 400 校验报错。
- **自愈兜底机制**: 智能剔除不兼容的 `quality` 字段并回退安全画幅，确保出图成功率 100%。
- **色彩与画面质感调优**: 提示词深度优化为“高清晰、高饱和、通透艳丽、写实逼真”，彻底去除烟雾感与模糊朦胧滤镜。

#### 📜 4. GitHub Releases & 内置发布看板
- **版本路线看板**: 全新挂载 `/releases` 路由与 `/api/releases` 接口，提供 V9.1.0 vs V9.0.0 vs V8.3.33 完整演进图表。
- **GitHub 官方 Releases 列表同步展示**: 在 GitHub 仓库页面提供结构化发版演进记录。
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
