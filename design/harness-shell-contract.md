# Harness 外壳重建 · 架构契约（唯一基准）

> 本文件由主协调者冻结。所有参与并行开发的 Agent 必须严格遵守本契约。契约变更只能由主协调者修改。

## 0. 唯一视觉/交互基准

`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-workspace-preview.html`（3245 行，原型）。

- 结构：顶栏（深色 44–46px）→ `.app` 三列网格 `--railw:248px / 1fr / --stagew:404px`。
- 三栏：左 `.rail`（任务中心，含 brand / 搜索 / 主导航 / 4 个 workspace context / 额度卡 / 账号行）；中 `.thread`（任务页 = thread-head + thread-meta + 对话 + composer；内容页 = 编辑器；采集页 = 采集面板；设置页 = 设置分节）；右 `.stage`（stage-head + 三页签 资产/浏览器/预览 + stage-body）。
- Design token（必须原样取用）：`--accent:#ef6432; --accent-deep:#d84a1b; --accent-soft:#fff1ea; --ink:#20242b; --ink-2:#575e6b; --line:#e7e9ee; --bg:#edeff3; --panel:#fff; --rail:#fbfbfc; --stage:#f7f8fa; --green:#268468; --amber:#b97716; --blue:#3768cf; --radius:14px;` 顶栏深色 `#1d2026` 系。
- 任何尺寸/间距/字号拿不准，直接去原型对应选择器抄，不要自创“紧凑版”。

## 1. 布局硬原则（解决“嵌套四栏挤压”）

- Harness 下 **body 自身成为三列 + 顶栏的 grid 容器**：`grid-template-columns: 248px minmax(0,1fr) 404px; grid-template-rows: 46px minmax(0,1fr);`
  行1 = 顶栏跨三列；行2 三列 = 左/中/右。
- 用 `grid-area` 把既有真实节点摆放进去，**优先 CSS 定位，不做大幅 DOM 重挂载**：
  - 左栏 = 既有 `<aside class="side">`（保留其 `.nav-item[data-p]` 真实导航点击链路，只重排样式 + 在内部插入 brand/搜索/context/额度/账号）。
  - 中栏 = 既有 `.main-wrapper`（隐藏其旧 `<header>`，把 `main` 里的业务面板 `#p-<key>` 重排为原型中栏）。
  - 右栏 = 既有 `<aside class="assets" id="assetsPanel">`（保留 workbench-shell.js 的真实资产接口与 `#assetsTabs` / `#assetsBody`）。
- 禁止：在既有三栏之外再造一层三栏容器；禁止 iframe 承载业务；禁止复制一份假 DOM 假装是真实页面。

## 2. 文件所有权（互斥，禁止越界写别人的文件）

| 文件 | 负责人 | 职责 |
|---|---|---|
| `web/static/css/harness-ui.css` | A 外壳底座 | token、body grid、顶栏、左栏、壳层通用组件、隔离规则、中/右栏框架占位 |
| `web/static/js/harness-core.js` | A 外壳底座 | `window.HX` 命名空间、状态、路由、注册表、boot、持久化、风格切换、键盘 |
| `web/static/js/harness-rail.js` | A 外壳底座 | 左栏渲染 + 4 个 workspace 的 rail context 兜底实现（任务/内容由本文件给出基础版） |
| `web/static/css/harness-thread.css` | B 中栏任务 | 中栏框架、thread-head/meta、消息流、计划卡、composer、内容/采集/设置中栏容器 |
| `web/static/js/harness-thread.js` | B 中栏任务 | `HX.registerThread` 的 4 个 workspace 实现（任务页最重） |
| `web/static/css/harness-stage.css` | C 右栏舞台 | stage-head、三页签、资产/浏览器/预览 pane、空态 |
| `web/static/js/harness-stage.js` | C 右栏舞台 | stage host + 三 pane 真实数据绑定 |
| `web/static/js/harness-collect.js` | D 采集与设置 | 采集页 rail context + 中栏重排 + 采集分析页签注册 |
| `web/static/css/harness-collect.css` | D 采集与设置 | 上述样式 |
| `web/static/js/harness-settings.js` | D 采集与设置 | 设置页 rail context + 中栏重排 + 配置检查页签注册 |
| `web/static/css/harness-settings.css` | D 采集与设置 | 上述样式 |
| `web/templates/index.html` | **仅主协调者** | 资源引用、挂载点。任何人不得编辑。 |
| `web/static/js/workbench-shell.js` | 无人（只读） | 必须继续兼容，不得修改，不得破坏 `getAttribute('data-shell') !== 'v2'` 字符串契约。 |

脚本按以下顺序同步加载（主协调者已写入模板）：core → rail → thread → stage → collect → settings。core 在 `DOMContentLoaded` 才 boot，因此 boot 时全部注册已完成。

## 3. 挂载点（core 创建，ID 固定，其他模块只读）

