# Harness 第三套外壳 · 第二轮修复 独立只读验收报告（round2 / round2b 复验）

- 验收时间：2026-11-24（CST, UTC+8）；round2b 定向复验同日完成
- 验收方：独立只读验收 Agent。**未修改任何业务文件 / 模板 / 脚本；未 commit；未重启 `127.0.0.1:8790` 服务；未写库。**
- 被测对象：`http://127.0.0.1:8790/?ui=harness&cb=<时间戳>`；回归对照 `?legacy=1`、`?ui=v2`
- 取证工具：项目 `.venv` Playwright headless Chromium，`deviceScaleFactor=1`，视口 1440×900 / 1231×761 / 1024×900 / 974×900
- 原始测量 JSON：`design/harness-verify-results/verify-round2.json`（round2 全矩阵）、`verify-round2b.json`（round2b 定向复验）、`verify-round2c.json`（round2c 定向复验）
- 截图目录：`design/harness-shots/`（`verify2-*.png` 47 张；`verify2b-*.png` 5 张；`verify3-*.png` 16 张）
- 上一轮报告：`design/harness-verify-final7.md`

---

## 一、总体判定（round2b 终判）：**通过**

> 判定口径：round2 全矩阵门禁通过后，round2b 对 A 方五组修复（sprite 图标渲染 / 顶栏余额 / 任务胶囊 / 迷你态品牌挤压 / 对比度 token）做了定向复验，并对溢出、网格、hx 节点三项零回归重测。结果：五组修复全部独立证实生效，零回归成立，阻断性缺陷 **0**。

本轮四片修复（Logo 恢复 / 双主题解除浅色锁定 / 逐页完善 / 模块接线）的**核心门禁全部实测通过**：零横向溢出、三列网格与迷你态尺寸正确、真实 Logo 加载、主题即时切换且刷新持久化、system 跟随、Classic 与 V11 零 hx 节点、21 个二级页签全部可达、更多页↔工作区往返无骨架互踩、真实数据一致。

**遗留说明（非阻断）**：D-1、D-2 浅色对比度已达辅助线 4.5:1；D-3 激活项文字 6.43:1，高于辅助线 4.5:1 但未达正文 7:1 目标线（按「选中标签」口径可判通过，若设计坚持 7:1 需再加深 token，详见第三节 D-3）。**round2c 复验后 D-6（矩阵工作空间裸「—」）已修复闭合**；D-5 为既有观察项，维持原状未闭合；B-1～B-6 为既有业务边界。

### 1.0 round2b 定向复验结论速览

| 复验组 | 判定 | 实测摘要（独立取证，非采信自测） |
|---|---|---|
| ① Sprite 图标像素渲染 | ✅ 生效 | 浅色 25/26、深色 25/26 枚采样到非背景描边像素；唯一未采样到的是 0 任务隐藏胶囊内的 chart 图标（零尺寸，属预期）。顶栏/左栏/迷你态截图描边可见 |
| ② 顶栏余额取值 | ✅ 生效 | 1440 浅/深、1024 浅/深共 4 组，500/600/1000/1500/2500ms 时序均为 `6,336,957`，无回落「—」；晚到兜底链路（导航节点→billing 缓存→总额-已用→大盘节点 + MutationObserver + 1.5s 复核）代码路径核对一致 |
| ③ 任务胶囊 0 态隐藏 | ✅ 生效 | `/api/tasks`=0 时胶囊 `display:none`、`<b>=0`、`has=false`；有任务显示路径（非 done/success/failed/cancelled/completed 过滤 → 显示 flex + 徽标计数）代码链路完整，未造持久化假数据 |
| ④ 迷你态品牌挤压 | ✅ 生效 | 68px 下 Logo 28px 居中（left 20）；品牌文本/副行/徽标/标题/折叠钮/菜单标签/额度卡/账号主行/齿轮/搜索框共 11 类节点 `display:none`；左栏内越界元素 **0**，`scrollWidth=67 ≤ 68` |
| ⑤ 对比度 token | ✅ 生效（附 D-3 口径说明） | 浅色 D-1 **5.04**、D-2 **5.21**、D-3 **6.43**；深色 D-1 5.63、D-2 5.46、D-3 8.51，未变差 |
| 零回归 · 横向溢出 | ✅ | 1440/1231/1024 × light/dark 共 6 组 harness 用例 `scrollWidth−clientWidth=0` |
| 零回归 · 网格宽度 | ✅ | rail 248 / thread 弹性（1440 788、1231 579、1024 372）/ stage 404 |
| 零回归 · hx 节点 | ✅ | classic 浅/深、v2 浅/深 hx 节点数均 **0** |
| 零回归 · 脚本与控制台 | ✅ | 6 个 harness JS `node --check` 全部 OK；round2b 16 个用例 **0 pageerror** |

### 1.1 门禁结论速览

| 门禁项 | 判定 | 实测摘要 |
|---|---|---|
| 文档级零横向溢出（1440/1231/1024） | ✅ 通过 | 24 个工作区 + 8 个更多页用例，`scrollWidth − clientWidth = 0` 全部成立 |
| 三列网格 248 / 弹性 / 404（迷你 68） | ✅ 通过 | 常态 rail 248、stage 404；迷你 rail 68；无第四列；线程右缘与舞台左缘重叠 0px（1036 = 1036） |
| 真实 Logo 恢复 | ✅ 通过 | 顶栏 22px、左栏 32px、迷你 28px，`naturalWidth=256`；占位类 `hx-tb-mark` / `hx-brand-mark` 计数 0 |
| 双主题解除浅色锁定 | ✅ 通过 | `light/dark/system` 三态均由 `localStorage['yimu_ui_theme_mode']` 驱动；`<html data-theme data-theme-mode>` 同步；顶栏「外观」按钮调用既有 `cycleThemeMode()` |
| 主题刷新持久化 | ✅ 通过 | 干净流程复测：system→light→dark，刷新后保持 dark；无 harness 新增主题键 |
| 深色可读性 | ✅ 通过（外壳层） | 深色最低辅助文字 5.46:1，主文字 ≥13.16:1；未见「白底大字」「灰字压深底」 |
| Classic / V11 零回归 | ✅ 通过 | 两种主题下 hx 节点数均为 **0**，主题行为与原站一致 |
| 窄屏 <1024 回落 classic | ✅ 通过 | 974×900 回落 `body[data-shell="classic"]`，hx 节点 0，未挂载 harness 槽位 |
| 真实数据 | ✅ 通过 | 成稿 57、话题 200、任务 0（空态「暂无执行计划」）；未发现写死假进度/假开关 |
| 跨模块互踩（A 清扫 ↔ B 骨架回填） | ✅ 通过 | 4 个更多页停留 3s 后往返 tasks/content，无重复骨架、无空白中栏、无循环卡顿；0 pageerror |
| JS 语法检查 | ✅ 通过 | 6 个 harness JS `node --check` 全部 OK |

### 1.2 与上一轮遗留问题的复核

| 上一轮遗留 | 本轮复测结论 |
|---|---|
| F-上① 页签记忆跨工区串值（stage.js 全局回退） | ✅ **已修复**：tasks 切到「浏览器」→ 回 content 默认回到「资产」、collect「采集分析」、settings「配置检查」，未串值 |
| F-上② 引导卡冷启动竞态（thread.js renderGuide 时机） | ✅ **已恢复**：全新存储冷启动 1.8s 内 `.hx-guide` 引导卡完整落地（头像/标题/文案/3 个 chip）；往返后仍在 |

---

## 二、逐页结论表

### 2.1 四个工作区（1440 / 1231 / 1024 × light / dark 全量实测）

