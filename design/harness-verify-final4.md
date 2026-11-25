# Harness 外壳重建 · 第五阶段收口复验报告（final4）

- 验收时间：2026-11-24 15:39–15:46（CST, UTC+8）
- 验收方：独立只读验收 Agent。**未改任何 `web/static/**`、`web/templates/**`；未 commit；未改版本号；未重启服务；未写库。**
- 被测应用：`http://127.0.0.1:8790/`；参数 `?ui=harness` / `?ui=v2` / `?legacy=1`
- 上一轮报告：`design/harness-verify-final3.md`（本轮覆盖其 F-3 / F-6 结论）
- 验收脚本：`scripts/harness_ui_verify.py`；门禁 JSON：`design/harness-verify-results/verify-20261124-153910.json`
- 本轮范围：**只验 F-3、F-6 两项收口 + 必要回归抽查**；未跑全量矩阵。

## 结论先行

| # | 复验项 | 判定 | 一句话结论 |
|---|---|---|---|
| 1 | F-6 选稿后返回任务页头部复位；回内容页恢复 | **PASS** | 选第 3 篇草稿 → 任务页头部为「新创作任务 / 新任务」，无稿标题、无「待审」；回内容页同稿恢复，编辑器 891 字、820 字/54 行、已同步。 |
| 2 | F-3 左栏 / 顶栏激活态色值跟随 | **PARTIAL（残留，见 §3.2）** | `is-active` class 切换正确、CSS 规则与声明色值就位；但实测 CSS transition **冻结在 `currentTime=0 / running`**，新激活项未取得激活色、旧激活项未复位，计算样式与目标色值不符。 |
| 3 | 回归：四工作区结构尺寸 | **PASS** | 顶栏 46 / 左栏 248 / 中栏 788 / 右栏 404，`innerWidth=1440`、`devicePixelRatio=1`、`scrollWidth=1440`。 |
| 4 | 回归：legacy / v2 0 hx 节点；harness 自身 0 error | **PASS** | legacy shell=classic、v2 shell=v2，均 0 hx 节点、`HX` undefined；harness 0 error / 0 warning。 |
| 5 | 门禁脚本复跑 | **PASS** | hard_fail=0，scan_warns=3（复核非违规）；pytest 51 例 rc=0。 |

**总体：有条件通过。** F-6 已修复；F-3 的 class 判据与样式规则已修对，但过渡动画未收敛导致视觉高亮仍错（轻-中，归属 A）。F-4（无带源草稿，浏览器内嵌路径不可运行时实测）、F-5（既有 `renderSettingsData` 偶发告警，本轮未复现）维持 final3 记录。

---

## 1. 环境与取证口径

| 项 | 实测值 |
|---|---|
| 视口自证 | `innerWidth=1440`、`innerHeight=900`、`devicePixelRatio=1`、`documentElement.scrollWidth=1440` |
| 截图 | CDP 全幅 `Page.captureScreenshot`（本机 Retina 原始 2880×1800）LANCZOS 降采样至 **1440×900**，PIL 复核 4 张均 1440×900；尺寸一律 `getBoundingClientRect()` CSS px |
| 缓存 | 验前 `Network.clearBrowserCache`；导航带 `?cb=<时间戳>` |
| 真实数据 | drafts 57、tasks 0、assets 141（门禁 API 探针） |

布局矩形（CSS px，四工作区一致）：`#hxTopbar` 1440×46 @0,0；`#hxRail` 248×854 @0,46；`#hxThread` 788×854 @248,46；`#hxStage` 404×854 @1036,46。

## 2. 门禁结果（`verify-20261124-153910.json`）

- **hard_fail=0**，scan_warns=3；静态 11/11 200；`node --check` 6/6；隔离抽查 0 失败；模板引用 0 失败；pytest 3 文件 51 例 rc=0；`/api/status` 200、`/api/tasks` 200（tasks_count=0）。
- 扫描 WARN 3 条（rail.js:40 / thread.js:724 / stage.js:518）复核同 final3，均非违规。

## 3. 复验明细

### 3.1 F-6 任务页头部复位 / 回内容页恢复 —— **PASS**

流程：干净重载 → 内容页选第 3 篇 → 任务页 → 回内容页。

| 阶段 | `HX.state.draftId` | 头部 crumb | 头部 h1 | 头部 pill | 编辑器 | 字数 | 保存态 |
|---|---|---|---|---|---|---|---|
| 内容页选第 3 篇 | `dr-3401d32584` | 内容工作台 › 警惕！不用Agent的… | 警惕！不用Agent的企业，正在被24小时不眠的AI团队围剿 | ✓ 已与服务器同步 | 891 字 | 820 字 / 54 行 | ✓ 已与服务器同步 |
| **返回任务页** | — | 任务 › 内容工作台 | **新创作任务** | **新任务** | — | — | — |
| 回内容页 | `dr-3401d32584` | 内容工作台 › 警惕！不用Agent的… | 警惕！不用Agent的企业，正在被24小时不眠的AI团队围剿 | ✓ 已与服务器同步 | 891 字 | 820 字 / 54 行 | ✓ 已与服务器同步 |

- 返回任务页：**未出现**该稿标题、**未出现**「待审」；`hasDraft=false`。
- 回内容页：选中稿、正文、字数、保存态均恢复；左栏对应草稿行 `.is-active` 在位。
- 代码核对：`harness-thread.js:192-198` `taskCtx()` 仅在 `/api/tasks` 有 `target_id` 命中且 running/queued 真实任务时沿用草稿，否则 `draft=null`；`:254-257` `renderTasksHead` 先过 `taskCtx`；`:662` `refreshWs` 用本模块 `resolveCtx()` 归一化 draftId 字符串；`:702-715` `ensureBusinessDraft()` 回内容页按 retained draftId 调 `HX.openDraft` 恢复。本轮 `/api/tasks=0`，任务页正确落空态。

