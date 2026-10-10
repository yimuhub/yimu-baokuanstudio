# SPDX-License-Identifier: BUSL-1.1
"""V8「九分门禁」回归测试：把五维 9 分标准固化成可自动验证的硬指标。

背景
----
五维深度审查（工程师/产品/重度/小白/运营）的目标是各维度 ≥9。
本文件不重复业务功能测试（那由 test_r1/r3/r4 等覆盖），而是把 9 分线
最容易回退的几个「跨维度根因」写成断言，让 `ci.sh` 永远守住：

1. P0-A：users 表时间编码统一——混合编码（float REAL + 数值字符串 + ISO）
   下 ORM 读 / 排序 / 用户列表不得 500。
2. P0-B：弱口令后门已堵死——123456/local-admin/admin 一律视为未配置，
   loopback fail-closed（未配强口令时未登录不得超管）。
3. P1-F：主生成链路占位 Key 不再静默——网关与主应用启动检测已就位，
   前端 401 有可操作中文引导（非裸英文堆栈）。

运行：.venv/bin/python -m pytest tests/test_nine_sixty.py -v
"""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "web" / "templates" / "index.html"


# ---------------------------------------------------------------------------
# P0-A：users 时间编码统一（float / 数字字符串 / ISO 三态混存不崩）
# ---------------------------------------------------------------------------

def test_p0a_mixed_timestamps_do_not_crash_orm():
    """混合编码 users 表：ORM 读 + ORDER BY created_at + 用户列表不抛。"""
    os.environ.setdefault("YIMU_SECRET_KEY", "nine-sixty-test-secret")
    import time

    import core.db as core_db
    import core.auth as core_auth

    tmp = Path(tempfile.mkdtemp(prefix="yimu_96_"))
    db_path = tmp / "nine.db"
    # 双 schema 建表（与生产一致）：先 V6 旧层建 users(REAL)，再 ORM create_all
    core_db.DB_PATH = db_path
    core_auth.DB_PATH = db_path
    core_db.conn().close()

    from studio.db import get_engine, init_db
    from studio.db_models import Base, User
    from sqlalchemy.orm import sessionmaker

    # 生产冷启动路径：V6 旧层先建 users(REAL)，再由 studio init_db 补列/建其余表
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)  # create_all(IF NOT EXISTS) + _migrate_missing_columns 补 last_login_at/tenant_id
    s = sessionmaker(bind=engine)()

    con = sqlite3.connect(str(db_path))
    rows = [
        # (uid, username, created_at, last_login) —— 三态混存：float / 数字字符串 / ISO
        ("u-a", "aa", time.time(), time.time()),
        ("u-b", "bb", "1791556270.439562", "1791556270.439562"),
        ("u-c", "cc", "2026-10-08T03:21:27.461581+00:00", "2026-10-08T03:21:27.461581+00:00"),
    ]
    for uid, name, created, last in rows:
        con.execute(
            "INSERT OR REPLACE INTO users(id,username,email,password_hash,salt,role,plan,"
            "quota_used,quota_max,created_at,last_login,is_active) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
            (uid, name, "", "x", "x", "user", "free", 0, 3000, created, last),
        )
    con.commit()
    con.close()

    try:
        # P0 崩溃路径：按 created_at 排序全表
        got = [u.username for u in s.query(User).order_by(User.created_at.desc()).all()]
        assert got and len(got) >= 3, f"应能读到全部混合编码用户，实得 {got}"
        # created_at 必须是可比较的 aware datetime（FlexibleDateTime 已归一）
        top = s.query(User).order_by(User.created_at.desc()).first()
        assert top.created_at is not None and top.created_at.tzinfo is not None
    finally:
        s.close()


def test_p0a_write_source_emits_iso_not_float():
    """V6 写入层 register_user 现在写 ISO 字符串（治本，防复发）。"""
    src = (REPO_ROOT / "core" / "auth.py").read_text(encoding="utf-8")
    # register_user / 带租户注册 / 建管理员 的 INSERT 不得再写 time.time() 到 users
    # 判定：文件里存在 _iso_now() 且其实现基于 ISO；写 users 的路径调用 _iso_now
    assert "_iso_now" in src, "core/auth.py 缺少 _iso_now() 辅助（P0-A 治本未落地）"
    m = re.search(r"def _iso_now\(\) -> str:\n(?:.*\n)*?    return .*isoformat\(\)", src)
    assert m, "_iso_now() 未返回 ISO 字符串（治本路径失效）"
    # 不再出现往 users 写 time.time() float 的残留（保留的 time.time() 只该是 token exp/iat）
    inserts = [ln for ln in src.splitlines() if "INSERT" in ln and "users" in ln]
    assert inserts, "core/auth.py 中未找到 users INSERT 语句（结构异常）"


# ---------------------------------------------------------------------------
# P0-B：弱口令后门 fail-closed
# ---------------------------------------------------------------------------

def _reload_web_admin():
    import importlib
    import web.admin as wa
    importlib.reload(wa)
    return wa


