"""V13.0.0 · 梅雪镜 · 全功能离线桌面包（A2 完全自给）回归锁。

锁的是「为什么以前只有几兆」这个根因，防止打包链路哪天退化回源码壳：
  · 全量资源目录（gateway / app / skills / config.yaml）必须在包里
  · 自带 runtime + site-packages + Chromium，客户机零 venv / 零 pip / 零 brew
  · 出厂配置指向官方云端通道，出厂配额重新生成
  · 内置官方凭证在构建期结构化注入、缺凭证可选硬门禁，用户自定义 Key 不被覆盖
  · 客户机全程离线，不再联网申领试用凭证
  · CI 三平台都要跑离线冒烟与体积下限
"""
from __future__ import annotations

import importlib.util
import json
import re
import stat
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
BUILDER = BASE / "scripts" / "build_full_bundle.py"
VERIFIER = BASE / "scripts" / "verify_bundle.py"
BOOTSTRAP = BASE / "scripts" / "first_run_bootstrap.py"
BROWSER_PATH = BASE / "core" / "browser_path.py"
DESKTOP = BASE / "desktop.py"
DEB = BASE / "scripts" / "build_linux_deb.sh"
DMG = BASE / "scripts" / "build_macos_dmg.sh"
WIN = BASE / "scripts" / "build_windows_installer.py"
LEGACY = BASE / "scripts" / "build_desktop_client.py"
CI = BASE / ".github" / "workflows" / "build-desktop-client.yml"

FORBIDDEN = ("python3 -m venv", "pip install -r requirements.txt", "brew install python")


@pytest.fixture(scope="module")
def builder() -> str:
    return BUILDER.read_text(encoding="utf-8")


def test_full_bundle_files_exist() -> None:
    for p in (BUILDER, VERIFIER, BOOTSTRAP, BROWSER_PATH):
        assert p.is_file(), f"缺少全功能包核心文件: {p}"


def test_all_runtime_resources_are_included(builder: str) -> None:
    """旧脚本只带 5 个目录，导致 gateway / app / skills / config.yaml 全丢。"""
    seg = builder[builder.find("INCLUDE_DIRS = ["):][:400]
    for d in ("core", "studio", "web", "adapters", "gateway", "app", "skills", "scripts", "installer"):
        assert f'"{d}"' in seg, f"打包目录缺少 {d}"
    files = builder[builder.find("INCLUDE_FILES = ["):][:400]
    for f in ("desktop.py", "version.py", "requirements.txt", "config.yaml"):
        assert f'"{f}"' in files, f"打包文件缺少 {f}"


def test_runtime_and_chromium_are_bundled(builder: str) -> None:
    assert "runtime" in builder and "site-packages" in builder
    assert "setup_runtime" in builder and "setup_chromium" in builder
    assert "--target" in builder, "依赖必须预装进包内 site-packages，不能客户机现装"
    assert "pywebview" in builder, "原生窗口依赖必须预装"
    assert "playwright install" not in builder, "内置 Chromium 后不应再下载 Playwright 浏览器"
    assert "MIN_ARCHIVE_MB" in builder and "疑似退化成源码壳" in builder


def test_official_channel_and_factory_quota(builder: str) -> None:
    assert "gateway.yimu.studio" in builder
    assert "yimu_official" in builder
    assert "reset_factory_quota" in builder
    assert "FACTORY_TRIAL_CREDITS" in builder
    for name in ("billing.json", "free_demo_calls.json", "llm_usage.json"):
        assert name in builder, f"出厂配额缺少 {name}"
    assert '"history": []' in builder, "出厂配额必须清空消费历史"


def test_official_key_is_injected_never_hardcoded(builder: str) -> None:
    assert "YIMU_OFFICIAL_BOOTSTRAP_KEY" in builder
    assert "YIMU_REQUIRE_OFFICIAL_KEY" in builder, "缺凭证硬门禁必须可配置"
    assert "ci-secret" in builder and "unset" in builder
    assert "official_credential.json" in builder
    assert "trial-claim" not in builder, "不得再产出需客户机联网申领凭证的包"
    # 仓库里不能出现可扣费的真实密钥字面量
    assert not re.search(r'api_key\s*=\s*["\']sk-[A-Za-z0-9]{16,}', builder)