| 页面 | 顶栏 Logo / 选中态 | 左栏上下文与计数 | 中栏标题与操作 | 右栏页签默认 / 切换 | 空态 / 弹窗 / 溢出 / 截断 / 可点 / 遮挡 / 四栏 | 结论 | 证据 |
|---|---|---|---|---|---|---|---|
| 任务 tasks | Logo 22px 加载；顶栏「任务」选中态正确 | 任务 / 内容 57 / 采集 200 / 设置；最近任务条目正常 | 标题「新创作任务」；执行计划卡 + 引导卡 + 建议 chip + 输入框可点 | 默认「资产 144」；浏览器 / 预览切换正常，空态文案就位 | 空态「暂无执行计划：…」；账单弹窗 `#m-billing` 正常打开；溢出 0；标题省略号生效；无遮挡；仅三列 + 顶栏 | ✅ 通过 | `verify2-{light,dark}-1440-tasks.png`、`-1231-tasks.png`、`-1024-tasks.png` |
| 内容 content | Logo 正常；「内容工作台」选中 | 草稿箱全部 **57**；条目评分/状态/缩略字正常 | 未选稿：「请在左侧草稿箱中选择一篇内容」；选稿后标题/署名/已同步徽标 + 编辑器双栏正常 | 默认「资产 144」；浏览器/预览可切换 | 未选稿空态正确；选稿后 `.hx-editor-wrap` 承载真实编辑器；溢出 0；无遮挡 | ✅ 通过 | `verify2-{light,dark}-1440-content.png`、`-1440-content-selected.png`、`-1024-content.png` |
| 采集 collect | Logo 正常；「采集工作台」选中，计数 200 | 采集记录 全部 200 / 待拆解 199 / 已入库 0 | 一句话成爆款 / 媒体署名记忆卡 / 平台勾选 / 风格下拉均在 | 默认「采集分析 200」；原文 / 爆款基因 / 素材三签可切 | 话题原文未入库降级空态正确；溢出 0；无遮挡 | ✅ 通过 | `verify2-{light,dark}-1440-collect.png`、`-1231-collect.png`、`-1024-collect.png` |
| 设置 settings | Logo 正常；「系统设置」选中 | 设置导航 6 组 + 4 个额外入口；接入/未接入圆点区分 | 中栏按分组渲染；未接入组仅出占位说明，无假控件/假开关 | 默认「配置检查」；33 项检查、1/3 能力线可用 | 发布账号 / 外观与快捷键两组「未接入」占位文案完整；溢出 0；无遮挡 | ✅ 通过 | `verify2-{light,dark}-1440-settings.png`、`-1231-settings.png`、`-1024-settings.png` |

### 2.2 更多页（light / dark × 1440）

| 页面 | 顶栏 / 左栏选中 | 中栏内容 | 右栏 | 结论 | 证据 |
|---|---|---|---|---|---|
| 操盘大屏 dashboard | Logo 正常；左栏「操盘大屏」选中 | 热点雷达 200 条 / 成稿 57 篇 / 12 支；趋势图、平台矩阵、品类环比、热榜流水均为业务真实面板 | 资产 144 / 浏览器 / 预览 | ✅ 通过 | `verify2-{light,dark}-1440-dashboard.png` |
| 影音工坊 studio | Logo 正常；左栏「影音工坊」选中 | 7 个影音二级页签 + 8 步流水线 + 未接入视频模型提示条 + 真实表单 | 资产 144 / 浏览器 / 预览 | ✅ 通过 | `verify2-{light,dark}-1440-studio.png`、`verify2-light-1440-studio-subs.png` |
| 套餐与价格 pricing | Logo 正常；左栏「套餐与价格」选中 | 邀请返佣条 / 算力中枢 / 五步下单流 / 卡密核销；套餐卡片为异步加载占位（既有边界） | 资产 144 / 浏览器 / 预览 | ✅ 通过（占位属已知边界） | `verify2-{light,dark}-1440-pricing.png` |
| 个人中心 profile | Logo 正常；左栏「个人中心」选中 | 已登录·管理员·Studio；媒体档案 / 账号画像 / Key 进阶 / 外观排版组真实渲染 | 资产 144 / 浏览器 / 预览 | ✅ 通过 | `verify2-{light,dark}-1440-profile.png` |

### 2.3 二级页签逐一点开（浅色 1440，共 21 个）

| 父级 | 页签 | `.sub-tab.on` 匹配 | 视图可见 | 视图有真实文本 | 结论 |
|---|---|---|---|---|---|
| 采集 inspire（6） | sp-oneshot 一句话成爆款 | ✅ | ✅ | ✅ | ✅ |
|  | sp-extract 万能爆款链接采集 | ✅ | ✅ | ✅ | ✅ |
|  | sp-hot 实时热榜抓取 | ✅ | ✅ | ✅ | ✅ |
|  | sp-search 爆款搜索仿写 | ✅ | ✅ | ✅ | ✅ |
|  | sp-paste 粘贴文案改编 | ✅ | ✅ | ✅ | ✅ |
|  | sp-batch 批量矩阵生产 | ✅ | ✅ | ✅ | ✅ |
| 控制台 console（8） | sp-ticket 每日工单自动化 | ✅ | ✅ | ✅ | ✅ |
|  | sp-agent-config Agent 配置 | ✅ | ✅ | ✅ | ✅ |
|  | sp-skills 技能库 | ✅ | ✅ | ✅ | ✅ |
|  | sp-health 服务健康自检 | ✅ | ✅ | ✅ | ✅ |
|  | sp-settings 系统与 API 配置 | ✅ | ✅ | ✅ | ✅ |
|  | sp-user-admin 用户与会员管理 | ✅ | ✅ | ✅ | ✅ |
|  | sp-gateway API 网关服务 | ✅ | ✅ | ✅ | ✅ |
|  | sp-video-config 视频合成配置 | ✅ | ✅ | ✅ | ✅ |
| 影音 studio（7） | sp-drama 全自动 AI 短剧 | ✅ | ✅ | ✅ | ✅ |
|  | sp-video 快速短视频合成 | ✅ | ✅ | ✅ | ✅ |
|  | sp-aivideo AI 短视频生成 | ✅ | ✅ | ✅ | ✅ |
|  | sp-storyboard 电影级分镜脚本 | ✅ | ✅ | ✅ | ✅ |
|  | sp-audio AI 口播配音 TTS | ✅ | ✅ | ✅ | ✅ |
|  | sp-video-tasks 成片资产资料库 | ✅ | ✅ | ✅ | ✅ |
|  | sp-advideo AI 产品广告短片 | ✅ | ✅ | ✅ | ✅ |

证据：`verify2-light-1440-inspire-subs.png`、`verify2-light-1440-console-subs.png`、`verify2-light-1440-studio-subs.png`；明细见 JSON `subtabs` 用例。

### 2.4 主题 × 视口矩阵

| 主题 | 视口 | 工作区 | 溢出 | 列宽实测 | Logo | 结论 |
|---|---|---|---|---|---|---|
| light | 1440×900 | tasks / content / collect / settings | 0 | 248 / 弹性 / 404 | 顶 22、栏 32 | ✅ |
| dark | 1440×900 | 同上 | 0 | 248 / 弹性 / 404 | 顶 22、栏 32 | ✅ |
| light | 1231×761 | 同上 | 0 | 248 / 弹性 / 404 | ✅ | ✅ |
| dark | 1231×761 | 同上 | 0 | 248 / 弹性 / 404 | ✅ | ✅ |
| light | 1024×900 | 同上 | 0 | 248 / 弹性 / 404 | ✅ | ✅ |
| dark | 1024×900 | 同上 | 0 | 248 / 弹性 / 404 | ✅ | ✅ |
| light | 974×900 | 回落 classic | 0 | — | harness Logo 槽位未挂载 | ✅ 回落正确 |
| dark | 974×900 | 回落 classic | 0 | — | 同上 | ✅ 回落正确 |

### 2.5 system 模式跟随

| 步骤 | 实测 `data-theme` | `data-theme-mode` | 结论 |
|---|---|---|---|
| 存 `system`，emulate light | light | system | ✅ 跟随浅色 |
| 切 emulate dark | dark | system | ✅ 跟随深色 |
| 刷新（dark 仿真环境） | dark | system | ✅ 持久化且继续跟随 |

### 2.6 跨模块互踩专项（A 的 MutationObserver 清扫 ↔ B 的骨架晚到回填）

