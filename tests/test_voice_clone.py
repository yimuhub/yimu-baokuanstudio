"""Unit tests for voice cloning configuration and client handling."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from studio import video_config
from core import video_native


def test_video_config_voice_clone_fields(tmp_path, monkeypatch):
    test_cfg_file = tmp_path / "ai_video_config.json"
    monkeypatch.setattr(video_config, "_CONFIG_PATH", test_cfg_file)

    cfg = video_config.get_config()
    assert cfg["voice_clone_provider"] == "custom"
    assert "voice_clone_model" in cfg

    # 保存配置
    saved = video_config.save_config({
        "voice_clone_provider": "minimax",
        "voice_clone_model": "speech-01-turbo",
        "voice_clone_voice_id": "female_host_01",
        "voice_clone_api_url": "https://api.minimax.chat/v1/t2a_v2",
        "voice_clone_api_key": "secret_key_12345"
    })
    assert saved["voice_clone_provider"] == "minimax"
    masked = video_config.get_masked_config()
    assert masked["voice_clone_api_key"] == "sec***345"  # 掩码

    # 重新加载
    reloaded = video_config.get_config()
    assert reloaded["voice_clone_api_key"] == "secret_key_12345"
    assert reloaded["voice_clone_model"] == "speech-01-turbo"


def test_make_voice_clone_audio_mock(tmp_path, monkeypatch):
    out_mp3 = tmp_path / "clone_test.mp3"

    # 1. 未配置 URL 时降级
    monkeypatch.setattr(video_config, "get_config", lambda: {"voice_clone_api_url": ""})
    res = video_native._make_voice_clone_audio("测试口播", out_mp3)
    assert res is None

    # 2. 配置了 URL 并且 mock 返回成功二进制
    monkeypatch.setattr(video_config, "get_config", lambda: {
        "voice_clone_api_url": "https://fake.voice.clone/v1/tts",
        "voice_clone_api_key": "fake_key",
        "voice_clone_provider": "minimax",
        "voice_clone_model": "speech-01-turbo",
        "voice_clone_voice_id": "v1"
    })

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"content-type": "audio/mpeg"}
    fake_resp.content = b"ID3" + b"\x00" * 2000  # 合法音频数据伪装（大于 1000 字节）

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = fake_resp
        mock_client_cls.return_value = mock_client

        res = video_native._make_voice_clone_audio("你好世界", out_mp3)
        assert res == out_mp3
        assert out_mp3.exists()
        assert out_mp3.read_bytes() == fake_resp.content
