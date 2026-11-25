# Harness 外壳重建 · 第三阶段终态验收报告（final2）

- 验收时间：2026-11-24 14:37–14:55（CST, UTC+8）
- 验收方：独立只读验收 Agent。**未改任何 `web/static/**`、`web/templates/**`；未 commit；未改版本号；未重启服务。**
- 被测应用：`http://127.0.0.1:8790/`；强制参数 `?ui=harness` / `?ui=v2` / `?legacy=1`
- 唯一视觉基准：`design/harness-workspace-preview.html`；契约：`design/harness-shell-contract.md` §7
- 验收脚本：`scripts/harness_ui_verify.py`（仓库根 `python3 scripts/harness_ui_verify.py` 一键复跑）
- 机器检查 JSON：`design/harness-verify-results/verify-20261124-145443.json`
- 上一轮报告：`design/harness-verify-final.md`（本轮覆盖其结论；旧截图保留未删）

## 结论先行

| # | 契约/任务验收项 | 判定 | 一句话结论 |
|---|---|---|---|
| 1 | 1440×900 四工作区尺寸：顶栏 46 / 左栏 248（迷你 68）/ 右栏 404 / 中栏弹性 / 无横向溢出 / 无嵌套四栏 | **PASS** | 实测 46 / 248 / 788 / 404，scrollWidth=1440，三栏容器仅一套；迷你 68、还原 248。 |
| 2 | 任务页：`#p-lite-mode` 在 DOM 且 >0、composer 可用、计划卡空态、无写死进度 | **PASS** | lite 756×621、composer textarea 194×81 可用；`/api/tasks=0`，计划卡为「暂无执行计划」空态，正则 `已完成 n/n` 未命中。 |
| 3 | 内容页：草稿箱 → 第 1/2/5 行 `draftId` 与卡片 `.on` 一致；编辑器正文/字数联动；预览同步；保存链路在位 | **PARTIAL** | 三栏联动已通（3 篇 draftId/正文/字数/预览全部一致）；**遗留 F-2**：外壳头 pill 与 meta chip 镜像保存状态后不随业务回调刷新，卡「⚡ 载入中…」。 |
| 4 | 采集/设置：中栏真实面板可见、二级入口逐个点开、未接入标注、字段对齐 API | **FAIL（F-1）** | 面板 DOM 在位、盒高 >0、6+8 子页签可切换且 onclick 为真实 `switchSubTab`；**但父面板 `opacity:0`、fadeIn 动画冻结 currentTime=0，中栏视觉空白**。D 页签字段与 `/api/status` 一致、未接入项无假开关。 |
| 5 | 右栏三页签：资产真实条目 / 预览真实排版 / 浏览器降级外部打开 | **PASS（附观察项 F-4）** | 资产 成稿 57 / 图片 141 / 数据 57；预览真实排版 1 图；浏览器无来源稿件诚实空态；iframe sandbox/no-referrer/懒加载/外部打开按钮代码在位。内嵌路径本轮无带源草稿可实测。 |
| 6 | 更多页：dashboard / studio / pricing / profile 可见 >0；studio 二级点开 1 个 | **PASS（附轻量 F-3）** | 四面板均 788×800、opacity 1；studio `sp-drama` 782×957 可见。更多页 rail/topbar 高亮未跟随（F-3）。 |
| 7 | 回归：legacy / v2 0 hx 节点、8 面板齐、57 草稿、0 新增报错；<1024 窄屏回落 classic | **PASS** | legacy shell=classic、v2 shell=v2，均 0 hx 节点、`HX` undefined、8 面板齐、57 草稿、0 报错；900px 回落 classic。 |
| 8 | 门禁：静态 200 / node --check / 违规扫描 / 模板引用 / pytest 子集 / API 探针 | **PASS** | hard_fail=0；静态 11/11、node 6/6、隔离 0 失败、模板引用 0 失败、pytest 3 文件 51 例 rc=0；扫描 WARN 3 条均已人工复核非违规。 |
| 9 | 控制台 error/WARN 归属；harness 模块自身 0 报错 | **PASS** | 本轮 harness 宽屏四工作区 + 选稿链路 0 error / 0 warning；legacy、v2 同为 0。既有 `renderSettingsData()` 偶发告警本轮未复现（F-5）。 |

