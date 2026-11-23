# SPDX-License-Identifier: BUSL-1.1
"""v15.9.10 收口回归锁：风格单源 / 计费身份幂等 / domain 死代码下线。

背景：v15.9.8 操作审查的「全部进行修复」在 Wave 2 中断，留下三项收尾：
1) 三处配图风格下拉仍是硬编码，/api/drafts/image_styles 无人消费；
2) 先跑 test_v1599_web_fixes 再跑 test_r1_stopping 时，billing_adapter 对已存在
   的 u-admin 重复 INSERT，撞 UNIQUE constraint，r1 连挂 13 项（真实单机链路
   在管理员先由 core.auth 建好时同样会 500）；
3) domain/pipeline 的 ArticleQualityGate 全仓零调用，是第三套质量门禁死代码。
本文件为这三项落锁，防止再次漂移。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1) 配图风格单一真源
# ---------------------------------------------------------------------------

def test_image_style_module_is_wired_and_covers_three_dropdowns():
    """风格模块必须被首页加载，并覆盖三处下拉；不许再出现「文件写了没人用」。"""
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "/static/js/yimu-image-styles.js" in html, "风格单一真源模块未被首页加载"

    js = (ROOT / "web" / "static" / "js" / "yimu-image-styles.js").read_text(encoding="utf-8")
    assert "/api/drafts/image_styles" in js, "模块必须拉统一风格接口"
    for sel in ("inspire-image-style-sel", "oneshot-image-style-sel",
                "stage-image-style-sel"):
        assert sel in js, f"模块未覆盖下拉 {sel}"
        assert f'id="{sel}"' in html, f"模板缺少下拉 {sel}"
    # 失败回退必须是静默保留静态项，不许抛错阻断页面
    assert "catch" in js and "console.warn" in js, "接口失败必须静默回退"


def test_image_styles_endpoint_exposes_frontend_contract(monkeypatch):
    """接口字段形状必须稳定：key/name/icon，且不含已下线/隐藏的 chinese_ink。"""
    from web import admin as web_admin
    from web.routers import drafts as drafts_router

    monkeypatch.setattr(drafts_router._a, "guard", lambda request: {"id": "u-admin"})
    payload = drafts_router.get_image_styles(None)
    assert payload["ok"] is True
    styles = payload["styles"]
    assert isinstance(styles, list) and styles, "风格清单不得为空"
    keys = {s["key"] for s in styles}
    assert "chinese_ink" not in keys, "chinese_ink 已隐藏，不应出现在下拉"
    for s in styles:
        assert set(s.keys()) >= {"key", "name", "icon"}, f"字段缺失: {s}"
    # 前端三处下拉的关键选项必须来自后端真源
    for expected in ("cinematic_movie", "documentary", "anime_cinematic"):
        assert expected in keys, f"后端缺少前端使用的风格 {expected}"


# ---------------------------------------------------------------------------
# 2) 计费身份幂等（测试顺序污染根因）
# ---------------------------------------------------------------------------

def test_default_billing_user_is_idempotent_with_legacy_default_tenant(db_session):
    """core.auth 以 tenant_id='default' 建 u-admin 后，再取默认用户不得重复 INSERT。"""
    from studio import billing_adapter
    from studio.db_models import User, utcnow

    if db_session.query(User).filter(User.id == "u-admin").first() is None:
        db_session.add(User(
            id="u-admin", tenant_id="default", username="admin",
            email="", password_hash="!", salt="", role="admin",
            is_active=True, created_at=utcnow(),
        ))
        db_session.commit()

    tenant, user = billing_adapter.get_default_billing_user(db_session)
    assert user is not None and user.id == "u-admin"
    # 再取一次（真实链路会多次调用）仍必须是同一行，不得抛 UNIQUE 冲突
    tenant2, user2 = billing_adapter.get_default_billing_user(db_session)
    assert user2.id == "u-admin"
    assert tenant2.id == tenant.id


def test_check_and_deduct_canonicalizes_legacy_tenant(db_session):
    """调用方传历史 'default' 租户时，扣费必须归一到用户真实会员行。"""
    from studio import billing_adapter
    from studio.auth import ensure_default_tenant
    from studio.db_models import User, utcnow
    from studio.membership.service import ensure_membership

    tenant = ensure_default_tenant(db_session)
    uid = "u-v15910-deduct"
    if db_session.query(User).filter(User.id == uid).first() is None:
        db_session.add(User(
            id=uid, tenant_id=tenant.id, username=uid,
            email="", password_hash="!", salt="", role="user",
            is_active=True, created_at=utcnow(),
        ))
        db_session.commit()
    ms = ensure_membership(db_session, tenant.id, uid)
    before = int(ms.credits_total or 0) - int(ms.credits_used or 0)

    ok = billing_adapter.check_and_deduct(db_session, "default", uid, "rewrite", 1, "回归锁")
    assert ok is True, "余额充足时应扣费成功（历史租户标记必须被归一）"
    status = billing_adapter.get_billing_status(db_session, "default", uid)
    assert status["balance"] == before - 800, "rewrite 应恰好扣 800 点"


# ---------------------------------------------------------------------------
# 3) domain 死代码下线
# ---------------------------------------------------------------------------

def test_dead_article_quality_gate_is_removed():
    """零调用的第三套质量门禁不得复活；保留的归一函数必须仍可用。"""
    src = (ROOT / "domain" / "pipeline" / "article_pipeline.py").read_text(encoding="utf-8")
    assert "class ArticleQualityGate" not in src, "死代码 ArticleQualityGate 不得复活"

    from domain.pipeline import normalize_score_100
    assert normalize_score_100(7.3) == 73.0
    assert normalize_score_100(85.5) == 85.5
