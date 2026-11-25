# Harness 外壳重建 · 第二阶段最终验收报告

- 验收时间：2026-11-24 13:40–13:56（CST, UTC+8）
- 验收方：独立只读验收 Agent。**未改任何 `web/static/**`、`web/templates/**`；未 commit；未改版本号；未重启服务。**
- 被测应用：`http://127.0.0.1:8790/`（运行中）；强制参数 `?ui=harness` / `?ui=v2` / `?legacy=1`
- 唯一视觉基准：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-workspace-preview.html`
- 验收契约：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shell-contract.md` §7
- 验收脚本：`/Users/czmj/Documents/yimu-baokuanstudio/scripts/harness_ui_verify.py`（一键复跑：仓库根 `python3 scripts/harness_ui_verify.py`）
- 机器检查 JSON：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-verify-results/verify-20261124-135424.json`

## 结论先行

| 契约 §7 标准 | 判定 | 一句话结论 |
|---|---|---|
| 1. 三栏尺寸 + 无嵌套四栏 | **PASS** | 顶栏 46 / 左栏 248（迷你 68）/ 中栏 788 弹性 / 右栏 404，scrollWidth=1440 无横向溢出，未见第二套三栏容器。 |
| 2. 任务页：真实对话 + 真实进度/计划 + 右栏成稿 | **FAIL** | 任务页骨架与模型元信息/composer 在位、`/api/tasks=0` 空态诚实无写死进度；但真实对话面板未落入中栏，右栏无真实成稿/图片/视频。 |
| 3. 内容页：草稿箱 + 真实编辑器 + 预览 + 三栏联动 | **FAIL** | 左栏 57 草稿、中栏真实编辑器、右栏真实预览均已出现；**镜像行点击三栏联动断裂**（业务卡片切换但 `HX.state.draftId` 不跟随，中/右栏不切换）。 |
| 4. 采集/设置按原型重排，缺项标「未接入」 | **FAIL** | rail context 与「采集分析/配置检查」页签为真实数据、缺项诚实标注；但 `#p-inspire`/`#p-console` 从中栏脱离文档树，中栏只剩兜底空态。 |
| 5. 右栏 资产/浏览器/预览 三页签 | **PARTIAL（资产 FAIL）** | 预览真实排版渲染、浏览器诚实空态且 iframe 带降级；**资产 pane 为空**——`#assetsTabs`/`#assetsBody` 脱离文档（API 侧有 141 条真实资产）。 |
| 6. classic / v2 行为不变；窄屏回落 classic | **PASS** | legacy、v2 均无 harness 节点、8 面板齐全、57 草稿、0 新增报错；900px 窄屏回落 classic。 |
| 7. 逐页核验 + `node --check` + 相关 pytest | **PARTIAL** | 门禁全绿（静态 11/11、node 6/6、pytest 3 文件 51 例 rc=0）；但二级入口被面板脱落阻断，**未完成 inspire 6 / console 8 / studio 7 的逐页点开截图**。 |

**总体：不通过（阻断项 I-1/I-2/I-3）。** 外壳底座布局与旧版回归达标，四个工作区的真实业务面板落位与联动存在三处阻断缺陷，详见 §5。

---

## 1. 环境与视口口径（如实记录）

| 项 | 实测值 | 说明 |
|---|---|---|
| 契约基准视口 | 1440 × 900 | §7 宽屏验收口径 |
| 验收采用方式 | CDP `Emulation.setDeviceMetricsOverride` width=1440 height=900 deviceScaleFactor=1 | 所有 `getBoundingClientRect` 读数为 1440×900 下的 CSS 像素 |
| 本机自然视口 | 974 × 761 CSS px（DPR 2） | 窗口截图表面仍是 974×761，与 1440×900 按比例等效；基线报告 `design/harness-verify-baseline.md` §1 有同口径说明 |
| 缓存策略 | 验前 `Network.enable` + `Network.clearBrowserCache`；导航 URL 带 `?cb=<时间戳>` | 模板每次请求读盘，未清缓存读数无效 |
| 主世界探针 | 隔离世界读不到 `window.HX`；所有主世界变量/节点探针走 CDP `Runtime.evaluate`（`returnByValue=True`） | 与基线阶段一致 |

