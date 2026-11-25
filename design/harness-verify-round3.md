# Harness 第三轮（rc3）独立复验报告 · 全局小清新 + 双栏每页可收展

> **版本：仍是 15.9.13（石泉境），未 commit、未升级版本号。** HEAD `b5a474e release(v15.9.13)`；工作区 `web/`、`tests/` 的改动为本轮三个执行者遗留，复验过程中**未改业务 JS、未改业务 CSS、未重启 8790 服务、未做任何 git 提交**。
>
> 复验角色：独立复验者，只做验证、取证、记录；未对视觉实现做大改。下文「复验期修复」一节为空（本轮未动 harness 自有 CSS/JS）。
>
> 取证环境：项目 `.venv` Playwright headless Chromium 153.0.8010.12，DPR=1；视口 1440×900 / 1231×761 / 1024×700；所有页面 URL 带 `?cb=<时间戳>` 绕过静态缓存。证据汇总 `artifacts/rc3-evidence.json`，截图 `design/harness-shots/rc3-*.png`。

## 一、结论摘要

**本轮达到验收线：核心目标「全局小清新低饱和视觉系统」与「双栏每页可收展 + 窄屏抽屉 + 状态持久化」均成立。** 24 张页面截图 + 2 张停靠回归截图全部 0 横向溢出、0 pageerror、0 渐变按钮、0 个非强调色实心按钮；门禁 hard_fail=0，扫描告警维持基线 3 条；Classic / V11 隔离干净（hx 自有节点 0、`HX` 全局未注入）。

残留问题均为**轻微 / 业务层待拍板**，不阻断本轮验收，但建议下一轮收口：

- **D1（轻微缺陷）**：影音工坊激活步骤序号 `span.drama-step-num` 仍是旧版朱红 `#C2410C / rgb(194,65,12)`，被基础模板 `!important` 规则压过 harness token 覆盖；同家族的「已完成步骤」绿色态在 harness 下未做映射。
- **D2（轻微缺陷）**：个人中心/套餐页选中套餐卡 `div.billing-plan-card.selected` 内联 `border:2px` 未被复位，仍为 2px 粗边（规约 1px）。
- **D3（需产品拍板）**：除全局「新建任务」外，设置页/套餐/个人中心/采集/内容页内仍有业务实心主按钮，同屏实心强调数 2–3 个；是否要把面板级 CTA 降级为 tonal/ghost，需拍板。
- **D4（轻微形状）**：少量控件圆角落在 5/6/7/9px，未完全收敛到 8/10px token。
- **D5（业务层待确认）**：部分页签/标签/芯片仍以前导 emoji 作图标，未全部换成单色线性图标；按既定例外口径暂记业务层保留。

## 二、逐项 PASS/FAIL 表（含实测值）

### 1. 门禁与静态检查 —— **PASS**

| 检查项 | 实测 | 结论 |
|---|---|---|
| `harness_ui_verify.py --base-url http://127.0.0.1:8790` | `hard_fail=0`，`scan_warns=3`（基线 3 条，无新增） | PASS |
| 扫描告警明细 | `harness-rail.js:47` 已完成；`harness-thread.js:1111` 已完成；`harness-stage.js:525` `<iframe>`（含降级关键字，契约允许） | PASS（=基线） |
| 6 个 harness JS `node --check` | core / rail / thread / stage / collect / settings 全部 `rc=0` | PASS |
| pytest 子集 3 文件 | `tests/test_v1100_workbench_shell.py`、`tests/test_v1102_rail_prototype_parity.py`、`tests/test_v1200_stage_layout.py`，`rc=0`，51 用例全绿 | PASS |
| `workbench-shell.js` v2 守卫计数 | `grep -c "getAttribute('data-shell') !== 'v2'"` = **3** | PASS |
| 静态资源 200 | 11 项（5 CSS + 6 JS）全部 200，失败 0 | PASS |
| 模板挂载 / 隔离规则 / 双主题 Logo | 挂载失败 0、隔离失败 0、主题检查 FAIL 0；深色覆盖 41 token、浅色 47 token | PASS |
| 真实接口探针 | `/api/status` 200、`/api/tasks` 200（tasks_count=0） | PASS |

