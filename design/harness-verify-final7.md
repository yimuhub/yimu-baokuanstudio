# Harness 外壳重建 · 终轮复验报告（final7）

- 验收时间：2026-11-24 16:20–16:38（CST, UTC+8）
- 验收方：独立只读验收 Agent。**未改业务代码/模板；未 commit；未改版本号；未重启服务；未写库。**
- 被测应用：`http://127.0.0.1:8790/`；参数 `?ui=harness` / `?ui=v2` / `?legacy=1`
- 上一轮报告：`design/harness-verify-final6.md`
- 门禁 JSON：`design/harness-verify-results/verify-20261124-163835.json`

## 结论：**有条件通过**

本轮两处改动的主体逻辑实测成立：四工作区默认页签正确、分工作区记忆对当前工区生效；引导卡结构/交互/撤卡规则正确，选稿会话不显示引导卡。遗留两项非阻断问题：

1. **页签记忆跨工区串值（中）**：未产生分工作区记忆的工区仍回退继承全局键，把上一工区页签带过来，未做到"旧全局键只迁移一次"。归属 `web/static/js/harness-stage.js:724-730`（`resolveStageTab` 全局回退）+ `web/static/js/harness-core.js:436`（每次切页签持续写全局键）、`:685-686`（启动读全局键）。
2. **引导卡冷启动竞态（轻）**：全新冷启动首屏引导卡不渲染，业务占位气泡保留；二次进入任务页后才出现。归属 `web/static/js/harness-thread.js:539-557`（`renderGuide`/`guideObs`）与 `:600-601`（`renderTasksBody` 调用时机）。

---

## 1. 取证口径

- 视口自证（Playwright 渲染面）：`innerWidth=1440`、`innerHeight=900`、`devicePixelRatio=1`、`scrollWidth=1440`；左栏 `#hxRail` 宽 **248**、顶栏 `#hxTopbar` 高 **46**（DOM rect + PIL 像素边界双重复核）。
- 渲染路径说明：本轮 GAC 内嵌 webview 物理尺寸固定 974×761，暴露接口无窗口/视口调整能力，全幅截图只能取到半幅；终态图改由项目 `.venv` 内 Playwright 自带 Chromium headless（1440×900、DPR=1）渲染取证。DOM/交互探针在 GAC 与 Playwright 双引擎复核，结论一致。
- 截图前 `?cb=<时间戳>` 破缓存；6 张图 PIL 复核均 **1440×900**。

## 2. 门禁复跑 —— **PASS**

`python3 scripts/harness_ui_verify.py`：**hard_fail=0**，scan_warns=3（rail.js:40 / thread.js:860 / stage.js:518，复核非违规）；静态 11/11 200；node --check 6/6；隔离 0 失败；模板引用 0 失败；pytest 3 文件 rc=0；`/api/status` 200、`/api/tasks` 200（tasks_count=0）。

## 3. C · 舞台页签默认值与分工作区记忆

### 3.1 全新存储默认值 —— **PASS**

| 工作区 | 期望默认 | 实测 stageTab | 右栏激活页签 |
|---|---|---|---|
| 任务 tasks | 资产 assets | `assets` | 资产 141 |
| 内容 content | 资产 assets | `assets` | 成稿 57 |
| 采集 collect | 采集分析 analysis | `analysis` | 采集分析 200 |
| 设置 settings | 配置检查 checks | `checks` | 配置检查 |

### 3.2 记忆生效 —— **PASS（当前工区）**

任务页手动切「预览」→ 刷新：任务页仍为 `preview`，分工作区键 `yimu.hx.stageTab.tasks=preview` 已写入。

### 3.3 不串工区 —— **FAIL（跨工区回退全局键）**

刷新后依次进入其余工区实测：

| 工区 | 期望 | 实测 | 判定 |
|---|---|---|---|
| 内容 content | 资产 assets（无记忆→默认） | `preview` | ✗ 串入任务页的预览 |
| 采集 collect | 采集分析 analysis | `analysis` | ✓（自身已有分工作区记忆，未被覆盖） |
| 设置 settings | 配置检查 checks | `checks` | ✓（自身已有分工作区记忆） |