往返序列：dashboard / studio / pricing / profile 各停留 **3 秒** → 切回 tasks → 切回 content，共 4 轮。

| 观测点 | 实测 |
|---|---|
| 更多页停留 3s 后中栏子树 | 单一面板挂载，无重复骨架 |
| 切回 tasks | 中栏仅 `hx-tasks-root` 一个子树，无残留骨架/空白 |
| 切回 content | 中栏为业务面板 + `hx-editor-wrap`，无重复编辑器骨架 |
| 控制台 | 0 pageerror、0 新增 warning |
| 循环卡顿 / 观察器死循环 | 未观测到 |

**未发现某一 Agent 的修复覆盖另一 Agent 的冲突。**

---

## 三、缺陷清单（按严重度排序）

> 严重度：中 = 违反门禁但不阻断主流程；轻 = 低于目标线但可读；观察 = 既有现象或数据/环境限制。

### D-1【中 → ✅ round2b 已修复】浅色主题：左栏品牌副行辅助文字对比度不足 2.99:1（阈值 4.5:1）

- **原现象**：浅色下左栏 Logo 下方副行「全媒体创作工作台 · V15.9.13」灰字压纸面，round2 实测 **2.99:1**，低于辅助文字 4.5:1 门禁；深色同位置 5.63:1 达标。
- **位置**：`web/static/css/harness-ui.css:289`（`.hx-brand-sub` 用 `--hx-ink-3`）；token 定义 `harness-ui.css:21`（浅色 `--hx-ink-3` 已由 `#8c939f` 改为 `#666d79`，纸面 `--hx-rail: #fbfbfc`）。
- **round2b 复验实测**：浅色前景 `rgb(102,109,121)` / 背景 `rgb(251,251,252)`，对比度 **5.04:1**（≥4.5 ✅）；深色同位置 5.63:1，未变差。证据 `verify2b-light-1440-icons.png`、JSON `contrast` 用例「左栏副行」。
- **结论**：**已修复**，辅助线达标。

### D-2【中 → ✅ round2b 已修复】浅色主题：任务空态备注辅助文字对比度不足 3.09:1（阈值 4.5:1）

- **原现象**：任务页「暂无执行计划：新建任务后，Agent 的拆解、检索与生成步骤会自动记录在这里。」round2 实测 **3.09:1**，低于辅助线；深色 5.46:1 达标。
- **位置**：`web/static/css/harness-thread.css:483-488`（`.hx-plan-empty-note` 用 `--hx-ink-3`，背景 `#ffffff`）。
- **round2b 复验实测**：浅色前景 `rgb(102,109,121)` / 背景 `rgb(255,255,255)`，对比度 **5.21:1**（≥4.5 ✅）；深色 5.46:1，未变差。证据 JSON `contrast` 用例「空态备注」。
- **结论**：**已修复**，辅助线达标。

### D-3【轻 → ⚠️ round2b 部分闭合：辅助线达标，正文 7:1 目标线未达】浅色主题：左栏激活项文字 5.19:1，未达正文 7:1 目标线

- **原现象**：激活菜单项文字 `--hx-accent-ink` 压 `--hx-accent-soft (#fff1ea)`，round2 实测 **5.19:1**；高于辅助 4.5:1，但未达正文 7:1 目标。深色同位置 8.51:1 达标。
- **位置**：`web/static/css/harness-ui.css:349`（激活项 background/color）；token `harness-ui.css:18`（浅色 `--hx-accent-ink` 已由 `#a94924` 改为 `#963c1b`，深色 `:68` `#ffa27f` 未动）。
- **round2b 复验实测**：浅色前景 `rgb(150,60,27)` / 背景 `rgb(255,241,234)`，对比度 **6.43:1**；深色前景 `rgb(255,162,127)` / 背景 `rgb(43,26,19)`，**8.51:1**，未变差。
- **口径判定**：
  - 按**辅助文字 4.5:1** 口径：6.43:1 ✅ 达标（激活态为选中标签，非长正文，可判通过）；
  - 按**正文 7:1** 目标线口径：6.43:1 ❌ 仍差 0.57，若设计侧坚持 7:1，需把 `--hx-accent-ink` 再加深或降低 `--hx-accent-soft` 明度。
- **结论**：**已解释 / 辅助线闭合**；是否需继续加深取决于设计口径，非阻断缺陷。

### D-4【观察 · 既有 → ✅ round2b 根因已解释并经像素采样复核】Harness Sprite `<use>` 图标在 headless 截图中未见描边像素

- **原现象**：左栏菜单图标、新建任务加号、顶栏状态图标等 `.icon` 引用 `#hx-i-*` sprite；round2 时 DOM 存在、`<use href>` 正确、计算样式正常，但 headless 元素截图内未采到描边像素；final7 基线同样缺失。
- **根因（round2b 证实）**：旧实现用 `createElement('svg')` 建容器，落入 XHTML 命名空间，导致内部 `<circle/>`/`<rect/>` 等形状非法嵌套、`<use>` 引用失效；这同时解释了顶栏/左栏/迷你态图标与「露色块」现象。现改为 `innerHTML` 注入（HTML 解析器自动归入 SVG 命名空间），42 枚图标表 `harness-core.js:803-849`，`search` 子节点为 `<circle>`、`<path>` 兄弟并列；注入逻辑 `harness-core.js:851-862`。
- **round2b 像素采样实测**（DPR=2，按非背景像素计数）：
  - 浅色 1440：25 枚 `painted=true`（search 252、bolt 167、chevron-down 66、panel 340、collapse-panel 340、plus 136、rail-search 252、tasks 352、file 380、globe 429、settings 400、grid 464、video 338、more-bolt 256、user 194、refresh 240、more×6 各 72、quota-bolt 165、profile-gear 333）；
  - 深色 1440：25 枚 `painted=true`（非背景像素 68～460，量级与浅色一致）；
  - 唯一 `painted=false`：顶栏任务胶囊内 `#hx-i-chart`，胶囊 0 态 `display:none`、图标零尺寸，属预期结果，非缺陷。
- **截图证据**：`verify2b-light-1440-icons.png`、`verify2b-dark-1440-icons.png`（顶栏搜索/账号/风格 sprite 图标 + 外观按钮 emoji 字形 🌓/☀️/🌙、左栏新建/搜索/4 导航/更多 4 项/额度/账号图标描边可见）；迷你态见 `verify2b-light-1440-mini.png`。外观按钮使用 emoji 字形而非 sprite，不在图标采样口径内。
- **结论**：**根因已解释，图标渲染缺陷闭合**；残留观察：真实 GUI 浏览器复核未在本环境执行（仅 headless Chromium），但本轮像素采样 + 截图双向取证已支持渲染生效结论。

### D-5【观察 · 既有】头像兜底图 `default-avatar.png` 与品牌图标 `logo-icon.png` 字节相同

- **现象**：两文件 MD5 均为 `d1ea914afffbac21f64dd68c840dc205`；账号无真实头像时，顶栏与底栏头像渲染的是品牌标而非中性默认头像。
- **位置**：静态资源 `web/static/img/default-avatar.png`、`web/static/img/logo-icon.png`；外壳引用链路 `harness-core.js`（`#hxTbAccount .hx-tb-avatar`、`#hxProfileAvatar` 回读 `#profile-user-avatar-img`）。
- **建议**：确认是有意的品牌化兜底还是资源误覆盖；若应为中性头像，替换 `default-avatar.png`，外壳代码引用关系无需改。

### D-6【观察 · 业务面板自身 → ✅ round2c 已修复】Dashboard「矩阵工作空间」空态残留孤立短横线

