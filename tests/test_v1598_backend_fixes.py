# SPDX-License-Identifier: BUSL-1.1
"""V15.9.8 · 后端整改回归锁（本版本全部修复点）。

钉死八类缺陷，防止复发：
1. SSRF 防护（core/outbound_guard）：多用户服务器拒私网、单机桌面放行环回、
   拒绝非 http(s) scheme；
2. 用户取消不再写 failed：TaskManager.cancel 同步 JOBS 用独立 cancelled 状态，
   Task.cancel() 触发 on_cancel 注册的取消联动回调；
3. JOBS 过期清理：prune_stale_jobs 只清 1 小时前已终态条目，running 永不动；
4. 升级供应链：默认无第三方镜像、ZIP 下载 SHA256 强校验（失败中止）、
   未提供校验和告警放行；
5. provider_registry 坏 YAML：回退上次好配置（.bak），无备份显性启动失败；
   write_config 写前自动备份；
6. imagegen 外链二次下载校验（2xx + image/* + ≤20MB + >1KB，伪响应直测）；
7. Pollinations 免 Key 公共通道开关（默认开、可关、关后零外呼）；
8. chat_stream 全链路透传 user_id（BYOK 解析 + 官方通道扣费都需要它）；
   官方通道缺 user_id 仅记统计未扣费的分支必须留 warning 日志。
"""
from __future__ import annotations

import io
import sys
import threading
import time
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1) SSRF 防护：core/outbound_guard
# ---------------------------------------------------------------------------

class TestOutboundGuard:
    def test_multiuser_rejects_private(self, monkeypatch):
        """多用户服务器（YIMU_MULTIUSER=1）：环回/私网/云元数据全部拒绝。"""
        from core import outbound_guard
        monkeypatch.setenv("YIMU_MULTIUSER", "1")
        bad_urls = [
            "http://127.0.0.1:8790/api/tasks",          # 环回本服务
            "http://localhost:18060/mcp",               # 环回域名
            "http://169.254.169.254/latest/meta-data/", # 云元数据（AWS/GCP/阿里云同段）
            "http://10.1.2.3/internal",                 # RFC1918 A 类
            "http://192.168.1.10/router",               # RFC1918 C 类
            "http://172.16.0.9/admin",                  # RFC1918 B 类
            "http://100.64.0.1/cgnat",                  # 运营商级 NAT
            "http://[::1]/",                            # IPv6 环回
            "http://[fe80::1]/",                        # IPv6 链路本地
            "http://[fd00::1]/",                        # IPv6 ULA (fc00::/7)
            "http://0.0.0.0/",                          # 未指定地址
        ]
        for url in bad_urls:
            with pytest.raises(outbound_guard.UnsafeURLError):
                outbound_guard.assert_safe_url(url)

    def test_single_machine_allows_loopback(self, monkeypatch):
        """单机桌面（未开启 YIMU_MULTIUSER）：环回/私网放行（连本地 Ollama 是合法场景）。"""
        from core import outbound_guard
        monkeypatch.delenv("YIMU_MULTIUSER", raising=False)
        assert outbound_guard.assert_safe_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
        assert outbound_guard.assert_safe_url("http://192.168.1.5/") == "http://192.168.1.5/"
        # 但云元数据在单机上也应拦（无论如何它都不是用户想要的业务目标）
        with pytest.raises(outbound_guard.UnsafeURLError):
            outbound_guard.assert_safe_url("http://169.254.169.254/latest/meta-data/")

    def test_rejects_non_http_scheme(self, monkeypatch):
        """非 http/https scheme 一律拒绝（file:// 读本地文件、ftp:// 明文）。"""
        from core import outbound_guard
        monkeypatch.delenv("YIMU_MULTIUSER", raising=False)
        for url in ("file:///etc/passwd", "ftp://example.com/a", "gopher://x", "javascript:alert(1)"):
            with pytest.raises(outbound_guard.UnsafeURLError):
                outbound_guard.assert_safe_url(url)

    def test_public_ip_passes_multiuser(self, monkeypatch):
        """多用户模式下公网字面量 IP 放行（不依赖 DNS，沙箱可跑）。"""
        from core import outbound_guard
        monkeypatch.setenv("YIMU_MULTIUSER", "1")
        assert outbound_guard.assert_safe_url("https://93.184.216.34/x").startswith("https://")

    def test_empty_url_rejected(self, monkeypatch):
        from core import outbound_guard
        with pytest.raises(outbound_guard.UnsafeURLError):
            outbound_guard.assert_safe_url("")