机制复核：`resolveStageTab(ws)` 在分工作区键缺失时回退全局键 `yimu.hx.stageTab` 并再次迁移写入；而 `core.setStageTab` 每次切页签都重写全局键。因此**任何从未手动选过页签的工区**，都会继承上一工区的页签。GAC 与 Playwright 双引擎复现：清空分工作区键后，content/collect 均可被全局 `preview` 串入。

## 4. B · 任务页空态引导卡

### 4.1 引导卡结构与布局 —— **PASS**（二次进入后）

- 卡片 `.hx-guide` 可见，矩形 722×152 @(281,137)；对话区 754×356 @(265,121)；composer 738×144 @(273,561)；**引导卡与 composer 交叠面积 0**，均在可视区内。
- 标题「一幕 Agent · 就绪」；文案「描述你想创作的选题、目标平台与字数，我会自动调用爆款算法与多端排版；也可以先点下方建议快速起稿。」
- 3 个 chip：
  1. 🔥 给我一个今日热点选题，写成小红书种草笔记
  2. 📕 围绕桶装水配送写一篇公众号深度长文
  3. 🎯 先出 5 个悬念赛马标题，挑点击率最高的

### 4.2 chip 只填输入框、不发送 —— **PASS**

点第一个 chip 后：`#copilot-input` 值 = 「给我一个今日热点选题，写成小红书种草笔记」，焦点在 `copilot-input`；引导卡仍在，业务消息子节点 0，**未产生已发送消息**。测试后已复原输入框为空。

### 4.3 已选草稿会话不显示引导卡 —— **PASS**

选第 3 篇草稿 `dr-3401d32584`（编辑器正文 891 字）后回任务页：`guidePresent=false`，引导卡撤卡，业务占位气泡保留；内容页标题/保存态/正文恢复正常（见 final7-content.png）。

### 4.4 冷启动竞态 —— **观察项（轻）**

全新冷启动（清 `stageTab` 记忆后重载）0.5s / 1.2s / 2.5s / 4.0s 四个时点，引导卡均未渲染，对话区仅剩业务占位气泡「对话已清空…」；往返 内容→任务 后引导卡才落地。GAC 与 Playwright 双引擎一致复现。真实业务消息出现后撤卡的观察逻辑本身正常（4.3 已验证）。

## 5. 回归抽查 —— **PASS**

| 版本 | shell | hx 节点 | 控制台 error |
|---|---|---|---|
| `?legacy=1` | classic | 0 | 0 |
| `?ui=v2` | v2 | 0 | 0 |
| harness 宽屏 | harness | — | 0 error / 0 warning（Playwright 与 GAC 双口径） |

## 6. 遗留观察项（沿前轮，非本轮新增）

| 编号 | 说明 | 归属 |
|---|---|---|
| F-4 | 草稿 `source_url` 全空，浏览器内嵌/禁嵌运行时路径无样本可测 | 业务数据 |
| F-5 | `renderSettingsData()` 偶发空节点写值，本轮未复现 | 模板既有问题 |
| F-3 | 高亮静态色/先 syncActive 再渲染，本轮未改动该路径，维持 final6 结论 | — |

## 7. 证据截图（1440×900，1x，PIL 复核）

- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final7-tasks.png` —— 任务页：引导卡（头像/标题/文案/3 chip）+ 满宽对话流 + 满宽输入卡 + 底部计划卡空态
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final7-content.png` —— 内容页：已选草稿 `dr-3401d32584`，编辑器正文 891 字、820 字/54 行、已同步
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final7-collect.png` —— 采集页：右栏默认「采集分析 200」
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final7-settings.png` —— 设置页：右栏默认「配置检查」
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final7-legacy.png` —— classic 回归抽查
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final7-v2.png` —— v2 回归抽查

## 8. 边界

- 未触发保存/发布/改写等写操作；chip 测试后已复原输入框；未修改业务代码/模板，未 commit，未改版本号，未重启服务。
