# Harness 外壳重建 · 第四阶段终轮复验报告（final3）

- 验收时间：2026-11-24 15:07–15:25（CST, UTC+8）
- 验收方：独立只读验收 Agent。**未改任何 `web/static/**`、`web/templates/**`；未 commit；未改版本号；未重启服务；未写库。**
- 被测应用：`http://127.0.0.1:8790/`；强制参数 `?ui=harness` / `?ui=v2` / `?legacy=1`
- 契约：`design/harness-shell-contract.md` §7；上一轮报告 `design/harness-verify-final2.md`（本轮覆盖其 F-1/F-2/F-6 结论，旧截图保留未删）
- 验收脚本：`scripts/harness_ui_verify.py`（仓库根 `python3 scripts/harness_ui_verify.py` 一键复跑）
- 机器检查 JSON：`design/harness-verify-results/verify-20261124-150728.json`
- 本轮范围：**只复验 final2 遗留 F-1 / F-2 / F-6 三项修复 + 必要回归抽查**；未重跑全部 28 张截图，仅补 4 张终态图（tasks / content / collect / settings）。

## 结论先行

| # | 复验项 | 判定 | 一句话结论 |
|---|---|---|---|
| 1 | F-1 采集/设置父面板可见性（opacity / 动画 / 盒高 / 二级入口） | **PASS** | `#p-inspire`、`#p-console` 实测 `opacity=1`、`animation-name=none`、788×790；inspire 6 / console 8 子页签逐个 `display:block` 且盒高 >0。 |
| 2 | F-2 内容页保存态 / 字数 / 平台徽标镜像跟随 | **PASS** | 对真实 `#wb-save-status / #wb-editor-wordcount / #wb-editor-plat-badge` 的 Observer 镜像生效：追加输入后头部 pill、meta chip、字数自动跟随；撤销复原后字数复位；全程无「载入中…」卡死。 |
| 3 | F-6 跨工作区头部残留 | **FAIL（未修复，见 §4.1）** | 内容页选稿后返回任务页，头部 h1 仍残留上一稿标题、pill 仍为「待审」；crumb 已复位。根因：`resolveCtx()` 在 tasks 工作区仍沿用 content 选中的 `draftId`。归属 `harness-thread.js`（B）。 |
| 4 | 回归：四工作区 + 四更多页结构尺寸 | **PASS** | 顶栏 46 / 左栏 248 / 中栏 788 / 右栏 404，`scrollWidth=1440`；四更多页均 788×800、opacity 1；studio `sp-drama` 782×957。 |
| 5 | 回归：右栏三页签真实数据 | **PASS** | 资产 成稿 57 / 图片 141 / 数据 57；预览真实排版；浏览器无来源稿件诚实空态。 |
| 6 | 回归：任务页 lite 面板与空计划 | **PASS** | `#p-lite-mode` 756×621、opacity 1；composer textarea 194×81 可用；`/api/tasks=0`，计划卡为「暂无执行计划」空态，无进度计数。 |
| 7 | 回归：`?legacy=1` / `?ui=v2` / 窄屏回落 | **PASS** | legacy shell=classic、v2 shell=v2，均 0 个 hx 节点；900px 回落 classic、0 hx 节点；无新增报错。 |
| 8 | 门禁脚本全量复跑 | **PASS** | hard_fail=0；静态 11/11 200、node --check 6/6、隔离 0 失败、模板引用 0 失败、pytest 3 文件 51 例 rc=0；扫描 WARN 3 条（复核非违规）。 |
| 9 | 控制台 error/WARN 归属；harness 模块自身 0 报错 | **PASS** | harness 宽屏四工作区 + 选稿链路 0 error / 0 warning；仅浏览器自带 password-field verbose DOM 提示；既有业务告警本轮未复现。 |
| 10 | F-3 高亮跟随（顺带核对） | **PARTIAL（见 §4.2）** | `is-active` class 切换正确，但视觉样式未跟随：旧项保留 active 背景/字色，新项未获得 active 背景。归属 core/rail（A）。 |

