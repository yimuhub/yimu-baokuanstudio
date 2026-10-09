# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 多用户认证、会话与 API Key Vault 存储管理模块。

- 密码散列：pbkdf2_hmac-sha256，21 万轮，新哈希自带算法标识；
  老版本 10 万轮哈希仍可验证（平滑迁移），新注册一律用新格式。
- Token 机制：无依赖轻量级签名令牌（自包含 exp、user_id、role，有效期30天）
- API Key Vault：密钥混淆加密存储，用户自填 API Key 入库前加密
- ⭐ 签名密钥只走环境变量 YIMU_SECRET_KEY，无默认值；缺失直接抛错，绝不静默降级。
"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

# R2-1：额度数字的唯一真源。注册/建管理员一律从这里取，禁止硬编码。
from studio.pricing import TIER_CREDITS

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DB_PATH = DATA / "mediaflow.db"

_PBKDF2_ITERATIONS = 210_000  # OWASP 对 HMAC-SHA-256 的建议量级（新哈希）
_LEGACY_ITERATIONS = 100_000  # 老版本哈希轮数（仅用于验证存量口令）


def _free_quota() -> int:
    """免费档额度（credits）：取自定价真源，禁止在业务代码里硬编码额度数字。"""
    return TIER_CREDITS["free"]


def _secret_key() -> str:
    """⭐ 签名密钥唯一来源：环境变量 YIMU_SECRET_KEY。

    无默认值——缺失直接抛错，绝不使用硬编码密钥启动。
    """
    key = os.environ.get("YIMU_SECRET_KEY", "")
    if not key:
        raise RuntimeError(
            "⛔ YIMU_SECRET_KEY 环境变量未设置：签名密钥不许硬编码，"
            "请设置后重启（示例：export YIMU_SECRET_KEY=$(openssl rand -hex 32)）。"
        )
    return key


def _db():
    """打开 auth 专用连接。

    ⭐ R3-9：这里也补齐 users 列。``core.db`` 与 ``studio.db_models`` 共用同一张
    ``users`` 表但列集不同，谁先建表另一方就会缺列——新装机器若studio 先
    init_db，``get_user_by_id`` 会抛 ``no such column: plan``，
    表现为**所有需要鉴权的接口全部 500**。
    在此补列可让两条建连路径都自愈（core.db.conn 与本函数）。
    """
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    from core.db import ensure_users_columns

    ensure_users_columns(c)
    return c


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """生成盐值和哈希密码（新格式自带算法标识，可独立验证）。

    返回 (password_hash, salt)，password_hash 形如
    ``pbkdf2_sha256$210000$<salt>$<hex>``。调用方原有入库逻辑不变。
    """
    if not salt:
        salt = uuid.uuid4().hex[:16]
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${dk.hex()}", salt


def _verify_legacy(password: str, hashed: str, salt: str) -> bool:
    """验证老版本哈希（10 万轮、无算法标识），用于存量账号平滑迁移。"""
    try:
        check = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), _LEGACY_ITERATIONS
        ).hex()
        return hmac.compare_digest(hashed, check)
    except Exception:
        return False


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """验证密码：优先新格式，失败则回退老格式（存量账号不断连）。"""
    try:
        if hashed.startswith("pbkdf2_sha256$"):
            algo, iters, salt_in_hash, _ = hashed.split("$", 3)
            if algo != "pbkdf2_sha256":
                return False
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                salt_in_hash.encode("utf-8"), int(iters),
            )
            expected = f"{algo}${iters}${salt_in_hash}${dk.hex()}"
            return hmac.compare_digest(expected, hashed)
    except (ValueError, AttributeError):
        pass
    # 回退：老版本哈希（salt 独立存列）
    return _verify_legacy(password, hashed, salt)


def make_token(payload: dict) -> str:
    """生成带有签名的会话 Token（30天有效）"""
    p = dict(payload)
    p["exp"] = time.time() + 30 * 86400
    p["iat"] = time.time()
    p_b64 = base64.urlsafe_b64encode(json.dumps(p, separators=(',', ':')).encode()).decode().rstrip("=")
    sig = hmac.new(_secret_key().encode(), p_b64.encode(), hashlib.sha256).hexdigest()
    return f"{p_b64}.{sig}"


