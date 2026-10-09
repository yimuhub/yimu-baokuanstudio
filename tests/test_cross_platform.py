"""跨平台兼容测试：ffmpeg 指引 / Windows 无窗口 / 路径处理。"""
from pathlib import Path, PureWindowsPath
from unittest import mock

from core import video_native


def test_ffmpeg_hint_darwin():
    with mock.patch("core.video_native.platform.system", return_value="Darwin"):
        hint = video_native.ffmpeg_install_hint()
        assert "brew install ffmpeg" in hint


def test_ffmpeg_hint_windows():
    with mock.patch("core.video_native.platform.system", return_value="Windows"):
        hint = video_native.ffmpeg_install_hint()
        assert "winget" in hint or "gyan.dev" in hint


def test_ffmpeg_hint_linux():
    with mock.patch("core.video_native.platform.system", return_value="Linux"):
        hint = video_native.ffmpeg_install_hint()
        assert "apt install ffmpeg" in hint


def test_subprocess_kwargs_windows_no_window():
    with mock.patch("core.video_native.platform.system", return_value="Windows"):
        kw = video_native._subprocess_kwargs()
        # Windows 下应带 creationflags（Linux 上常量不存在，只验证非空）
        assert "creationflags" in kw and kw["creationflags"]


def test_subprocess_kwargs_posix_empty():
    with mock.patch("core.video_native.platform.system", return_value="Linux"):
        assert video_native._subprocess_kwargs() == {}
    with mock.patch("core.video_native.platform.system", return_value="Darwin"):
        assert video_native._subprocess_kwargs() == {}


def test_windows_path_handling():
    """pathlib 在 Windows 风格路径下不报错。"""
    wp = PureWindowsPath(r"C:\Users\test\runs\advideo_refs\ref_abc.jpg")
    assert wp.suffix == ".jpg"
    assert wp.name.startswith("ref_")
    # Path 拼接跨平台
    p = Path("runs") / "advideo_refs" / "ref_abc.jpg"
    assert "advideo_refs" in str(p)


def test_make_video_native_accepts_new_params():
    """make_video_native 签名包含 custom_audio / cover_images（向后兼容）。"""
    import inspect
    sig = inspect.signature(video_native.make_video_native)
    assert "custom_audio" in sig.parameters
    assert "cover_images" in sig.parameters
    # 都有默认值，老调用不受影响
    assert sig.parameters["custom_audio"].default is None
    assert sig.parameters["cover_images"].default is None


def test_ad_video_accepts_new_params():
    """make_ad_video 签名包含新参数。"""
    import inspect
    from core import ad_video
    sig = inspect.signature(ad_video.make_ad_video)
    for name in ("selling_points", "ref_images", "person_ref_image",
                 "voice_mode", "custom_audio_path"):
        assert name in sig.parameters, f"缺少参数 {name}"
    assert sig.parameters["voice_mode"].default == "auto"
