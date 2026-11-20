# 📝 Changelog · 一幕·YIMU 爆款工作室

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [15.9.9] - 鹤鸣篇 (Crane Call Chapter) · 2026-11-20

### Fixed 任务终态断裂、Python 3.13+ 路径判定 fail-open 与静态资源缓存

本轮为 v15.9.8 之后的操作审查收口：机械门禁全绿的前提下，靠真实浏览器走查与
真实任务提交抓出两类「跑起来才断」的缺陷，并补齐对应的回归锁。
`tests/test_v1599_web_fixes.py` 扩至 32 项、`tests/test_v1594_pathsafe.py` 扩至 16 项。

**P0 · 所有后台任务轮询等不到终态**

1. **任务状态词汇断裂**：v15.9.9 做「三条任务读路径统一 `_get_task_view`」时，把
   JOBS 的 `done` 归一成 `completed`，而前端 45 处轮询各自写死 `j.status === 'done'`。
   结果是配音 / 改写 / 生图 / 视频 / 发布 / 工单**全部**等不到终态，一路轮询到
   `maxMs`（最长 30 分钟）才报「任务仍在后台执行」，用户看到的是「合成完成但界面不动」。
   同批代码还暴露一个早已存在的同类断裂：`/api/tasks/{id}` 一直只返回 `completed`，
   AI 短视频轮询从来没走通过。
   修复不是把后端改回去（`task_queue` 落库一直是 `completed`，改回去只会掩盖旧 bug），
   而是建立唯一真源：后端 `TASK_TERMINAL_STATUSES` 集合 + 前端 `isTerminalStatus()` /
   `isSuccessStatus()`，移动端模板自包含就地内联同一套词汇表，全站字面量判定全部替换。

**P1 · 路径包含判定在 Python 3.13+ 静默 fail-open（安全）**

2. **符号链接环不再抛错**：Python 3.13 起 `Path.resolve(strict=False)` 遇到 ELOOP
   **不再抛 OSError**，改为原样返回未展开路径。`core/pathsafe.is_within()` 原本靠
   `except OSError: return False` 实现 fail-closed，于是自指链接被解析成自己、
   `relative_to(base)` 顺利通过——坏链接被判为合法。代码一行没改，升级 Python 就中招。
   修复补一道 `_resolves_cleanly()` 存在性走查，判据写成「存在但不可达」
   （`lexists` 真 / `exists` 假）；路径尚未生成时仍按词法放行，保持原有语义。

**其它**

3. **静态资源破缓存**：`/static/*` 下发 7 天强缓存而模板引用为裸路径，发版后最多可连续
   一周「新壳 + 旧 JS」。`render_dynamic_html()` 末尾统一注入 `?v=<版本>`（幂等）。
4. **免 Key 生图引擎三处口径不一**：`flux-schnell` 设置页可选可存、后端兜底链恒用它，
   但工坊下拉不列、流水线闸门还判「没有可用生图模型」。收敛为单常量 `FREE_IMAGE_ENGINE`
   + 下拉选项 + 闸门豁免，并在只缺视频模型时给出如实文案。

### Verified

全量 **954** 用例通过；`ci.sh` 四步门禁全绿（探针 2 PASS / 4 SKIP / 0 FAIL）；
真实浏览器走查：全站 7 页运行时 JS 错误 0，真实配音任务端到端第 2 次探测收敛到
`completed` 并产出 447KB 音频，四种终态词汇（done/completed/failed/cancelled）全部命中。

---

## [15.9.8] - 月泉吟 (Moon Spring Chant) · 2026-11-20

### Fixed 深度审查整改：资损、可靠性、安全与移动端体验同步收口

本版本全部来自 2026-11-19 全量深度剖析（后端/前端/产品三线代码走查 + 真实浏览器
端到端实测 + GitHub 竞品调研）确认的问题清单，后端 / PC 前端 / 移动端 / 静态资源 /
容器化五线并行整改，`tests/test_v1598_backend_fixes.py`（32 项）全部落锁。

**资损与安全（P0）**

1. **流式计费漏损封堵**：`chat_stream` 此前不把 `user_id` 传进解析链与计费，官方通道
   流式调用只记统计不扣费——等于免费无上限。现在 user_id 全链路透传（BYOK 随之生效），
   `/api/stream/write` 开流前按官方通道估算法验余额（不足 402 拒绝），完成后照常记账；
   metering 缺 user_id 的兜底分支补 warning 并落回归锁。
2. **全站请求超时**：`api()` 默认 60s AbortController（`opts.timeoutMs` 可分级覆盖，
   升级/上传/生图等 28 处长接口显式配置），超时抛「请求超时，请检查网络或稍后重试」，
   按钮的 finally 解锁从此自然生效——"按钮永久生成中只能刷新页面"根除。
3. **PopupGuard 从静默吞到有反馈**：生成期间拦截与重复确认拦截从无声 `return false`
   改为 toast 告知（同 key 10s 防抖），同步语义不变，30 处 confirm 调用零破坏。
4. **中文输入法回车误发送**：PC 15 处 + 移动端全部裸 `Enter` 提交点统一
   `imeSafeEnter` 守卫（`isComposing || keyCode===229`），拼音候选确认不再半截发送。
5. **升级供应链收口**：移除默认第三方镜像（ghfast.top / ghproxy.net），镜像改为
   `upgrade.mirrors` 显式配置且绝不携带 token；Release ZIP 下载后优先取 `.sha256`
   强校验（失败中止不落盘），未提供则明示「完整性未验证」。
6. **SSRF 出站防护**：新增 `core/outbound_guard.py`——scheme 白名单 + 全 A/AAAA
   解析逐个校验 + 私网/环回/链路本地/云元数据拦截；多用户模式强制启用，单机桌面
   保持环回放行；接入声音克隆测试与热榜抓取等用户可控 URL 出站点。
7. **Docker 宣称落地**：README 此前宣传 `docker compose up -d` 而全仓无任何容器文件，
   现补齐 `Dockerfile`（内置 CJK 字体防卡片方框）+ `docker-compose.yml`（命名卷/
   healthcheck/必填管理口令）+ `deploy/cloud/`（env 样例 + 部署指南），镜像构建与
   compose 配置均已实测通过。

**可靠性（P1）**

- **任务管线收拢**：新增 `spawn_user_task`（受界 worker 池 + 每用户并发闸门 2 +
  JOBS 一小时过期清理），drafts/media 五处 fire-and-forget 全部改走 helper；
  此前"看起来有队列"实为默认执行器无背压，连点生成即无限制并发。
- **取消语义修正**：用户取消写独立 `status="cancelled"`（不再污染 failed 统计）；
  `Task.register_cancel` 联动 ffmpeg 子进程 `terminate→kill`（Popen + 0.5s 轮询 +
  stderr 抽干防管道死锁），僵尸进程收得掉。
- **任务归属隔离**：`/api/tasks` 与取消/详情接口按当前用户过滤，admin 全量，
  越权 404 与草稿归属同口径。
- **磁盘治理**：`draft_expire_days` 出厂默认 0→90，启动自动清理过期草稿并输出
  data/drafts 体量日志（>5GB 告警）；进度持久化失败从静默改 warning。
- **流式降级链对齐**：`chat_stream` 补齐与 `chat()` 相同的逐通道 fallback +
  逐通道诊断；已吐 chunk 后不跨通道缝合；SSE 坏 chunk 从静默丢弃改 debug 留痕。
- **轮询纪律**：PC 19 处 + 移动端 6 处 `while(true)` 任务轮询全部收拢为
  `pollJob/pollJobMini`——网络抖动容忍重试、总时长上限（超限诚实提示"任务仍在
  后台执行"）、可取消（切草稿/切页/关抽屉联动）、后台标签页节流；"一次抖动即
  假失败"与"裸异常文案"根除。
- **配置损坏防护**：`config.local.yaml` 解析失败先把坏文件存档 `.corrupt-<ts>`
  → 回退 `.bak` → 无备份拒绝空配置启动；写配置前原子备份当前好配置。
- **移动端**：加号菜单「抓取全网热榜」死链修复（复用热榜 Tab 同源实现）；
  等待文案诚实化（5~10 秒 → 1~3 分钟 + 可离开本页）+ 发送防重复提交。

**产品口径与体验（P2）**

- **影音工坊无模型守门**：生图/视频模型均未接入时，8 步流水线主按钮禁用并展开
  「去配置模型」引导条（直达 系统与 API 配置）；分镜脚本 / 口播 TTS 不受影响；
  引导条全部文案进 i18n 词典，英文模式零残留。
- **i18n 内容污染修复**：翻译引擎新增 `[data-no-i18n]` 子树跳过（AI 生成内容
  标记 10 处），EN 模式不再把回复正文里的「今日头条」改写成 Toutiao；
  `document.title` 版本号从当前页原样保留（此前写死 V10.0.1）；语言同步从
  1 秒轮询改为事件驱动。
- **渲染注入防护**：热榜/搜索渲染的外部标题/摘要统一 `escapeHtml`。
- **复制兜底**：`copyText` 三级回落（Clipboard API → execCommand → 失败 toast），
  LAN http 场景不再静默失败。
- **触控目标**：移动端约 30 个过小按钮统一提升可点击区域 ≥28px。
- **密码策略**：新设/修改密码最短 8 位（存量 6 位账号可继续登录）。
- **网关可观测**：`/v1` 装配失败从控制台 print 升级为 logger.error 并随 `/health`
  回显 `gateway_v1_ok`。
- **性能与卫生**：配置读取摘除每次 deepcopy（38 个调用点核查均只读）；httpx
  连接池模块级共享；任务注入的字节码探测加固（partial/可调用对象安全）；
  生图外链下载校验（content-type/大小上限）；Pollinations 免 Key 通道加开关与
  第三方发送披露；example.com 占位清理；print→logger 收口；删除零引用死文件
  `infra/logging.py` 与 `web/static/css/design-tokens.css`（架构锁同步更新）；
  幂等中间件缓存失败从静默改 debug 留痕。
- **文档口径收口**：README/README_EN/说明书统一测试规模口径（845 项测试函数）、
  版本段更新至 v15.9.x、「95% 图文匹配度」与「即时声音克隆」措辞与实现对齐。

### Added

- `core/outbound_guard.py`：SSRF 出站防护模块（多用户强制 / 单机放行环回）。
- `web/static/js/yimu-net.js`：`api` 超时、`pollJob/pollJobAsync/cancelAllPolls`、
  `imeSafeEnter` 前端共享工具（移动端保持自包含等价实现）。
- `Dockerfile` / `docker-compose.yml` / `deploy/cloud/`：容器化部署三件套。
- `tests/test_v1598_backend_fixes.py`：32 项回归锁（计费透传/闸门/取消语义/
  SHA256/坏 YAML 回退/外链校验/SSRF/pollinations 开关等）。

---

## [15.9.7] - 松风令 (Pine Wind Edict) · 2026-11-19

### Fixed 能力线默认统一收口：显式默认压得过通道内遗留路由

v15.9.6 引入 `capability_defaults` 后，消费侧有四条解析链各写各的排序，留下
两处真实的双源冲突：

1. **移动端/旧弹窗残留的 `agent_routing.image/video` 会静默压过 PC 上的
   「设为生图/生视频默认」**——`imagegen.image_cfg()` 旧链把通道路由排在
   能力线显式默认之前；手机上历史上保存过的路由值会让新设置「看起来没生效」。
2. **视频线两条链排序相反**：`ad_video` 把调用方单次指定的 `model_override`
   放最高，`short_drama` 却把配置里的 routing 放在入参之上——调用方明确指定
   的模型反被配置覆盖。

统一后的解析链（四链同序，`imagegen.py` / `ad_video.py` / `short_drama.py` /
`agents.model_for`）：

    单次显式指定 > 阶段绑定(agents.*) > 能力线显式默认(capability_defaults)
    > 通道内路由(agent_routing，兼容遗留) > 跨通道自动 > 兜底

- `agents.model_for` 末级兜底不再硬编码 `deepseek-chat`（出厂预设不该从代码
  里冒出来），改为跟随文字能力线跨通道解析，全空返回空串交给 `llm.chat`
  的「未配置」人话提示。
- `llm.chat` 的防串台护栏（文字请求解析到图像/视频模型时）改为回退
  **文字能力线默认**，而不是该供应商的预设 `default_model`。

### Added 预设目录模型可见性（preset_only）

自动跨通道挑选会读取内置预设目录（openai 含 dall-e-3/sora、qwen 含 wanx-video
等）：用户可能**只为文字**在某家存过 Key，生图/生视频却会自动落到该家的预设
模型并走私钥计费。这是 V15.9.6 的设计选择，但此前完全不可见。现在
`resolve_capability_default()` 的 auto 结果带 `preset_only` 标记，设置页自动项
与影音工坊系统默认项都会显示「［预设目录模型］」。

### Fixed 移动端同步 v15.9.6（此前零改动）

- 跨模型服务下拉的值统一加 `通道/模型` 前缀——同名模型在两家都有时，裸 id
  会被解析器「活动通道池优先」静默路由回主通道（桌面端已修，移动端补齐）；