**总体：有条件通过。** 阻断项 F-1 已解除；F-2 已修复；**F-6 仍未修复（中，头部标题/状态跨工作区残留）**；F-3 视觉高亮残留为轻量项。F-4（无带源草稿，浏览器内嵌路径不可运行时实测）、F-5（既有 `renderSettingsData` 偶发告警，本轮未复现）维持 final2 记录。

---

## 1. 环境、视口与取证口径（含本轮纠错）

| 项 | 实测值 / 口径 | 说明 |
|---|---|---|
| 契约基准视口 | 1440 × 900 | CDP `Emulation.setDeviceMetricsOverride{width:1440,height:900,deviceScaleFactor:1,mobile:false}` |
| 视口自证（写入报告） | `innerWidth=1440`、`innerHeight=900`、`devicePixelRatio=1`、`documentElement.scrollWidth=1440` | 导航后同会话 `Runtime.evaluate` 读取，四项同时满足才截图 |
| 截图 DPR 口径 | **1x CSS 像素**；落盘图 PIL 复核均为 **1440×900** | 本机 Retina 下 CDP 全幅 `Page.captureScreenshot` 原始返回 2880×1800（2x  backing）；本轮按 `clip{0,0,1440,900,scale:1}` 与全幅降采样两种方式比对，最终交付图由 2880×1800 全幅 LANCZOS 降采样至 1440×900，右栏舞台完整入画（不再出现左栏 2 倍放大、中栏右侧被裁） |
| 尺寸口径 | 一律 `getBoundingClientRect()` CSS 像素，不从截图量 | 报告内宽/高均为 CSS px |
| 缓存 | 验前 `Network.enable` + `Network.clearBrowserCache`；导航带 `?cb=<时间戳>` | 模板每次请求读盘 |
| 主世界探针 | CDP `Runtime.evaluate`（`returnByValue=True`）；隔离世界读不到 `window.HX` | 与前三轮一致 |
| 真实数据基线 | drafts **57**、tasks **0**、assets library total **141** | `/api/status`、`/api/tasks`、`/api/assets/library` 本轮实测 |

### 1.1 布局矩形（CSS px，四工作区一致）

| 节点 | x | y | 宽 | 高 | 判定 |
|---|---|---|---|---|---|
| `#hxTopbar` | 0 | 0 | 1440 | **46** | PASS |
| `#hxRail` | 0 | 46 | **248** | 854 | PASS |
| `#hxThread` | 248 | 46 | **788**（弹性 1fr） | 854 | PASS |
| `#hxStage` | 1036 | 46 | **404** | 854 | PASS |
| `documentElement.scrollWidth` | — | — | **1440** | — | 无横向溢出 PASS |

---

## 2. 门禁结果（脚本复跑，JSON `verify-20261124-150728.json`）

| 检查项 | 结果 | 明细 |
|---|---|---|
| 静态资源 HTTP 200 | **PASS** | 11/11（5 CSS + 6 JS），失败 0 |
| `node --check` | **PASS** | 6/6 harness JS rc=0；node v22.23.2 |
| 违规模式扫描 | **FAIL 0 / WARN 3** | 见 §2.1 人工复核 |
| 隔离规则抽查 | **PASS**（0 失败） | core/rail 为壳本体不适用守卫早退，脚本保留 WARN，属设计内 |
| 模板挂载引用 | **PASS** | 0 失败 |
| pytest 子集 | **PASS** | `test_v1100_workbench_shell.py`、`test_v1102_rail_prototype_parity.py`、`test_v1200_stage_layout.py`，51 例 rc=0（未全量跑） |
| API 探针 | **PASS** | `/api/status` 200；`/api/tasks` 200，`tasks_count=0` |

### 2.1 扫描 WARN 人工复核（均不判 FAIL）

