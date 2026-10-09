"""视频合成配置中心测试：配置读写、掩码显示、key 优先级。"""
import json
import os

import pytest


@pytest.fixture()
def _isolated_config(tmp_path, monkeypatch):
    """把 video_config 的存储文件隔离到 tmp，避免污染仓库 data/。"""
    import studio.video_config as vc
    fake = tmp_path / "video_config.json"
    monkeypatch.setattr(vc, "_CONFIG_PATH", fake)
    # 清环境变量，避免干扰优先级测试
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    return vc


class TestReadWrite:
    def test_defaults_when_no_file(self, _isolated_config):
        vc = _isolated_config
        cfg = vc.get_config()
        assert cfg["pexels_api_key"] == ""
        assert cfg["subtitle_enabled"] is True
        assert cfg["voice_engine"] == "tts"

    def test_save_and_reload(self, _isolated_config):
        vc = _isolated_config
        vc.save_config({"pexels_api_key": "pk-test-123", "subtitle_enabled": False})
        cfg = vc.get_config()
        assert cfg["pexels_api_key"] == "pk-test-123"
        assert cfg["subtitle_enabled"] is False
        # 文件真实落盘
        raw = json.loads(vc._CONFIG_PATH.read_text(encoding="utf-8"))
        assert raw["pexels_api_key"] == "pk-test-123"

    def test_unknown_fields_ignored(self, _isolated_config):
        vc = _isolated_config
        cfg = vc.save_config({"not_a_field": 1, "pixabay_api_key": "px-1"})
        assert "not_a_field" not in cfg
        assert cfg["pixabay_api_key"] == "px-1"

    def test_invalid_voice_engine_rejected(self, _isolated_config):
        vc = _isolated_config
        with pytest.raises(ValueError):
            vc.save_config({"voice_engine": "nope"})

    def test_valid_voice_engines(self, _isolated_config):
        vc = _isolated_config
        for eng in ("tts", "voice_clone", "local_model"):
            assert vc.save_config({"voice_engine": eng})["voice_engine"] == eng


class TestMask:
    def test_mask_long(self, _isolated_config):
        assert _isolated_config.mask_key("abcdef123456") == "abc***456"

    def test_mask_empty(self, _isolated_config):
        assert _isolated_config.mask_key("") == ""

    def test_mask_short(self, _isolated_config):
        assert _isolated_config.mask_key("12345678") == "***"

    def test_masked_config_hides_keys(self, _isolated_config):
        vc = _isolated_config
        vc.save_config({"pexels_api_key": "pk-secret-999", "voice_clone_api_key": "vc-k"})
        m = vc.get_masked_config()
        assert m["pexels_api_key"] == "pk-***999"
        assert "pk-secret-999" not in json.dumps(m)
        # 非 key 字段不受影响
        assert m["subtitle_enabled"] is True


class TestKeyPriority:
    """配置 > 环境变量。"""

    def test_config_beats_env(self, _isolated_config, monkeypatch):
        vc = _isolated_config
        monkeypatch.setenv("PEXELS_API_KEY", "env-key-aaa")
        assert vc.get_pexels_key() == "env-key-aaa"  # 无配置时用环境变量
        vc.save_config({"pexels_api_key": "cfg-key-bbb"})
        assert vc.get_pexels_key() == "cfg-key-bbb"  # 有配置时配置优先

    def test_env_fallback_pixabay(self, _isolated_config, monkeypatch):
        vc = _isolated_config
        monkeypatch.setenv("PIXABAY_API_KEY", "px-env")
        assert vc.get_pixabay_key() == "px-env"

    def test_delete_key(self, _isolated_config):
        vc = _isolated_config
        vc.save_config({"pexels_api_key": "to-delete"})
        vc.delete_key("pexels")
        assert vc.get_config()["pexels_api_key"] == ""

    def test_delete_key_bad_provider(self, _isolated_config):
        vc = _isolated_config
        with pytest.raises(ValueError):
            vc.delete_key("unknown")


class TestEngineDefaults:
    def test_subtitle_default_true(self, _isolated_config):
        assert _isolated_config.get_subtitle_enabled() is True

    def test_voice_engine_default_tts(self, _isolated_config):
        assert _isolated_config.get_voice_engine() == "tts"

    def test_voice_engine_bad_value_falls_back(self, _isolated_config, tmp_path, monkeypatch):
        import studio.video_config as vc
        # 直接写坏值进文件，get 应兜底
        vc._CONFIG_PATH.write_text(json.dumps({"voice_engine": "bad"}), encoding="utf-8")
        assert vc.get_voice_engine() == "tts"


class TestMaterialMode:
    """素材模式：stock_only / ai_only / mixed（默认）。"""

    def test_default_mixed(self, _isolated_config):
        vc = _isolated_config
        assert vc.get_config()["material_mode"] == "mixed"
        assert vc.get_material_mode() == "mixed"

    def test_save_valid_modes(self, _isolated_config):
        vc = _isolated_config
        for m in ("stock_only", "ai_only", "mixed"):
            cfg = vc.save_config({"material_mode": m})
            assert cfg["material_mode"] == m
            assert vc.get_material_mode() == m

    def test_invalid_mode_rejected(self, _isolated_config):
        vc = _isolated_config
        with pytest.raises(ValueError):
            vc.save_config({"material_mode": "nope"})

    def test_bad_value_in_file_falls_back(self, _isolated_config):
        import studio.video_config as vc
        vc._CONFIG_PATH.write_text(
            json.dumps({"material_mode": "bad"}), encoding="utf-8")
        assert vc.get_material_mode() == "mixed"
        # get_config 也兜底
        assert vc.get_config()["material_mode"] == "mixed"

    def test_masked_config_includes_material_mode(self, _isolated_config):
        vc = _isolated_config
        vc.save_config({"material_mode": "ai_only"})
        m = vc.get_masked_config()
        assert m["material_mode"] == "ai_only"
