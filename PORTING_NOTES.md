# V7 移植修改清单（port tree vs B @ 0cb424f）

> 原则：B 原有功能/代码直接复制使用，没有的功能才新开发；只做手术式修改。
> 基线：Mac `/Users/czmj/Documents/mediaflow` → `/home/hatch/workspace/yimu-v7-port/`

## 一、直接复制（未改动业务逻辑）

| 来源 | 落点 | 说明 |
|---|---|---|
| B `core/`（35 个 py） | `core/` | 全部保留；另补传 `adapters/`（8 个平台适配器，搬运遗漏） |
| B `web/`（admin.py 4142 行、templates、static） | `web/` | 全部保留 |
| B `requirements.txt`、`config.yaml`、`docs/需求稿-v2.md` | 根目录 / `docs/` | 保留（config.yaml 已验无真实密钥） |
| WS-C | `studio/promptforge.py`、`studio/image_forge/`（8 模块）、`studio/ledger.py`、`studio/errors.py`、`studio/db.py`、`studio/db_models.py` | 图片专项取件 |
| WS-E | `studio/hot/`（24 平台采集）、`studio/audio/`（chain/engines/subtitle）、`studio/tts.py`、`studio/skills/*.md`（5 份方法论） | V7.1 取件 |
| WS-A | `tests/` 全套门禁、`docs/CONTRACT.md`、`ci.sh` | 质量门禁 |

## 二、手术式修改（文件 + 原因）

### C-1 安全必须：`core/auth.py` 重写
- 去掉 `SECRET_KEY` 硬编码默认值（原 `"mediaflow-v6-cloud-production-secret-seed-98217"`），只读 `YIMU_SECRET_KEY` 环境变量，缺失直接抛错
- 密码哈希升级 10 万轮 → 21 万轮，新格式自带算法标识；`verify_password` 兼容老哈希（存量账号不断连）
- `ensure_default_admin()` 不再内置 `admin/123456`，口令只从 `YIMU_ADMIN_PASSWORD` 环境变量取

### C-4 版本真源：`version.py`（新增）+ `web/admin.py`
- 新增 `version.py`（`__version__ = "7.0.0-dev"`），`APP_VERSION` 改为从它读取（原硬编码 `"6.7"`）
- 新增 `GET /api/health`（契约归一；`/health` 保留为兼容别名并在 CONTRACT 登记）

### DB：`core/db.py`
- 新增 5 张表：`tenants`、`memberships`、`gateway_keys`、`ledger`、`invites`（列定义与 `studio/db_models.py` 对齐，raw sqlite3 与 SQLAlchemy 双层共用，已验证共存）
- 老表补 `tenant_id` 列（`NOT NULL DEFAULT 'default'`），老数据归默认租户；`conn()` 内自动建默认租户行（`launch_mode='invite-only'`）

### C-5 测试门禁
- `tests/` 整套复制并跑通；`test_contract_lock.py` 增加框架路由忽略（`/openapi.json`、`/docs`、`/redoc`）
- `docs/CONTRACT.md`：7 条文件直链改逐条登记（原一行导致解析器漏检）、补登记 `GET /health`

### 品牌/文案：`web/admin.py`、`web/templates/*.html`
- `供应商` → `模型服务`、`闸门` → `关卡`（用户文案禁用词，门禁要求）
- docstring 品牌改为"一幕·YIMU 爆款工作室"（app title 原本已是）

### 新增（无 B 功能对应）
- `studio/image_forge/b_adapter.py`：把 B 的 `core/imagegen.gen_image` 包装成 forge 的 client 协议（`client(prompt=,n=,size=)`），接入赛马 + Judge + 记账；B 原有生图函数不动
- `studio/main.py`：垫片，`from web.admin import app`，供契约锁校验
- `gateway/__init__.py`、`studio/membership/__init__.py`：WS-B 挂载点（try/except 兜底）
- `studio/hot/__init__.py`、`studio/audio/__init__.py`：WS-E 挂载点（已被真实实现覆盖）
- `web/admin.py`：`GET /api/hot/trends`、`POST /api/hot/collect` 返回 501（V7.1 预留，CONTRACT §5.14）

## 三、验证结果（2026-10-06，`.venv`）

- `bash ci.sh`：4 步全绿（pytest 45 passed / 探针 1 通过 4 跳过 / 术语 / 密钥扫描）
- 契约锁：CONTRACT 185+ 条 ↔ app 实际路由双向一致
- auth：新哈希 roundtrip、老哈希兼容、缺密钥抛错，硬编码残留 0
- DB：15 张表建成，`tenant_id` 迁移 + 默认租户 + SQLAlchemy 共存验证通过
- 适配器冒烟：3 候选 → 赛马优选（quality 9.0）→ 记账 15 credits，全链路通

## 四、遗留（给后续 WS）

1. WS-B：`gateway/` 独立服务、`studio/membership/` 真实实现；`studio/ledger.py` 在 port 树已存在（WS-C 版），WS-B 集成时二选一
2. WS-E（V7.1）：把 `/api/hot/*` 501 桩替换为真实 pipeline 接线；`studio/tts.py` 对接 B 的音频路由
3. WS-F：B 的 `web/` 已就位，只做最小适配（管理后台新增网关/会员页入口）
4. `web/admin.py:41` 的 `@app.on_event("startup")` 有 DeprecationWarning（功能正常，V7.1 再迁 lifespan）

