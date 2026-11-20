# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 爆款工作室 V9.0.0 数据库模型层。

设计要点（详见 docs/SCHEMA.md）：
- SQLAlchemy 2.0 ``Mapped`` 注解风格，SQLite / PostgreSQL 双兼容。
- 主键统一 32 位十六进制字符串（uuid4），避免 PG 专有类型。
- 时间统一带时区的 ``FlexibleDateTime()``，应用层写入 UTC。
- JSON 字段统一使用 ``sqlalchemy.JSON``（SQLite 落 TEXT，PG 落 JSONB）。
- 金额统一整数分（cost_cents），额度统一整数点数（credits），杜绝浮点。
- 敏感字段（password_hash / salt / key_hash）标记为「永不返回给前端」。
- ``ledger`` 与 ``audit_logs`` 为只增不改账本表。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .flex_datetime import FlexibleDateTime


def new_id() -> str:
    """生成 32 位十六进制主键。"""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """当前 UTC 时间（带时区）。"""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """所有模型的声明式基类。"""


class HasTenant:
    """租户隔离混入：除 tenants 自身外，所有业务表都带 tenant_id。

    仓储层约定（见 docs/SCHEMA.md「租户隔离」一节）：
    任何查询都必须显式加上 ``tenant_id == <当前租户>`` 过滤，
    写操作必须从请求上下文注入 tenant_id，禁止信任客户端传值。
    """

    # 所属租户 id（外键指向 tenants.id）
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False, index=True, default="default", server_default="default"
    )


# ---------------------------------------------------------------------------
# 租户与用户
# ---------------------------------------------------------------------------


class Tenant(Base):
    """租户：一级隔离单元。唯一不带 tenant_id 的表。"""

    __tablename__ = "tenants"

    # 租户主键
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 租户名称（如工作室 / 企业名），全局唯一
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # 套餐：free / pro / studio
    plan: Mapped[str] = mapped_column(String(16), nullable=False, default="free")
    # 云端首发模式：invite-only（邀请制）/ public（公开注册），默认邀请制
    launch_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="invite-only"
    )
    # 是否启用：True 启用 / False 停用
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint("plan IN ('free','pro','studio')", name="ck_tenants_plan"),
        CheckConstraint(
            "launch_mode IN ('invite-only','public')", name="ck_tenants_launch_mode"
        ),
    )


# ---------------------------------------------------------------------------
# 用户与用户级 API Key Vault
# ---------------------------------------------------------------------------
#
# ⭐ V9.3.2 P0-2：双层数据访问合并（审查报告"合并双层数据访问"建议）
#    core/auth.py（V6 裸 sqlite3）与 studio（V7 SQLAlchemy）历史上共用同一张
#    users 表但列集不同，靠 core/db.py:ensure_users_columns 自愈补列维持。
#    本版本把 core.auth 需要的全部列（plan / quota_used / quota_max /
#    last_login）与租户列（tenant_id，由 HasTenant 混入）补齐到 ORM 真源，
#    从此 studio.init_db(engine) 先建表也不会再缺 core.auth 依赖的列；
#    core 侧 ALTER TABLE 自愈保留作兜底（幂等），两条路径不再互斥。


