# 一幕·YIMU 爆款工作室 V7 · API 契约（Contract）

> **版本**：7.1.0 ｜ **状态**：WS-A 冻结版（冻结后修改须走 §8 变更流程）
> **基线**：项目 B @ commit `0cb424f` 的全部 `/api` 路由功能（§5 路由清单逐一映射，遗漏显式标注）
> **阅读对象**：WS-B（网关+会员）、WS-C（图片专项）、WS-D（B功能重实现）、WS-E（A移植→V7.1）、WS-F（前端）

---

## 1. 服务划分

| 服务 | 基地址（本地） | 说明 |
|------|---------------|------|
| YIMU Gateway | `http://127.0.0.1:8791` | 独立 FastAPI 服务；OpenAI 兼容；可独立部署 |
| Studio 主服务 | `http://127.0.0.1:8790` | 工作室业务；所有模型调用经网关 SDK 发出 |

## 2. 通用约定

### 2.1 鉴权

| 场景 | 方式 |
|------|------|
| 网关 `/v1/*` | `Authorization: Bearer yimu_sk_...`（网关 Key，只存 hash，前缀展示） |
| Studio 浏览器 | Cookie session（多用户登录态） |
| Studio CLI/API | `Authorization: Bearer <session token>` 或网关 Key（只读类接口） |

未鉴权 → `401`；无权限 → `403`；Key 配额超限 → `429`（body 带 `retry_after` 与剩余额度）。

### 2.2 统一错误体

```json
{
"ok": false,
"code": "CODES_BELOW",
"message": "给人看的中文一句话（禁止开发者黑话，见术语检查）",
"hint": "可操作的下一步（可空）",
"request_id": "uuid"
}
```

| code | HTTP | 含义 |
|------|------|------|
| `OK` | 200 | 成功（`ok: true`，`data` 载荷） |
| `BAD_REQUEST` | 400 | 参数错误（`detail` 指明字段） |
| `UNAUTHORIZED` | 401 | 未登录 / Key 无效 |
| `FORBIDDEN` | 403 | 无权限 / 租户隔离拦截 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `CONFLICT` | 409 | 状态冲突（如重复发放） |
| `QUOTA_EXCEEDED` | 429 | 配额/限速超限（带 `retry_after`、`credits_left`） |
| `UPSTREAM_ERROR` | 502 | 上游模型/服务故障（已触发熔断降级时带 `fallback` 说明） |
| `TIMEOUT` | 504 | 外部调用超时（任务转异步时返回 `task_id` 而非直接 504） |
| `INTERNAL` | 500 | 未预期错误（必须记审计日志，message 脱敏） |

### 2.3 分页 / 时间 / 租户

- 分页：`?page=1&page_size=20`（`page_size` ≤ 100），响应 `{items, total, page, page_size}`。
- 时间：ISO-8601 UTC（`2026-10-06T12:00:00Z`）。
- 租户：云端版所有业务接口按登录用户自动带 `tenant_id` 过滤；跨租户访问一律 `403`（测试断言覆盖）。

### 2.4 长任务约定

耗时 >3 秒的操作一律走**异步任务**：`POST` 返回 `202 {task_id, status: "queued"}`；
查询 `GET /api/tasks/{task_id}` 得 `{status, progress(0-100), message, result}`；
`POST /api/tasks/{task_id}/cancel` 取消。任务超时（`timeout_sec`）后状态置 `failed`，**不许永久 running**。

---

## 3. YIMU Gateway：OpenAI 兼容 API

> WS-B 实现。目标：用户现有 OpenAI SDK 代码**零改**迁移（只换 `base_url` + Key）。

### 3.1 `POST /v1/chat/completions`
- 请求：OpenAI Chat Completions 格式（`model`, `messages`, `stream`, `temperature`, `max_tokens` …）。
- `stream: true` → SSE（`text/event-stream`，`data: [DONE]` 结束）。
- 模型路由：`model` 支持网关别名（如 `yimu-auto` 按能力自动选上游）；未知模型 → `400 BAD_REQUEST`。
- 计费：按实际 input/output tokens 记账进 `ledger`。

### 3.2 `POST /v1/images/generations`
- 请求：`{model, prompt, n=1, size, style}`；`n` ≤ 4（多张即走"赛马"优选，见图片专项契约 §6）。
- 响应：`{created, data: [{url, revised_prompt}]}`（OpenAI 格式）。

### 3.3 `POST /v1/embeddings`
- 请求：`{model, input}`；响应 OpenAI 格式。

### 3.4 `GET /v1/models`
- 返回网关可用模型列表（含别名、能力标签、单价）：`{data: [{id, object: "model", capabilities: ["chat","vision"], pricing: {...}}]}`。

### 3.5 网关管理 API（需管理员 role）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/gw/keys` | 网关 Key 列表 / 发放（返回明文 Key **仅一次**） |
| PATCH/DELETE | `/api/gw/keys/{id}` | 更新配额限速 / 吊销 |
| GET | `/api/gw/ledger` | 调用账本查询（按 key/model/日期过滤，分页） |
| GET | `/api/gw/upstreams` | 上游健康状态（熔断器状态可见） |
| POST | `/api/gw/upstreams/{id}/toggle` | 手动上下线 |

---

## 4. Studio 主服务：通用

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 存活探针（判据：进程活着） |
| GET | `/api/ready` | **真活探针**（判据=产物存在：5 条最小链路见 tests/probes.py；任一红灯则 ready=false） |
| GET/POST | `/api/tasks` | 任务提交 / 列表（分页） |
| GET | `/api/tasks/{task_id}` | 任务状态（§2.4） |
| POST | `/api/tasks/{task_id}/cancel` | 取消任务 |

---

## 5. Studio 主服务：路由清单（B @ 0cb424f 全量映射，共 185 条）