| 文件:行 | 规则 | 复核结论 |
|---|---|---|
| harness-rail.js:40 | bare_done_text「已完成」 | 真实状态文案映射，非写死进度 |
| harness-thread.js:724 | bare_done_text「已完成」 | toast「耗时来自已完成的真实任务记录」，非演示数据 |
| harness-stage.js:518 | bare_iframe `<iframe` | iframe 带 `sandbox` / `referrerpolicy=no-referrer` / `loading=lazy` / 外部打开 `noopener`，符合 §7.5 |

---

## 3. 本轮复验明细

### 3.1 F-1 采集 / 设置父面板可见性 —— **PASS**

计算样式 + 盒高（CSS px，`getComputedStyle` + `getBoundingClientRect`）：

| 工作区 | 面板 | opacity | animation-name | transform | 宽×高 | on |
|---|---|---|---|---|---|---|
| collect | `#p-inspire` | **1** | **none** | none | **788×790** | true |
| settings | `#p-console` | **1** | **none** | none | **788×790** | true |
| tasks | `#p-lite-mode` | 1 | none | none | 756×621 | — |
| content | `#p-drafts`（宿主） | 0 | fadeIn | none | 0×0 | true（见 §3.1.1 观察项） |

- CSS 固化规则已落地：`web/static/css/harness-ui.css:388`
  `body[data-shell="harness"] #hxThreadBody .panel { animation:none!important; opacity:1!important; transform:none!important; }`
  作用域已从中栏直属子节点扩到 `#hxThreadBody .panel` 任意层级。

**二级入口逐个点开（真实 `switchSubTab`，组键为 `inspire` / `console`）：**

| 组 | 子页签（实测 `display:block` 盒高，CSS px） |
|---|---|
| inspire 6 | sp-oneshot 361 · sp-extract 117 · sp-hot 7685 · sp-search 127 · sp-paste 580 · sp-batch 421 |
| console 8 | sp-ticket 220 · sp-agent-config 1460 · sp-skills 10355 · sp-health 318 · sp-settings 1624 · sp-gateway 1975 · sp-user-admin 1369 · sp-video-config 1534 |

- 右栏 D 页签在位：collect「采集分析 200」、settings「配置检查」；未接入项仍有文字标注、无假开关（沿用 final2 口径，本轮未回归到假开关）。

#### 3.1.1 观察项（不阻断）：content 宿主面板 `#p-drafts` 自身仍 `opacity:0 / 0×0`

- `#p-drafts` 节点链：`SECTION.p-drafts > MAIN > DIV.main-wrapper > DIV.hxThread`，**不在 `#hxThreadBody` 内**，故 §3.1 的固化规则未覆盖到它；其 `animation-name=fadeIn`、`opacity=0`、盒高 0。
- 但内容页可见片段 `#hxEditorReal`（`.hx-editor-real`）实测 **746×724、opacity 1、animation none**，编辑器与预览完整可见，**无视觉阻断**。
- 归属候选：`harness-thread.js`（B）迁入节点挂载位置 / `web/templates/index.html`（template）`.panel.on` fadeIn 规则。建议后续把 drafts 宿主也纳入终态固化，或迁入 `#hxThreadBody` 子树。

证据：
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final3-collect.png`
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final3-settings.png`

### 3.2 F-2 保存态 / 字数 / 平台徽标镜像跟随 —— **PASS**

内容页选中第 1 行草稿（`dr-346633505c`，别用闹钟…），探针对比真实节点与头部镜像槽：