**总体：有条件通过，1 个阻断视觉缺陷（F-1）需修复后复验；2 个轻量问题（F-2/F-3）建议同批处理。** 上一轮 I-1（面板脱落）、I-2（三栏联动断裂）、I-3（资产 pane 空）、I-4（任务对话未落入）、I-5（更多页不可见）经本轮复测均已解除，详见 §3。

---

## 1. 环境、视口与取证口径

| 项 | 实测值 | 说明 |
|---|---|---|
| 契约基准视口 | 1440 × 900 | CDP `Emulation.setDeviceMetricsOverride{width:1440,height:900,deviceScaleFactor:1,mobile:false}` |
| 截图方式 | CDP `Page.captureScreenshot`，`clip 1440×900 scale:1`，`captureBeyondViewport:true` | 全部 final2 宽屏图实测 **1440×900、1x CSS 像素**（PIL 复核）；窄屏图 900×761 |
| 尺寸口径 | 一律 `getBoundingClientRect()` CSS 像素，不从截图量 | 报告内宽/高均为 CSS px |
| 缓存 | 验前 `Network.enable` + `Network.clearBrowserCache`；导航带 `?cb=<时间戳>` | 模板每次请求读盘 |
| 主世界探针 | CDP `Runtime.evaluate`（`returnByValue=True`）；隔离世界读不到 `window.HX` | 与前两轮一致 |
| 真实数据基线 | drafts **57**、jobs **0**、assets **141**；能力线 text=`deepseek-v4.1-flash-free`，image/video 未配置 | `/api/status`、`/api/tasks`、`/api/assets/library` 实测 14:54 |

---

## 2. 门禁结果（脚本复跑，JSON `verify-20261124-145443.json`）

| 检查项 | 结果 | 明细 |
|---|---|---|
| 静态资源 HTTP 200 | **PASS** | 11/11（harness-ui/thread/stage/collect/settings CSS + core/rail/thread/stage/collect/settings JS），失败 0 |
| `node --check` | **PASS** | 6/6 harness JS rc=0；node v22.23.2 |
| 违规模式扫描 | **FAIL 0 / WARN 3** | 见 §2.1 人工复核 |
| 隔离规则抽查 | **PASS**（0 失败） | thread/stage/collect/settings 均有 `data-shell` 守卫早退；core/rail 为壳本体不适用（脚本保留 WARN，属设计内） |
| 模板挂载引用 | **PASS** | core→rail→thread→stage→collect→settings 顺序齐全 |
| pytest 子集 | **PASS** | `test_v1100_workbench_shell.py`、`test_v1102_rail_prototype_parity.py`、`test_v1200_stage_layout.py`，51 例 rc=0（未全量跑） |
| API 探针 | **PASS** | `/api/status` 200；`/api/tasks` 200，`tasks_count=0` |

### 2.1 扫描 WARN 人工复核（均不判 FAIL）

| 文件:行 | 规则 | 复核结论 |
|---|---|---|
| harness-rail.js:40 | bare_done_text「已完成」 | 真实状态文案映射（`done/success/…` → 已完成），非写死进度 |
| harness-thread.js:612 | bare_done_text「已完成」 | toast「耗时来自已完成的真实任务记录」，非演示数据 |
| harness-stage.js:518 | bare_iframe `<iframe` | iframe 带 `sandbox="allow-scripts allow-popups"`、`referrerpolicy="no-referrer"`、`loading="lazy"`、禁嵌提示与「外部打开」`target=_blank rel=noopener`，符合 §7.5 |

