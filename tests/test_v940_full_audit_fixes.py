# SPDX-License-Identifier: BUSL-1.1
"""V9.4.3 (回响曲 · Echo Melody) 全量审查修复与架构升级专项验收测试。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import version


def test_v940_version_truth():
    """验证 V9.4.3 版本单一真源与专属代号"""
    assert version.__version__ == "9.4.3"
    assert version.__codename__ == "浮光录"
    assert "Luminous Chronicles" in version.__slogan_en__


def test_v940_reverse_proxy_loopback_guard():
    """验证反向代理转发头包含公网 IP 时拒绝判定为本机 loopback 免密"""
    from web import admin as web_admin

    class _Client:
        host = "127.0.0.1"

    class _LocalReq:
        client = _Client()
        headers = {}

    class _ProxiedReqXFF:
        client = _Client()
        headers = {"x-forwarded-for": "203.0.113.50, 127.0.0.1"}

    class _ProxiedReqXRI:
        client = _Client()
        headers = {"x-real-ip": "198.51.100.22"}

    assert web_admin._is_loopback(_LocalReq()) is True
    assert web_admin._is_loopback(_ProxiedReqXFF()) is False
    assert web_admin._is_loopback(_ProxiedReqXRI()) is False


def test_v940_csrf_drive_by_and_cookie_reuse():
    """验证跨站无 Cookie 请求仍触发 CSRF 防护，且已有合法 csrf_token 时复用不覆盖"""
    from starlette.responses import Response
    from core.security_middleware import _csp_for_request, _needs_csrf, ensure_csrf_cookie

    class _URL:
        def __init__(self, scheme="http", path="/api/settings"):
            self.scheme = scheme
            self.path = path

    class _DriveByReq:
        url = _URL("http", "/api/settings")
        headers = {"origin": "https://evil.attacker.com", "host": "127.0.0.1:8790"}
        cookies = {}

    assert _needs_csrf(_DriveByReq()) is True

    # 验证已有合法 csrf_token 时复用，避免多标签页或预览 iframe 互相覆盖失效
    class _TabReq:
        cookies = {"csrf_token": "existing-valid-csrf-token-123456"}

    resp = Response("ok", media_type="text/html")
    tok = ensure_csrf_cookie(resp, request=_TabReq())
    assert tok == "existing-valid-csrf-token-123456"

    # 验证纯 HTTP 请求不强制注入 upgrade-insecure-requests，HTTPS 请求注入
    class _HttpReq:
        url = _URL("http", "/")
        headers = {}

    class _HttpsReq:
        url = _URL("https", "/")
        headers = {}

    assert "upgrade-insecure-requests" not in _csp_for_request(_HttpReq())
    assert "upgrade-insecure-requests" in _csp_for_request(_HttpsReq())


def test_v940_api_key_vault_v2_nonce_encryption():
    """验证 API Key Vault 采用带随机 Nonce 与 HMAC 校验的 v2 加密格式，同明文密文不同且防篡改"""
    from core import auth

    plain = "sk-deepseek-prod-secret-key-987654321"
    c1 = auth.encrypt_key(plain)
    c2 = auth.encrypt_key(plain)

    assert c1.startswith("v2$")
    assert c2.startswith("v2$")
    assert c1 != c2, "相同明文每次加密应使用独立随机 Nonce 产生不同密文"
    assert auth.decrypt_key(c1) == plain
    assert auth.decrypt_key(c2) == plain

    # 篡改最后一位 MAC 应校验失败返回空串
    tampered = c1[:-1] + ("0" if c1[-1] != "0" else "1")
    assert auth.decrypt_key(tampered) == ""


def test_v940_v6_v7_token_cross_compatibility(monkeypatch):
    """验证 core.auth 签发的会话令牌可被 studio.auth 无缝验签解析"""
    from core import auth as core_auth
    from studio import auth as studio_auth

    monkeypatch.setenv("YIMU_SECRET_KEY", studio_auth._SIGNING_SECRET)
    tok = core_auth.make_token({"user_id": "u-test940", "role": "user"})
    parsed = studio_auth.parse_session_token(tok)
    assert parsed is not None
    assert parsed["uid"] == "u-test940"
    assert parsed["tenant_id"] == "default"


def test_v940_byok_waives_platform_credits(tmp_path, monkeypatch):
    """验证用户配置并启用自备 API Key（BYOK）时，require_credits 免扣平台算力点数"""
    from core import auth as core_auth
    from core import db as core_db
    from web import admin as web_admin

    test_db = tmp_path / "byok_test.db"
    monkeypatch.setattr(core_db, "DB_PATH", test_db)
    monkeypatch.setattr(core_db, "DATA", tmp_path)
    monkeypatch.setattr(core_auth, "DB_PATH", test_db)

    reg = core_auth.register_user("byok_user", "password123")
    uid = reg["user"]["id"]
    core_auth.save_user_api_key(uid, "deepseek", "sk-user-own-key-123456789")

    token_ctx = web_admin._CURRENT_USER.set({"id": uid, "username": "byok_user", "role": "user"})
    try:
        assert web_admin.require_credits("rewrite", 1, "BYOK 测试") is True
    finally:
        web_admin._CURRENT_USER.reset(token_ctx)


def test_v940_6d_persona_injected_into_agents():
    """验证写作与导演 Agent 组装系统提示词时自动注入工作区 6 维数字画像"""
    from core import agents

    sys_prompt = agents.compose_system("write", "基础提示词")
    assert "6 维数字人格档案" in sys_prompt
    assert "账号定位" in sys_prompt
