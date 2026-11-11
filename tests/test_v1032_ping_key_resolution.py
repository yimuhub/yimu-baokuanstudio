"""V10.3.2 · 供应商「测速」401 的回归测试。

背景（真实报障）：设置页编辑已有供应商时 Key 输入框是**故意清空**的
（placeholder 写着「留空则保持现有密钥不变」），但 ``ping_provider`` 直接拿
输入框的值当 Key，空值就完全不发 ``Authorization`` 头，于是
「编辑官方通道 → 点测速」必然 401：

  · 官方通道 → 401 invalid api key
  · AgnesAI  → 401 Token not provided (AgnesAI_error)

同一根因，两个上游的不同措辞。本文件锁住三件事：
  1. 空 Key 会回退到该供应商已保存的 Key；
  2. 回退**只**在 base_url 与已保存地址一致时发生（不能把 Key 送去任意地址）；
  3. 用户粘贴脏 Key（Bearer 前缀 / 引号 / 零宽字符）也能用。
"""

from __future__ import annotations

import json

import pytest

from core import llm


@pytest.fixture()
def fake_env(monkeypatch):
    """把 .env / config.yaml 换成内存里的假数据，绝不碰真实文件。"""
    env = {
        "MEDIAFLOW_APIPOOL_KEY": "ap-platform-key",
        "MEDIAFLOW_KEY_YIMU_OFFICIAL": "ap-official-key",
        "MEDIAFLOW_KEY_MYVENDOR": "sk-myvendor-key",
    }
    cfg = {
        "gateway": {
            "provider_id": "yimu_official",
            "base_url": "https://gateway.yimu.studio/v1",
            "providers": {
                "yimu_official": {"base_url": "https://gateway.yimu.studio/v1"},
                "myvendor": {"base_url": "https://api.myvendor.com/v1"},
            },
        }
    }
    monkeypatch.setattr(llm, "load_env", lambda: dict(env))
    monkeypatch.setattr(llm, "load_config", lambda: json.loads(json.dumps(cfg)))
    # V15.8.3：密钥取用已收口到 core.provider_registry，这里同步替换它的两个入口，
    # 让「已保存 Key 回退」的判定用同一份内存假数据（契约不变，只是入口换了）。
    from core import provider_registry as _reg
    monkeypatch.setattr(_reg, "env", lambda: dict(env))
    monkeypatch.setattr(_reg, "raw_config", lambda: json.loads(json.dumps(cfg)))
    return env


# ---------------------------------------------------------------------------
# clean_api_key：用户粘进来的 Key 经常带垃圾
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("  sk-abc  ", "sk-abc"),
        ('"sk-abc"', "sk-abc"),
        ("'sk-abc'", "sk-abc"),
        ("Bearer sk-abc", "sk-abc"),
        ("bearer sk-abc", "sk-abc"),
        ("Bearer  sk-abc ", "sk-abc"),
        ("sk-a\u200bb\u200bc", "sk-abc"),
        ("sk-abc\n", "sk-abc"),
        ("\u3000sk-abc", "sk-abc"),
        ("", ""),
        (None, ""),
    ],
)
def test_clean_api_key_strips_common_pollution(raw, expect):
    assert llm.clean_api_key(raw) == expect


# ---------------------------------------------------------------------------
# resolve_provider_key：空 Key 的回退规则与安全边界
# ---------------------------------------------------------------------------


def test_empty_key_falls_back_to_saved_key_for_same_endpoint(fake_env):
    key, src = llm.resolve_provider_key(
        "https://api.myvendor.com/v1", "", "myvendor"
    )
    assert (key, src) == ("sk-myvendor-key", "saved")


def test_trailing_slash_and_case_do_not_break_match(fake_env):
    key, src = llm.resolve_provider_key(
        "HTTPS://API.MYVENDOR.COM/v1/", "", "myvendor"
    )
    assert (key, src) == ("sk-myvendor-key", "saved")


def test_empty_key_does_not_fall_back_when_base_url_changed(fake_env):
    """🔴 安全：把 base_url 改成自己的服务器，不能拿到已存 Key。"""
    key, src = llm.resolve_provider_key(
        "https://evil.example.com/v1", "", "myvendor"
    )
    assert (key, src) == ("", "none")


