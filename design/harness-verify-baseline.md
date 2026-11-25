# Harness 外壳重建 · 第一阶段基线验收报告

- 验收时间：2026-11-24 12:50–12:56（CST, UTC+8）
- 验收方：独立只读验收 Agent（未改任何业务代码；未 commit；未改版本号；未重启服务）
- 被测应用：`http://127.0.0.1:8790/`（运行中）
- 唯一视觉基准：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-workspace-preview.html`（3245 行，与契约记录一致）
- 契约：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shell-contract.md`
- 验收脚本：`/Users/czmj/Documents/yimu-baokuanstudio/scripts/harness_ui_verify.py`（一键复跑：`python3 scripts/harness_ui_verify.py`）
- 机器检查 JSON：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-verify-results/verify-20261124-125558.json`

> 结论先行：**重建刚开始，Harness 外壳主体尚未落地。** 6 个 JS 模块与 4 个业务 CSS 模块均为 125B/127B 空桩；仅 `harness-ui.css`（45,236B）底座已写入。宽屏下 `body[data-shell="harness"]` 引导与三栏 grid 占位生效，但 `window.HX` 未定义、9 个契约挂载点全部不存在；任务/内容/采集/设置四工作区的中右栏实现均未开始。classic 与 v2 基线外观正常，未被破坏。

---

## 1. 环境与视口口径（如实记录）

| 项 | 实测值 | 说明 |
|---|---|---|
| 自然浏览器视口 | **974 × 761** CSS px，DPR 2 | 任务预估约 1231×761，以本轮实测为准；窗口物理截图表面 974×761 |
| 契约基准视口 | 1440 × 900 | 宽屏验收口径 |
| 宽屏等效方式 | CDP `Emulation.setDeviceMetricsOverride` 模拟 1440×900（deviceScaleFactor=1） | 布局读数（getBoundingClientRect）为 1440×900 下的 CSS 像素；截图表面仍是 974×761 窗口，按比例等效，第二阶段复验需同样先模拟宽屏再读数 |
| 窄屏回落阈值 | `window.innerWidth >= 1024`（模板引导脚本） | 974 < 1024，`?ui=harness` 强制参数也会回落 classic（契约 §7.6 允许），已单独截图记录 |
| 静态缓存 | URL 带 `?cb=<时间戳>` + 验前 `Network.clearBrowserCache` | 模板每次请求读盘，复验必须继续带 cb 或清缓存 |

---

## 2. 机器检查结果（脚本可复跑）

### 2.1 静态资源 HTTP 200 —— 11/11 PASS

| 状态 | 字节 | 路径 |
|---|---|---|
| 200 | 45,236 | `/static/css/harness-ui.css` |
| 200 | 127（桩） | `/static/css/harness-thread.css` |
| 200 | 127（桩） | `/static/css/harness-stage.css` |
| 200 | 127（桩） | `/static/css/harness-collect.css` |
| 200 | 127（桩） | `/static/css/harness-settings.css` |
| 200 | 125（桩） | `/static/js/harness-core.js` |
| 200 | 125（桩） | `/static/js/harness-rail.js` |
| 200 | 125（桩） | `/static/js/harness-thread.js` |
| 200 | 125（桩） | `/static/js/harness-stage.js` |
| 200 | 125（桩） | `/static/js/harness-collect.js` |
| 200 | 125（桩） | `/static/js/harness-settings.js` |

### 2.2 `node --check` —— 6/6 PASS

6 个 harness JS 模块语法检查全部 rc=0（当前为空 IIFE 桩，无语法风险；落地后必须保持通过）。node v22.23.2。

### 2.3 违规模式扫描 —— 0 FAIL / 0 WARN

扫描范围：上述 11 个契约文件。

- 写死 `http://` 外链/假数据：**0 处**
- 写死“已完成 n/n”演示进度：**0 处**；裸“已完成”文案：**0 处**
- 裸 `<iframe>`：**0 处**（应用整体既有 1 个空 `src` iframe，属业务遗留，见 §4.7）
- `eval(` / `new Function(` / 字符串定时器：**0 处**

### 2.4 隔离规则抽查（契约 §6）—— 56 FAIL / 6 WARN