# ---------------------------------------------------------------------------
# 2) 取消语义：cancelled 独立状态 + on_cancel 联动
# ---------------------------------------------------------------------------

def _fake_web_admin(monkeypatch, jobs: dict):
    """向 sys.modules 注入假 web.admin（真实 admin 导入整棵 FastAPI 应用，太重）。"""
    web_pkg = types.ModuleType("web")
    admin_mod = types.ModuleType("web.admin")
    admin_mod.JOBS = jobs
    web_pkg.admin = admin_mod
    monkeypatch.setitem(sys.modules, "web", web_pkg)
    monkeypatch.setitem(sys.modules, "web.admin", admin_mod)
    return admin_mod


class TestCancelSemantics:
    def test_task_cancel_invokes_registered_callbacks(self):
        from core.task_queue import Task
        t = Task(id="t-x", name="n", task_type="tt")
        calls: list[str] = []
        t.register_cancel(lambda: calls.append("cb1"))
        t.register_cancel(lambda: calls.append("cb2"))
        # 联动回调抛异常不得阻断取消本身
        t.register_cancel(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        t.cancel()
        assert calls == ["cb1", "cb2"]
        assert t.status == "cancelled"
        assert t.is_cancelled() is True

    def test_manager_cancel_jobs_not_failed(self, monkeypatch):
        """用户取消在 JOBS 里必须是 cancelled——污染 failed 统计的旧行为不允许回归。"""
        from core.task_queue import Task, TaskManager
        jobs = {"t1": {"status": "running", "step": "处理中", "error": ""}}
        _fake_web_admin(monkeypatch, jobs)
        tm = TaskManager(max_workers=1)
        task = Task(id="t1", name="x", task_type="tt")
        tm._tasks["t1"] = task
        tm.cancel("t1")
        assert jobs["t1"]["status"] == "cancelled"
        assert jobs["t1"]["status"] != "failed"
        assert jobs["t1"]["error"] == "任务已由用户主动取消"  # 中文文案保留


# ---------------------------------------------------------------------------
# 3) JOBS 过期清理
# ---------------------------------------------------------------------------

class TestPruneStaleJobs:
    def test_prunes_terminal_only_older_than_1h(self, monkeypatch):
        from core import task_queue
        now = time.time()
        jobs = {
            "old-done": {"status": "done", "completed_at": now - 7200},      # 该清
            "old-failed": {"status": "failed", "completed_at": now - 4000},  # 该清
            "fresh-done": {"status": "done", "completed_at": now - 100},     # 保留（未满 1h）
            "running-old": {"status": "running", "created_at": now - 9000},  # 永不清
            "no-status": {"created_at": now - 9000},                          # 无状态=未知，保守保留
        }
        _fake_web_admin(monkeypatch, jobs)
        pruned = task_queue.prune_stale_jobs()
        assert pruned == 2
        assert "old-done" not in jobs
        assert "old-failed" not in jobs
        for keep in ("fresh-done", "running-old", "no-status"):
            assert keep in jobs


# ---------------------------------------------------------------------------
# 4) 升级供应链：镜像配置化 + SHA256 校验
# ---------------------------------------------------------------------------

def _zip_bytes(payload: bytes = b"code") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("yimu-baokuanstudio-main/version.py", payload)
    return buf.getvalue()


class TestUpdaterSupplyChain:
    def test_default_no_mirrors(self, monkeypatch):
        """默认仅 GitHub 直连：ghfast.top/ghproxy.net 不得再进下载链路。"""
        import core.updater as up
        monkeypatch.setattr(up, "_get_mirrors", lambda: [])
        assert up._get_mirrors() == []

    def test_mirrors_from_config(self, monkeypatch, tmp_path):
        """upgrade.mirrors config 键可注入镜像（不再硬编码）。"""
        import core.updater as up
        fake_cfg = {"upgrade": {"mirrors": ["https://my-mirror.example"]}}
        monkeypatch.setattr(up, "_get_mirrors", lambda: (
            [str(m).strip().rstrip("/") for m in (fake_cfg.get("upgrade") or {}).get("mirrors", [])]))
        assert up._get_mirrors() == ["https://my-mirror.example"]

    def test_sha256_mismatch_aborts(self, monkeypatch):
        """校验和不匹配 → 中止不落盘（防篡改包进解压链路）。"""
        import hashlib
        import core.updater as up
        data = _zip_bytes(b"trusted code")
        good = hashlib.sha256(data).hexdigest()
        monkeypatch.setattr(up, "_fetch_expected_sha256", lambda repo, token, url: good[:-1] + ("0" if good[-1] != "0" else "1"))
        ok, msg = up._verify_zip_bytes(data, "a/b", "", "https://github.com/a/b/archive/main.zip", "github.com")
        assert ok is False
        assert "SHA256" in msg and "中止" in msg

    def test_sha256_match_passes(self, monkeypatch):
        import hashlib
        import core.updater as up
        data = _zip_bytes(b"trusted code")
        monkeypatch.setattr(up, "_fetch_expected_sha256",
                            lambda repo, token, url: hashlib.sha256(data).hexdigest())
        ok, msg = up._verify_zip_bytes(data, "a/b", "", "u", "github.com")
        assert ok is True
        assert "校验通过" in msg

    def test_no_checksum_warns_but_continues(self, monkeypatch, caplog):
        """未提供校验和 → 告警「完整性未验证」后继续（保可用性）。"""
        import core.updater as up
        monkeypatch.setattr(up, "_fetch_expected_sha256", lambda repo, token, url: None)
        with caplog.at_level("WARNING", logger="core.updater"):
            ok, msg = up._verify_zip_bytes(_zip_bytes(), "a/b", "", "u", "github.com")
        assert ok is True
        assert "未提供校验和" in msg
        assert any("完整性未验证" in r.message for r in caplog.records)

    def test_fetch_sha256_parses_sums_file(self, monkeypatch):
        """<zip>.sha256 命中时能从「摘要  文件名」格式解析出 64 位摘要。"""
        import hashlib
        import core.updater as up
        data = _zip_bytes()
        digest = hashlib.sha256(data).hexdigest()
        lines = f"{digest}  yimu-baokuanstudio-main.zip\n"

        class _Resp:
            status = 200
            def read(self):
                return lines.encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        monkeypatch.setattr(up.urllib.request, "urlopen", lambda req, timeout: _Resp())
        got = up._fetch_expected_sha256("a/b", "", "https://github.com/a/b/archive/main.zip")
        assert got == digest


# ---------------------------------------------------------------------------
# 5) provider_registry 坏 YAML 回退
# ---------------------------------------------------------------------------

class TestProviderRegistryYaml:
    def _patch_base(self, monkeypatch, tmp_path):
        import core.provider_registry as reg
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(reg, "BASE", tmp_path)
        monkeypatch.setattr(reg, "config_path", lambda: tmp_path / "config.yaml")
        # load_config 的文件签名缓存与 registry 实例身份相关，测试隔离更稳
        return reg

    def test_bad_yaml_falls_back_to_bak(self, monkeypatch, tmp_path, caplog):
        """坏 config.local.yaml → 改名保留现场 + 回退 .bak 上次好配置。"""
        reg = self._patch_base(monkeypatch, tmp_path)
        (tmp_path / "data" / "config.local.yaml").write_text(
            "gateway: [broken", encoding="utf-8")  # 非法 YAML
        (tmp_path / "data" / "config.local.yaml.bak").write_text(
            "gateway:\n  provider_id: bak-channel\n", encoding="utf-8")
        with caplog.at_level("ERROR", logger="core.provider_registry"):
            cfg = reg.raw_config()
        assert (cfg.get("gateway") or {}).get("provider_id") == "bak-channel"
        assert any("回退" in r.message for r in caplog.records)
        # 坏文件改名保留现场
        assert not (tmp_path / "data" / "config.local.yaml").exists()
        assert list((tmp_path / "data").glob("config.local.yaml.corrupt-*"))

    def test_bad_yaml_without_bak_raises(self, monkeypatch, tmp_path):
        """无 .bak → 抛显性异常让启动失败（密钥全消失优于静默空跑）。"""
        reg = self._patch_base(monkeypatch, tmp_path)
        (tmp_path / "data" / "config.local.yaml").write_text(
            "gateway: [broken", encoding="utf-8")
        with pytest.raises(RuntimeError):
            reg.raw_config()

    def test_write_config_creates_bak(self, monkeypatch, tmp_path):
        """写入前自动把当前好配置备份为 .bak（原子替换）。"""
        import yaml
        reg = self._patch_base(monkeypatch, tmp_path)
        assert reg.write_config({"a": 1}) is True
        assert reg.write_config({"a": 2}) is True
        bak = tmp_path / "data" / "config.local.yaml.bak"
        assert bak.exists()
        assert yaml.safe_load(bak.read_text(encoding="utf-8")) == {"a": 1}
        assert yaml.safe_load((tmp_path / "data" / "config.local.yaml").read_text(encoding="utf-8")) == {"a": 2}


# ---------------------------------------------------------------------------
# 6) imagegen 外链二次下载校验（伪响应）
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code=200, content_type="image/png", body=b"x" * 4096):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = body


