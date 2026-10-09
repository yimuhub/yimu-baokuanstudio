"""AI 短视频生成：分段算法 + 配置读写测试。"""
from core import ai_video_gen
from studio import ai_video_config


def test_plan_segments_60s():
    """60 秒、每段 8 秒 → 7×8 + 1×4 = 8 段。"""
    segs = ai_video_gen.plan_segments(60, 8)
    assert len(segs) == 8
    assert sum(s["dur"] for s in segs) == 60
    assert segs[-1]["dur"] == 4


def test_plan_segments_15s():
    """15 秒 → 1×8 + 1×7 = 2 段。"""
    segs = ai_video_gen.plan_segments(15, 8)
    assert len(segs) == 2
    assert sum(s["dur"] for s in segs) == 15


def test_plan_segments_exact():
    """整除：16 秒 → 2×8。"""
    segs = ai_video_gen.plan_segments(16, 8)
    assert len(segs) == 2
    assert all(s["dur"] == 8 for s in segs)


def test_plan_segments_unlimited():
    """不限时长（0）→ 单段标记。"""
    segs = ai_video_gen.plan_segments(0, 8)
    assert len(segs) == 1
    assert segs[0]["dur"] == 0


def test_estimate_seconds_from_script():
    """按脚本字数估算，向上取整到段长倍数。"""
    est = ai_video_gen._estimate_seconds_from_script("你好" * 100, 8)  # 200字→50秒→56
    assert est == 56
    assert est % 8 == 0


def test_ai_video_config_defaults():
    cfg = ai_video_config.get_config()
    assert cfg["segment_seconds"] == 8
    assert cfg["interval_seconds"] == 2
    assert cfg["max_parallel"] == 1


def test_ai_video_config_save(tmp_path, monkeypatch):
    import studio.ai_video_config as m
    monkeypatch.setattr(m, "_CONFIG_PATH", tmp_path / "ai_video_config.json")
    saved = m.save_config({"segment_seconds": 10, "max_parallel": 2})
    assert saved["segment_seconds"] == 10
    assert saved["max_parallel"] == 2
    # 非法值兜底
    saved2 = m.save_config({"segment_seconds": 999})
    assert saved2["segment_seconds"] == 30  # 上限
