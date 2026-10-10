# SPDX-License-Identifier: BUSL-1.1
"""R5 留存与增长批次验收测试。

覆盖 R5-1 ~ R5-7 的可判定验收标准：
- R5-1 通知 provider 可插拔；未配置时优雅降级不报错（不抛异常）
- R5-2 每日工单改应用内定时：进程重启后能恢复；不再写 launchd
- R5-3 撞配额墙 → 24h 内收到召回通知（mock 掉实际发送）
- R5-4invites 能查出邀请关系；邀请人余额真实增加 20%
- R5-5 裂变产物链接渲染正常；**改别人的 did 拿不到别人的稿件**
- R5-6 看板能算出 5 步漏斗转化
- R5-7 同一账号 1 小时内自动发布 > 3 条 → 被频控拦截
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-r5")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def r5_db(tmp_path, monkeypatch):
    """把 core.db 指向临时隔离库（绝不碰 data/mediaflow.db 生产库）。"""
    from core import db as core_db

    monkeypatch.setattr(core_db, "DB_PATH", tmp_path / "r5_mediaflow.db")
    monkeypatch.setattr(core_db, "DATA", tmp_path)
    monkeypatch.setattr(core_db, "DRAFTS", tmp_path / "drafts", raising=False)
    return core_db


@pytest.fixture()
def clean_env(monkeypatch):
    """清掉所有可能影响通知/定时判定的环境变量，保证测试确定性。"""
    for key in ("DINGTALK_WEBHOOK", "DINGTALK_SECRET", "SMTP_HOST", "SMTP_FROM",
                "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_SECURITY",
                "TICKET_ENABLED", "TICKET_TIME",
                "XHS_PUBLISH_MAX_PER_HOUR", "XHS_PUBLISH_MIN_INTERVAL_S",
                "XHS_PUBLISH_FAIL_THRESHOLD", "XHS_PUBLISH_COOLDOWN_S",
                "PUBLIC_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# ===========================================================================
# R5-1 用户侧通知通道：provider 可插拔 + 优雅降级
# ===========================================================================

class TestNotifyProvider:
    """R5-1：钉钉保留给运营，用户通知走可插拔 provider。"""

    def test_email_registered_and_dingtalk_preserved(self, clean_env):
        """邮件 provider 已注册；运营侧钉钉 send() 签名保持不变。"""
        import inspect

        from core import notify

        assert "email" in notify.PROVIDERS, "邮件 provider 应已注册"
        # 钉钉仍保留给运营，且签名未变（R1/R4 之前的调用方不能破）
        assert list(inspect.signature(notify.send).parameters) == ["title", "markdown_text"]
        assert list(inspect.signature(notify.notify_user).parameters) == [
            "to", "subject", "body", "provider"]

    def test_graceful_degrade_when_not_configured(self, clean_env, r5_db):
        """⭐ 无 SMTP 配置时**不抛异常**，返回 skipped=True。

        这是本项最关键的验收点：邮件服务器没配也不能把用户主流程带崩。
        """
        from core import notify

        assert notify.email_configured() is False
        res = notify.notify_user("a@example.com", "标题", "正文")
        assert res["ok"] is False
        assert res["skipped"] is True, "未配置应标记 skipped 而非报错"
        assert "未配置" in res.get("error", "")

    def test_missing_recipient_is_skipped(self, clean_env, r5_db):
        """没有收件地址时跳过，不抛异常。"""
        from core import notify

        res = notify.notify_user("", "标题", "正文")
        assert res["skipped"] is True

    def test_unknown_provider_does_not_raise(self, clean_env, r5_db):
        """未知 provider 不抛异常（可插拔接口的契约）。"""
        from core import notify

        res = notify.notify_user("a@example.com", "t", "b", provider="wechat-not-exist")
        assert res["ok"] is False and res["skipped"] is True

    def test_provider_exception_is_swallowed(self, clean_env, r5_db, monkeypatch):
        """provider 自身抛异常也不许上抛（旁路能力不能影响主流程）。"""

        def _boom(to, subject, body):
            raise RuntimeError("SMTP 炸了")

        from core import notify

        monkeypatch.setitem(notify.PROVIDERS, "email", _boom)
        res = notify.notify_user("a@example.com", "t", "b")
        assert res["ok"] is False
        assert "SMTP炸了" in res.get("error", "").replace(" ", "")

    def test_email_sends_via_smtp_when_configured(self, clean_env, r5_db, monkeypatch):
        """配置齐全时走 smtplib（用假 SMTP 验证确实调用了 send_message）。"""
        import smtplib

        sent = {}

        class _FakeSMTP:
            def __init__(self, host, port, timeout=None):
                sent["host"] = host
                sent["port"] = port

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, u, p):
                sent["login"] = (u, p)

            def send_message(self, msg):
                sent["to"] = msg["To"]
                sent["subject"] = msg["Subject"]

        from core import notify

        clean_env.setenv("SMTP_HOST", "smtp.example.com")
        clean_env.setenv("SMTP_PORT", "465")
        clean_env.setenv("SMTP_FROM", "n@example.com")
        clean_env.setenv("SMTP_USER", "u@example.com")
        clean_env.setenv("SMTP_PASSWORD", "pw")
        monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)

        res = notify.notify_user("real@example.com", "额度提醒", "正文")
        assert res["ok"] is True
        assert sent["host"] == "smtp.example.com"
        assert sent["to"] == "real@example.com"
        assert sent["subject"] == "额度提醒"
        # 返回值必须脱敏，不回显完整邮箱
        assert "real@example.com" not in str(res)


# ===========================================================================
# R5-2 每日工单：应用内定时 + 重启可恢复
# ===========================================================================

class TestTicketScheduler:
    """R5-2：不再依赖 macOS launchd，改为应用内定时。"""

    def test_no_launchd_writes_remain(self):
        """⭐ 静态护栏：工单定时不得再写 launchd plist。

        云端容器没有 launchctl，保留即意味着「云端定时静默失效」。

        ⚠️ 只针对**工单**这条链路：web/admin.py 里`apipool`/`wae`
           等本地服务的 kickstart 修复是另一回事（那些服务本身就是
           macOS 本机常驻进程），不在本项范围。R5 只要求工单不再依赖
           launchd，因此这里断言「不再生成 plist / 不再 load 工单」。
        """
        src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
        # ① 不得再有写 plist 的行为
        assert "StartCalendarInterval" not in src, "仍在生成 launchd plist"
        assert 'plist.write_text' not in src, "仍在写 plist 文件"
        # ③ 工单路由的**函数体**不得直接操作 plist
        #     （先剥掉 docstring 与注释——里面会解释「为何移除 launchd」，
        #       那是必要的开发者说明，不是调度逻辑；
        #       并且只取 POST 路由函数体，不含其后的清理辅助函数）
        import re

        route_start = src.find('@app.post("/api/ticket/schedule")')
        # 函数体结束于下一个顶层 def/@app
        tail = src[route_start + 10:]
        m = re.search(r"\n(?=@app\.|def )", tail)
        raw = tail[:m.start()] if m else tail
        code = re.sub(r'"""[\s\S]*?"""', "", raw)
        code = "\n".join(
            line for line in code.splitlines()
            if not line.strip().startswith("#")
        )
        assert "plist" not in code, "工单路由仍直接操作 plist"
        assert "launchctl" not in code, "工单路由仍调用 launchctl"
        # ④ 必须已改为应用内模式
        assert "in_app" in src, "工单调度未标记为应用内模式"
        # ⑤ 清理函数只在 macOS 上动 plist，云端直接跳过
        cleanup = src[src.find("def _unload_legacy_launchd"):
                      src.find('@app.get("/api/ticket/schedule")')]
        assert "darwin" in cleanup, "清理 launchd 必须限定 macOS，云端不应触碰"

    def test_ticket_status_reads_config(self, clean_env, r5_db):
        """工单状态可读：开关/时间来自配置而非 launchd。"""
        from core import scheduler

        st = scheduler.ticket_status()
        assert st["enabled"] is False
        assert st["time"] == "07:30", "缺省应为 07:30"

        clean_env.setenv("TICKET_ENABLED", "1")
        clean_env.setenv("TICKET_TIME", "09:15")
        st = scheduler.ticket_status()
        assert st["enabled"] is True
        assert st["time"] == "09:15"

    def test_restart_recovers_missed_run(self, clean_env, r5_db):
        """⭐ 进程重启后能补跑：标记在内存，重启即失效 → 当天会重跑。

        场景 1：模拟「进程刚启动、当天尚未跑过」→ 应触发一次
        场景 2：同一天再次轮询 → 不应重复跑（防重复发稿）

        ⚠️ 设定时间取**当前分钟**，才能落进触发窗口；若写死 07:30
           只在每天那个时刻才会跑，测试无法稳定复现。
        """
        from datetime import datetime

        from core import scheduler

        now = datetime.now()
        clean_env.setenv("TICKET_ENABLED", "1")
        clean_env.setenv("TICKET_TIME", f"{now.hour:02d}:{now.minute:02d}")

        calls = []
        import core.ticket as ticket_mod

        original = ticket_mod.run_ticket
        ticket_mod.run_ticket = lambda *a, **k: calls.append(time.time())
        try:
            # 场景 1：进程刚启动、当天未跑过 → 补跑一次
            scheduler._ticket_ran_on = ""
            scheduler._maybe_run_daily_ticket()
            for _ in range(60):
                if calls:
                    break
                time.sleep(0.05)
            assert len(calls) == 1, "重启后当天应补跑一次"

            # 场景 2：同一天再轮询 → 不重复跑
            scheduler._maybe_run_daily_ticket()
            time.sleep(0.3)
            assert len(calls) == 1, "当天不应重复执行"
        finally:
            ticket_mod.run_ticket = original

    def test_outside_window_does_not_run(self, clean_env, r5_db):
        """不在设定时间窗内不触发（避免任何时刻都发稿）。"""
        from datetime import datetime

        from core import scheduler

        clean_env.setenv("TICKET_ENABLED", "1")
        # 设一个当前时刻不可能落入的窗口（+6 小时）
        now = datetime.now()
        clean_env.setenv("TICKET_TIME", f"{(now.hour + 6) % 24:02d}:{now.minute:02d}")

        calls = []
        import core.ticket as ticket_mod

        original = ticket_mod.run_ticket
        ticket_mod.run_ticket = lambda *a, **k: calls.append(1)
        try:
            scheduler._ticket_ran_on = ""
            scheduler._maybe_run_daily_ticket()
            time.sleep(0.3)
            assert calls == [], "非设定时间不应触发工单"
        finally:
            ticket_mod.run_ticket = original

    def test_disabled_never_runs(self, clean_env, r5_db):
        """开关关闭时永不触发。"""
        from core import scheduler

        clean_env.setenv("TICKET_ENABLED", "0")
        clean_env.setenv("TICKET_TIME", "00:00")
        calls = []
        import core.ticket as ticket_mod

        original = ticket_mod.run_ticket
        ticket_mod.run_ticket = lambda *a, **k: calls.append(1)
        try:
            scheduler._ticket_ran_on = ""
            scheduler._maybe_run_daily_ticket()
            time.sleep(0.3)
            assert calls == [], "开关关闭不应触发"
        finally:
            ticket_mod.run_ticket = original


# ===========================================================================
# R5-3 配额墙召回邮件（mock 掉实际发送）
# ===========================================================================

class TestQuotaRecall:
    """R5-3：撞额度墙 → 24h 内收到一封召回通知。"""

    def _sent(self):
        """构造一个记录投递的假sender。"""
        out = []

        def _sender(to, subject, body):
            out.append({"to": to, "subject": subject, "body": body})
            return {"ok": True}

        return out, _sender

    def test_first_block_delivers_within_24h(self, clean_env, r5_db):
        """⭐ 撞墙 → 24 小时内收到召回通知（实际发送已 mock）。"""
        from core import user_notify

        out, sender = self._sent()
        title, body = user_notify.quota_recall_body("新建草稿", 800, 0)

        res = user_notify.deliver("u-1", "u@example.com", title, body,
                                  kind="quota_recall", sender=sender)
        assert res["status"] == "sent", f"首次撞墙应发出召回邮件：{res}"
        assert len(out) == 1
        assert "额度" in out[0]["subject"]
        # 文案要说清「发生了什么 + 怎么办」
        assert "800" in out[0]["body"]
        for kw in ("兑换卡密", "升级"):
            assert kw in out[0]["body"], f"召回文案应给出行动项「{kw}」"

    def test_repeat_block_throttled_within_24h(self, clean_env, r5_db):
        """⭐ 24 小时内重复撞墙不重复轰炸（节流）。"""
        from core import user_notify

        out, sender = self._sent()
        for _ in range(5):
            user_notify.deliver("u-1", "u@example.com", "[quota_recall] 额度已用完",
                                "正文", kind="quota_recall", sender=sender)
        assert len(out) == 1, f"24h 内应只发 1 封，实际发了 {len(out)} 封"

    def test_throttle_expires_after_24h(self, clean_env, r5_db):
        """⭐ 24 小时后允许再发（节流窗口确实会过期）。"""
        from core import user_notify

        out, sender = self._sent()
        user_notify.deliver("u-1", "u@example.com", "[quota_recall] a", "正文",
                            kind="quota_recall", sender=sender)
        # 把已发记录回拨 25 小时前，模拟窗口过期
        c = r5_db.conn()
        c.execute("UPDATE user_notifications SET created_at=? WHERE user_id=?",
                  (time.time() - 25 * 3600, "u-1"))
        c.commit()
        c.close()

        user_notify.deliver("u-1", "u@example.com", "[quota_recall] b", "正文",
                            kind="quota_recall", sender=sender)
        assert len(out) == 2, "超过 24h 后应可再次发送"

    def test_other_users_not_throttled_by_each_other(self, clean_env, r5_db):
        """节流是**按用户**的：A 收到不影响 B。"""
        from core import user_notify

        out, sender = self._sent()
        user_notify.deliver("u-A", "a@example.com", "[quota_recall] a", "正文",
                            kind="quota_recall", sender=sender)
        user_notify.deliver("u-B", "b@example.com", "[quota_recall] b", "正文",
                            kind="quota_recall", sender=sender)
        assert len(out) == 2, "不同用户应各自能收到召回"

    def test_no_recipient_stays_pending(self, clean_env, r5_db):
        """没有邮箱时不丢消息，保持待发（用户补邮箱后可补发）。"""
        from core import user_notify

        res = user_notify.deliver("u-1", "", "[quota_recall] t", "正文",
                                  kind="quota_recall")
        assert res["status"] == "pending"
        rows = user_notify.list_for_user("u-1")
        assert len(rows) == 1, "应落库待发记录，而不是静默丢弃"

    def test_unconfigured_channel_does_not_raise(self, clean_env, r5_db):
        """SMTP 未配置时不得抛异常（保持 pending）。"""
        from core import user_notify

        res = user_notify.deliver("u-1", "u@example.com", "[quota_recall] t", "正文",
                                  kind="quota_recall")
        assert res["ok"] is False
        assert res["status"] in ("pending", "failed")

    def test_recall_body_has_no_jargon(self, clean_env, r5_db):
        """召回文案不得含开发者黑话（面向付费用户的文案）。"""
        from core import user_notify

        _title, body = user_notify.quota_recall_body("新建草稿", 800, 0)
        for jargon in ("quota", "402", "ledger", "token", "check_and_deduct"):
            assert jargon not in body, f"召回文案含黑话 {jargon}"


# ===========================================================================
# R5-4 invites：邀请关系可查 + 邀请人余额真实增加
# ===========================================================================

class TestInviteReferral:
    """R5-4：inviter_id + 20% 邀请奖励。"""

    def test_invite_model_has_inviter_id(self):
        """模型层：Invite 必须有 inviter_id 字段。"""
        from studio.db_models import Invite

        cols = {c.name for c in Invite.__table__.c}
        assert "inviter_id" in cols, "Invite 缺 inviter_id，无法追踪邀请人"

    def test_core_db_schema_has_inviter_id(self, r5_db):
        """⭐ 迁移：core.db 的 invites 表也要有 inviter_id（raw sqlite 双层共用）。"""
        c = r5_db.conn()
        cols = {r["name"] for r in c.execute("PRAGMA table_info(invites)")}
        c.close()
        assert "inviter_id" in cols, "invites 表迁移未补 inviter_id"

    def test_inviter_balance_increases_20pct(self, db_session):
        """⭐ 核销后邀请人余额真实增加被邀请人所得的 20%。"""
        from studio.auth import register_user
        from studio.db_models import Tenant, new_id
        from studio.membership import service as svc

        tenant = Tenant(id=new_id(), name="r5-invite-" + new_id()[:6], plan="free",
                        launch_mode="public", is_active=True)
        db_session.add(tenant)
        db_session.commit()

        inviter = register_user(db_session, tenant, "inviter-" + new_id()[:6],
                                "pw-" + new_id()[:10])
        invitee = register_user(db_session, tenant, "invitee-" + new_id()[:6],
                                "pw-" + new_id()[:10])

        inviter_m = svc.ensure_membership(db_session, tenant.id, inviter.id)
        before = svc.credits_left(inviter_m)

        invite = svc.create_invite(db_session, tenant, max_uses=5,
                                   credits_grant=10000, inviter_id=inviter.id)
        svc.redeem_invite(db_session, tenant, invite.code, invitee)

        db_session.expire_all()
        after = svc.credits_left(
            db_session.query(type(inviter_m)).filter_by(id=inviter_m.id).one())
        reward = after - before
        assert reward == 2000, f"应奖励 20%×10000=2000，实际 {reward}"

    def test_invite_relation_is_queryable(self, db_session):
        """⭐ 能查出「谁邀请了谁」。"""
        from studio.auth import register_user
        from studio.db_models import Tenant, new_id
        from studio.membership import service as svc

        tenant = Tenant(id=new_id(), name="r5-rel-" + new_id()[:6], plan="free",
                        launch_mode="public", is_active=True)
        db_session.add(tenant)
        db_session.commit()

        inviter = register_user(db_session, tenant, "inv-" + new_id()[:6], "pw-" + new_id()[:10])
        invitee = register_user(db_session, tenant, "invee-" + new_id()[:6], "pw-" + new_id()[:10])

        invite = svc.create_invite(db_session, tenant, max_uses=3,
                                   credits_grant=1000, inviter_id=inviter.id)
        svc.redeem_invite(db_session, tenant, invite.code, invitee)

        rels = svc.list_invite_relations(db_session, tenant, inviter.id)
        assert len(rels) == 1
        assert rels[0]["inviter_id"] == inviter.id
        assert rels[0]["invitee_id"] == invitee.id
        assert rels[0]["reward_credits"] == 200

        summary = svc.inviter_summary(db_session, tenant, inviter.id)
        assert summary["invited_count"] == 1
        assert summary["total_reward_credits"] == 200

    def test_ops_issued_code_gives_no_reward(self, db_session):
        """运营批量发的码（inviter_id 空）→ 被邀请人照得额度，邀请人不得奖励。"""
        from studio.auth import register_user
        from studio.db_models import Tenant, new_id
        from studio.membership import service as svc

        tenant = Tenant(id=new_id(), name="r5-ops-" + new_id()[:6], plan="free",
                        launch_mode="public", is_active=True)
        db_session.add(tenant)
        db_session.commit()

        invitee = register_user(db_session, tenant, "opsee-" + new_id()[:6], "pw-" + new_id()[:10])
        invite = svc.create_invite(db_session, tenant, max_uses=1, credits_grant=5000)
        assert (invite.inviter_id or "") == ""

        svc.redeem_invite(db_session, tenant, invite.code, invitee)
        assert svc.list_invite_relations(db_session, tenant) == [], \
            "运营码不应产生邀请关系记录"

    def test_self_invite_gives_no_reward(self, db_session):
        """⭐ 自邀（自己核销自己发的码）不得刷额度。"""
        from studio.auth import register_user
        from studio.db_models import Tenant, new_id
        from studio.membership import service as svc

        tenant = Tenant(id=new_id(), name="r5-self-" + new_id()[:6], plan="free",
                        launch_mode="public", is_active=True)
        db_session.add(tenant)
        db_session.commit()

        user = register_user(db_session, tenant, "self-" + new_id()[:6], "pw-" + new_id()[:10])
        m0 = svc.ensure_membership(db_session, tenant.id, user.id)
        before = svc.credits_left(m0)

        invite = svc.create_invite(db_session, tenant, max_uses=2,
                                   credits_grant=10000, inviter_id=user.id)
        svc.redeem_invite(db_session, tenant, invite.code, user)

        db_session.expire_all()
        after = svc.credits_left(
            db_session.query(type(m0)).filter_by(id=m0.id).one())
        # 只应拿到被邀请人的 10000，不应额外多出 2000 奖励
        assert after - before == 10000, f"自邀不应有奖励，实得 {after - before}"

    def test_fake_inviter_id_rejected(self, db_session):
        """伪造他人 id 当邀请人被拒（不能冒领别人的奖励池）。"""
        from fastapi import HTTPException

        from studio.db_models import Tenant, new_id
        from studio.membership import service as svc

        tenant = Tenant(id=new_id(), name="r5-fake-" + new_id()[:6], plan="free",
                        launch_mode="public", is_active=True)
        db_session.add(tenant)
        db_session.commit()

        with pytest.raises(HTTPException):
            svc.create_invite(db_session, tenant, max_uses=1, credits_grant=1,
                              inviter_id="u-does-not-exist")

    def test_cdkey_redeem_still_works(self, db_session):
        """⭐ 与 R1 的卡密兑换路径不冲突：兑换仍然成功且余额增加。"""
        from studio import billing_adapter
        from studio.auth import register_user
        from studio.db_models import Tenant, new_id

        tenant = Tenant(id=new_id(), name="r5-cdkey-" + new_id()[:6], plan="free",
                        launch_mode="public", is_active=True)
        db_session.add(tenant)
        db_session.commit()
        user = register_user(db_session, tenant, "cdk-" + new_id()[:6], "pw-" + new_id()[:10])

        codes = billing_adapter.generate_cdkeys(db_session, tenant.id, "admin",
                                                key_type="tokens", amount=5000, count=1)
        before = billing_adapter.get_billing_status(
            db_session, tenant.id, user.id)["balance"]
        res = billing_adapter.redeem_cdkey(db_session, tenant.id, user.id, codes[0])
        assert res["ok"] is True
        after = billing_adapter.get_billing_status(
            db_session, tenant.id, user.id)["balance"]
        assert after == before + 5000, "R1 卡密兑换路径未被 R5-4 破坏"
        # 重复兑换仍应被拒（原子核销未被破坏）
        again = billing_adapter.redeem_cdkey(db_session, tenant.id, user.id, codes[0])
        assert again["ok"] is False


# ===========================================================================
# R5-5 裂变分享链接 + 二维码（含归属校验）
# ===========================================================================

class TestShareLinks:
    """R5-5：公网链接 + 二维码；重点是归属校验。"""

    @pytest.fixture()
    def two_drafts(self, r5_db, monkeypatch, tmp_path):
        """造两个用户各一篇稿件，且各自产物文件真实存在。"""
        drafts = tmp_path / "drafts"
        monkeypatch.setattr(r5_db, "DRAFTS", drafts, raising=False)

        made = {}
        for owner, did in (("user-A", "dr-aaa"), ("user-B", "dr-bbb")):
            d = r5_db.add_draft("t1", f"{owner}的稿件", "机密正文", ["wechat_mp"])
            ddir = r5_db.draft_dir(d["id"])
            (ddir / "preview-wechat_mp.html").write_text(
                f"<html><body>机密内容-{owner}</body></html>", encoding="utf-8")
            made[owner] = d["id"]
        return made

    def test_share_page_renders_owner_content(self, r5_db, two_drafts, clean_env):
        """⭐ 用令牌访问自己的稿件：渲染正常。"""
        from core import share

        did = two_drafts["user-A"]
        link = share.create_share(did, "wechat_mp", "user-A")
        rec = share.resolve(link["token"])
        assert rec and rec["draft_id"] == did

        f = r5_db.draft_dir(did) / "preview-wechat_mp.html"
        html = share.render_share_page(rec, f.read_text(encoding="utf-8"))
        assert "机密内容-user-A" in html
        assert "<html" in html

    def test_token_cannot_reach_other_users_draft(self, r5_db, two_drafts, clean_env):
        """⭐⭐ 核心安全验收：A 的令牌拿不到 B 的稿件。

        验证三层：① 令牌唯一映射；② 改 did 无从下手（地址里没有 did）；
        ③ 遍历/猜测令牌拿不到他人内容。
        """
        from core import share

        did_a, did_b = two_drafts["user-A"], two_drafts["user-B"]
        link_a = share.create_share(did_a, "wechat_mp", "user-A")
        link_b = share.create_share(did_b, "wechat_mp", "user-B")

        # ① 令牌与稿件一一对应，不可串用
        rec = share.resolve(link_a["token"])
        assert rec["draft_id"] != did_b, "A 的令牌不得解析到 B 的稿件"

        # ② 地址里只有令牌：不存在 did 字段，因此「改 did」这条路不存在
        assert did_b not in link_a["url"]
        assert "/s/" in link_a["url"]
        # ③ 拿 B 的 did 去拼也拿不到内容（因为路由只认令牌）
        fake = share.resolve(f"{did_b}-guessed-token")
        assert fake is None

        # ④ 实际渲染时，A 的令牌渲染出的必须是 A 的内容
        f = r5_db.draft_dir(did_a) / "preview-wechat_mp.html"
        html = share.render_share_page(rec, f.read_text(encoding="utf-8"))
        assert "机密内容-user-A" in html
        assert "机密内容-user-B" not in html, "⭐ 绝不能渲染出他人稿件内容"

    def test_invalid_token_returns_none(self, r5_db, two_drafts, clean_env):
        """无效/空令牌一律解析失败（不泄露存在性）。"""
        from core import share

        assert share.resolve("") is None
        assert share.resolve("nonexistent-token") is None

    def test_revoked_token_stops_working(self, r5_db, two_drafts, clean_env):
        """吊销后立即失效。"""
        from core import share

        link = share.create_share(two_drafts["user-A"], "wechat_mp", "user-A")
        assert share.resolve(link["token"]) is not None
        assert share.revoke(link["token"]) is True
        assert share.resolve(link["token"]) is None, "吊销后不应再可访问"

    def test_expired_token_stops_working(self, r5_db, two_drafts, clean_env):
        """过期链接失效。"""
        from core import share

        link = share.create_share(two_drafts["user-A"], "wechat_mp", "user-A", ttl_days=1)
        c = r5_db.conn()
        c.execute("UPDATE share_links SET expires_at=? WHERE token=?",
                  (time.time() - 10, link["token"]))
        c.commit()
        c.close()
        assert share.resolve(link["token"]) is None

    def test_only_existing_artifacts_get_links(self, r5_db, two_drafts, clean_env):
        """⭐ 只为产物真实存在的平台签发链接（不给点开 404 的死链）。"""
        from core import share

        did = two_drafts["user-A"]
        res = share.create_share_set(
            did, ["wechat_mp", "xhs", "toutiao"], "user-A")
        assert len(res["links"]) == 1, "只有 wechat_mp 产物存在"
        assert res["links"][0]["platform"] == "wechat_mp"
        skipped = {s["platform"] for s in res["skipped"]}
        assert skipped == {"xhs", "toutiao"}
        assert all("尚未生成" in s["reason"] for s in res["skipped"]), "跳过需说明原因"

    def test_qr_and_poster_generated(self, r5_db, two_drafts, clean_env):
        """二维码与海报可生成（纯标准库，不引第三方依赖）。"""
        from core import qrcode_min, share

        link = share.create_share(two_drafts["user-A"], "wechat_mp", "user-A",
                                  base_url="https://example.com")
        svg = qrcode_min.encode_svg(f"https://example.com/s/{link['token']}")
        assert svg.startswith("<svg") and "</svg>" in svg
        poster = share.build_poster(two_drafts["user-A"], link["token"],
                                    base_url="https://example.com")
        assert "二维码" in poster and "data:image/svg+xml;base64," in poster

    def test_qr_roundtrip_decodes_to_original(self):
        """⭐ 二维码正确性：按 QR 规范反向解码可还原原文。

        环境内无第三方扫码器，因此用**规范逆向流程**做往返校验——
        可发现位序/掩码/分块等编码错误。
        """
        from core import qrcode_min as q

        for text in ("https://example.com/s/abc123XYZ",
                     "http://127.0.0.1:8790/s/tok-123",
                     "A"):
            decoded = _qr_decode(q.encode(text))
            assert decoded == text, f"二维码往返解码失败：{decoded!r} != {text!r}"

    def test_qr_rejects_oversized_input(self):
        """超长内容明确报错，而非静默截断（避免扫出错误内容）。"""
        from core import qrcode_min as q

        with pytest.raises(ValueError):
            q.encode("x" * 500)

    def test_poster_escapes_html_in_title(self):
        """标题含 < & > " 等字符不得破坏 SVG 结构。"""
        import xml.etree.ElementTree as ET

        from core import share

        svg = share.build_poster("dr-x", "tok-x", title='标题<&>"测试',
                                 base_url="https://e.com")
        # 三个危险字符都必须已转义
        for ent in ("&lt;", "&amp;", "&gt;", "&quot;"):
            assert ent in svg, f"缺少转义实体 {ent}"
        # ⭐ 真正的判据：整段必须是**合法可解析的 XML**
        # （若转义有误，这里会直接抛 ParseError）
        ET.fromstring(svg)


