"""V13.0.0 · 梅雪镜 · 全功能离线桌面包（A2 完全自给）回归锁。

锁的是「为什么以前只有几兆」这个根因，防止打包链路哪天退化回源码壳：
  · 全量资源目录（gateway / app / skills / config.yaml）必须在包里
  · 自带 runtime + site-packages + Chromium，客户机零 venv / 零 pip / 零 brew
  · 出厂配置指向官方云端通道，出厂配额重新生成
  · 内置官方凭证可注入，用户自定义 Key 不被覆盖
  · CI 三平台都要跑离线冒烟与体积下限
"""
from __future__ import annotations

import json
import re
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
    assert "ci-secret" in builder
    # 仓库里不能出现可扣费的真实密钥字面量
    assert not re.search(r'api_key\s*=\s*["\']sk-[A-Za-z0-9]{16,}', builder)


def test_first_run_bootstrap_respects_user_keys() -> None:
    s = BOOTSTRAP.read_text(encoding="utf-8")
    assert "activate_runtime" in s and "reset_factory_quota" in s
    assert "if not env.get(k)" in s, "绝不能覆盖用户已填的自定义 Key"
    assert "MEDIAFLOW_KEY_YIMU_OFFICIAL" in s
    assert "YIMU_SKIP_TRIAL_CLAIM" in s
    assert "trial/claim" in s and "CLAIM_TIMEOUT" in s, "官方试用凭证需有超时，断网不阻断启动"


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


def test_legacy_builder_forwards_to_full_bundle() -> None:
    s = LEGACY.read_text(encoding="utf-8")
    i = s.find("def main():")
    tail = s[i:]
    assert "build_full_bundle" in tail, "旧入口必须转发，避免手动跑又产出源码壳"


def test_version_and_codename() -> None:
    import version
    assert version.__version__ == "13.0.0"
    assert version.__codename__ == "梅雪镜"
    assert version.__codename_en__ == "Plum-Snow Mirror"
    d = json.loads((BASE / "release-codenames.json").read_text(encoding="utf-8"))
    assert d["current_version"] == "13.0.0" and d["next_index"] == 10
    assert d["history"][-1]["version"] == "v13.0.0"
