# 一幕·YIMU 爆款工作室 V7 — 数据库设计文档

> 版本：V7.0 Schema 初版 · 日期 2026-10-06 · WS-A / Schema 设计师
> 代码：`studio/db_models.py`（模型）· `studio/db.py`（连接与初始化）
> 许可：`# SPDX-License-Identifier: BUSL-1.1`

---

## 1. 总览

| 项目 | 决策 |
|---|---|
| ORM | SQLAlchemy 2.0，`Mapped` 注解风格（`mapped_column`） |
| 双兼容 | SQLite（本地）/ PostgreSQL（云端）；**不使用任何 PG 专有类型** |
| 主键 | 全部 `String(32)`，uuid4 十六进制；不用自增整数（避免分库分表/合并冲突） |
| 时间 | 全部 `DateTime(timezone=True)`，应用层统一写 UTC（`utcnow()`）；SQLite 存文本、PG 存 timestamptz |
| JSON | 统一 `sqlalchemy.JSON`（SQLite 落 TEXT，PG 落 JSONB） |
| 金额/额度 | **整数**：费用用 `cost_cents`（分），额度用 credits 点数；**杜绝浮点** |
| 状态枚举 | `String` + `CheckConstraint`（SQLite/PG 均支持 CHECK），枚举值见各表说明 |
| 表数量 | **14 张**（1 租户表 + 13 业务表） |

### 表清单

| # | 表名 | 用途 |
|---|---|---|
| 1 | `tenants` | 租户（一级隔离单元） |
| 2 | `users` | 用户（归属单个租户） |
| 3 | `memberships` | 会员订阅（档位 + 额度周期） |
| 4 | `gateway_keys` | YIMU Gateway API Key（只存哈希） |
| 5 | `ledger` | 网关调用账本（只增不改） |
| 6 | `invites` | 邀请码（invite-only 发放） |
| 7 | `assets` | 素材库（图片/视频/音频） |
| 8 | `drafts` | 草稿（内容创作主体） |
| 9 | `draft_history` | 草稿版本历史 |
| 10 | `drama_jobs` | 短剧任务（8 步流水线） |
| 11 | `drama_shots` | 分镜（镜头产出物） |
| 12 | `ip_characters` | IP 角色库（三视图+特征锚点） |
| 13 | `async_tasks` | 统一异步任务队列 |
| 14 | `audit_logs` | 审计日志（只增不改） |

---

## 2. 租户隔离（多租户真隔离约定）

**结构层**：除 `tenants` 自身外，所有业务表都通过 `HasTenant` 混入带 `tenant_id`
（`String(32)`，外键 → `tenants.id`，建索引，NOT NULL）。

**仓储层约定（强制）**：

1. **读必过滤**：任何查询必须显式加 `WHERE tenant_id = <当前租户>`。
   推荐封装 `TenantQuery` 基类 / repository 基类，禁止裸 `session.query(Model)`。
2. **写必注入**：`tenant_id` 必须从请求上下文（JWT / API Key 解析出的租户）注入，
   **禁止信任客户端传来的 tenant_id**。
3. **跨表校验**：涉及外键（如 `draft_id`）时，必须同时校验目标行 `tenant_id`
   与当前租户一致，防止跨租户 ID 穿透。
4. **后台任务**：`async_tasks` worker 取任务时按 `tenant_id` 分片认领；
   定时清理任务必须带租户条件分批执行。
5. **测试门禁**：CI 必须包含跨租户不可见断言——A 租户写入数据，
   B 租户用任何 API/仓储方法都查不到（`test_tenant_isolation.py`，WS-A 质量门禁）。

**本地单机模式**：自动创建默认租户（`name='default'`），行为与云端一致，
只是只有一个租户，代码路径不分叉。

---

## 3. 安全约定

| 字段 | 表 | 规则 |
|---|---|---|
| `password_hash` / `salt` | `users` | **永不返回给前端**；API 序列化用白名单，显式剔除 |
| `key_hash` | `gateway_keys` | **永不返回给前端**；原始 key 只在创建时返回一次 |
| 密码存储 | `users` | `pbkdf2_hmac-sha256`，21 万轮，独立随机盐；hash 自带 `算法$轮数$salt$hex`，明文绝不落盘 |
| 网关 Key | `gateway_keys` | 只存 SHA-256 哈希（加 `yimu-gateway-key:` 域分隔）；`key_prefix` 仅展示 |