- **原现象**：操盘大屏「矩阵工作空间」卡片在无工作室空间时，描述上方出现一个孤立「—」短横，为业务面板自身空态骨架残留；非 harness 外壳重复骨架。
- **改动位置**：`web/templates/index.html` 计数位初始由「—」改为空；新增 `loadDashWorkspaceCount()`（`index.html:19648-19671`），优先 `window._allWorkspaces`，否则拉 `/api/workspaces`；有 N 个显示「N 个」并改写副行，0 个/失败/缺失时清空数字行并 `display:none`，副行保留「尚未创建工作空间」；卡片点击仍调 `openWorkspaceManageModal()`。
- **round2c 复验实测**（详见第七节）：
  - 真实分支（`/api/workspaces` 返回 1 个）：计数文本 **「1 个」**、`display:block`、副行 **「查看各矩阵号空间与技能配置」**，卡片文本无「—」；浅/深一致。
  - 空数组分支（route stub `{"workspaces":[]}`）：计数文本 **空**、`display:none`、副行 **「尚未创建工作空间」**，无裸破折号。
  - 接口 500 分支：同上，计数行隐藏、副行文案正确。
  - 模态框：点击卡片后 `#m-workspace-manage` 加 `on`、`display:flex`、列表 1 张（默认创作者工作室 `ws-default`），模态正常打开。
- **结论**：**已修复**。

---

## 四、实测数值汇总

### 4.1 横向溢出（`documentElement.scrollWidth − clientWidth`）

| 视口 | light | dark |
|---|---|---|
| 1440×900 | 0（4 工作区 + 4 更多页） | 0（同左） |
| 1231×761 | 0（4 工作区） | 0（4 工作区） |
| 1024×900 | 0（4 工作区） | 0（4 工作区） |
| 974×900 | 0（classic 回落） | 0（classic 回落） |

### 4.2 网格与 Logo 实测

| 项 | 常态 | 迷你态 | 判据 | 结论 |
|---|---|---|---|---|
| 左栏宽 `#hxRail` | 248px | 68px | 248 / 迷你 68 | ✅ |
| 中栏 `#hxThread` | 弹性（1440 下 788px） | 弹性 | 弹性 | ✅ |
| 右栏 `#hxStage` | 404px | 404px | 404 | ✅ |
| 顶栏 Logo `.hx-logo` | 22×22，naturalWidth 256 | 22×22 | ≥20px、naturalWidth>0 | ✅ |
| 左栏 Logo `.hx-brand-logo` | 32×32，naturalWidth 256 | 28×28 | ≥30 / 迷你 ≥24 | ✅ |
| 占位类 `.hx-tb-mark / .hx-brand-mark` | 0 | 0 | 0 | ✅ |
| 第四列 / 线程-舞台重叠 | 无第四列；重叠 0px（1036=1036） | — | 无第四列、无遮挡 | ✅ |
| 顶栏/底栏头像 | `default-avatar.png`，naturalWidth 256 | — | 非 Logo 冒充（见 D-5） | ✅（附观察） |

### 4.3 对比度实测（计算样式反推背景，WCAG 比值）

| 采样点 | 浅色比值 | 深色比值 | 阈值 | 浅色判定 |
|---|---|---|---|---|
| 顶栏主文字 `.hx-tb-name` | 16.32 | 19.05 | 主 ≥7 | ✅ |
| 顶栏徽标 `.hx-tb-badge` | 8.83 | 7.40 | 辅 ≥4.5 | ✅ |
| 左栏激活项 `.hx-menu-item.is-active .hx-menu-label` | ~~5.19~~ **6.43**（round2b） | 8.51 | 主 ≥7 / 辅 ≥4.5 | ✅ 辅线；⚠️ 未达 7:1（D-3） |
| 左栏副行 `.hx-brand-sub` | ~~2.99~~ **5.04**（round2b） | 5.63 | 辅 ≥4.5 | ✅ D-1 已修复 |
| 中栏标题 `#hxThreadHead h1` | 15.03 | 13.16 | 主 ≥7 | ✅ |
| 空态备注 `.hx-plan-empty-note` | ~~3.09~~ **5.21**（round2b） | 5.46 | 辅 ≥4.5 | ✅ D-2 已修复 |
| 右栏舞台 `#hxStageBody` | 14.65 | 15.18 | 主 ≥7 | ✅ |
| 输入框 `#hxThreadBody input/textarea` | 15.57–17.85 | 14.27–17.77 | 主 ≥7 | ✅ |
| 左栏条目标题 | 15.06 | 14.73 | 主 ≥7 | ✅ |

### 4.4 主题持久化与存储键

| 观测 | 实测 |
|---|---|
| 点「外观」即时切换 | `data-theme` / `data-theme-mode` 同步变化（light→dark） |
| 刷新持久化（干净流程，无 init 脚本覆写） | dark 刷新后保持 `dark/dark` ✅；system 刷新后保持 `system` 并跟随仿真配色 ✅ |
| 主题相关 localStorage 键 | 仅 `yimu_ui_theme_mode`；**未发现 harness 新增主题键**（`yimu.hx.workspace / railMini / stageOpen / stageTab` 为外壳状态键，非主题键） |

### 4.5 Classic / V11 回归（hx 节点数）

| 版本 | 参数 | 主题 | shell | hx 节点数 | 控制台 error | 结论 |
|---|---|---|---|---|---|---|
| Classic | `?legacy=1` | light | classic | **0** | 0 | ✅ |
| Classic | `?legacy=1` | dark | classic | **0** | 0 | ✅ |
| V11 | `?ui=v2` | light | v2 | **0** | 0 | ✅ |
| V11 | `?ui=v2` | dark | v2 | **0** | 0 | ✅ |

### 4.6 真实数据探针（接口直连 + 页面回读）

| 指标 | 实测 | 说明 |
|---|---|---|
| 成稿 / 草稿 | **57** | `/api/status` drafts 长度；左栏草稿箱计数 57 |
| 话题 | **200** | `/api/status` topics 长度；采集分析徽标 200 |
| 执行任务 | **0** | `/api/tasks` tasks 长度 0；中栏空态「暂无执行计划」 |
| 图片徽标 | 右栏「图片 144」（草稿 `imgs` 求和 144） | 验收口径记 141；本轮运行实测 144，属两轮间业务数据漂移，非写死值 |
| 数据徽标 | 57 | 与成稿一致 |
| 假进度 / 假开关 | 未发现 | 未接入组仅占位说明，无伪造控件 |

### 4.7 round2b 定向复验实测（修复后）

**顶栏余额时序（真实数字，非「—」）**

| 视口 | 主题 | 500/600ms | 1000ms | 1500ms | 2500ms | 判定 |
|---|---|---|---|---|---|---|
| 1440 | light | 6,336,957 | 6,336,957 | 6,336,957 | 6,336,957 | ✅ 未回落 |
| 1440 | dark | 6,336,957 | 6,336,957 | 6,336,957 | 6,336,957 | ✅ 未回落 |
| 1024 | light | 6,336,957（600ms） | — | 6,336,957 | 6,336,957 | ✅ 未回落 |
| 1024 | dark | 6,336,957（600ms） | — | 6,336,957 | 6,336,957 | ✅ 未回落 |

**任务胶囊（0 任务态，`/api/tasks`=0）**

| 项 | 实测 |
|---|---|
| `#hx-tb-tasks` 计算 `display` | `none` |
| 徽标 `<b>` 文本 | `0` |
| `has` 类 | `false` |
| 有任务显示路径（代码核对） | `state.tasks` 过滤 `status` 非 done/success/failed/cancelled/canceled/completed → `active>0` 时 `display=''`、徽标计数、`has` 置位；`refresh()` 回填 `/api/tasks` 后重入 `syncTopbarStatus()` |

**迷你态（68px rail）**

| 项 | 实测 |
|---|---|
| 左栏宽 / `scrollWidth` | 68px / 67px（零横向溢出） |
| Logo 宽 / naturalWidth | 28px / 256，left 20（栏内居中） |
| 隐藏节点（`display:none`） | `.hx-brand-text` `.hx-brand-line` `.hx-brand-title` `.hx-brand-badge` `.hx-brand-sub` `.hx-rail-collapse` `.hx-menu-label` `.hx-quota-card` `.hx-profile-main` `.hx-profile-gear` `.hx-rail-search` |
| 栏内越界元素（`right > rail.right`） | 0 |
| 可见元素 | 仅 28px Logo、新建任务加号钮、8 枚菜单/更多图标、底部头像；无品牌文字、无标签、无额度色块残留 |