class User(Base, HasTenant):
    """用户：归属单个租户。

    安全红线：``password_hash`` / ``salt`` 永不返回给前端，
    API 序列化时必须显式剔除。密码永不明文存储。

    V9.3.2 补充（core/auth.py 兼容列）：plan / quota_used / quota_max /
    last_login —— core.auth 的注册 / 登录 / CRUD 直接读这些列，
    缺失时表现为全鉴权接口 500（历史事故见 core/db.py:ensure_users_columns）。
    """

    __tablename__ = "users"

    # 用户主键
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 用户名（同一租户内唯一）
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    # 邮箱（可选）
    email: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    # 密码哈希（pbkdf2_hmac-sha256，格式见 hash_password）【永不返回给前端】
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    # 密码盐（每个用户独立随机）【永不返回给前端】
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    # 角色：owner（租户拥有者）/ admin（管理员）/ user（普通用户）
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    # 是否启用：True 启用 / False 禁用
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow
    )
    # 最近登录时间
    last_login_at: Mapped[datetime | None] = mapped_column(
        FlexibleDateTime(), nullable=True
    )

    # ---- ⭐ V9.3.2 P0-2：core.auth 兼容列（双层数据访问合并）----
    # 套餐档位（free / pro / studio / enterprise）：core.auth.register_user 写入
    #   TIER_CREDITS 对应的档位；studio 侧此前从不写，列由 core.db 自愈补齐。
    plan: Mapped[str] = mapped_column(String(16), nullable=False, default="free")
    # 已用算力点数（credits）：core.auth 注册即设 0，套餐升级 / 卡密核销改写
    quota_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 算力额度上限（credits）：注册默认 = studio.pricing.TIER_CREDITS['free']
    #   （单一真源，与 core/db.py:_CORE_USER_COLUMNS 保持一致，禁止硬编码数字）
    quota_max: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
    # 最近登录时间（⭐ V9.3.2 双层数据访问合并：统一为 FlexibleDateTime，
    #   与 core.auth._iso_now 的写入格式及 core/db.py 的 users.last_login TEXT 一致。
    #   存量 epoch 浮点值由 FlexibleDateTime 的读兼容层解析；
    #   新写入一律 ISO，从此 users 表两条写入路径不再有编码分歧）
    last_login: Mapped[datetime | None] = mapped_column(
        FlexibleDateTime(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
        CheckConstraint("role IN ('owner','admin','user')", name="ck_users_role"),
    )


class UserApiKey(Base, HasTenant):
    """用户级 API Key Vault（core/auth.py:save_user_api_key 的 ORM 真源）。

    密钥可逆混淆加密后落库（core.auth.encrypt_key）；
    ``api_key`` 列【永不返回给前端】，API 只回显 masked_key。
    """

    __tablename__ = "user_api_keys"

    # 主键（key-<hex8>，与 core.auth 现有生成规则对齐）
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 归属用户
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False, index=True
    )
    # 模型服务类型（deepseek / openai / claude / ... 小写）
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    # 混淆加密后的 API Key【永不返回给前端】
    api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 可选：自定义 Base URL（聚合网关 / 自建推理服务）
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # 可选：默认模型 id
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # 是否当前生效（同 provider 多条时取最新创建且 is_active=1）
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 备注名称（用户自填，便于多 Key 区分）
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("ix_user_api_keys_user_active", "user_id", "is_active"),
    )


# ---------------------------------------------------------------------------
# 会员与网关
# ---------------------------------------------------------------------------


class Membership(Base, HasTenant):
    """会员订阅：记录用户当前周期内的会员档位与额度使用。

    会员额度与 YIMU Gateway 的 credits 为同一账本：
    网关每次调用扣减此处 credits_used（明细见 ledger）。
    """

    __tablename__ = "memberships"

    # 主键
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 所属用户（每用户一条有效记录）
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False, unique=True
    )
    # 会员档位：free / pro / studio
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="free")
    # 本周期总授信额度（整数 credits 点数）
    credits_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 本周期已用额度（整数 credits 点数）
    credits_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 周期开始时间
    period_start: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow
    )
    # 周期结束时间（NULL 表示长期有效）
    period_end: Mapped[datetime | None] = mapped_column(
        FlexibleDateTime(), nullable=True
    )
    # 状态：active（有效）/ expired（过期）/ cancelled（取消）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow
    )
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("tier IN ('free','pro','studio')", name="ck_memberships_tier"),
        CheckConstraint(
            "status IN ('active','expired','cancelled')",
            name="ck_memberships_status",
        ),
    )


class GatewayKey(Base, HasTenant):
    """YIMU Gateway API Key：只存 key 的哈希，前缀仅用于展示。

    安全红线：原始 key 只在创建瞬间返回一次，之后永远不可再查；
    ``key_hash`` 永不返回给前端；校验时用哈希比对。
    """

    __tablename__ = "gateway_keys"

    # 主键
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 所属用户
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False, index=True
    )
    # key 前缀（如 "yimu_sk_ab12"），仅用于展示与排查
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    # key 的 SHA-256 哈希（加域分隔）【永不返回给前端】
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # key 别名（用户自命名）
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # 配额：周期内可用 credits 总数
    quota_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 限流：每分钟请求数
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # 限流：每分钟 token 数
    rate_limit_tpm: Mapped[int] = mapped_column(Integer, nullable=False, default=100000)
    # 允许调用的模型列表（JSON 数组，如 ["deepseek-chat", "gpt-4o"]）
    allowed_models: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # IP 白名单（JSON 数组，空表示不限制）
    ip_allowlist: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 状态：active（有效）/ revoked（吊销）/ expired（过期）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # 过期时间（NULL 表示永不过期）
    expires_at: Mapped[datetime | None] = mapped_column(
        FlexibleDateTime(), nullable=True
    )
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow
    )
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','revoked','expired')",
            name="ck_gateway_keys_status",
        ),
    )