| 阶段 | 真实 `#wb-save-status` | 真实 `#wb-editor-wordcount` | 真实 `#wb-editor-plat-badge` | 头部 pill | 镜像 save chip | 镜像 wc chip | 头部「载入中…」计数 |
|---|---|---|---|---|---|---|---|
| 基线 | ✓ 已与服务器同步 | 1231 字 / 69 行 | 🟢 微信公众号 | ✓ 已与服务器同步 | ✓ 已与服务器同步 | 1231 字 / 69 行 | **0** |
| 编辑器追加「【终验标记F2】」并派发 `input`（未点保存、未写库） | ● 未保存修改（按 Ctrl+S 存盘，2.5 秒后自动保存） | 1239 字 / 69 行 | 🟢 微信公众号 | ● 未保存修改… | ● 未保存修改… | 1239 字 / 69 行 | **0** |
| 恢复原文本 + 派发 `input` | ● 未保存修改（业务 dirty 标记，见下注） | 1231 字 / 69 行 | 🟢 微信公众号 | 跟随真实节点 | 跟随真实节点 | 1231 字 / 69 行 | **0** |

- Observer 链路与代码一致：`harness-thread.js:362-438`，对 `wb-save-status / wb-editor-wordcount / wb-editor-plat-badge` 挂 MutationObserver，镜像到头部 pill 与 `.hx-mirror-save/.hx-mirror-wc/.hx-mirror-plat`；离开内容页 `stopMirror()` 断开。
- 输入跟随：字数 1231→1239、保存态 已同步→未保存，头部 pill 与 meta chip **自动跟随**，无「载入中…」卡死。
- 数据安全：测试文本已撤销，`#wb-editor-input` 长度复原 1316（与原始一致）；**未点击保存按钮、未触发写库**。恢复后真实节点仍显示「未保存修改」是业务自身 dirty 标记（文本复原不等于清除 dirty），外壳如实镜像该状态，不属外壳缺陷。
- 保存链路（只读检查）：外壳保存按钮 `data-hx-act="save"` 事件委托在位；真实 `#btn-wb-save` 与全局 `saveCurrentPlatformContent` 存在。
- 「载入中…」文案归属：harness 6 个 JS 模块内 **0 处**「载入中…」；该占位文案来自业务 `web/templates/index.html` 与 `web/static/js/workbench-shell.js`（`updateSaveStatus()`），外壳只做镜像，未在外壳写死占位文案。

证据：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final3-content.png`

### 3.3 F-6 跨工作区头部残留 —— **FAIL（未修复）**

**复现路径（干净重载后）：** tasks（初始）→ content 选第 2 行草稿（349 块的咖啡机…）→ 返回 tasks。

| 阶段 | 头部 crumb | 头部 h1 | 头部 pill |
|---|---|---|---|
| 初始 tasks | 任务 › 内容工作台 | 新创作任务 | 新任务 |
| content 选稿后 | 内容工作台 › 349块的咖啡机开箱… | 349块的咖啡机开箱，我再没进过咖啡馆 | ✓ 已与服务器同步 |
| **返回 tasks（残留）** | 任务 › 内容工作台（已复位） | **349块的咖啡机开箱，我再没进过咖啡馆（残留）** | **待审（残留）** |

- 五段连续切换 tasks→content→collect→settings→tasks 复测：collect / settings 头部由 D 模块自有节点完整重写、无残留；**残留仅出现在返回 tasks 时**，h1 与 pill 沿用 content 选中稿。
- **根因定位（代码）**：`harness-thread.js:116-121` `resolveCtx()` 取 `draftId = state.draftId || domActiveDraftId()`；返回 tasks 时 `state.draftId` 未清、左栏草稿卡 `.on` 未摘，ctx 仍命中上一稿。`renderTasksHead()`（`harness-thread.js:242-256`）据 `ctx.draft` 渲染 h1（`d.title`）与 `pillFor(ctx.draft)`（无活动任务时归为「待审」）。`detachOwned('content')`（`harness-thread.js:669-680`）只归还面板/断 Observer/扫自有 chrome，**未清 `state.draftId` 与草稿卡选中态**。
- **归属**：`harness-thread.js`（B）。建议方向：离开 content 时清 `state.draftId`/摘掉草稿卡 `.on`，或 `renderTasksHead` 在 tasks 工作区无活动任务时不沿用 content 选中稿。
- 补充观察：左栏任务/草稿列表首项仍带 `is-active` 选中态，与同一根因相关。

### 3.4 回归：右栏三页签 —— **PASS**

| 页签 | 本轮实测 | 判定 |
|---|---|---|
| 资产 | 成稿 **57**、图片 **141**（= `/api/assets/library` total）、数据 **57**；条目含评分/平台/图数/卡数 | PASS |
| 预览 | 真实草稿排版：标题、字数、评分、平台页签在位 | PASS |
| 浏览器 | 无来源稿件诚实空态「这篇稿件没有原文链接…去采集工作台」，0 iframe | PASS（内嵌路径 F-4 仍无样本） |

### 3.5 回归：任务页 lite 面板与空计划 —— **PASS**

- `#p-lite-mode` 在 DOM，**756×621**、opacity 1、动画 none；composer textarea **194×81**、`disabled=false`。
- `/api/tasks = 0`：计划卡文案「执行计划 · 暂无真实任务记录 · 暂无执行计划：新建任务后…」；无 `.hx-plan-count` 进度计数（无 `5/5` 之类写死进度）。

