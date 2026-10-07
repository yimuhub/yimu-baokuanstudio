# V7 可用性审计报告（WS3，第一阶段：只审计，不修复）

- 审计时间：2026-10-07
- 审计对象：`/home/hatch/workspace/yimu-v7-port/`（V7 移植主树，commit 以工作区现状为准）
- 审计方式：只读。未修改工作目录任何文件；冒烟测试脚本放在 `/tmp`，唯一产出为本报告。
- 启动条件：`export YIMU_SECRET_KEY=<任意非空值>`（core/auth.py 无硬编码默认值，缺失时签发侧抛错，属预期设计）

---

## 一、审计覆盖

| 维度 | 覆盖量 | 结果 |
|---|---|---|
| 路由总数（web.admin:app） | 196 条 | 全部枚举 |
| GET 冒烟（无路径参数） | 39 条 | 逐条请求，无 500 |
| GET 冒烟（带路径参数） | 31 条 | 全部抽测（合法参数值），无 500 |
| GET 冒烟（登录态 cookie） | 27 条 | 逐条请求，无 500 |
| POST 冒烟 | 1 条（/api/auth/login 错误密码） | 400，符合预期失败语义 |
| Gateway 独立服务（gateway/main.py:create_app） | 10 个 OpenAPI 路径 | /api/health 200；鉴权路由 401 正常 |
| 静态交叉检查项 | 7 大类 | auth/db/billing/AG/judge/orchestrator/layouter 调用 vs 定义；懒导入模块 vs 文件；studio 引用；adapters/base |
| py_compile 全树 | 全部 .py | 通过 |
| pytest | 62 | 全部通过 |
| ci.sh（4 步） | pytest/真活探针/术语检查/密钥扫描 | 全绿 |
| templates 静态资源引用 | 4 个去重引用 | 3 个存在，1 个缺失（见 BUG-003） |
| 启动事件函数 | 2 个 | 均存在 |

**结论先行：未发现 500 级崩溃类 bug（致命=0）。发现 bug 5 个：高 2、中 2、低 1，另有观察项 1。**

---

## 二、bug 清单

| 编号 | 严重程度 | 位置 | 现象 | 证据 | 修复建议 |
|---|---|---|---|---|---|
| BUG-001 | 高（功能不可用） | `web/templates/index.html:3227` / `web/admin.py`（缺路由） | 首页底部导航"🔥热榜采集"卡片指向 `/admin/hot`，点击后 404 | `grep` 显示 admin.py 仅注册 `/admin/gateway`（:380）、`/admin/billing`（:386），无 `/admin/hot`；TestClient 实测 `GET /admin/hot → 404` | 二选一：① 在 `web/admin.py` 补 `@app.get("/admin/hot")` 占位页（复用 `_admin_placeholder_page`，与 gateway/billing 一致）；② 若 V7.1 前不做该入口，从 `index.html` 移除该卡片。推荐①（与 WS-F"占位页"策略一致） |
| BUG-002 | 高（功能不可用） | `studio/auth_router.py`、`studio/membership_router.py`（未挂载） | 会员/多租户 HTTP API（注册/登录/邀请码/launch_mode/会员自查，共 11 条路由）在生产环境无任何入口，不可达 | 全仓库 `grep include_router`：`studio/auth_router` 与 `studio/membership_router` 只在 `tests/wsb_common.py:68-69` 被挂载；`web/admin.py`、`gateway/main.py`、`studio/main.py` 均未挂载。模块本身可独立导入（冒烟验证通过） | 在 `gateway/main.py:create_app()` 或独立 studio 服务入口 `include_router`。注意路径冲突：`auth_router` 的 `/api/auth/*` 与 `web/admin.py` 现有 B 路由重名，不可直接挂进 admin app；建议挂到 Gateway 侧（前缀如 `/api/studio`）或等会员体系接入方案确定后再定挂载点 |
| BUG-003 | 中（文案样式/体验） | `web/templates/mobile.html:2416,2441` | 手机端图片加载失败时的兜底图 `/static/placeholder.png` 不存在，失败时触发二次 404 | `web/static/` 下仅有 `css/`、`js/` 两个目录，`find` 确认无 `placeholder.png`；两处引用均为 `onerror` 兜底逻辑，图片坏链时用户会看到破图 | 补一张 `web/static/placeholder.png`（与现有 `css/modern_studio.css` 等同目录挂载，`/static` 已挂载 `web/static`），或把兜底改为内联 SVG data URI |
| BUG-004 | 中（API 语义错误） | `gateway/main.py:40-49`（`_HTTP_TO_CODE`）、`:125-132`（`handle_http_error`） | 对仅支持 POST 的路由发 GET（如 `/v1/chat/completions`），返回 **500** `{\"code\":\"INTERNAL\",\"message\":\"Method Not Allowed\"}`，应为 405 | 实测 `GET /v1/chat/completions → 500`；`_HTTP_TO_CODE` 无 405 映射 → `code` 回退 `\"INTERNAL\"` → `CODE_HTTP[\"INTERNAL\"]=500`（`gateway/config.py:35-44`） | 在 `_HTTP_TO_CODE` 加 `405: \"METHOD_NOT_ALLOWED\"`，并在 `CODE_HTTP` 加 `\"METHOD_NOT_ALLOWED\": 405`；或对未映射状态码直接透传 `exc.status_code` 而非回退 500 |
| BUG-005 | 低（HTTP 语义） | `web/admin.py`（`/api/auth/login` 处理器） | 错误用户名/密码登录返回 **400**，常规语义应为 401 | 实测 `POST /api/auth/login`（错误密码）→ `400 {\"detail\":\"用户名或密码错误\"}` | 改为 `HTTPException(status_code=401)`；若前端已依赖 400 做分支判断，需同步改前端（`web/templates/*.html` 搜索该接口调用处） |
| OBS-006 | 观察项（非 bug） | `web/admin.py:342,352` | 启动时 FastAPI 警告 `Duplicate Operation ID mobile_index_m_head / index__head` | `@app.api_route(..., methods=[\"GET\",\"HEAD\"])` 自动生成的 HEAD operationId 命名冲突；已验证无重复路由（(methods,path) 去重=0），`/openapi.json` 可正常生成 | 可忽略；如需消除警告，给 HEAD 显式指定 `operation_id` 或改用 `include_in_schema=False` 的 HEAD 路由 |