def test_first_run_bootstrap_respects_user_keys() -> None:
    s = BOOTSTRAP.read_text(encoding="utf-8")
    assert "activate_runtime" in s and "reset_factory_quota" in s
    assert "if not env.get(k)" in s, "绝不能覆盖用户已填的自定义 Key"
    assert "MEDIAFLOW_KEY_YIMU_OFFICIAL" in s
    assert "official_credential.json" in s
    assert "trial/claim" not in s and "urllib.request" not in s, \
        "客户机首次启动必须全程离线，不再联网申领试用凭证"
    assert "factory_state.json" in s and "quota_regenerated" in s, \
        "全新版本包必须能重新生成出厂配额"


def test_launchers_have_no_client_side_install() -> None:
    for p in (DEB, DMG, WIN, LEGACY):
        lines = [l for l in p.read_text(encoding="utf-8").splitlines()
                 if not l.lstrip().startswith("#") and not l.lstrip().startswith('"""')]
        text = "\n".join(lines)
        for bad in FORBIDDEN:
            # 允许注释性说明（已过滤注释行），执行语句里一律禁止
            assert bad not in text, f"{p.name} 仍要求客户机现装: {bad}"


def test_deb_no_longer_depends_on_system_python() -> None:
    s = DEB.read_text(encoding="utf-8")
    assert "python3-pip" not in s and "python3-venv" not in s
    assert "runtime/bin/python3" in s, "deb 启动器必须指向自带解释器"
    assert "MANIFEST.json" in s, "安装器必须校验拿到的是全功能 bundle"


def test_macos_launcher_no_brew_python() -> None:
    s = DMG.read_text(encoding="utf-8")
    assert "runtime/bin/python3" in s
    assert "display alert" not in s, "不应再弹窗让用户装 Python"


def test_desktop_uses_bootstrap_and_bundled_chromium() -> None:
    s = DESKTOP.read_text(encoding="utf-8")
    assert "first_run_bootstrap" in s and "BOOTSTRAP" in s
    assert "bundled_chromium" in s
    assert "auto_heal_all_sqlite_databases" not in s, "该函数并不存在，异常此前被吞掉"


def test_playwright_uses_bundled_browser() -> None:
    for rel, count in (("core/render_card.py", 1), ("core/search.py", 2)):
        s = (BASE / rel).read_text(encoding="utf-8")
        assert s.count("launch_chromium(") >= count, f"{rel} 未接入内置浏览器"
        assert "launch_chromium" in s and "core.browser_path" in s


def test_ci_builds_and_verifies_all_platforms() -> None:
    import yaml
    d = yaml.safe_load(CI.read_text(encoding="utf-8"))
    jobs = d["jobs"]
    for name in ("build-windows", "build-macos", "build-linux"):
        steps = " ".join(str(s.get("run", "")) for s in jobs[name]["steps"])
        assert "build_full_bundle.py" in steps, f"{name} 未构建全功能 bundle"
        assert "verify_bundle.py" in steps, f"{name} 缺离线冒烟验收"
    pub = " ".join(str(s.get("run", "")) for s in jobs["publish-release"]["steps"])
    assert "90" in pub and "源码壳" in pub, "发布前必须有包体积下限门禁"
    assert "YIMU_OFFICIAL_BOOTSTRAP_KEY" in CI.read_text(encoding="utf-8")
    assert "YIMU_REQUIRE_OFFICIAL_KEY" in CI.read_text(encoding="utf-8")
    assert "YIMU_REQUIRE_OFFICIAL_KEY" in (BASE / ".github" / "workflows" /
                                           "build-macos-installer.yml").read_text(encoding="utf-8")


def test_legacy_builder_forwards_to_full_bundle() -> None:
    s = LEGACY.read_text(encoding="utf-8")
    i = s.find("def main():")
    tail = s[i:]
    assert "build_full_bundle" in tail, "旧入口必须转发，避免手动跑又产出源码壳"