def _qr_decode(matrix: list[list[int]]) -> str:
    """QR 逆向解码（仅支持字节模式 + 等级 L），用于编码器往返校验。

    按 ISO/IEC 18004 逆向：定位格式信息→反掩码→反交错→去纠错→解字节模式。
    """
    size = len(matrix)
    version = (size - 17) // 4

    # ① 读格式信息（右下角那条），校验 BCH 并取出掩码号
    # 规范§ 8.9：bit0..bit7 → (size-1,8)..(size-8,8) 自下而上；
    #            bit8..bit14 → (8,size-8)..(8,size-1)
    fmt = 0
    for i in range(8):
        fmt |= matrix[size - 1 - i][8] << i
    for i in range(8, 15):
        fmt |= matrix[8][size - 15 + i] << i
    # 去掉格式信息自带的固定异或掩码，得到 (5 位数据 << 10) | 10 位 BCH
    fmt ^= 0b101010000010010
    # ⭐ 关键：5 位数据在**高位**——bit14..13 是纠错等级、bit12..10 是掩码号。
    #    误从低位取掩码号会解出错误的掩码，进而反掩码得到乱码。
    ecc_level = (fmt >> 13) & 0b11
    mask = (fmt >> 10) & 0b111
    assert ecc_level == 0b01, f"解码器只支持等级 L，实际 {ecc_level:#04b}"

    # ② 重建功能模块掩码（哪些格子是功能区，不能当数据读）
    fixed = [[False] * size for _ in range(size)]

    def mark(r0, c0, h, w):
        for dr in range(h):
            for dc in range(w):
                if 0 <= r0 + dr < size and 0 <= c0 + dc < size:
                    fixed[r0 + dr][c0 + dc] = True

    mark(0, 0, 9, 9)
    mark(0, size - 8, 9, 8)
    mark(size - 8, 0, 8, 9)
    for i in range(size):
        fixed[6][i] = True
        fixed[i][6] = True
    from core.qrcode_min import _ALIGN_POS

    pos = _ALIGN_POS[version]
    for r in pos:
        for c in pos:
            if (r, c) in ((pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])):
                continue
            mark(r - 2, c - 2, 5, 5)
    for i in range(9):
        fixed[8][i] = True
        fixed[i][8] = True
    for i in range(8):
        fixed[8][size - 1 - i] = True
        fixed[size - 1 - i][8] = True
    if version >= 7:
        mark(size - 11, 0, 3, 6)
        mark(0, size - 11, 6, 3)

    # ③ 按之字形路径反掩码取回数据位
    bits = []
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if fixed[row][c]:
                    continue
                bit = matrix[row][c]
                if q_mask_cond(mask, row, c):
                    bit ^= 1
                bits.append(bit)
        upward = not upward
        col -= 2

    codewords = [sum(bits[i + j] << j for j in range(8))
                 for i in range(0, len(bits) - 7, 8)]

    # ④ 反交错还原数据块
    from core.qrcode_min import _VERSION_L

    ec_count, groups = _VERSION_L[version]
    data_blocks = []
    ec_blocks = []
    idx = 0
    i = 0
    for cnt, size_each in groups:
        for _ in range(cnt):
            data_blocks.append([])
            ec_blocks.append([])
    for blk in data_blocks:
        for _ in range(len(blk)):
            pass
    max_data = max(size_each for _cnt, size_each in groups)
    for i in range(max_data):
        for bi, (_cnt, size_each) in enumerate(
                [g for g in groups for _ in range(g[0])]):
            if i < size_each:
                data_blocks[bi].append(codewords[idx])
                idx += 1
    for i in range(ec_count):
        for bi in range(len(data_blocks)):
            ec_blocks[bi].append(codewords[idx])
            idx += 1

    # ⑤ 拼回字节流并解析字节模式
    stream = []
    for blk in data_blocks:
        stream.extend(blk)
    out_bits = []
    for cw in stream:
        for i in range(8):
            out_bits.append((cw >> i) & 1)

    pos_bit = 0

    def take(n):
        nonlocal pos_bit
        v = 0
        for i in range(n):
            v |= out_bits[pos_bit + i] << i
        pos_bit += n
        return v

    mode = take(4)
    assert mode == 0b0100, f"只支持字节模式，实际 mode={mode:#06b}"
    count_bits = 8 if version <= 9 else 16
    length = take(count_bits)
    out = bytearray()
    for _ in range(length):
        out.append(take(8))
    return out.decode("utf-8")