### 逐项复核说明（"漏网之鱼"排查结论）

- **auth 调用**：`web/admin.py` 中 `auth.verify_token / get_user_by_id / register_user / ensure_default_admin / make_token / login_user / list_user_api_keys / get_active_user_llm_config / save_user_api_key / delete_user_api_key` 在 `core/auth.py` 中**全部存在**；`_token()` 为 admin.py 本地函数（:139），无此前 `auth._token` 类问题残留。
- **db 调用**：22 个 `db.XXX` 调用在 `core/db.py` 中**全部存在**。
- **billing 调用**：`check_and_deduct / generate_cdkeys / get_billing_status / redeem_cdkey` 在 `core/billing.py` 中**全部存在**。
- **AG/judge/orchestrator/layouter**：`orchestrator.llm.get_configured_models()` 初看可疑，实为 `core/orchestrator.py:17` 的 `from core import ... llm` 模块属性，`core/llm.py` 中 `get_configured_models`（:438）与 `available`（:853）均存在——**不是 bug**。其余 `AG.`/`judge.`/`layouter.` 调用**全部存在**。
- **懒导入模块**：`from core import X` 涉及的 24 个模块文件**全部存在**；`from adapters import Y` 的 6 个适配器（wechat_mp/toutiao/zhihu/weibo/twitter/xhs）**全部存在**；`adapters/base.py` 的 `PLATFORMS`、`NAMES` **存在**。
- **studio 交叉**：`gateway/deps.py:189` 懒导入 `studio.auth.get_current_user_optional`——`studio/auth.py:166` **存在**（且有 try/except 回退通道 2，设计合理）；`gateway/{deps,limits,routers_admin}.py` 引用的 `studio.db_models` 的 `GatewayKey/Tenant/User/Ledger/Membership/hash_gateway_key/new_id/utcnow` **全部存在**；`studio/billing_adapter.py` 懒导入的 `studio.membership.service` 的 `deduct_credits/ensure_membership/grant_credits` **全部存在**；`studio/image_forge/generate.py` 引用的 `studio.ledger.calc_cost/record_ledger_entry` **全部存在**。
- **启动事件**：`db.recover_interrupted_tasks`（core/db.py:674）✓、`scheduler.start_scheduler_daemon`（core/scheduler.py:84）✓。
- **501 说明**：`/api/hot/trends`、`/api/hot/collect` 返回 501 系**故意设计**（V7.1 占位，代码注释明确），不计为 bug。
- **401/404 说明**：未登录态下绝大多数 API 返回 401（"未登录或登录态已失效"）、资源不存在返回 404，均为**正常鉴权/资源语义**。