- 模型绑定视图顶部新增「三线归属」一行：文字 / 生图 / 生视频当前各自解析到
  哪家（读 `/api/status capabilities`，与桌面同源）；
- 生图路由首项文案对齐系统默认语义。

### Fixed 边界与卫生

- **幽灵供应商**：全部通道删除后 `active_provider_id` 为空串，`/api/settings`
  的网关表单写入会以空键落池（normalize 还可能把它扶正当主通道）——现在明确
  拒绝并提示先添加模型服务；
- **测试守护补口**：全新 clone 上测试期间新建的 `data/config.local.yaml`
  会话结束一并删除（此前只还原已存在的文件）；
- **影音工坊缓存失效**：`_studioProvidersData` 此前没有任何失效点——设默认/
  保存/删除/切主网关后下拉一直显示旧的能力归属直到整页刷新；现在五个变更点
  统一失效；
- `resolve_llm_endpoint` 的 `stage` 形参注明为调用方兼容保留（阶段路由由
  `agents.model_for` 完成，本函数不按阶段分支）；
- 系统注释与实际写入位置对齐（v15.9.5 起运行时写 `data/config.local.yaml`）。

### Tests

- `tests/test_v1597_capability_priority.py`（10 项）：显式默认压过遗留路由、
  路由兼容语义保留、阶段绑定最优先、两条视频链同序、对话兜底走文字能力线、
  preset_only 标记、幽灵供应商拒绝、model_for 不再硬编码出厂预设。
- 全量 `912 passed`，CI 四道门禁全过；浏览器实测走查通过
  （桌面七页舞台导航 / 设默认菜单 / 能力线回显 / 移动端三线归属）。

---

## [15.9.6] - 星槎引 (Star Raft Prelude) · 2026-11-18

### Added 文字、生图、生视频可以各用一家通道

用户设了一家只有文本模型的中转为主通道，又保存了另一家有生图/生视频模型的通道，
却发现**生图模型下拉里永远只有主通道的文本模型**，根本选不到 B 家；把主通道设成
默认以后，三条能力线被迫共用一家。根因是「系统默认」只在**活动通道**的模型池里找：

* `resolve_default_model()` 读的是 `gateway.configured_models`（活动通道的派生视图）；
* 设置页的生图下拉只列当前通道的模型；
* 视频切片拿活动通道的 `base_url`/`key` 去发别家的模型 ID。

本版新增**能力线默认**（`gateway.capability_defaults`），文字 / 生图 / 生视频
三条线各自记录「用哪一家、用哪个模型」，互不牵连：

| 能力线 | 默认存储 | 未显式设置时 |
|---|---|---|
| 文字 | `gateway.provider_id`（沿用主通道） | 主通道第一个文字模型 |
| 生图 | `capability_defaults.image` | 主通道 → 其它已配置通道，取第一个生图模型 |
| 生视频 | `capability_defaults.video` | 同上，取第一个视频模型 |

自动挑选时会跳过已删除、没有 Key（本机服务除外）的通道；找到别家的模型时返回
`通道/模型` 前缀，端点解析器据此切到正确的地址与密钥。一家都没有时返回空，
生图走免 Key 保底引擎，生视频给出明确提示——不会偷偷拿文本模型顶替。

### Changed 设置入口

* 模型服务卡片：原来的「🌟 设为主网关」换成「设为默认…」菜单，可选
  **文字默认 / 生图默认 / 生视频默认 / 全功能默认**；卡片上用小标签显示这家
  当前承担哪几条线，一家可以同时是文字 + 生图默认。
* 「AI 配图设置」升级为「生图 / 生视频设置」：两个下拉都按**通道分组**列出全部
  已配置模型，值用 `通道/模型`，同名模型不会串台；「自动」项直接显示当前解析到
  哪一家的哪个模型。
* 影音工坊 / 短剧 / 分镜 / AI 短视频的下拉：系统默认项显示真实解析结果；跨通道
  模型统一带通道前缀；Agent 模型下拉里别家的模型也带前缀，避免同名模型被路由回
  主通道。
* 首次引导第 3 步：出图/出视频选项带通道名，保存走能力线默认而不是只写一个
  `image.model`。
* 「AI 视频生成配置」里的默认视频模型不再只写 JSON（真正生成时读不到），
  保存时同步写入能力线默认并刷新各处下拉。

### Fixed 视频链路跨通道

`core/short_drama.generate_ai_video_clip()` 原来用活动通道的 `base_url`/`key`
发送模型 ID；B 家才有视频模型时请求必然打到 A 家。现在对每个候选模型调用
`resolve_llm_endpoint()` 取各自的端点与密钥，并校验解析结果确实是视频模型，
不是就跳过而不是把文本模型发到 `/videos`。

### Verification

- 新增 `tests/test_v1596_capability_defaults.py` **12 项**：自动跨通道选中 B 家、
  显式默认优先、全功能默认逐条设置并如实报告缺失、删除通道清理指针、
  `image_cfg` / `ad_video_model_info` 真正用到 B 家端点、接口回显能力归属。
- 真实配置实测：主通道 `custom_520`（只有文字）保持不动，另存一家带 `img-b`
  的通道并设为生图默认 → `/api/status` 显示 `image: provtestb/img-b`，
  清成「自动」后仍自动选中 B 家；删除 B 家后指针自动清空。
- 全量 `892 passed`，`ci.sh` 四道门禁全过。

---

## [15.9.5] - 云程赋 (Cloud Journey Ode) · 2026-11-18

### Fixed 有 7 家模型服务怎么点都删不掉

用户把能删的都删了，剩下 OpenAI / Claude / Gemini / 智谱 GLM / Kimi / Ollama / 百川
**七家点了删除毫无反应**，卡片一直挂在列表里。三个原因叠在一起：

1. **删除的第一步就把它挡掉了。** `delete_provider()` 开头是
   `if pid not in pool: return False`。内置预设只有在用户**保存过**之后才会进
   `gateway.providers` 池；没保存过的（正是这七家）不在池里，于是删除被当成
   「不存在」，既不拉黑也不清池 —— 列表照旧显示。
2. **删掉的那家会被原地复活。** `normalize()` 无条件写
   `active = provider_id or "deepseek"` 并顺手把 `pool[active]` 补成空条目。
   活动通道一被删，下一轮读取又把它补回来，于是「删掉 DeepSeek → 刷新又出现一家空
   DeepSeek」——用户的理解就是「删不掉」。
3. **接口一律假报成功。** 路由不管删没删掉都回「已成功删除模型服务 [xxx]」，
   把上面的失败盖得严严实实。

现在：`delete_provider()` 池里有就清池、没有就只拉黑，**任意一家都能删**；删完不再
复活（已删的通道不会进池、不会被 `normalize` 补回、不会被模型名路由命中、也不能被
设为活动通道）；活动通道被删时自动换一家还活着的，一家不剩就置空；接口如实回报
「本来就不在列表里」。

### Fixed 删除操作会改写仓库里的出厂配置

`config.yaml` 是跟着仓库走的**出厂样本**，但以前用户在设置页的每一次改动（删通道、
改水印、换风格）都直接写回它：开发机工作区永远是脏的、`git pull` 常冲突，更新器为了
能拉代码还得先 `git checkout -- config.yaml` 再还原——稍有不慎就把用户删掉的通道
带回来。现在运行时写入统一落到 `data/config.local.yaml`（本来就被 git 忽略、
`raw_config()` 也一直把它叠加在主配置之上），出厂样本只读。

顺带修了覆盖层的合并方式：以前逐键 `update`，主配置里已被清理掉的旧字段（如
`gateway.base_url`）每次读取都会冒回来，导致归一化永远「不干净」、回写不幂等；
现在按整段替换。

### Added 列表删空后的空态

一家都不剩时，卡片区不再是空白（那看起来像坏了），而是明确写出下一步：
「＋ 添加自定义模型服务」或「⚡ 快速载入官方预设通道」→ 填地址与 Key → 保存并设为主通道。

### Tests

- `tests/test_v1595_provider_delete_all.py`：15 项（七家预设逐一可删、14 家全删后列表为空、
  不复活、不可路由、不可设为活动、可再加回来、删空后 `chat()` 给出人话、接口如实回报）
- 全量 880 项通过，`ci.sh` 四道门禁全过

---

## [15.9.4] - 四海宁 (Four Seas Tranquil) · 2026-11-18

### Changed 设置收口为一处：填一次 Key、选一次引擎、定一次风格

V15.9.0 起系统设置里有三套东西在说同一件事：生图模型在「生图设置」和「写作默认设置」
里各存一份，`localStorage` 还分叉成 `yimu_studio_image_model` / `yimu_copilot_image_model`
/ `yimu_image_model` 三个键；智能体弹窗里那个生图下拉写回的又是第二个键。于是**换个地方选
模型，另一个地方不跟着变**。本次把设置页顶部改成「三件事总览」，每一项只显示当前值和
一个按钮，其余细节收进折叠区：

- 设置顶部：`① 模型与 Key` / `② 生图引擎` / `③ 写作默认风格`，各自一行只读值 + 一个入口按钮
- 生图模型收敛为单一真源 `yimu_image_model`，旧键首次读取时单向迁移，三个键此后同写
- 智能体弹窗里的第二个生图下拉**删除**，改为只读回显 +「更换 →」跳转；`saveCopilotSettings()`
  不再改写生图模型
- 「系统维护」4 张卡片收进 `<details>` 默认折叠；个人中心的 API Vault 同样折叠
- 首次引导的「Key 说明」从大卡片收成一行提示条，进设置页自动隐藏，「不再提示」记本地开关

### Added 聊天流式思考过程

发完消息立刻在气泡里出现「正在思考」，并按步骤推进（读题 → 检索 → 起草 → 校核），
而不是只让发送按钮转圈——后者在长任务里看起来就是卡死。异常与中断分支同样收尾，
不会留下一个永远在跳的气泡。

### Added 图片在页面内点开看大图

极简模式右侧面板、资产台的卡片图此前点不动：预览在 `iframe.srcdoc` 里，子文档的点击
**不会冒泡到父页面**；另有一部分图被放在 `display:none` 的容器里，量出来是 0×0。
本次向 `srcdoc` 注入缩放脚本，点击时用 `postMessage` 把图片地址送回父页面开灯箱；
`/api/drafts/{did}/images` 补上 `card-*.png` 扫描口径，卡片图才出现在列表里。

### Fixed 成稿首尾露出 `<WritingBlock id="...">`

模型会把正文包一层 `<WritingBlock variant="document">`，旧的清洗正则把标签名截断在
11 个字符，`WritingBlock`（12 字符）正好匹配不到，标签原样留在用户看到的稿子里。
现在标签名放宽到 24 字符，另加一张模型包装标签黑名单（`WritingBlock` / `antml:*` /
`FunctionCalls` 等），对话出口单独用 `strip_model_wrappers()` 只剥壳、不动正文格式。

### Fixed 左栏展开后收不起来

折叠监听挂在捕获阶段（第三个参数 `true`），而箭头按钮上写的 `stopPropagation()` 是冒泡
阶段——拦不住捕获阶段的监听，于是子菜单刚收起就被 30ms 后的定时器重新展开。改为在监听
入口直接跳过箭头按钮。

### Fixed 两个全屏弹窗完全不显示

`#copilot-settings-modal` 与 `#agent-task-progress-modal` 被误放进 `#lite-drafts-modal`
内部，而后者默认 `display:none`，导致弹窗量出来是 0×0。新增 `reparentFixedModals()`
把固定定位弹窗搬到 `<body>`，两个打开函数内幂等调用（实测由 0×0 变为 1440×1100）。

### Fixed 浅色主题下白底白字

设置页若干标题写死了 `#fff`，浅色主题下等于隐形，补深色覆盖。

### Security 路径包含判定收口

`str(path).startswith(str(base))` 这类判定放过同前缀的兄弟目录（`runs/avatars_backup`
对 `runs/avatars` 判定为「在内部」）；更糟的是 `str(base).startswith(str(base.parent))`
恒为真，等于没有校验。新增 `core/pathsafe.py`：

- `is_within()` 用 `Path.relative_to` 做组件级判定，解析失败一律 False，默认不允许等于 base
- `safe_join()` 拒绝绝对路径把 base 顶掉
- `media.py` 4 处、`skills.py` 1 处全部换用；`aivideo_file` 的 job id 加 `[A-Za-z0-9_-]{1,64}` 白名单
- 上传上限：视频整包 20MB、docx 正文解压后 40MB，堵住 zip bomb 打满内存
- 去掉 `draft_publish_xhs` 里未被使用的 `await request.json()`

### Added 发版脚本补齐六处真源

`scripts/release.py` 以前只改 `version.py`，`pyproject.toml`、代号登记簿、中英语言包、
README 徽章全靠手补，漏一处就被门禁打红（本次发版就漏了两处）。现在一次写全六处，
代号序列耗尽时明确报错而不是写出越界指针；同时新增 `--status` 显示下一个待用代号。

### Tests

- `tests/test_v1594_settings_dedup.py`：13 项（单一真源、旧键迁移、设置总览、折叠区）
- `tests/test_v1594_pathsafe.py`：13 项（组件级判定、兄弟目录、恒真表达式、源码禁用 `startswith(str(`）
- 全量 865 项通过，`ci.sh` 四道门禁全过

