# SPDX-License-Identifier: BUSL-1.1
"""R4 合规与信任批次验收测试。

覆盖 R4-1 ~ R4-8 的可判定验收标准：
- R4-1 含伪医疗词的内容发布前被拦截，返回**可读**原因；灰区只标记不阻断
- R4-2 词库规模达标（≥200 条），开关可关闭
- R4-3 政治敏感选题不进 pending 池；存量可标记 blocked 而非删除
- R4-4 草稿 needs_review 字段存在，标记后**草稿不丢**
- R4-5 /static-img/data/video_config.json → 404，图片直链仍 200
- R4-6 排期非小红书平台不再标 published（诚实状态 + 文案）
- R4-7 index.html 全文搜「98.6%」零命中
- R4-8 无 CSRF token 的跨站 POST → 403；Bearer API 客户端不受影响
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-r4")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "web" / "templates" / "index.html"


@pytest.fixture()
def isolated_core_db(tmp_path, monkeypatch):
    """把 core.db 指向临时库，绝不碰生产 data/mediaflow.db。"""
    from core import db as core_db

    test_db = tmp_path / "r4_mediaflow.db"
    monkeypatch.setattr(core_db, "DB_PATH", test_db)
    monkeypatch.setattr(core_db, "DATA", tmp_path)
    return core_db


@pytest.fixture()
def guard_client():
    """加载 FastAPI app 的 TestClient（契约锁与静态目录验收需要真实路由）。"""
    from fastapi.testclient import TestClient

    from studio.main import app

    with TestClient(app) as c:
        yield c


# ===========================================================================
# R4-1 / R4-2 内容安全前置闸 + 词库
# ===========================================================================

class TestContentGuard:
    """R4-1：pre_publish_check 分级拦截 + 可读原因。"""

    def test_pseudo_medical_is_blocked_with_readable_reason(self):
        """含伪医疗词（消火 + 疗效承诺）→ 阻断，且原因面向小白可读。"""
        from core.content_guard import pre_publish_check

        res = pre_publish_check(
            "很多人以为睡不着是压力大，其实身体在求救。三步助眠法，第一步喝这个茶。",
            title='别再用手机搜"消火"了❗️这3步教你科学解忧💡',
        )
        assert res.blocked, "伪医疗擦边内容必须被阻断"
        assert res.level == "block"
        reason = res.reason()
        assert reason, "必须给出可读的拦截原因"
        # 面向小白：不能是开发者黑话，且要指明具体命中的词
        assert "检测到" in reason and "不能发布" in reason
        assert "「消火」" in reason or "消火" in reason
        for jargon in ("GuardResult", "blocklist", "regex", "traceback", "level="):
            assert jargon not in reason, f"原因里不应出现开发者黑话：{jargon}"

    def test_absolute_superlative_is_blocked(self):
        """广告法绝对化用语 → 命中拦截。"""
        from core.content_guard import pre_publish_check

        res = pre_publish_check("我们的品质全网第一，永久有效，100%有效。", title="行业第一")
        assert res.blocked
        assert "广告法极限词" in res.reason()

    def test_sexual_and_political_blocked(self):
        """涉黄擦边与政治敏感各自能拦住。"""
        from core.content_guard import pre_publish_check

        r1 = pre_publish_check("详情私聊，约炮上门服务。", title="深夜服务")
        assert r1.blocked and "涉黄" in r1.reason()

        r2 = pre_publish_check(None, title="俄罗斯不明原因肺炎死亡")
        assert r2.blocked and "政治敏感" in r2.reason()

    def test_gray_zone_marks_but_does_not_block(self):
        """灰区（review）只标记不阻断——避免误伤正常自媒体文章。"""
        from core.content_guard import pre_publish_check

        # 「顶级矩阵/唯一办法」在正常叙述里常见 → 只标记待审，不阻断
        res = pre_publish_check(
            "这才是顶级财团的经营方式，唯一的办法是开源节流，危机才能化解。",
            title="贾府破产实录",
        )
        assert not res.blocked, "灰区不应阻断"
        assert res.needs_review, "灰区应标记待人工审"
        assert "人工确认" in res.reason()

    def test_normal_content_passes(self):
        """正常自媒体内容不得被误杀。"""
        from core.content_guard import pre_publish_check

        for title, body in [
            ("蒸生蚝千万别冷水下锅", "冷水下锅肉会老，正确计时这样做，90% 的人都做错了第 2 步。"),
            ("别再做烂好人了", "普通人职场跃迁的 3 个反常识真相，做好向上管理。"),
            ("AI 重构客服流程", "千万别急着裁客服！9 成老板都踩了大坑。"),
        ]:
            res = pre_publish_check(body, title=title)
            assert not res.blocked, f"正常内容被误杀：{title} → {res.reason()}"

    def test_medical_science_whitelisted(self):
        """正常医疗科普走白名单放行（不能误杀）。"""
        from core.content_guard import pre_publish_check

        res = pre_publish_check(
            "高血压是最常见的慢性病之一。如有不适请及时就医，本文仅为科普。",
            title="高血压日常管理",
        )
        assert not res.blocked and res.whitelisted, "医疗科普应被白名单放行"

    def test_env_switch_disables_guard(self, monkeypatch):
        """CONTENT_GUARD_ENABLED=0 可整体关闸（应急回滚）。"""
        from core import content_guard

        monkeypatch.setenv("CONTENT_GUARD_ENABLED", "0")
        res = content_guard.pre_publish_check("约炮上门", title="深夜服务")
        assert not res.blocked and not res.enabled

    def test_review_only_mode_downgrades_block(self, monkeypatch):
        """CONTENT_GUARD_LEVEL=review 时全部降级为只标记。"""
        from core import content_guard

        monkeypatch.setenv("CONTENT_GUARD_LEVEL", "review")
        res = content_guard.pre_publish_check("约炮上门", title="深夜服务")
        assert res.level == "review" and not res.blocked and res.needs_review

    def test_empty_text_passes(self):
        from core.content_guard import pre_publish_check

        assert pre_publish_check("").level == "pass"
        assert pre_publish_check(None, None).level == "pass"


class TestBlocklistLibrary:
    """R4-2：词库规模与结构。"""

    def test_library_size_at_least_200(self):
        """词库条目数达 200 条起步要求。"""
        from core.content_guard import library_stats

        stats = library_stats()
        assert stats["total"] >= 200, f"词库仅 {stats['total']} 条，未达 200 条起步要求"

    def test_all_four_categories_present(self):
        """四个分类齐备：涉黄擦边 / 伪医疗 / 广告法 / 政治敏感。"""
        from core.content_guard import library_stats

        libs = library_stats()["libraries"]
        joined = " ".join(libs)
        for kw in ("涉黄擦边", "伪医疗", "广告法", "政治敏感"):
            assert kw in joined, f"缺少分类：{kw}"

    def test_json_files_are_valid_and_nonempty(self):
        """词库 JSON 均可解析且 block 档非空。"""
        from core.content_guard import BLOCKLIST_DIR

        for name in ("porn_terms.json", "medical_terms.json",
                     "ad_terms.json", "political_terms.json", "whitelist.json"):
            path = BLOCKLIST_DIR / name
            assert path.exists(), f"缺词库文件：{name}"
            data = json.loads(path.read_text(encoding="utf-8"))
            if name == "whitelist.json":
                assert data["phrases"], "白名单不能为空"
            else:
                assert data["block"]["terms"], f"{name} 的 block 词条为空"
                # 正则必须能编译
                for pat in data["block"].get("patterns", []):
                    if isinstance(pat, dict):
                        import re
                        re.compile(pat["regex"])


# ===========================================================================
# R4-3 选题池敏感过滤
# ===========================================================================

class TestTopicFiltering:
    """R4-3：敏感选题不进 pending 池。"""

    def test_political_topic_not_in_pending(self, isolated_core_db):
        """政治敏感/军事冲突选题入池时应被拦为 blocked，不进 pending。"""
        db = isolated_core_db
        from core.topics import _admit_topic

        _admit_topic("test", "俄罗斯不明原因肺炎死亡", "热榜", False)
        _admit_topic("test", "俄密集轰炸乌克兰导弹工厂有何影响", "热榜", False)
        _admit_topic("test", "寒露时节养生记住三要点", "热榜", False)

        pending_titles = [t["title"] for t in db.list_topics(status="pending")]
        blocked_titles = [t["title"] for t in db.list_blocked_topics()]

        assert "俄罗斯不明原因肺炎死亡" not in pending_titles, "敏感选题进了 pending 池"
        assert "俄密集轰炸乌克兰导弹工厂有何影响" not in pending_titles
        assert "寒露时节养生记住三要点" in pending_titles, "正常选题被误杀"
        assert len(blocked_titles) == 2, "敏感选题应标记 blocked"
        assert "俄罗斯不明原因肺炎死亡" in blocked_titles

    def test_blocked_topics_are_kept_not_deleted(self, isolated_core_db):
        """标记 blocked 而非删除——保留痕迹可复核。"""
        db = isolated_core_db
        from core.topics import _admit_topic

        _admit_topic("test", "如何看待俄实验室病毒外泄致死事件", "热榜", False)
        total = len(db.list_topics())  # 不带 status 过滤 = 全部
        assert total == 1, "被拦下的选题不应从库里消失"

    def test_blocked_reason_is_readable(self, isolated_core_db):
        """blocked_reason 存的是可读中文原因，不是黑话。"""
        db = isolated_core_db
        from core.topics import _admit_topic

        _admit_topic("test", "俄罗斯不明原因肺炎死亡", "热榜", False)
        item = db.list_blocked_topics()[0]
        assert "检测到" in item["blocked_reason"]
        assert item["blocked_reason"], "必须记录可读原因"

    def test_sweep_marks_existing_sensitive_topics(self, isolated_core_db):
        """存量敏感选题扫描：预演不写库，apply 才标记。"""
        db = isolated_core_db
        conn = db.conn()
        conn.execute(
            "INSERT INTO topics (id, created_at, source, title, reason, matched, status) "
            "VALUES ('tp-x', 0, 'test', '俄罗斯现不明原因肺炎死亡病例', '', 0, 'pending')")
        conn.commit()
        conn.close()

        dry = db.sweep_blocked_topics(apply=False)
        assert dry["would_block"] == 1 and dry["blocked"] == 0
        assert db.list_topics(status="pending"), "预演不应改动数据"

        applied = db.sweep_blocked_topics(apply=True)
        assert applied["blocked"] == 1
        assert not db.list_topics(status="pending")
        assert len(db.list_blocked_topics()) == 1


# ===========================================================================
# R4-4 草稿 needs_review
# ===========================================================================

class TestDraftNeedsReview:
    """R4-4：草稿加 needs_review 字段 + 标记不删除。"""

    def test_draft_model_has_needs_review_field(self):
        """studio/db_models.py 的 Draft 模型有 needs_review 字段。"""
        from studio.db_models import Draft

        assert "needs_review" in Draft.__table__.columns
        assert "guard_reason" in Draft.__table__.columns

    def test_schema_migration_adds_columns(self, isolated_core_db):
        """core.db.conn() 的迁移逻辑会给旧库补列。"""
        conn = isolated_core_db.conn()
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(drafts)")}
        assert "needs_review" in cols and "guard_reason" in cols
        conn.close()

    def test_mark_and_clear_needs_review(self, isolated_core_db):
        """标记与清除都正常，且草稿始终保留。"""
        db = isolated_core_db
        d = db.add_draft("tp1", "测试稿件", "正文内容", ["xhs"])

        assert db.mark_draft_needs_review(d["id"], "检测到测试原因")
        marked = db.list_drafts_needs_review()
        assert len(marked) == 1 and marked[0]["id"] == d["id"]
        assert marked[0]["guard_reason"] == "检测到测试原因"

        # 草稿仍在库中（未被删除）
        assert db.get_draft(d["id"]) is not None
        assert len(db.list_drafts()) == 1

        assert db.clear_draft_needs_review(d["id"])
        assert db.list_drafts_needs_review() == []

    def test_sweep_flags_violating_draft(self, isolated_core_db):
        """扫描草稿：违规成品被标记，正常稿件不被误标记为阻断。"""
        db = isolated_core_db
        bad = db.add_draft("tp1", '别再用手机搜"消火"了❗️这3步教你科学解忧💡',
                           "很多人以为睡不着是压力大，其实身体在求救。偏方治本。", ["xhs"])
        good = db.add_draft("tp2", "蒸生蚝千万别冷水下锅", "冷水下锅肉会老，90%的人都做错了。", ["xhs"])

        dry = db.sweep_drafts_needs_review(apply=False)
        assert dry["flagged"] == 1 and dry["marked"] == 0

        applied = db.sweep_drafts_needs_review(apply=True)
        assert applied["marked"] == 1
        flagged_ids = [x["id"] for x in db.list_drafts_needs_review()]
        assert flagged_ids == [bad["id"]], "只应标记违规稿件"
        assert db.get_draft(good["id"]) is not None, "正常草稿必须保留"


# ===========================================================================
# R4-1 链路接入：发布前必须过闸
# ===========================================================================

class TestPublishChainGuard:
    """R4-1：approve_and_publish 发布前必经内容安全闸。"""

    def test_publish_blocked_for_violating_draft(self, isolated_core_db):
        db = isolated_core_db
        d = db.add_draft("tp1", '别再用手机搜"消火"了❗️这3步教你科学解忧💡',
                         "很多人以为睡不着是压力大，其实身体在求救。偏方治本，三天见效。", ["xhs"])
        from core import orchestrator

        results = orchestrator.approve_and_publish(d["id"], ["xhs", "wechat_mp"])
        assert len(results) == 1
        assert results[0]["ok"] is False, "违规内容不得进入发布"
        assert "内容安全" in results[0]["detail"]
        # 不得产生任何发布任务
        assert db.list_jobs() == [], "被拦截的稿件不应创建发布任务"

    def test_publish_allowed_for_normal_draft(self, isolated_core_db):
        db = isolated_core_db
        d = db.add_draft("tp1", "蒸生蚝千万别冷水下锅", "冷水下锅肉会老，90%的人都做错了第2步。", ["xhs"])
        from core import orchestrator

        results = orchestrator.approve_and_publish(d["id"], ["xhs"])
        assert results[0]["ok"] is True, f"正常稿件应放行：{results[0]['detail']}"


# ===========================================================================
# R4-5 静态目录收窄 + 明文 Key 迁移
# ===========================================================================

class TestStaticExposure:
    """R4-5：data/ 不再可通过 HTTP 下载，但图片直链不打断。"""

    def test_data_dir_files_are_404(self, guard_client):
        """验收标准：访问 /static-img/data/video_config.json → 404。"""
        for path in (
            "/static-img/data/video_config.json",
            "/static-img/video_config.json",
            "/static-img/mediaflow.db",
            "/static-img/billing.json",
            "/static-img/cookies",
            "/static-img/drafts",
        ):
            resp = guard_client.get(path)
            assert resp.status_code == 404, f"{path} 仍可访问（HTTP {resp.status_code}）"

    def test_no_secret_leaks_through_static(self, guard_client):
        """即便路径被猜到，也拿不到任何 key 内容。"""
        resp = guard_client.get("/static-img/data/video_config.json")
        assert resp.status_code == 404
        assert "pexels" not in resp.text.lower()

    def test_only_editor_uploads_is_mounted(self):
        """静态挂载只保留 editor_uploads 子目录。"""
        src = (REPO_ROOT / "web" / "admin.py").read_text(encoding="utf-8")
        assert 'StaticFiles(directory=str(BASE / "data"))' not in src, \
            "整个 data/ 目录仍被挂成静态服务"
        assert "/static-img/editor_uploads" in src

    def test_image_direct_links_still_work(self, guard_client):
        """关键回归：/img/{did}/{name} 与 /card/{did}/{name} 直链不能被打断。"""
        did = "dr-fca81d99e8"
        draft_dir = REPO_ROOT / "data" / "drafts" / did
        img = draft_dir / "img" / "cover.png"
        card = draft_dir / "card-0.png"
        if not img.exists() or not card.exists():
            pytest.skip("本地无草稿图片产物，跳过直链回归验证")

        r1 = guard_client.get(f"/img/{did}/cover.png")
        r2 = guard_client.get(f"/card/{did}/card-0.png")
        assert r1.status_code == 200 and r1.headers["content-type"] == "image/png"
        assert r2.status_code == 200 and r2.headers["content-type"] == "image/png"

    def test_video_config_json_has_no_plaintext_key(self):
        """data/video_config.json 不得再含明文 key。"""
        path = REPO_ROOT / "data" / "video_config.json"
        if not path.exists():
            pytest.skip("本地无 video_config.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert not (data.get("pexels_api_key") or "").strip(), \
            "data/video_config.json 仍存明文 pexels_api_key"

    def test_pexels_key_readable_from_env(self, monkeypatch):
        """get_pexels_key 能从 .env / 环境变量读到（迁移后不断档）。"""
        import studio.video_config as vc

        monkeypatch.setattr(vc, "_CONFIG_PATH", REPO_ROOT / "data" / "__none__.json")
        monkeypatch.setenv("PEXELS_API_KEY", "env-only-key-123")
        assert vc.get_pexels_key() == "env-only-key-123"
        assert vc.get_masked_config()["pexels_api_key_source"] == "env"


# ===========================================================================
# R4-6 排期发布不再假成功
# ===========================================================================

class TestSchedulerHonesty:
    """R4-6：非小红书平台不得标 published。"""

    def test_non_xhs_platform_not_marked_published(self, isolated_core_db):
        db = isolated_core_db
        d = db.add_draft("tp1", "测试稿件", "正文", ["toutiao"])
        pid = db.add_scheduled_post(d["id"], "toutiao", 0)

        from core import scheduler

        scheduler._run_scheduled_job(
            {"id": pid, "draft_id": d["id"], "platform": "toutiao"})

        post = db.list_scheduled_posts()[0]
        assert post["status"] != "published", "非小红书平台不得标为已发布"
        assert post["status"] == "manual_pending"
        assert "暂不支持自动发布" in post["detail"]
        assert "手动复制" in post["detail"]
        assert "模拟分发成功" not in post["detail"], "假成功文案必须移除"

    def test_source_has_no_fake_success_string(self):
        """源码**可执行语句**里不得再把非小红书平台标成 published。

        注意：模块 docstring 与注释里保留了那句假成功的原文作为变更说明
        （这是有价值的审计痕迹），因此这里剥离 docstring 后再用 AST 检查。
        """
        import ast
        from pathlib import Path as _P

        src = _P(REPO_ROOT / "core" / "scheduler.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(
                        getattr(body[0], "value", None), ast.Constant):
                    body = body[1:]   # 丢掉 docstring
                node.body = body or [ast.Pass()]
        stripped = ast.unparse(tree)

        assert "模拟分发成功" not in stripped, "代码里仍有假成功文案"

        # 逐个检查 update_scheduled_post_status 的状态参数：
        # 只有带「小红书」字样的调用才允许 published（那是真实发布成功的分支）。
        for call in ast.walk(ast.parse(stripped)):
            if (isinstance(call, ast.Call) and getattr(call.func, "attr", "") ==
                    "update_scheduled_post_status"
                    and len(call.args) >= 2
                    and isinstance(call.args[1], ast.Constant)
                    and call.args[1].value == "published"):
                line = ast.unparse(call)
                assert "小红书" in line, f"非小红书分支被标成 published：{line}"

    def test_frontend_handles_manual_pending(self):
        """前端能展示 manual_pending 状态与提示文案。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "manual_pending" in html, "前端未处理 manual_pending 状态"
        assert "待手动发布" in html
        assert "p.detail" in html, "前端未展示 detail 提示文案"