def verify_token(token: str) -> dict | None:
    """验证并解码 Token"""
    if not token or not isinstance(token, str):
        return None
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        p_b64, sig = parts
        exp_sig = hmac.new(_secret_key().encode(), p_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, exp_sig):
            return None
        padded = p_b64 + "=" * ((4 - len(p_b64) % 4) % 4)
        p = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if p.get("exp", 0) < time.time():
            return None
        return p
    except Exception:
        return None


# ---------------- API Key 加密与解密 ----------------

def encrypt_key(plain_key: str) -> str:
    """对用户 API Key 进行可逆轻量混淆加密"""
    if not plain_key:
        return ""
    key_bytes = plain_key.encode("utf-8")
    mask = hashlib.sha256(_secret_key().encode()).digest()
    encrypted = bytes(b ^ mask[i % len(mask)] for i, b in enumerate(key_bytes))
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_key(cipher_b64: str) -> str:
    """解密用户 API Key"""
    if not cipher_b64:
        return ""
    try:
        encrypted = base64.urlsafe_b64decode(cipher_b64.encode())
        mask = hashlib.sha256(_secret_key().encode()).digest()
        decrypted = bytes(b ^ mask[i % len(mask)] for i, b in enumerate(encrypted))
        return decrypted.decode("utf-8")
    except Exception:
        return ""


# ---------------- 用户管理操作 ----------------

def ensure_default_admin(password: str | None = None) -> bool:
    """初始化保证系统至少有一个管理员账户。

    ⭐ 口令只从参数或环境变量 YIMU_ADMIN_PASSWORD 获取，不再内置弱口令；
    未提供口令时跳过创建并返回 False（调用方自行提示）。
    """
    pwd = password or os.environ.get("YIMU_ADMIN_PASSWORD", "")
    if not pwd:
        print("⚠️ 未设置 YIMU_ADMIN_PASSWORD，跳过默认管理员创建。")
        return False
    if len(pwd) < 8:
        raise ValueError("管理员口令至少 8 个字符")
    c = _db()
    r = c.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if not r:
        uid = "u-admin"
        now_ts = time.time()
        pwd_hash, salt = hash_password(pwd)
        #⭐ R2-1：管理员额度同样取自定价真源。历史硬编码 10,000,000 credits
        #   按 0.01 元/credit 折算≈ 100 万元，属同类漏钱口子，一并收敛。
        c.execute(
            "INSERT OR REPLACE INTO users (id, username, email, password_hash, salt, role, plan, quota_used, quota_max, created_at, last_login, is_active) "
            "VALUES (?,?,?,?,?,?,?,0,?,?,?,1)",
            (uid, "admin", "admin@localhost", pwd_hash, salt, "admin", "enterprise",
             TIER_CREDITS["studio"], now_ts, now_ts)
        )
        c.commit()
    c.close()
    return True


def register_user(username: str, password: str, email: str = "") -> dict:
    """注册新用户"""
    username = username.strip()
    if len(username) < 2:
        raise ValueError("用户名至少2个字符")
    if len(password) < 6:
        raise ValueError("密码至少6个字符")

    c = _db()
    exist = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if exist:
        c.close()
        raise ValueError("该用户名已被注册，请更换")

    uid = f"u-{uuid.uuid4().hex[:10]}"
    now_ts = time.time()
    pwd_hash, salt = hash_password(password)

    #⭐ R2-1：新用户初始体验额度取自定价真源（studio/pricing.TIER_CREDITS），
    #   不再硬编码 500000。历史硬编码值按 0.05 元/篇折算≈ 25000 元白送，
    #   是比卡密后门更隐蔽的漏钱口子。免费档现为 3000 credits（=30 元）。
    free_quota = TIER_CREDITS["free"]
    c.execute(
        "INSERT INTO users (id, username, email, password_hash, salt, role, plan, quota_used, quota_max, created_at, last_login, is_active) "
        "VALUES (?,?,?,?,?,?,'free',0,?,?,?,1)",
        (uid, username, email.strip(), pwd_hash, salt, "user", free_quota, now_ts, now_ts)
    )
    c.commit()
    c.close()

    token = make_token({"user_id": uid, "username": username, "role": "user"})
    return {
        "ok": True,
        "token": token,
        "user": {
            "id": uid,
            "username": username,
            "email": email,
            "role": "user",
            "plan": "free",
            "quota_max": free_quota,
            "quota_used": 0
        }
    }


