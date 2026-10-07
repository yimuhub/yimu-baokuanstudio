# SPDX-License-Identifier: BUSL-1.1
"""WS-C 路由集成 + 图片专项行为测试。

⭐ 硬规则：
- 不 import fastapi；测试替身一律称「桩」。
- 业务模块由并行 agent 实现：凡依赖其行为的用例一律用
  pytest.importorskip 引用锁定接口；骨架期模块未落地时跳过
  （ci.sh 允许 skip、不允许 fail，写法同 tests/test_canary.py）。
- 路由注册表 / handle_request 分发 / 租户校验不依赖业务模块，始终执行。
- 金丝雀种子 tests/seed/ 只读：本文件绝不写入 expected.json。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.errors import BadRequest, Code, UpstreamNotReady
from studio.image_forge.router import (
    ROUTES,
    build_router,
    handle_request,
)

SEED_DIR = Path(__file__).resolve().parent / "seed"

# docs/CONTRACT.md §6 图片质量专项契约（冻结版，逐字对齐）
CONTRACT_ROUTES = {
    ("POST", "/api/image/forge"),
    ("GET", "/api/image/styles"),
    ("POST", "/api/image/generate"),
    ("POST", "/api/image/judge"),
    ("GET", "/api/image/benchmark"),
}


def _ctx(**overrides) -> dict:
    """构造 handler 上下文：默认带租户与链路 id。"""
    ctx = {"tenant_id": "t_ws_c_test", "request_id": "req-ws-c-001"}
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# 路由注册表与分发（不依赖业务模块，始终执行）
# ---------------------------------------------------------------------------


class TestRouterRegistry:
    """ROUTES 注册表与 handle_request 分发。"""

    def test_routes_match_contract_section_6(self):
        """ROUTES 恰好 5 条，(method, path) 与 CONTRACT §6 一致。"""
        assert len(ROUTES) == 5, f"路由条数漂移：{ROUTES}"
        assert {(m, p) for m, p, _ in ROUTES} == CONTRACT_ROUTES
        assert [name for _, _, name in ROUTES] == [
            "forge",
            "styles",
            "generate",
            "judge",
            "benchmark",
        ]

    def test_unknown_path_returns_not_found(self):
        """未知路径 → ok=False 且 code=NOT_FOUND。"""
        resp = handle_request("POST", "/api/image/nope", {}, _ctx())
        assert resp["ok"] is False
        assert resp["code"] == Code.NOT_FOUND

    def test_unknown_method_on_known_path_returns_not_found(self):
        """已知路径配错方法 → 同样 NOT_FOUND。"""
        resp = handle_request("DELETE", "/api/image/styles", {}, _ctx())
        assert resp["ok"] is False
        assert resp["code"] == Code.NOT_FOUND

    @pytest.mark.parametrize("path", ["/api/image/forge", "/api/image/generate", "/api/image/judge"])
    def test_missing_tenant_rejected(self, path):
        """⭐ generate/judge/forge 缺 tenant_id → BAD_REQUEST（经 handle_request 转错误体）。"""
        method = "POST"
        resp = handle_request(method, path, {}, {"request_id": "req-no-tenant"})
        assert resp["ok"] is False
        assert resp["code"] == Code.BAD_REQUEST
        assert resp["message"] == "缺少租户信息"

    def test_judge_missing_url_rejected(self):
        """judge 缺 url → BadRequest("请提供图片地址")。"""
        resp = handle_request("POST", "/api/image/judge", {"prompt": "晚霞"}, _ctx())
        assert resp["ok"] is False
        assert resp["code"] == Code.BAD_REQUEST
        assert resp["message"] == "请提供图片地址"

    def test_build_router(self):
        """build_router：无 fastapi 时抛 ImportError；有则返回 5 条路由。"""
        try:
            import fastapi  # noqa: F401
        except ImportError:
            with pytest.raises(ImportError, match="fastapi 未安装"):
                build_router()
        else:
            router = build_router()
            got = {(sorted(r.methods)[0], r.path) for r in router.routes}
            assert got == CONTRACT_ROUTES


# ---------------------------------------------------------------------------
# 风格库（studio.image_forge.styles）
# ---------------------------------------------------------------------------


class TestStyleLibrary:
    """12 风格库：数量 / 字段 / id 唯一。"""

    def test_exactly_12_styles(self):
        styles_mod = pytest.importorskip("studio.image_forge.styles", reason="骨架期：风格库未实现")
        styles = styles_mod.list_styles()
        assert len(styles) == 12, f"风格库数量漂移：{len(styles)}"

    def test_style_item_fields(self):
        styles_mod = pytest.importorskip("studio.image_forge.styles", reason="骨架期：风格库未实现")
        required = {"id", "name", "description", "use_cases", "prompt_fragment", "example_image_url"}
        for item in styles_mod.list_styles():
            assert required <= set(item), f"风格项缺字段：{item.get('id')}"
            assert item["example_image_url"], f"风格 {item['id']} 缺示例图 URL"

    def test_style_ids_unique(self):
        styles_mod = pytest.importorskip("studio.image_forge.styles", reason="骨架期：风格库未实现")
        ids = [item["id"] for item in styles_mod.list_styles()]
        assert len(ids) == len(set(ids)), f"风格 id 重复：{ids}"


# ---------------------------------------------------------------------------
# 赛马（studio.image_forge.race）
# ---------------------------------------------------------------------------


def _race_candidates() -> list[dict]:
    """赛马候选：3 张固定地址。"""
    return [
        {"url": "https://img.example.com/race/a.png", "prompt": "晨雾中的江南小镇"},
        {"url": "https://img.example.com/race/b.png", "prompt": "晨雾中的江南小镇"},
        {"url": "https://img.example.com/race/c.png", "prompt": "晨雾中的江南小镇"},
    ]


class TestRace:
    """Aesthetic Judge 赛马：确定性 / 优选最高分 / 空列表拒绝。"""

    def test_race_is_deterministic(self):
        race_mod = pytest.importorskip("studio.image_forge.race", reason="骨架期：赛马未实现")
        first = race_mod.race(_race_candidates())
        second = race_mod.race(_race_candidates())
        assert first == second, "同一候选集两次赛马结果不一致"
        assert first["winner"] == second["winner"]
        assert first["ranking"] == second["ranking"]

    def test_winner_has_top_race_score(self):
        race_mod = pytest.importorskip("studio.image_forge.race", reason="骨架期：赛马未实现")
        result = race_mod.race(_race_candidates())
        scores = [item["race_score"] for item in result["ranking"]]
        assert result["winner"]["race_score"] == max(scores), "优选图不是最高分"

    def test_empty_candidates_rejected(self):
        race_mod = pytest.importorskip("studio.image_forge.race", reason="骨架期：赛马未实现")
        with pytest.raises(BadRequest):
            race_mod.race([])


# ---------------------------------------------------------------------------
# Judge（studio.image_forge.judge）
# ---------------------------------------------------------------------------


class TestJudge:
    """Aesthetic Judge：分值范围 / 缺陷结构 / 宽高可选。"""

    def test_scores_in_range(self):
        judge_mod = pytest.importorskip("studio.image_forge.judge", reason="骨架期：Judge 未实现")
        report = judge_mod.judge_image({"url": "https://img.example.com/j1.png", "prompt": "晚霞"})
        assert 0 <= report["quality_score"] <= 10
        assert 0 <= report["fidelity_score"] <= 10

    def test_defects_and_hints_are_lists_and_dims_optional(self):
        judge_mod = pytest.importorskip("studio.image_forge.judge", reason="骨架期：Judge 未实现")
        report = judge_mod.judge_image({"url": "https://img.example.com/j2.png"})
        assert isinstance(report["defects"], list)
        assert isinstance(report["retouch_hints"], list)


# ---------------------------------------------------------------------------
# PromptForge（studio.promptforge）
# ---------------------------------------------------------------------------


class TestForgePrompt:
    """forge_prompt：7 个固定键；空输入抛 BadRequest。"""

    def test_returns_seven_fixed_keys(self):
        promptforge = pytest.importorskip("studio.promptforge", reason="骨架期：PromptForge 未实现")
        result = promptforge.forge_prompt("雨后初晴的西湖", "cinematic")
        assert set(result) == {
            "subject",
            "style",
            "lighting",
            "composition",
            "negative",
            "prompt",
            "style_id",
        }, f"返回键漂移：{sorted(result)}"

    @pytest.mark.parametrize("thin", ["", "   "])
    def test_empty_input_rejected(self, thin):
        promptforge = pytest.importorskip("studio.promptforge", reason="骨架期：PromptForge 未实现")
        with pytest.raises(BadRequest):
            promptforge.forge_prompt(thin, "cinematic")


class TestCanaryAssemble:
    """PromptForge 金丝雀口径：assemble_prompt 在 hot_1.json 上与 expected.json 逐字一致。"""

    def test_assemble_prompt_matches_expected_on_hot_1(self):
        promptforge = pytest.importorskip("studio.promptforge", reason="骨架期：PromptForge 未实现")
        hotspot = json.loads((SEED_DIR / "hot_1.json").read_text(encoding="utf-8"))
        expected = json.loads((SEED_DIR / "expected.json").read_text(encoding="utf-8"))
        key = f"{hotspot['id']}:纪实短评"
        assert promptforge.assemble_prompt(hotspot, "纪实短评") == expected["assemble_prompt"][key]


# ---------------------------------------------------------------------------
# generate 集成（studio.image_forge.generate + 桩客户端 + 隔离库）
# ---------------------------------------------------------------------------


_STUB_IMAGE_URLS = (
    "https://img.example.com/ws-c/gen-1.png",
    "https://img.example.com/ws-c/gen-2.png",
    "https://img.example.com/ws-c/gen-3.png",
)


class _StubImageClient:
    """测试桩：模拟网关图片客户端。

    遵循 studio.image_forge.generate 文档化的桩协议：
    ``client(prompt=..., n=..., size=...) -> list[{"url","revised_prompt"}]``，
    返回 3 张固定地址；每次调用记录在 calls 供断言。
    """

    def __init__(self, urls=_STUB_IMAGE_URLS) -> None:
        self._urls = tuple(urls)
        self.calls: list[dict] = []

    def __call__(self, *, prompt: str = "", n: int = 3, size: str = "1024x1024") -> list[dict]:
        self.calls.append({"prompt": prompt, "n": n, "size": size})
        return [
            {"url": url, "revised_prompt": prompt} for url in self._urls[:n]
        ]


def _ledger_count_for_tenant(engine, tenant_id: str) -> int:
    """查某租户在 ledger 表中的行数（只增不改账本，只读查询）。"""
    from sqlalchemy.orm import Session

    from studio.db_models import Ledger

    with Session(engine) as session:
        return session.query(Ledger).filter(Ledger.tenant_id == tenant_id).count()


class TestGenerateIntegration:
    """generate：桩客户端 3 图赛马 → 优选/候选/计费/账本；缺 client 抛 UpstreamNotReady。"""

    def test_generate_with_stub_client(self, db_url):
        generate_mod = pytest.importorskip("studio.image_forge.generate", reason="骨架期：generate 未实现")
        from studio.db import get_engine, init_db

        engine = get_engine(db_url)
        try:
            init_db(engine)
            tenant_id = "t_gen_ws_c"
            before = _ledger_count_for_tenant(engine, tenant_id)
            stub = _StubImageClient()
            result = generate_mod.generate(
                prompt="雨后初晴的西湖，电影感",
                style_id="cinematic",
                n=3,
                tenant_id=tenant_id,
                db_url=db_url,
                client=stub,
                size="1024x1024",
            )
            assert "winner" in result and result["winner"]
            assert len(result["candidates"]) == 3
            assert result["cost_credits"] == 15, f"计费漂移：{result.get('cost_credits')}"
            after = _ledger_count_for_tenant(engine, tenant_id)
            assert after - before == 3, "ledger 未新增 3 行赛马记账"
        finally:
            engine.dispose()

    def test_generate_without_client_raises_upstream_not_ready(self, db_url):
        generate_mod = pytest.importorskip("studio.image_forge.generate", reason="骨架期：generate 未实现")
        with pytest.raises(UpstreamNotReady):
            generate_mod.generate(
                prompt="雨后初晴的西湖",
                tenant_id="t_gen_ws_c",
                db_url=db_url,
                client=None,
            )

    def test_handle_generate_uses_ctx_client(self, db_url):
        """路由层：image_client 从 ctx 透传；成功返回统一 ok 体。"""
        pytest.importorskip("studio.image_forge.generate", reason="骨架期：generate 未实现")
        resp = handle_request(
            "POST",
            "/api/image/generate",
            {"prompt": "雨后初晴的西湖", "style_id": "cinematic", "n": 3},
            _ctx(db_url=db_url, image_client=_StubImageClient()),
        )
        assert resp["ok"] is True
        assert resp["data"]["cost_credits"] == 15
        assert len(resp["data"]["candidates"]) == 3
        assert resp["data"]["winner"]

    def test_handle_generate_bubbles_upstream_not_ready(self, db_url):
        """⭐ ctx 缺 image_client → UpstreamNotReady 冒泡 → 统一转 UPSTREAM_ERROR 错误体。"""
        pytest.importorskip("studio.image_forge.generate", reason="骨架期：generate 未实现")
        resp = handle_request(
            "POST",
            "/api/image/generate",
            {"prompt": "雨后初晴的西湖"},
            _ctx(db_url=db_url),
        )
        assert resp["ok"] is False
        assert resp["code"] == Code.UPSTREAM_ERROR


# ---------------------------------------------------------------------------
# 人物一致性（studio.image_forge.consistency，内部能力，不挂路由）
# ---------------------------------------------------------------------------


class TestConsistency:
    """人物一致性：缺失锚点跳过；observed=None 记 match=None 且不计入 mismatches。"""

    def test_build_checklist_skips_missing_anchors(self):
        consistency = pytest.importorskip("studio.image_forge.consistency", reason="骨架期：一致性模块未实现")
        character = {"name": "阿梨", "feature_anchors": {"发色": "乌黑长发", "瞳色": "琥珀色"}}
        checklist = consistency.build_checklist(character)
        text = json.dumps(checklist, ensure_ascii=False, default=str)
        assert "乌黑长发" in text and "琥珀色" in text, "现有锚点应纳入检查清单"
        assert "服装" not in text and "配饰" not in text, "缺失锚点应被跳过"

    def test_none_observed_marks_match_none_and_excluded_from_mismatches(self):
        consistency = pytest.importorskip("studio.image_forge.consistency", reason="骨架期：一致性模块未实现")
        character = {"name": "阿梨", "feature_anchors": {"发色": "乌黑长发", "瞳色": "琥珀色"}}
        # image_report 为扁平形状：{锚点名: 观察值 | None}
        image_report = {"发色": None, "瞳色": "琥珀色"}
        result = consistency.check_consistency(character, image_report)
        assert isinstance(result, dict) and "mismatches" in result
        assert "发色" not in result["mismatches"], "observed=None 不应计入 mismatches"
        items = {entry["anchor"]: entry for entry in result["items"]}
        assert items["发色"]["match"] is None, "observed=None 应记 match=None"
        assert items["瞳色"]["match"] is True, "观察值与期望一致应记 match=True"
