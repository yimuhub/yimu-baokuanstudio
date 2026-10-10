# SPDX-License-Identifier: BUSL-1.1
"""视频模型能力表（data/video_model_rules.json）参数钳制回归测试。

覆盖：规则匹配、时长钳制（最近档/区间/drop_field）、画幅字段映射、
附加请求头、轮询参数、未知模型兜底、文件缺失降级。
"""
from __future__ import annotations

import json

import pytest

from core import video_rules


@pytest.fixture(autouse=True)
def _fresh_cache():
    video_rules.clear_cache()
    yield
    video_rules.clear_cache()


def test_match_rule_known_models():
    for model, expected in [
        ("yimu_official/agnes-video-2.5-flash", "agnes-video-2.5-flash"),
        ("sora-2", "sora"),
        ("veo-3.1-generate-preview", "veo"),
        ("kling-2.6", "kling"),
        ("wan2.7-i2v-2026-04-25", "wan"),
    ]:
        r = video_rules.match_rule(model)
        assert r is not None, f"{model} 应命中规则"
        assert r["id"] == expected, f"{model} 命中了 {r['id']}，期望 {expected}"


def test_match_rule_unknown_returns_none():
    assert video_rules.match_rule("totally-unknown-model-x9") is None


def test_clamp_nearest_tier():
    # Sora：5s → 4（4/8/12 中最近档）；Kling：8s → 10
    sora = video_rules.match_rule("sora-2")
    kling = video_rules.match_rule("kling-2.6")
    assert video_rules.clamp_duration(5, sora) == 4
    assert video_rules.clamp_duration(9, sora) == 8
    assert video_rules.clamp_duration(30, sora) == 12
    assert video_rules.clamp_duration(8, kling) == 10
    assert video_rules.clamp_duration(5, kling) == 5


def test_clamp_range():
    wan = video_rules.match_rule("wan2.7-i2v-2026-04-25")
    assert video_rules.clamp_duration(30, wan) == 15   # 越上界收到 15
    assert video_rules.clamp_duration(1, wan) == 2     # 越下界收到 2
    assert video_rules.clamp_duration(8, wan) == 8     # 区间内原样


def test_clamp_drop_field_agnes():
    flash = video_rules.match_rule("agnes-video-2.5-flash")
    assert video_rules.clamp_duration(5, flash) is None  # 时长由档位决定，字段不传


def test_clamp_no_rule_passthrough():
    assert video_rules.clamp_duration(5, None) == 5


def test_aspect_payload_sora_uses_size():
    sora = video_rules.match_rule("sora-2")
    assert video_rules.aspect_payload(sora, "9:16") == {"size": "720x1280"}
    assert video_rules.aspect_payload(sora, "16:9") == {"size": "1280x720"}


def test_aspect_payload_default_format():
    # 无规则 / 非 size 字段模型：沿用 aspect_ratio + 1080 档 size
    assert video_rules.aspect_payload(None, "9:16") == {
        "aspect_ratio": "9:16", "size": "1080x1920"}
    kling = video_rules.match_rule("kling-2.6")
    out = video_rules.aspect_payload(kling, "1:1")
    assert out["aspect_ratio"] == "1:1"


def test_duration_field_names():
    assert video_rules.duration_field(video_rules.match_rule("sora-2")) == "seconds"
    assert video_rules.duration_field(video_rules.match_rule("veo-3.1")) == "durationSeconds"
    assert video_rules.duration_field(video_rules.match_rule("kling-2.6")) == "duration"
    assert video_rules.duration_field(None) == "duration"


def test_extra_headers_dashscope():
    wan = video_rules.match_rule("wan2.7-i2v-2026-04-25")
    h = video_rules.extra_headers(wan)
    assert h.get("X-DashScope-Async") == "enable"
    assert video_rules.extra_headers(None) == {}


def test_poll_params_default_and_override():
    iv, polls = video_rules.poll_params(None)
    assert (iv, polls) == (5, 120)  # 旧行为：5s × 120 次 = 10 分钟
    veo = video_rules.match_rule("veo-3.1-generate-preview")
    iv, polls = video_rules.poll_params(veo)
    assert iv == 10 and polls == 90  # 900s / 10s
    wan = video_rules.match_rule("wan2.7-t2v-2026")
    iv, polls = video_rules.poll_params(wan)
    assert iv == 15 and polls == 100  # 1500s / 15s


def test_rules_file_valid_json_and_minimal_shape():
    video_rules.clear_cache()
    data = video_rules.load_rules()
    assert data.get("version")
    for r in data["rules"]:
        assert r.get("id") and r.get("match") and r.get("protocol")


def test_rules_file_missing_degrades_gracefully(tmp_path, monkeypatch):
    # 文件缺失/损坏时：match_rule 返回 None、钳制原样放行（不炸主流程）
    video_rules.clear_cache()
    monkeypatch.setattr(video_rules, "_RULES_FILE", tmp_path / "nope.json")
    assert video_rules.match_rule("sora-2") is None
    assert video_rules.clamp_duration(8, video_rules.match_rule("sora-2")) == 8
    assert video_rules.poll_params(None) == (5, 120)


def test_ad_video_module_wires_rules(monkeypatch):
    # 编译检查 + 确认 ad_video 的 _call_video_model 引用了 video_rules
    import inspect
    import core.ad_video as av
    src = inspect.getsource(av._call_video_model)
    assert "video_rules.match_rule" in src
    assert "video_rules.clamp_duration" in src
    # 未知模型在同步分支仍传通用 duration/aspect_ratio（兼容旧网关）
    assert "aspect_payload" in src or "aspect_ratio" in src