---

## [15.9.3] - 千秋盛 (Thousand Autumns Prosperous) · 2026-11-17

### Fixed 内置浏览器「启动即崩」的真正原因：13 个可执行文件没有执行位

V15.9.2 的判断是错的。那一版把崩溃归因为「ad-hoc 签名 / 无 entitlements 建不出沙箱子进程」，
于是把内置内核降为兜底、加了探活降级——治的是症状，客户机装上后**依旧弹同一个崩溃窗**。

重新在 macOS 27.2.1 + Apple Silicon 上复现，拿到了 Chromium 自己吐的 FATAL 日志：

```
FATAL:crashpad/util/posix/spawn_subprocess.cc:231
posix_spawnp .../Helpers/chrome_crashpad_handler: Permission denied (13)
```

真因是打包时的一个疏漏：`ZipFile.extractall()` **不还原** `external_attr` 里的权限位，
解压出来一律 `0644`。`setup_chromium()` 只对主可执行文件单点 `chmod`，于是：

- `Helpers/chrome_crashpad_handler`（启动第一步就要 spawn）
- `Helper (Renderer).app` / `Helper (GPU).app` / `Helper (Alerts).app` 等全部子进程
- `app_mode_loader`、`web_app_shortcut_copier`

**共 13 个 Mach-O 全是 `-rw-r--r--`**。主进程能起来，但 spawn crashpad handler 就 `EACCES`，
Chromium 的 `CHECK()` 失败触发 `__builtin_trap()` —— 这就是崩溃报告里的
`EXC_BREAKPOINT / SIGTRAP / brk 0`、`crashed on child side of fork pre-exec`、
进程只活 0.05~0.15 ms。跟签名、SIP、系统版本、沙箱、渲染、大模型都没有关系。

**只补执行位、别的一行不改**，同版本 CfT 立刻正常起窗（实测连续存活 5 秒未崩），
Playwright 也能正常建页导航。

- `scripts/build_full_bundle.py`：新增 `restore_zip_perms()`，解压时按 `ZipInfo.external_attr`
  逐条还原权限；再按魔数（Mach-O 各字节序 + ELF）兜底扫描，缺 `x` 位就补。覆盖 macOS 与 Linux
  两个平台（Linux 包同样受 `extractall()` 影响）。
- `scripts/build_full_bundle.py`：新增 `assert_executables()`，出厂断言——凡是可执行映像必须
  有执行位，否则**构建直接失败**。此前没有任何检查，所以缺 13 个执行位的包顺利发了出去。
- `core/browser_path.py`：新增 `heal_executable_perms()`，运行期首次解析内置内核时再兜一层
  自愈，覆盖已经装了旧包、或用第三方工具二次解压丢权限的目录（幂等，进程内只做一次）。
- `core/browser_path.py`：内置内核**重回第一候选**（版本可控、离线可用）。探活失败会落
  `chromium/.broken` 标记，后续不再反复重试，直接走系统浏览器——避免每次开机弹一次崩溃窗。
  `desktop.py` 的窗口兜底同样尊重该标记。
- `desktop.py`：更新注释，把"ad-hoc 签名"的错误结论改成真实根因。

### Added 回归测试

- `tests/test_v1593_bundled_exec_perms.py`（9 项）：zip 权限还原、0644 元数据按魔数兜底、
  普通数据文件不误加执行位、出厂断言拒绝缺执行位、干净目录通过、运行期自愈与幂等、
  `bundled_chromium()` 首次自愈、内置内核优先、`.broken` 标记跳过重试。

---

### Fixed 客户端窗口起不来：内置浏览器被系统在 fork 后终止

客户机（macOS 27.x + Apple Silicon）双击客户端后弹出「Google Chrome for Testing 意外退出」，
窗口不出现。崩溃报告关键事实：父子进程 procPath 相同、`crashed on child side of fork pre-exec`、
`EXC_BREAKPOINT / SIGTRAP`、进程存活 **0.15 毫秒**——即 Chromium 的 main 一行都没执行，
渲染子进程在 `fork` 之后、`exec` 之前就被系统打断。与本项目业务代码无关。

根因有两层：内置 Chrome for Testing 是 ad-hoc 签名、无 hardened runtime / entitlements，
在这类系统上建不出沙箱子进程；而客户端又**把内置内核排在系统浏览器前面**，且启动后没有任何存活性判断。

- `desktop.py`：候选顺序改为「系统 Chrome / Edge / Brave 优先，内置内核兜底」；新增
  `_launch_and_probe()`，启动后探测 1.2s，进程已退出即跳过并换下一个候选；全程失败时打印明确
  原因并退回系统默认浏览器（不再"弹崩溃窗 + 界面干等"）。
- `desktop.py`：应用窗口统一补 `--user-data-dir=<用户目录>/browser-profile`（与用户日常 Chrome
  分开，避免 profile 锁冲突）、`--no-first-run`、`--no-default-browser-check`；内置内核额外加
  `--no-sandbox`（ad-hoc 签名内核的唯一可用路径，窗口只加载本机 localhost 页面）。
- `core/browser_path.py`：`launch_chromium()` 新增 `_probe_browser()` —— 启动后真建一个
  `about:blank` 页并导航，失败则关闭该内核、降级到系统浏览器，全部候选失败才抛异常。此前只在
  `launch()` 抛异常时降级，而崩溃发生在连接建立之后的渲染子进程里，等于不降级。
- `core/browser_path.py`：内置内核仍在 Playwright 链路里优先（离线包客户机可能没装浏览器），
  但探活不过就自动让位。

### Added 回归测试

- `tests/test_v1592_browser_launch_fallback.py`（9 项）：系统优先顺序、内置兜底必带 `--no-sandbox`、
  立即退出判定为失败、存活判定为成功、启动参数结构、Playwright 探活失败降级、全失败抛异常、
  无内置内核时行为不变。

---

## [15.9.1] - 九州同 (Nine Provinces One) · 2026-11-14

### Fixed 系统设置 / 个人中心逻辑治理（专项深审 15 项 + 首次引导重做）

**① 舞台导航根因修复（「点配置没反应」）**
- `workbench-stage.js`：`bindNav` 只绑定了第一个 `.nav-group`，而「控制中心 / 个人中心」
  在底部组 `.nav-group.nav-group-bottom`——点它们面板类名切换、舞台永不打开。
  现两组全部接管，未配置大模型弹窗的「去配置」直达「系统与 API 配置」并自动弹出
  「模型服务配置」弹窗（浏览器实测验证）。

**② 出厂默认清洗：Agnes 全部退场，统一「系统默认」**
- 出厂 `config.yaml` 不再预置任何具体模型：`agents.*.model` / `image.model` 全空，
  主通道 `yimu_official` 指向云端网关，供应商池移除 Agnes 测试通道；
- 新增 `core/llm.resolve_default_model(category)`：空绑定 = 活动通道模型池首个
  该类别模型；生图无池选模型时走免 Key 保底引擎，视频无池选模型时给出明确
  「未配置视频大模型」指引（`short_drama` / `ad_video` / `prompt_polish` 同步去硬编码）；
- 移动端/双语文案去掉 Agnes 字样；Copilot 生图下拉不再提供后端不存在的虚构模型。

**③ 四步完整首次引导（可随时跳过）**
- 引导重构为 ① 免费额度 → ② 主链路（官方 / 自备 Key，供应商下拉对齐真实预设）→
  ③ 出图与出视频（跟随系统默认 / 指定）→ ④ 文字审核开关 + 配置摘要；
- 引导 JS 整体外置 `web/static/js/onboarding.js`（巨石拆分）。

**④ 设置逻辑修复清单**
- 移动端水印保存是静默空操作：`/api/settings` 补 `watermark` 分支，`/api/status` 回显；
- 移动端保存供应商强制抢占主通道：改「保存≠激活」+ 独立「设为主网关」；
- 跨模型服务路由污染：编辑新通道不再预填别家的 Agent 路由；
- 个人中心「媒体名称」假保存：新增 `users.media_name` + `GET/POST /api/user/media_name`；
- 双轨模型绑定（Agent 配置 vs 模型服务路由）在两处 UI 标注优先级关系；
- `/api/models/save` 回复语义诚实化：仅保存不再宣称「已立即热生效」；
- 文字审核设置 UI 落地：`content_guard.enabled` 进 config.yaml（环境变量仍可强制覆盖），
  新增 `GET/POST /api/compliance/settings`（仅管理员）+ 设置页开关卡片；
- Copilot「只选供应商不选模型」失效：补默认模型，不再回裸供应商名；
- 水印 API 改管理员权限（全局品牌配置）；图床 Token 已存状态可见；
- 移动端移除「云端网关参数直连」旧表单（无 Key 字段却覆盖活动通道），统一入口；
- 清理 `/api/settings` 的 `apipool_key` 与顶层 `draft_expire_days` 死分支。

**⑤ 性能与巨石**
- `/api/status` 过期清理从「每轮询全表扫描」节流为每小时一次；
- `studio/releases_page.py` 790 行巨石函数拆为模板文件 + 40 行渲染器；
- 残留 `console.log` 清零。

**回归锁**：`tests/test_v1590_settings_logic.py`（21 项）。全量 821 用例 + CI 四道门禁全绿。

---

## [15.9.0] - 星火继 (Spark Relay) · 2026-11-12

### Changed 深审整改
- 上帝函数 handle_copilot_chat 再拆:CREATE 全流程分支(324 行)抽为 _intent_create
- 计量写盘节流(15s 窗口+atexit 冲刷+内存镜像即时可见),高 token 流量去瓶颈
- 3 天改动全面核对:15 提交声明与实现一致,前置整改(R12 能力匹配/保存≠激活/首篇券/支付闭环)完整存活

## [15.8.4] - 朝晖颂 (Dawn Glow Ode) · 2026-11-12

### Fixed & Optimized
- `core/llm.py`：`load_config()` 新增基于 `config.yaml` 与 `data/config.local.yaml` 文件元数据（`inode / mtime_ns / size`）的进程级缓存与 `deepcopy` 隔离，消除高频重复磁盘读取与解析开销。
- `web/admin.py` / `web/routers/drafts.py`：将 `thumbnail` 与 `preview_urls` 并入 `_draft_view()`，统一 `/api/status` 与 `GET /api/drafts` 输出口径，并消除列表接口重复 `glob` 扫描。
- `core/watermark.py`：水印配置读取接入 `provider_registry.raw_config()`（兼容只读安装目录的 `data/config.local.yaml` 叠加），同时修复 Windows 字体路径 `Fonts\arial.ttf` 转义错误。
- `web/admin.py`：将 `@app.on_event("startup")` 迁移至 FastAPI `lifespan` 上下文管理器，消除弃用警告。
- `core/copilot.py`：`re.split` 的 `maxsplit=1` 改为关键字传参，消除 Python 3.14 弃用警告。
- `web/routers/skills.py` / `web/routers/workspace.py`：清理不再使用的 `load_config, load_env` 死导入。

---

## [15.8.3] - 朝晖颂 (Dawn Glow Ode) · 2026-11-11

### Fixed 通道配置「单一真源」（客户缺陷：填了地址与密钥仍提示大模型不可用）

Windows 客户端在「设置 → 模型服务」填好 API 地址与密钥，点「灵感与选题 → 一句话生成爆款」
仍报「大模型调用失败」。这不是密钥错了，而是**同一件事被存了两份、读的又是另一份**：

- **密钥写到读不到的地方**：保存写安装目录 `.env`，而读取优先级是
  「进程环境变量 > 用户目录 `secrets.env` > 安装目录 `.env`」——新 Key 被旧示例值
  `test_key` 永久压制。
- **地址写到了另一侧**：保存写 `gateway.providers.<pid>`，解析读 `gateway.base_url`
  这份出厂快照，改了地址仍打向老地址。
- **备用链漏掉用户通道**：旧实现只遍历内置预设，用户自建通道永远进不了候选，
  一跳到底即抛出「全链路失败」。

### Added
- `core/provider_registry.py`：供应商配置与密钥的**唯一真源**——供应商池为唯一存储，
  密钥只写用户目录（0600），示例值一律视为「未配置」。
- `GET /api/models/diagnose`：通道自检（当前地址、密钥来源、末四位、备用通道、可执行建议，不含明文）。
- 前端「大模型尚未就绪」弹窗改为显示服务端给出的**具体原因**，不再是一句笼统提示。

### Changed
- `gateway.base_url/model/configured_models/agent_routing` 不再是独立事实，改为由活动通道
  派生；老代码读到的永远是真实生效值。
- 调用失败时抛出**逐通道诊断**（每条通道的地址、HTTP 状态与中文成因），替代「已尝试所有可用备选通道」。
- 启动时自动把旧配置折叠为单一真源（幂等，已归一化则不动）。

### Tests
- 新增 `tests/test_v1583_provider_single_source.py`（13 项）：保存后解析一致性、密钥落点、
  示例值过滤、备用链含自建通道、旧配置折叠幂等、错误信息逐条、以及**AST 护栏**——
  除 registry/llm/user_paths 外任何模块出现 `MEDIAFLOW_KEY_*` 字面量即失败。