备注（非缺陷）：验收脚本对 `harness-core.js`、`harness-rail.js` 报「未发现 data-shell 守卫早退」WARN，属脚本启发式只认 `if(!fn()) return` 写法；实际两文件顶部均有 `if (!DOC.body || DOC.body.getAttribute('data-shell') !== 'harness') return;` 守卫早退，隔离有效。另脚本主题检查有 1 条 WARN：`harness-ui.css` 有 21 处裸 hex，逐条核对**全部出现在属性选择器**（`[style*="#…"]`）用于压制业务内联色，声明侧已映射 token，不构成裸色使用。

### 2. 隔离与回归（Classic / V11）—— **PASS**

| 形态 | URL | hx 节点数 | `HX` 全局 | body 底色 | 顶栏底色 | 主按钮底色 | pageerror |
|---|---|---|---|---|---|---|---|
| Classic | `?legacy=1` | **0** | 未定义 | `rgb(248,250,252)` | `rgba(255,255,255,0.96)` | 页面无 `.primary` | 0 |
| V11 | `?ui=v2` | **0** | 未定义 | `rgb(248,250,252)` | `rgba(255,255,255,0.96)` | `rgb(194,65,12)`（V11 自有旧橙，**非** harness 强调 `rgb(174,91,55)`） | 0 |

- 两种旧形态均未出现 `hx-` id / `hx-` class 节点，body 上无 harness 自有属性。
- 未观察到 harness 奶白底 / 陶土橙泄漏到 Classic/V11；V11 保留其自有旧橙主按钮。
- 两种形态页面均正常渲染（可见区 `p-lite-mode`）。

### 3. 逐页视觉（8 页 × 3 组合）—— **PASS（含 D1/D4 轻微项）**

24 组合指标汇总（完整数值见 `artifacts/rc3-evidence.json → pages`）：

| 页面 | 1440 浅 scrollW/err | 1231 深 scrollW/err | 1024 浅 scrollW/err | 渐变按钮 | 非强调实心按钮 |
|---|---|---|---|---|---|
| dashboard 大屏 | 1440 / 0 | 1231 / 0 | 1024 / 0 | 0 | 0 |
| lite 任务 | 1440 / 0 | 1231 / 0 | 1024 / 0 | 0 | 0 |
| inspire 采集 | 1440 / 0 | 1231 / 0 | 1024 / 0 | 0 | 0 |
| content 内容 | 1440 / 0 | 1231 / 0 | 1024 / 0 | 0 | 0 |
| studio 影音 | 1440 / 0 | 1231 / 0 | 1024 / 0 | 0 | 0 |
| console 设置 | 1440 / 0 | 1231 / 0 | 1024 / 0 | 0 | 0 |
| pricing 套餐 | 1440 / 0 | 1231 / 0 | 1024 / 0 | 0 | 0 |
| profile 个人中心 | 1440 / 0 | 1231 / 0 | 1024 / 0 | 0 | 0 |

共性实测：

- **顶栏**：浅色 `rgba(251,250,247,0.88)` + `backdrop-filter: blur(12px)` + 1px `rgb(231,229,222)` 底线；深色 `rgba(23,24,26,0.9)` + 底线 `rgb(44,45,39)`，半透明同层级、非简单反相。无黑底。
- **底色/卡片**：外壳底 token `#F7F6F2`（深 `#17181A`），卡片 `#FFFFFF`（深 `#1E1F1D`）；卡片圆角 10px，阴影单层极轻（如 `rgba(0,0,0,0.03) 0 2px 10px` / `rgba(46,51,47,0.04) 0 1px 2px`），未见双层重阴影。
- **按钮体系**：无 `linear-gradient/radial-gradient` 背景图；实心强调统一 `#AE5B37`（深 `#B4603C`）；其余 ghost 透明底 + `#E7E5DE` 描边 + `#5A615B` 文字。
- **横向溢出**：24 组合 `scrollWidth ≤ innerWidth`，`overflowX=false`。
- **文字可读**：深浅两态正文/次文字层级正常，未见低对比灰字。