---

## 4. 只增不改表

- `ledger`（调用账本）、`audit_logs`（审计日志）：**禁止 UPDATE / DELETE，只允许 INSERT**。
  应用层通过 repository 封装保证；建议 PG 侧配只读触发器做二次兜底（后续迁移）。
- 纠错方式：冲正（insert 一条负向/修正记录），不改历史行。

---

## 5. 表结构详述

### 5.1 `tenants`（租户）

用途：多租户一级隔离单元；云端 `launch_mode` 控制注册方式。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | uuid4 hex |
| name | String(128) | UNIQUE, NOT NULL | 租户名，全局唯一 |
| plan | String(16) | NOT NULL, 默认 'free', CHECK | free / pro / studio |
| launch_mode | String(16) | NOT NULL, 默认 'invite-only', CHECK | invite-only / public |
| is_active | Boolean | NOT NULL, 默认 true | 停用租户拒绝一切写入 |
| created_at | DateTime(tz) | NOT NULL | UTC |

索引：`name` 唯一索引（隐式）。
租户隔离：自身不带 `tenant_id`；是所有外键的根。

### 5.2 `users`（用户）

用途：归属单个租户的登录主体；角色控制管理后台权限。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | uuid4 hex |
| tenant_id | String(32) | FK→tenants.id, NOT NULL, 索引 | 所属租户 |
| username | String(64) | NOT NULL | 登录名 |
| email | String(256) | NOT NULL, 默认 '' | 可选 |
| password_hash | String(256) | NOT NULL | pbkdf2-sha256 哈希串，**永不返回前端** |
| salt | String(64) | NOT NULL | 独立随机盐，**永不返回前端** |
| role | String(16) | NOT NULL, 默认 'user', CHECK | owner / admin / user |
| is_active | Boolean | NOT NULL, 默认 true | 禁用即拒绝登录 |
| created_at | DateTime(tz) | NOT NULL | UTC |
| last_login_at | DateTime(tz) | NULL | 最近登录 |

索引/约束：`UNIQUE(tenant_id, username)`（同租户用户名唯一，不同租户可重名）；
`role` CHECK。
租户隔离：`tenant_id` 必填；登录时先按租户解析再验密。

### 5.3 `memberships`（会员订阅）

用途：用户当前计费周期的档位与额度；**会员额度 = YIMU Gateway credits 同一账本**，
网关调用扣减 `credits_used`，明细在 `ledger`。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL, 索引 | |
| user_id | String(32) | FK→users.id, NOT NULL, UNIQUE | 每用户一条有效记录 |
| tier | String(16) | NOT NULL, 默认 'free', CHECK | free / pro / studio |
| credits_total | Integer | NOT NULL, 默认 0 | 本周期总授信（点数，整数） |
| credits_used | Integer | NOT NULL, 默认 0 | 本周期已用（点数，整数） |
| period_start | DateTime(tz) | NOT NULL | 周期开始 |
| period_end | DateTime(tz) | NULL | 周期结束；NULL=长期有效 |
| status | String(16) | NOT NULL, 默认 'active', CHECK | active / expired / cancelled |
| created_at / updated_at | DateTime(tz) | NOT NULL | |

租户隔离：`tenant_id` 必填；扣减额度必须用行锁（`SELECT ... FOR UPDATE`，PG）
或原子 `UPDATE ... SET credits_used = credits_used + N` 防止超扣。

### 5.4 `gateway_keys`（网关 API Key）

用途：YIMU Gateway 的调用凭证；支持配额、限流、模型白名单、IP 白名单。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL, 索引 | |
| user_id | String(32) | FK→users.id, NOT NULL, 索引 | 持有人 |
| key_prefix | String(32) | NOT NULL | 如 `yimu_sk_ab12`，仅展示/排查 |
| key_hash | String(128) | NOT NULL, UNIQUE | SHA-256 哈希，**永不返回前端** |
| name | String(128) | NOT NULL, 默认 '' | 用户自命名别名 |
| quota_credits | Integer | NOT NULL, 默认 0 | 周期配额（点数） |
| rate_limit_rpm | Integer | NOT NULL, 默认 60 | 每分钟请求数 |
| rate_limit_tpm | Integer | NOT NULL, 默认 100000 | 每分钟 token 数 |
| allowed_models | JSON | NULL | 模型白名单数组；NULL=不限制 |
| ip_allowlist | JSON | NULL | IP 白名单数组；NULL/空=不限制 |
| status | String(16) | NOT NULL, 默认 'active', CHECK | active / revoked / expired |
| expires_at | DateTime(tz) | NULL | NULL=永不过期 |
| created_at / updated_at | DateTime(tz) | NOT NULL | |