> 格式约定（`tests/test_contract_lock.py` 按此解析）：每条为行 `- \`METHOD /path\` → handler：说明【V7.0/V7.1】[来源]`。
> 映射规则：B 的每个路由必须出现；`[B]` 原样保留 / `[B→重写]` D-3 重写或 C 项调整 / `[NEW]` 新增。
> 冲突调整标注：C-1（auth 重写）、C-2（TTS）、C-3（采集增补）、C-4（版本真源）、C-5（测试）。
> 别名路由标记 `(deprecated)`：V7.0 保留兼容，V7.1 可下线。

### 5.1 页面 / 静态 / 基础【V7.0】
- `GET /` → index：首页（UA 分流手机/桌面，登录态校验）【V7.0】[B]
- `GET /m` → mobile_index：手机专属首页【V7.0】[B]
- `GET /api/health` → health：健康检查（B 原路径 `/health`，归一为 `/api/health`）【V7.0】[B→重写]
- `GET /health` → health：旧路径兼容别名（deprecated）【V7.0】[B]
- `GET /api/version` → api_version：版本号（必须读 `version.py` 单一真源）【V7.0】[B→重写] C-4
- `GET /api/status` → status：系统状态与配置摘要【V7.0】[B]
- `GET /preview/{did}/{platform}` → preview：草稿分平台预览页【V7.0】[B]
- `GET /card/{did}/{name}` → card：小红书卡片图直链【V7.0】[B]
- `GET /img/{did}/{name}` → draft_img：草稿配图直链【V7.0】[B]
- （静态挂载）`/static` → web 静态资源；`/static-img` → data 目录文件服务【V7.0】[B]
- `GET /admin/gateway` → gateway_page：网关管理页（模型服务状态/Key 管理/测试调用）【V7.0】[NEW]
- `GET /admin/billing` → billing_page：会员与账本页（档位/额度/账本/邀请码）【V7.0】[NEW]
- `GET /api/system/check_update` → api_system_check_update：GitHub 在线版本升级检测【V8.3.31 / V8.3.32 左下角一键检测】[新增]
- `POST /api/system/upgrade` → api_system_upgrade：GitHub 仓库代码在线一键同步升级【V8.3.31 / V8.3.32】[新增]
- `GET /api/workspace/profile` / `PUT /api/workspace/profile` → 创作者 6 维数字画像与个人中心数据契约【V8.3.32】
- `GET /favicon.ico` → get_favicon：官方 Favicon 专属图标【V9.1.1】[NEW]
- `POST /api/onboarding/done` → onboarding_done：首次引导完成/跳过标记（持久化 data/user_onboarding_done.json，防反复打扰）【V9.3.2】[NEW]

### 5.2 认证 / 用户保险箱【V7.0，C-1 重写实现】
- `POST /api/auth/register` → api_register：用户自助注册（launch_mode=invite-only 时需邀请码）【V7.0】[B→重写]
- `POST /api/auth/login` → api_login：登录（写 cookie）【V7.0】[B→重写]
- `GET /api/auth/me` → api_auth_me：当前用户资料与额度【V7.0】[B]
- `POST /api/auth/change_password` → api_change_password：当前登录用户修改密码【V8.3.33】[新增]
- `GET /api/auth/status` → auth_status：登录状态查询【V7.0】[B]
- `POST /api/auth/logout` → logout：退出登录【V7.0】[B]
- `POST /login` → login：旧路径兼容别名（deprecated）【V7.0】[B]
- `GET /api/user/vault/keys` → vault_keys：用户自备模型 Key 列表【V7.0】[B]
- `POST /api/user/vault/keys` → vault_save：添加/配置自备 Key【V7.0】[B]
- `DELETE /api/user/vault/keys/{kid}` → vault_delete：删除自备 Key【V7.0】[B]

### 5.3 热榜选题 /api/topics【V7.0 保留 B；V7.1 由 studio/hot/ 增强】
- `GET /api/topics` → topics_list：热榜选题列表（前端下拉/选题池，按状态+来源筛选）【V7.0】[NEW]
- `POST /api/topics/collect` → topics_collect：触发全网热榜采集【V7.0】[B]
- `POST /api/topics/manual` → topics_manual：手动添加选题【V7.0】[B]
- `POST /api/topics/clean` → topics_clean：清理 N 天前热榜【V7.0】[B]
- `POST /api/topics/clear_all` → topics_clear_all：清空热榜库（需二次确认+审计）【V7.0】[B]
- `GET /api/topics/stats` → topics_stats：热榜库统计【V7.0】[B]
- `POST /api/topics/{tid}/{action}` → topic_action：选题通过/驳回/删除【V7.0】[B]
- `POST /api/topics/evaluate` → topic_evaluate：爆款潜力五维评分【V7.0】[B]
- `POST /api/topics/one_sentence_viral` → one_sentence_viral：一句话灵感异步创作（返回 job）【V7.0】[B]

### 5.4 搜索 / 仿写 / 拆解【V7.0】
- `GET /api/search/status` → search_status：搜索服务状态（internal）【V7.0】[B]
- `POST /api/search` → do_search：全网搜索对标爆款文章【V7.0】[B]
- `POST /api/rewrite` → do_rewrite：爆款仿写（同步）【V7.0】[B]
- `POST /api/extract` → do_extract：爆款文章结构化拆解【V7.0】[B]
- `POST /api/rewrite/job` → rewrite_job：仿写异步任务（进度可见）【V7.0】[B]
- `GET /api/jobs/{jid}` → rewrite_job_status：异步任务状态查询（主）【V7.0】[B]
- `GET /api/rewrite/job/{jid}` → rewrite_job_status：同上兼容别名（deprecated）【V7.0】[B]