证据：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final3-tasks.png`

### 3.6 回归：更多页 —— **PASS**

| 面板 | 盒宽×高 | opacity | 备注 |
|---|---|---|---|
| `#p-dashboard` | 788×800 | 1 | 可见 |
| `#p-studio` | 788×800 | 1 | 7 个二级页签在位；`sp-drama` 782×957 可见 |
| `#p-pricing` | 788×800 | 1 | 可见 |
| `#p-profile` | 788×800 | 1 | 可见 |

### 3.7 回归：legacy / v2 / 窄屏 —— **PASS**

| 版本 | shell | hx 节点 | 8 面板 | 控制台 |
|---|---|---|---|---|
| `?legacy=1` | classic | 0 | 全部在 | 0 harness 报错（仅 password-field verbose DOM 提示） |
| `?ui=v2` | v2 | 0 | 全部在 | 0 harness 报错 |
| `?ui=harness` @900px | classic（回落） | 0 | — | 0 报错，窄屏未启用外壳 |

### 3.8 控制台归属 —— **PASS**

- harness 宽屏四工作区 + 选稿链路：22 条消息全部为浏览器自带 `[DOM] Password field is not contained in a form` verbose 提示（业务登录表单，非外壳）；**harness 模块 0 error / 0 warning**。
- 既有业务告警：`renderSettingsData()` 偶发空节点写值、预览 iframe sandbox 告警，本轮三种 shell 均未复现，维持 F-5 记录备查。

---

## 4. 遗留问题清单（按归属文件，供回派）

### 4.1 F-6 【中 · 未修复】返回任务页头部残留上一稿标题与「待审」pill

- **现象**：content 选稿后切回 tasks，`#hxThreadHead` h1 仍为上一稿标题、pill 仍为「待审」；crumb 已复位。
- **证据（CSS px / 文本）**：见 §3.3 表格；返回 tasks 时 `state.workspace=tasks`，ctx.draft 仍为上一稿。
- **归属**：`harness-thread.js`（B）—— `resolveCtx()`（:116-121）、`renderTasksHead()`（:242-256）、`detachOwned()`（:669-680）未清 draftId / 草稿卡选中态。
- **复验要点**：content 选稿 → 返回 tasks，头部 h1 应为「新创作任务」、pill「新任务」，无残留标题/字数/状态。

### 4.2 F-3 【轻 · 部分残留】rail / topbar 高亮 class 正确但视觉样式未跟随

- **现象（settings 工作区实测）**：

  | 元素 | data-ws | `is-active` | 计算背景 | 计算字色 |
  |---|---|---|---|---|
  | rail 任务 | tasks | false | rgb(255,241,234)（accent-soft，active 底） | rgb(216,74,27)（active 红） |
  | rail 设置 | settings | **true** | rgba(0,0,0,0)（未获得 active 底） | rgb(102,109,120) |
  | topbar 任务 | tasks | false | rgb(48,52,61)（active 深底） | #fff |
  | topbar 设置 | settings | **true** | rgba(0,0,0,0)（未获得 active 底） | rgb(156,163,175) |

