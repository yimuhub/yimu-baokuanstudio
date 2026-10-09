"""V7 原生视频引擎测试：stock 降级、ffmpeg 可用性、端到端合成。"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


class TestStockGracefulDegradation:
    """无 API key 时优雅降级，不抛异常。"""

    def test_no_keys_returns_empty(self, monkeypatch):
        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
        # 确保环境变量确实为空
        os.environ.pop("PEXELS_API_KEY", None)
        os.environ.pop("PIXABAY_API_KEY", None)
        from studio import stock
        # 不应抛异常
        assert stock.search_videos("test", n=1) == []
        assert stock.search_images("test", n=1) == []

    def test_stock_available_reports(self):
        from studio import stock
        st = stock.stock_available()
        assert "pexels" in st and "pixabay" in st
        assert isinstance(st["pexels"], bool)


class TestFfmpeg:
    def test_ffmpeg_available(self):
        from core import video_native
        assert video_native.ffmpeg_available(), "测试环境需要 ffmpeg"

    def test_ffprobe_reads_duration(self, tmp_path):
        from core import video_native
        # 生成 2 秒测试视频
        mp4 = tmp_path / "t.mp4"
        subprocess.run(
            [shutil.which("ffmpeg"), "-y", "-f", "lavfi",
             "-i", "color=c=black:s=320x240:d=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)],
            capture_output=True, check=True, timeout=60)
        dur = video_native._probe_duration(mp4)
        assert 1.5 < dur < 2.5, f"时长读取异常: {dur}"


class TestNativeSynthesis:
    """端到端：1 张测试图 + 静音 → 3 秒 mp4，ffprobe 验证。"""

    def test_image_to_video_no_audio(self, tmp_path):
        from PIL import Image
        from core import video_native

        # 1 张测试图
        img = tmp_path / "test.jpg"
        Image.new("RGB", (540, 960), (240, 136, 62)).save(img, "JPEG")

        work = tmp_path / "work"
        work.mkdir()
        out = work / "out.mp4"
        # 每张图 3 秒 → 总 3 秒
        video_native._images_to_video([img], out, 540, 960, total_s=3.0)

        assert out.exists() and out.stat().st_size > 5000
        dur = video_native._probe_duration(out)
        assert 2.5 < dur < 3.5, f"合成时长异常: {dur}"

    def test_title_card_generation(self, tmp_path):
        from core import video_native
        card = tmp_path / "card.jpg"
        video_native._make_title_card("测试标题", "副标题", card, 540, 960)
        assert card.exists() and card.stat().st_size > 5000

    def test_srt_generation(self, tmp_path):
        from core import video_native
        srt = tmp_path / "t.srt"
        video_native._script_to_srt("第一句。第二句！第三句？", 9.0, srt)
        text = srt.read_text(encoding="utf-8")
        assert "第一句" in text and "第三句" in text
        assert "-->" in text

    def test_mux_silent_video(self, tmp_path):
        """无音频时输出无声视频不抛异常。"""
        from PIL import Image
        from core import video_native

        img = tmp_path / "test.jpg"
        Image.new("RGB", (540, 960), (30, 30, 40)).save(img, "JPEG")
        work = tmp_path / "work"
        work.mkdir()
        base = work / "base.mp4"
        video_native._images_to_video([img], base, 540, 960, total_s=3.0)

        srt = work / "s.srt"
        video_native._script_to_srt("测试字幕。", 3.0, srt)
        final = work / "final.mp4"
        # audio=None → 无声输出
        video_native._mux_audio_subtitle(base, None, srt, final, 3.0)
        assert final.exists()
        dur = video_native._probe_duration(final)
        assert 2.5 < dur < 3.5

    def test_no_ffmpeg_raises_friendly(self, monkeypatch):
        """ffmpeg 不可用时抛友好错误（而非裸 subprocess 报错）。"""
        from core import video_native
        monkeypatch.setattr(video_native, "_FFMPEG", None)
        monkeypatch.setattr(video_native, "ffmpeg_available", lambda: False)
        with pytest.raises(RuntimeError, match="ffmpeg"):
            video_native.make_video_native("测试文案", work_dir="/tmp/vn-noffmpeg-test")