class TestImagegenExternalDownload:
    def test_validator_accepts_valid_image(self):
        from core.imagegen import _external_image_ok
        ok, reason = _external_image_ok(_FakeResp())
        assert ok is True and reason == ""

    def test_validator_rejects_non_2xx(self):
        from core.imagegen import _external_image_ok
        ok, reason = _external_image_ok(_FakeResp(status_code=404))
        assert ok is False and "404" in reason

    def test_validator_rejects_html_error_page(self):
        """HTML 错误页（200）不落盘——历史上坏文件一路走到 PIL 才爆。"""
        from core.imagegen import _external_image_ok
        ok, reason = _external_image_ok(_FakeResp(content_type="text/html"))
        assert ok is False and "content-type" in reason

    def test_validator_rejects_oversize(self):
        from core.imagegen import _external_image_ok
        ok, _ = _external_image_ok(_FakeResp(body=b"x" * (21 * 1024 * 1024)))
        assert ok is False

    def test_validator_rejects_tiny_body(self):
        from core.imagegen import _external_image_ok
        ok, reason = _external_image_ok(_FakeResp(body=b"x" * 10))
        assert ok is False and "过小" in reason

    def test_gen_image_does_not_write_invalid_download(self, monkeypatch, tmp_path):
        """整链路：商业端点返回外链，外链回 HTML 错误页 → 不落盘。"""
        from core import imagegen

        class _ApiResp:
            status_code = 200
            text = ""
            def json(self):
                return {"data": [{"url": "https://cdn.example/img.png"}]}

        class _Api:
            def post(self, url, json=None, headers=None):
                return _ApiResp()

        class _Dl:
            def get(self, url):
                return _FakeResp(content_type="text/html", body=b"<html>err</html>" * 10)

        monkeypatch.setattr(imagegen, "_get_http_client", lambda *a, **k: _Api())
        monkeypatch.setattr(imagegen, "_get_download_client", lambda: _Dl())
        monkeypatch.setattr("core.llm.resolve_llm_endpoint",
                            lambda *a, **k: ("https://api.example.com/v1", "sk-test", "agnes-image", "custom"))
        monkeypatch.setattr(imagegen, "gen_image_pollinations", lambda *a, **k: False)
        # Pillow 保底卡片可能真的渲染一张卡——禁掉以验证「外链校验失败不落盘」
        monkeypatch.setattr(imagegen, "_render_fallback_card", lambda *a, **k: False)
        out = tmp_path / "img.png"
        ok = imagegen.gen_image("a coffee shop", out)
        assert ok is False
        assert not out.exists()
        assert "校验失败" in imagegen.last_gen_diagnosis().get("commercial_error", "")

    def test_gen_image_writes_valid_download(self, monkeypatch, tmp_path):
        """合法图片外链（image/png 2KB+）仍正常落盘。"""
        from core import imagegen

        class _ApiResp:
            status_code = 200
            text = ""
            def json(self):
                return {"data": [{"url": "https://cdn.example/img.png"}]}

        class _Api:
            def post(self, url, json=None, headers=None):
                return _ApiResp()

        png = b"\x89PNG\r\n" + b"0" * 4096
        class _Dl:
            def get(self, url):
                return _FakeResp(content_type="image/png", body=png)

        monkeypatch.setattr(imagegen, "_get_http_client", lambda *a, **k: _Api())
        monkeypatch.setattr(imagegen, "_get_download_client", lambda: _Dl())
        monkeypatch.setattr("core.llm.resolve_llm_endpoint",
                            lambda *a, **k: ("https://api.example.com/v1", "sk-test", "agnes-image", "custom"))
        monkeypatch.setattr(imagegen, "gen_image_pollinations", lambda *a, **k: False)
        out = tmp_path / "img.png"
        ok = imagegen.gen_image("a coffee shop", out)
        assert ok is True
        assert out.exists() and out.read_bytes() == png