**FAIL（56 条，全部位于 `harness-ui.css`）**：选择器未收在 `body[data-shell="harness"]` 作用域下，裸选择器直接挂 `#hxTopbar` / `.hx-tb-*` / `.hx-newtask` / `.hx-recent-*` / `.hx-ctx-*` 等。

- 样本：`#hxTopbar`、`.hx-tb-brand`、`.hx-tb-nav button`、`.hx-newtask:hover`、`.hx-recent-row.on .hx-dot`、`.hx-ctx-action span` …… 完整 56 条见 JSON `checks.isolation.findings`。
- 风险评估：这些类名/ID 均为 `hx-`/`#hx` 专属命名，实际串扰 classic/v2 的概率低；但**违反契约 §6 字面要求**（“所有 CSS 选择器必须以 `body[data-shell="harness"]` 开头”“严禁写裸选择器”）。是否回派 A 外壳底座补齐作用域前缀，由主协调者裁决。
- 另：右栏宽度变量 `--hx-panelw` 默认 **400px**（`clamp(340px, var(--panelw, 400px), 480px)`），契约 §7.1 要求 **404px**，存在 4px 偏差，第二阶段实测复核。

**WARN（6 条）**：6 个 JS 桩模块均未发现 `getAttribute('data-shell') !== 'harness'` 早退守卫。当前为空桩零副作用，可忽略；**落地时必须按 §6 补齐守卫**，否则属于违规。

### 2.5 模板挂载引用 —— PASS

- 5 个 CSS、6 个 JS 在 `web/templates/index.html` 中引用齐全；JS 加载顺序 core → rail → thread → stage → collect → settings 与契约 §2 一致。
- **INFO**：`web/static/js/harness-shell.js`（36,646B，早期单体 Harness 实现）存在于磁盘但**模板未挂载**，不在契约 §2 所有权表内。建议主协调者确认归档/删除，避免与新四模块方案混淆。

### 2.6 相关 pytest 子集 —— PASS（rc=0，非全量）

先 `pytest --collect-only -q` 按文件名关键词 `shell|harness|workbench|rail|stage` 筛出 3 个文件，共 51 用例全部通过：

- `tests/test_v1100_workbench_shell.py`（14）
- `tests/test_v1102_rail_prototype_parity.py`（14）
- `tests/test_v1200_stage_layout.py`（23）

未全量跑其它用例。

### 2.7 真实接口探针

| 接口 | 状态 | 实测数据 |
|---|---|---|
| `/api/status` | 200（379,054B） | drafts **57**、topics **200**、jobs 0；capabilities：text / image / video；文本模型 `deepseek-v4.1-flash-free` |
| `/api/tasks` | 200 | tasks **0**（当前无执行中任务） |

页面真实草稿卡片 DOM 计数 `#draft-list-container .draft-card` = **57**，与 `/api/status` drafts 数一致，当前线上数据为真实数据，无演示数据迹象。

---

## 3. 三端浏览器实测基线

### 3.1 `?ui=harness`（宽屏模拟 1440×900）—— 外壳未成型

截图：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/harness-wide-20261124-125428.png`

| 探针项 | 实测 | 契约要求 | 判定 |
|---|---|---|---|
| `body[data-shell]` | `harness` | harness | ✅ 引导生效 |
| `html[data-ui-shell]` | `harness` | harness | ✅ |
| `window.HX` | `undefined` | core 提供 `HX` 命名空间 | ❌ 未实现 |
| 挂载点 `#hxTopbar / #hxRail / #hxRailCtx / #hxThread / #hxThreadHead / #hxThreadBody / #hxStage / #hxStageTabs / #hxStageBody` | 全部 `null` | core 创建、各模块写入 | ❌ 全部缺失 |
| 左栏 `aside.side` | x=0, y=46, **w=248**, h=854 | 248px | ◑ 宽度由底座 CSS 占位，内部仍是旧导航，无 brand/搜索/context/额度/账号 |
| 中栏 `.main-wrapper` | x=248, y=46, w=792, h=854 | 弹性中栏 | ◑ 旧业务面板未按原型重排；旧 `<header>` 仍留在中栏顶部（契约 §1 要求隐藏） |
| 右栏 `aside.assets#assetsPanel` | x=1040, y=46, **w=400**, h=854 | 404px | ◑ 面板在，宽 400（差 4px）；无 stage-head / 三页签 / pane 重排 |
| 顶栏行 | y=46 起，高 46px 占位 | 46px 深色顶栏跨三列 | ❌ 无 `#hxTopbar` 节点，无深色顶栏内容 |
| 草稿卡片 | 57 | 真实 DOM | ✅ 真实数据保留 |
| iframe | 1（空 src，业务遗留） | 业务页禁 iframe 承载 | 待第二阶段核浏览器页签降级 |
| console error | 0 | 模块异常不得阻断业务 | ✅ 当前无报错（桩未执行逻辑） |