---

## 3. 契约 §7 逐条复验

### 3.1 标准 1 —— 三栏尺寸 / 无嵌套四栏 —— **PASS**

1440×900 宽屏实测（CSS px，`getBoundingClientRect`）：

| 节点 | x | y | 宽 | 高 | 判定 |
|---|---|---|---|---|---|
| `#hxTopbar` | 0 | 0 | 1440 | **46** | PASS |
| `#hxRail` | 0 | 46 | **248** | 854 | PASS |
| `#hxThread` | 248 | 46 | **788**（弹性 `1fr`） | 854 | PASS |
| `#hxStage` | 1036 | 46 | **404** | 854 | PASS |
| `documentElement.scrollWidth` | — | — | **1440** | — | 无横向溢出 PASS |

- 迷你左栏：`HX.toggleRail()` → 宽 **68**（`railMini=true`），还原 **248**（`railMini=false`），持久化生效。
- 嵌套四栏：body 顶层三栏为 `HEADER.hxTopbar / DIV.hxRail / DIV.hxThread / DIV.hxStage`，`.hx-rail/.hx-thread/.hx-stage` 计数 **3**，未见第二套三栏容器；其余 body 子节点为既有业务 modal/input/svg/sprite。
- 9 个契约挂载点宽屏均存在。

证据：`design/harness-shots/final2-tasks-20261124-145313.png`

### 3.2 标准 2 —— 任务页真实对话 / 空计划 / composer —— **PASS**

- `#p-lite-mode` 在 DOM，实测 **756×621**，opacity 1、动画 none；composer textarea **194×81**、`disabled=false`。
- `/api/tasks = 0`：计划卡 1 张，文案「执行计划 · 暂无真实任务记录 · 暂无执行计划：新建任务后…」；正则 `已完成 n/n` **未命中**，无写死进度。
- 中栏真实 Copilot 面板在位（爆款创作 Copilot、快捷指令、模型选择 `deepseek-v4.1-flash-free`）；右栏资产页签可见成稿/图片/数据汇总。
- 控制台 0 报错。

证据：`design/harness-shots/final2-tasks-20261124-145313.png`

### 3.3 标准 3 —— 内容页三栏联动 / 编辑器 / 预览 / 保存链路 —— **PARTIAL（联动 PASS，遗留 F-2）**

**联动实测（左栏镜像行点击，未直接调 `HX.openDraft`）：**

| 点击行 | `HX.state.draftId` | 真实卡片 `.on` | 编辑器正文长度 | 字数（业务） | 右栏预览 |
|---|---|---|---|---|---|
| 第 1 行 | `dr-346633505c` | 别用闹钟叫醒自己… 82 良好 | 1309 | 1225 字 / 69 行 | 公众号 · 970 字 · 评分 82 ✓ |
| 第 2 行 | `dr-0852c14e10` | 349 块的咖啡机… 87.3 | 298 | — | 218 字 · 评分 87 ✓ |
| 第 5 行 | `dr-7dc058f9ad` | 算清账后我哭了… | 1240 | — | 788 字 · 评分 84 ✓ |

- 编辑器：`#wb-editor-input` **314×141**、`disabled=false`、正文随选稿切换；`#hxEditorReal/.workspace-stage` **746×724**、opacity 1；`#phone-empty-state` `display:none / 0×0`，无空节点报错。
- 保存链路（只读检查，未写库）：外壳保存按钮 `data-hx-act="save"` 走事件委托，点击真实 `#btn-wb-save`（「💾 保存并重新渲染 (Ctrl+S)」，`onclick` 在位），兜底全局 `saveCurrentPlatformContent` 函数存在。
- **遗留 F-2**：见 §4。业务 `#wb-save-status` 已为「✓ 已与服务器同步」后，外壳头 pill 与 meta chip 仍卡「⚡ 载入中…」；手动 `HX.refresh()` 后才同步。