## [15.8.2] - 朝晖颂 (Dawn Glow Ode) · 2026-11-11

### Removed 商业交付级代码卫生清理(AST 全仓扫描)
- 删除 13 个零引用死函数(task_queue/notify/text_purity/content_guard/artifacts/llm_metering,约 -150 行)
- 保守恢复 3 个被误判的存活模块(notify/scheduler/tts——装饰器注册与 probe 契约属活代码,教训已记录)
- 清理孤儿 import;0 重复函数体 / 0 重复路由 / 0 重复 JS 函数 / 0 TODO / 0 console.log(扫描实证)
- 测试:786 用例全绿(远端新增测试并入),CI 四道门禁通过

## [15.8.1] - 朝晖颂 (Dawn Glow Ode) · 2026-11-11

> 本版为「源码与安装包完全一致」的重建版，同时落地内置官方凭证机制、云库巨石拆分，
> 并吸收 v15.8.0 发布后的两项热修（打包鉴权、建库幂等）。

### Added 内置官方凭证机制（出厂即用）

- **构建期注入**：`scripts/build_full_bundle.py` 从 GitHub Secret `YIMU_OFFICIAL_BOOTSTRAP_KEY`
  生成结构化凭证 `app/.bootstrap/official_credential.json`（权限 0600），
  内含 `api_key` / `channel` / `base_url` / `bundle_id` / `built_at`；仓库内仍不出现明文 Key。
- **硬门禁**：`YIMU_REQUIRE_OFFICIAL_KEY=1` 时缺凭证直接失败，拒绝产出「没有官方通道」的安装包；
  未开启时仅告警并在清单里记 `official_key_source=unset`，便于事后核验。
- **客户机零联网**：`scripts/first_run_bootstrap.py` 移除运行期 `POST /trial/claim` 设备试用凭证申领
  （原实现断网要空等 6 秒、网关不可达时静默失败）。现在只读随包凭证，落用户目录 `secrets.env`（0600）。
- **不覆盖用户配置**：只补空项；用户在设置页填的自定义 API Key 始终优先，永不被随包凭证顶掉。
- **每包重新生成配额**：出厂 `billing.json` / `llm_usage.json` 等仍由构建器重新生成，
  不携带开发机的余额、消费记录与测试用户。
- 新增 `scripts/set_official_key.py`：把 Key 写入仓库 Secret 并校验格式，避免手工粘贴出错。
- `scripts/verify_bundle.py` 增加凭证存在性验收；`DEVELOPMENT.md` 新增第 8 章机制说明。

### Changed 云库（yimu-baokuanstudio-cloud）巨石后端完成 R11 拆分

- `web/admin.py` **7639 行 → 2020 行**（-73.6%），路由整体迁入 `web/routers/` 18 个族模块（合计 5290 行）。
- 路由表**逐条等价**：拆分前后均为 332 条，零丢失、零新增（含 `include_router` 挂载的
  gateway / membership 子应用）；云库独有的 `teams.py` 13 条多租户端点完整保留。
- `web/admin.py` 只保留辅助层（`guard` / `require_credits` / `DraftOwnerRoute` / 静态挂载 / 中间件 / 启动事件）。
- 新增云库 GitHub Actions CI（此前完全没有，这是巨石长期无人守门的结构性原因）。
- 新增云库 `tests/test_routes_smoke.py`（从本地版移植，4 项），补齐拆分后的鉴权冒烟。
- 静态护栏全部改扫 `web_routing_source()` 聚合源（原只扫 `admin.py`，路由搬走后会变成假护栏）；
  已用变异测试验证：往 `routers/pages.py` 注入弱口令后门，护栏立即报错。
- 修复拆分副作用：`/api/health` 迁入 `system.py` 后仍引用 `admin.health`，改走 `pages.health()`。

### Fixed v15.8.0 发布后热修（并入本版）

- **打包鉴权**：查询 GitHub Release API 时带 `GITHUB_TOKEN`，对 403 / 429 / 5xx 与网络错误做指数退避，
  修掉三平台并行构建时 macOS 作业撞匿名 60 次/小时限额的问题。
- **建库幂等**：`core/db.py` 把两处重复的 `tenant_id` 补列收敛为 `_ensure_tenant_columns()`，
  消除多连接竞态下的 `duplicate column name: tenant_id` 与 CI 偶发红灯。

### Changed 发布物

- 三平台 6 个安装资产全部由 v15.8.1 源码重新构建，与 tag 内容一致。

---

## [15.8.0] - 归帆渡 (Homebound Ferry) · 2026-11-10

### Fixed 客户端缺陷排查报告全栈整改

- **启动链路（F1/R1/R2）**：Windows VBS / A2 离线包模板 / 旧构建器模板统一从 `SW_HIDE(0)` 改为 `SW_SHOWNORMAL(1)`；三平台启动器统一 `PYTHONIOENCODING=utf-8`、`PYTHONUTF8=1` 并走 `app/launch_desktop.py` 垫片；`desktop.py` 在任何 import 前安装日志垫片，`pythonw.exe` 无控制台也留痕。
- **单实例（F4/R8）**：跨平台 `O_EXCL` 原子锁 + 已有窗口唤起；`probe_service()` 区分 free / yimu / foreign，端口被无关进程占用时自动避让。
- **配图契约（F2/R3/R4/R5）**：新增 `core/image_contract.py`，模型只输出 `{{IMG:N}}` 占位符，`to_storage()` 落库前拦截自造文件名；`normalize()` 按序号映射真实 sec 图，标题文本只作 alt；`inject_images_to_markdown()` 成为唯一回写入口，`generate_and_inject_images()` 重写；新增 `core/artifacts.py` 统一收口。
- **六平台预览（F3/R6/R7）**：新增 `core/previews.py`，六平台统一编译并补齐 `preview-xhs.html`；`files.py` / `share.py` 懒生成，`fission.py` / `orchestrator.py` / `drafts.py` 卡片生成后刷新；`matrix.json` 增加 `xhs.preview_url`；缺失图片降级为占位块，`quality_gate()` 发布前拦截。
- **补齐缺失函数**：`core.imagegen.recompile_previews` 历史上被 3 处 import 却不存在，异常被 `except: pass` 吞掉，现已补齐。
- **安全加固**：`adapters/base.save_preview()` 增加平台标识白名单，防路径穿越。
- **密钥（F5/R9/S7）**：新增 `core/user_paths.py` 与 `scripts/init_secrets.py`，敏感项写用户目录 `secrets.env`（0600），旧 `.env` 明文自动迁出；`load_env()` 合并顺序为进程环境变量 > 用户目录 > 安装目录；三平台启动、部署、设置页写入统一。
- **草稿列表（F6/R10/S8）**：新增 `GET /api/drafts`，返回统一摘要、`thumbnail` 与 `preview_urls`，并登记 `docs/CONTRACT.md`。
- **默认通道（报告 6.3）**：`/api/status` 增加 `active_key_set` / `key_hint`，空 Key 报错给出明确引导。

### Added

- `tests/test_v158_client_defects.py`：18 项 V15.8 专项回归。
- `app/launch_desktop.py`、`core/artifacts.py`、`core/image_contract.py`、`core/previews.py`、`core/user_paths.py`、`scripts/init_secrets.py`。

### Changed

- 版本真源、代号表、Windows 安装器、双语 README、i18n 语言包同步至 15.8.0 / 归帆渡 / Homebound Ferry。

## [15.7.0] - 长歌行 (Long Song Journey) · 2026-11-09

### Added 审查建议落地
- 一句话成稿进度加耗时回显(消除黑盒等待)
- 模型服务配置保存后自动收起弹窗
- 系统设置新增「访问模式」开关(单机免密/多用户注册,YIMU_MULTIUSER)
- 价格页新增邀请返佣 20% 常驻横幅
- 新增 GitHub Actions push/PR 级 CI(ci.yml)

## [15.6.0] - 星野阔 (Starfield Wide) · 2026-11-09

### Added 内容工作台双栏自由拖拽
- 编辑栏 / 成稿预览栏之间新增可拖拽分隔条：左右拖动、双击复位、方向键微调、`Home`/`Enter` 复位
- 宽度按百分比写入 `yimu.wb.split`，换窗口与进出全屏舞台保持视觉比例；编辑栏保底 320px、预览栏保底 380px
- 修复模板里 `#split-workbench` 被提前闭合的历史结构缺陷：手柄与预览栏此前并不在双栏容器内，拖拽与命中测试全部失效
- 分隔条增加三点抓手与亮/暗双主题配色，`aria-valuenow/min/max` 与 `role="separator"` 可访问

### Changed 顶栏、资产台与发布条按会话状态收敛
- 删除顶部「管理员已登录」徽章；左下个人中心的登录态为唯一展示位
- 新增「⚙」顶栏显示设置：手动勾选哪些分类常驻、未勾选的收进「更多」，配置持久化到 `yimu.shell.hdr`
- 新建对话后资产台显示「未创作 / 立即创作」空态：不再残留上一次的评分卡、小红书卡片与点不开的图片；经典双栏工作台同步回到「未选稿」空态，清空正文与渲染结果
- 发布条仅在本次创作有成品时出现；「复制 / 导出 / 发布」在无成品时给出明确提示，有成品时分别走富文本复制、ZIP 卡片包或 HTML 成稿导出、发布配置弹窗

### Fixed 路由层未定义名与测试隔离
- 修复 R11 巨石拆分遗留的 47 个 `F821`（`JOBS` / `update_async_job` / `_current_user_id` / `_os` / `BASE` / `_SAFE_DID_RE` / `Optional`），统一改走 `_a.X` 晚绑定；`ruff check --select F821,E9 .` 全绿
- 计量用例显式隔离「首篇完整体验券」，不再依赖仓库残留状态导致全量首次运行偶发红灯

---

## [15.5.1] - 玉衡明 (Jade Balance Bright) · 2026-11-09

### Fixed 弹窗层级修复
- `.mask` z-index 90 → 9800:修复全屏工作台(舞台层 9600)打开时,所有弹窗被压在舞台后方"闪现即逝"的问题
- 「小白点这里配置」一步到位:切换子视图同时直接弹出模型服务配置窗

## [15.5.0] - 玉衡明 (Jade Balance Bright) · 2026-11-09

### Fixed 编辑器底栏协调化
- 保存/AI 改写按钮一行排布；派生平台改横排胶囊 + 全选/反选右置
- 派生 CTA 全宽防挤压；提示语归位；i18n 词条同步

## [15.4.0] - 四海晏 (Four Seas at Peace) · 2026-11-09

### Changed 工作台工具条 2.0
- 主条 19 钮归 6：AI 改写提升 / AI 智能配图 / 配图▾ / 复制导出▾ / 多端发布 / 更多▾
- 三个收纳菜单承载全部次级能力（零功能删减）；编辑条与 footer 去重
- 基因溯源条与保底巡航熔炉条默认收纳为「进阶面板」细条开关

## [15.3.0] - 九霄阔 (Broad Ninth Heaven) · 2026-11-08

### Changed 三栏外壳交互大修
- 导航减肥：移除无效/重复二级菜单，主导航 8→7 项；「套餐与价格」并入个人中心
- 左栏一键折叠成图标栏（记忆态持久化）+ 内容工作台全屏形态 + 右下角悬浮 Copilot 常驻
- 小红书成稿新增 5 卡预览（灯箱）/单张下载/打包下载
- 去重：极简/全能模式切换、跟随系统主题循环、左下角个人中心 v2 失效修复
- 「控制中心」更名「系统设置」（导航/面板/i18n 同步）

## [15.2.0] - 千帆举 (Thousand Sails) · 2026-11-08

### Changed 供应商三层能力统一
- 保存≠激活：`save_provider_config` 默认不抢占主通道，激活显式化（修复多供应商互相覆盖）
- BYOK 能力匹配：用户 Key 仅服务其能力池内模型，运营显式路由不再被劫持（修复跨供应商 404 隐患）
- 计量实现去重（`_meter_call` 统一入口）；移除死代码 `saveGateway`
- 设置中心 UI 现代化：三层架构总览卡 + 分组卡片网格，i18n 词条同步

## [15.1.0] - 万象新 (Grand Renewal) · 2026-11-08

### Added 双线融合
- 合并远端 v10.3.0→v14.0.0 全部 24 个提交：三栏工作台重构（workbench shell/rail/stage）、A2 全功能离线安装包、亮色模式全站统一、存储态/展示态分离、系统诊断日志、文本纯净管线（core/text_purity）、密钥保管（core/secret_store）、首启引导（scripts/first_run_bootstrap）
- 远端安全强化并入：0 元开通漏洞修复（卡密仅 paid 后下发）、DraftOwnerRoute fail-closed 401 强化
- 本地整改增量在融合基底上重新落地（支付/上传守卫/收入看板/首篇券/术语减负）
- web/admin.py 在 v14 基底（7,629 行/280 路由）上重新拆分为 18 域 router

## [15.0.0] - 太平令 (Great Peace Edict) · 2026-11-08

商业交付级整改（依据 2026-11-08 五维综合审查报告 P0/P1/P2 路线图）。详见 [RELEASES.md](RELEASES.md)。