def test_version_and_codename() -> None:
    """版本三处真源必须一致。

    注意：这里校验的是「一致性」而不是某个固定版本号 —— 写死 13.0.0 会让每次
    正常升版都把这条门禁打红，反而掩盖真正的不一致。
    """
    import version
    d = json.loads((BASE / "release-codenames.json").read_text(encoding="utf-8"))
    assert d["current_version"] == version.__version__, "代号表与 version.py 版本号不一致"
    assert d["current_codename_zh"] == version.__codename__, "代号表中文代号与 version.py 不一致"
    assert d["current_codename_en"] == version.__codename_en__, "代号表英文代号与 version.py 不一致"
    assert d["history"][-1]["version"] == f"v{version.__version__}", "history 末条必须对应当前版本"
    assert d["history"][-1]["zh"] == version.__codename__
    # 代号只能前进，不许回退或重号
    assert d["next_index"] >= 1
    assert d["sequence"][d["next_index"]]["zh"] not in {h["zh"] for h in d["history"]}, "下一个待用代号已被消耗"


# ---------------------------------------------------------------------------
# V15.8：GitHub Release API 限流加固（v15.8.0 macOS 作业曾 403 失败）
# ---------------------------------------------------------------------------

def test_builder_github_api_has_auth_and_backoff(builder: str) -> None:
    assert "Authorization" in builder and "GITHUB_TOKEN" in builder
    assert "retries" in builder and "time.sleep" in builder
    assert "rate limit" in builder


def test_workflows_pass_github_token_to_builder() -> None:
    standalone = BASE / ".github" / "workflows" / "build-macos-installer.yml"
    for p in (CI, standalone):
        s = p.read_text(encoding="utf-8")
        assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in s, (
            f"{p.name} 必须把 GITHUB_TOKEN 传给打包脚本，否则仍会撞 60 次/小时匿名限额"
        )


def test_get_json_retries_on_rate_limit_and_sends_token(monkeypatch) -> None:
    """403 限流后应退避重试，且带上鉴权头；无需真的访问网络。"""
    import importlib.util
    import urllib.error

    spec = importlib.util.spec_from_file_location("yimu_full_bundle_under_test", BUILDER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    url = "https://api.github.com/repos/example/runtime/releases/latest"

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"assets": []}'

    calls = []

    def fake_urlopen(req, timeout=60):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, None)
        return _Resp()

    monkeypatch.setenv("GITHUB_TOKEN", "ci-token-for-test")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    assert mod._get_json(url) == {"assets": []}
    assert len(calls) == 2, "403 后必须重试一次"
    assert calls[0].get_header("Authorization") == "Bearer ci-token-for-test"


# ---------------------------------------------------------------------------
# V15.8.1：内置官方凭证机制（构建期注入 + 可选硬门禁 + 客户机零联网）
# ---------------------------------------------------------------------------

def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bundle_builder():
    return _load_module(BUILDER, "yimu_builder_under_test_v1581")


def _bootstrap_module():
    return _load_module(BOOTSTRAP, "yimu_bootstrap_under_test_v1581")


def test_official_credential_gate_blocks_missing_key(tmp_path, monkeypatch) -> None:
    """开启硬门禁后，缺 Secret 必须直接让打包失败，不许悄悄出无凭证包。"""
    b = _bundle_builder()
    stage = tmp_path / "stage"
    (stage / "app" / ".bootstrap").mkdir(parents=True)
    monkeypatch.delenv("YIMU_OFFICIAL_BOOTSTRAP_KEY", raising=False)
    monkeypatch.setenv("YIMU_REQUIRE_OFFICIAL_KEY", "1")
    with pytest.raises(RuntimeError, match="YIMU_OFFICIAL_BOOTSTRAP_KEY"):
        b.write_official_credential(stage, "linux", "v-test-1")

    monkeypatch.setenv("YIMU_REQUIRE_OFFICIAL_KEY", "0")
    assert b.write_official_credential(stage, "linux", "v-test-1") == "unset"
    assert not (stage / "app" / ".bootstrap" / "official_credential.json").exists()


