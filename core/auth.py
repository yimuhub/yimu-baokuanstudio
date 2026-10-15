# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 多用户认证、会话与 API Key Vault 存储管理模块。

- 密码散列：pbkdf2_hmac-sha256，21 万轮，新哈希自带算法标识；
  老版本 10 万轮哈希仍可验证（平滑迁移），新注册一律用新格式。
- Token 机制：无依赖轻量级签名令牌（自包含 exp、user_id、role，有效期30天）
- API Key Vault：带随机 Nonce + HMAC 校验的流加密存储（v2 格式），向后兼容旧版解密
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import secrets
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
_PROCESS_FALLBACK_SECRET = secrets.token_hex(32)


def _free_quota() -> int:
    """免费档额度（credits）：取自定价真源，禁止在业务代码里硬编码额度数字。"""
    return TIER_CREDITS["free"]


def _iso_now() -> str:
    """当前 UTC 时间的 ISO-8601 字符串。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _secret_key() -> str:
    """⭐ 签名密钥：优先取环境变量 YIMU_SECRET_KEY；未配置时使用进程级高熵随机密钥，绝不使用固定公开常量，也不污染 os.environ。"""
    key = os.environ.get("YIMU_SECRET_KEY", "").strip()
    if key:
        return key
    return _PROCESS_FALLBACK_SECRET


def _db():
    """打开 auth 专用连接。"""
    from core.db import _connect_sqlite, ensure_users_columns
    c = _connect_sqlite(DB_PATH)
    c.row_factory = sqlite3.Row
    ensure_users_columns(c)
    return c


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """生成盐值和哈希密码（新格式自带算法标识，可独立验证）。"""
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
    return _verify_legacy(password, hashed, salt)


def make_token(payload: dict) -> str:
    """生成带有签名的会话 Token（30天有效，同时携带 uid/tenant_id 兼容 studio.auth）"""
    p = dict(payload)
    if "user_id" in p and "uid" not in p:
        p["uid"] = p["user_id"]
    p.setdefault("tenant_id", "default")
    p["exp"] = int(time.time()) + 30 * 86400
    p["iat"] = int(time.time())
    p_b64 = base64.urlsafe_b64encode(json.dumps(p, separators=(',', ':')).encode()).decode().rstrip("=")
    sig = hmac.new(_secret_key().encode(), p_b64.encode(), hashlib.sha256).hexdigest()
    return f"{p_b64}.{sig}"


def verify_token(token: str) -> dict | None:
    """验证并解码 Token（同时兼容 core.auth make_token 与 studio.auth create_session_token）"""
    if not token or not isinstance(token, str):
        return None
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        p_b64, sig = parts
        padded = p_b64 + "=" * ((4 - len(p_b64) % 4) % 4)
        raw_bytes = base64.urlsafe_b64decode(padded.encode())
        # 兼容1：core.auth 签名在 p_b64 上
        exp_sig_b64 = hmac.new(_secret_key().encode(), p_b64.encode(), hashlib.sha256).hexdigest()
        # 兼容2：studio.auth 签名在解码后的 raw_bytes 上
        exp_sig_raw = hmac.new(_secret_key().encode(), raw_bytes, hashlib.sha256).hexdigest()
        if not (hmac.compare_digest(sig, exp_sig_b64) or hmac.compare_digest(sig, exp_sig_raw)):
            return None
        p = json.loads(raw_bytes.decode("utf-8"))
        if p.get("exp", 0) < time.time():
            return None
        if "uid" in p and "user_id" not in p:
            p["user_id"] = p["uid"]
        return p
    except Exception:
        return None


# ---------------- API Key 加密与解密 ----------------

def _derive_keystream(secret: bytes, nonce: bytes, length: int) -> bytes:
    """使用 HMAC-SHA256 Counter Mode 派生任意长度的伪随机密钥流（每个 Nonce 完全独立）。"""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(secret, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt_key(plain_key: str) -> str:
    """对用户 API Key 进行带随机 Nonce 与 HMAC 认证的加密（v2 格式）。"""
    if not plain_key:
        return ""
    key_bytes = plain_key.encode("utf-8")
    secret = hashlib.sha256(_secret_key().encode("utf-8")).digest()
    nonce = secrets.token_bytes(16)
    stream = _derive_keystream(secret, nonce, len(key_bytes))
    cipher = bytes(b ^ s for b, s in zip(key_bytes, stream))
    mac = hmac.new(secret, b"v2|" + nonce + cipher, hashlib.sha256).hexdigest()[:32]
    c_b64 = base64.urlsafe_b64encode(cipher).decode("ascii").rstrip("=")
    return f"v2${nonce.hex()}${c_b64}${mac}"


def decrypt_key(cipher_b64: str) -> str:
    """解密用户 API Key（支持 v2 随机 Nonce 认证格式，并平滑兼容历史 v1 XOR 格式）。"""
    if not cipher_b64:
        return ""
    try:
        secret = hashlib.sha256(_secret_key().encode("utf-8")).digest()
        if cipher_b64.startswith("v2$"):
            _, nonce_hex, c_b64, mac = cipher_b64.split("$", 3)
            nonce = bytes.fromhex(nonce_hex)
            pad = "=" * ((4 - len(c_b64) % 4) % 4)
            cipher = base64.urlsafe_b64decode((c_b64 + pad).encode("ascii"))
            expected_mac = hmac.new(secret, b"v2|" + nonce + cipher, hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(mac, expected_mac):
                return ""
            stream = _derive_keystream(secret, nonce, len(cipher))
            plain = bytes(b ^ s for b, s in zip(cipher, stream))
            return plain.decode("utf-8")
        # 兼容历史 v1 格式
        pad = "=" * ((4 - len(cipher_b64) % 4) % 4)
        encrypted = base64.urlsafe_b64decode((cipher_b64 + pad).encode())
        decrypted = bytes(b ^ secret[i % len(secret)] for i, b in enumerate(encrypted))
        return decrypted.decode("utf-8")
    except Exception:
        return ""


# ---------------- 用户管理操作 ----------------

def ensure_default_admin(password: str | None = None) -> bool:
    """初始化保证系统至少有一个管理员账户。"""
    pwd = password or os.environ.get("YIMU_ADMIN_PASSWORD", "") or os.environ.get("ADMIN_PASSWORD", "")
    if not pwd:
        print("⚠️ 未设置 YIMU_ADMIN_PASSWORD / ADMIN_PASSWORD，跳过默认管理员创建。")
        return False
    if len(pwd) < 8:
        raise ValueError("管理员口令至少 8 个字符")
    c = _db()
    r = c.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if not r:
        uid = "u-admin"
        now_ts = _iso_now()
        pwd_hash, salt = hash_password(pwd)
        c.execute(
            "INSERT OR REPLACE INTO users (id, username, email, password_hash, salt, role, plan, quota_used, quota_max, created_at, last_login, is_active, tenant_id) "
            "VALUES (?,?,?,?,?,?,?,0,?,?,?,1,'default')",
            (uid, "admin", "admin@localhost", pwd_hash, salt, "admin", "enterprise",
             TIER_CREDITS["studio"], now_ts, now_ts)
        )
        c.commit()
    c.close()
    return True


def register_user(username: str, password: str, email: str = "", invite_code: str = "") -> dict:
    """注册新用户（同步记 signup 漏斗埋点，并支持可选邀请码裂变核销）。"""
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
    now_ts = _iso_now()
    pwd_hash, salt = hash_password(password)

    free_quota = TIER_CREDITS["free"]
    c.execute(
        "INSERT INTO users (id, username, email, password_hash, salt, role, plan, quota_used, quota_max, created_at, last_login, is_active) "
        "VALUES (?,?,?,?,?,?,'free',0,?,?,?,1)",
        (uid, username, email.strip(), pwd_hash, salt, "user", free_quota, now_ts, now_ts)
    )
    c.commit()
    c.close()

    # 若携带了邀请码，尝试通过裂变模块或卡密模块兑付奖励（绝不阻断主注册）
    bonus_credits = 0
    clean_code = (invite_code or "").strip()
    if clean_code:
        try:
            from core import fission
            ref_res = fission.accept_referral(clean_code, uid)
            if ref_res.get("ok"):
                bonus_credits = int(ref_res.get("invitee_bonus", 0) or 0)
        except Exception:
            pass

    # 埋点：记录注册漏斗首步 signup
    try:
        from core import analytics
        analytics.track("signup", uid, {"username": username, "invite_code": clean_code})
    except Exception:
        pass

    token = make_token({"user_id": uid, "uid": uid, "tenant_id": "default", "username": username, "role": "user"})
    return {
        "ok": True,
        "token": token,
        "user": {
            "id": uid,
            "username": username,
            "email": email,
            "role": "user",
            "plan": "free",
            "quota_max": free_quota + bonus_credits,
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

    now_ts = _iso_now()
    c.execute("UPDATE users SET last_login=? WHERE id=?", (now_ts, user_dict["id"]))
    c.commit()
    c.close()

    tenant_id = user_dict.get("tenant_id") or "default"
    token = make_token({
        "user_id": user_dict["id"],
        "uid": user_dict["id"],
        "tenant_id": tenant_id,
        "username": user_dict["username"],
        "role": user_dict["role"],
    })
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
    r = c.execute("SELECT id, username, email, role, plan, quota_used, quota_max, created_at, last_login, is_active, tenant_id FROM users WHERE id=?", (user_id,)).fetchone()
    c.close()
    return dict(r) if r else None


# ---------------- 👥 会员管理与账号体系 CRUD ----------------

def list_users_crud(keyword: str = "", limit: int = 50, offset: int = 0) -> dict:
    """获取系统用户列表（带搜索与分页）"""
    c = _db()
    kw = f"%{keyword.strip()}%" if keyword.strip() else "%"
    total = c.execute(
        "SELECT COUNT(*) FROM users WHERE username LIKE ? OR email LIKE ?",
        (kw, kw)
    ).fetchone()[0]
    rows = c.execute(
        "SELECT id, username, email, role, plan, quota_used, quota_max, created_at, last_login, is_active, tenant_id "
        "FROM users WHERE username LIKE ? OR email LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (kw, kw, limit, offset)
    ).fetchall()
    c.close()
    return {
        "total": total,
        "items": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset
    }


def create_user_crud(username: str, password: str, email: str = "", role: str = "user", plan: str = "free", quota_max: int = 0) -> dict:
    """管理员直接新建用户"""
    username = username.strip()
    if len(username) < 2:
        raise ValueError("用户名至少2个字符")
    if len(password) < 6:
        raise ValueError("密码至少6个字符")
    if role not in ("user", "admin", "owner"):
        role = "user"
    if not quota_max or quota_max <= 0:
        quota_max = TIER_CREDITS.get(plan, TIER_CREDITS["free"])

    c = _db()
    exist = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if exist:
        c.close()
        raise ValueError(f"用户名 '{username}' 已存在")

    uid = f"u-{uuid.uuid4().hex[:10]}"
    now_ts = _iso_now()
    pwd_hash, salt = hash_password(password)

    c.execute(
        "INSERT INTO users (id, username, email, password_hash, salt, role, plan, quota_used, quota_max, created_at, last_login, is_active, tenant_id) "
        "VALUES (?,?,?,?,?,?,?,0,?,?,?,1,'default')",
        (uid, username, email.strip(), pwd_hash, salt, role, plan, quota_max, now_ts, now_ts)
    )
    c.commit()
    c.close()
    return {"id": uid, "username": username, "email": email, "role": role, "plan": plan, "quota_max": quota_max}


def update_user_crud(user_id: str, email: str | None = None, role: str | None = None, plan: str | None = None, quota_max: int | None = None, is_active: int | None = None) -> dict:
    """更新用户资料、角色、套餐档位及额度"""
    c = _db()
    r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not r:
        c.close()
        raise ValueError("指定用户不存在")
    
    cur = dict(r)
    new_email = cur["email"] if email is None else email.strip()
    new_role = cur["role"] if role is None else role.strip()
    new_plan = cur["plan"] if plan is None else plan.strip()
    new_quota = cur["quota_max"] if quota_max is None else int(quota_max)
    new_active = cur["is_active"] if is_active is None else int(bool(is_active))

    c.execute(
        "UPDATE users SET email=?, role=?, plan=?, quota_max=?, is_active=? WHERE id=?",
        (new_email, new_role, new_plan, new_quota, new_active, user_id)
    )
    c.commit()
    c.close()
    return {
        "id": user_id, "username": cur["username"], "email": new_email,
        "role": new_role, "plan": new_plan, "quota_max": new_quota, "is_active": new_active
    }


def change_password_crud(user_id: str, new_password: str) -> bool:
    """修改指定用户的密码"""
    if len(new_password) < 6:
        raise ValueError("密码至少6个字符")
    c = _db()
    r = c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not r:
        c.close()
        raise ValueError("指定用户不存在")

    pwd_hash, salt = hash_password(new_password)
    c.execute("UPDATE users SET password_hash=?, salt=? WHERE id=?", (pwd_hash, salt, user_id))
    c.commit()
    c.close()
    return True


def delete_user_crud(user_id: str) -> bool:
    """删除指定用户（保护超级管理员不被删除）"""
    if user_id == "u-admin" or user_id == "admin":
        raise ValueError("系统默认超级管理员账号不可删除")
    c = _db()
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    c.execute("DELETE FROM user_api_keys WHERE user_id=?", (user_id,))
    c.commit()
    c.close()
    return True


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
    now_ts = _iso_now()

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