def login_user(username: str, password: str) -> dict:
    """用户登录"""
    username = username.strip()
    c = _db()
    r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not r:
        c.close()
        raise ValueError("用户名或密码错误")

    user_dict = dict(r)
    if not user_dict.get("is_active"):
        c.close()
        raise ValueError("账号已被停用，请联系管理员")

    if not verify_password(password, user_dict["password_hash"], user_dict["salt"]):
        c.close()
        raise ValueError("用户名或密码错误")

    now_ts = time.time()
    c.execute("UPDATE users SET last_login=? WHERE id=?", (now_ts, user_dict["id"]))
    c.commit()
    c.close()

    token = make_token({"user_id": user_dict["id"], "username": user_dict["username"], "role": user_dict["role"]})
    return {
        "ok": True,
        "token": token,
        "user": {
            "id": user_dict["id"],
            "username": user_dict["username"],
            "email": user_dict.get("email", ""),
            "role": user_dict["role"],
            "plan": user_dict.get("plan", "free"),
            "quota_max": user_dict.get("quota_max") or _free_quota(),
            "quota_used": user_dict.get("quota_used", 0)
        }
    }


def get_user_by_id(user_id: str) -> dict | None:
    """根据 user_id 查询用户画像"""
    c = _db()
    # ⭐ R2-3：必须带上 tenant_id —— 计费按 (tenant_id, user_id) 定位memberships 行，
    #   拿不到租户就只能退化到 "default"，多租户下会扣错账。
    r = c.execute("SELECT id, username, email, role, plan, quota_used, quota_max, created_at, last_login, is_active, tenant_id FROM users WHERE id=?", (user_id,)).fetchone()
    c.close()
    return dict(r) if r else None


# ---------------- 用户专属 API Key Vault ----------------

def list_user_api_keys(user_id: str) -> list[dict]:
    """查询用户保存的所有自定义模型服务配置"""
    c = _db()
    rows = c.execute("SELECT id, user_id, provider, base_url, model_id, is_active, label, created_at, api_key FROM user_api_keys WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        raw_key = decrypt_key(d["api_key"])
        # 安全脱敏显示：sk-xxxx...1234
        if len(raw_key) > 8:
            d["masked_key"] = f"{raw_key[:4]}****{raw_key[-4:]}"
        else:
            d["masked_key"] = "********"
        del d["api_key"]
        out.append(d)
    return out


def save_user_api_key(user_id: str, provider: str, api_key: str, base_url: str = "", model_id: str = "", label: str = "") -> dict:
    """保存或更新用户的自定义模型服务 API Key"""
    c = _db()
    kid = f"key-{uuid.uuid4().hex[:8]}"
    enc_key = encrypt_key(api_key.strip())
    now_ts = time.time()

    # 将此用户同 provider 的其它 key 设为非默认（或者直接替换）
    c.execute(
        "INSERT INTO user_api_keys (id, user_id, provider, api_key, base_url, model_id, is_active, label, created_at) "
        "VALUES (?,?,?,?,?,?,1,?,?)",
        (kid, user_id, provider.strip().lower(), enc_key, base_url.strip(), model_id.strip(), label.strip() or provider, now_ts)
    )
    c.commit()
    c.close()
    return {"id": kid, "provider": provider, "label": label, "model_id": model_id}


def delete_user_api_key(user_id: str, key_id: str) -> bool:
    """删除用户的指定 API Key"""
    c = _db()
    c.execute("DELETE FROM user_api_keys WHERE id=? AND user_id=?", (key_id, user_id))
    c.commit()
    c.close()
    return True


def get_active_user_llm_config(user_id: str) -> dict | None:
    """获取用户当前正在生效的模型调用凭证。
    若用户未配置自己的 Key，或者配置为使用平台托管，则返回 None（自动走平台默认 master key）。
    """
    c = _db()
    r = c.execute("SELECT * FROM user_api_keys WHERE user_id=? AND is_active=1 ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
    c.close()
    if not r:
        return None
    d = dict(r)
    d["plain_api_key"] = decrypt_key(d["api_key"])
    return d