def test_official_credential_is_structured_and_private(tmp_path, monkeypatch) -> None:
    b = _bundle_builder()
    stage = tmp_path / "stage"
    (stage / "app" / ".bootstrap").mkdir(parents=True)
    monkeypatch.setenv("YIMU_OFFICIAL_BOOTSTRAP_KEY", "ap-unit-test-credential-0123456789")
    monkeypatch.setenv("YIMU_REQUIRE_OFFICIAL_KEY", "1")
    assert b.write_official_credential(stage, "linux", "v-test-2") == "ci-secret"
    f = stage / "app" / ".bootstrap" / "official_credential.json"
    cred = json.loads(f.read_text(encoding="utf-8"))
    assert cred["schema"] == 1
    assert cred["key"] == "ap-unit-test-credential-0123456789"
    assert cred["bundle_id"] == "v-test-2"
    assert cred["channel"] == "yimu_official" and "gateway.yimu.studio" in cred["base_url"]
    assert stat.S_IMODE(f.stat().st_mode) == 0o600, "随包凭证必须 0600"


def test_bootstrap_is_fully_offline_and_reads_bundled_credential(tmp_path, monkeypatch) -> None:
    fb = _bootstrap_module()
    app = tmp_path / "app"
    (app / ".bootstrap").mkdir(parents=True)
    monkeypatch.setattr(fb, "APP", app)
    monkeypatch.setattr(fb, "BUNDLE", tmp_path)
    monkeypatch.setattr(fb, "DATA", app / "data")
    monkeypatch.setattr(fb, "ENV_PATH", app / ".env")
    monkeypatch.delenv("YIMU_OFFICIAL_BOOTSTRAP_KEY", raising=False)

    assert fb.resolve_official_key() == ("", "unset")
    (app / ".bootstrap" / "official_credential.json").write_text(json.dumps({
        "schema": 1, "bundle_id": "v-test-3", "key": "ap-bundled-credential-987654321",
        "channel": "yimu_official",
    }), encoding="utf-8")
    assert fb.resolve_official_key() == ("ap-bundled-credential-987654321", "bundle")
    # 没有凭据文件也没有环境变量时不发任何网络请求（模块已不导入 urllib.request）
    assert not hasattr(fb, "urllib")


def test_bootstrap_regenerates_quota_only_on_new_bundle(tmp_path, monkeypatch) -> None:
    fb = _bootstrap_module()
    app = tmp_path / "app"
    data = app / "data"
    data.mkdir(parents=True)
    monkeypatch.setattr(fb, "APP", app)
    monkeypatch.setattr(fb, "BUNDLE", tmp_path)
    monkeypatch.setattr(fb, "DATA", data)
    monkeypatch.setattr(fb, "ENV_PATH", app / ".env")

    assert fb.reset_factory_quota("v1") is False  # 首次安装
    (data / "billing.json").write_text(json.dumps({
        "tier": "free", "balance": 12, "total_consumed": 99,
        "history": ["keep-me"], "cdkeys": {"KEEP": 1},
    }), encoding="utf-8")
    (data / "free_demo_calls.json").write_text('{"u1": 3}', encoding="utf-8")
    (data / "llm_usage.json").write_text('{"u1": 7}', encoding="utf-8")
    (data / "user_onboarding_done.json").write_text('{"done": true}', encoding="utf-8")

    assert fb.reset_factory_quota("v1") is False  # 同一包不重置
    assert fb.reset_factory_quota("v2") is True   # 全新包才重新生成
    billing = json.loads((data / "billing.json").read_text(encoding="utf-8"))
    assert billing["balance"] == fb.FACTORY_TRIAL_CREDITS
    assert billing["history"] == ["keep-me"] and billing["cdkeys"] == {"KEEP": 1}, \
        "重新生成配额不得抹掉用户消费历史与兑换码"
    assert json.loads((data / "free_demo_calls.json").read_text(encoding="utf-8")) == {}
    assert json.loads((data / "llm_usage.json").read_text(encoding="utf-8")) == {}
    assert json.loads((data / "user_onboarding_done.json").read_text(encoding="utf-8")) == {"done": True}, \
        "升级不应反复弹首次引导"
    assert fb.reset_factory_quota("v2") is False


def test_verifier_rejects_stale_trial_claim_contract() -> None:
    s = VERIFIER.read_text(encoding="utf-8")
    assert "trial-claim" in s, "验收脚本必须拒绝已废弃的运行期申领包"
    assert "YIMU_REQUIRE_OFFICIAL_KEY" in s
    assert "official_credential.json" in s
    assert "bundle_id" in s
    assert "YIMU_SKIP_TRIAL_CLAIM" not in s