---

## 2. 机器门禁结果（脚本可复跑，JSON `verify-20261124-135424.json`）

| 检查项 | 结果 | 明细 |
|---|---|---|
| 静态资源 HTTP 200 | **PASS** | 11/11（harness-ui/thread/stage/collect/settings CSS + core/rail/thread/stage/collect/settings JS），失败 0 |
| `node --check` | **PASS** | 6/6 harness JS 模块 rc=0；node v22.23.2 |
| 违规模式扫描 | **FAIL 0 / WARN 4** | 4 条 WARN 均已人工复核为非违规，见 §2.1 |
| 隔离规则抽查 | **PASS**（0 失败） | thread/stage/collect/settings 均有 `data-shell` 守卫早退；core/rail 为壳本体，不适用该守卫 |
| 模板挂载引用 | **PASS** | core→rail→thread→stage→collect→settings 顺序引用齐全，失败 0 |
| pytest 子集 | **PASS** | `tests/test_v1100_workbench_shell.py`、`tests/test_v1102_rail_prototype_parity.py`、`tests/test_v1200_stage_layout.py`，51 例 rc=0（未全量跑） |
| API 探针 | **PASS** | `/api/status` 200；`/api/tasks` 200，`tasks_count=0` |

### 2.1 扫描 WARN 人工复核结论（均不判 FAIL）

| 文件:行 | 规则 | 复核结论 |
|---|---|---|
| harness-rail.js:40 | bare_done_text「已完成」 | 真实状态文案映射（`done/success/finished/published/drafted/approved` → 已完成），非写死进度 |
| harness-thread.js:365 | bare_done_text「已完成」 | 结果卡提示语「初稿已完成…」，非进度计数 |
| harness-thread.js:723 | bare_done_text「已完成」 | toast「耗时来自已完成的真实任务记录」，非演示数据 |
| harness-stage.js:300 | bare_iframe `<iframe` | iframe 带 `sandbox="allow-scripts allow-popups"`、`rel="no-referrer"`、懒加载、禁嵌提示与「外部打开」降级按钮，符合 §7.5 |

### 2.2 真实数据基线（API 实测，2026-11-24 13:55）

- `/api/status`：草稿 **57**，jobs **0**；能力线 `text = custom_520 · deepseek-v4.1-flash-free`（正常），`image = {}`、`video = {}`（未配置）。
- `/api/tasks`：**tasks = 0**。
- `/api/assets/library`：**total = 141**（资产 pane 未展示，见 I-3）。
- 草稿 `dr-346633505c`：`/raw/wechat_mp` 200 / 11165B，`/raw/xhs` 200 / 1352B，预览为真实排版。

---

## 3. 契约 §7 逐条核验

### 3.1 标准 1 —— 46px 顶栏 + 248px 左栏 + 弹性中栏 + 404px 右栏，无嵌套四栏 —— **PASS**

宽屏 1440×900 实测（`getBoundingClientRect`，CDP 主世界探针）：

| 节点 | x | y | 宽 | 高 | 契约口径 | 判定 |
|---|---|---|---|---|---|---|
| `#hxTopbar` | 0 | 0 | 1440 | **46** | 46px 深色顶栏 | PASS |
| `#hxRail` | 0 | 46 | **248** | 854 | 248px 左栏 | PASS |
| `#hxThread` | 248 | 46 | **788**（弹性） | 854 | 弹性中栏 `1fr` | PASS |
| `#hxStage` | 1036 | 46 | **404** | 854 | 404px 右栏 | PASS |
| `documentElement.scrollWidth` | — | — | **1440** | — | 无横向溢出 | PASS |