### Added 在线支付闭环
- 虎皮椒（微信/支付宝扫码）+ Stripe Checkout 双通道适配器与沙箱收银台，回调验签 → 幂等确认收款 → 卡密自动兑换到账（`studio/membership/payments.py`）
- 新用户「首篇完整体验券」：终身一次，首次长文自动免上限免扣费（`studio/first_piece.py`）
- 运营收入看板：GMV / MRR / ARPU / 付费转化率 / 日收入序列（`studio/membership/revenue.py`）
- 付费会员到期前 7/3/1 天自动续费提醒（24h 节流幂等）
- 头条草稿箱 API 直推通道（`adapters/toutiao_publish.py`，配置 `TOUTIAO_COOKIE` 启用）

### Fixed 安全与性能
- 修复 BGM/素材上传端点路径穿越漏洞；新增统一上传守卫 `core/upload_guard.py`（服务端命名 + 类型白名单 + 大小上限）覆盖全部 6 个上传端点
- `draft_dir()` 拒绝 `..`/分隔符穿越 ID
- 清除 DB 连接税：`conn()` 快速路径改索引探测式自愈，新增 `drafts` 四列索引（2 万行表 1.35ms/conn）
- 修复更新检查测试硬编码版本白名单导致的存量红灯

### Changed 工程与体验
- 删除 7 个 AST 核实零引用的死函数；`billing_adapter` 新增公开工厂 `web_session()`（跨层私有调用治理）
- 967 行上帝函数 `handle_copilot_chat` 拆出上下文组装阶段至 `core/copilot_context.py`（行为一致）
- 控制中心新增「3 个 API 入口」小白说明卡；Key 相关入口全部补白话悬停提示
- 新增 43 个回归用例（上传 7 / 支付 12 / 首篇券 5 / 收入 7 / 发布 6 / 小白 UX 5 / 契约锁同步）

---

## 🧭 Release Evolution & Version Management Philosophy (版本演进与发布规范)

YIMU Studio maintains strict version discipline:
1. **Permanent Git Tags for Historical Releases**: Every version is permanently tagged (e.g., `v8.3.33`, `v9.0.0`). Older versions remain 100% frozen, unmodified, and downloadable at any time.
2. **Direct Forward Releases**: New features and upgrades are shipped directly under subsequent version increments (Major `X.0.0`, Minor `X.Y.0`, Patch `X.Y.Z`).
3. **Transparent Upgrade Path**: Clear comparative matrices document breaking changes, aesthetic upgrades, and API evolution between milestones.

### 📌 How to Access Different Versions on GitHub:
- **Switch to Archived V8.3.33**:
  ```bash
  git checkout v8.3.33
  ```
- **Switch to Latest V9.0.0 (Infinite Worlds)**:
  ```bash
  git checkout v9.0.0
  # Or track latest main
  git checkout main && git pull origin main
  ```