索引/约束：`key_hash` 唯一；`status` CHECK；`user_id` 索引。
租户隔离：`tenant_id` 必填；鉴权时按 `key_hash` 查 key 后必须校验租户一致。
安全：原始 key 只在创建响应里返回一次；吊销=状态置 `revoked`，不删行（审计）。

### 5.5 `ledger`（调用账本）

用途：每次模型调用的计量/计费明细；**只增不改**。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | |
| key_id | String(32) | FK→gateway_keys.id, NULL, 索引 | NULL=内部直调 |
| model | String(128) | NOT NULL | 如 deepseek-chat |
| direction | String(16) | NOT NULL, CHECK | input / output（分开计费） |
| tokens | Integer | NOT NULL, 默认 0 | |
| cost_cents | Integer | NOT NULL, 默认 0 | **整数分**，杜绝浮点 |
| latency_ms | Integer | NOT NULL, 默认 0 | |
| cached | Boolean | NOT NULL, 默认 false | 是否命中缓存 |
| created_at | DateTime(tz) | NOT NULL, 索引 | UTC |

索引：**复合索引 `ix_ledger_tenant_created(tenant_id, created_at)`**（账单按租户+时间拉取）；
`key_id`、`created_at` 单列索引。
租户隔离：所有账单查询强制 `tenant_id` 过滤；该复合索引即为此设计。

### 5.6 `invites`（邀请码）

用途：`launch_mode=invite-only` 租户的注册/升级凭证；可批量生成。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL, 索引 | 发放租户 |
| code | String(64) | NOT NULL, UNIQUE | 人可读短码，全局唯一 |
| max_uses | Integer | NOT NULL, 默认 1 | 最大可用次数 |
| used_count | Integer | NOT NULL, 默认 0 | 已用次数 |
| credits_grant | Integer | NOT NULL, 默认 0 | 使用后赠送 credits 点数 |
| expires_at | DateTime(tz) | NULL | NULL=永不过期 |
| status | String(16) | NOT NULL, 默认 'active', CHECK | active / exhausted / revoked / expired |
| created_at | DateTime(tz) | NOT NULL | |

租户隔离：核销时校验 `tenant_id` 与注册目标租户一致；`used_count` 递增用原子更新防超发。

### 5.7 `assets`（素材库）

用途：图片/视频/音频素材统一登记；本地存相对路径，云端存对象存储 URL。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | |
| kind | String(16) | NOT NULL, CHECK | image / video / audio |
| path_or_url | Text | NOT NULL | 本地相对路径或云端 URL |
| prompt | Text | NOT NULL, 默认 '' | 生成提示词；上传素材可为空 |
| style | String(64) | NOT NULL, 默认 '' | 风格标签（如 赛博水墨） |
| tags | JSON | NULL | 自定义标签数组 |
| source | String(32) | NOT NULL, 默认 'generated', CHECK | generated / uploaded / drama |
| width / height | Integer | NULL | 像素尺寸 |
| user_id | String(32) | FK→users.id, NULL, 索引 | 创建人 |
| created_at | DateTime(tz) | NOT NULL, 索引 | |

索引：复合 `ix_assets_tenant_kind(tenant_id, kind)`；`created_at` 索引。
租户隔离：`tenant_id` 必填；文件访问 URL 必须经鉴权后签发，不做公开直链。

### 5.8 `drafts`（草稿）

用途：爆款内容（文章/图文/脚本）创作主体；对接选题→仿写→质检链路。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | |
| user_id | String(32) | FK→users.id, NOT NULL, 索引 | 创建人 |
| title | String(256) | NOT NULL, 默认 '' | |
| body_md | Text | NOT NULL, 默认 '' | Markdown 正文 |
| platform | String(32) | NOT NULL, 默认 '' | 目标平台（wechat_mp / xhs / douyin…） |
| status | String(16) | NOT NULL, 默认 'draft', CHECK | draft（草稿）/ pending_review（待审）/ published（已发布） |
| score | Float | NULL | 质检评分 0-100；NULL=未评分 |
| created_at / updated_at | DateTime(tz) | NOT NULL | |

