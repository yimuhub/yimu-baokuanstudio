# SPDX-License-Identifier: BUSL-1.1
"""v15.9.11「竹溪曲」回归锁：受界阻塞池 + 卡密/邀请码单一创建路径。"""
from __future__ import annotations

import asyncio
import pathlib
import re

# ⭐ 环境变量必须在任何 studio import 之前就绪
import os

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-v15911")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")

import pytest  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_bounded_blocking_pool_wired_and_no_default_executor():
    """路由层不再直连默认线程池；受界池默认 16 且可配置。"""
    from core import blocking

    assert 2 <= blocking._POOL._max_workers <= 64
    assert blocking._worker_count() == 16

    offenders = []
    for path in sorted((ROOT / "web" / "routers").glob("*.py")):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if ".run_in_executor(None, " in line:
                offenders.append(f"{path.name}:{no}")
    assert offenders == [], f"仍有路由直连默认线程池: {offenders}"

    # 关机兜底是唯一保留例外（池已关闭时不能再提交任务）
    task_queue = (ROOT / "core" / "task_queue.py").read_text(encoding="utf-8")
    code_lines = [
        line for line in task_queue.splitlines()
        if ".run_in_executor(None, " in line and not line.lstrip().startswith("#")
    ]
    assert len(code_lines) == 1

    assert asyncio.run(blocking.run_blocking(lambda: 42)) == 42


def test_generate_cdkeys_delegates_to_create_invite(db_session, monkeypatch):
    """卡密生成必须走 membership.service.create_invite（不再裸 INSERT）。"""
    from types import SimpleNamespace

    from studio import billing_adapter
    from studio.auth import ensure_default_tenant
    import studio.membership.service as membership_service

    tenant = ensure_default_tenant(db_session)
    calls = []

    def fake_create_invite(db, tenant_obj, **kwargs):
        calls.append((tenant_obj.id, kwargs))
        return SimpleNamespace(code=kwargs["code"])

    monkeypatch.setattr(membership_service, "create_invite", fake_create_invite)
    codes = billing_adapter.generate_cdkeys(
        db_session, tenant.id, "tester", key_type="tokens", amount=500, count=3
    )
    assert len(codes) == 3
    assert all(code.startswith("YIMU-TOKEN-") for code in codes)
    assert len(calls) == 3
    assert all(call[0] == tenant.id for call in calls)
    assert all(call[1]["max_uses"] == 1 and call[1]["credits_grant"] == 500 for call in calls)


def test_all_invite_entrances_call_the_same_service():
    """三处入口（billing 卡密 / gateway UI / membership 路由）同源。"""
    service_src = (ROOT / "studio" / "membership" / "service.py").read_text(encoding="utf-8")
    assert "def create_invite(" in service_src
    assert "code_prefix" in service_src

    billing = (ROOT / "studio" / "billing_adapter.py").read_text(encoding="utf-8")
    assert "membership.service import create_invite" in billing
    assert "db.add(Invite(" not in billing

    gateway = (ROOT / "web" / "gateway_ui.py").read_text(encoding="utf-8")
    assert "studio.membership.service import" in gateway
    assert "create_invite(" in gateway

    router = (ROOT / "studio" / "membership_router.py").read_text(encoding="utf-8")
    assert "membership_service.create_invite" in router


def test_create_invite_keeps_explicit_card_code_and_audits(db_session):
    """显式 code 原样保留，且与邀请码走同一审计路径。"""
    from studio.auth import ensure_default_tenant
    from studio.db_models import AuditLog
    from studio.membership.service import create_invite

    tenant = ensure_default_tenant(db_session)
    code = "YIMU-TOKEN-ABCD1234-EF56"
    invite = create_invite(
        db_session, tenant, code=code, max_uses=1, credits_grant=800, actor="tester"
    )
    assert invite.code == code
    assert invite.tenant_id == tenant.id
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "invite.create", AuditLog.target == f"invite:{invite.id}")
        .first()
    )
    assert audit is not None
    assert audit.actor == "tester"
    assert audit.detail["code"] == code

    with pytest.raises(Exception):
        create_invite(db_session, tenant, code=code)
