# Harness 外壳 · 双主题与品牌 Logo 契约（第二轮）

> 主协调者冻结。所有 Agent 必须遵守；契约变更只能由主协调者修改。
> 前置：第一轮原型重建已完成并通过验收。本轮**只修**，不重建、不回退紧凑版、不动 Classic/V11。

## 一、主题机制（沿用站点既有，不新造）

- 偏好存储键：`localStorage['yimu_ui_theme_mode']`，取值 `light | dark | system`（既有，别改键名、别新增键）。
- 生效属性：`<html data-theme="light|dark" data-theme-mode="light|dark|system">`（既有引导脚本已处理 system，并监听 `prefers-color-scheme` 变化）。
- 执行 API（模板内联，全局可用，禁止另写一套）：
  - `setThemeMode(mode)` / `setThemeModeDirect(mode)` / `cycleThemeMode()`
  - 既有控件：`#th-ui-mode` 下拉、设置页「🌓 系统 / ☀️ 浅色 / 🌙 深色」按钮。
- Harness 侧要求：
  - **不再强制 `data-theme`**（模板里两处强制 light 已由主协调者删除）。
  - Harness 顶栏提供“外观”入口：点击循环 `light → dark → system`，实现上调用既有 `cycleThemeMode()`（若它只切三态则直接用），并实时回显当前模式（☀️/🌙/🌓）。
  - 主题切换必须**即时生效**（不需要刷新）；刷新后由既有引导脚本恢复。
  - Classic / V11 的主题规则零影响：所有 harness 主题样式必须限定在 `body[data-shell="harness"]`。

## 二、语义 token 契约（唯一取色来源）

定义位置：`web/static/css/harness-ui.css` 的 `body[data-shell="harness"]` 块（浅色为默认），深色用 `html[data-theme="dark"] body[data-shell="harness"]` 覆盖。

| token | light | dark | 用途 |
|---|---|---|---|
| `--hx-accent` | `#ef6432` | `#f4744a` | 主行动色 |
| `--hx-accent-deep` | `#d84a1b` | `#d0451c` | 按压/渐变深端 |
| `--hx-accent-2` | `#ff9258` | `#ff9d68` | 渐变亮端 |
| `--hx-accent-soft` | `#fff1ea` | `#2b1a13` | 选中底/柔和强调 |
| `--hx-accent-line` | `#ffd8c7` | `#4a2b20` | 强调描边 |
| `--hx-on-accent` | `#ffffff` | `#ffffff` | 强调填充上的文字/图标 |
| `--hx-ink` | `#20242b` | `#e9ecf2` | 主文字 |
| `--hx-ink-2` | `#575e6b` | `#b7bfcb` | 次文字 |
| `--hx-ink-3` | `#8c939f` | `#8b93a1` | 辅助文字 |
| `--hx-ink-4` | `#b2b7c0` | `#666e7c` | 弱化/占位 |
| `--hx-line` | `#e7e9ee` | `#2b303a` | 常规分隔线 |
| `--hx-line-strong` | `#d9dde5` | `#3a4150` | 控件描边 |
| `--hx-bg` | `#edeff3` | `#101216` | 外壳底色 |
| `--hx-panel` | `#ffffff` | `#1a1d23` | 卡片/面板 |
| `--hx-panel-2` | `#fafbfc` | `#20242b` | 次级面板 |
| `--hx-panel-3` | `#f4f6f8` | `#262b33` | 三级/表头/胶囊底 |
| `--hx-rail` | `#fbfbfc` | `#171a20` | 左栏底 |
| `--hx-stage` | `#f7f8fa` | `#14171c` | 右栏舞台底 |
| `--hx-hover` | `#f3f5f8` | `#262b34` | hover 底 |
| `--hx-hover-2` | `#eef1f5` | `#2d333d` | 强 hover / 选中底 |
| `--hx-input` | `#ffffff` | `#1f232a` | 输入框底 |
| `--hx-input-line` | `#e8ebf0` | `#343a46` | 输入框描边 |
| `--hx-topbar` | `#1d2026` | `#0e1013` | 顶栏底 |
| `--hx-topbar-ink` | `#ffffff` | `#ffffff` | 顶栏主文字 |
| `--hx-topbar-ink-2` | `#b9bfc9` | `#9aa2ae` | 顶栏次文字/边框内描边 |
| `--hx-overlay` | `rgba(12,14,18,.52)` | `rgba(0,0,0,.66)` | 弹层遮罩 |
| `--hx-scroll` | `#d9dde5` | `#3a4150` | 滚动条 |
| `--hx-green` / `-soft` | `#268468` / `#eaf6f1` | `#4fbb93` / `#122a22` | 成功态 |
| `--hx-amber` / `-soft` | `#b97716` / `#fff5e6` | `#dfa14e` / `#2a2113` | 提醒态 |
| `--hx-blue` / `-soft` | `#3768cf` / `#edf2fd` | `#7aa2f0` / `#16203a` | 信息态 |
| `--hx-shadow-sm` | `0 1px 2px rgba(20,24,32,.035)` | `0 1px 2px rgba(0,0,0,.42)` | 轻阴影 |
| `--hx-shadow-md` | `0 16px 44px rgba(24,28,38,.12)` | `0 18px 48px rgba(0,0,0,.55)` | 中阴影 |
| `--hx-shadow-lg` | `0 30px 80px rgba(16,20,28,.2)` | `0 32px 88px rgba(0,0,0,.62)` | 弹层阴影 |