索引：复合 `ix_drafts_tenant_status(tenant_id, status)`（工作台列表页主查询）。
租户隔离：`tenant_id` 必填。

### 5.9 `draft_history`（草稿版本历史）

用途：草稿每次显著修改追加版本，支持回滚/对比。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | |
| draft_id | String(32) | FK→drafts.id, NOT NULL, 索引 | 所属草稿 |
| version | Integer | NOT NULL | 同一草稿内从 1 递增 |
| body_md | Text | NOT NULL, 默认 '' | 该版本正文 |
| score | Float | NULL | 该版本评分 |
| created_at | DateTime(tz) | NOT NULL | |

约束：`UNIQUE(draft_id, version)`。
租户隔离：`tenant_id` 必填；写入前校验 `draft_id` 归属当前租户。

### 5.10 `drama_jobs`（短剧任务）

用途：8 步短剧流水线任务主体；`pipeline_state` 存断点快照以支持续跑。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | |
| title | String(256) | NOT NULL, 默认 '' | 短剧标题 |
| style | String(64) | NOT NULL, 默认 '' | 风格（古风 / 现代都市 / 赛博…） |
| status | String(16) | NOT NULL, 默认 'queued', CHECK | queued / running / completed / failed / cancelled |
| pipeline_state | JSON | NULL | 各步骤输入输出+断点，用于续跑 |
| current_step | Integer | NOT NULL, 默认 0 | 当前步骤序号（0 起） |
| user_id | String(32) | FK→users.id, NULL, 索引 | 创建人 |
| created_at / updated_at | DateTime(tz) | NOT NULL | |

索引：复合 `ix_drama_jobs_tenant_status(tenant_id, status)`。
租户隔离：`tenant_id` 必填；worker 认领任务时按租户分片。

### 5.11 `drama_shots`（分镜）

用途：短剧任务下的单个镜头产出物（图/视频/配音三件套）。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | 冗余租户列，避免经 job 二次 join 做隔离 |
| job_id | String(32) | FK→drama_jobs.id, NOT NULL, 索引 | 所属任务 |
| shot_no | Integer | NOT NULL | 同一任务内从 1 递增 |
| image_path | Text | NOT NULL, 默认 '' | 分镜图路径 |
| video_clip_path | Text | NOT NULL, 默认 '' | 视频片段路径；空=未生成 |
| voice_path | Text | NOT NULL, 默认 '' | 配音路径；空=未生成 |
| status | String(16) | NOT NULL, 默认 'pending', CHECK | pending / generating / done / failed |
| created_at / updated_at | DateTime(tz) | NOT NULL | |

约束：`UNIQUE(job_id, shot_no)`。
租户隔离：`tenant_id` 必填（写入时从所属 job 继承，读时直接过滤）。

### 5.12 `ip_characters`（IP 角色库）

用途：可复用的虚拟角色设定；`feature_anchors` 保证跨图一致性（对接图片质量专项）。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | |
| name | String(128) | NOT NULL | 角色名 |
| turnaround_path | Text | NOT NULL, 默认 '' | 三视图（正/侧/背拼图）路径 |
| feature_anchors | JSON | NULL | 特征锚点（发色/瞳色/服装/配饰…） |
| created_at / updated_at | DateTime(tz) | NOT NULL | |

约束：`UNIQUE(tenant_id, name)`（同租户角色名唯一）。
租户隔离：`tenant_id` 必填。

### 5.13 `async_tasks`（统一异步任务队列）