- 迷你左栏：`HX.toggleRail()` 后 `#hxRail` 宽 **68**（`data-rail=mini`，`HX.state.railMini=true`），再切回 248，持久化键生效。
- 嵌套四栏检查：body 顶层子节点为 `HEADER.hx-topbar` / `DIV.hx-rail` / `DIV.hx-thread` / `DIV.hx-stage`（外加 mask/input/svg/拖拽条），未见第二套三栏容器。
- 9 个契约挂载点 `#hxTopbar / #hxRail / #hxRailCtx / #hxThread / #hxThreadHead / #hxThreadBody / #hxStage / #hxStageTabs / #hxStageBody` 宽屏均存在。
- 持久化键：`yimu.hx.workspace / railMini / stageOpen / stageTab` 已写入。

证据截图：
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-tasks-20261124-134951.png`
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-narrow-20261124-135535.png`（窄屏回落，见 §3.6）

### 3.2 标准 2 —— 任务页：面包屑/标题/状态/操作/元信息 + 真实对话 + 真实进度/计划 + 输入区；右栏真实成稿 —— **FAIL**

**在位且真实的部分：**
- 中栏头「新创作任务 · 新任务」；meta 模型 `deepseek-v4.1-flash-free`（与 `/api/status.capabilities.text` 一致）；composer 输入区、快捷指令（抓热点/小红书种草/公众号长文/赛马标题）在位。
- `/api/tasks = 0`：计划卡计数 `planCardCount = 0`，正则 `已完成 n/n` 未命中，**无写死进度**；Agent 就绪空态文案与空任务基线一致，属诚实空态。
- 控制台 0 报错。

**未达标部分：**
- 真实对话面板 `#p-lite-mode` 在中栏内 `display:none / 0×0`；中栏可见内容为 thread 模块自绘的欢迎态，未承载真实消息流。
- 右栏任务态无真实成稿/图片/视频/数据（资产 pane 亦为空，见 I-3）。

证据截图：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-tasks-20261124-134951.png`

### 3.3 标准 3 —— 内容页：草稿箱在左栏，中栏真实编辑器，右栏预览；选中草稿三栏联动；保存/发布链路不丢 —— **FAIL**

**在位且真实的部分：**
- 左栏草稿箱 57 行真实镜像（`.hx-draft-row` 57 条，与 `/api/status.drafts=57` 一致），标题/评分/字数/平台 pill 来自真实草稿。
- 选中草稿后，真实编辑器迁入 `#hxEditorReal`：`.wb-editor-body` textarea 314×141、正文 1309 字，工具栏（AI 改写/智能配图/配图/复制导出/多端发布/进阶面板）为既有业务节点。
- 右栏预览为真实排版：标题「别用闹钟叫醒自己，用这杯☕」、970 字、评分 82、1 图、公众号/小红书(5图)/今日头条页签；raw 接口 xhs 200/1352B、wechat_mp 200/11165B。

**阻断缺陷（I-2）：三栏联动断裂。**
- 左栏镜像行点击只执行 `card.click()` 委托真实卡片，**未走 `HX.openDraft(id)`**：实测点第二行后，真实业务卡片 `.on` 已切到「349块的咖啡机开箱…」，但 `HX.state.draftId` 仍为第一篇，中栏头标题/字数不跟随，编辑器正文长度 0，右栏不切换。
- 直接调 `HX.openDraft(id)` 后头 meta 可更新，但中栏编辑器/右栏预览的跟随链路仍需业务选稿事件打通。
- 保存/发布链路：本轮为只读验收，未主动触发保存/发布；编辑器与工具栏真实节点在位，链路是否丢失待修复联动后回归。

证据截图：
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-content-draft-20261124-135026.png`（真实编辑器 + 预览）
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-stage-preview-20261124-135026.png`（右栏真实排版）

### 3.4 标准 4 —— 采集/设置按原型重排；原型有而系统没有的项标「未接入」，不得伪造开关 —— **FAIL**

