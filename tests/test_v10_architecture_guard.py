# SPDX-License-Identifier: BUSL-1.1
"""V10.0.0 (鸿蒙始 · Primordial Dawn) 大厂级架构防腐化与全链路门禁测试集。"""
from __future__ import annotations

from pathlib import Path
import version

ROOT = Path(__file__).resolve().parent.parent


def test_v10_single_source_of_truth():
    """验证全站版本单一真源已步进至 10.0.1 / 10.0.0（鸿蒙始 · Primordial Dawn）。"""
    assert version.__version__ in ("10.0.1", "10.0.0")
    assert version.__codename__ == "鸿蒙始"
    assert version.__codename_en__ == "Primordial Dawn"

    idx = (ROOT / "web/templates/index.html").read_text(encoding="utf-8")
    assert any(v in idx for v in ("V10.0.1", "V10.0.0"))
    assert any(v in idx for v in ("10.0.1", "10.0.0"))
    assert "9.3.1" not in idx


def test_v10_clean_architecture_layers_exist():
    """验证大厂级四层架构（app / domain / infra / web）及抽离模板均已就位。"""
    required_paths = [
        "pyproject.toml",
        "app/deps.py",
        "app/schemas/billing.py",
        "app/routers/architecture.py",
        "domain/billing/service.py",
        "domain/pipeline/article_pipeline.py",
        "domain/pipeline/image_pipeline.py",
        "domain/prompts/registry.py",
        "domain/prompts/templates.yaml",
        "infra/logging.py",
        "infra/crawlers/popup_guard.py",
        "web/templates/pages/pricing.html",
        "web/templates/pages/users_admin.html",
        "web/templates/pages/audit_admin.html",
        "web/static/css/design-tokens.css",
        "web/static/locales/zh-CN.json",
        "web/static/locales/en-US.json",
    ]
    for rel in required_paths:
        assert (ROOT / rel).exists(), f"Missing V10 architecture module: {rel}"


def test_v10_domain_pipeline_and_popup_breaker():
    """验证统一 100 分制折算、公众号图片去重与浏览器弹窗单次熔断器。"""
    from domain.pipeline import normalize_score_100, dedupe_wechat_html_images
    from infra.crawlers.popup_guard import BrowserPopupCircuitBreaker

    # 10 分制自动折算为 100 分制
    assert normalize_score_100(7.3) == 73.0
    assert normalize_score_100(85.5) == 85.5

    # 公众号重复与相邻连贴插图自动去重
    dup_html = "<p>导语段落文字超过八个字以上</p><img src='/img/d1/cover.png'/><img src='/img/d1/sec-0.png'/><p>第二段正文内容超过八个字</p><img src='/img/d1/cover.png?v=2'/>"
    cleaned = dedupe_wechat_html_images(dup_html)
    assert cleaned.count("<img") == 1

    # 弹窗单次熔断器：只允许弹出 1 次，之后直接拦截
    cb = BrowserPopupCircuitBreaker()
    assert cb.allow_launch("xhs") is True
    assert cb.allow_launch("xhs") is False
    cb.trip("xhs")
    assert cb.allow_launch("douyin") is False