目视基线：左栏旧导航（操盘大屏/极简模式/灵感与选题/内容工作台/影音工坊/系统设置/个人中心）原样保留；中栏为旧 Copilot 对话页；右栏旧资产台残留；无原型中的顶栏工作区切换、rail context、stage 三页签。

### 3.2 `?ui=harness`（自然窄屏 974×761）—— 回落 classic，符合 §7.6

截图：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/harness-20261124-125405.png`

- `body[data-shell]` = `classic`（974 < 1024 阈值回落）；side 230×761、main 744×761、assets 隐藏（w=0）；57 草稿卡片；0 console error。
- 判定：窄屏回落链路正常，未白屏、未报错。

### 3.3 `?ui=v2`（V11 三栏，宽屏 1440×900）—— 基线正常，未被破坏

截图：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/v2-20261124-125456.png`

| 探针项 | 实测 |
|---|---|
| `body[data-shell]` | `v2` |
| side / main / assets | 248×900 @(0,0) / 792×900 @(248,0) / 400×900 @(1040,0) |
| `window.HX` / `[id^=hx]` | `undefined` / 0 个（harness 未污染 v2） |
| 草稿卡片 / iframe / console error | 57 / 1 / 0 |

目视：V11 左栏「新建创作 + 导航 + 最近产出」列表完整，中栏对话、右栏资产台在位。

### 3.4 `?legacy=1`（经典版，宽屏 1440×900）—— 基线正常，未被破坏