**图标像素采样（DPR=2，非背景像素计数）**

| 主题 | 采样总数 | painted=true | 未采样到 |
|---|---|---|---|
| light 1440 | 26 | 25 | 胶囊内 `#hx-i-chart`（胶囊隐藏，零尺寸，预期） |
| dark 1440 | 26 | 25 | 同上 |

**零回归重测（round2b）**

| 项 | light | dark |
|---|---|---|
| 1440 溢出 / 列宽 | 0 / 248·788·404 | 0 / 248·788·404 |
| 1231 溢出 / 列宽 | 0 / 248·579·404 | 0 / 248·579·404 |
| 1024 溢出 / 列宽 | 0 / 248·372·404 | 0 / 248·372·404 |
| classic hx 节点 / 溢出 | 0 / 0 | 0 / 0 |
| v2 hx 节点 / 溢出 | 0 / 0 | 0 / 0 |
| 6 模块 `node --check` | 全部 OK | 全部 OK |
| 控制台 pageerror（16 用例） | 0 | 0 |

---

## 五、剩余边界（未接入项 / 接口缺口 / 无法验证项）

### 5.1 既有边界，本轮复核描述仍准确

| 编号 | 边界 | 本轮复核 |
|---|---|---|
| B-1 | `/api/drafts/{id}/video/tasks` 返回 **404**，视频任务线未接入 | ✅ 复测首篇草稿接口 404，描述准确 |
| B-2 | 57 篇草稿 `source_url` **全部为空**，浏览器内嵌面板无真实样本；禁 iframe 降级空态已验证 | ✅ 复测 `source_url` 空 57/57，描述准确 |
| B-3 | pricing 套餐卡片异步加载，首屏为「当前档位加载中 / 正在从定价中心加载套餐与权益…」占位 | ✅ 浅色/深色均复现占位，描述准确 |
| B-4 | 设置侧两组未接入：**发布账号**、**外观与快捷键**；仅渲染说明空态 | ✅ 占位文案与警告圆点正确，无假控件 |
| B-5 | `renderSettingsData()` 偶发空节点写值告警为模板既有问题（`?legacy=1` 同样复现） | 本轮 harness 用例未复现该告警；维持既有结论 |
| B-6 | 暗色下稿件预览画布保留白底（模拟发布效果） | ✅ 对比复测：legacy 深色同样为浅色预览画布，属原站既有行为，非 harness 回归 |

### 5.2 本轮无法在本环境确证的项

| 项 | 原因 |
|---|---|
| Sprite 图标在真实 GUI 浏览器的描边可见性 | round2b 已在 headless 做 DPR=2 像素采样 + 截图双向取证，25/26 枚描边像素成立（唯一缺失为隐藏胶囊内图标）；真实 GUI 浏览器复核仍未在本环境执行，作为低优先级残留观察 |
| 套餐卡片真实价格 / 权益渲染 | 定价中心异步数据本轮未返回卡片，仅验证占位链路 |
| iframe 内嵌原文阅读 | 受 B-2 所限无 `source_url` 样本 |
| 移动端 <1024 细化布局 | 按设计 <1024 整体回落 classic，harness 外壳不提供窄屏布局；974 回落已验证 |
| 编辑历史版本、消息推送等深层业务交互 | 不在本轮四片修复范围内，未做深链路压测 |

---

## 六、证据清单

### 6.1 截图（`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/`）

**四工作区 · 1440**
- `verify2-light-1440-tasks.png` / `verify2-dark-1440-tasks.png`
- `verify2-light-1440-content.png` / `verify2-dark-1440-content.png`
- `verify2-light-1440-collect.png` / `verify2-dark-1440-collect.png`
- `verify2-light-1440-settings.png` / `verify2-dark-1440-settings.png`

**四工作区 · 1024**
- `verify2-light-1024-{tasks,content,collect,settings}.png`
- `verify2-dark-1024-{tasks,content,collect,settings}.png`

**四工作区 · 1231（浅色）**
- `verify2-light-1231-{tasks,content,collect,settings}.png`

**更多页 · 1440**
- `verify2-light-1440-{dashboard,studio,pricing,profile}.png`
- `verify2-dark-1440-{dashboard,studio,pricing,profile}.png`

**二级页签**
- `verify2-light-1440-inspire-subs.png` / `verify2-light-1440-console-subs.png` / `verify2-light-1440-studio-subs.png`

**选稿编辑器（浅/深）**
- `verify2-light-1440-content-selected.png` / `verify2-dark-1440-content-selected.png`

**迷你态**
- `verify2-light-1440-mini-tasks.png` / `verify2-light-mini-rail-zoom.png` / `verify2-light-full-rail-zoom.png`

**回归与窄屏**
- `verify2-light-1440-classic.png` / `verify2-dark-1440-classic.png`
- `verify2-light-1440-v2.png` / `verify2-dark-1440-v2.png`
- `verify2-light-974-classic.png` / `verify2-dark-974-classic.png`

**对照 / 辅助**
- `verify2-dark-{harness,legacy,v2}-draft.png`（深色预览画布三外壳对照）
- `verify2-light-billing-modal.png`（账单弹窗）
- `verify2-light-settings-modal.png`（设置弹窗探针）
- `repro-use.png` / `repro-hidden.png` / `repro-zero.png` / `repro-cssstroke.png` / `repro-app-icon.png`（图标渲染隔离复现）
- `smoke-tasks.png` / `smoke-dark-{tasks,content,collect,settings}.png`（首轮冒烟）

**round2b 定向复验（`verify2b-*.png`）**
- `verify2b-light-1440-icons.png` / `verify2b-dark-1440-icons.png`（图标像素采样对照：顶栏搜索/外观/账号/风格 + 左栏新建/搜索/导航/更多/额度/账号）
- `verify2b-light-1024-balance.png` / `verify2b-dark-1024-balance.png`（1024 余额真实数字）
- `verify2b-light-1440-mini.png`（迷你态 68px，仅 Logo + 图标）

**round2c 定向复验（`verify3-*.png`）**
- 工作空间计数：`verify3-light-dash-real.png` / `verify3-dark-dash-real.png`（真实「1 个」）、`verify3-light-dash-empty.png`（空态隐藏数字行）、`verify3-light-workspace-modal.png`（管理中枢模态框）
- 引导卡五场景（浅/深各一）：`verify3-{theme}-s1-cold.png`（冷启动在卡）、`verify3-{theme}-s2-draft-memory.png`（草稿记忆刷新后仍在卡）、`verify3-{theme}-s3-real-bind.png`（真实绑稿撤卡）、`verify3-{theme}-s4-retained-refresh.png`（应用内刷新会话保留）、`verify3-{theme}-s5-newtask.png`（新任务回到冷启动）、`verify3-{theme}-s5-nav-retain.png`（跨页往返会话保留）；`theme ∈ {light, dark}`

### 6.2 原始测量数据

- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-verify-results/verify-round2.json`（round2 全部用例的 measure / contrast / sequence / subtab / conflict / probe 原始值）
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-verify-results/verify-round2b.json`（round2b 图标采样 / 余额时序 / 胶囊态 / 迷你态 / 回归原始值，16 用例）
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-verify-results/verify-round2c.json`（round2c 工作空间三分支 / 模态框 / 引导卡 7 类场景 / 回归原始值，28 用例）

### 6.3 验收报告

- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-verify-round2.md`（本文件）

---

## 七、round2c 定向复验记录（第 3、4 项，2026-11-24）

> 复验方式：只读取证，未改业务文件 / 模板 / 脚本，未 commit，未重启 `127.0.0.1:8790`（复用 pid 93201 实例）。探针口径：`.hx-guide` 节点数；`#copilot-chat-messages` 业务子节点（排除 `data-owner="thread"` 外壳节点）；真实消息（排除「对话已清空」占位气泡）；`/api/tasks` 中 `running/queued` 活动任务数。绑稿用稿 `dr-346633505c`（copilot_history 2 条）。