**内容页专项核对**（`rc3-content-1440-light.png` / `1231-dark` / `1024-light`）：

- 工具条（AI 改写提升 / AI 智能配图 / 配图 / 复制·导出 / 多端发布 / 更多）：透明底 ghost、单色描边、统一高度；富文本操作条（H3/加粗/列表/引用/分割线/标签/配图/换肤/富文本）为透明底 + 细线描边文字按钮。
- 底部动作条实心主按钮仅 **1 个**：`#btn-wb-save`「保存并重新渲染 (Ctrl+S)」`rgb(174,91,55)` 白字 8px；旁侧「AI 改写提升」「按需派生所选平台」为白底 ghost，非第二实心主按钮。
- **橙色署名横条：已消失**（中栏未检出宽度 >200、高度 >14 的橙底整条 bar，`orangeBars=[]`）。
- 进阶面板（拆解报告 / 7 维评分 / 历史版本 / 合规风控体检 / 复制 / 派生）位于右栏预览页签与预览卡片区，未铺在中栏。
- 平台/字数/同步状态收成一行紧凑 meta，成功态仅文字绿。

### 4. 双栏伸缩 —— **PASS**

宽屏 1440（`artifacts/rc3-evidence.json → layout.wide_1440`）：

| 动作 | 实测 | 结论 |
|---|---|---|
| 初始左栏 | `#hxRail` 宽 **248px**，`data-rail=full` | PASS |
| 点 `#hxRailToggle` 收栏 | 宽 **68px**，`data-rail=mini`；按钮仍可见，title=「展开左栏」；无横向溢出 | PASS |
| 再点展开 | 回到 **248px**，`data-rail=full`，title=「收起左栏」 | PASS |
| 右栏 8 页收/展 | 8 页（dashboard/lite/inspire/content/studio/console/pricing/profile）点 `#hxTbStage` 后 `data-stage=closed`、`#hxStage display:none`；再点恢复 `open/flex`；收起后顶栏按钮仍可见，title=「展开舞台」 | PASS |
| 持久化（宽屏） | 置 `rail=mini` + `stage=closed`，LS `yimu.hx.railMini=1`、`yimu.hx.stageOpen=0`；刷新后仍 `mini/closed`，LS 保持 | PASS |

窄屏 1024（`layout.narrow_1024`）：

| 动作 | 实测 | 结论 |
|---|---|---|
| 舞台展开形态 | `position:fixed`，`top=46` = 顶栏高 `46`（**不盖顶栏**），宽 `420px`（`min(420px,92vw)`），`overflowX=false`，不挤压中栏 | PASS |
| 左栏收/展 | 248 → 68 → 248，迷你态按钮可见可点 | PASS |
| 舞台收/展 | closed `display:none`；open 回到 fixed 抽屉；无横向溢出 | PASS |
| 持久化（窄屏） | 刷新后 `rail=mini`、`stage=closed`，LS `1/0` 保持 | PASS |

### 5. 内容页停靠回归 —— **PASS**

证据 `layout` 旁 `dock` 段，截图 `rc3-content-dock-open.png` / `rc3-content-dock-inline.png`：

| 阶段 | `data-preview-dock` | `#wb-preview-pane` 数 | pane 父节点 | 结论 |
|---|---|---|---|---|
| 选稿后（舞台展开） | `stage` | **1** | `hxStagePreviewMount` | PASS |
| 折叠舞台 | `inline` | **1** | `hxPreviewHome` | PASS |
| 再展开 | `stage` | **1** | `hxStagePreviewMount` | PASS |

- inline 态预览窗内 12 个控件、9 个可见，含平台 tab（公众号/小红书/今日头条）、拆解报告、7 维评分、历史版本，均可定位；点击平台 tab 切到「小红书(5图)」状态变更生效，0 pageerror。
- 全程未出现第二份 `#wb-preview-pane`。

### 6. 诚实性核查 —— **PASS**

- 随机点击 5 个安全可见按钮，全部有状态响应、0 pageerror / 0 console error：

