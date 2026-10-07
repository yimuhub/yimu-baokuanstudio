# SPDX-License-Identifier: BUSL-1.1
"""网关链路测试：发 Key → 鉴权 → 调用 → 记账 → 管理接口。

覆盖：Key 发放一次性明文、chat 非流记账、SSE 流、图片/向量/模型列表、
鉴权失败码、限速 429、账本分页与过滤、上游手动下线、yimu-auto 别名。
"""
# ⭐ 环境变量必须在任何 studio / gateway import 之前就绪
import os

os.environ.setdefault("YIMU_SECRET_KEY", "test-secret-ws-b")
os.environ.setdefault("YIMU_UPSTREAM_ECHO", "1")
os.environ.setdefault("YIMU_ADMIN_KEY", "test-admin-key-wsb-2026")

from tests.wsb_common import (  # noqa: E402
    admin_headers,
    gw_client,
    issue_gateway_key,
    make_tenant_stack,
    test_env,
    unique_name,
)

CHAT_BODY = {
    "model": "yimu-chat",
    "messages": [{"role": "user", "content": "你好，请介绍一下自己"}],
}


def _key_headers(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


def test_issue_key_plaintext_once_and_chat_writes_two_ledger_rows(
    db_session, gw_client
):
    """发 Key 明文只返回一次；chat 成功后账本恰好落 input/output 两行。"""
    stack = make_tenant_stack(db_session, unique_name("gw-ledger"))
    issued = issue_gateway_key(gw_client, stack["tenant_id"], stack["user_id"])
    data = issued["data"]

    # 明文只在发放响应里出现一次
    assert data["key"].startswith("yimu_sk_"), "发放响应应携带明文 Key"
    assert data["key_prefix"] == data["key"][:12], "前缀应与明文前 12 位一致"

    # 列表接口：无明文、无哈希，只有可展示的前缀
    resp = gw_client.get(
        "/api/gw/keys", headers=admin_headers(),
        params={"tenant_id": stack["tenant_id"]},
    )
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert "key" not in item, "列表接口不得返回明文 Key"
    assert "key_hash" not in item, "列表接口不得返回 Key 哈希"
    assert item["key_prefix"] == data["key_prefix"]

    # chat 非流成功
    resp = gw_client.post(
        "/v1/chat/completions", headers=_key_headers(issued["raw"]), json=CHAT_BODY
    )
    assert resp.status_code == 200, f"chat 失败：{resp.text[:300]}"
    body = resp.json()
    assert body["choices"][0]["message"]["content"], "应答内容不应为空"
    assert body["usage"]["total_tokens"] > 0

    # 账本恰好 2 行：input + output，租户归属正确
    resp = gw_client.get(
        "/api/gw/ledger",
        headers=admin_headers(),
        params={"tenant_id": stack["tenant_id"]},
    )
    assert resp.status_code == 200
    ledger = resp.json()["data"]
    assert ledger["total"] == 2, f"一次调用应恰好产生 2 行账本，实际 {ledger['total']}"
    directions = {row["direction"] for row in ledger["items"]}
    assert directions == {"input", "output"}, f"账本方向应为 input/output，实际 {directions}"
    for row in ledger["items"]:
        assert row["tenant_id"] == stack["tenant_id"], "账本行租户归属错误"


def test_chat_sse_stream_ends_with_done(db_session, gw_client):
    """SSE 流：收到 data: 数据块，并以 data: [DONE] 收尾。"""
    stack = make_tenant_stack(db_session, unique_name("gw-sse"))
    issued = issue_gateway_key(gw_client, stack["tenant_id"], stack["user_id"])
    body = dict(CHAT_BODY)
    body["stream"] = True
    with gw_client.stream(
        "POST", "/v1/chat/completions",
        headers=_key_headers(issued["raw"]), json=body,
    ) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert "data:" in text, "流式响应应包含 data: 数据块"
    assert text.rstrip().endswith("data: [DONE]"), "流式响应应以 data: [DONE] 结束"


def test_images_embeddings_models_and_unknown_model(db_session, gw_client):
    """图片 n 越界 400；n=2 成功；向量成功；模型列表含能力与单价；未知模型 400。"""
    stack = make_tenant_stack(db_session, unique_name("gw-multi"))
    issued = issue_gateway_key(gw_client, stack["tenant_id"], stack["user_id"])
    headers = _key_headers(issued["raw"])

    resp = gw_client.post(
        "/v1/images/generations", headers=headers,
        json={"model": "yimu-image", "prompt": "一只橘猫", "n": 5},
    )
    assert resp.status_code == 400, f"n=5 应被拒绝，实际 {resp.status_code}"

    resp = gw_client.post(
        "/v1/images/generations", headers=headers,
        json={"model": "yimu-image", "prompt": "一只橘猫", "n": 2},
    )
    assert resp.status_code == 200, f"n=2 应成功：{resp.text[:300]}"
    assert len(resp.json()["data"]) == 2, "应返回 2 张图片"

    resp = gw_client.post(
        "/v1/embeddings", headers=headers,
        json={"model": "yimu-embed", "input": "你好世界"},
    )
    assert resp.status_code == 200, f"向量接口应成功：{resp.text[:300]}"
    assert resp.json()["data"], "向量结果不应为空"

    resp = gw_client.get("/v1/models", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["data"]["data"]
    assert items, "模型列表不应为空"
    for item in items:
        assert "capabilities" in item and "pricing" in item, "模型条目应含能力标签与单价"
    assert any(i["id"] == "yimu-chat" for i in items), "模型列表应包含 yimu-chat"

    resp = gw_client.post(
        "/v1/chat/completions", headers=headers,
        json={"model": "no-such-model-xyz",
              "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 400, f"未知模型应 400，实际 {resp.status_code}"


def test_yimu_auto_alias_resolves(db_session, gw_client):
    """yimu-auto 别名：自动选到可用通道，调用成功。"""
    stack = make_tenant_stack(db_session, unique_name("gw-auto"))
    issued = issue_gateway_key(gw_client, stack["tenant_id"], stack["user_id"])
    resp = gw_client.post(
        "/v1/chat/completions", headers=_key_headers(issued["raw"]),
        json={"model": "yimu-auto",
              "messages": [{"role": "user", "content": "别名测试"}]},
    )
    assert resp.status_code == 200, f"yimu-auto 应可用：{resp.text[:300]}"
    assert resp.json()["choices"][0]["message"]["content"]


def test_invalid_and_revoked_keys(db_session, gw_client):
    """无效 Key → 401；吊销后 → 403。"""
    stack = make_tenant_stack(db_session, unique_name("gw-auth"))
    issued = issue_gateway_key(gw_client, stack["tenant_id"], stack["user_id"])

    resp = gw_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer yimu_sk_notarealkey000"},
        json=CHAT_BODY,
    )
    assert resp.status_code == 401, f"无效 Key 应 401，实际 {resp.status_code}"
    assert resp.json()["code"] == "UNAUTHORIZED"

    resp = gw_client.delete(
        f"/api/gw/keys/{issued['id']}", headers=admin_headers()
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "revoked"

    resp = gw_client.post(
        "/v1/chat/completions", headers=_key_headers(issued["raw"]), json=CHAT_BODY
    )
    assert resp.status_code == 403, f"吊销 Key 应 403，实际 {resp.status_code}"
    assert resp.json()["code"] == "FORBIDDEN"


def test_rpm_limit_returns_429_with_retry_info(db_session, gw_client):
    """rpm 限速：超限 → 429，且响应体带 retry_after 与 credits_left。"""
    stack = make_tenant_stack(db_session, unique_name("gw-rpm"))
    issued = issue_gateway_key(
        gw_client, stack["tenant_id"], stack["user_id"], rate_limit_rpm=1
    )
    headers = _key_headers(issued["raw"])
    first = gw_client.post("/v1/chat/completions", headers=headers, json=CHAT_BODY)
    assert first.status_code == 200, "首次调用应成功"
    second = gw_client.post("/v1/chat/completions", headers=headers, json=CHAT_BODY)
    assert second.status_code == 429, f"超 rpm 应 429，实际 {second.status_code}"
    body = second.json()
    assert body["code"] == "QUOTA_EXCEEDED"
    assert "retry_after" in body and body["retry_after"] > 0, "429 应带退避秒数"
    assert "credits_left" in body, "429 应带剩余额度"


def test_admin_ledger_pagination_and_model_filter(db_session, gw_client):
    """账本管理接口：分页结构 {items,total,page,page_size}；按 model 过滤。"""
    stack = make_tenant_stack(db_session, unique_name("gw-page"))
    issued = issue_gateway_key(gw_client, stack["tenant_id"], stack["user_id"])
    headers = _key_headers(issued["raw"])
    assert gw_client.post(
        "/v1/chat/completions", headers=headers, json=CHAT_BODY
    ).status_code == 200

    params = {"tenant_id": stack["tenant_id"], "page": 1, "page_size": 1}
    resp = gw_client.get("/api/gw/ledger", headers=admin_headers(), params=params)
    assert resp.status_code == 200
    page = resp.json()["data"]
    assert page["total"] == 2
    assert page["page"] == 1 and page["page_size"] == 1
    assert len(page["items"]) == 1, "page_size=1 应只返回 1 行"

    resp = gw_client.get(
        "/api/gw/ledger",
        headers=admin_headers(),
        params={"tenant_id": stack["tenant_id"], "model": "yimu-chat"},
    )
    filtered = resp.json()["data"]
    assert filtered["total"] == 2
    assert all(r["model"] == "yimu-chat" for r in filtered["items"])

    resp = gw_client.get(
        "/api/gw/ledger",
        headers=admin_headers(),
        params={"tenant_id": stack["tenant_id"], "model": "yimu-image"},
    )
    assert resp.json()["data"]["total"] == 0, "未调用过的模型过滤结果应为空"


def test_upstream_toggle_offline_then_chat_502(db_session, gw_client):
    """上游手动下线后，chat 应返回 502（通道不可用）。"""
    stack = make_tenant_stack(db_session, unique_name("gw-toggle"))
    issued = issue_gateway_key(gw_client, stack["tenant_id"], stack["user_id"])

    resp = gw_client.get("/api/gw/upstreams", headers=admin_headers())
    assert resp.status_code == 200
    assert any(u["id"] == "echo" for u in resp.json()["data"]["data"])

    resp = gw_client.post(
        "/api/gw/upstreams/echo/toggle",
        headers=admin_headers(),
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False

    resp = gw_client.post(
        "/v1/chat/completions", headers=_key_headers(issued["raw"]), json=CHAT_BODY
    )
    assert resp.status_code == 502, f"上游下线后应 502，实际 {resp.status_code}"
    assert resp.json()["code"] == "UPSTREAM_ERROR"