def test_empty_key_falls_back_to_platform_key_only_on_platform_endpoint(fake_env):
    key, src = llm.resolve_provider_key("https://gateway.yimu.studio/v1", "", "")
    assert (key, src) == ("ap-platform-key", "platform")

    key, src = llm.resolve_provider_key("https://evil.example.com/v1", "", "")
    assert (key, src) == ("", "none")


def test_typed_key_always_wins(fake_env):
    key, src = llm.resolve_provider_key(
        "https://api.myvendor.com/v1", "sk-typed", "myvendor"
    )
    assert (key, src) == ("sk-typed", "input")


def test_empty_base_url_uses_saved_endpoint(fake_env):
    key, src = llm.resolve_provider_key("", "", "myvendor")
    assert (key, src) == ("sk-myvendor-key", "saved")


# ---------------------------------------------------------------------------
# ping_provider 端到端：确认真实发出的 Authorization 头
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code: int, payload: dict | str):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        return self._payload


class _FakeClient:
    """记录最后一次请求，返回预设响应。"""

    last_headers: dict = {}
    last_url: str = ""
    response: _FakeResp = _FakeResp(200, {"choices": [{"message": {"content": "hi"}}]})

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        type(self).last_url = url
        type(self).last_headers = dict(headers or {})
        return type(self).response

    def get(self, url, headers=None):
        type(self).last_url = url
        type(self).last_headers = dict(headers or {})
        return type(self).response


@pytest.fixture()
def fake_http(monkeypatch):
    monkeypatch.setattr(llm.httpx, "Client", _FakeClient)
    _FakeClient.last_headers = {}
    _FakeClient.response = _FakeResp(200, {"choices": [{"message": {"content": "pong"}}]})
    return _FakeClient


def test_ping_with_empty_key_sends_saved_key(fake_env, fake_http):
    """V10.3.2 的核心回归：编辑已有供应商、输入框留空，测速不再 401。"""
    res = llm.ping_provider(
        "https://api.myvendor.com/v1", "", "my-model", "myvendor"
    )
    assert res["ok"] is True
    assert res["key_source"] == "saved"
    assert fake_http.last_headers.get("Authorization") == "Bearer sk-myvendor-key"
    assert fake_http.last_url == "https://api.myvendor.com/v1/chat/completions"


def test_ping_with_dirty_key_is_cleaned_before_send(fake_env, fake_http):
    llm.ping_provider(
        "https://api.myvendor.com/v1", ' "Bearer sk-typed" ', "my-model", "myvendor"
    )
    assert fake_http.last_headers.get("Authorization") == "Bearer sk-typed"


def test_ping_401_without_any_key_explains_why(fake_env, fake_http):
    fake_http.response = _FakeResp(
        401, {"error": {"message": "invalid api key", "type": "auth_error"}}
    )
    res = llm.ping_provider(
        "https://evil.example.com/v1", "", "my-model", "myvendor"
    )
    assert res["ok"] is False
    assert res["key_source"] == "none"
    assert res["status_code"] == 401
    assert "没有携带 API Key" in res["hint"]


def test_ping_401_with_saved_key_points_at_the_key(fake_env, fake_http):
    fake_http.response = _FakeResp(
        401, {"error": {"message": "invalid api key", "type": "auth_error"}}
    )
    res = llm.ping_provider(
        "https://api.myvendor.com/v1", "", "my-model", "myvendor"
    )
    assert res["key_source"] == "saved"
    assert "已保存的 Key" in res["hint"]


def test_fetch_models_uses_saved_key_too(fake_env, fake_http):
    """「拉取模型列表」与「测速」必须共用同一套 Key 解析，否则同名 bug 复现。"""
    fake_http.response = _FakeResp(200, {"data": [{"id": "m-1"}]})
    res = llm.fetch_remote_models("https://api.myvendor.com/v1", "", "myvendor")
    assert res["ok"] is True
    assert res["key_source"] == "saved"
    assert fake_http.last_headers.get("Authorization") == "Bearer sk-myvendor-key"