### 替换规则（五个 CSS 文件都要做）

1. 颜色只能来自上表 token；新增颜色需求先问主协调者，不要自造第十个近似灰。
2. 常见字面量映射：`#fff/#ffffff` → 面板底用 `--hx-panel`、强调/顶栏上的文字用 `--hx-on-accent` / `--hx-topbar-ink`；`#edeff3`→`--hx-bg`；`#fbfbfc`→`--hx-rail`；`#f7f8fa`→`--hx-stage`；`#fafbfc`→`--hx-panel-2`；`#f4f6f8/#f3f5f8`→`--hx-panel-3`/`--hx-hover`；`#20242b`→`--hx-ink`；`#575e6b`→`--hx-ink-2`；`#8c939f`→`--hx-ink-3`；`#e7e9ee`→`--hx-line`；`#d9dde5`→`--hx-line-strong`；`#fff1ea`→`--hx-accent-soft`。
3. `rgba(255,255,255,.x)` 这类白色蒙层在深色下必须换成 `rgba(255,255,255,.06→.1)` 或对应 token 的透明变体，不能保留浅色浓度。
4. 深色下**禁止只改背景**：文字/描边/输入框/滚动条/阴影/badge 必须同步换 token，保证对比度（正文 ≥ 7:1 目标，辅助文字 ≥ 4.5:1）。
5. 允许保留字面量的唯一例外：token 定义块本身；品牌橙的 `linear-gradient(var(--hx-accent-2), var(--hx-accent-deep))` 内部可引用 token。

## 三、品牌 Logo（用户自有资源，不得替代）

- 权威资源：`/static/img/logo-icon.png`（256×256 RGBA，当前站内 `apple-touch-icon` 在用）、`/static/img/logo.png`（512）、`/static/img/logo-master.png`（1024 透明母版）。
- 使用规范：
  - 顶栏：`<img class="hx-logo" src="/static/img/logo-icon.png" srcset="/static/img/logo-icon.png 1x, /static/img/logo.png 2x" alt="一幕·YIMU">`，高 22px，`border-radius:6px`，`object-fit:contain`，**不裁切、不滤镜、不反色**。
  - 左栏品牌区：32px（迷你态 28px 且必须可见、居中），形状同上；品牌名「一幕·YIMU」+ 徽标「爆款工作室」+ 副行「全媒体创作工作台」保持可读；版本号展示沿用既有 `#side-version-badge` 或等价真实版本。
  - 空态 / 关于 / 登录 / 引导等品牌位：logo-icon 64–96px；不得用默认头像、emoji、字母、原型光球。
  - 深色下 Logo 原样显示（图片自带配色），若周边对比不足，靠 token 调整容器底色而不是给 Logo 加滤镜。
- 必须清除的原型替代物：顶栏 `.hx-tb-mark`（CSS 光球）、左栏 `.hx-brand-mark` 内的内联 SVG 光球；以及任何 `background-image` 画的假标。
- 全局排查：favicon、`apple-touch-icon`、登录/关于弹窗、空态插画、账号头像（头像用用户真实头像 `default-avatar.png` 或首字，不得用 Logo 冒充）。

## 四、页面矩阵与视口

- 页面：`dashboard`、`lite`(任务)、`drafts`(内容)、`inspire`(+6 二级)、`console`(+8 二级)、`studio`(+7 二级)、`pricing`、`profile`。
- 视口：`1440×900`、`1231×761`、`1024×900`（临界）、`<1024`（回落 classic）。
- 每页每视口检查：顶栏 Logo 与工作区选中态、左栏上下文与计数、中栏标题/操作、右栏三页签、空态、弹窗、滚动与溢出、文本截断、按钮可点性、有无白块/被右栏遮挡/嵌套四栏。
- 数据一律真实接口；原型有而系统无的继续标「未接入」，**不得新增假开关**。

## 五、验收要求

- `node --check` 全部模块；`python3 scripts/harness_ui_verify.py` 扩展后 hard_fail=0；相关 pytest 子集通过。
- 双主题需分别截图：`light` 与 `dark` 各至少四工作区；`system` 模式在 `prefers-color-scheme` 切换后能跟随。
- 每个修复项必须给「改了什么文件 + 证据截图绝对路径 + 剩余问题」。