### 5.5 草稿核心 /api/drafts【V7.0】
- `POST /api/drafts/create` → create_draft：手动新建/导入草稿【V7.0】[B]
- `GET /api/drafts/{did}` → get_draft：草稿详情【V7.0】[B]
- `GET /api/drafts/{did}/score` → draft_score：7 维评分结果查询【V7.0】[B]
- `GET /api/drafts/{did}/history` → draft_history：版本历史列表【V7.0】[B]
- `POST /api/drafts/{did}/restore` → draft_restore：回滚历史版本【V7.0】[B]
- `POST /api/drafts/delete` → drafts_delete：批量删除草稿（需二次确认）【V7.0】[B]
- `POST /api/drafts/clean_old` → drafts_clean_old：清理过期草稿【V7.0】[B]
- `POST /api/drafts/{did}/rewrite` → draft_rewrite：整篇重写【V7.0】[B]
- `POST /api/drafts/{did}/rewrite_platform` → draft_rewrite_platform：单平台专属重写【V7.0】[B]
- `POST /api/drafts/{did}/refine` → draft_refine：单点修补【V7.0】[B]
- `POST /api/drafts/{did}/evolve` → draft_evolve：自进化多轮打磨【V7.0】[B]
- `POST /api/drafts/{did}/ai_upgrade` → ai_upgrade：名家文风一键改写提分【V7.0】[B]
- `POST /api/drafts/{did}/quality_gate` → draft_quality_gate：发布前质量关卡与合规体检【V7.0】[B]
- `POST /api/drafts/{did}/rescore` → draft_rescore：重新评分【V7.0】[B]
- `GET /api/drafts/{did}/platform_scores` → draft_platform_scores：各平台差异化评分【V7.0】[B]
- `POST /api/drafts/{did}/switch_title` → draft_switch_title：切换候选标题【V7.0】[B]
- `GET /api/drafts/{did}/raw/{platform}` → draft_raw：取某平台源文案【V7.0】[B]
- `POST /api/drafts/{did}/save_platform` → draft_save_platform：多平台源文案保存与同步渲染【V7.0】[B]
- `POST /api/drafts/{did}/save_wechat` → draft_save_wechat：保存公众号正文【V7.0】[B]
- `POST /api/drafts/{did}/switch_theme_pure` → draft_switch_theme：零 LLM 纯规则换肤【V7.0】[B]
- `POST /api/drafts/{did}/fission` → draft_fission：一稿多平台裂变【V7.0】[B]
- `POST /api/drafts/{did}/derive_omni` → draft_derive_omni：母稿全域一键派生【V7.0】[B]
- `GET /api/drafts/{did}/matrix` → draft_matrix：矩阵派生结果总览【V7.0】[B]
- `POST /api/drafts/{did}/publish` → draft_publish：发布（公众号 API/手动）【V7.0】[B]
- `POST /api/drafts/{did}/publish_xhs` → draft_publish_xhs：小红书发布【V7.0】[B]
- `GET /api/drafts/{did}/html` → get_draft_html：取渲染后 HTML【V7.0】[B]
- `POST /api/drafts/{did}/html` → save_draft_html：保存编辑器 HTML【V7.0】[B]
- `GET /api/drafts/{did}/zip/xhs` → draft_zip：小红书图文打包下载【V7.0】[B]
- `GET /api/drafts/{did}/copilot_history` → copilot_history：Copilot 对话历史【V7.0】[B]
- `POST /api/drafts/{did}/voiceover_script` → voiceover_script：生成口播稿【V7.0】[B]
- `GET /api/drafts/image_styles` → get_image_styles：获取配图视觉风格清单【V8.3】[B]

### 5.6 配图 / 素材【V7.0；生图实现切 image_forge】
- `GET /api/drafts/{did}/images` → draft_images：草稿配图列表【V7.0】[B]
- `GET /api/drafts/{did}/images_detail` → draft_images_detail：配图明细【V7.0】[B]
- `POST /api/drafts/{did}/images/regenerate_one` → images_regenerate_one：单张重绘【V7.0】[B→重写]
- `POST /api/drafts/{did}/images/analyze_prompts` → images_analyze_prompts：AI 重提炼生图提示词（走 PromptForge）【V7.0】[B→重写]
- `POST /api/drafts/{did}/images/upload_custom` → images_upload_custom：上传自定义配图【V7.0】[B]
- `POST /api/drafts/{did}/images/replace_in_article` → images_replace：替换正文插槽图片【V7.0】[B]
- `POST /api/drafts/{did}/generate_images` → images_generate：批量生成全套插图+封面（走 §6 赛马）【V7.0】[B→重写]
- `POST /api/drafts/{did}/generate_single_image` → image_generate_single：单张主题配图【V7.0】[B→重写]
- `POST /api/drafts/{did}/wx_imgs` → wx_imgs：配图上传公众号素材库【V7.0】[B]
- `POST /api/drafts/{did}/gh_imgs` → gh_imgs：配图上传 GitHub 图床【V7.0】[B]
- `POST /api/drafts/{did}/ai_layout` → ai_layout：AI 重排版【V7.0】[B]
- `GET /api/assets/library` → asset_library：全局素材库（分页/过滤）【V7.0】[B]
- `POST /api/assets/delete` → asset_delete：删除单张素材【V7.0】[B]
- `POST /api/assets/batch_delete` → asset_batch_delete：批量删除素材【V7.0】[B]
- `POST /api/assets/generate_hyper_real` → asset_hyper_real：电影级超写实文生图（走 §6）【V7.0】[B→重写]
- `POST /api/assets/use_in_draft` → asset_use_in_draft：素材用于草稿插槽【V7.0】[B]
- `POST /api/image/forge` → image_forge_forge：PromptForge 提示词工程（贫瘠输入→结构化提示词）【V7.0】[NEW]
- `GET /api/image/styles` → image_forge_styles：12 风格库列表【V7.0】[NEW]
- `POST /api/image/generate` → image_forge_generate：赛马生图（会员分级：free 单张直出/pro 赛马）【V7.0】[NEW]
- `POST /api/image/judge` → image_forge_judge：Aesthetic Judge 图片评分【V7.0】[NEW]
- `GET /api/image/benchmark` → image_forge_benchmark：审美基准集回归结果【V7.0】[NEW]