证据：`design/harness-shots/final2-content-20261124-144730.png`

### 3.4 标准 4 —— 采集 / 设置面板与二级入口 —— **FAIL（F-1，视觉遮挡）**

**已通过项：**
- `#p-inspire` 实测 **788×790**、`on=true`；`#p-console` **788×790**、`on=true`；面板内按钮 195（inspire）。
- 二级入口 DOM 与真实 onclick 在位，逐个切换后子视图 `display:block`、宽 ~788：

| 工作区 | 二级页签（实测可见盒高） |
|---|---|
| inspire 6 | sp-oneshot 361 · sp-extract 117 · sp-hot 7683 · sp-search 127 · sp-paste 580 · sp-batch 421 |
| console 8 | sp-ticket 220 · sp-agent-config 1460 · sp-skills 10355 · sp-health 318 · sp-settings 1624 · sp-gateway 1975 · sp-user-admin 1369 · sp-video-config 1534 |

- 右栏 D 页签：collect「采集分析 200」、settings「配置检查」。配置检查字段与 `/api/status` 一致：文本 `custom_520 · deepseek-v4.1-flash-free 正常`；图像/视频「尚未配置…未配置」；发布账号、团队席位「未接入」并注明接口未回传；健康度 1/3 能力线。配置 pane 内 checkbox/radio/开关 **0 个**，无假开关。
- 采集分析：真实选中话题（标题/热榜位次/热度/待拆解/未命中），诚实标注「原文快照尚未入库」。

**阻断缺陷 F-1：** 两个父面板 `opacity: 0`、`animation: fadeIn` `currentTime=0 / running`，空闲 4 秒不收敛；中栏视觉空白。强制 `animation:none; opacity:1` 后内容完整在位（诊断图）。详见 §4 F-1。

证据：
- 采集总览（空白中栏）：`design/harness-shots/final2-collect-20261124-145215.png`
- 设置总览（空白中栏）：`design/harness-shots/final2-settings-20261124-145215.png`
- 解除遮挡诊断（内容在位）：`design/harness-shots/final2-collect-opacity-diag.png`
- inspire 6：`design/harness-shots/final2-inspire-sp-{oneshot,extract,hot,search,paste,batch}-20261124-144236.png`
- console 8：`design/harness-shots/final2-console-sp-{ticket,agent-config,skills,health,settings,gateway,user-admin,video-config}-20261124-144305.png`

### 3.5 标准 5 —— 右栏资产 / 浏览器 / 预览 —— **PASS（附 F-4 观察项）**

| 页签 | 实测 | 判定 |
|---|---|---|
| 资产 | 自渲染：成稿 **57**（= drafts）、图片 **141**（= `/api/assets/library` total）、数据 **57**；条目含评分/平台/图数/卡数/时间；页签徽标「资产141」 | PASS |
| 预览 | 真实草稿排版：标题、970 字、评分 82、1 图、平台页签；raw 接口 wechat_mp/xhs 200 | PASS |
| 浏览器 | 无来源稿件诚实空态「这篇稿件没有原文链接…去采集工作台」，0 iframe；代码内 iframe `sandbox="allow-scripts allow-popups"`、`no-referrer`、懒加载、禁嵌提示与「外部打开」`noopener` | PASS（内嵌路径 F-4 未实测） |

- `#assetsPanel` 与 `#assetsTabs/#assetsBody` 已迁入离屏持有节点 `#hxLegacyHolder`（-9999，1×1），不再以 0×0 空壳占舞台。
- 三页签对四工作区注册：tasks/content = 资产/浏览器/预览；collect 加「采集分析 200」；settings 加「配置检查」。

证据：
- `design/harness-shots/final2-stage-assets-20261124-145346.png`
- `design/harness-shots/final2-stage-preview-20261124-145346.png`
- `design/harness-shots/final2-stage-browser-20261124-145346.png`