证据：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final4-tasks.png`、`final4-content.png`

### 3.2 F-3 左栏 / 顶栏激活态 —— **PARTIAL（过渡冻结，视觉未跟随）**

**六步切换**：tasks → content → collect → settings → 更多·studio → settings。

- **class 判据（正确）**：每步仅一项左栏 `is-active`、仅一段顶栏 `is-active`；更多页 studio 时顶栏四段全灭、左栏「影音工坊」更多项 `is-active`；返回 settings 后复位。
- **CSS 规则（就位）**：`harness-ui.css:127-128` 顶栏、`:270-279` 左栏，非激活 `:not(.is-active)` 显式 `transparent !important`，激活高优先级夺回；声明色值：左栏激活底 `rgb(255,241,234)`、字 `rgb(169,73,36)`、徽标底 `rgb(255,216,198)`/字 `rgb(181,74,34)`；顶栏激活底 `rgb(48,52,61)`/白字。
- **计算样式实测（settings 工作区，未达标）**：

  | 元素 | ws | `is-active` | 实测背景 | 实测字色 | 应为 |
  |---|---|---|---|---|---|
  | 左栏 | tasks | false | **rgb(255,241,234)** | **rgb(169,73,36)** | transparent / rgb(102,109,120) |
  | 左栏 | settings | **true** | rgba(0,0,0,0) | rgb(102,109,120) | rgb(255,241,234) / rgb(169,73,36) |
  | 顶栏 | tasks | false | **rgb(48,52,61)** | **rgb(255,255,255)** | transparent / rgb(156,163,175) |
  | 顶栏 | settings | **true** | rgba(0,0,0,0) | rgb(156,163,175) | rgb(48,52,61) / #fff |

- **冻结取证**：未激活旧项上 `background-color` / `color` / `font-weight` 的 `CSSTransition` `playState=running`、**`currentTime=0`**、duration 160ms；切换后静置 1.5s 仍停在 0。对按钮临时置 `transition:none` 强制回流后，计算背景/字色立即变为目标值（透明/灰），证明级联规则本身生效，**卡点在过渡动画未收敛**。
- **归属候选（A）**：`harness-rail.js`（挂载/重排时序，迁入节点后未强制重排使过渡起跑）与 `harness-ui.css`（`.hx-menu-item` / `.hx-tb-seg-btn` 的 `transition: all .16s` 与迁入节点组合）；与 final2 F-1 同类「节点迁移后动画/过渡冻结在起始帧」模式。建议方向：挂载后强制 reflow、迁移节点上先清过渡再切 class，或激活态去掉过渡。
- 备注：本轮在 CDP/无头环境取证；真实浏览器下过渡是否同样冻结，建议上线前在本机 Chrome 再目检一次。

### 3.3 回归抽查

| 项 | 实测 | 判定 |
|---|---|---|
| 四工作区尺寸 | 46 / 248 / 788 / 404，scrollWidth 1440 | PASS |
| 右栏三页签 | 资产 成稿 57 / 图片 141 / 数据 57；预览真实排版；浏览器无来源诚实空态 | PASS（沿用 final3 口径） |
| 任务页 | lite 面板 756×621、composer 可用、空计划卡无进度计数 | PASS（沿用 final3 口径） |
| `?legacy=1` | shell=classic、hx=0、`HX` undefined、7 面板齐；6 条 error 均为业务预览 iframe sandbox 拦截 `about:srcdoc` 脚本（既有业务告警，非外壳） | PASS |
| `?ui=v2` | shell=v2、hx=0、`HX` undefined、7 面板齐、0 error | PASS |
| harness 控制台 | 0 error / 0 warning；11 条均为浏览器自带 password-field verbose DOM 提示 | PASS |

## 4. 遗留项与归属

| 编号 | 级别 | 现象 | 归属 |
|---|---|---|---|
| F-3（残留） | 轻-中 | 激活 class 与 CSS 规则正确，但过渡冻结 `currentTime=0`，高亮视觉未跟随：旧项保留激活色、新项未取得激活色 | A：`harness-rail.js` 挂载/重排时序；`harness-ui.css` 过渡规则 |
| F-4 | 观察 | 57 篇草稿 `source_url` 全空，浏览器内嵌/禁嵌运行时路径无样本可测 | 待业务产生带源草稿后补验 |
| F-5 | 既有非回归 | `renderSettingsData()` 偶发空节点写值，本轮未复现 | 模板既有问题，不计外壳回归 |

## 5. 证据截图（1440×900，1x CSS 像素，PIL 复核）

- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final4-tasks.png` —— 任务页：头部「新创作任务 / 新任务」、空计划卡
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final4-content.png` —— 内容页：第 3 篇选稿，编辑器 820 字/54 行、已同步、预览排版
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final4-collect.png` —— 采集页真实面板
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final4-settings.png` —— 设置页配置面板 + 配置检查页签

## 6. 边界

- 未触发保存/发布/改写等写操作；未修改业务代码/模板，未 commit，未改版本号，未重启服务。
- F-3 冻结根因未深挖到具体 CSS/JS 行，归属为候选；建议真实 Chrome 目检复核过渡是否同样不收敛。