### 5.7 小红书【V7.0】
- `POST /api/drafts/{did}/ai_xhs` → ai_xhs：AI 生成小红书图文【V7.0】[B]
- `POST /api/drafts/{did}/ai_xhs_visual` → ai_xhs_visual：小红书视觉生图与制卡【V7.0】[B]
- `POST /api/drafts/{did}/xhs_style` → xhs_style：即时切换卡片风格【V7.0】[B]
- `GET /api/drafts/{did}/xhs/history` → xhs_history：历史快照列表【V7.0】[B]
- `GET /api/drafts/{did}/xhs/history/{hid}/card/{card_name}` → xhs_history_card：查看历史卡片图【V7.0】[B]
- `POST /api/drafts/{did}/xhs/history/{hid}/restore` → xhs_history_restore：回溯还原【V7.0】[B]
- `GET /api/xhspub/status` → xhspub_status：发布通道状态【V7.0】[B]
- `GET /api/xhspub/qrcode` → xhspub_qrcode：扫码登录二维码【V7.0】[B]
- `POST /api/xhspub/login` → xhspub_login：小红书登录确认【V7.0】[B]

### 5.8 技能 / 习惯【V7.0】
- `GET /api/agents/config` → agents_config：11 Agent 矩阵当前配置（模型/技能/指令，前端只读展示）【V7.0】[NEW]
- `GET /api/skills/all` → skills_all：技能库列表【V7.0】[B]
- `POST /api/skills/save` → skills_save：保存/更新技能【V7.0】[B]
- `POST /api/skills/delete` → skills_delete：删除技能【V7.0】[B]
- `POST /api/skills/distill` → skills_distill：爆款文章蒸馏成技能【V7.0】[B]
- `POST /api/skills/distill_deep` → skills_distill_deep：深度蒸馏（博主音色/排版逆向）【V7.0】[B]
- `GET /api/skills/ref` → skills_ref：技能参考资料读取【V7.0】[B]
- `GET /api/habit/status` → habit_status：习惯自进化状态【V7.0】[B]
- `POST /api/habit/evolve` → habit_evolve：从定稿提取习惯并进化【V7.0】[B]
- `POST /api/habit/reset` → habit_reset：重置习惯基线【V7.0】[B]

### 5.9 工单 / 健康【V7.0】
- `GET /api/ticket/last` → ticket_last：最近每日工单【V7.0】[B]
- `POST /api/ticket/run` → ticket_run：执行工单任务【V7.0】[B]
- `POST /api/ticket/schedule` → ticket_schedule：工单排期【V7.0】[B]
- `GET /api/health/services` → health_services：下游服务健康探针（internal）【V7.0】[B]
- `POST /api/health/repair` → health_repair：服务自愈修复【V7.0】[B]

### 5.10 视频 / 音频 / 分镜【V7.0；C-2 音频实现 V7.1 升级】
- `GET /api/video/tasks` → video_tasks：视频任务列表【V7.0】[B]
- `GET /api/video/file/{tid}` → video_file：视频文件下载【V7.0】[B]
- `POST /api/video/upload_bgm` → video_upload_bgm：上传背景音乐【V7.0】[B]
- `POST /api/video/upload_material` → video_upload_material：上传图片/视频素材【V7.0】[B]
- `POST /api/video/make` → video_make：图文转视频合成【V7.0】[B]
- `POST /api/advideo/create` → advideo_create：AI 产品广告短片一键生成（异步 job，支持卖点/参考图/配音模式）【V7.0】[新增]
- `POST /api/advideo/selling_points` → advideo_selling_points：AI 广告卖点单独生成（预览/编辑）【V7.0】[新增]
- `POST /api/advideo/upload_ref` → advideo_upload_ref：广告参考图上传【V7.0】[新增]
- `POST /api/advideo/upload_audio` → advideo_upload_audio：广告配音音频上传【V7.0】[新增]
- `GET /api/advideo/ref_file` → advideo_ref_file：参考图/音频预览 serving【V7.0】[新增]
- `POST /api/advideo/script_rewrite` → advideo_script_rewrite：广告脚本一键改写（数字人口播/改写模式）【V8.0】[新增]
- `POST /api/aivideo/create` → aivideo_create：AI 短视频生成（视频大模型分段生成，异步 job）【V7.0】[新增]
- `GET /api/aivideo/rewrite/modes` → aivideo_rewrite_modes：AI 短视频脚本改写模式列表【V8.0】[新增]
- `POST /api/aivideo/rewrite` → aivideo_rewrite：AI 短视频脚本改写【V8.0】[新增]
- `POST /api/advideo/upload_avatar` → advideo_upload_avatar：广告短片数字人头像上传【V8.2】[新增]
- `POST /api/video/upload_avatar` → video_upload_avatar：数字人头像照片上传兼容别名【V8.2】[新增]
- `POST /api/aivideo/upload_avatar` → aivideo_upload_avatar：AI 数字人正脸照片上传（图生视频驱动）【V8.0】[新增]
- `GET /api/aivideo/avatar/{filename}` → aivideo_avatar_file：数字人头像照片 serving【V8.0】[新增]
- `GET /api/video/avatar/{filename}` → video_avatar_file：数字人头像照片 serving 兼容别名【V8.2】[新增]
- `GET /api/aivideo/avatars` → aivideo_list_avatars：AI 数字人形象记忆库列表【V8.2】[新增]
- `POST /api/aivideo/avatars/use` → aivideo_use_avatar：一键复用历史数字人形象【V8.2】[新增]
- `POST /api/aivideo/avatars/update` → aivideo_update_avatar：重命名数字人形象【V8.2】[新增]
- `DELETE /api/aivideo/avatars/{avatar_id}` → aivideo_delete_avatar：删除数字人形象【V8.2】[新增]
- `POST /api/video/test_voice_clone` → video_test_voice_clone：声音克隆服务连通性与试听生成测试【V8.2】[新增]
- `GET /api/aivideo/config` → aivideo_config_get：AI 视频生成配置读取【V7.0】[新增]
- `PUT /api/aivideo/config` → aivideo_config_put：AI 视频生成配置保存【V7.0】[新增]
- `GET /api/aivideo/file/{jid}` → aivideo_file：AI 短视频成片下载/预览【V7.0】[新增]
- `POST /api/video/upload_script_file` → video_upload_script：上传文档提取口播稿【V7.0】[B]
- `POST /api/audio/make` → audio_make：TTS 配音合成（API 稳定；V7.1 实现换 A 的三引擎降级链）【V7.0】[B→重写] C-2
- `GET /api/audio/file/{did}/{name}` → audio_file：音频文件下载【V7.0】[B]
- `POST /api/drafts/{did}/storyboard` → storyboard：生成分镜脚本【V7.0】[B]
- `GET /api/drafts/{did}/export_jianying` → export_jianying：导出剪映草稿【V7.0】[B]
- `POST /api/drafts/{did}/storyboard/gen_image` → storyboard_gen_image：分镜单帧生图【V7.0】[B]
- `POST /api/drafts/{did}/storyboard/batch_gen_images` → storyboard_batch：分镜批量生图【V7.0】[B]

