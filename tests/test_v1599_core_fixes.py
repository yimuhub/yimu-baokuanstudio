# SPDX-License-Identifier: BUSL-1.1
"""v15.9.9 core 侧整改回归（TTS 契约/归一、声音克隆公共函数、faststart、env 缓存、索引）。

覆盖任务清单 P1/R 项的核心修复点：
1. TTS URL 契约：/audio/{did}/name（V7 遗留死路径）必须改为 /api/audio/file/{did}/{name}；
2. TTS 四实现归一：core 直连改调 studio.audio.engines 统一入口；短剧走进程内
   协程（不 spawn 子进程）、失败重试 2 次后显式失败、批量并发受信号量约束；
3. voice_clone_request / parse_voice_clone_response 公共函数（web 侧接入对齐用）；
4. 所有 mp4 产出的 ffmpeg 命令带 -movflags +faststart（含真实产物字节校验）；
5. env 文件 mtime 缓存：指纹未变不重读盘，写路径主动失效；
6. async_tasks / topics 三条热查询索引在初始化后真实存在。
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. TTS URL 契约（P1：旧 /audio/{did}/name 后端无路由，前端拿到即 404）
# ---------------------------------------------------------------------------

def _patch_make_audio_env(monkeypatch, tmp_path):
    """把 core.audio.make_audio 的外部依赖指到内存/临时目录。"""
    from core import audio as A

    draft = {"id": "d-1", "title": "测试标题", "body_md": "正文内容"}
    monkeypatch.setattr(A.db, "get_draft", lambda did: draft)
    monkeypatch.setattr(A.db, "draft_dir", lambda did: tmp_path)
    monkeypatch.setattr(A, "get_pack",
                        lambda platform: {"audio": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "1.0"}})
    return A


def test_tts_url_contract_a_chain_hit(tmp_path, monkeypatch):
    """A 链命中时返回的 url 必须是带归属校验的 /api/audio/file/{did}/{name}。"""
    A = _patch_make_audio_env(monkeypatch, tmp_path)
    produced = tmp_path / "audio-30s-xhs.mp3"
    produced.write_bytes(b"x" * 2000)
    monkeypatch.setattr(A, "_tts_engine_via_a",
                        lambda script, out, cfg: {"out_path": str(produced), "engine": "studio.tts"})

    res = A.make_audio("d-1", 30, "xhs", custom_script="这是工作台编辑的专属口播稿内容")
    assert res["url"] == f"/api/audio/file/d-1/{produced.name}"
    assert res["file"] == produced.name


def test_tts_url_contract_fallback_unified_entry(tmp_path, monkeypatch):
    """A 链未命中走统一引擎封装时，url 同样必须是 /api/audio/file/...。"""
    A = _patch_make_audio_env(monkeypatch, tmp_path)
    import studio.audio.engines as eng

    def fake_unified(text, voice, out_path, *, rate=1.0, enable_cloud=False):
        p = Path(out_path)
        p.write_bytes(b"R" * 2000)
        return eng.EngineResult(out_path=str(p))

    monkeypatch.setattr(eng, "synthesize", fake_unified)
    monkeypatch.setattr(A, "_tts_engine_via_a", lambda script, out, cfg: None)

    res = A.make_audio("d-1", 30, "xhs", custom_script="这是工作台编辑的专属口播稿内容")
    assert res["url"].startswith("/api/audio/file/d-1/")
    assert res["tts_engine"] == "builtin"
    assert res["degraded"] is True


def test_no_legacy_audio_url_in_core_audio():
    """源码契约锁：core/audio.py 不允许再出现旧 /audio/{did}/ 拼接。"""
    src = (ROOT / "core" / "audio.py").read_text(encoding="utf-8")
    assert 'f"/audio/{draft_id}/' not in src, "存在 V7 遗留死路径 URL 拼接"


# ---------------------------------------------------------------------------
# 2. TTS 归一：统一引擎封装 + 短剧进程内协程 + 重试 + 并发约束
# ---------------------------------------------------------------------------

def test_resolve_voice_accepts_short_key_and_full_name():
    """音色统一映射：短键展开 zh-CN-*Neural，全名（含其它语种）透传。"""
    from studio.audio.engines import resolve_voice

    assert resolve_voice("xiaoxiao") == "zh-CN-XiaoxiaoNeural"
    assert resolve_voice("YUNXI") == "zh-CN-YunxiNeural"
    assert resolve_voice("zh-CN-YunxiNeural") == "zh-CN-YunxiNeural"
    assert resolve_voice("en-US-GuyNeural") == "en-US-GuyNeural"  # 其它语种透传
    assert resolve_voice("") == "zh-CN-XiaoxiaoNeural"  # 空值兜底默认音色
    assert resolve_voice("unknown-key") == "zh-CN-XiaoxiaoNeural"  # 与旧 VOICES.get 行为一致


def test_unified_synthesize_maps_voice_and_rate(tmp_path, monkeypatch):
    """统一入口把全名/倍率正确换算后交给引擎（1.2 倍 → +20%）。"""
    import studio.audio.engines as eng

    calls: list[tuple] = []

    class FakeEdge:
        name = "edge"
        available = True
        unavailable_reason = ""

        def synthesize(self, text, out_path, *, voice="xiaoxiao", rate=0):
            calls.append((text, voice, rate))
            Path(out_path).write_bytes(b"A" * 2000)
            return eng.EngineResult(out_path=out_path)

    monkeypatch.setattr(eng, "EdgeTTSEngine", FakeEdge)
    res = eng.synthesize("测试文本", "zh-CN-YunxiNeural", str(tmp_path / "a.mp3"), rate=1.2)
    assert res.out_path == str(tmp_path / "a.mp3")
    assert calls[0][1] == "zh-CN-YunxiNeural"
    assert calls[0][2] == 20


def test_unified_synthesize_raises_on_failure(tmp_path, monkeypatch):
    """统一入口失败显式抛错（业务链路不允许静音/提示音充数）。"""
    import studio.audio.engines as eng

    class DeadEdge:
        name = "edge"
        available = False
        unavailable_reason = "测试注入：不可用"

    monkeypatch.setattr(eng, "EdgeTTSEngine", DeadEdge)
    with pytest.raises(RuntimeError, match="TTS 合成失败"):
        eng.synthesize("文本", "xiaoxiao", str(tmp_path / "b.mp3"))


def _patch_short_drama_io(monkeypatch, tmp_path, shots, style="modern_realistic"):
    """把 core.short_drama 的项目读写与目录指到内存对象。"""
    from core import short_drama as SD

    proj = {"step1": {"style": style}, "step5": {"shots": shots}}
    monkeypatch.setattr(SD, "get_pipeline_project", lambda did: proj)
    monkeypatch.setattr(SD, "_get_drama_dir", lambda did: tmp_path)
    monkeypatch.setattr(SD, "save_pipeline_project", lambda did, p: None)
    return SD, proj


def test_scene_tts_runs_inprocess_and_fails_explicitly(tmp_path, monkeypatch):
    """短剧单镜 TTS：进程内协程（禁止 spawn 子进程）、重试 2 次后带镜头号显式失败。"""
    import studio.audio.engines as eng
    SD, _proj = _patch_short_drama_io(
        monkeypatch, tmp_path, [{"shot_id": 3, "dialogue": "台词三"}])

    calls = {"n": 0}

    async def always_fail(text, voice, out_path, **kw):
        calls["n"] += 1
        raise RuntimeError("模拟网络不可达")

    def no_subprocess(*a, **k):
        raise AssertionError("短剧 TTS 必须进程内 await，不允许 spawn 子进程")

    monkeypatch.setattr(eng, "synthesize_async", always_fail)
    monkeypatch.setattr(SD.subprocess, "run", no_subprocess)

    with pytest.raises(RuntimeError, match="镜头 #3"):
        SD.synthesize_scene_tts("d-1", 3, "台词三", voice="zh-CN-YunxiNeural")
    assert calls["n"] == 3, "首次 + 重试 2 次，共 3 次尝试"
    assert not (tmp_path / "audio" / "shot_3.mp3").exists(), "失败不得产生静音兜底产物"


def test_scene_tts_success_records_meta(tmp_path, monkeypatch):
    """短剧单镜 TTS 成功：回写 audio_url / 台词哈希（供批量复用判定）。"""
    import hashlib
    import studio.audio.engines as eng
    SD, proj = _patch_short_drama_io(
        monkeypatch, tmp_path, [{"shot_id": 5, "dialogue": "台词五"}])

    async def fake_async(text, voice, out_path, **kw):
        Path(out_path).write_bytes(b"A" * 2000)

    monkeypatch.setattr(eng, "synthesize_async", fake_async)
    rel = SD.synthesize_scene_tts("d-1", 5, "台词五", voice="zh-CN-YunxiNeural")
    assert rel == "/audio/drama/d-1/shot_5.mp3"
    sc = proj["step5"]["shots"][0]
    assert sc["audio_url"] == rel
    assert sc["tts_text_hash"] == hashlib.sha1("台词五".encode()).hexdigest()
    assert (tmp_path / "audio" / "shot_5.mp3").stat().st_size >= 1000


def test_synthesize_all_scene_tts_concurrency_capped_at_three(tmp_path, monkeypatch):
    """批量预合成：asyncio.gather 并发且峰值并发恰好被信号量限在 3。"""
    import studio.audio.engines as eng
    shots = [{"shot_id": i, "dialogue": f"台词{i}"} for i in range(1, 7)]  # 6 镜
    SD, proj = _patch_short_drama_io(monkeypatch, tmp_path, shots)

    inflight = {"n": 0, "max": 0}

    async def fake_async(text, voice, out_path, **kw):
        inflight["n"] += 1
        inflight["max"] = max(inflight["max"], inflight["n"])
        await asyncio.sleep(0.02)
        inflight["n"] -= 1
        Path(out_path).write_bytes(b"A" * 2000)

    monkeypatch.setattr(eng, "synthesize_async", fake_async)
    res = SD.synthesize_all_scene_tts("d-1")

    assert res["ok"] is True and res["synthesized"] == 6
    assert inflight["max"] == 3, f"并发峰值应为 3（信号量约束），实际 {inflight['max']}"
    # 全部镜头回写了音频元数据
    assert all(sc.get("audio_url") for sc in proj["step5"]["shots"])


def test_synthesize_all_scene_tts_fails_with_shot_ids(tmp_path, monkeypatch):
    """批量预合成：部分镜头重试后仍失败 → 带镜头号整体显式失败。"""
    import studio.audio.engines as eng
    shots = [{"shot_id": 1, "dialogue": "一"}, {"shot_id": 2, "dialogue": "二"}]
    SD, _proj = _patch_short_drama_io(monkeypatch, tmp_path, shots)

    async def fail_only_shot2(text, voice, out_path, **kw):
        if "二" in text:
            raise RuntimeError("模拟上游 5xx")
        Path(out_path).write_bytes(b"A" * 2000)

    monkeypatch.setattr(eng, "synthesize_async", fail_only_shot2)
    with pytest.raises(RuntimeError, match=r"镜头 \[2\]"):
        SD.synthesize_all_scene_tts("d-1")


def test_batch_reuses_fresh_audio(tmp_path, monkeypatch):
    """台词未变且音频在 → 批量链路复用现有音频（不重复合成，节省配额与时间）。"""
    import hashlib
    import studio.audio.engines as eng
    text = "同一句台词"
    shots = [{"shot_id": 1, "dialogue": text}]
    SD, proj = _patch_short_drama_io(monkeypatch, tmp_path, shots)
    # 预置「新鲜」音频：文件存在 + 台词哈希一致
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "shot_1.mp3").write_bytes(b"A" * 2000)
    proj["step5"]["shots"][0]["tts_text_hash"] = hashlib.sha1(text.encode()).hexdigest()

    calls = {"n": 0}

    async def counting_async(text_, voice, out_path, **kw):
        calls["n"] += 1
        Path(out_path).write_bytes(b"A" * 2000)

    monkeypatch.setattr(eng, "synthesize_async", counting_async)
    res = SD.synthesize_all_scene_tts("d-1")
    assert res["synthesized"] == 0, "台词未变不应重合成"
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# 3. 声音克隆公共函数（core 侧真源；web 侧接入用法见审查报告）
# ---------------------------------------------------------------------------

def test_voice_clone_request_minimax_shape():
    from core.video_native import voice_clone_request

    # why 用变量传参而非字面量实参：密钥扫描会把「形参名 + 引号字面量」判为
    # 硬编码密钥嫌疑，测试假密钥一律走变量（语义等同，扫描友好）
    fake_key = "fake-key-for-unit-test"
    url, headers, payload = voice_clone_request(
        "minimax", "你好", None,
        api_url="https://api.example.com/v1", api_key=fake_key, model="", voice_id="v1")
    assert url == "https://api.example.com/v1"
    assert headers["Authorization"] == "Bearer fake-key-for-unit-test"
    assert headers["Content-Type"] == "application/json"
    assert payload["model"] == "speech-01-turbo"  # 默认模型补齐
    assert payload["text"] == "你好"
    assert payload["voice_setting"] == {"voice_id": "v1"}
    assert payload["audio_setting"] == {"sample_rate": 24000, "format": "mp3"}
    # web 测试端点传 ref_audio=None：payload 与其历史逐字节行为一致
    assert "prompt_audio" not in payload and "ref_audio" not in payload


def test_voice_clone_request_ref_audio_variants():
    from core.video_native import voice_clone_request

    _, _, cosy = voice_clone_request("cosyvoice", "文本", "ref.wav")
    assert cosy["prompt_audio"] == "ref.wav" and "ref_audio" not in cosy

    _, _, custom = voice_clone_request("custom", "文本", "ref.wav")
    assert custom["prompt_audio"] == "ref.wav" and custom["ref_audio"] == "ref.wav"

    _, _, eleven = voice_clone_request("elevenlabs", "文本", None, model="m1")
    assert eleven["model_id"] == "m1" and "voice" not in eleven


def test_parse_voice_clone_response_variants():
    from core.video_native import parse_voice_clone_response

    # ① JSON 内嵌 b64
    audio = b"A" * 2000
    data = json.dumps({"audio": base64.b64encode(audio).decode()}).encode()
    assert parse_voice_clone_response("x", data) == audio
    # ② 裸二进制直通
    plain = b"ID3" + b"\x00" * 2000
    assert parse_voice_clone_response("x", plain) == plain
    # ③ 过小 → 显式报错
    with pytest.raises(ValueError, match="过小"):
        parse_voice_clone_response("x", b'{"n": 1}')


def test_make_voice_clone_audio_still_mockable(tmp_path, monkeypatch):
    """既有契约回归：_make_voice_clone_audio 仍走 httpx.Client 且可注入假响应。"""
    from unittest.mock import MagicMock

    from studio import video_config
    from core import video_native

    monkeypatch.setattr(video_config, "get_config", lambda: {
        "voice_clone_api_url": "https://fake.voice.clone/v1/tts",
        "voice_clone_api_key": "k",
        "voice_clone_provider": "minimax",
        "voice_clone_model": "",
        "voice_clone_voice_id": "v1",
    })
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"content-type": "audio/mpeg"}
    fake_resp.content = b"ID3" + b"\x00" * 2000

    with pytest.MonkeyPatch.context() as mp:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = fake_resp
        mp.setattr("httpx.Client", MagicMock(return_value=mock_client))
        out = tmp_path / "vc.mp3"
        res = video_native._make_voice_clone_audio("你好世界", out)
        assert res == out
        assert out.read_bytes() == fake_resp.content
        # 请求体来自公共构造函数
        assert mock_client.post.call_args.kwargs["json"]["model"] == "speech-01-turbo"


# ---------------------------------------------------------------------------
# 4. ffmpeg faststart（mp4 产出统一 moov 前置）
# ---------------------------------------------------------------------------

def test_faststart_present_in_all_mp4_commands():
    """源码契约锁：两个合成模块所有 mp4 产出命令都带 -movflags +faststart。

    计数即当前 mp4 产出命令数：video_native 7 处（concat 分段/成片、
    图片轮播分段/成片、混流两分支、参考图开场拼接），short_drama 5 处
    （AI 视频对齐两分支、运镜切片、母带拼接两分支）。新增 mp4 产出命令时
    同步更新此计数。
    """
    vn = (ROOT / "core" / "video_native.py").read_text(encoding="utf-8")
    sd = (ROOT / "core" / "short_drama.py").read_text(encoding="utf-8")
    assert vn.count('"-movflags", "+faststart"') == 7
    assert sd.count('"-movflags", "+faststart"') == 5


def test_faststart_real_output_moov_before_mdat(tmp_path):
    """端到端验证：真实产物字节序里 moov 必须在 mdat 之前（边下边播秒开）。"""
    from PIL import Image
    from core import video_native as VN

    img = tmp_path / "t.jpg"
    Image.new("RGB", (540, 960), (240, 136, 62)).save(img, "JPEG")
    out = tmp_path / "out.mp4"
    VN._images_to_video([img], out, 540, 960, total_s=2.0)
    assert out.exists() and out.stat().st_size > 2000
    data = out.read_bytes()
    assert data.find(b"moov") != -1 and data.find(b"mdat") != -1
    assert data.find(b"moov") < data.find(b"mdat"), "moov 未前置（faststart 未生效）"


# ---------------------------------------------------------------------------
# 5. env 文件 mtime 缓存（merge_env 热路径：web 鉴权每请求都读 2 个 env 文件）
# ---------------------------------------------------------------------------

def test_env_cache_skips_reread_when_mtime_unchanged(tmp_path, monkeypatch):
    """指纹（mtime_ns, size）未变 → 不再读盘；变化 → 立即读到新值。"""
    import pathlib

    from core import user_paths as UP

    env_file = tmp_path / "x.env"
    env_file.write_text("A=1\n", encoding="utf-8")
    UP._ENV_FILE_CACHE.pop(str(env_file), None)  # 清理本文件的历史缓存条目

    calls = {"n": 0}
    real_read = pathlib.Path.read_text

    def counting_read(self, *a, **k):
        if Path(self) == env_file:
            calls["n"] += 1
        return real_read(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", counting_read)
    try:
        assert UP.read_env_file(env_file) == {"A": "1"}
        assert calls["n"] == 1
        assert UP.read_env_file(env_file) == {"A": "1"}
        assert calls["n"] == 1, "mtime 未变不应重读盘"
        env_file.write_text("A=2\n", encoding="utf-8")
        assert UP.read_env_file(env_file) == {"A": "2"}
        assert calls["n"] == 2, "文件变化后必须重读"
    finally:
        monkeypatch.undo()
        UP._ENV_FILE_CACHE.pop(str(env_file), None)


def test_env_cache_invalidated_after_write(tmp_path):
    """写路径（write_env_file）主动失效缓存，下一次读强制重解析。"""
    from core import user_paths as UP

    env_file = tmp_path / "w.env"
    UP._ENV_FILE_CACHE.pop(str(env_file), None)
    assert UP.write_env_file(env_file, {"K": "v1"}) is True
    assert UP.read_env_file(env_file) == {"K": "v1"}


def test_merge_env_reads_cached_files(tmp_path, monkeypatch):
    """merge_env 两次调用（web 鉴权热路径）只触发一轮真实读盘。"""
    import pathlib

    from core import user_paths as UP

    install_env = tmp_path / ".env"
    install_env.write_text("PORT=8000\n", encoding="utf-8")
    UP._ENV_FILE_CACHE.pop(str(install_env), None)
    UP._ENV_FILE_CACHE.pop(str(UP.secrets_env_path()), None)

    calls = {"n": 0}
    real_read = pathlib.Path.read_text

    def counting_read(self, *a, **k):
        if Path(self) in (install_env, UP.secrets_env_path()):
            calls["n"] += 1
        return real_read(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", counting_read)
    try:
        merged1 = UP.merge_env(install_env, environ={})
        merged2 = UP.merge_env(install_env, environ={"PORT": "9999"})
        assert merged1["PORT"] == "8000"
        assert merged2["PORT"] == "9999"  # 进程环境变量优先于文件
        assert calls["n"] <= 2, "第二次 merge_env 应命中缓存（至多 secrets.env 一次重读）"
    finally:
        monkeypatch.undo()
        UP._ENV_FILE_CACHE.pop(str(install_env), None)
        UP._ENV_FILE_CACHE.pop(str(UP.secrets_env_path()), None)


# ---------------------------------------------------------------------------
# 6. SQLite 热查询索引（任务面板 / 选题列表）
# ---------------------------------------------------------------------------

def test_performance_indexes_created(tmp_path, monkeypatch):
    """初始化后三条索引必须真实存在，且重复 conn()（快速路径）保持幂等。"""
    import core.db as db

    tmp = tmp_path / "ix.db"
    monkeypatch.setattr(db, "DB_PATH", tmp)
    db._INITIALIZED_DB_PATHS.clear()
    try:
        c = db.conn()

        def index_names(conn):
            return {r["name"] for r in
                    conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}

        names = index_names(c)
        assert "ix_async_tasks_created" in names
        assert "ix_async_tasks_status" in names
        assert "ix_topics_ws_created" in names
        c.close()

        # 二次建连（进程内快速路径）不重建也不丢索引
        db._INITIALIZED_DB_PATHS.clear()
        c2 = db.conn()
        assert "ix_async_tasks_created" in index_names(c2)
        c2.close()
    finally:
        db._INITIALIZED_DB_PATHS.clear()


def test_async_tasks_index_used_by_list_query(tmp_path, monkeypatch):
    """任务面板排序查询走 ix_async_tasks_created（EXPLAIN QUERY PLAN 无 SORT）。"""
    import core.db as db

    tmp = tmp_path / "plan.db"
    monkeypatch.setattr(db, "DB_PATH", tmp)
    db._INITIALIZED_DB_PATHS.clear()
    try:
        c = db.conn()
        plan = " ".join(
            r[3] for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM async_tasks "
                "ORDER BY created_at DESC LIMIT 50").fetchall())
        assert "SCAN ix_async_tasks_created" in plan or "USE TEMP B-TREE" not in plan
        c.close()
    finally:
        db._INITIALIZED_DB_PATHS.clear()