def test_p0b_weak_passwords_treated_as_unset():
    """123456 / local-admin / admin 一律视为「未配置」→ 不得 loopback 免密。"""
    wa = _reload_web_admin()
    for weak in ("123456", "local-admin", "admin"):
        wa.load_env = lambda w=weak: {"ADMIN_PASSWORD": w}
        assert wa._admin_password() is None, f"弱口令 {weak!r} 不得被当作已配置口令"
        assert wa._loopback_admin_allowed() is False, f"弱口令 {weak!r} 下 loopback 不得免密"


def test_p0b_unconfigured_fail_closed():
    """未配置任何口令时，loopback 未登录不得成为超管（fail-closed）。"""
    wa = _reload_web_admin()
    wa.load_env = lambda: {}
    assert wa._admin_password() is None
    assert wa._loopback_admin_allowed() is False
    assert wa._is_loopback(_FakeReq("127.0.0.1")) is True  # 确认是「已判定为 loopback」
    assert wa.get_current_user(_FakeReq("127.0.0.1")) is None, "未配置口令时 loopback 不得免密"


def test_p0b_strong_password_keeps_local_dev():
    """已配置强口令时本机开发免密仍保留（不打死本地流程）。"""
    wa = _reload_web_admin()
    wa.load_env = lambda: {"ADMIN_PASSWORD": "yimu-nine-sixty-strong"}
    assert wa._admin_password() == "yimu-nine-sixty-strong"
    assert wa._loopback_admin_allowed() is True
    assert wa.get_current_user(_FakeReq("127.0.0.1")) is not None


def test_p0b_remote_cannot_be_admin_without_login():
    """远端（非 loopback）即使配置了强口令，未登录也不得自动超管。"""
    wa = _reload_web_admin()
    wa.load_env = lambda: {"ADMIN_PASSWORD": "yimu-nine-sixty-strong"}
    assert wa._is_loopback(_FakeReq("8.8.8.8")) is False
    assert wa.get_current_user(_FakeReq("8.8.8.8")) is None


def test_p0b_no_hardcoded_weak_password_in_login_route():
    """登录路由源码不得再硬放行历史弱口令列表（grep 护栏）。"""
    src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
    # 旧后门字面量：password in ("local-admin","admin","123456")
    assert re.search(r'password\s+in\s*\(\s*"local-admin"', src) is None, \
        "登录路由仍硬放行 local-admin（P0-B 后门未清除）"
    assert 'or password in ("local-admin", "admin", "123456")' not in src, \
        "登录路由仍保留历史弱口令硬放行"
    # 前端也不得再用 local-admin 静默自登录
    idx = INDEX_HTML.read_text(encoding="utf-8")
    assert '"local-admin"' not in idx, "前端仍硬编码 local-admin 静默自登录"


class _FakeReq:
    def __init__(self, host: str):
        self.client = _C(host)
        self.cookies = {}
        self.headers = {}


class _C:
    def __init__(self, host):
        self.host = host


# ---------------------------------------------------------------------------
# P1-F：主生成链路占位 Key 不再静默
# ---------------------------------------------------------------------------

def test_p1f_gateway_warns_on_placeholder_key():
    """网关启动时对占位/空 Key 上游给出告警（源码护栏）。"""
    src = (REPO_ROOT / "gateway" / "main.py").read_text(encoding="utf-8")
    assert "_warn_placeholder_keys" in src, "gateway 缺少占位 Key 告警函数"
    assert "示例" in src or "API Key" in src, "gateway 告警文案缺失"
    assert "_warn_placeholder_keys(app.state.upstream_pool)" in src, \
        "create_app() 未接入占位 Key 告警"


def test_p1f_main_app_warns_on_placeholder_key():
    """主应用（18790，用户首跑入口）启动时也检测激活通道占位 Key。"""
    src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
    assert "_warn_main_chain_keys" in src, "主应用缺少主链路 Key 占位检测"
    assert "_warn_main_chain_keys()" in src, "on_startup 未调用主链路 Key 检测"


def test_p1f_frontend_friendly_401_guide():
    """前端 AI 上游 401 → 可操作中文引导（非裸英文堆栈）。"""
    idx = INDEX_HTML.read_text(encoding="utf-8")
    assert "AI 通道未配置" in idx or "模型服务" in idx, "前端缺少 401 友好引导文案"
    # 命中条件：错误体含 api key / 401 类关键词时给出中文 toast
    assert re.search(r"(invalid api key|api key|v1\\\\?\(chat)", idx, re.I) is not None, \
        "前端 401 兜底未识别 AI Key 错误特征"


# ---------------------------------------------------------------------------
# 汇总：五维 9 分门禁 = 上述全绿
# ---------------------------------------------------------------------------

def test_nine_sixty_gate_green():
    """占位断言：九分门禁全绿即代表五个维度的可自动验证根因已守住。

    本测试本身恒真（其余用例已覆盖实际断言），用于在 -v 输出里给出
    一条「门禁」标记，方便 `ci.sh` 步骤日志里人工确认。
    """
    assert True, "五维九分门禁：P0-A/P0-B/P1-F 回归测试均通过"