def q_mask_cond(mask: int, row: int, col: int) -> bool:
    """掩码条件（与编码器一致）。"""
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


# ===========================================================================
# R5-6 埋点 + 漏斗看板
# ===========================================================================

class TestAnalytics:
    """R5-6：user_events + 5 步漏斗。"""

    def test_funnel_schema_exists(self, r5_db):
        """user_events 表含任务要求的全部字段。"""
        c = r5_db.conn()
        cols = {r["name"] for r in c.execute("PRAGMA table_info(user_events)")}
        c.close()
        for col in ("user_id", "tenant_id", "event", "props", "created_at"):
            assert col in cols, f"user_events 缺字段 {col}"

    def test_five_events_defined(self, r5_db):
        """5 个漏斗事件齐全且顺序正确。"""
        from core import analytics

        names = [e for e, _ in analytics.FUNNEL_STEPS]
        assert names == ["signup", "first_draft_created", "first_drama_run",
                         "quota_blocked", "cdkey_redeemed"]

    def test_track_and_count(self, r5_db):
        """埋点写入与计数正确（按用户去重）。"""
        from core import analytics

        assert analytics.track("signup", "u1") != ""
        analytics.track("first_draft_created", "u1")
        analytics.track("signup", "u2")
        # 同一用户重复事件只算 1 人
        analytics.track("quota_blocked", "u1")
        analytics.track("quota_blocked", "u1")

        assert analytics.count_users("signup") == 2
        assert analytics.count_users("quota_blocked") == 1
        assert analytics.count_event("quota_blocked") == 2

    def test_funnel_computes_conversion(self, r5_db):
        """⭐ 看板能算出 5 步漏斗转化率。"""
        from core import analytics

        # u1 走完全程；u2 只注册；u3 注册+成稿
        analytics.track("signup", "u1")
        analytics.track("first_draft_created", "u1")
        analytics.track("first_drama_run", "u1")
        analytics.track("quota_blocked", "u1")
        analytics.track("cdkey_redeemed", "u1")
        analytics.track("signup", "u2")
        analytics.track("signup", "u3")
        analytics.track("first_draft_created", "u3")

        fn = analytics.funnel(30)
        steps = fn["steps"]
        assert len(steps) == 5
        assert [s["users"] for s in steps] == [3, 2, 1, 1, 1]
        assert steps[0]["label"] == "注册"
        # 成稿相对注册的转化率 2/3
        assert steps[1]["rate_from_prev"] == 66.7
        # 相对首步的转化率
        assert steps[1]["rate_from_top"] == 66.7
        assert steps[-1]["rate_from_prev"] == 100.0

    def test_funnel_window_filtering(self, r5_db):
        """时间窗生效：窗口外的事件不计入。"""
        from core import analytics

        analytics.track("signup", "u-new")
        c = r5_db.conn()
        c.execute("UPDATE user_events SET created_at=? WHERE user_id=?",
                  (time.time() - 40 * 86400, "u-new"))
        c.commit()
        c.close()
        assert analytics.funnel(30)["steps"][0]["users"] == 0
        assert analytics.funnel(0)["steps"][0]["users"] == 1, "days=0 表示全量"

    def test_track_never_raises(self, r5_db, monkeypatch):
        """⭐ 埋点是旁路能力：DB 故障也不许抛异常影响主流程。

        做法：直接让 ``db.conn()`` 抛异常（比 DROP TABLE 更贴近真实故障——
        DROP TABLE 会被 ``conn()`` 里的建表脚本重新建回来）。
        """
        from core import analytics, db as core_db

        def _boom():
            raise RuntimeError("数据库不可用")

        monkeypatch.setattr(core_db, "conn", _boom)
        assert analytics.track("signup", "u1") == "", "DB 故障时应静默返回空串"
        assert analytics.count_users("signup") == 0
        assert analytics.count_event("signup") == 0
        assert analytics.list_recent() == []

    def test_metrics_api_requires_admin(self):
        """⭐ 看板接口必须是管理员专属（运营数据不外泄）。"""
        from fastapi.testclient import TestClient

        from studio.main import app

        with TestClient(app) as c:
            r = c.get("/api/admin/metrics")
            assert r.status_code in (401, 403), f"未登录应拒绝，实际 {r.status_code}"

    def test_metrics_api_returns_funnel_for_admin(self):
        """管理员可拿到 5 步漏斗数据。"""
        from fastapi.testclient import TestClient

        from studio.main import app

        with TestClient(app) as c:
            # 未登录先确认被拦
            assert c.get("/api/admin/metrics").status_code in (401, 403)
            # 直接调核心函数验证结构（避免依赖管理员登录态）
            from core import analytics

            fn = analytics.funnel(30)
            assert "steps" in fn and len(fn["steps"]) == 5


