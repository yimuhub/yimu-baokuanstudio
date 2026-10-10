"""AI 产品广告短片流水线测试（mock LLM，不调真实模型）。"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ad_video


def _fake_llm_selling_points(*a, **k):
    return '{"points": ["3秒速干不粘腻", "敏感肌可用", "一瓶顶三瓶"], "pain": "夏天出汗黏糊糊"}'


def _fake_llm_script(*a, **k):
    return (
        "HOOK: 还在为夏天黏腻烦恼吗？\n"
        "BODY: 3秒速干不粘腻。敏感肌可用。一瓶顶三瓶。\n"
        "CTA: 点击小黄车，把清爽带回家。\n"
        "TERMS: skincare, summer, fresh"
    )


def test_extract_selling_points():
    with patch.object(ad_video, "_llm", side_effect=_fake_llm_selling_points):
        sp = ad_video.extract_selling_points("清爽喷雾", "夏天用的喷雾")
    assert len(sp["points"]) == 3
    assert "速干" in sp["points"][0]
    assert sp["pain"]


def test_extract_selling_points_fallback():
    # LLM 返回非 JSON 时走兜底
    with patch.object(ad_video, "_llm", return_value="纯文本无JSON"):
        sp = ad_video.extract_selling_points("X", "这是描述。这是第二句。")
    assert sp["points"]


def test_generate_ad_script_format():
    with patch.object(ad_video, "_llm", side_effect=_fake_llm_script):
        sc = ad_video.generate_ad_script("清爽喷雾", ["3秒速干", "敏感肌可用"], seconds=15)
    assert sc["hook"].startswith("还在为")
    assert sc["cta"]
    assert len(sc["terms"]) >= 2
    assert "formulas" in sc
    assert sc["script"]


def test_generate_ad_script_seconds_normalize():
    with patch.object(ad_video, "_llm", side_effect=_fake_llm_script):
        sc = ad_video.generate_ad_script("X", ["卖点"], seconds=45)
    # 45 秒归一化到 30
    assert sc["script"]


def test_build_storyboard():
    sc = {"hook": "Hook文案", "body": "卖点一。卖点二。卖点三。",
          "cta": "CTA文案", "terms": [], "formulas": {}}
    shots = ad_video.build_storyboard(sc, seconds=15)
    assert shots[0]["start"] == 0 and shots[0]["dur"] == 3  # Hook 3s
    total = sum(s["dur"] for s in shots)
    assert total == 15
    assert all("voice" in s and "visual" in s for s in shots)


def test_pick_formulas():
    h, b, c = ad_video._pick_formulas("90%用户好评 限时优惠", 15)
    assert h == "惊人数据式"
    assert c == "限时优惠"


def test_make_ad_video_mocked():
    fake_res = {"mp4": "/tmp/fake.mp4", "duration_s": 9.5}
    with patch.object(ad_video, "_llm", side_effect=[_fake_llm_selling_points(),
                                                     _fake_llm_script()]):
        import core.video_native as vn
        with patch.object(vn, "make_video_native", return_value=dict(fake_res)) as m:
            # 模拟「视频大模型不可用」：不触网，走 AI 图片保底路径（测试本意）
            with patch.object(ad_video, "ad_video_model_info",
                              return_value={"ok": False, "base": "", "key": "",
                                            "model": "", "provider_id": "",
                                            "reason": "视频大模型未配置"}):
                res = ad_video.make_ad_video("清爽喷雾", "夏天喷雾", seconds=15)
    assert res["mp4"] == "/tmp/fake.mp4"
    assert res["engine"] == "ad_video_dual_agent"
    assert len(res["storyboard"]) >= 3
    assert m.called
    # 确认合成时传入的是广告脚本
    _, kw = m.call_args
    assert "还在为" in kw["script"]
    # 确认走了 AI 图片保底（视频模型不可用）
    assert res.get("fallback") is True