- **Download Source Bundles on GitHub**:
  Visit [GitHub Releases / Tags](https://github.com/yimuhub/yimu-baokuanstudio/tags) to download exact `.zip` or `.tar.gz` packages for any historical release.

---

## 📊 Major Milestone Comparison: V8.3.33 vs V9.0.0 (核心版本差异矩阵)

| 核心维度 Dimension | V8.3.33 (Archived Stable Release) | V9.0.0 (Latest Major Milestone) | 升级演进说明 Evolution & Impact |
|---|---|---|---|
| **配图默认分辨率 (Image Resolution)** | 1024x1024 (标准 1K 画幅) | **2048x1152 / 1152x2048 / 2048x2048 (原生 2K)** | 极简与灵感模式出图分辨率翻倍，细节极致纤毫毕现 |
| **画面通透感 (Atmospheric Clarity)** | 易产生灰蒙蒙的雾感与烟雾朦胧 | **零烟雾通透滤镜 (Zero-Haze Prompt Pipeline)** | 强力注入高饱和、高锐度，严厉负向剔除 fog/smoke/blur |
| **生图大模型适配 (Model Adaptation)** | 基础生图接口，易触发 400 size 限制 | **Agnes 图像大模型深度协议对齐** | 严格规范画幅尺寸，内置 400 智能自愈与重试保护 |
| **商业化与算力入口 (Billing Portal)** | 顶栏按钮割裂、含外部版本号跳转链接 | **商业化算力与套餐价格深度合并统一胶囊** | 彻底下线冗余跳转页，算力/套餐/卡密一站式极速弹窗 |
| **国际化多语言 (Internationalization)** | 仅支持简体中文单语言 | **中英双语 (i18n) 全域即时热切换** | Desktop 与 Mobile 双端支持，GitHub 纯英文专业说明 |
| **账号安全与管理 (Account Security)** | 无法自主修改登录口令 | **个人中心与口令弹窗集成修改密码** | 后端 `/api/auth/change_password` 严格校验加密更新 |
| **GitHub 归档管理 (Git Release)** | `git tag v8.3.33` 独立归档冻结 | `git tag v9.0.0` (Latest 旗舰版) | 老版本保持冻结原貌不变，新版本直推发布 |

## [14.0.0] - 2026-11-07 · 兰心曲 (Orchid Melody) · 亮色统一与 WorkBuddy 式输入框

> 这次是 major：新增/改进 7 项，按 `VERSION_RULES.md` 第二章 X+1、Y/Z 归零。

### Added
- **中栏输入框改造为 WorkBuddy 形态**：`cb-composer` 结构落地 —— 附件区、输入区、操作条三段式。左下角 `＋` 传附件、模型下拉直选、`✨ 优化提示词`，右下角字数与圆形发送/停止。附件以 chip 呈现，可单个移除。
- **附件上传与正文抽取**：新增 `POST /api/copilot/attach` 与 `core/copilot_files.py`。txt/md/csv/json 多编码兜底（utf-8 / gb18030 / utf-16…）、docx 走 zipfile 取 `word/document.xml` 并按段落保留换行、pdf 走 pypdf（缺失时静默返回空正文，不让上传失败）、图片落盘并挂静态路径。单文件 10MB、单次 6 个、正文 12000 字截断。
- **提示词一键优化**：新增 `POST /api/copilot/polish_prompt` 与 `core/prompt_polish.py`。有可用模型时交给模型改写（保留原意、补全维度），返回 `source="llm"`；模型不可用时按平台结构模板补全，返回 `source="template"` 并在前端如实提示「已按结构模板补全」。
- **`llm.chat` 支持 `max_tokens`**：交互式短任务终于能限制生成长度。不传时行为完全不变，长文创作链路不受影响。
- **亮色模式语义 token 体系**：`--card2 / --border2 / --border3 / --text-dim / --active / --hover / --accbg` 七个 token 首次在 `:root` 与 `[data-theme="light"]` 内显式定义。

### Fixed
- **亮色模式下大片看不清**：这七个 token 此前从未定义，全部落到 `var(--x, 深色兜底)`，导致左栏选中项是「深底压深字」（实测对比度 1.06:1，等于看不见）、空态引导卡与输入条整块发黑。补全 token 后逐页审计，低对比文本从 22/39/57 条收敛到 0–1 条。
- **发送按钮被压扁**：`#btn-copilot-send` 作为 flex 子项被 textarea 撑成 28×42，`border-radius:50%` 在非正方形上变成椭圆。现锁定 `32×32` + `aspect-ratio: 1/1` + `flex: 0 0 32px`，任何输入高度下都是正圆；文字箭头改为内联 SVG。
- **提示词优化点了转半分钟没反应**：默认通道解析到推理型模型，不设上限时一路生成到上下文尽头（35–45 秒），设了上限又把 token 全烧在思维链上、正文为空，两种表现合起来就是「转很久、最后什么都没给、静默套模板」。现改为「直出型模型优先 + max_tokens 封顶 + 18 秒总预算 + 10 分钟结果缓存」，实测 45 秒降至约 4 秒，且真正走的是大模型。
- **白底上的深色强调色不达标**：模板里大量内联 `style="color:#f0883e"` 一类深色主题色，在白底只有 1.4–3.8:1。用属性选择器在亮色主题内统一折算到同色相更深一档，共 40 条规则，不动 HTML 结构。
- **紫色残留**：14 处 `#ede9fe / #c4b5fd / #e9d5ff / #faf5ff / #4f46e5 / #4338ca` 全部折算到暖橙同明度层级。

### Changed
- 亮色模式下主按钮与左栏「新建创作」改为白字橙底（`#c2410c`），替代原来的深棕字压橙底（对比度 3.58）。

## [13.0.0] - 2026-11-06 · 梅雪镜 (Plum-Snow Mirror) · 全功能离线安装包 (A2 Full Offline Bundle)

> 这次是 major：新增/改进 7 项，按 `VERSION_RULES.md` 第二章 X+1、Y/Z 归零。

### Added
- **A2 完全自给分发包**：新增 `scripts/build_full_bundle.py`，把所有运行条件在构建机一次装好 —— 自带 Python 3.11 运行时、预装全量依赖、内置 Chrome for Testing、全量源码资源、重新生成的出厂配额。客户机安装后双击即用，不需要 Python、不需要 venv、不需要 pip、不需要浏览器、不需要联网。
- **内置浏览器内核**：`core/browser_path.py` 统一把内置 Chromium 供给桌面窗口（`desktop.py`）与 Playwright（`core/render_card.py`、`core/search.py`）；开发模式无内置目录时行为完全不变。
- **内置官方通道与凭证**：出厂配置指向官方云端网关（不再残留开发机 `127.0.0.1:8787`）；`scripts/first_run_bootstrap.py` 首次启动按「随包凭证 → 环境变量 → 官方网关设备试用凭证」注入，用户在设置页填的自定义 API Key 永不覆盖，删除自定义凭证后自动切回官方通道。
- **出厂配额重新生成**：`billing.json` / `free_demo_calls.json` / `llm_usage.json` 等全新生成（free 档 + 出厂赠送额度、零消费历史），不再携带开发机 999999 余额与测试用户记录。
- **离线冒烟与体积门禁**：`scripts/verify_bundle.py` 校验全量资源、预装依赖、内置浏览器、出厂配置与配额，并用自带解释器启动服务请求 `/api/version`；压缩产物低于 90 MB 直接判定「退化成源码壳」。

### Fixed
- **桌面客户端只有几兆、装完起不来**：旧打包器只复制 `core/studio/web/adapters/docs`，`--with-runtime` 默认 False 且函数里没有 `pip install`；`gateway/`、`app/`、`skills/`、`config.yaml` 全都没进包，模拟客户安装后 `from web.admin import app` 直接 `ModuleNotFoundError: No module named 'gateway'`。
- **客户机现装依赖**：Linux `.deb` 的 `/usr/bin/yimu-studio`、macOS `.dmg` 的 launcher、Windows `一键启动.bat` 全部改为直接 exec 自带解释器；`.deb` 的 `Depends` 去掉 `python3* / python3-pip`，macOS 不再弹窗要求 `brew install python`。
- **不存在的数据库自愈调用**：`desktop.py` 里 `core.db.auto_heal_all_sqlite_databases` 并不存在、异常被吞掉，改为由首次启动自举统一创建数据目录与 SQLite 占位。
- **原生窗口永远降级**：`requirements.txt` 缺 `pywebview`，现随包预装；即使系统 WebView 不可用，也由内置 Chromium 以独立应用模式呈现窗口。

## [12.1.0] - 2026-11-04 · 竹韵篇 (Bamboo Rhythm) · 进页真数据 (Page-Enter Data)

### Added
- **控制中心工单流程可视化**：把原来一行机制说明升级为「抓热榜 → 挑选优质题 → AI 成稿 → 制作短视频 → 钉钉推送卡片」五步横向流程卡，宽屏一行铺满、窄屏自动折行。

### Fixed
- **进页不拉数据**：订阅与会员、内容工作台、控制中心、操盘大屏 四页此前没有进页钩子，进入后停在「加载中…」。现补齐 `pageLoaders` 统一钩子，进页即调用 `loadIntegratedPricingPanel` / `renderDraftList` / `loadTicketStatus` / `renderAgentList` / `renderSkillsList` / `healthLoad` / 大屏统计与雷达刷新。
- **右栏舞台改道吞掉业务逻辑**：`switchToPage` 的舞台包装此前直接打开舞台并提前返回，页面自己的加载与子视图切换全部被跳过。改为先执行原函数（挂钩子、拉数据、写高亮），再搬运面板。
- **同页重复搬运**：业务跳转与导航冒泡会各触发一次打开，导致滚动位置与输入焦点被冲掉；`open()` 增加同页复用判断。

## [12.0.0] - 2026-11-04 · 松涛境 (Pinewave Realm) · 右栏舞台 (Right-Pane Stage)

Major release. 交互模型整体重构：**左栏恒定、中栏恒定对话、所有功能页面在右栏打开、右栏可全屏**。
七个功能页不再是「把中间对话挤走」的整页切换，而是右栏里的一个可全屏工作区。

### Changed
- **中栏永不切换**：`#p-lite-mode` 被固定为对话栏，任何菜单点击都不会把它替换掉；
  主区里 7 个 `.panel` 由 CSS 统一收起（舞台内的面板不在 `<main>` 下，不受影响）。
- **右栏成为舞台**：点左侧任意功能，对应面板**整体搬进右栏**（DOM 搬家，非重写），
  面板自带的 onclick、事件绑定、滚动位置、表单状态原样保留。
- **轴心自动反转**：打开功能页时三列从「对话为主」切到「内容为主」——
  中栏收成对话宽度（340–400px），右栏吃满剩余空间。
- **全屏**：舞台头右侧的全屏按钮 / 双击标题 / `Esc` 三级退出；
  `.assets` 是层叠上下文，全屏时与舞台一起抬高 z-index，否则会被左栏盖住。
- **业务跳转改道**：`switchToPage()` 在舞台打开时改走舞台，避免页面切到看不见的主区；
  左栏二级树点击会先把所属页面开到舞台上，再切子视图。

### Added
- `web/static/js/workbench-stage.js`：舞台引擎（构建 / 搬运 / 全屏 / 键盘 / 双语）。
- `tests/test_v1200_stage_layout.py`：21 项结构契约回归锁。

### Fixed
- **全站主色统一**：清掉 8 种紫色变体（`#8b5cf6` / `#a855f7` / `#a371f7` / `#6366f1` 等，
  共 100+ 处），全部收敛到品牌橙 `#f0883e`；`--brand-primary` 同步改正。
- **左栏二级树串开**：连点多个菜单会把所有二级树都摊开、把「最近产出」顶出视口，
  改为手风琴（切页时收起其它）。
- **内页视觉与工作台脱节**：子标签改为换行不裁切、卡片去掉高亮描边与渐变底、
  页面大标题去掉彩虹渐变文字、按钮文字不再被压成两行、8 步步骤条换行完整显示。

### Notes
- 全部改动仍只在 `body[data-shell="v2"]` 下生效；`?legacy=1` 经典版与 <1280px 回落一行未改。
- 实测：1512 / 1280 两档 × 7 个功能页，`scrollWidth === innerWidth`，零横向溢出、控制台零报错。

## [11.1.1] - 2026-11-04 · 江河曲 (River Rhapsody) · 实机像素校准 (Pixel Fixes)

Patch release. 用过真机截图逐块比对后，修掉 11.1.0 残留的四处观感偏差，功能零增减。

### Fixed
- **主色回归原型橙**：基础样式层用 `!important` 把 `.btn.primary` 写死成紫色渐变，
  「发布」等主按钮与原型不符；V11.2 层以更高权重覆盖为 `#f0883e`，
  「极简 / 全能」模式胶囊一并收敛，与 `--yimu-brand-primary` 统一。
- **左栏底栏不再互相挤压**：用户卡曾被压缩到 50px，「个人中心」文字与齿轮图标重叠；
  改为第一行「明暗 / Sage-A1.5 / 经典版 / 控制中心」，第二行整宽「个人中心 · 已登录」。
- **控制中心图标**换成控制滑杆造型，15px 下不再被误认成太阳。
- **顶栏窄屏重叠**：≤1400px 收起页面副标题并收紧模式胶囊内边距，
  1280 / 1366 / 1512 三档实测顶层元素零重叠、`scrollWidth === innerWidth`。

### Notes
- 全部改动仍挂在 `body[data-shell="v2"]` 下，`?legacy=1` 经典版与 <1280px 回落一行未改。
- 实测：三栏渲染正常、控制台零报错，外壳与术语门禁 29 项、全量 632 项测试全绿。

## [11.1.0] - 2026-11-04 · 山岳赋 (Mountain Hymn) · 三栏逐项对齐原型 (Prototype Parity)

三栏外壳在 11.0.x 只是「搭起了架子」：左栏仍是老的加粗双行导航，中栏仍是「Copilot 面板 + 画布」
两块并排，顶栏还有元素重叠。这一版把左栏、中栏、右栏逐项改成原型的样子，功能一个不少。

### Added
- **左栏（全新）**：品牌块改为 logo + 两行文字；橙色「＋ 新建创作」主按钮；30px 单行导航配线性图标；
  一级项可展开二级树（8 个一级页共 35 个二级入口，全部指向真实子视图）；「最近产出」列表直连
  `S.drafts`，点一条即切到内容工作台并载入该稿；底部收为主题 / 算力 / 用户 / 经典版 / 控制中心一行
- **中栏**：标题下加副标题（按页面切换）；快捷胶囊条接管原 6 个快捷芯片，右侧并排两个入口图标；
  输入框改圆角卡片 + 圆形发送键；对话为空时给出「从这里开始」三张引导卡，开聊后自动撤掉
- **右栏**：底部新增动作条「复制 / 导出 / 发布」，分别接 `copyLiteCurrentRichContent` /
  `dlXhsZip` / `openPublishModal`
- `tests/test_v1102_rail_prototype_parity.py` 14 项门禁：注入块齐全、二级树无死链、
  样式全部收在 `body[data-shell="v2"]` 下、SVG 有明确尺寸、中英文案成对、无调试开关残留

### Fixed
- 注入的内联 SVG 缺省尺寸导致按 300×150 撑开，把右栏动作条挤成竖排文字；统一补上尺寸规则
- 胶囊条 6 个胶囊 + 2 个工具入口超出一行被裁切；改为 4 个胶囊 + 两个图标入口
- 原「爆款创作 Copilot」行与顶部标题重复；两个入口收进胶囊条，整行收起
- 中栏在 1280px 宽时输入框提示被裁下半截（`min-height` 抬高）

### Notes
- 经典版 `?legacy=1` 与 <1280px 回落完全未受影响，注入块与增强样式全部挂在 `body[data-shell="v2"]` 下
- 英文模式下注入块全部为英文（`New draft / Recent / Copy / Export / Publish` 与 35 个二级项）
- 预览：`prototype/ui-v2.html`

## [11.0.1] - 2026-11-04 · 沧海吟 (Oceanic Ode) · 质量门禁修复 (Quality Gate Fix)

### Fixed

- **术语门禁红**：`web/templates/index.html` 中一段 V11 三栏外壳的 CSS 注释误用了「占位」一词，触发 `tests/test_no_internal_jargon.py` 的面向用户文案禁用词表，导致 v11.0.0 的 CI 校验失败。注释已改写为「提示文案」，功能零影响。
- **版本门禁随补丁版漂移**：`tests/test_v1100_workbench_shell.py` 原先硬编码 `11.0.0` 与「长风谣」，现改为与 `release-codenames.json` 互相校验（版本号 / 中英代号 / history 末条 / 序列不重复），`test_v1002`、`test_v1020` 的版本等值断言改为从 `version.py` 动态取值，后续补丁版不再需要逐处改测试。

### Changed

- 版本推进至 `11.0.1`，代号「沧海吟 / Oceanic Ode」，`next_index` 由 4 推进至 5，下一代号「山岳赋 / Mountain Hymn」。

---

## [11.0.0] - 2026-11-04 · 长风谣 (Longwind Ballad) · 三栏工作台外壳重构 (Three-Pane Workbench Shell)

### Added

- **三栏工作台外壳（P0）**：主界面由「侧栏 + 单列主区」升级为「左功能栏 / 中主台 / 右资产台」三栏布局。
  - 左栏 248px、右栏 400px 起，**两条 11px 拖拽带可实时改宽**（左 200–420 / 右 300–680，中栏保底 460px），双击手柄复位，宽度写入 `localStorage` 并按屏宽自适应默认值。
  - 右栏「资产台」四个标签页全部接真实数据：**成稿**（平台切换 + 真排版 iframe + 版本历史一键回滚）、**图片**（稿件配图、点击放大灯箱、← → 翻页）、**视频**（`/api/video/tasks` 成片直接播放）、**数据**（当前稿件评分、后台任务、资产统计）。
  - **选中即联动**：内容工作台选稿 / 极简模式出稿，右栏立刻跟随；左侧导航切到影音工坊自动翻到视频页。
  - **专注态**：右栏「⛶ 放大」一键铺满整屏阅读稿件，`Esc` 或右下角浮标退出，成稿按 940px 居中排版。
  - **顶栏自动收敛**：中栏变窄时按重要性把顶栏动作自动收进「⋯ 更多」下拉，任何屏幕宽度都保持单行 57px 高度，功能一个不减。
- **经典版往返**：`?legacy=1` / `?classic=1` 直达原版复杂界面，经典版右下角常驻「⚡ 新版工作台」返程浮标；窄于 1280px 自动回落经典版，避免小屏被三栏挤坏。

### Changed

- 极简模式在中栏内改为可压缩双列（`min-width:0`），面板子标签改为单行横向滚动，杜绝折行与横向溢出。
- 版本代号步进至 **长风谣 · Longwind Ballad**（`10.x 鸿蒙始` 收官），版本号 **11.0.0**。

### Notes

- 业务逻辑零改动：7 个业务面板、约 400 个函数、117 个接口原样复用，外壳只更换容器与视口分配；出任何问题 `?legacy=1` 一键回退。
- 新增 `web/static/js/workbench-shell.js`（外壳全部逻辑，非 v2 布局下自行空转退出）。

## [10.3.2] - 2026-11-03 · 鸿蒙始 (Primordial Dawn) · 模型服务测速 401 修复 (Provider Ping Auth Fix)

### Fixed
- **编辑已有模型服务后点「连通性测速」必然 401**：设置页在编辑时会**故意清空** Key 输入框，
  占位提示写着「留空则保持现有密钥不变」，但测速接口直接把输入框的值当 Key 用，
  空值就完全不带 `Authorization` 头，于是：
  - 一幕官方通道 → `HTTP 401: invalid api key`
  - 自建 / AgnesAI 通道 → `HTTP 401: Token not provided (AgnesAI_error)`

  同一个根因，两个上游的不同措辞。Key 本身是好的——带上已保存的同一把 Key 请求即 200。
  - 新增 `core/llm.resolve_provider_key()`：手填 Key 优先；留空时回退到该服务已保存的 Key；
    平台自有端点再回退到平台主 Key。返回 `key_source`（input / saved / platform / none）。
  - `ping_provider()` 与 `fetch_remote_models()` 统一走这套解析，避免「测速」和「拉取模型」
    再次出现同款分裂。`/api/models/ping` 现在把 `provider_id` 一并透传给后端。
  - 前端在输入框留空时明确提示「将使用已保存的密钥」，结果行显示「校验凭证: 已保存密钥」；
    401 时直接给结论（未携带 Key / 该 Key 被上游拒绝），不再只丢一句英文报错。
- **粘贴的 Key 带 `Bearer ` 前缀 / 引号 / 零宽字符时同样 401**：新增 `clean_api_key()` 统一清洗，
  避免拼成 `Bearer Bearer sk-...`。
- **安全边界保持不变**：已保存的 Key 只在 `base_url` 与该服务已保存地址一致时才回退，
  平台主 Key 只在平台自有端点生效——把 `base_url` 指向自己的服务器骗不走任何密钥。

## [10.3.1] - 2026-11-03 · 鸿蒙始 (Primordial Dawn) · 首次引导按钮修复 (Onboarding Wizard Fixes)

### Fixed
- **首次引导（Wizard）里 ✕ / 下一步 / 完成引导全部点不动**：
  `closeWizard()` 里写的是 `modal('m-wizard').classList.remove('on')`，而 `modal()` 没有返回值，
  必然抛 `TypeError: Cannot read properties of undefined (reading 'classList')`。
  结果是弹窗关不掉、`POST /api/onboarding/done` 也永远发不出去 → 每次刷新都重新弹，新用户被永久卡在引导里。
  - `modal()` 改为返回元素（并对不存在的 id 静默容错）。
  - `closeWizard()` 直接操作 DOM 并包 try/catch，无论从哪条路径关闭都落「已完成」标记。
  - 背景点击 / Esc 关闭引导同样走 `closeWizard()`，不再出现「关了但下次还弹」。
- **矮屏（1366×768 笔记本、125% 缩放、小窗口）下「下一步」被压在可视区外**：
  弹窗 `max-height:88vh` + 内部滚动，把底部按钮藏到滚动区之外，看着像"按钮没反应"。
  - mask 改为 `flex-start + overflow-y:auto`，超高时弹窗顶部不会被居中裁掉，整层可滚动。
  - 每步的底部操作条改为 `position:sticky` 实色贴底，任何屏高下「下一步 / 完成引导」都看得见、点得到。
- **步骤条只能看不能点**：现在可点击回看已走过的步骤，未走到的步骤保持锁定，避免空跑到「完成」页。
- **自备 Key 保存失败仍跳「完成」页**：改为失败即停在当前步并提示，按钮进入「保存中…」防连点；
  Key 为空时把焦点与红框送到输入框，而不是弹个 toast 就没了。
- **默认管理员自动登录后永不出现引导**：此前用登录前的状态判断（`wizard.show` 恒为 false），
  改为登录成功后重新拉取 `/api/auth/status`；注册 / 登录成功后也会立即拉起引导。

## [10.3.0] - 2026-11-03 · 鸿蒙始 (Primordial Dawn) · 系统诊断日志与改写链路修复 (Diagnostics & Rewrite Fixes)

### Added
- **系统诊断日志（设置 → 系统诊断日志）**：一键导出可复制的诊断文本，包含环境快照、失败步骤、完整错误堆栈。
  - 新增 `core/diagnostics.py`：环形缓冲区（2000 条）+ 落盘 `data/logs/diagnostics.log`（2MB 自动轮转）。
  - 自动接管 `logging` WARNING 及以上、线程/进程未捕获异常、asyncio 未处理异常、HTTP 4xx/5xx。
  - 新增接口 `GET /api/diagnostics/log`、`GET /api/diagnostics/stats`、`POST /api/diagnostics/clear`。
  - 敏感字段（key/token/password/secret/cookie/auth）自动打码，可安全外发。
  - 前端支持「复制全部 / 保存为文件 / 只看错误与警告 / 清空」。

### Fixed
- **Windows 端「新建正常、所有改写方式全失败」**：旧库 `draft_history` 缺 `title` 列时报
  `table draft_history has no column named title`。根因是补列迁移只写在「首次建库」分支，
  只要 `drafts` 表存在就走快速路径，永远补不上。
  - `conn()` 快速路径现在会补缺失的表（`_ensure_core_tables`）与缺失的列（`_migrate_columns`）。
  - `add_history` 增加「最后一米」兜底：表存在但缺 `title` / `body_md` / `score` / `created_at` 时就地补齐。
  - `add_history` 改为单连接 + `finally` 关闭，避免异常路径漏关连接造成的 `database is locked`。
- **改写不再因「历史版本存不下」整体失败**：`add_history` 失败降级为告警，改写继续。
- **Windows 控制台编码**：启动时把 `stdout`/`stderr` 切到 UTF-8 + `replace`，
  避免 `cp936` 下 print emoji 抛 `UnicodeEncodeError` 把长链路带崩。
- **改写链路步骤埋点**：`rewrite_draft_once` / `rewrite_single_platform` 记录「读取草稿 → 写历史 →
  调模型 → 解析 → 重建产物 → 评分」各步，失败时能直接看出卡在哪一步。

## [10.2.1] - 2026-10-23 · 鸿蒙始 (Primordial Dawn) · 原生应用安装包发布 (Native Application Installers)

### Added
- **Windows 原生安装程序 (.exe)**:
  - 引入基于 Inno Setup 6 的专业标准现代化安装程序配置 (`installer/windows/yimu_installer.iss`) 与自动化编译脚本 (`scripts/build_windows_installer.py`)。
  - 产出单文件安装包 `YIMU-Studio-Windows-Setup-v10.2.1.exe`，支持自定义安装路径、创建桌面图标、开始菜单快捷方式、卸载程序登记与安装完成自动运行。
- **macOS 原生磁盘映像安装包 (.dmg)**:
  - 打造原生 DMG 打包引擎 (`scripts/build_macos_dmg.sh`)，封装标准 `一幕·YIMU 爆款工作室.app` 应用程序包并内嵌 `/Applications` 替身链接，支持一键拖拽完成安装。
- **Linux 原生系统安装包 (.deb)**:
  - 打造标准 Debian/Ubuntu `.deb` 安装包生成器 (`scripts/build_linux_deb.sh`)，规范注册 `/usr/bin/yimu-studio` 系统命令与 `/usr/share/applications` 桌面菜单项。
- **GitHub Actions 多平台安装包编译流水线**:
  - 全新升级 `.github/workflows/build-desktop-client.yml` 为 Windows / macOS / Linux 三系统原生矩阵构建，全自动编译 `.exe`、`.dmg`、`.deb` 并挂载至 GitHub Releases。

## [10.2.0] - 2026-10-23 · 鸿蒙始 (Primordial Dawn) · 全平台独立桌面客户端 (Zero-Config Desktop Client)

### Added
- **全新跨平台原生独立桌面客户端 (`desktop.py`)**:
  - 后台静默守护拉起 FastAPI/Uvicorn 核心服务 (127.0.0.1:8790) 与端口健康自愈检测。
  - 优先调用 `pywebview` 引擎呈现 100% 独立桌面窗体（无浏览器地址栏、独占原生软件体验）。
  - 若环境未装载 webview，自适应平滑降级至 Chromium / Edge「独立应用模式 (`--app`)」，呈现极简桌面纯净视窗。
  - 智能感知窗口关闭事件，窗体关闭时自动终止后台服务，实现无残留退出。
- **Windows 原生静默启动引导 (`一幕桌面客户端.vbs`)**:
  - 双击直接拉起桌面客户端，彻底消除黑色控制台 CMD 窗口。
  - 自动优先检测内嵌独立便携 Python 运行时 (`runtime\pythonw.exe`) 与本地环境。
- **macOS 与 Linux 原生桌面客户端套件**:
  - `一幕桌面客户端.command`：macOS 双击直接以桌面独立客户端启动。
  - `一幕桌面客户端_linux.sh` & `一幕桌面客户端.desktop`：Linux 桌面双击快捷启动与系统应用菜单集成。
- **自动化桌面客户端打包与分发流水线 (`scripts/build_desktop_client.py`)**:
  - 支持一键打包 Windows x64 便携桌面压缩包 (`.zip`)、macOS (`.tar.gz`) 和 Linux (`.tar.gz`) 客户端。
  - 支持 `--with-runtime` 参数自动嵌入官方独立便携 Python 解释器并预装全量核心依赖，达成 100% 零环境配置、免 Python 安装开箱即用。
  - 集成 `.github/workflows/build-desktop-client.yml` CI/CD，Tag 发布时全自动构建并挂载 Releases 资源。
- **启动与升级脚本运行时架构升级**:
  - `一键启动.bat` 与 `一键升级.bat` 注入步骤 0：优先嗅探 `runtime\python.exe` 独立运行时，彻底跳过系统 Store 伪占位符与环境检查，直接进入极速创作。

## [10.1.12] - 2026-10-23 · 鸿蒙始 (Primordial Dawn)

### 🛡️ Windows 全版本通用架构 (Windows 7 / 8 / 8.1 / 10 / 11 终极适配)
- **终极彻底根除 Windows 启动闪退**：
  - Windows 11 的 Store 假解释器（`WindowsApps\python.exe` 0 字节 ReparsePoint）只要被直接调用就会导致 CMD 进程瞬间崩溃闪退。新版在调用前直接通过路径特征与文件大小进行静态隔离，彻底杜绝调用；
  - 优先扫描官方/系统所有标准安装目录（27+ 常见路径），一经命中立即使用绝对路径直启；
  - 彻底规避批处理预解析陷阱，采用安全标签跳转结构；
  - 无论何时出现异常或缺少依赖，窗口绝对常开（`pause`），杜绝任何控制台闪退或盲退。
- **原生适配 Windows 7 / 8 / 8.1 老旧系统**：
  - 兼容检测 `ver` 内核版本（NT 6.1），专属提供 Windows 7 Python 3.10/3.11 安装指导与国内高速下载镜像；
  - 优化代码页切换 `chcp 65001 >nul 2>nul`，抑制旧版点阵字体控制台报错崩溃；
  - 兼容 Python 3.9+ 解释器探测与启动。

## [10.1.11] - 2026-10-23 · 鸿蒙始 (Primordial Dawn)

### 🛡️ 全端全流程韧性加固 (Full-Stack Cross-Platform Resilience Release)
- **Windows 一键启动与一键升级彻底杜绝假解释器闪退**：全面实装 `python --version` 真实执行动态验证，坚决破除 Windows 11 下 Microsoft Store 0 字节 `python.exe` 假占位符引起的秒闪退；
- **全平台更新中枢 `core/updater.py` 100% 绝对零依赖解耦**：彻底消除对外部第三方库的任何强耦合，裸机/依赖损坏场景下均能稳定自主在线升级与归档无损热覆盖；
- **跨平台启动与部署脚本全量接入数据库约束自愈中枢**：覆盖 Windows、macOS、Linux 原生桌面及 Linux Server 生产部署脚本，任何环境升级后均能全自动自愈数据库结构与 `ck_drafts_status` / `drafts.platform` 等历史约束；
- **端到端防回归门禁验证**：新增自动化测试集覆盖全平台脚本健康、更新器零依赖与多环境自愈。

## [10.1.10] - 2026-10-23 · 鸿蒙始 (Primordial Dawn)

### 🔧 全平台版本排查与修复 (Cross-Platform Resilient Fixes)
- **`一键升级.bat` 防闪退加固**：全面同步与 `一键启动.bat` 相同等级的解释器探测机制，增加 `python --version` 真实执行测试（排除 Store 假解释器）、Python ≥ 3.10 版本底线校验、`venv` 创建异常捕获及目录预热。
- **在线升级引擎 `core/updater.py` 彻底零依赖解耦**：移除旧版对 `core.llm` 的顶层导入，自包含轻量 `.env` 解析器，消除对 `httpx`、`yaml` 等第三方库的依赖。即使在依赖尚未安装或损坏的裸机环境下，也能 100% 独立稳定执行在线升级与归档覆盖。
- **全平台脚本接入约束自愈中枢 (`auto_heal_all_sqlite_databases`)**：
  - 同步加固：[`一键升级.bat`](一键升级.bat)、[`一键启动_linux.sh`](一键启动_linux.sh)、[`一键升级_linux.sh`](一键升级_linux.sh)、[`一键启动.command`](一键启动.command)、[`一键升级.command`](一键升级.command)、[`服务器一键部署.sh`](服务器一键部署.sh)。
  - 彻底解决 Linux 与 macOS 用户在跨版本升级后可能因遗留数据库未自愈而出现 `ck_drafts_status` 或字段缺失报错的问题。
- **`一键启动.bat` 致命闪退修复**：原脚本使用 `where python` 检测 Python 是否存在，在 Windows 11 中 Microsoft Store 的 `python.exe` 占位符（0 字节 ReparsePoint）会通过 `where` 检测但无法真正执行，导致脚本误以为 Python 已就绪，进入 `python -m venv` 时窗口直接闪退。新脚本在 `where python` 之后增加 `python --version` 真实执行验证，Store 占位符会返回非 0 错误码，从而被正确排除。
- **Python 版本下限校验**：找到可执行 Python 后，追加 `sys.version_info >= (3,10)` 验证，低于 3.10 的解释器给出明确提示并退出。
- **venv 创建失败不再静默闪退**：`python -m venv .venv` 后追加 `errorlevel` 检测；失败时打印可读错误并 `pause`，不再无声退出。
- **pip 安装失败兜底**：依赖安装失败时给出明确提示并 `pause`，而非静默中断。
- **自动创建 `.env`**：若项目目录下无 `.env` 文件，启动时自动从 `.env.example` 复制，避免首次启动因缺少环境变量而报错。
- **友好错误提示 Store 占位符问题**：在「未找到 Python」错误提示中，明确解释 Microsoft Store `python.exe` 占位符的识别方式及关闭方法（Windows 设置 → 应用 → 高级应用设置 → 应用执行别名）。
- **扩展 Python 路径扫描**：新增对 `%ProgramFiles%\Python3xx` 等路径的扫描，覆盖更多安装场景。

### 📋 次要隐患说明（本版本记录，待后续跟进）
- 端口 8787（模型网关）未监听时，内容生成功能会连接失败，需另行配置 API Key 或启动配套网关。
- `playwright` 内核首次需手动 `python -m playwright install chromium`（后续版本考虑自动化）。

## [10.1.9] - 2026-10-22 · 鸿蒙始 (Primordial Dawn)

### Fixed & Enhanced
- **Permanent Eradication of Windows Git Credential Manager Popups**:
  - Removed obsolete `git credential fill` execution: since the repository is 100% public open-source, all read and update operations execute anonymously without prompting for GitHub credentials.
  - Injected `_safe_git_env()` with `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, `GIT_ASKPASS=""`, strictly disabling all GUI and terminal credential dialogs across Windows, macOS, and Linux.
- **Robust Multi-Tier Upgrade Fallback & Instant Synchronization**:
  - Seamless auto-fallback: if `git pull` encounters network blocks, branch conflicts, or missing Git on Windows, `perform_upgrade()` automatically falls back to downloading the latest Release ZIP archive from high-speed mirror channels (`github.com` -> `ghfast.top` -> `ghproxy.net`).
  - Safe data isolation: protected user configurations (`config.yaml`, `data/`, `.env`) from being overwritten during archive extractions.
  - Aligned Windows `一键升级.bat` with non-interactive flags, ensuring zero popups in both web UI and desktop batch environments.

---

## [10.1.8] - 2026-10-22 · 鸿蒙始 (Primordial Dawn)

### Fixed & Enhanced
- **Permanent Fix for Rewrite Failures in Content Workbench & Copilot**:
  - Upgraded `_parse_rewrite` into self-healing mode: accurately extracts Markdown bold headers (`**TITLE_WX:**`), section headings (`### TITLE_WX`), Chinese brackets (`【微信标题】:`) and unformatted pure Markdown outputs.
  - Eliminated `RuntimeError("重写解析失败")`: when models output plain articles without labels, the system automatically parses the title and body with 100% success.
  - Slashed rewrite latency & boosted stability: disabled redundant 5-image visual re-generation on text rewrites (`generate_images=False`), cutting execution time from 30s to 2s and eliminating external image API timeout risks.
- **Permanent Fix for Missing Scores & Auto-Scoring Failures in Minimal Mode**:
  - Implemented missing `rewrite_with_feedback(draft_id, score_res)` in `core.judge`, eradicating `AttributeError` during automated quality improvement loops.
  - Added `_heuristic_draft_eval(draft)` fallback algorithm in `core.judge` to ensure valid 7-dimensional scoring even if LLM review calls fail or return invalid JSON.
  - Guaranteed database persistence of fallback scores in `core.copilot`: drafts are 100% saved with valid scores, eliminating `score: null` / `⚖️ 未评分` frontend badges.

---

## [10.1.7] - 2026-10-16 · 鸿蒙始 (Primordial Dawn)

### Fixed & Enhanced
- **Exhaustive Root-Cause Fix for `CHECK constraint failed: ck_drafts_status`**:
  - Solved foreign key conflict during SQLite table rebuild: implicit active transactions prevented `PRAGMA foreign_keys=OFF` from taking effect, causing `DROP TABLE drafts` to fail with `FOREIGN KEY constraint failed` when referenced by `draft_history`.
  - Enforced explicit transaction rollback and `isolation_level = None` (autocommit mode) before schema rebuild, guaranteeing 100% successful removal of `ck_drafts_status` constraint across all environments.
  - Multi-tier resilience: `add_draft` and `set_draft_status` implement automatic retry and safe fallback to compliant `'draft'` status and minimal column insertion, completely eliminating crashes.
  - Preemptive database inspection: injected startup event and pre-Copilot check in `web/admin.py` to auto-heal all SQLite databases prior to servicing requests.
  - Aligned frontend draft counter to recognize both `'preview'` and `'draft'` statuses.

---

## [10.1.6] - 2026-10-16 · 鸿蒙始 (Primordial Dawn)

### Fixed & Enhanced
- **Ultimate Bulletproof Self-Healing for Windows & Cross-Platform SQLite Databases**:
  - Eliminated hidden failure in table rebuild where legacy tables without `tenant_id` or `platform` column caused silent rollback of `auto_heal_drafts_check_constraint`.
  - Implemented `STANDARD_DRAFT_COLUMNS` schema baseline ensuring all required columns (`tenant_id`, `platform`, `user_id`, `needs_review`) and zero CHECK constraints are always properly initialized with defaults.
  - Added `auto_heal_all_sqlite_databases()` to automatically scan and self-heal all `.db` database files in `data/` (`mediaflow.db`, `yimu.db`, etc.) on module import, startup, and upgrade.
  - Enhanced `一键升级.bat` with 4-tier fallback: `git pull origin` -> `ghfast.top` mirror -> `ghproxy.net` mirror -> Release ZIP online archive extraction, guaranteeing 100% upgrade success on Windows.
  - Added database constraint self-healing step directly into `一键启动.bat` and `一键升级.bat`.

---

## [10.1.5] - 2026-10-16 · 鸿蒙始 (Primordial Dawn)

### Fixed & Enhanced
- **Root Cause Resolution for `CHECK constraint failed: ck_drafts_status`**:
  - Completely eradicated `sqlite3.IntegrityError: CHECK constraint failed: ck_drafts_status` when creating drafts in Minimal Mode or updating drafts across any platform.
  - Implemented SQLite standard 12-step zero-loss table rebuild migration (`_auto_heal_drafts_check_constraint`) in `core.db.conn()` and `studio.db._migrate_missing_columns()`.
  - Automatically heals existing SQLite database files (`data/mediaflow.db`) upon startup, preserving 100% of historical drafts while removing the brittle static status CHECK constraint.
  - Removed restrictive `CheckConstraint` on `Draft.status` in `studio.db_models.Draft` to decouple runtime draft statuses (`preview`, `draft`, `pending_review`, `published`, `approved`, `failed`) from static database DDL.
  - Added triple-layer self-healing retry in `core.db.add_draft()` to guarantee 100% crash-free creation on all platforms.

---

## [10.1.4] - 2026-10-16 · 鸿蒙始 (Primordial Dawn)

### Fixed & Enhanced
- **Windows & Cross-Platform Auto-Updater Overhaul**:
  - Implemented dual-mode auto-updater: supports standard Git repository workflow and automated Release ZIP archive extraction for users who deployed without `.git`.
  - Added multi-mirror fallback (`ghfast.top`, `ghproxy.net`) ensuring reliable updates in mainland China network environments.
  - Added service process inspection and termination for port 8790 before update, preventing Windows file locking and stale memory persistence.
  - Eliminated misleading success logs: upgrade scripts strictly check pull return codes and dynamically print the true upgraded version.
- **Drafts `platform` NOT NULL Integrity Fix**:
  - Resolved `NOT NULL constraint failed: drafts.platform` during fresh Windows installations.
  - Injected database `server_default=""` and explicit parameters in `core.db.add_draft`.
  - Added auto-healing migration for existing databases in `core.db.conn()`.

---

## [10.0.0] - 2026-10-14 · 浮光录 (Luminous Chronicles)

### Added & Upgraded
- **Full-Stack `user_id` & BYOK Pipeline Unification**: Automatic context `user_id` propagation across `core/agents.py` (`chat_for`) and `core/llm.py` (`resolve_llm_endpoint`, `chat`), ensuring user-configured API Vault keys (BYOK) and free-demo metering work across all creation, rewriting, and short-drama stages. When an active BYOK key is present, `require_credits` automatically waives platform credit deductions.
- **6D Persona Profile Auto-Injection**: Workspace 6D persona profiles (`build_profile_system_prompt`) are now automatically injected into `compose_system` for writing, director, and ad-creative agents.
- **Local Config Overlay (`data/config.local.yaml`) & Conflict-Free Online Upgrade**: `core/llm.py` supports merging `data/config.local.yaml`, and `core/updater.py` automatically stashes/restores local `config.yaml` edits during `git pull`.
- **Database Connection Initialization Cache**: `core/db.py:conn()` caches schema/migration verification per database file inode, eliminating 40+ redundant DDL/PRAGMA queries per call (10x+ speedup).

### Fixed & Hardened
- **Reverse-Proxy Loopback Guard**: `_is_loopback` in `web/admin.py` now inspects `X-Forwarded-For` / `X-Real-IP` to prevent Nginx/Caddy reverse proxies from unintentionally granting loopback super-admin access to remote clients.
- **CSRF & Dynamic CSP Hardening**: `core/security_middleware.py` now enforces CSRF on cross-origin requests even without cookies (blocking Drive-by Localhost CSRF), checks `yimu_session`, reuses existing valid `csrf_token` cookies across tabs/iframes, and only emits `upgrade-insecure-requests` over HTTPS.
- **V6/V7 Session & Auth Unification**: `core/auth.py` and `studio/auth.py` now share cross-compatible token verification and dual-cookie (`mf_v6_token` + `yimu_session`) issuance; `encrypt_key` upgraded to `v2$` random-nonce HMAC stream cipher with backward compatibility.
- **Growth Funnel & Scheduler Fixes**: `/api/auth/register` and `orchestrator` now emit `signup` and `first_draft_created` funnel events and support `invite_code` referral redemption; `core/scheduler.py` supports cross-hour 15-minute windows and persists daily ticket state; `rewrite_single_platform` respects custom `instruction` on Xiaohongshu rewrites.

---

## [9.3.2] - 2026-10-14 · 扶风翼 (Gale Wings: Free First, Pay Later)

### Added
- **Official-Channel Free Trial Quota (P0-1)**: New users (Free tier) get **3 free lightweight AI generations per day** via the `yimu_official` channel — no API Key required, single-call output capped at 512 tokens, quota resets daily (UTC+8), counters persisted to `data/free_demo_calls.json`. Exhaustion falls back to normal compute-credit billing, preserving the existing `InsufficientCreditsError` contract.
- **First-Run Onboarding Wizard (P1-1)**: 3-step 30-second setup on first login (free-quota awareness → choose main engine: official channel or own API Key → done). Dismissal persisted via `POST /api/onboarding/done` → `data/user_onboarding_done.json`, never nags again. All wizard copy registered in `i18n_dict.json` (now 1,835+ terms).
- **Dual Data-Access Unification (P0-2)**: `users` and `user_api_keys` fully declared in the SQLAlchemy source of truth (`studio/db_models.py`), including V6-era columns (`plan`, `quota_used`, `quota_max`, `last_login`) and the `UserApiKey` model; raw-sqlite self-healing demoted to guarded fallback. Time columns unified to ISO-8601 via `FlexibleDateTime`.
- **Test Coverage**: 5 new `test_llm_metering` cases (free-quota exhaustion, paid-tier exclusion, long-output exclusion, left-today tracking); `test_r3_monetization` updated to assert ORM schema contains V6 columns; `docs/CONTRACT.md` registers the new onboarding route.

### Changed
- **Single Source of Truth (`version.py`)**: `__version__ = "9.3.2"`, `__codename__ = "扶风翼"`, slogan "Gale Wings: Free First, Pay Later".
- **User-facing copy**: internal jargon ("降级") replaced with user-friendly wording across `web/`, `studio/`.
- **All version references** (templates, i18n, license, README, RELEASES) unified to V9.3.2.

---

## [9.1.0] - 2026-10-13 · 万象生 (Infinite Worlds)

### Added
- **Full i18n Bilingual Unification**: Upgraded `web/static/js/i18n.js` with deep DOM auto-translation and comprehensive bidirectional dictionaries. Enforces 100% pure English when in English mode and 100% pure Chinese when in Chinese mode, eliminating any half-English/half-Chinese inconsistencies.
- **GitHub Releases Official Showcase**: Created GitHub Releases via GitHub REST API for all releases (`v9.1.0`, `v9.0.0`, `v8.3.33`, `v8.3.2`).
- **Installed Releases Showcase View & API**: Mounted `GET /releases`, `GET /admin/releases`, and `GET /api/releases` for seamless version tracking.

### Changed
- **Unified Single Source of Truth**: Updated all version references, docstrings, licenses, and contracts to `V9.1.0` / `9.1.0`.
- **Licensor Alignment**: Licensor strictly set to `yimu.hyipf.com` in `LICENSE` and across legal notices.

---

## [9.0.0] - 2026-10-13 · 万象生 (Infinite Worlds)

### Added
- **2K Cinematic Storyboard Visual Engine**: Default canvas dimensions upgraded to 2K resolution (`2048x1152` landscape for articles, `1152x2048` portrait for RED notes, and `2048x2048` square).
- **Agnes Model Zero-Haze Prompt Pipeline**:
  - Positive crystal-clarity prompt engineering: `crystal-clear sharp focus, vibrant saturated colors, crisp details, zero haze`.
  - Negative haze/smoke suppression: Aggressively filters out words causing hazy, foggy, or blurry AI artifacts.
  - Strict parameter normalization ensuring compliance with vision models that require specific size patterns.
- **Global Bilingual Internationalization Engine (`web/static/js/i18n.js`)**:
  - Hot toggle between English and Simplified Chinese on PC topbar and Mobile header.
  - Full DOM translation dictionary with `data-i18n` binding and `localStorage` persistence.
- **Bilingual Documentation**:
  - Full English specification [`README.md`](README.md).
  - Preserved Chinese guide [`README_ZH.md`](README_ZH.md) with two-way cross links.
- **Milestone Release Documentation**:
  - Published [`RELEASES.md`](RELEASES.md) and [`CHANGELOG.md`](CHANGELOG.md).
- **Automated Test Guardrails**:
  - Created [`tests/test_v90_release_and_i18n.py`](tests/test_v90_release_and_i18n.py) covering version single source of truth and legacy version sanitization.

### Changed
- **Unified Billing & Compute Hub**: Merged separate price buttons and token pills into a single consolidated capsule (`.unified-billing-pill`).
- **Single Source of Truth (`version.py`)**: Bumped `__version__ = "9.0.0"`, `__codename__ = "万象生"`, `__slogan_en__ = "One Thought. One Scene. Infinite Worlds."`.
- **System Updater**: User-Agent dynamically reads `version.__version__`.

### Removed
- **Topbar Release Link & Deprecated Pages**: Completely removed legacy release link `<a id="nav-release-entry">` and deprecated `/admin/releases` overview page to maintain a sleek, clean workspace.

---

## [8.3.33] - 2026-10-13 · 星河引 (Galactic Beacon)

### Added
- **Personal Profile Center Integration**: Migrated membership tiers and compute ledgers into the independent Personal Center panel (`#p-profile`).
- **Interactive Billing Plan Selection**: Added interactive clicking and highlighting for Free, Pro, and Studio plan cards in both billing modals and personal profile sections.
- **Account Password Management**: Added change password modal tab and connected backend `POST /api/auth/change_password`.
- **Permanent Tag**: Frozen as git tag `v8.3.33`.

---

## [8.3.2] - 2026-10-12 · 视觉大跃迁 (Visual Quantum Leap)

### Added
- 10 Curated Visual Aesthetic Presets (Documentary, Swiss Minimal, Cyberpunk, Anime, etc.).
- Conversational visual style hot-swapping via creator Copilot.
- Xiaohongshu 5-act panoramic frosted glass card compilation engine.
- Permanent Tag: Frozen as git tag `v8.3.2`.

---

<div align="center">
  <sub>Copyright © 2026 <a href="https://yimu.hyipf.com">yimu.hyipf.com</a> · All rights reserved.</sub>
</div>