| 按钮 | 选择器 | 响应 | 新错误 |
|---|---|---|---|
| 顶栏外观主题循环 | `#hxTbTheme` | 主题模式 system→light→dark→system 循环正常（首击 system→light，headless 下解析浅色，故 `data-theme` 暂留 light，非死按钮） | 无 |
| 顶栏舞台开关 | `#hxTbStage` | stage open→closed | 无 |
| 左栏开合 | `#hxRailToggle` | rail full→mini | 无 |
| 舞台页签 | `.hx-stage-tab:nth-of-type(2)` | 预览→浏览器 | 无 |
| 预览平台 tab | `.wb-nav-tab:nth-of-type(2)` | 公众号→小红书(5图) | 无 |

- 「未接入 / 尚未接入」徽标均带诚实说明，未伪造已接入：控制台「发布账号 / 团队席位 · 未接入」附注「接口未回传岗位/成员数据，暂无真实数据」；大屏/影音「尚未接入生图/视频模型——分镜脚本仍可用…」为能力边界提示。
- 加载态文案诚实：「正在从定价中心加载套餐与权益…」「实时抓取中…」「原文快照尚未入库」，无伪装成已成稿的假数据。
- 计数与真实接口一致：左栏内容 57、采集 200，与 `/api/status` drafts 列表吻合；`/api/tasks` tasks_count=0，任务页呈现真实空态「真实对话面板尚未就绪，请稍后重试。」

## 三、逐页目检记录

| 页面 | 1440 浅色 | 1231 深色 | 1024 浅色 | 目检备注 |
|---|---|---|---|---|
| dashboard 大屏 | PASS | PASS | PASS | 统计卡白底圆角轻阴影；四条 CTA 链接统一强调墨色；环形/折线序列色为图表业务色（例外）；「实时抓取中」「全链路畅通」为状态软底 |
| lite 任务 | PASS | PASS | PASS | 真实空态，一句说明无插图；模型 chip 中性；右栏草稿列表中性 |
| inspire 采集 | PASS | PASS | PASS | 页签选中强调软底；平台品牌圆点保留；主操作为页内「一键联网创作」（见 D3） |
| content 内容 | PASS | PASS | PASS | 见 §2.3 专项；编辑器正文内联色为业务内容层（例外） |
| studio 影音 | PASS（D1） | PASS | PASS | 工具条 ghost；无第二实心主按钮；**激活步骤序号残留旧朱红（D1）** |
| console 设置 | PASS（D3） | PASS | PASS | 页签前导 emoji 未全部单色化（D5）；「去填 Key」「重新检测」两个业务实心 CTA（D3） |
| pricing 套餐 | PASS（D3） | PASS | PASS | 步骤卡中性；套餐加载空态诚实；右栏配置检查面板带「重新检测」实心按钮（D3） |
| profile 个人中心 | PASS（D2/D3） | PASS | PASS | 选中套餐卡 2px 粗边（D2）；语义 gold badge 软底保留（例外）；trait/主题芯片 emoji 前导（D5） |

## 四、双栏矩阵（实测值）

| 场景 | 左栏 full | 左栏 mini | 右栏 open | 右栏 closed | 窄屏抽屉 | 持久化 |
|---|---|---|---|---|---|---|
| 1440 宽 | 248px / full | 68px / mini，入口可见「展开左栏」 | relative，404px，flex | display:none，顶栏入口可见「展开舞台」 | 不适用（>1180 三列） | 刷新保持 mini/closed |
| 1024 窄 | 248px / full | 68px / mini，入口可见 | fixed，420px，top=46=顶栏高，不盖顶栏，无横向溢出 | display:none，入口可见 | fixed 覆盖式抽屉，不挤压中栏 | 刷新保持 mini/closed |

## 五、停靠回归（内容页）

见 §2.5。补充：inline 态平台 / 评分 / 拆解 / 历史页签仍可点；舞台折叠不删除预览窗；再展开仍仅 1 份 pane。

## 六、残留彩色与业务层例外清单

### 6.1 本轮发现的待修项（harness 外壳口径内）