### 7.1 第 3 项：操盘大屏「矩阵工作空间」计数（对应 D-6）

改动：`index.html:19648-19671` `loadDashWorkspaceCount()`，优先 `window._allWorkspaces`，否则 `/api/workspaces`；有 N 个显示「N 个」并改写副行，0 个 / 失败 / 缺失时清空数字行并 `display:none`，副行保留「尚未创建工作空间」。

| 分支 | 计数文本 | 计数行 display | 副行文案 | 卡片含裸「—」 | 判定 |
|---|---|---|---|---|---|
| 真实接口（浅 / 深，返回 1 个） | `1 个` | `block` | 查看各矩阵号空间与技能配置 | 否 | ✅ |
| 空数组 stub（`{"workspaces":[]}`） | 空 | `none` | 尚未创建工作空间 | 否 | ✅ |
| 接口 500 reject | 空 | `none` | 尚未创建工作空间 | 否 | ✅ |
| 模态框（点击卡片 `openWorkspaceManageModal()`） | — | `#m-workspace-manage` 加 `on`、`display:flex`、可见，列表 1 张（默认创作者工作室 `ws-default`） | — | — | ✅ |

证据：`verify3-light-dash-real.png` / `verify3-dark-dash-real.png` / `verify3-light-dash-empty.png` / `verify3-light-workspace-modal.png`。

### 7.2 第 4 项：冷启动引导卡不再被草稿记忆抑制（五场景 × 浅/深）

撤卡口径（`harness-thread.js:546-548`）：对话区出现真实业务消息 **或** 存在 `running/queued` 真实任务；仅有草稿记忆、或只剩「对话已清空」占位气泡时不撤卡。下表数值格式为「浅色 / 深色」。

| # | 场景 | guide 节点 | 业务子节点 | 真实消息 | 活动任务 | 关键观测 | 判定 |
|---|---|---|---|---|---|---|---|
| S1 | 清 localStorage 冷启动直接进任务页 | 1 / 1 | 0 / 0 | 0 / 0 | 0 / 0 | 引导卡「一幕 Agent · 就绪」+ 3 条建议 chip 在场 | ✅ |
| S2 | 绑一篇草稿后回任务页，再浏览器刷新 | 1 / 1 | 0 / 0 | 0 / 0 | 0 / 0 | 刷新后无该稿残留内容；绑稿阶段 guide=0 系真实消息抑制，非 draftId 记忆抑制 | ✅ |
| S3 | 真实绑稿（`loadLiteDraftById` 路径） | 0 / 0 | 2 / 2 | 2 / 2 | 0 / 0 | 用户消息「写一段60字的清晨咖啡短句,小红书体」+ 助理成稿结果两条完整可见，未被引导卡覆盖 | ✅ |
| S4 | S3 后应用内刷新（`HX.refresh()`） | 0 / 0 | 2 / 2 | 2 / 2 | 0 / 0 | 会话保留，引导卡不回潮 | ✅ |
| S5a | `HX.newTask()` 后回到冷启动 | 1 / 1 | 0 / 0 | 0 / 0 | 0 / 0 | 新任务清空会话，引导卡重新在场 | ✅ |
| S5b | 真实会话存在时切内容页 → 采集页 → 回任务页 | 0 / 0 | 2 / 2 | 2 / 2 | 0 / 0 | 跨页往返会话保留，引导卡不回潮 | ✅ |

证据：`verify3-{light,dark}-s1-cold.png`、`-s2-draft-memory.png`、`-s3-real-bind.png`、`-s4-retained-refresh.png`、`-s5-newtask.png`、`-s5-nav-retain.png`。

### 7.3 边界观察（非本轮回归，不记为新缺陷）

- **整页刷新不保留 lite 会话（业务既有设计）**：S3 绑稿后做浏览器整页刷新，实测 guide=1、业务子节点 0；lite 模式每次载入由 `newLiteDraft(true)` 回到空白新稿（`index.html:14413-14420`、`16871-16876`），copilot 消息不跨刷新持久化。场景 4「刷新后不显示」按**应用内刷新**口径通过；若产品要求整页刷新后恢复上次会话，属新增需求，不在本轮改动范围。
- **活动任务撤卡分支未造数实测**：当前 `/api/tasks`=0，`running/queued` 计数 0；该分支（`hasActiveTask`，`thread.js:532-542`）仅做代码路径核对，未写入持久化假任务。
- 补卡缺陷复核：业务 innerHTML 清流摘掉引导卡后按「不在文档内」重建（`thread.js:596-607`）；撤卡后 MutationObserver 仍挂在聊天节点上保留监听（`thread.js:587-592`），代码路径与实测场景一致。

### 7.4 零回归重测（round2c）

| 项 | light | dark |
|---|---|---|
| 1440×900 溢出 / 列宽 | 0 / 248·788·404 | 0 / 248·788·404 |
| 1231×761 溢出 / 列宽 | 0 / 248·579·404 | 0 / 248·579·404 |
| 1024×900 溢出 / 列宽 | 0 / 248·372·404 | 0 / 248·372·404 |
| Classic（`?legacy=1`）hx 节点 / 溢出 | 0 / 0 | 0 / 0 |
| V11（`?ui=v2`）hx 节点 / 溢出 | 0 / 0 | 0 / 0 |
| 6 个 harness JS `node --check` | 全部 OK | 全部 OK |
| 浏览器 pageerror（28 用例） | 0 | 0 |

### 7.5 round2c 结论

- **第 3 项（D-6 矩阵工作空间裸「—」）：闭合。** 真实 / 空数组 / 接口失败三分支计数行与副行均正确，无裸破折号，模态框正常打开。
- **第 4 项（引导卡草稿记忆抑制）：闭合。** 五场景浅/深实测全部符合预期；两条补卡缺陷修复路径核对一致。
- **仍未闭合**：D-3（6.43:1，辅线达标、正文 7:1 口径待定）；D-5（头像与品牌图标字节相同，待业务确认）；B-1～B-6 既有业务边界。

## 八、round2d 独立全量复验记录（六组改动，2026-11-24）

> 复验方式：只读取证，未改业务文件 / 模板 / 脚本，未写库、未 commit，未重启 `127.0.0.1:8790`（复用既有监听实例）。Playwright headless Chromium，项目 `.venv`；探针在浏览器内回读真实 DOM / 接口，不采信自述。绑稿用稿 `dr-346633505c`（历史版本 3 条）。原始数据：`design/harness-verify-results/verify-round2d.json`（39 例，pageerror 0），分项 `verify-round2d-reg.json` / `-int.json` / `-fu.json` / `-fu2.json`。

### 8.1 最终判定

| # | 改动组 | 判定 | 关键实测 |
|---|---|---|---|
| A | 任务页页头动作委托 + 舞台切换同步 | ✅ 闭合 | stage 按钮两次点击 `body[data-stage]` open→closed→open，`#hxStage` display flex→none→flex，`aria-pressed` / `is-on` 同步翻转；share/pin/more 均有 toast 反馈 |
| B | 任务页元信息 / 计划卡收紧 | ✅ 闭合（空步骤态实测；有步骤态代码路径核对） | 无步骤时计划卡可见 0、「暂无执行计划」出现 0 次；meta 收成单行 chips |
| C | composer 改 V11 风 | ✅ 闭合 | 单一圆角卡、textarea/工具栏全宽、左图标 28×28、发送 32×32、模型下拉 160；360 字输入卡片/输入框溢出均 0 |
| D | 内容工作台新 IA | ✅ 闭合 | `h1`=1、可见「历史版本视图」0 次、全宽橙色署名 banner 隐藏（迁入 meta chip）；历史抽屉 3 条 = 接口 3 条；编辑器可写，字数/保存态/平台 chip 真实联动 |
| E | 真实预览停靠往返 | ✅ 闭合 | 停靠态 pane 在 `#hxStagePreviewMount`、全文 1 份、中栏无重复；折叠归还 `#hxPreviewHome`，平台页签 xhs 保留；重开仍 xhs；停靠态连切 3 稿 pane 不被拉回 |
| F | 跨工作区往返 | ✅ 闭合 | content→tasks→content→collect→content 五轮 pane 均 1 份；content（预览页签激活）`data-preview-dock=stage`，tasks/collect `inline` |
| G | 左栏草稿卡三点菜单 | ✅ 闭合 | 单实例、1231 视口浅/深均不越界、Esc / 外部点击关闭；置顶排位、归档隐藏+恢复、历史条数、删除确认层均实测；复制派生禁用标「未接入」 |
| UX | 内容页右栏默认页签疑点 | ⚠️ 建议优化（非阻断缺陷，见 8.8） | 进入内容页右栏默认激活「资产」，预览留在中栏，右栏看不到预览 |