**在位且真实的部分：**
- 采集 rail context：采集记录列表（全部 200 / 待拆解 191 / 已入库 0），话题标题、热榜位次、热度、状态来自真实数据。
- 设置 rail context：设置导航（模型与密钥/发布账号/内容与质量/团队与权限/安全合规…）。
- D 注册页签「采集分析」「配置检查」：
  - 采集分析：展示真实选中话题（标题、热榜位次、热度、待拆解/未命中），诚实标注「原文快照尚未入库」，无伪造正文。
  - 配置检查：文本引擎 `custom_520 · deepseek-v4.1-flash-free 正常`；图像/视频引擎「尚未配置…未配置」；发布账号、团队席位标「未接入」并注明「接口未回传…暂无真实数据」；健康度 1/3 能力线，与 `/api/status.capabilities` 一致，**无假开关**。

**阻断缺陷（I-1）：真实面板脱离中栏。**
- 进入采集工作区时 `#p-inspire` 已不在文档树（`getElementById = null`）；进入设置工作区时 `#p-console` 同样脱离，`#p-inspire` 未归还。
- 中栏仅显示兜底空态：「该页面内容由对应工作台模块接入，真实业务面板将自动落入此区域。」
- 对照回归：`?legacy=1` 与 `?ui=v2` 下 8 个面板全部在文档内，确认脱落为 harness 引入。

证据截图：
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-collect-20261124-135323.png`
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-settings-20261124-135323.png`

### 3.5 标准 5 —— 右栏 资产/浏览器/预览 三页签；资产接真实数据；预览真实排版；浏览器内嵌/禁 iframe 时外部打开 —— **PARTIAL（资产 FAIL）**

| 页签 | 判定 | 实测 |
|---|---|---|
| 预览 | **PASS** | 真实草稿排版渲染（标题/字数/评分/配图/平台页签），非假 HTML；raw 接口 200 |
| 浏览器 | **PASS** | 未选稿件时诚实空态「未选择稿件…去选稿件 / 去采集」，0 个 iframe；代码内 iframe 带 `sandbox="allow-scripts allow-popups"`、`rel="no-referrer"`、懒加载、禁嵌域名清单与「外部打开」降级按钮 |
| 资产 | **FAIL（I-3）** | `#assetsTabs`、`#assetsBody` 整个不在文档；`#assetsPanel` 被移入 `#hxStage` 但 `display:none`、0×0；pane 内 0 页签、0 资产条目。而 `/api/assets/library` total=141，真实数据存在但未接入 |

证据截图：
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-stage-preview-20261124-135026.png`
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-stage-browser-20261124-135323.png`
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-stage-assets-20261124-135012.png`（空资产 pane）

### 3.6 标准 6 —— classic / v2 行为不变；Harness 宽屏默认、窄屏回落 classic —— **PASS**

| 版本 | data-shell | hx 节点 | `window.HX` | 8 面板 | 草稿 | 控制台报错 | 实测布局 |
|---|---|---|---|---|---|---|---|
| `?legacy=1` | classic | 0 | undefined | 全部在 | 57 | 0 | side 230 / main 1210 / assets 隐藏 |
| `?ui=v2` | v2 | 0 | undefined | 全部在 | 57 | 0 | side 248 / main 792 / assets 400 |
| `?ui=harness` @900px | classic（回落） | 0 | undefined | — | — | 0 | 窄屏未启用 harness 外壳 |

- 两套旧版未被破坏；harness 节点未泄漏进 classic/v2。
- 既有非回归报错：模板内联 `renderSettingsData()` 偶发对空节点写值，`?legacy=1` 下同样出现，不计入本轮 harness 回归。

证据截图：
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-legacy-20261124-134910.png`
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-v2-20261124-134927.png`
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-narrow-20261124-135535.png`

### 3.7 标准 7 —— 逐页核验一级页与二级页；node --check + 相关 pytest 通过；截图与可复现结论 —— **PARTIAL**