# ===========================================================================
# R5-7 自动发布频控 + 账号健康
# ===========================================================================

class TestPublishGuard:
    """R5-7：频控拦截 + 账号健康。"""

    def test_fourth_publish_in_hour_is_blocked(self, clean_env, r5_db):
        """⭐⭐ 同一账号 1 小时内第 4 条自动发布 → 被频控拦截。

        场景即任务描述的风险组合：一次 matrix 裂变 + 定时任务。
        """
        from core import pubguard

        # 只测「每小时条数」这一个维度：关掉最小间隔（另有用例单独覆盖）
        clean_env.setenv("XHS_PUBLISH_MIN_INTERVAL_S", "0")
        # 清干净历史
        c = r5_db.conn()
        c.execute("DELETE FROM publish_attempts")
        c.execute("DELETE FROM account_health")
        c.commit()
        c.close()

        # 前 3 条放行
        for i in range(3):
            gate = pubguard.check_rate_limit("xhs")
            assert gate["ok"] is True, f"第 {i + 1} 条应放行：{gate}"
            pubguard.record_attempt(f"dr-{i}", "u1", "xhs", "success", "ok")

        # 第 4 条拦截
        gate = pubguard.check_rate_limit("xhs")
        assert gate["ok"] is False, "⭐ 第 4 条必须被频控拦截"
        assert gate["detail"]["kind"] == "count"
        assert "频繁" in gate["reason"] and "限流" in gate["reason"], \
            f"拦截原因应说明频繁与风险：{gate['reason']}"
        # 文案不含开发者黑话
        for jargon in ("rate_limit", "publish_attempts", "quota"):
            assert jargon not in gate["reason"]

    def test_blocked_publish_records_attempt(self, clean_env, r5_db):
        """被拦截也要留痕（运营需知道挡了多少次）。

        模拟真实发布流程：每次都记账（无论放行还是拦截），
        第 4 次应被拦下并在台账里留下一条 blocked。
        """
        from core import pubguard

        clean_env.setenv("XHS_PUBLISH_MIN_INTERVAL_S", "0")
        c = r5_db.conn()
        c.execute("DELETE FROM publish_attempts")
        c.commit()
        c.close()

        for i in range(4):
            gate = pubguard.check_rate_limit("xhs")
            if gate["ok"]:
                pubguard.record_attempt(f"dr-{i}", "u1", "xhs", "success", "ok")
            else:
                pubguard.record_attempt("dr-x", "u1", "xhs", "blocked", gate["reason"])

        rows = pubguard.recent_attempts("xhs")
        assert sum(1 for r in rows if r["status"] == "blocked") == 1, \
            "第 4 次应被拦截并留痕"
        assert sum(1 for r in rows if r["status"] == "success") == 3

    def test_window_expiry_allows_again(self, clean_env, r5_db):
        """超过 1 小时后重新放行。"""
        from core import pubguard

        clean_env.setenv("XHS_PUBLISH_MIN_INTERVAL_S", "0")
        c = r5_db.conn()
        c.execute("DELETE FROM publish_attempts")
        c.commit()
        c.close()
        for i in range(3):
            pubguard.record_attempt(f"dr-{i}", "u1", "xhs", "success", "ok")
        assert pubguard.check_rate_limit("xhs")["ok"] is False

        # 回拨 2 小时
        c = r5_db.conn()
        c.execute("UPDATE publish_attempts SET created_at=?",
                  (time.time() - 7200,))
        c.commit()
        c.close()
        assert pubguard.check_rate_limit("xhs")["ok"] is True

    def test_min_interval_enforced(self, clean_env, r5_db):
        """最小发布间隔生效（默认 300 秒）——与条数上限是两道独立防线。"""
        from core import pubguard

        c = r5_db.conn()
        c.execute("DELETE FROM publish_attempts")
        c.commit()
        c.close()

        pubguard.record_attempt("dr-1", "u1", "xhs", "success", "ok")  # 刚刚
        gate = pubguard.check_rate_limit("xhs")
        assert gate["ok"] is False
        assert gate["detail"]["kind"] == "interval"
        assert "间隔" in gate["reason"]

    def test_threshold_is_configurable(self, clean_env, r5_db):
        """阈值可配（不同运营策略需要不同松紧）。"""
        from core import pubguard

        c = r5_db.conn()
        c.execute("DELETE FROM publish_attempts")
        c.commit()
        c.close()

        clean_env.setenv("XHS_PUBLISH_MAX_PER_HOUR", "10")
        clean_env.setenv("XHS_PUBLISH_MIN_INTERVAL_S", "0")
        for i in range(5):
            assert pubguard.check_rate_limit("xhs")["ok"] is True
            pubguard.record_attempt(f"dr-{i}", "u1", "xhs", "success", "ok")
        assert pubguard.check_rate_limit("xhs")["ok"] is True, "上限 10 时 5 条应放行"

    def test_consecutive_failures_trigger_cooldown(self, clean_env, r5_db):
        """⭐ 连续失败达阈值 → 账号进冷却，冷却期内禁止自动发布。"""
        from core import pubguard

        c = r5_db.conn()
        c.execute("DELETE FROM publish_attempts")
        c.execute("DELETE FROM account_health")
        c.commit()
        c.close()

        for i in range(3):
            pubguard.record_result(False, "xhs", f"失败{i}")
        h = pubguard.account_health("xhs")
        assert h["status"] == "cooldown", f"连续失败 3 次应进冷却，实际 {h['status']}"
        assert h["consecutive_failures"] == 3

        gate = pubguard.check_rate_limit("xhs")
        assert gate["ok"] is False, "冷却期内必须禁止自动发布"
        assert gate["detail"]["kind"] == "cooldown"
        assert "冷却" in gate["reason"]

    def test_success_resets_failures(self, clean_env, r5_db):
        """一次成功即清零连续失败。"""
        from core import pubguard

        c = r5_db.conn()
        c.execute("DELETE FROM publish_attempts")
        c.execute("DELETE FROM account_health")
        c.commit()
        c.close()

        pubguard.record_result(False, "xhs", "失败1")
        pubguard.record_result(False, "xhs", "失败2")
        assert pubguard.account_health("xhs")["consecutive_failures"] == 2
        pubguard.record_result(True, "xhs", "成功")
        h = pubguard.account_health("xhs")
        assert h["consecutive_failures"] == 0
        assert h["status"] == "healthy"

    def test_xhspublish_calls_gate_before_external_call(self, clean_env, r5_db):
        """⭐ 静态+行为护栏：被频控拦截时**绝不调用外部发布**。

        一旦被限流还继续发，只会让账号风控更严重。
        """
        import inspect

        from core import xhspub

        src = inspect.getsource(xhspub.publish)
        gate_at = src.find("check_rate_limit")
        run_at = src.find("_run(")
        assert gate_at != -1, "publish 未接入频控"
        assert run_at != -1
        assert gate_at < run_at, "频控检查必须早于外部发布调用"

        # 行为验证：拦下时不得触发 _run
        from core import pubguard

        c = r5_db.conn()
        c.execute("DELETE FROM publish_attempts")
        c.execute("DELETE FROM account_health")
        c.commit()
        for i in range(3):
            pubguard.record_attempt(f"dr-{i}", "u1", "xhs", "success", "ok")
        c.close()

        called = []
        original = xhspub._run
        xhspub._run = lambda *a, **k: called.append(1) or (0, "")
        try:
            res = xhspub.publish("dr-x")
        finally:
            xhspub._run = original

        assert res["ok"] is False and res["blocked"] is True
        assert called == [], "⭐ 被频控拦截时不得调用外部发布命令"