### 8.2 A 任务页页头动作委托与舞台同步

委托挂在线程根 `#hxThread`（`harness-thread.js:1156-1168`，幂等标记 `data-hxBound=1`），`closest('[data-hx-act]')` 后走 `actDispatch`；stage 分支调 `HX.toggleStage()` 并 `syncStageButtons()`（`thread.js:1090-1093`、`1172-1179`）。

**stage 按钮两次点击序列（浅色实测）**

| 时点 | `body[data-stage]` | `#hxStage` display | 按钮 `aria-pressed` | 按钮 `is-on` | 判定 |
|---|---|---|---|---|---|
| 初始 | open | flex | true | true | ✅ |
| 点第 1 次 | closed | none | false | false | ✅ |
| 点第 2 次 | open | flex | true | true | ✅ |

**头部动作反馈（`#toast` 实读文案）**

| 动作 | 任务页 toast | 内容页 toast | 其他观测 |
|---|---|---|---|
| share 分享 | 分享面板即将接入 | 分享面板即将接入 | ✅ 有可见反馈 |
| pin 钉住 | 已钉住当前任务 | — | 按钮 `on` 态置位 ✅ |
| stage 展开/收起 | 舞台 open↔closed 同步 | 收起后 closed / pressed=false / is-on=false | ✅ |
| more 更多 | 更多操作菜单即将接入 | 更多操作菜单即将接入 | ✅ |
| save 保存 | — | 未触发（避免写库） | 代码路径 `thread.js:1116-1120`：优先点 `#btn-wb-save`，回落 `saveCurrentPlatformContent()` |

深色复测：stage open→closed，display flex→none，pressed true→false，is-on true→false，与浅色一致。

### 8.3 B 任务页元信息 / 计划卡收紧

空步骤态实测（当前 `/api/tasks` 活动任务 0）：

| 探针 | 浅色 | 深色 | 判定 |
|---|---|---|---|
| 可见计划卡 `.hx-plan-card` | 0 | 0 | ✅ 无空卡渲染 |
| 可见计划卡包裹 `.hx-plan-wrap` | 0 | 0 | ✅ |
| 「暂无执行计划」出现次数 | 0 | 0 | ✅ 不重复 |
| meta chips | `deepseek-v4.1-flash-free` | 同左 | ✅ 单行紧凑 chips |
| 计划 / 耗时 meta 链接 | 无 | 无 | ✅ 无步骤不渲染链接 |

代码路径（有步骤态，未造数实测）：`planCardHtml()` 无 `steps.length` 返回空串（`thread.js:297`）；有步骤时渲染可折叠计划卡，`plan-toggle` 切换 `is-collapsed` 与 `aria-expanded`（`thread.js:298-312`、`1097-1104`），卡片对齐消息列宽。

证据：`verify4-light-tasks-layout.png` / `verify4-dark-tasks-layout.png`。

### 8.4 C composer V11 风几何实测（1440 视口，浅色 / 深色一致）

| 量项 | 实测值 | 判定 |
|---|---|---|
| 消息列宽 / 输入卡宽 | 754 / 730 | ✅ 两侧各内缩 12px，与消息列对齐 |
| textarea 宽 / 工具栏宽 | 704 / 704 | ✅ 全宽铺满卡内 |
| 左侧附件类图标 | 28×28 | ✅ 尺寸一致 |
| 模型下拉（`.cb-model-wrap`） | 160 宽 | ✅ 紧凑 |
| 发送按钮 `#btn-copilot-send` | 32×32 圆形，未禁用 | ✅ 橙色圆形 |
| 360 字长文输入 | textarea 溢出 0，卡片溢出 0 | ✅ 换行不溢出 |
| 空态消息区底部 → 输入卡顶部 | 86px（消息区弹性留白） | ✅ 卡片钉在对话底部 |
| 输入卡底部 → 线程容器底部 | 48px（含 `.cb-hint` 提示行 + 底边距） | ✅ 不悬空 |

证据：`verify4-light-tasks-layout.png` / `verify4-dark-tasks-layout.png`（含 composer 卡、工具栏、模型下拉、发送按钮）。

### 8.5 D 内容工作台新 IA

| 探针 | 浅色 | 深色 | 判定 |
|---|---|---|---|
| 头部 `h1` 数量 | 1（`别用闹钟叫醒自己，用这杯☕`） | 同左 | ✅ 标题唯一 |
| 可见「历史版本视图」文案 | 0 | 0 | ✅ 重复文案清零（残留仅在 `<script>` 源码串内，不可见） |
| 全宽橙色署名 / 指标 banner | `.live-metrics-banner` 隐藏；全宽 `.user-media-badge-bar` 隐藏 | 同左 | ✅ 旧 banner 不占中栏 |
| 署名徽标去向 | 唯一可见 badge-bar 已迁入 `.hx-thread-meta` meta 行 | 同左 | ✅ 收成 meta chip |
| 平台 / 字数 / 保存态 chip | 🟢 微信公众号 / 1173 字 / 67 行 / ✓ 已与服务器同步 | 同左 | ✅ 真实联动 |
| 编辑器 `.wb-textarea` | 非只读，正文 1256 字 | 同左 | ✅ 可写 |
| 历史抽屉（`#hxHistoryDrawer`） | 3 条版本，接口 `/api/drafts/{id}/history` 返回 3 条 | — | ✅ 条数一致，含「回退至该版本」 |

**真实功能入口留存核对（中栏 + 右栏可见按钮/节点）**：AI 改写提升、AI 智能配图、配图、插入配图、复制 / 导出、复制微信公众号、多端发布、按需派生所选平台、母稿派生全平台、合规风控体检、历史版本、7维评分、拆解报告——节点均在业务迁入树内，未被 IA 重构移除。

证据：`verify4-light-content-ia.png` / `verify4-dark-content-ia.png`（历史抽屉 3 版本在浅色图右栏可见）。

### 8.6 E 真实预览停靠往返（pane = `#wb-preview-pane`）

| 状态 | pane 父节点 | 在 mount | 在 home | 在中栏线程 | 平台页签 | `data-preview-dock` | 判定 |
|---|---|---|---|---|---|---|---|
| 预览页签停靠 | `hxStagePreviewMount` | 是 | 否 | 否 | wechat_mp | stage | ✅ |
| 切小红书后折叠前 | `hxStagePreviewMount` | 是 | 否 | 否 | xhs | stage | ✅ 页签切换保留 |
| 折叠舞台 | `hxPreviewHome` | 否 | 是 | 是 | xhs | inline | ✅ 归还中栏，xhs 未丢 |
| 重新展开 | `hxStagePreviewMount` | 是 | 否 | 否 | xhs | stage | ✅ 再停靠，xhs 仍在 |
| 停靠态连切 3 篇草稿 | 3 轮均 `hxStagePreviewMount` | 是 | 否 | 否 | xhs | stage | ✅ pane 不被拉回 |

- 全文 `#wb-preview-pane` 数量每轮 = 1，中栏无第二份预览；停靠不 clone、不重拉接口（`harness-stage.js:653-662` 搬运真实节点，`664-683` 归还，`687-702` 决策 + rAF/220ms 复核）。
- 证据：`verify4-light-dock.png` / `verify4-dark-dock.png`。