class Ledger(Base, HasTenant):
    """网关调用账本：每次模型调用的计量记录。

    【只增不改】：禁止 UPDATE / DELETE，只能 INSERT。

    ⭐ R2-4 单位统一：``cost_cents`` 存的语义是 **credits 点数**（不是人民币分）。
       历史上有三种语义混写同一列（网关写点数 / 生图写 5×100 / adapter 写点数），
       差 100 倍，导致任何 SUM(cost_cents) 都得出无意义数字（含 key_used_credits）。
       现统一为「1 行 = N credits」，与 memberships.credits_used 同量纲，可直接对账。
       列名 cost_cents 保留仅为兼容既有库与 UI 字段，不再表示「分」。
    """

    __tablename__ = "ledger"

    # 主键
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 调用的网关 key（可为空：内部直调）
    key_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("gateway_keys.id"), nullable=True, index=True
    )
    # 模型名（如 deepseek-chat）
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    # 方向：input（输入）/ output（输出），分开计量计费
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    # token 数量
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 费用（⭐ R2-4：语义为 credits 点数，非人民币分）
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 延迟毫秒
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 是否命中缓存
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow, index=True
    )

    __table_args__ = (
        CheckConstraint("direction IN ('input','output')", name="ck_ledger_direction"),
        # 租户账单查询复合索引：按租户 + 时间范围拉账单
        Index("ix_ledger_tenant_created", "tenant_id", "created_at"),
    )


class Invite(Base, HasTenant):
    """邀请码：供 launch_mode=invite-only 的租户发放注册 / 升级资格。"""

    __tablename__ = "invites"

    # 主键
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 邀请码（全局唯一，人可读短码）
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # 最大可用次数
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 已用次数
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 使用后赠送的 credits 点数
    credits_grant: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 过期时间（NULL 表示永不过期）
    expires_at: Mapped[datetime | None] = mapped_column(
        FlexibleDateTime(), nullable=True
    )
    # 状态：active（有效）/ exhausted（用完）/ revoked（作废）/ expired（过期）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # R5-4 邀请人：发放这张邀请码的用户 user_id。
    # ⭐ 空串= 运营在后台批量发放的卡密（无邀请人，不发奖励）。
    #    这是裂变动机的来源——没有 inviter_id 就无法回答「谁带来了谁」。
    inviter_id: Mapped[str] = mapped_column(
        String(32), nullable=False, default=""
    )
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','exhausted','revoked','expired')",
            name="ck_invites_status",
        ),
    )


class InviteReferral(Base, HasTenant):
    """R5-4 邀请关系流水：谁邀请了谁、奖励了多少额度。

    与 ``invites.inviter_id`` 的分工：invites 记「这张码是谁发的」，
    本表记「每一次实际核销」，因此一个邀请人可以有多条记录
    （一张多��码），也才能算出累计邀请数与累计奖励（裂变 ROI）。
    """

    __tablename__ = "invite_referrals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 邀请人
    inviter_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # 被邀请人
    invitee_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # 使用的邀请码（便于对账）
    invite_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 本次核销给邀请人的奖励点数
    reward_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("idx_invite_referrals_inviter", "inviter_id"),
    )


# ---------------------------------------------------------------------------
# 任务队列与审计
# ---------------------------------------------------------------------------



class AuditLog(Base, HasTenant):
    """审计日志：记录敏感操作（登录、删改、配额调整等）。

    【只增不改】：禁止 UPDATE / DELETE，只能 INSERT。
    """

    __tablename__ = "audit_logs"

    # 主键
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 操作人（用户 id；系统操作记 "system"）
    actor: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 动作（如 user.login / draft.delete / key.revoke）
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # 作用对象（如 draft:<id>）
    target: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    # 详情（JSON：变更前后、IP、UA 等）
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow, index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
    )