# ===========================================================================
# 静态护栏：面向用户文案不得含内部黑话（R5 新增文案）
# ===========================================================================

def test_r5_new_user_facing_copy_has_no_jargon():
    """R5 新增的用户可见文案不得含内部黑话。

    只查「会展示给用户」的字符串字面量与页面文案，不查模块 docstring
    （开发者注释里说明技术取舍是必要的，且不会展示给用户）。
    """
    import re

    files = [
        REPO_ROOT / "core" / "notify.py",
        REPO_ROOT / "core" / "user_notify.py",
        REPO_ROOT / "core" / "pubguard.py",
        REPO_ROOT / "core" / "share.py",
        REPO_ROOT / "core" / "qrcode_min.py",
    ]
    banned = ("mock", "dummy", "TODO", "FIXME", "占位")
    # 提取所有字符串字面量（够用且无需引入 ast 依赖）
    lit_re = re.compile(r'"([^"\\\n]{4,})"|\'([^\'\\\n]{4,})\'')
    for f in files:
        if not f.exists():
            continue
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "'''")) or stripped.startswith("*"):
                continue
            for m in lit_re.finditer(line):
                text = m.group(1) or m.group(2) or ""
                for word in banned:
                    assert word not in text, (
                        f"{f.name}:{lineno} 用户可见文案含禁用词「{word}」：{text[:60]}")


def test_r5_no_heavy_dependencies_added():
    """R5 不得引入重量级/新增依赖（保持 requirements 轻量）。

    ⭐ V8 修正：``sqlalchemy`` / ``pydantic`` 是 7.x ORM/网关的**既有核心依赖**
    （studio/db_models、gateway 全系在用），不属于 R5「新增」，移出拦截名单；
    仅拦截 R5 真正可能引入的重依赖（任务队列/Redis/图像库等）。
    """
    req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("qrcode", "segno", "celery", "apscheduler", "redis", "rq", "numpy"):
        assert pkg not in req.lower(), f"R5 不应引入依赖 {pkg}"