## 五、WS-B 集成（2026-10-06，父 agent 执行）

取件自 `/home/hatch/workspace/yimu-v7-ws-b`：

| 来源 | 落点 | 说明 |
|---|---|---|
| `gateway/`（7 个 py） | `gateway/` | 独立 FastAPI 服务（端口 8791）：OpenAI 兼容 chat/images/embeddings/models、熔断、限速、配额、admin Key 管理 |
| WS-B `studio/auth.py`、`auth_router.py` | `studio/` | 会员认证（HMAC 会话），与 B 的 `core/auth.py` 并存 |
| WS-B `studio/membership/service.py`、`studio/membership_router.py` | `studio/membership/`、`studio/` | 会员档位/扣费/邀请码 |
| WS-B `studio/ledger.py` | `studio/ledger.py` | 替换 WS-C 精简版（calc_cost 金丝雀逐字一致）；追加 `record_ledger_entry` 兼容垫片供 image_forge 用 |
| WS-B `studio/billing_adapter.py`、`gw_client.py` | `studio/` | B billing→ledger 桥接、网关 SDK |
| WS-B `studio/errors.py` | —— | 未采用（port 已有 WS-C 版，6 个模块依赖其 Code/YimuError/BadRequest）；仅给 port 版追加了 `raise_err` |
| `tests/test_gateway.py` 等 4 文件 | `tests/` | 网关/会员/租户隔离测试 |
| `probe_gateway` | `tests/probes.py` | 网关链路探针：chat 200 → 账本落 input/output 两行 |

验证：`bash ci.sh` 4 步全绿（pytest 62 passed；探针 3 通过/3 跳过：语音/视频/网关通过，出稿/仿写/交付待 B 流水线对接 studio.pipeline）。

## 六、WS-F 最小适配（2026-10-06）

- `web/templates/index.html`：侧边栏新增「网关管理」「会员与账本」入口（链接 /admin/gateway、/admin/billing）
- `web/admin.py`：新增 `_admin_placeholder_page()` + 两条占位路由（中文"功能开发中"，无禁用词）
- `docs/CONTRACT.md` §5.1：登记新增两条路由（契约锁双向一致要求）
- 未动 core/、tests/、业务逻辑；未重写页面。

## 七、V7 完整可用性集成（2026-10-07，总协调员）

用户要求：所有功能真实可用，不许占位；A/B 完美融合。三 WS 并行交付后由总协调员集成。

### WS1：网关 + 会员与账本完整实现
- 新增 `web/gateway_ui.py`（~1000 行）：GET /admin/gateway（13 模型服务状态/Key 管理/测试调用）、GET /admin/billing（档位卡/账本历史/邀请码/launch_mode）；API：/api/gw/ui/*（keys/my-keys/revoke/test-call）、/api/billing/ui/*（me/init/ledger/invites/launch_mode）
- web/admin.py：删除占位页（366-389 行），include web.gateway_ui 与 gateway.routers_openai（/v1）
- 自测 33/33 通过：Key 创建→测试调用→账本落 2 行→额度扣减→吊销 403 全链路

### WS2：A 能力接线
- 新增 `web/hot_ui.py`：GET /api/hot/platforms、GET /api/hot/trends、POST /api/hot/collect（真实调 studio/hot/pipeline.collect_all）、GET /admin/hot（24 平台复选框页面）
- core/audio.py：make_audio 先走 studio/tts.py 三引擎链，异常降级回 B 原 _tts（日志+degraded 标注）
- index.html 导航加"🔥 热榜采集"入口；studio/skills_staging/ 暂存 5 个 .md + manifest.txt
- 自测 9/9 通过

### WS3：可用性审计（docs/AUDIT_V7.md）
- 5 bug：高 2（/admin/hot 死链→已随 WS2 解决；11 条 studio 路由未挂载→会员 5 条已挂载，auth 5 条与 B 重名不挂载）、中 2（placeholder.png 缺失→已补；网关 405 错标 500→已修为 400）、低 1（登录错密码返回 400 而非 401，B 原行为，保留）
- 70 条 GET 路由实测零 500；pytest 62 通过

### 总协调员集成动作
- web/admin.py：删除 /api/hot/* 501 桩；补 /v1 运行时装配（app.state.settings/session_factory/rate_limiter/model_catalog/upstream_pool + GatewayError 处理器），与 gateway_ui 共用同一 DB
- 挂载 studio/membership_router（/api/membership/me、/api/admin/launch_mode、/api/admin/invites，无路径冲突）
- YIMU_DB_URL 默认指向主应用同一 sqlite 文件（测试可用环境变量隔离）
- docs/CONTRACT.md：§5.1/§5.14 转正 + 新增 §5.15（27 条新路由登记）
- skills/agents/：放入 A 的 5 个方法论 .md（topic-select/article-disassemble/viral-rewrite/title-forge/quality-gate），字节校验一致；B 的 21 个补传中（已到 1 个），注意未来 title-forge 同名
- 验证：bash ci.sh 4 步全绿（pytest 62 passed，契约锁真实通过；探针 3 通过/3 跳过；术语；密钥扫描）
- 实测：/v1/chat/completions → 200，账本落 input/output 两行，会员额度 20000→19994
