# Harness 外壳重建 · 终轮复验报告（final6）

- 验收时间：2026-11-24 15:59–16:03（CST, UTC+8）
- 验收方：独立只读验收 Agent。**未改业务代码/模板；未 commit；未改版本号；未重启服务；未写库。**
- 被测应用：`http://127.0.0.1:8790/`；参数 `?ui=harness` / `?ui=v2` / `?legacy=1`
- 上一轮报告：`design/harness-verify-final4.md`
- 门禁 JSON：`design/harness-verify-results/verify-20261124-155936.json`

## 结论：**通过**（无新增阻断/中等级外壳缺陷；遗留仅观察项 F-4/F-5）

本轮两处修复均复测通过：高亮静态色一致跟随；任务页 lite 满宽、无遮挡。门禁 hard_fail=0。

---

## 1. 取证口径

- 视口自证：`innerWidth=1440`、`innerHeight=900`、`devicePixelRatio=1`、`scrollWidth=1440`。
- 截图：CDP 全幅截后 LANCZOS 降采样至 **1440×900**，PIL 复核 6 张均 1440×900；尺寸一律 `getBoundingClientRect()` CSS px。
- 布局矩形：顶栏 1440×46 @0,0；左栏 248×854 @0,46；中栏 788×854 @248,46；右栏 404×854 @1036,46。

## 2. 门禁复跑 —— **PASS**

`python3 scripts/harness_ui_verify.py`：**hard_fail=0**，scan_warns=3（rail.js:40 / thread.js:724 / stage.js:518，复核非违规）；静态 11/11 200；node --check 6/6；隔离 0 失败；模板引用 0 失败；pytest 3 文件 51 例 rc=0；`/api/status` 200、`/api/tasks` 200（tasks_count=0）。

## 3. 高亮一致性（F-3 收口）—— **PASS**

六步切换 tasks→content→collect→settings→更多·studio→settings，每步仅一项左栏激活、一段顶栏激活，无双重激活；色值与声明一致。

| 步骤 | state.workspace | moreKey | 左栏激活（文本 / 底 / 字色） | 顶栏激活（文本 / 底 / 字色） |
|---|---|---|---|---|
| tasks | tasks | — | 任务 / rgb(255,241,234) / rgb(169,73,36) | 任务 / rgb(48,52,61) / rgb(255,255,255) |
| content | content | — | 内容工作台57 / rgb(255,241,234) / rgb(169,73,36) | 内容工作台 / rgb(48,52,61) / #fff |
| collect | collect | — | 采集工作台200 / rgb(255,241,234) / rgb(169,73,36) | 采集工作台 / rgb(48,52,61) / #fff |
| settings | settings | — | 系统设置 / rgb(255,241,234) / rgb(169,73,36) | 系统设置 / rgb(48,52,61) / #fff |
| studio（更多） | settings | studio | 左栏四工作区全灭；更多项「影音工坊」激活 | 顶栏四段全灭 |
| settings（返回） | settings | — | 系统设置 / rgb(255,241,234) / rgb(169,73,36) | 系统设置 / rgb(48,52,61) / #fff |

- 非激活态复核：左栏透明 / rgb(102,109,120)，徽标底 rgb(240,241,244) / 字 rgb(123,130,141)；顶栏透明 / rgb(156,163,175)。
- 激活徽标：底 rgb(255,216,198)、字 rgb(181,74,34) ✓。
- 代码核对：`harness-core.js:576` `syncActive()` 先写顶栏/左栏/更多项，`:357/:362/:374/:378` 渲染前同步 + `requestAnimationFrame` 幂等复核；`harness-ui.css:125/:271` 顶栏分段、左栏徽标 `transition:none !important`，菜单/面板静态声明色；`:399` 中栏搬入面板 `transition:none !important`。

## 4. 任务页 lite 满宽布局 —— **PASS**

中栏 body 宽 **788** CSS px：

| 节点 | 宽 | 占 body 比 | 判定 |
|---|---|---|---|
| `#p-lite-mode` | 756 | 96% | ≥90% PASS |
| 对话区 `#copilot-chat-messages` | 754 | 96% | ≥90% PASS |
| composer `#copilot-composer` | 738 | 94% | ≥90% PASS |
| 输入框 textarea | 720 | 91% | ≥90% PASS |

- `#copilot-chat-messages` 与 `#copilot-composer` 均在可视区内；rect 交叠面积 **0**，无互相遮挡。
- 业务重复头部 `.hx-lite-head` 及其余 92 个业务节点隐藏；快捷 chips 6 个换行排布；发送按钮 **31×31**（x971 靠右）；模型下拉靠右（x749，宽 223）；停止生成按钮 0×0 隐藏。
- 计划卡为空态「暂无真实任务记录 / 暂无执行计划…」，与 composer 不重叠。

## 5. 回归抽查 —— **PASS**

| 版本 | shell | hx 节点 | `HX` | 控制台 |
|---|---|---|---|---|
| `?legacy=1` | classic | 0 | undefined | 0 外壳报错（既有业务 iframe sandbox 提示偶发，非外壳） |
| `?ui=v2` | v2 | 0 | undefined | 0 error |
| harness 宽屏 | harness | — | object | 0 error / 0 warning |

- 窄屏回落：本机内嵌浏览器 974 CSS 宽实测 `?ui=harness` 按设计回落 classic、旧界面完好（用户现场活证据）；本轮 CDP 900px 口径同前。
- 右栏三页签沿用 final3/final4 口径：资产 57 / 图片 141 / 数据 57，预览真实排版，浏览器无来源诚实空态。

## 6. 遗留观察项（非阻断，不计外壳回归）

| 编号 | 说明 | 归属 |
|---|---|---|
| F-4 | 57 篇草稿 `source_url` 全空，浏览器内嵌/禁嵌运行时路径无样本可测，待带源草稿产生后补验 | 业务数据 |
| F-5 | `renderSettingsData()` 偶发空节点写值，本轮未复现 | 模板既有问题 |

## 7. 证据截图（1440×900，1x，PIL 复核）

- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final6-tasks.png` —— 任务页：满宽对话流 + 满宽输入卡 + 底部计划卡空态
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final6-content.png` —— 内容页：已选草稿，编辑器正文可见
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final6-collect.png` —— 采集页
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final6-settings.png` —— 设置页
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final6-legacy.png` —— classic 回归抽查
- `/Users/czmj/Documents/yimu-baokuanstudio/design/harness-shots/final6-v2.png` —— v2 回归抽查

## 8. 边界

- 未触发保存/发布/改写等写操作；未修改业务代码/模板，未 commit，未改版本号，未重启服务。