- **说明**：`harness-rail.js:314` 的 `classList.toggle('is-active', …)` class 切换结果与 `state.workspace` 一致；但 active 视觉样式未作用到新项，旧项保留 active 底/字色。CSS 规则在 `harness-ui.css:267 / 126`（`.hx-menu-item.is-active` / `.hx-tb-seg-btn.is-active`）。本轮未深挖到是业务旧 CSS 覆盖、样式表注入时序还是 transition 未收敛；本机 `:hover` 底为灰色，可排除悬停误判。
- **归属候选**：`harness-rail.js`（A）高亮刷新 / `harness-ui.css`（A）active 规则联动；必要时排查业务旧轨 CSS 对同名类的覆盖。
- **复验要点**：四工作区切换后，当前项获得 active 底/字色，其余项复位透明/灰字。

### 4.3 F-1 附观察项：drafts 宿主面板自身仍 `opacity:0 / 0×0`（不阻断）

- 见 §3.1.1。可见片段 `#hxEditorReal` 746×724 opacity 1，无视觉缺陷；建议后续把宿主面板纳入终态固化。

### 4.4 F-4 【观察 · 未覆盖路径】浏览器内嵌阅读路径无真实样本

- 57 篇草稿 `source_url` 全空，「有来源链接 → 内嵌 / 禁嵌域名 → 外部打开」运行时链路仍不可测；仅代码核验 + 无来源空态实测。待采集库产生带源草稿后补验。

### 4.5 F-5 【既有非回归】`renderSettingsData()` 偶发空节点写值

- 模板内联既有问题，本轮 harness/legacy/v2 均未复现，不计入外壳回归。

---

## 5. 本轮未覆盖与边界

- 未主动触发保存/发布/改写等写操作；F-2 测试文本已复原，未点保存、未写库。
- 浏览器内嵌/禁嵌降级运行时样本缺失（F-4）。
- 未修改任何业务代码/模板，未 commit，未改版本号，未重启服务。
- F-3 视觉样式未跟随的具体 CSS 覆盖源未在本轮深挖到规则行，归属为候选，最终定责由主协调者裁定。

## 6. 复现步骤

1. 仓库根 `python3 scripts/harness_ui_verify.py` 复跑门禁，JSON 写入 `design/harness-verify-results/`。
2. 浏览器导航 `?ui=harness&cb=<时间戳>`，先清缓存；CDP 模拟 1440×900 DPR=1；探针走 `Runtime.evaluate`；截图前读 `innerWidth/innerHeight/devicePixelRatio/scrollWidth` 自证。
3. F-1：`HX.openWorkspace('collect'|'settings')` 读面板计算样式与盒高；`switchSubTab('inspire'|'console', '<sp-…>')` 逐个开二级入口。
4. F-2：content 选稿 → 读 `wb-save-status/wb-editor-wordcount/wb-editor-plat-badge` 与头部镜像槽；向 `#wb-editor-input` 追加文字并派发 `input`，对比跟随；复原文本 + `input`，确认字数复位、未写库。
5. F-6：tasks→content 选稿→collect→settings→tasks 连续切换，逐段读 `#hxThreadHead` 文本。
6. 回归 `?legacy=1`、`?ui=v2`；900px 宽验窄屏回落。

## 7. 本轮证据截图（1440×900，1x CSS 像素，PIL 复核）

- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final3-tasks.png` —— 任务页：lite Copilot、空计划卡、composer 在位
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final3-content.png` —— 内容页：选稿后编辑器 / 字数 / 平台徽标 / 预览三栏联动
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final3-collect.png` —— 采集页：真实面板可见、采集分析页签
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final3-settings.png` —— 设置页：配置面板可见、配置检查页签