| 编号 | 元素 / 类 | 实测 | 位置 | 性质 |
|---|---|---|---|---|
| D1 | `span.drama-step-num`（影音工坊激活步骤序号） | 背景 `rgb(194,65,12)` / `#C2410C`，hsl(17,0.88,0.40)，旧版朱红，未走 `--hx-accent` | studio 页步骤条 | 根因：基础模板 `[data-theme="light"] .drama-step-item.active .drama-step-num{background:#c2410c!important}` 带 `!important`，压过 `harness-ui.css:846` 无 `!important` 的 token 覆盖；同规则族 `.done` 绿 `#16a34a/#86efac/#15803d` 在 harness 下也未映射（当前视图无 done 步骤，未触发） |
| D2 | `div.billing-plan-card.selected`（选中套餐卡） | 内联 `border:2px solid`，harness 覆盖了颜色/阴影但未复位宽度，实测 2px 粗边 `rgb(231,213,201)` | profile（pricing 同结构，加载态未渲染） | 规约要求 1px `--hx-line`；需在 harness 覆盖里补 `border-width:1px` |
| D3 | 业务实心主按钮：`#btn-run-oneshot`（采集）、`#btn-wb-save`（内容）、`button.btn.ok`「去填 Key」（设置）、`button.hx-config-run`「重新检测」（跨页常驻配置检查面板） | 与全局 `#hxNewTask` 同屏并存；console 同屏实心 3 个，pricing/profile/content/inspire 2 个 | 多页 | 规约「同屏最多一个 primary」的口径需产品拍板：全局 chrome 主按钮与面板/页内 CTA 是否分级，面板级是否降 tonal/ghost |
| D4 | 散见控件圆角 5/6/7/9px（富文本行按钮 6px、历史版本 5px、全站 7px 81 处、9px 20 处等） | 未全部收敛到 `--hx-radius-sm:8px` / `--hx-radius:10px` | 多页工具条/小控件 | 轻微形状不一致，不影响可读性 |
| D5 | 页签 / 芯片 / 按钮前导 emoji：🤖🎯🎬🎙️📋🚀⚡💾🎨🖼️✍️ 等 | 未全部替换为 currentColor 单色线性图标 | console/inspire/studio/profile 标签与芯片 | 与「工具条不得用彩色 emoji 当图标」口径有偏差；是否视为业务文案 emoji 保留需拍板 |

### 6.2 业务内容层保留（非本轮缺陷，按既定口径记录为例外）

1. 编辑器 / 预览文章正文内联排版色（如正文橙色小标题、加粗强调色）。
2. 平台品牌 emoji 圆点与名称：🟢 公众号、📕 小红书、🔴 今日头条、🔵 知乎、🟡 微博、𝕏 Twitter/X。
3. 图表 SVG 内联序列色（大屏折线、环形占比、平台条形），仅整体降饱和，未逐序列改 token。
4. pricing/profile 语义 badge 软底与文字（`.badge.ok/.green/.blue/.gold`，含 gold `rgb(254,243,199)`「自备直连零损耗」）。
5. 按钮 / 标签文案里的业务 emoji（随文案出现，不作为独立彩色图标）。
6. 成功/完成状态绿（`--hx-green`，仅状态文字/圆点）；信息/提醒/危险色仅用于对应语义。

## 七、待办与风险

**建议下一轮收口（轻微，不阻断本轮）：**

1. D1：在 `harness-ui.css` 对 `.drama-step-item.active/.done .drama-step-num` 提高优先级（补 `!important` 或更具体选择器），映射到 `--hx-accent` / `--hx-green`；并核对深色态。
2. D2：选中套餐卡覆盖规则补 `border-width:1px`。
3. D4：把散在 5/6/7/9px 的控件圆角归一到 8/10 token。

**需用户 / 产品拍板：**

4. D3：同屏实心主按钮数量口径——全局「新建任务」之外，面板级 CTA（去填 Key、重新检测、页内主操作）是否允许保留实心强调，还是统一降 tonal/ghost。
5. D5：业务页签/芯片前导 emoji 是否本轮一并换单色线性图标，还是作为业务层长期保留。