### 3.6 标准 6 —— 更多页直达入口 —— **PASS（附 F-3 轻量项）**

| 面板 | 实测盒宽×高 | opacity | 备注 |
|---|---|---|---|
| `#p-dashboard` | 788×800 | 1 | 真实数据：191 热点雷达、57 篇成稿、均分 77.8 |
| `#p-studio` | 788×800 | 1 | 7 个二级页签在位；`sp-drama` 子视图 782×957 可见 |
| `#p-pricing` | 788×800 | 1 | 可见 |
| `#p-profile` | 788×800 | 1 | 可见 |

- studio 二级：`sp-drama / sp-video / sp-aivideo / sp-storyboard / sp-audio / sp-video-tasks / sp-advideo`（7 个，模板实测；任务书口径 6 个以模板为准）。
- F-3：进入更多页后左栏/顶栏高亮未跟随到对应面板，仍停留前一工作区。

证据：
- `design/harness-shots/final2-more-dashboard-20261124-144454.png`
- `design/harness-shots/final2-more-studio-20261124-144454.png`
- `design/harness-shots/final2-more-pricing-20261124-144454.png`
- `design/harness-shots/final2-more-profile-20261124-144454.png`
- `design/harness-shots/final2-studio-sp-drama-20261124-144454.png`

### 3.7 标准 7 —— classic / v2 回归 + 窄屏回落 —— **PASS**

| 版本 | shell | hx 节点 | `HX` | 8 面板 | 草稿 | 控制台报错 | 实测布局 |
|---|---|---|---|---|---|---|---|
| `?legacy=1` | classic | 0 | undefined | 全部在 | 57 | 0 | side 230 / main 1210 |
| `?ui=v2` | v2 | 0 | undefined | 全部在 | 57 | 0 | side 248 / main 792 / assets 400 |
| `?ui=harness` @900px | classic（回落） | 0 | undefined | — | — | 0 | 窄屏未启用外壳 |

证据：
- `design/harness-shots/final2-legacy-20261124-144536.png`
- `design/harness-shots/final2-v2-20261124-144549.png`
- `design/harness-shots/final2-narrow-20261124-144602.png`

### 3.8 标准 8/9 —— 门禁与控制台归属 —— **PASS**

- 门禁 hard_fail=0，明细见 §2；pytest 51 例 rc=0。
- 控制台：harness 宽屏四工作区 + 两轮选稿链路，**0 error / 0 warning**；legacy、v2 同为 0。
- 既有业务告警（非本轮回归）：模板内联 `renderSettingsData()` 偶发对空节点写值；本轮三种 shell 均未复现，记录备查。预览 iframe sandbox 相关告警本轮未出现。

---

## 4. 问题清单（按归属文件，供回派）

### F-1 【阻断 · 视觉遮挡】采集/设置父面板 fadeIn 动画冻结在 `opacity:0`
- **现象**：`#p-inspire`、`#p-console`（以及宿主态的 `#p-drafts`）盒高 >0、文本在位，但 `opacity:0`、`animation: fadeIn` `currentTime=0 / running`，空闲 4 秒不收敛；中栏截图空白。诊断强制 `animation:none; opacity:1` 后面板完整渲染（媒体记忆栏、目标平台、6/8 子页签均在）。
- **实测**：`getAnimations()` → `{name:'fadeIn', playState:'running', duration:200, currentTime:0, fill:'none'}`；computed `transform: translateY(4px)`（动画 from 帧）。
- **归属候选**：
  - `harness-collect.js` / `harness-settings.js`（D）：`mountPanel` 把已带 `.on`（动画已在原隐藏位置起跑）的面板迁入可见槽，DOM 迁移导致动画冻结；挂载后未强制重排/清动画/固化 opacity。
  - `harness-thread.js` / `harness-core.js`（B/A）：面板迁入/归还时序，迁入后未清除残留动画终态。
  - `web/templates/index.html`（template，主协调者所有）：`.panel.on{display:block; animation:fadeIn .2s ease}` 既有规则；外壳作用域下可能需要在迁入后覆写 `animation:none` 或补 `opacity:1`。