### 5.11 全 AI 短剧 8 步流水线【V7.0；D-3 重写实现】
- `GET /api/video/drama/{did}/scenes` → drama_scenes：分镜场景列表【V7.0】[B→重写]
- `POST /api/video/drama/{did}/decompose` → drama_decompose：剧本分镜解构【V7.0】[B→重写]
- `POST /api/video/drama/{did}/gen_image` → drama_gen_image：单镜头生图【V7.0】[B→重写]
- `POST /api/video/drama/{did}/batch_gen_images` → drama_batch_images：批量生图【V7.0】[B→重写]
- `POST /api/video/drama/{did}/update_scene` → drama_update_scene：更新分镜【V7.0】[B→重写]
- `POST /api/video/drama/{did}/preview_audio` → drama_preview_audio：单句 TTS 试听【V7.0】[B→重写]
- `POST /api/video/drama/{did}/render` → drama_render：全片渲染（异步 job，扣费进 ledger）【V7.0】[B→重写]
- `GET /api/video/drama/{did}/pipeline/project` → drama_pipeline_get：取流水线工程【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/save_project` → drama_pipeline_save：保存流水线工程【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step1_analyze` → step1：剧本分析【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step2_outline` → step2：大纲【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step3_assets` → step3：资产规划【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step4_gen_asset` → step4_single：单资产生成【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step4_batch_assets` → step4_batch：批量资产生成【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step5_storyboard` → step5：分镜【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step6_gen_shot` → step6_single：单镜头生成【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step6_batch_shots` → step6_batch：批量镜头生成【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step7_gen_video` → step7_single：单镜头视频生成【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step7_batch_videos` → step7_batch：批量镜头视频生成【V7.0】[B→重写]
- `POST /api/video/drama/{did}/pipeline/step8_render` → step8：终混渲染【V7.0】[B→重写]
- `POST /api/short_drama/shots/reroll` → shots_reroll：单镜头重抽【V7.0】[B→重写]
- `POST /api/short_drama/shots/retake_voice` → shots_retake_voice：单镜头重配音【V7.0】[B→重写]
- `POST /api/short_drama/reorder_and_restitch` → reorder_restitch：重排重混母带【V7.0】[B→重写]
- 文件直链（7 条）【V7.0】[B]：
- `GET /audio/drama/{did}/{filename}` → drama_audio_file：短剧音频直链【V7.0】[B]
- `GET /img/drama/{did}/images/{filename}` → drama_img_file：短剧图片直链【V7.0】[B]
- `GET /img/drama/{did}/assets/{filename}` → drama_asset_file：短剧资产直链【V7.0】[B]
- `GET /img/drama/{did}/shots/{filename}` → drama_shot_img_file：短剧分镜图直链【V7.0】[B]
- `GET /img/storyboard/{did}/images/{filename}` → storyboard_img_file：分镜图直链【V7.0】[B]
- `GET /video/drama/{did}/shots/{filename}` → drama_shot_video_file：短剧分镜视频直链【V7.0】[B]
- `GET /video/drama/{did}/{filename}` → drama_video_file：短剧视频直链【V7.0】[B]

### 5.12 计费 / 模型 / 任务 / Copilot / 批量【V7.0】
- `GET /api/billing/status` → billing_status：算力余额与套餐（后端切统一 ledger）【V7.0】[B→重写]
- `POST /api/billing/redeem` → billing_redeem：卡密兑换【V7.0】[B→重写]
- `POST /api/billing/admin/gen_keys` → billing_gen_keys：管理员生成卡密【V7.0】[B→重写]
- `GET /api/voices/all` → voices_all：名家文风库列表（接口不变，文案改名）【V7.0】[B]
- `GET /api/models/providers` → models_providers：模型供应商列表（收口进网关 upstream）【V7.0】[B→重写]
- `POST /api/models/fetch` → models_fetch：拉取供应商模型列表【V7.0】[B→重写]
- `POST /api/models/ping` → models_ping：连通性测试【V7.0】[B→重写]
- `POST /api/models/save` → models_save：保存模型配置【V7.0】[B→重写]
- `POST /api/models/provider/set_active` → models_set_active：切换活动供应商【V7.0】[B→重写]
- `POST /api/models/provider/delete` → models_delete_provider：删除供应商【V7.0】[B→重写]
- `GET /api/llm/usage` → llm_usage：各模型服务使用量统计+官方通道消费汇总（双轨制）【V7.0】[NEW]
- `GET /api/pricing` → pricing_plans：三档套餐与售价（价格页数据源，价格取 studio/pricing 真源）【V7.2/R3-1】[NEW]
- `GET /pricing` → pricing_page：价格页（自包含 HTML，含下单与订单查询）【V7.2/R3-1】[NEW]
- `GET /releases` → releases_page：版本更新展示页（展示 V9.1.0 万象生与历史各版本更新演进与对比矩阵）【V9.1.0】[新增]
- `GET /admin/releases` → admin_releases_page：版本更新总览展示页（兼容后台路径）【V9.1.0】[新增]
- `GET /api/releases` → api_releases：获取版本更新与发布历史数据【V9.1.0】[新增]
- `POST /api/billing/order` → billing_create_order：下单购买套餐→生成 CDKey+支付指引【V7.2/R3-2】[NEW]
- `GET /api/billing/orders` → billing_my_orders：当前用户自己的订单列表【V7.2/R3-2】[NEW]
- `POST /api/billing/orders/{order_id}/activate` → billing_activate_order：用户核销激活订单【V9.4】[NEW]
- `POST /api/billing/orders/{order_id}/cancel` → billing_cancel_order：用户取消待支付订单【V9.4】[NEW]
- `GET /api/billing/upgrade` → billing_upgrade_options：额度墙付费引导（缺口+套餐对比，取定价真源）【V7.2/R3-4】[NEW]
- `GET /api/admin/orders` → admin_list_orders：订单管理列表（管理员，分页+状态筛选）【V7.2/R3-2】[NEW]
- `POST /api/admin/orders/{order_id}/confirm` → admin_confirm_order：管理员核销收款（pending→paid）【V7.2/R3-2】[NEW]
- `POST /api/admin/orders/{order_id}/cancel` → admin_cancel_order：作废未支付订单并撤销卡密【V7.2/R3-2】[NEW]
- `POST /api/admin/orders/{order_id}/refund` → admin_refund_order：退款（扣回额度+作废卡密+审计，幂等防重复退）【V7.2/R3-6】[NEW]
- `POST /api/admin/grant_credits` → admin_grant_credits：给指定用户发放额度（管理员，资金动作）【V7.2/R3-5】[NEW]
- `GET /api/admin/users` → admin_list_users：用户列表（分页+搜用户名/邮箱/档位/封禁态）【V7.2/R3-7】[NEW]
- `POST /api/admin/users` → admin_create_user：新建用户（管理员，指定档位/额度，审计必写）【V7.2/R3-7】[NEW]
- `PUT /api/admin/users/{user_id}` → admin_update_user：更新用户（改名/档位/封禁态，审计必写）【V7.2/R3-7】[NEW]
- `POST /api/admin/users/{user_id}/password` → admin_reset_password：重置用户密码（管理员，审计必写）【V7.2/R3-7】[NEW]
- `DELETE /api/admin/users/{user_id}` → admin_delete_user：删除用户（管理员，级联清理，审计必写）【V7.2/R3-7】[NEW]
- `POST /api/admin/users/{user_id}/ban` → admin_ban_user：封禁/解封用户（审计必写，封禁后无法调 API）【V7.2/R3-7】[NEW]
- `GET /admin/users` → admin_users_page：用户管理页（管理员）【V7.2/R3-7】[NEW]
- `GET /api/admin/audit_logs` → admin_audit_logs：审计日志查询（分页+动作/操作人/对象过滤）【V7.2/R3-8】[NEW]
- `GET /api/admin/audit_actions` → admin_audit_actions：已出现的审计动作列表（下拉筛选用）【V7.2/R3-8】[NEW]
- `GET /admin/audit` → admin_audit_page：审计日志查询页（管理员）【V7.2/R3-8】[NEW]
- `GET /api/video/status` → video_status：MoneyPrinterTurbo 视频服务运行状态探测【V7.0】[B]
- `POST /api/video/launch` → video_launch：拉起 MoneyPrinterTurbo 视频服务进程【V7.0】[B]
- `GET /api/tasks` → tasks_list：异步任务列表【V7.0】[B]
- `GET /api/tasks/{task_id}` → tasks_get：任务状态/进度【V7.0】[B]
- `POST /api/tasks/{task_id}/cancel` → tasks_cancel：取消任务【V7.0】[B]
- `POST /api/tasks/clear` → tasks_clear：清理 N 天前的失败/已完成任务（不碰 running/queued）【V7.0】[NEW]
- `POST /api/copilot/chat` → copilot_chat：Copilot 对话【V7.0】[B→重写]
- `POST /api/copilot/chat_stream` → copilot_chat_stream：Copilot SSE 流式对话【V7.0】[B→重写]
- `POST /api/stream/write` → stream_write：流式写作【V7.0】[B]
- `POST /api/batch/submit` → batch_submit：批量矩阵生产提交【V7.0】[B]
- `GET /api/platforms` → platforms_list：平台能力包列表【V7.0】[B]
- `GET /api/platforms/custom` → platforms_custom_list：获取用户自定义内容分发平台列表【V9.2.0】[新增]
- `POST /api/platforms/custom` → platforms_custom_save：新增或更新自定义内容分发平台【V9.2.0】[新增]
- `DELETE /api/platforms/custom/{platform_id}` → platforms_custom_delete：删除自定义分发平台【V9.2.0】[新增]
- `POST /api/platforms/detect` → platforms_detect：根据URL自动识别平台名称与域名【V9.2.0】[新增]
- `POST /api/platforms/analyze_style` → platforms_analyze_style：Agent智能读取目标网址并提取专属排版技能【V9.2.0】[新增]
- `POST /api/render` → render：markdown→微信兼容 HTML 实时渲染【V7.0】[B]

### 5.13 IP 角色 / 工作区 / 排期 / 水印 / 设置【V7.0】
- `GET /api/ip_characters` → ip_list：IP 角色库列表【V7.0】[B]
- `POST /api/ip_characters/save` → ip_save：保存 IP 角色【V7.0】[B]
- `POST /api/ip_characters/export_from_drama` → ip_export：从短剧导出角色【V7.0】[B]
- `POST /api/ip_characters/bind_to_drama` → ip_bind：角色绑定短剧【V7.0】[B]
- `POST /api/ip_characters/delete` → ip_delete：删除 IP 角色【V7.0】[B]
- `GET /api/workspaces` → ws_list：工作区列表【V7.0】[B]
- `GET /api/workspaces/skills` → ws_skills：工作区技能目录【V7.0】[B]
- `POST /api/workspaces/switch` → ws_switch：切换工作区【V7.0】[B]
- `POST /api/workspaces/create` → ws_create：新建工作区【V7.0】[B]
- `POST /api/workspaces/update` → ws_update：更新工作区【V7.0】[B]
- `POST /api/workspaces/delete` → ws_delete：删除工作区【V7.0】[B]
- `GET /api/workspace/profile` → ws_profile_get：6 维数字人格档案【V7.0】[B]
- `POST /api/workspace/profile` → ws_profile_update：更新数字人格档案【V7.0】[B]
- `GET /api/workspace/voiceprint` → ws_voiceprint_get：工作区声纹记忆档案【V8.3】[B]
- `POST /api/workspace/voiceprint` → ws_voiceprint_update：更新工作区声纹记忆【V8.3】[B]
- `POST /api/content/postmortem` → postmortem：爆款效果归因复盘【V7.0】[B]
- `GET /api/schedule/posts` → schedule_list：排期发布列表【V7.0】[B]
- `POST /api/schedule/post` → schedule_create：新增定时发布【V7.0】[B]
- `POST /api/schedule/cancel` → schedule_cancel：取消排期【V7.0】[B]
- `GET /api/watermark/settings` → watermark_get：水印设置读取【V7.0】[B]
- `POST /api/watermark/settings` → watermark_save：水印设置保存【V7.0】[B]
- `POST /api/editor/upload` → editor_upload：富文本编辑器上传【V7.0】[B]
- `POST /api/settings` → settings_save：全局配置保存【V7.0】[B]

### 5.14 V7.1 新增（A 移植，骨架期预留，不阻塞 V7.0）
> 2026-10-08 精简：独立热榜采集页与 `/api/hot/*` 接口已移除（与「灵感与选题」内置热榜功能重复），底层采集能力保留在 `studio/hot/` 供灵感模块调用。

### 5.14b R4 内容合规与信任（内容安全闸 / CSRF）【R4 合规批次新增】
> 内容安全前置闸（`core/content_guard.py`）：成稿与发布前独立于 7 维质量评分拦截违规内容。
> 分级：block 阻断 / review 标记待人工审 / pass 放行。开关 `CONTENT_GUARD_ENABLED`。
> 草稿 `needs_review` 为**标记**字段，不删除用户草稿；敏感选题标记 `blocked` 而非删除。
- `GET /api/compliance/guard` → guard_stats：内容安全闸概况（开关/词库规模/白名单）【R4】[NEW]
- `POST /api/compliance/topics/sweep` → guard_sweep_topics：扫描选题池标记 blocked（apply=false 预演）【R4】[NEW]
- `GET /api/compliance/topics/blocked` → guard_blocked_topics：列出被拦下的选题供复核【R4】[NEW]
- `POST /api/compliance/drafts/sweep` → guard_sweep_drafts：扫描草稿箱标记 needs_review【R4】[NEW]
- `GET /api/compliance/drafts/review` → guard_drafts_review：列出待人工复核草稿【R4】[NEW]
- `POST /api/compliance/drafts/{did}/clear_review` → guard_clear_review：人工复核通过后清除标记【R4】[NEW]
- `POST /api/compliance/drafts/{did}/check` → guard_check_draft：单篇草稿发布前检查（不写库）【R4】[NEW]

### 5.14c R5 留存与增长（通知 / 定时 / 邀请 / 分享 / 埋点 / 频控）【R5 批次新增】
> 用户侧通知走可插拔 provider（`core/notify.py`，邮件通道标准库 smtplib）；钉钉保留给运营。
> 每日工单改为**应用内定时**（原 macOS launchd 云端失效），接 `core/scheduler.py` 同一生命周期。
> 裂变分享地址**只含不可猜测令牌、不含 did**（`secrets.token_urlsafe(24)`），令牌→稿件映射仅存服务端。
> 埋点 5 事件：signup → first_draft_created → first_drama_run → quota_blocked → cdkey_redeemed。
> 自动发布频控：1 小时≤3 条 + 最小间隔 300 秒；连续失败 3 次进冷却。
- `GET /api/ticket/schedule` → ticket_schedule_get：读取每日工单定时状态【R5】[NEW]
- `GET /api/admin/metrics` → admin_metrics：5 步漏斗 + 账号健康 + 工单状态（管理员）【R5】[NEW]
- `GET /admin/metrics` → admin_metrics_page：运营漏斗看板页面（管理员）【R5】[NEW]
- `POST /api/drafts/{did}/share` → draft_create_share：为裂变产物签发分享链接/二维码【R5】[NEW]
- `GET /api/drafts/{did}/shares` → draft_list_shares：列出该稿件的全部分享链接【R5】[NEW]
- `POST /api/share/revoke` → share_revoke：吊销分享链接（立即失效）【R5】[NEW]
- `GET /s/{token}` → share_page：分享页（令牌换已排版产物；无效/过期/吊销一律 404）【R5】[NEW]
- `GET /s/{token}/qr.svg` → share_qr：分享链接二维码（SVG，纯标准库实现）【R5】[NEW]
- `GET /s/{token}/qr.png` → share_qr_png：分享链接二维码（PNG）【R5】[NEW]
- `GET /s/{token}/poster.svg` → share_poster：分享海报（标题+二维码+署名）【R5】[NEW]

### 5.14d 商业化算力与套餐（可见性）
> 商业化算力账本与套餐状态深度合并统一，顶栏展示统一算力与套餐价格入口。
> 版本号从 `GET /api/version` 读取、不得写死（`mobile.html` 同理，徽章不得写死 `V7`）。

### 5.15 网关 / 会员 / 热榜（V7.0 新增，真实可用）【V7.0】
- `POST /v1/chat/completions` → gw_chat：OpenAI 兼容 chat（含 SSE；鉴权→限速→扣费→上游）【V7.0】[NEW]
- `POST /v1/images/generations` → gw_images：OpenAI 兼容生图【V7.0】[NEW]
- `POST /v1/embeddings` → gw_embeddings：OpenAI 兼容向量【V7.0】[NEW]
- `GET /v1/models` → gw_models：模型列表【V7.0】[NEW]
- `POST /api/gw/ui/keys` → gw_ui_create_key：创建网关 Key（明文仅本次返回）【V7.0】[NEW]
- `GET /api/gw/ui/keys` → gw_ui_list_keys：Key 列表（管理员）【V7.0】[NEW]
- `GET /api/gw/ui/my-keys` → gw_ui_my_keys：我的 Key 列表【V7.0】[NEW]
- `POST /api/gw/ui/keys/{key_id}/revoke` → gw_ui_revoke_key：吊销 Key（不删行）【V7.0】[NEW]
- `POST /api/gw/ui/test-call` → gw_ui_test_call：网关测试调用（走真实流水线，echo 明确标注）【V7.0】[NEW]
- `GET /api/gw/ui/upstream` → gw_ui_upstream：上游模型服务状态（JSON，供原生视图）【V7.0】[NEW]
- `GET /api/video/config` → video_config_get：视频合成配置（Key 掩码，管理员）【V7.0】[NEW]
- `PUT /api/video/config` → video_config_put：增量更新视频合成配置（管理员）【V7.0】[NEW]
- `DELETE /api/video/config/keys/{provider}` → video_config_delete_key：删除素材站 Key（pexels/pixabay，管理员）【V7.0】[NEW]
- `GET /api/billing/ui/me` → billing_ui_me：我的档位与剩余额度【V7.0】[NEW]
- `POST /api/billing/ui/init` → billing_ui_init：会员一键初始化【V7.0】[NEW]
- `GET /api/billing/ui/ledger` → billing_ui_ledger：账本历史（分页）【V7.0】[NEW]
- `POST /api/billing/ui/invites` → billing_ui_create_invite：创建邀请码（管理员）【V7.0】[NEW]
- `GET /api/billing/ui/invites` → billing_ui_list_invites：邀请码列表（管理员）【V7.0】[NEW]
- `GET /api/billing/ui/launch_mode` → billing_ui_get_launch_mode：查看首发模式（管理员）【V7.0】[NEW]
- `PUT /api/billing/ui/launch_mode` → billing_ui_set_launch_mode：切换首发模式（管理员）【V7.0】[NEW]
- `GET /api/membership/me` → membership_me：会员自查（studio 会话鉴权）【V7.0】[NEW]
- `GET /api/admin/launch_mode` → admin_get_launch_mode：查看首发模式（studio 会话鉴权）【V7.0】[NEW]
- `PUT /api/admin/launch_mode` → admin_set_launch_mode：切换首发模式（studio 会话鉴权）【V7.0】[NEW]
- `GET /api/admin/invites` → admin_list_invites：邀请码列表（studio 会话鉴权）【V7.0】[NEW]
- `POST /api/admin/invites` → admin_create_invite：创建邀请码（studio 会话鉴权）【V7.0】[NEW]

---

## 6. 图片质量专项契约（WS-C）

| 方法 | 路径 | 说明 | 范围 |
|------|------|------|------|
| POST | `/api/image/forge` | PromptForge：贫瘠输入 → 结构化提示词（主体/风格/光影/构图四维）+ 否定词 | V7.0 |
| GET | `/api/image/styles` | 12 风格库列表（含示例图 URL、适用场景） | V7.0 |
| POST | `/api/image/generate` | 生成（走网关 `/v1/images/generations`，`n`=3 赛马）→ 返回优选图 + 候选列表 | V7.0 |
| POST | `/api/image/judge` | Aesthetic Judge：对已有图打分（质量分+保真分 0–10）+ 缺陷描述 | V7.0 |
| GET | `/api/image/benchmark` | 审美基准集回归结果（CI 门禁读取） | V7.0 |

## 7. 会员与首发模式契约（WS-B）

| 方法 | 路径 | 说明 | 范围 |
|------|------|------|------|
| GET/PUT | `/api/admin/launch_mode` | 首发模式：`invite-only` / `public`（后台开关） | V7.0 |
| GET/POST | `/api/admin/invites` | 邀请码发放 / 列表 | V7.0 |
| POST | `/api/auth/register` | 注册（invite-only 下需邀请码） | V7.0 |
| GET | `/api/membership/me` | 我的档位与剩余额度 | V7.0 |

---

## 8. 契约变更流程

1. 任何 WS 需要改契约 → 提 PR 改本文件 → WS-A（coordinator）评审。
2. 破坏性变更（删路由/改字段名/改错误码）必须 **提前 1 天**在 WS 群公告，并给前端留适配期。
3. `tests/test_contract_lock.py` 是机器门禁：CONTRACT 有而 app 无 → 红；app 有而 CONTRACT 无 → 红。

## 9. B 功能遗漏核查（已完成）

- 路由挖掘员全量扫描 `web/admin.py`（4142 行），确认 `web/routers/` 为空目录、无 APIRouter 挂载；§5 共 185 条已全部映射，**无遗漏**。
- 遗留待办（转交 WS-D 实现时执行）：在 Mac 上跑一次 `grep -rn "CREATE TABLE" --include="*.py" /Users/czmj/Documents/mediaflow` 做建表语句最终确认；`tests/test_contract_lock.py` 为机器门禁，持续防漂移。