class Order(Base, HasTenant):
    """R3-2 订单：用户下单购买套餐（或充值包）的一条记录。

    ⭐ 为什么要有这张表：此前收款只有「运营手工生成 CDKey → 微信群发」，
       系统里**没有任何一行记录谁付了钱、付了多少**。缺了这张表，
       退款（R3-6）无从谈起，营收也无法对账。

    收款流程（R3-2 手工核销方案，支付资质未落地时也能收钱）：
        下单 → 立刻生成一张 CDKey（invites 行，max_uses=1）
             → 把卡密与支付指引回给用户
             → 用户转账 → 管理员核销确认
             → 用户自己兑换卡密，额度到账
    卡密本身仍走 invites 表（与既有 redeem 同源），
    本表只负责「订单态」与「退款时该扣多少额度」。

    状态机：
        pending（待支付）→ paid（已核销/已收款）→ refunded（已退款）
        pending → cancelled（用户放弃或管理员作废）
    ⚠️ 只允许 pending→paid、paid→refunded、pending→cancelled，
       终态不可再迁移，非法迁移直接 raise（防重复退款）。
    """

    __tablename__ = "orders"

    # 主键（同时是对外订单号：32 位十六进制，不可枚举）
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 下单用户
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False, index=True
    )
    # 套餐码（pro / studio；充值包为 credits_pack）
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="pro")
    # 本单发放的额度（credits）
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 应付金额（分）——下单时快照，日后改价不影响历史订单
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 状态：pending / paid / refunded / cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # 本单生成的 CDKey（invites.code）。未生成时为空串。
    cdkey: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 退款时实际扣回的额度（可能小于 credits：用户已花掉的部分扣不回来）
    refunded_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 退款备注/原因（运营填写，进审计）
    note: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow, index=True
    )
    # 核销（确认收款）时间
    paid_at: Mapped[datetime | None] = mapped_column(
        FlexibleDateTime(), nullable=True
    )
    # 退款时间
    refunded_at: Mapped[datetime | None] = mapped_column(
        FlexibleDateTime(), nullable=True
    )

    __table_args__ = (
        Index("ix_orders_tenant_status", "tenant_id", "status"),
        CheckConstraint(
            "status IN ('pending','paid','refunded','cancelled')",
            name="ck_orders_status",
        ),
    )


class QuotaCounter(Base, HasTenant):
    """配额计数器：按自然日/周/月统计用户某能力的使用次数。

    用于会员分级的功能配额（如 free 每日热榜采集 1 次、每周短剧 1 次）。
    同一 (user_id, capability, window, window_start) 只增计数，不删改历史；
    窗口滚动后自然产生新行，旧行由定期清理任务归档（不阻塞）。
    """

    __tablename__ = "quota_counters"

    # 主键
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 所属用户（用户 id；不建外键——配额计数是运营数据，允许用户行尚未初始化时
    # 先计数，避免 FK 阻塞主功能；租户隔离仍由 tenant_id 保证）
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 能力码（如 hot_daily / tts_daily / drama_weekly / image_race_weekly）
    capability: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 窗口类型：day（自然日）/ week（自然周，周一为始）/ month（自然月）
    window: Mapped[str] = mapped_column(String(16), nullable=False)
    # 窗口起始标识：day→"2026-10-08"；week→周一日期；month→"2026-10"
    window_start: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # 本窗口已用次数
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        FlexibleDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "capability", "window", "window_start",
            name="uq_quota_counters_window",
        ),
        CheckConstraint(
            "window IN ('day','week','month')", name="ck_quota_counters_window"
        ),
    )


# ---------------------------------------------------------------------------
# 密码学小工具（pbkdf2_hmac-sha256）
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 210_000  # OWASP 2023 对 HMAC-SHA-256 的建议量级


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """用 pbkdf2_hmac-sha256 生成（hash, salt）。

    返回的 hash 形如 ``pbkdf2_sha256$210000$<salt>$<hex>``，自带算法与轮数，
    便于将来升级算法时平滑迁移。明文密码绝不落盘。
    """
    if salt is None:
        salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${dk.hex()}", salt


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码。hash 格式不符时返回 False（不抛异常，避免信息泄露）。"""
    try:
        algo, iters, salt, _ = password_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iters)
        )
        expected = f"{algo}${iters}${salt}${dk.hex()}"
        return hmac.compare_digest(expected, password_hash)
    except (ValueError, AttributeError):
        return False


def hash_gateway_key(raw_key: str) -> str:
    """网关 API Key 哈希：SHA-256（加固定域分隔，防止与密码哈希混淆）。"""
    return hashlib.sha256(f"yimu-gateway-key:{raw_key}".encode("utf-8")).hexdigest()