### 8.7 F 跨工作区三轮往返

路径：content → tasks → content → collect → content（stage 展开、预览页签激活起始）。

| 轮次 | 工作区 | pane 数量 | 停靠标记 | pane 父节点 | 判定 |
|---|---|---|---|---|---|
| 1 | content | 1 | stage | `hxStagePreviewMount` | ✅ |
| 2 | tasks | 1 | inline | `split-workbench`（业务家位） | ✅ |
| 3 | content | 1 | stage | `hxStagePreviewMount` | ✅ |
| 4 | collect | 1 | inline | `split-workbench` | ✅ |
| 5 | content | 1 | stage | `hxStagePreviewMount` | ✅ |

### 8.8 UX 疑点评估：内容页右栏默认激活哪个页签

**实测**：进入内容工作台（选中草稿、舞台展开）时，右栏舞台默认激活 **「资产」**（`activeTab=资产144`）；此时 `#hxStagePreviewMount` 尚未创建，pane 留在中栏 `#hxPreviewHome`，`data-preview-dock` 为空（inline）。即用户打开右栏先看到资产列表，预览仍在中栏。

**根因定位**：
- `harness-stage.js:898` `WS_DEFAULT_TAB = { tasks:'assets', content:'assets', collect:'analysis', settings:'checks' }`——content 默认 assets；
- mount 容器仅在预览页签的 `mountPreview()` 内创建（`stage.js:737-741`），assets 页签下无 mount，`dockPreview()` 因缺 mount 直接返回（`stage.js:655-656`），停靠不会发生。

**建议**：
1. 首选——content 工作区在「有选中草稿」时默认页签置为 **预览**（无选中稿时保持 assets 空态引导）；或
2. 复用既有 per-workspace 页签记忆（`memorizeStageTab` / `resolveStageTab`，`stage.js:901-941`），仅在无记忆时给 content 一个预览默认值。

**影响面**：小。改动集中在 content 的默认页签决策；不影响 tasks/collect/settings，不改变停靠/归还逻辑本身；需回归 content 无选中稿空态与跨工作区页签记忆。本轮按要求未改代码。

### 8.9 G 左栏草稿卡三点菜单

| 探针 | 浅色 1231 | 深色 1231 | 判定 |
|---|---|---|---|
| 菜单实例数 `#hxDraftMenu` | 1 | 1 | ✅ 单实例 |
| 菜单位置 | x235 / y432 / 206×321，右缘 441 < 1231，底缘 753 < 761 | 同左 | ✅ 不越界 |
| Esc 关闭 | open=false | — | ✅ |
| 外部点击关闭 | open=false | — | ✅ |
| 条目 | 打开稿件 / 重命名 / 导出 HTML / 历史版本 / 置顶(本机) / 归档(本机) / 删除(软删除) / 复制派生(禁用·未接入) | 同左 | ✅ |

| 子动作 | 实测 | 判定 |
|---|---|---|
| 历史版本（菜单弹窗 `.hx-hist-row`） | 3 条 + 3 个「回退至此版」按钮，接口返回 3 条 | ✅ 条数一致 |
| 置顶 | 置顶后该稿排位索引 0（`is-pinned`）；取消置顶后索引 -1 | ✅ 置顶排序生效，已还原 |
| 归档 | 主列表 57→56，「已归档」计数 1，归档视图可见该稿；取消归档后主列表恢复 57 | ✅ 隐藏 + 可恢复，已还原 |
| 重命名 | 弹窗预填当前标题、maxlength 60；全程无 `/title` 请求发出（未写库） | ✅ 确认层与绑定正确 |
| 删除 | 二次确认层可见，标题「警惕！不用Agent的企业…」，软删除提示在，确认按钮在；未点确认，`/api/drafts/delete` 请求数 0 | ✅ 确认层 + 入参核对；未删真实稿 |
| 测试稿 | 全量草稿无标题含 `[hx-test]` | ✅ 按口径只验确认层，未发起删除 |
| 复制派生 | `disabled` + 「未接入」标签，无假动作 | ✅ |

代码定位：单实例/外部点击/Esc `rail.js:266-307`；条目与派发 `rail.js:316-374`；重命名 `rail.js:400-435`；历史弹窗 `rail.js:443-475`；删除确认 `rail.js:479-514`（POST `/api/drafts/delete`，body `{ids:[did]}`）。

证据：`verify4-light-menu-open-1231.png` / `verify4-dark-menu-open-1231.png`（展开态）；`verify4-light-menu-1231.png` / `verify4-dark-menu-1231.png`（归档/toast 态）。

### 8.10 零回归重测

**布局 / 溢出 / 列宽（`documentElement.scrollWidth − clientWidth`）**

| 视口 | 浅色溢出 / 列宽 左·中·右 | 深色溢出 / 列宽 |
|---|---|---|
| 1440×900 | 0 / 248·788·404 | 0 / 248·788·404 |
| 1231×761 | 0 / 248·579·404 | 0 / 248·579·404 |
| 1024×900 | 0 / 248·372·404 | 0 / 248·372·404 |

| 回归项 | 结果 |
|---|---|
| Classic（`?legacy=1`）`hx-` 节点 / 溢出 | 浅 0 / 0，深 0 / 0 |
| V11（`?ui=v2`）`hx-` 节点 / 溢出 | 浅 0 / 0，深 0 / 0 |
| 6 个 harness JS `node --check` | core / rail / thread / stage / collect / settings 全部 OK |
| 浏览器 pageerror（39 例探针） | 0 |
| pytest 子集（`test_v1100_workbench_shell` / `test_v1102_rail_prototype_parity` / `test_v1200_stage_layout`） | 51 passed，rc=0，fails=0 |
| `scripts/harness_ui_verify.py` 独立扫描 | hard_fail=0；scan_warns=3（CSS 裸色值 WARN，非阻断） |

### 8.11 缺陷与观察清单

**新发现 hard 缺陷：无。**

| 编号 | 级别 | 现象 / 位置 | 说明与建议 |
|---|---|---|---|
| O-1 | 建议优化（非阻断，对应 8.8） | 内容页右栏默认「资产」，选中稿时右栏看不到预览；`stage.js:898` 默认页签 + `stage.js:737-741` mount 仅预览页签创建 | 有选中稿时默认（或记忆恢复到）预览页签；影响面限于 content 默认值，不改停靠逻辑 |
| O-2 | 未造数口径（非缺陷） | 有步骤计划卡折叠态、save 按钮真实保存写入路径未在本轮写库实测 | 当前 `/api/tasks`=0、无真实步骤；save 走 `thread.js:1116-1120` 既有业务保存路径。待有真实任务后补测 |
| O-3 | 既有边界，不重复记为新缺陷 | B-1～B-6（video/tasks 404、source_url 空、pricing 占位、设置两组未接入、renderSettingsData 空节点告警、深色预览白底） | 沿用 round2 既有口径，本轮未复现新增回归 |

**既有状态不变**：D-1 / D-2 / D-4 已闭合；D-3 辅线达标、正文 7:1 口径待定；D-5 头像与品牌图标字节相同待业务确认；D-6 已闭合。

### 8.12 证据清单

截图目录：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/`

- `verify4-light-tasks-layout.png` / `verify4-dark-tasks-layout.png`：任务页空步骤布局 + composer V11 风
- `verify4-light-content-ia.png` / `verify4-dark-content-ia.png`：内容工作台 IA、meta chips、历史抽屉
- `verify4-light-dock.png` / `verify4-dark-dock.png`：预览停靠右栏、中栏无重复
- `verify4-light-menu-open-1231.png` / `verify4-dark-menu-open-1231.png`：草稿菜单展开态与边界
- `verify4-light-menu-1231.png` / `verify4-dark-menu-1231.png`：归档 toast 与菜单态

原始测量：`design/harness-verify-results/verify-round2d.json`（合并 39 例）、`verify-round2d-reg.json`、`verify-round2d-int.json`、`verify-round2d-fu.json`、`verify-round2d-fu2.json`、`verify-round2d-harness.json`。