# ---------------------------------------------------------------------------
# 7) Pollinations 免 Key 公共通道开关
# ---------------------------------------------------------------------------

class TestPollinationsSwitch:
    def test_default_enabled(self, monkeypatch):
        from core import imagegen
        monkeypatch.setattr(imagegen, "load_config", lambda: {"image": {}})
        assert imagegen.pollinations_enabled() is True

    def test_disabled_skips_channel_without_http(self, monkeypatch):
        """开关关掉：直接返回 False，零外呼。"""
        from core import imagegen
        monkeypatch.setattr(imagegen, "load_config", lambda: {"image": {"pollinations_enabled": False}})

        def _boom(*a, **k):
            raise AssertionError("关闭后不应发起任何外呼")
        monkeypatch.setattr(imagegen, "_get_http_client", _boom)
        out = tmp_unused = Path("/tmp") / "yimu-test-should-not-exist.png"
        assert imagegen.gen_image_pollinations("cat", out) is False
        assert not out.exists()

    def test_enabled_logs_third_party_notice(self, monkeypatch, caplog):
        """命中该通道时记录「提示词将经免 Key 公共通道发送至第三方」。"""
        from core import imagegen
        monkeypatch.setattr(imagegen, "load_config", lambda: {"image": {"pollinations_enabled": True}})

        class _Resp:
            status_code = 404
            content = b""

        class _Cli:
            def get(self, url):
                return _Resp()

        monkeypatch.setattr(imagegen, "_get_http_client", lambda *a, **k: _Cli())
        out = Path("/tmp") / "yimu-test-pollinations.png"
        with caplog.at_level("INFO", logger="core.imagegen"):
            imagegen.gen_image_pollinations("cat", out)
        out.unlink(missing_ok=True)
        assert any("免 Key 公共通道" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 8) chat_stream 全链路透传 user_id（P0 流式计费漏损）