**门禁（PASS）：** 静态 11/11 200；`node --check` 6/6；pytest 3 文件 51 例 rc=0；脚本可一键复跑。

**逐页覆盖矩阵（harness 宽屏实测）：**

| 工作区 | 一级页 | 二级入口 | harness 内状态 |
|---|---|---|---|
| 任务 tasks | 新创作任务 | — | 骨架在位，真实对话流未落入（I-4） |
| 内容 content | 内容工作台 | — | 编辑器/预览在位，联动断裂（I-2） |
| 采集 collect | 采集工作台 | inspire 6：`sp-oneshot / sp-extract / sp-hot / sp-search / sp-paste / sp-batch` | **阻断**：`#p-inspire` 脱离文档，6 个子页签不在 DOM，无法点开截图（I-1） |
| 设置 settings | 系统设置 | console 8：`sp-ticket / sp-agent-config / sp-skills / sp-health / sp-settings / sp-gateway / sp-user-admin / sp-video-config` | **阻断**：`#p-console` 脱离文档，8 个子页签不在 DOM，无法点开截图（I-1） |
| 更多·影音工坊 studio | 内容工厂 | studio 7：`sp-drama / sp-video / sp-aivideo / sp-storyboard / sp-audio / sp-video-tasks / sp-advideo` | 面板在文档内但 `on=true / 0×0` 隐藏；7 个 `.sub-tab` 与内联 `switchSubTab(...)` onclick 保留，不可见；未逐页点开（I-5） |

- 模板层二级入口 onclick 均为 `switchSubTab('<panel>','<sp-...>')`；全局 `switchSubTab`、`switchToPage` 函数仍在（`typeof = function`）。
- 任务书称 studio 二级 6 个，模板实测 **7 个**，已按模板如实记录。

证据截图：
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final-studio-20261124-135130.png`
- 一级工作区截图见 §3.2–3.4。

---

## 4. 问题清单（按归属文件，供主协调者回派）

> 严重级：**阻断** = 标准不通过、需修复后复验；**观察** = 待确认或非本轮回归。

### I-1 【阻断】`#p-inspire` / `#p-console` 脱离文档树，采集/设置中栏只剩兜底空态
- 实测：进 collect 时 `#p-inspire = null`；进 settings 时 `#p-console = null` 且 `#p-inspire` 未归还；classic/v2 下两面板均在。
- 归属候选：
  - `harness-collect.js` / `harness-settings.js`（D）：`mountPanel` 在面板已缺失时静默 `return`，无重建/告警；`unmountPanel` 归还链路可能把面板留在非文档宿主。
  - `harness-thread.js`（B）/ `harness-core.js`（A）：工作区切换时真实面板的迁入/归还与 `.on` 显隐口径。
  - 既有 `workbench-shell.js` / `workbench-stage.js`（只读）：其 DOM 搬家逻辑在 harness 壳下的交互需主协调者核查。
- 复验要点：collect/settings 进入后两面板应在 `#hxThreadBody`（或其 grid 槽内）可见，二级子页签可点开。

### I-2 【阻断】内容页三栏联动断裂：镜像行点击不更新 `HX.state.draftId`
- 实测：点 `.hx-draft-row` 第二行，真实卡片 `.on` 切换，但 `draftId` 不变、中栏头/编辑器/右栏不跟随；`HX.openDraft(id)` 可更新头 meta，编辑器/预览跟随仍不完整。
- 归属候选：
  - `harness-rail.js`（A）：镜像行 `click` 仅 `card.click()`，应对齐兜底分支调用 `HX.openDraft(d.id)`。
  - `harness-thread.js`（B）/ `harness-stage.js`（C）：需监听业务卡片 `.on` 变化作为兜底，保证中栏编辑器与右栏预览跟随选稿。
- 复验要点：左栏点任意草稿 → 头 meta、编辑器正文、右栏预览三者同步切换到同一草稿。