截图：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/legacy-20261124-125510.png`

| 探针项 | 实测 |
|---|---|
| `body[data-shell]` | `classic` |
| side / main / assets | 230×900 @(0,0) / 1210×900 @(230,0) / 隐藏（w=0） |
| `window.HX` / `[id^=hx]` | `undefined` / 0 个 |
| 草稿卡片 / iframe / console error | 57 / 1 / 0 |

---

## 4. 失败项与偏差清单（回派主协调者，验收方不改代码）

| # | 级别 | 问题 | 位置 / 证据 | 对应契约 |
|---|---|---|---|---|
| 1 | ❌ 阻断 | 6 个 JS 模块为空 IIFE 桩：`HX` 命名空间/状态/路由/注册表/boot/持久化/键盘、rail 渲染、thread 四工作区、stage host 三 pane、collect、settings 均未实现 | `web/static/js/harness-{core,rail,thread,stage,collect,settings}.js`（各 125B）；探针 `HX=undefined`、9 挂载点全 null | §2/§3/§4 |
| 2 | ❌ 阻断 | 4 个业务 CSS 为空桩：thread/stage/collect/settings 中右栏样式未落地 | `web/static/css/harness-{thread,stage,collect,settings}.css`（各 127B） | §2 |
| 3 | ◑ 偏差 | `harness-ui.css` 56 条裸选择器未加 `body[data-shell="harness"]` 前缀 | JSON `checks.isolation.findings` | §6 |
| 4 | ◑ 偏差 | 右栏宽默认 400px，契约 404px；需落地后以 getBoundingClientRect 实测复核 | `harness-ui.css` `--hx-panelw` | §7.1 |
| 5 | ⚠️ 待办 | 6 个 JS 桩落地时必须补 `data-shell !== 'harness'` 早退守卫；当前缺失仅记 WARN | 脚本隔离抽查 | §6 |
| 6 | ℹ️ 清理建议 | 孤儿文件 `web/static/js/harness-shell.js`（36,646B 早期单体实现）磁盘存在、模板未挂载，建议确认归档或删除 | 模板引用扫描 | §2 |
| 7 | ℹ️ 观察项 | 应用既有 1 个空 `src` iframe（classic/v2/harness 下均在），非 harness 新增；第二阶段核验右栏“浏览器”页签内嵌阅读与「外部打开」降级时一并确认 | 探针 `iframe=1` | §7.5 |
| 8 | ❌ 待实现 | harness 下旧 `<header>` 尚未隐藏；中栏业务面板未按原型重排 | §3.1 截图 | §1 |

---

## 5. 第二阶段复验清单（按契约 7 条标准逐条）

> 复验前提：四模块落地后，先清缓存/带 `?cb=<ts>`，CDP 模拟 1440×900 宽屏；所有尺寸以 `getBoundingClientRect` 实测为准，视觉与 `harness-workspace-preview.html` 对照；真实数据以 `/api/status`、`/api/tasks` 为准，写死演示数据一律判不通过。

1. **布局硬原则**：实测顶栏高 **46px** 且深色 `#1d2026` 系、左栏 **248px**、中栏 `minmax(0,1fr)`、右栏 **404px**；`body` 自身为三列 + 顶栏 grid；无嵌套四栏（检查无第二套三栏容器）。当前基线：顶栏节点缺失、右栏 400、中栏未重排。
2. **任务页（tasks → `switchToPage('lite')`）**：面包屑/标题/状态/操作、模型·引用·平台元信息齐全；对话消息来自真实草稿/历史；进度/计划由 `/api/tasks`、草稿历史、生成状态推导（不得写死“已完成 5/5”）；输入区在位；右栏真实成稿/图片/视频/数据。
3. **内容页（content → `'drafts'`）**：草稿箱在左栏（`#draft-list-container .draft-card` 真实 DOM），中栏真实编辑器，右栏预览；选中草稿三栏联动；保存/发布链路不丢。
4. **采集页（collect → `'inspire'`）/ 设置页（settings → `'console'`）**：按原型重排；原型有而系统没有的项标「未接入」，不得伪造开关/假数据。
5. **右栏舞台**：资产/浏览器/预览三页签齐全；资产接 `/api/assets/library` 等真实数据；预览用真实排版渲染；浏览器页签先内嵌阅读，禁 iframe 时提供「外部打开」。
6. **回归保护**：`?ui=v2`、`?legacy=1` 行为与本轮基线一致（v2 248/792/400、classic 230/1210/资产隐藏）；宽屏默认 harness、窄屏（<1024）回落 classic；harness 作用域样式不得串扰另两套。
7. **逐页 + 门禁**：一级页与二级入口逐个点开截图——inspire 6 个、studio 6 个、console 8 个，外加 dashboard / pricing / profile “更多”直达入口保留；`node --check` 全过；相关 pytest 子集通过；输出 `design/harness-verify-final.md`，每条标准记通过/不通过 + 截图绝对路径。

### 第二阶段待补测量项（本轮未做）

- 四工作区 × 一级/二级入口逐页点开截图与尺寸实测。
- 顶栏/左栏/右栏内部元素的实测宽度、颜色 token 与原型逐一比对。
- 右栏三页签切换、草稿选中联动、新建任务/真实新建链路点击验证。
- 窄屏回落与 classic/v2 回归目视复核。

---

## 6. 本轮交付物清单

| 文件 | 说明 |
|---|---|
| `/Users/czmj/Documents/yimu-baokuanstudio/scripts/harness_ui_verify.py` | 可复现验收脚本（静态 200 / node --check / 违规扫描 / 隔离抽查 / 模板引用 / pytest 子集 / API 探针） |
| `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-verify-results/verify-20261124-125558.json` | 本轮机器检查结构化结果 |
| `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/harness-wide-20261124-125428.png` | Harness 宽屏基线（1440×900 模拟） |
| `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/harness-20261124-125405.png` | Harness 窄屏回落 classic 基线（974×761 自然视口） |
| `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/v2-20261124-125456.png` | V11（v2）基线 |
| `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/legacy-20261124-125510.png` | 经典版（classic）基线 |

**只读声明**：本轮未修改 `web/static/**`、`web/templates/**`，未 git commit，未改版本号，未重启服务；`web/` 下既有改动为其他 Agent/主协调者先前留下，不在本次验收范围内。