---

## 三、验证可用的功能清单（用户信心项）

1. **Web 主服务可正常启动加载**：`web/admin.py` 196 条路由全部注册成功，无导入期异常（`YIMU_SECRET_KEY` 非空即可）。
2. **核心页面**：`/`（PC/手机 UA 自适应）、`/m`、`/admin/gateway`、`/admin/billing` 均 200；`/docs`、`/redoc`、`/openapi.json` 正常。
3. **健康与版本契约**：`/health`、`/api/health`、`/api/version`（`{\"version\":\"7.0.0-dev\"}`，与 `version.py` 单一真源一致）。
4. **登录态下 27 个 GET 接口全部 200**：选题统计、任务列表、模型供应商、平台包、技能���工作区、水印、习惯、搜索状态、视频状态、账单状态、票据、IP 角色、排期、密钥 vault、小红书发布状态、语音列表、服务健康、资产库等。
5. **鉴权机制**：未登录 401、错误密码登录 400（语义见 BUG-005）、`core/auth.py` 无硬编码密钥（C-1 达标；无 key 时签发侧抛 `RuntimeError`，验签侧返回 None→401，fail-closed）。
6. **YIMU Gateway 独立服务**：`create_app()` 可构建启动；`/api/health` 200；OpenAPI 10 路径（`/v1/chat/completions`、`/v1/embeddings`、`/v1/images/generations`、`/v1/models`、`/api/gw/keys`、`/api/gw/ledger`、`/api/gw/upstreams` 等）；无 Key 访问 401 `UNAUTHORIZED`；统一错误体（含 `request_id`）工作正常。
7. **测试与 CI**：`pytest` 62 passed；`bash ci.sh` 4 步全绿（真活探针：语音/视频/网关账本 3 通过，出稿/仿写/交付 3 跳过系 V7.1 未实现；术语检查通过；密钥扫描通过）。
8. **静态资源**：`modern_studio.css`、`modern_studio.js`、`yimu-editor.js` 引用与文件一致。
9. **账本/会员底层**：`studio/ledger.py`、`studio/membership/service.py`、`studio/billing_adapter.py`、`core/billing.py` 之间调用关系完整（HTTP 层未挂载见 BUG-002）。

---

## 四、未覆盖项（需真实上游 Key / 真实账号 / 写操作才能验证）

1. **LLM 真实调用**：选题生成、仿写、标题、质检等依赖上游模型 Key 的链路（探针仅验证了网关账本落账，未做真实模型转发）。
2. **TTS 三引擎真实合成**：探针验证了本地音频产物（123522 字节 wav），未验证云端引擎降级链。
3. **图片生成专项**（PromptForge/12 风格库/Aesthetic Judge 赛马）：需真实生图上游 Key，未覆盖。
4. **视频渲染真实上游**：探针验证了 ffmpeg 本地合成 1s 视频，未验证云端视频模型。
5. **21/24 平台采集**：V7.1 能力，当前 501 占位，未覆盖。
6. **小红书发布**：`xhspub` 技能依赖未安装（`/api/xhspub/qrcode` 明确返回"依赖未安装"），需真实账号+依赖。
7. **多用户全流程**：注册→登录→邀请码兑换→额度扣减，需真实走完写路径（本阶段只读，未执行）。
8. **POST/PUT/DELETE 写接口**：除登录失败路径外未逐个冒烟（避免写库污染 `data/`）；已用静态交叉检查覆盖调用存在性。
9. **`/static-img` 挂载的 `data/` 运行时文件**：目录存在，实际产物文件随运行产生，未逐项核对。
10. **apipool 上游（127.0.0.1:8787）**：`/api/health/services` 显示服务发现配置正常，未验证真实连通。

---

## 五、给修复阶段的优先级建议

1. **P0**：BUG-001（用户可见死链，改动最小：补占位路由或删卡片）。
2. **P0**：BUG-002（会员体系 HTTP 入口缺失；需先定挂载点方案，注意与 admin 现有 `/api/auth/*` 路由冲突）。
3. **P1**：BUG-004（网关 405→500，API 语义错误，对接方易误判为服务端故障）。
4. **P1**：BUG-003（补占位图或改内联 SVG）。
5. **P2**：BUG-005（登录失败 400→401，视前端依赖情况而定）。