用途：网关调用、短剧步骤、批量生成等所有异步工作统一入口；替代项目 B 的 jobs 表。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | |
| type | String(64) | NOT NULL, 索引 | 任务类型（drama_step / image_gen / batch_publish…） |
| status | String(16) | NOT NULL, 默认 'queued', CHECK | queued / running / completed / failed / cancelled |
| progress | Integer | NOT NULL, 默认 0 | 0-100 |
| message | Text | NOT NULL, 默认 '' | 前端展示的状态说明 |
| params | JSON | NULL | 入参 |
| result | JSON | NULL | 完成后写入的结果 |
| error | Text | NOT NULL, 默认 '' | 失败原因 |
| timeout_sec | Integer | NOT NULL, 默认 0 | 超时秒数；0=不限制 |
| user_id | String(32) | FK→users.id, NULL, 索引 | 创建人；NULL=系统任务 |
| created_at | DateTime(tz) | NOT NULL | |
| started_at | DateTime(tz) | NULL | |
| updated_at | DateTime(tz) | NOT NULL | |
| finished_at | DateTime(tz) | NULL | |

索引：复合 `ix_async_tasks_tenant_status(tenant_id, status)`（worker 轮询）；
`type`、`user_id` 索引。
租户隔离：worker 按 `(tenant_id, status)` 认领；用户只能查自己租户的任务。

### 5.14 `audit_logs`（审计日志）

用途：敏感操作审计（登录、删改、配额调整、key 吊销等）；**只增不改**。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | String(32) | PK | |
| tenant_id | String(32) | FK, NOT NULL | |
| actor | String(64) | NOT NULL, 索引 | 操作人（用户 id；系统操作记 `system`） |
| action | String(128) | NOT NULL, 索引 | 如 `user.login` / `draft.delete` / `key.revoke` |
| target | String(256) | NOT NULL, 默认 '' | 作用对象，如 `draft:<id>` |
| detail | JSON | NULL | 变更前后、IP、UA 等 |
| created_at | DateTime(tz) | NOT NULL, 索引 | UTC |

索引：复合 `ix_audit_logs_tenant_created(tenant_id, created_at)`（按租户时间范围审计）；
`actor`、`action` 单列索引。
租户隔离：所有审计查询强制 `tenant_id` 过滤。

---

## 6. 连接与初始化

位置：`studio/db.py`（模型在 `studio/db_models.py`，两者分离：模型可被 Alembic 独立引用）。

```python
from studio.db import get_engine, init_db, get_session_factory

engine = get_engine("sqlite:///./data/yimu.db")          # 本地
engine = get_engine("postgresql+psycopg2://u:p@host/db")  # 云端
init_db(engine)                                           # 建表（幂等）
SessionFactory = get_session_factory(engine)              # FastAPI 依赖注入用
```

- `get_engine(db_url)`：SQLite 时自动 `check_same_thread=False`；PG 时配连接池。
- `init_db(engine)`：`Base.metadata.create_all`，幂等；SQLite 下额外开 WAL + `foreign_keys=ON`。
- 生产 schema 演进后续由 **Alembic** 管理（WS-A 契约冻结后接入），`init_db` 仅用于开发/测试与首次部署。

---

## 7. 与项目 B（基线）的对应关系

| 项目 B `core/db.py` | V7 新表 | 说明 |
|---|---|---|
| `users` | `users` | 重做：加 `tenant_id`，角色扩展 owner，密码哈希升级 pbkdf2（B 未明确算法） |
| `user_api_keys`（存加密 key） | `gateway_keys` | 重做：**只存哈希不存原文**；加配额/限流/模型白名单/IP 白名单 |
| `drafts` / `draft_history` | `drafts` / `draft_history` | 重做：加租户隔离、状态收敛为 draft/pending_review/published |
| `jobs` / `async_tasks` / `scheduled_posts` | `async_tasks` | 合并为统一任务队列；定时发布后续以 `type='scheduled_publish'` 承载 |
| `ip_characters` | `ip_characters` | 重做：加租户隔离、特征锚点 JSON |
| `topics`（热榜采集） | — | 项目 A 能力，V7.1 再移植；本期不建表 |
| `workspaces` | `tenants` | 概念升级为多租户 |

---

## 8. 后续待办（给 WS-B~F / WS-A 质量门禁）

1. Alembic 迁移基线（`init_db` 仅开发用）。
2. `TenantQuery` 仓储基类 + `test_tenant_isolation.py` 跨租户断言（质量门禁）。
3. `ledger` / `audit_logs` 的 PG 只读触发器兜底。
4. API 序列化白名单：`password_hash`、`salt`、`key_hash` 永不出现在响应中（code review 门禁）。
5. 额度扣减原子更新 + `memberships` 行锁（防超扣）。