- **复验要点**：collect/settings 进入后中栏面板直接可见，无需等待/强制样式；inspire 6、console 8 子页签截图中栏有内容。

### F-2 【中 · 状态不同步】内容页外壳头 pill / meta chip 保存状态镜像后不刷新
- **现象**：业务 `#wb-save-status` 已为「✓ 已与服务器同步」，外壳 `#hxThreadHead .hx-state-pill` 与 meta chip 仍停在「⚡ 载入中…」；`HX.refresh()` 后外壳才同步。选稿后复现（t+0.6s 与 t+3.1s 均未收敛）。
- **归属**：`harness-thread.js`（B）`renderContentHead` / `contentMetaHtml` 在渲染时一次性读取 `#wb-save-status` 文本，缺少对该节点的 MutationObserver 或选稿/状态回调后重读。「载入中…」文案源为模板内联 `updateSaveStatus()`（index.html:17917 / 19183），外壳只是镜像了过期快照。
- **复验要点**：选中草稿待业务同步完成后，外壳 pill/chip 跟随变为「✓ 已与服务器同步」，不再残留「载入中…」。

### F-3 【轻 · 高亮不同步】更多页打开后 rail/topbar 高亮未跟随
- **现象**：`HX.openMorePage('dashboard'|'studio'|'pricing'|'profile')` 面板可见，但左栏/顶栏高亮仍停留在前一工作区。
- **归属候选**：`harness-core.js`（A）路由 / `harness-rail.js`（A）高亮刷新。
- **复验要点**：进入更多页时对应入口（或中性态）高亮正确，返回四工作区后高亮复位。

### F-4 【观察 · 未覆盖路径】浏览器内嵌阅读路径本轮无真实样本
- 57 篇草稿 `source_url` 全为空，无法实测「有来源链接 → 内嵌阅读 / 禁嵌域名 → 外部打开」的运行时链路；仅完成代码核验（stage.js iframe sandbox/no-referrer/懒加载/外部打开按钮在位）与无来源空态实测。待采集库产生带源草稿后补验。

### F-5 【既有非回归】`renderSettingsData()` 偶发空节点写值
- 模板内联既有问题，legacy 下同样可能出现；本轮 harness/legacy/v2 均 0 报错、未复现，不计入外壳回归。

### F-6 【观察 · 状态残留】工作区切换后中栏头可能残留上一稿标题
- 一次观测：从内容页切到任务页，中栏头仍显示上一稿标题与「待审」；重载后复位。复现条件未稳定确认。归属候选：`harness-thread.js`（B）/ `harness-core.js`（A）切换时的头状态清理。

---

## 5. 本轮未覆盖与边界

- 未主动触发保存/发布/改写等写操作（只读验收）；保存按钮仅核验节点与事件委托在位。
- 浏览器内嵌/禁嵌降级运行时样本缺失（F-4）。
- F-1 根因未在本轮深挖到具体代码行，归属为候选，最终定责由主协调者裁定。
- 未修改任何业务代码/模板，未 commit，未改版本号，未重启服务。

## 6. 复现步骤

1. 仓库根 `python3 scripts/harness_ui_verify.py` 复跑门禁，JSON 写入 `design/harness-verify-results/`。
2. 浏览器导航 `?ui=harness&cb=<时间戳>`，先清缓存；CDP 模拟 1440×900 DPR=1；探针走 `Runtime.evaluate`。
3. 四工作区 `HX.openWorkspace(...)`、更多页 `HX.openMorePage(...)`、子页签 `switchSubTab(...)`，按 §3 矩阵核对盒高/opacity/文本与 API。
4. 回归 `?legacy=1`、`?ui=v2`；900px 宽验窄屏回落。