**风险备注：**

- 验收脚本对 core/rail 的「守卫早退」WARN 为启发式误报，实际守卫存在；不影响隔离结论。
- `/api/tasks` 当前 tasks_count=0，任务页为空态；任务交互链路（生成中、轮询、完成态）本轮未造数覆盖，建议下一轮有真实任务时补测。
- 定价套餐区当前处于「从定价中心加载」态，套餐卡成组样式未在真实套餐数据下复核；profile 选中卡为预置 `pro` 卡。
- 本轮所有 headless 会话使用独立浏览器上下文，未写入用户日常 webview 的 localStorage；8790 服务未重启。

## 八、复验期修复

无。本轮复验未修改任何 harness 自有 CSS/JS，未改业务 JS，未提交 git。

## 附：证据与截图清单

- 证据 JSON：`/Users/czmj/Documents/yimu-baokuanstudio/artifacts/rc3-evidence.json`（门禁数值、node/pytest、24 页 scrollWidth/pageerror/stage/rail/入口可见性/pane 数/dock 值、隔离计数、按钮抽查、残留彩色审计）
- 门禁原始输出：`/Users/czmj/Documents/yimu-baokuanstudio/artifacts/rc3-gate.json`
- 截图目录：`/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/`

矩阵截图（24）：

- `rc3-dashboard-1440-light.png` / `rc3-dashboard-1231-dark.png` / `rc3-dashboard-1024-light.png`
- `rc3-lite-1440-light.png` / `rc3-lite-1231-dark.png` / `rc3-lite-1024-light.png`
- `rc3-inspire-1440-light.png` / `rc3-inspire-1231-dark.png` / `rc3-inspire-1024-light.png`
- `rc3-content-1440-light.png` / `rc3-content-1231-dark.png` / `rc3-content-1024-light.png`
- `rc3-studio-1440-light.png` / `rc3-studio-1231-dark.png` / `rc3-studio-1024-light.png`
- `rc3-console-1440-light.png` / `rc3-console-1231-dark.png` / `rc3-console-1024-light.png`
- `rc3-pricing-1440-light.png` / `rc3-pricing-1231-dark.png` / `rc3-pricing-1024-light.png`
- `rc3-profile-1440-light.png` / `rc3-profile-1231-dark.png` / `rc3-profile-1024-light.png`

停靠回归截图（2）：`rc3-content-dock-open.png`、`rc3-content-dock-inline.png`。

---

## 七、复验后收口（主协调者执行，2026-11-25）

独立复验列出的两个轻微缺陷已在 `web/static/css/harness-ui.css` 直接修复并复测：

- **D1 已修**：`#p-studio .drama-step-item.active .drama-step-num` 实测 `bg=rgb(174,91,55)`、`color=rgb(255,255,255)`（白字压在陶土橙上，对比 4.83），`border=1px var(--hx-accent-line)`；新增 `.done` 映射为 `--hx-green-soft` + `--hx-green`，不再残留 `#C2410C` 朱红。修法为在 harness 作用域内补 `#p-studio` 前缀 + `!important`，压过基础模板的同名 `!important` 规则。
- **D2 已修**：`.billing-plan-card.selected` 实测 `border-width=1px`、`border-color=rgb(231,213,201)`、`bg=rgb(246,237,231)`、`radius=8px`，粗边消失。
- 修复后复跑门禁：`hard_fail=0`、`scan_warns=3`（与基线一致），产出 `design/harness-verify-results/verify-20261125-004658.json`。
- 最终成图重拍为 `design/harness-shots/fresh-*.png`（8 页 × 1440 浅 / 1231 深 / 1024 浅 + 双栏矩阵 + 内容页停靠），矩阵指标仍为 0 溢出、0 pageerror、0 第四列。

**仍未改、留待拍板**：D3（面板级实心 CTA 是否降级）、D4（少量 5/6/7/9px 圆角）、D5（业务 emoji 前导图标）。这三项均为口径/内容问题，不属本轮视觉 token 缺陷。