### I-3 【阻断】资产 pane 为空：`#assetsTabs` / `#assetsBody` 脱离文档
- 实测：harness 下两节点 `getElementById = null`；`#assetsPanel` 在 `#hxStage` 内 `display:none / 0×0`；pane 0 页签 0 条目；API `/api/assets/library` total=141。
- 归属候选：
  - `harness-stage.js`（C）：`moveAssetsInto` 在节点缺失时无兜底（仅 `if(tabs && ...) appendChild`）。
  - 上游既有资产节点构建/搬迁逻辑（`workbench-shell.js`，只读）在 harness 壳下是否未执行，需主协调者判定是否由 core 补建插槽。
- 复验要点：资产页签条与资产条目真实渲染，计数与 `/api/assets/library` 一致。

### I-4 【阻断/高】任务页真实对话面板未落入中栏
- 实测：`#p-lite-mode` 在中栏内 `display:none / 0×0`；中栏为 thread 自绘欢迎态；右栏无真实成稿。
- 归属候选：`harness-thread.js`（B）tasks 线程实现；`harness-core.js`（A）面板路由/迁入口径。
- 复验要点：任务页中栏出现真实对话消息流与 composer 联动；右栏随出稿更新。

### I-5 【中】studio 面板 0×0 隐藏；真实导航冒泡未映射到 harness workspace
- 实测：`#p-studio` `on=true` 但 0×0，7 个子页签不可见；点真实 `.side` 导航进 studio 后 `HX.state.workspace` 仍停在 content，中栏未按 studio 重排。
- 归属候选：`harness-core.js`（A）路由（业务导航冒泡 → `openWorkspace` 映射）；`harness-thread.js`（B）面板迁入。
- 复验要点：更多分组 4 个直达入口（操盘大屏/影音工坊/套餐与价格/个人中心）在 harness 下不消失且可到达。

### I-6 【观察】rail/topbar 高亮与 `state.workspace` 偶发不同步
- 实测：早期一轮 collect 时 rail 仍高亮 settings；复测 `is-active` 与 workspace 一致（collect/settings 均正确），复现条件未最终确认。
- 归属候选：`harness-rail.js`（A）/ `harness-core.js`（A）。

### I-7 【观察·既有接口问题】草稿视频任务接口 404
- 实测：`/api/drafts/{id}/video/tasks` 真实为 404，真实接口是全局 `/api/video/tasks`。
- 归属：`harness-thread.js`（B）。

### I-8 【非回归】模板内联 `renderSettingsData()` 偶发对空节点写值
- legacy 下同样出现，属既有问题，不计入 harness 回归；记录备查。

---

## 5. 复现步骤（只读验收）

1. 服务保持运行 `http://127.0.0.1:8790/`；仓库根执行 `python3 scripts/harness_ui_verify.py` 复跑门禁（静态 200 / node --check / 违规扫描 / 隔离抽查 / 模板引用 / pytest 子集 / API 探针），结果 JSON 写入 `design/harness-verify-results/`。
2. 浏览器导航 `?ui=harness&cb=<时间戳>`，先 `Network.clearBrowserCache`；CDP 模拟 1440×900；主世界探针走 `Runtime.evaluate`（`returnByValue=True`）。
3. 依次 `HX.openWorkspace('tasks'|'content'|'collect'|'settings')`，按 §3 矩阵截图、量尺寸、比对 API。
4. 回归：`?legacy=1`、`?ui=v2` 各验 shell 标识 / hx 节点数 / 8 面板 / 草稿数 / 报错数；900px 宽验窄屏回落。

## 6. 本轮未做（验收边界）

- 未修改任何 `web/static/**`、`web/templates/**`；未 git commit；未改版本号；未重启服务。
- 未主动触发保存/发布链路（避免改写业务数据）；该链路待 I-2 修复后补验。
- 未深挖 I-1/I-3 根因到具体代码行；归属为候选文件，最终回派由主协调者裁定。