# ===========================================================================
# R4-7 首页假数据清理
# ===========================================================================

class TestDashboardFakeData:
    """R4-7：首页不得再展示永不变化的假数字。"""

    def test_acceptance_986_zero_hits(self):
        """验收标准：index.html 全文搜「98.6%」→ 零命中。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "98.6%" not in html, "首页仍有写死的 98.6% 达标率"

    def test_other_hardcoded_fake_numbers_zero_hits(self):
        """其余写死数字同样清零。

        ⚠️ 只检查首页**数据看板**区域。会员套餐表里的「500,000 Token」
        是真实的定价额度（¥99/月 送 50 万 token），不属于假数据，不能删。
        """
        html = INDEX_HTML.read_text(encoding="utf-8")
        for token in ("88.6", "200 条 (100%)", "54 篇 (27%)",
                      "达标率98", "峰值240"):
            assert token not in html, f"首页仍写死：{token}"

        # 顶栏算力余额默认必须是占位符，不是写死的 50 万
        assert '<span id="nav-token-bal">—</span>' in html, \
            "顶栏算力余额默认值应为「—」，由 loadBillingStatus() 真实填充"

    def test_pricing_plan_allowance_preserved(self):
        """会员套餐的真实额度不能被误删（回归保护）。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "500,000 Token" in html, "会员套餐额度被误删"

    def test_x_axis_dates_generated_by_js(self):
        """X 轴日期不再写死，改由 JS 动态生成。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "09-15" not in html and "09-21" not in html
        assert 'id="trend-x-axis"' in html, "缺少 X 轴容器"
        assert "function renderTrendXAxis()" in html, "缺少 X 轴动态生成函数"

    def test_empty_state_uses_guidance_not_fake_numbers(self):
        """无数据时显示引导态而非假数字。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "去生成第一篇" in html or "还没有成稿" in html
        for el in ("dash-topics-count", "dash-drafts-count", "dash-videos-count"):
            assert f'id="{el}">—<' in html, f"{el} 默认值应为 —"

    def test_real_stats_renderer_exists(self):
        """真实统计渲染函数已接入 refresh 链路。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "function renderDashboardRealStats()" in html
        assert "renderDashboardRealStats();" in html, "未在 refresh() 中调用"


# ===========================================================================
# R4-8 CSRF + 安全响应头
# ===========================================================================

class TestCSRFProtection:
    """R4-8：跨站 POST 拦截，API 客户端不误伤。"""

    def test_cross_site_post_without_token_gets_403(self, guard_client):
        """验收标准：无 CSRF token 的跨站 POST → 403。"""
        guard_client.cookies.set("mf_token", "some-session")
        resp = guard_client.post("/api/topics/collect", json={},
                                 headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403, f"跨站 POST 应 403，实际 {resp.status_code}"
        assert "CSRF" in resp.json().get("detail", "")

    def test_publish_route_blocked_cross_site(self, guard_client):
        """任务点名的危险接口：跨站诱导发布必须失败。"""
        guard_client.cookies.set("mf_v6_token", "some-session")
        resp = guard_client.post("/api/drafts/dr-fca81d99e8/publish",
                                 json={"platforms": ["xhs"]},
                                 headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403

    def test_delete_vault_keys_blocked_cross_site(self, guard_client):
        """DELETE 接口同样受 CSRF 保护。"""
        guard_client.cookies.set("mf_v6_token", "some-session")
        resp = guard_client.request("DELETE", "/api/user/vault/keys/k1",
                                    headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403

    def test_mismatched_token_gets_403(self, guard_client):
        guard_client.cookies.set("mf_token", "sess")
        guard_client.cookies.set("csrf_token", "right-token")
        resp = guard_client.post("/api/topics/collect", json={},
                                 headers={"X-CSRF-Token": "wrong-token"})
        assert resp.status_code == 403

    def test_valid_token_passes_csrf(self, guard_client):
        """带正确 token 的浏览器请求不再被 CSRF 拦（交给后续鉴权）。"""
        guard_client.cookies.set("mf_token", "sess")
        guard_client.cookies.set("csrf_token", "right-token")
        resp = guard_client.post("/api/topics/collect", json={},
                                 headers={"X-CSRF-Token": "right-token"})
        assert resp.status_code != 403, "合法请求被 CSRF 误杀"

    def test_api_client_with_bearer_not_blocked(self, guard_client):
        """API 客户端（Bearer 鉴权）不被 CSRF 挡掉——SDK/CLI 仍可用。"""
        resp = guard_client.post("/api/topics/collect", json={},
                                 headers={"Authorization": "Bearer sdk-key"})
        assert resp.status_code != 403, "Bearer API 客户端被 CSRF 误伤"

    def test_anonymous_request_gets_401_not_403(self, guard_client):
        """无 Cookie 无 token：应落到鉴权 401，而非 CSRF 403。"""
        resp = guard_client.post("/api/topics/collect", json={})
        assert resp.status_code == 401

    def test_safe_methods_not_affected(self, guard_client):
        """GET 不受 CSRF 影响。"""
        guard_client.cookies.set("mf_token", "sess")
        resp = guard_client.get("/api/version")
        assert resp.status_code == 200

    def test_login_exempt_so_users_can_sign_in(self, guard_client):
        """登录接口豁免 CSRF，否则没人能登录。"""
        resp = guard_client.post("/api/auth/login",
                                 json={"password": "wrong-password"})
        assert resp.status_code != 403

    def test_csrf_switch_allows_rollback(self, monkeypatch, guard_client):
        """应急回滚开关。"""
        monkeypatch.setenv("CSRF_PROTECTION_ENABLED", "0")
        guard_client.cookies.set("mf_token", "sess")
        resp = guard_client.post("/api/topics/collect", json={},
                                 headers={"Origin": "https://evil.example"})
        assert resp.status_code != 403


class TestSecurityHeaders:
    """R4-8：安全响应头齐备。"""

    def test_headers_present(self, guard_client):
        resp = guard_client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        csp = resp.headers.get("Content-Security-Policy", "")
        assert csp, "缺少 CSP"
        for directive in ("default-src", "object-src 'none'", "frame-ancestors 'none'"):
            assert directive in csp, f"CSP 缺少 {directive}"

    def test_security_headers_on_error_responses(self, guard_client):
        """403 响应同样带安全头。"""
        guard_client.cookies.set("mf_token", "sess")
        resp = guard_client.post("/api/topics/collect", json={},
                                 headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Content-Security-Policy")

    def test_csrf_cookie_issued_to_browser(self, guard_client):
        """页面下发 csrf_token Cookie，且非 HttpOnly（前端 JS 需读取）。"""
        resp = guard_client.get("/")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "csrf_token=" in set_cookie
        assert "HttpOnly" not in set_cookie

    def test_frontend_sends_csrf_header(self):
        """前端 api() 与 fetch 兜底都会带上 token。"""
        for name in ("index.html", "mobile.html"):
            html = (REPO_ROOT / "web" / "templates" / name).read_text(encoding="utf-8")
            assert "csrfHeaders" in html, f"{name} 缺少 csrfHeaders()"
            assert "X-CSRF-Token" in html, f"{name} 未发送 X-CSRF-Token"
            assert "patchFetchForCsrf" in html, f"{name} 未给裸 fetch 兜底加 token"