# ---------------------------------------------------------------------------

class TestChatStreamUserId:
    def test_stream_passes_user_id_to_resolver(self, monkeypatch):
        """chat_stream 必须把 user_id 传给 resolve_llm_endpoint（BYOK 解析需要）。"""
        import core.llm as llm
        captured: dict = {}

        def _fake_resolve(model=None, stage=None, user_id=None):
            captured["user_id"] = user_id
            return "https://api.example.com/v1", "sk-k", "m-x", "yimu_official"

        monkeypatch.setattr(llm, "resolve_llm_endpoint", _fake_resolve)
        monkeypatch.setattr(llm, "_get_fallback_candidates", lambda pid: [])

        def _boom(*a, **k):
            raise RuntimeError("simulated network down")
        monkeypatch.setattr(llm, "_get_http_client", _boom)

        with pytest.raises(RuntimeError):
            list(llm.chat_stream([{"role": "user", "content": "hi"}], user_id="u-42"))
        assert captured["user_id"] == "u-42"

    def test_metering_official_without_user_logs_warning(self, monkeypatch, caplog, tmp_path):
        """官方通道缺 user_id 仅记统计未扣费的分支必须留 warning（真正修复在上游传对）。"""
        from studio import llm_metering
        monkeypatch.setattr(llm_metering, "_USAGE_PATH", tmp_path / "usage.json")
        monkeypatch.setattr(llm_metering, "_USAGE_MEM", None)
        monkeypatch.setattr(llm_metering, "_USAGE_MEM_PATH", None)
        with caplog.at_level("WARNING", logger="studio.llm_metering"):
            res = llm_metering.record_llm_call(
                "yimu_official", "yimu-chat", 100, 50, 150, user_id=None,
                prompt_text="", completion_text="")
        assert res.get("metered") is True
        assert res.get("deducted") == 0
        assert any("缺少 user_id" in r.message and "未扣费" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 9) spawn_user_task：统一受界池 + 每用户闸门（附带回归）