```
#hxTopbar     顶栏容器（core 建）
#hxRail       左栏根（core 建，包住 aside.side）
  #hxRailCtx     workspace context 插槽（rail 模块写入）
#hxThread     中栏根
  #hxThreadHead    中栏头插槽（thread 模块写入）
  #hxThreadBody    中栏体插槽（真实业务面板落在这里或由 grid 摆放）
#hxStage      右栏根
  #hxStageTabs     页签条（stage 模块写入）
  #hxStageBody     pane 容器（stage 模块写入）
```

## 4. `window.HX` API（core 提供，其他模块只依赖这一层）

```js
HX.state      // { workspace, page, draftId, topicId, stageTab:'assets', stageOpen, railMini, drafts:[], status:{} }
HX.ready      // Promise，boot 完成后 resolve
HX.on(evt, fn)        // 'ready' | 'workspace' | 'state' | 'drafts' | 'draft' | 'stage'
HX.off(evt, fn)
HX.esc(s) / HX.trim(s,n) / HX.fmtTime(v) / HX.ico(name, cls)   // 图标使用原型内联 svg symbol（core 注入 sprite）
HX.api(path, opts)    // fetch → json，失败返回 null 并 toast，绝不抛出
HX.toast(msg)
HX.openWorkspace(key) // 'tasks'|'content'|'collect'|'settings'
HX.openDraft(id)      // 通过点击 #draft-list-container 内真实卡片或业务函数切换，不复制业务逻辑
HX.newTask(text)      // 触发真实新建链路（优先点 #draft-list-container 上方新建按钮/全局函数）
HX.refresh()          // 重取 /api/status 并广播 'drafts'/'state'
HX.setStageTab(tab) / HX.toggleStage() / HX.toggleRail()
HX.registerRailCtx(ws, fn(slotEl, ctx))
HX.registerThread(ws, { head(el, ctx), body(el, ctx), refresh(ctx) })
HX.registerStageTab(ws, { key, title, count(ctx), mount(paneEl, ctx), refresh(paneEl, ctx) })
```

- `ctx = { state, status, drafts, draft, topic, data }`，`data` 为已拉取的真实数据缓存。
- 未注册的 workspace 必须由 core/rail/thread/stage 给出安全兜底（不白屏、不报错）。
- workspace → 真实页面映射（固定）：`tasks → switchToPage('lite')`、`content → 'drafts'`、`collect → 'inspire'`、`settings → 'console'`。
- 其他真实页（dashboard / studio / pricing / profile）在左栏“更多”分组中保留直达入口，Harness 下不得消失。

## 5. 真实数据接口（只读优先；不得编造数据）

`/api/status`（能力/模型/话题/草稿概况）、`/api/drafts/{id}/raw/{plat}`、`/api/drafts/{id}/history`、`/api/drafts/{id}/images`、`/api/drafts/{id}/video/tasks`、`/api/assets/library`、`/api/tasks`。
草稿清单：`#draft-list-container .draft-card`（真实 DOM，选中态由此读取）。
进度/执行计划：必须由真实任务状态（`/api/tasks`、草稿历史、生成状态）推导，**不得写死“已完成 5/5”**。

## 6. 隔离与编码规则

- 所有 CSS 选择器必须以 `body[data-shell="harness"]` 开头（可再叠加 `html[data-ui-shell="harness"]`）；新增 class 统一 `hx-` 前缀。
- 严禁写裸选择器，严禁改动 `.side` / `.main-wrapper` / `.assets` 在 classic、v2 下的既有样式（只在 harness 作用域内覆盖）。
- 纯 ES5 + IIFE，无构建步骤；`node --check` 必须通过。
- 每个模块启动即判 `document.body.getAttribute('data-shell') !== 'harness'` → 直接 return，零副作用。
- 任一模块异常不得阻断业务：所有对外调用包 try/catch，失败只 toast。
- 真实业务函数（`switchToPage` / `newLiteDraft` / `selectDraft` / `switchSubTab` / `toggleCmdK`）可直接调 `window.<fn>`；**不得** eval 模板内联作用域里的 `let/const` 变量。

## 7. 验收（1440×900 宽屏，`?ui=harness`）

1. 46px 深色顶栏 + 248px 左栏 + 弹性中栏 + 404px 右栏，无嵌套四栏。
2. 任务页：面包屑/标题/状态/操作/模型·引用·平台元信息 + 真实对话 + 真实进度/计划 + 输入区；右栏真实成稿/图片/视频/数据。
3. 内容页：草稿箱在左栏，中栏真实编辑器，右栏预览；选中草稿三栏联动；保存/发布链路不丢。
4. 采集页/设置页按原型重排；原型有而系统没有的项标「未接入」，不得伪造开关。
5. 右栏 资产/浏览器/预览 三页签；资产接真实数据；预览用真实排版渲染；浏览器先内嵌阅读，禁 iframe 时「外部打开」。
6. classic / v2 行为不变；Harness 宽屏默认、窄屏回落 classic。
7. 逐页核验一级页与二级页；`node --check` + 相关 pytest 通过；给出截图与可复现结论。