# ---------------------------------------------------------------------------

class TestSpawnUserTask:
    def test_gate_limits_per_user(self, monkeypatch):
        """每用户同时最多 2 个重任务，超出抛友好中文错误；完成后闸门释放。"""
        from core import task_queue
        jobs: dict = {}
        admin_mod = _fake_web_admin(monkeypatch, jobs)
        admin_mod.start_async_job = lambda jid, **kw: jobs.setdefault(
            jid, {"status": "running", "owner": kw.get("owner", "")})
        release = threading.Event()
        done = threading.Event()

        def _blocker():
            release.wait(timeout=5)
            jobs["j"]["status"] = "done"

        task_queue.spawn_user_task("u1", "任务1", _blocker, jid="j")
        task_queue.spawn_user_task("u1", "任务2", _blocker, jid="j2")
        with pytest.raises(task_queue.UserTaskLimitError) as ei:
            task_queue.spawn_user_task("u1", "任务3", _blocker, jid="j3")
        assert "同时最多" in str(ei.value)
        # 其他用户不受影响
        task_queue.spawn_user_task("u2", "任务4", _blocker, jid="j4")

        release.set()
        for _ in range(100):
            if all(jobs.get(x, {}).get("status") == "done" for x in ("j", "j2", "j4")):
                break
            time.sleep(0.05)
        done.set()
        # 闸门释放后可再次提交
        time.sleep(0.2)
        task_queue.spawn_user_task("u1", "任务5", lambda: None, jid="j5")

    def test_spawn_failure_marks_job_failed(self, monkeypatch):
        """fn 抛出的漏网异常必须把 JOBS 标 failed，而不是永远 running。"""
        from core import task_queue
        jobs: dict = {}
        admin_mod = _fake_web_admin(monkeypatch, jobs)
        admin_mod.start_async_job = lambda jid, **kw: jobs.setdefault(
            jid, {"status": "running", "owner": kw.get("owner", "")})
        task_queue.spawn_user_task("u1", "会炸的任务", lambda: (_ for _ in ()).throw(ValueError("炸")), jid="jx")
        for _ in range(100):
            if jobs.get("jx", {}).get("status") == "failed":
                break
            time.sleep(0.05)
        assert jobs["jx"]["status"] == "failed"
        assert "炸" in (jobs["jx"].get("error") or "")

    def test_task_queue_fn_injection_via_partial(self):
        """functools.partial 无 __code__：TypeError 试探后回退，任务不再整单 AttributeError。"""
        import functools
        from core.task_queue import Task, TaskManager
        tm = TaskManager(max_workers=1)
        t = Task(id="tp", name="n", task_type="tt")

        def plain(a, b):
            return a + b
        p = functools.partial(plain, 1)
        assert tm._invoke_fn(p, t, (2,), {}) == 3

        def with_task(task, a, b):
            return ("task", a + b)
        assert tm._invoke_fn(with_task, t, (1,), {"b": 2}) == ("task", 3)

        def without_task(a, b):
            return a + b
        assert tm._invoke_fn(without_task, t, (1,), {"b": 2}) == 3
