# SPDX-License-Identifier: BUSL-1.1
"""内置 Chromium 执行位回归（V15.9.3）。

客户机现象：装完客户端双击，弹「Google Chrome for Testing 意外退出」，窗口不出现。
崩溃报告：`crashed on child side of fork pre-exec` + `EXC_BREAKPOINT / SIGTRAP`，
进程 0.05~0.15 ms 内结束。

真因：`ZipFile.extractall()` 不还原 `external_attr` 里的权限位，解压出来一律 0644。
旧实现只对主可执行文件单点 chmod，`chrome_crashpad_handler`、Renderer/GPU Helper
等 13 个 Mach-O 全都不可执行 —— Chromium 启动第一步 spawn crashpad handler 就
EACCES，`CHECK` 失败触发 `__builtin_trap()`，于是崩溃。

本文件锁三件事：
1. 解压即按 zip 记录还原权限；
2. zip 元数据不可信时，按魔数兜底补执行位；
3. 缺执行位必须在出厂断言处直接失败，不许流到客户机。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import zipfile
from pathlib import Path

import pytest

from core import browser_path as bp

ROOT = Path(__file__).resolve().parent.parent

MACHO_ARM64 = b"\xcf\xfa\xed\xfe" + b"\x00" * 12
ELF64 = b"\x7fELF" + b"\x02\x01\x01\x00" + b"\x00" * 8


def _load_builder():
    """把构建脚本当模块加载（scripts/ 不是包）。"""
    path = ROOT / "scripts" / "build_full_bundle.py"
    spec = importlib.util.spec_from_file_location("_yimu_build_bundle", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def builder():
    return _load_builder()


def test_zip_permissions_are_restored(builder, tmp_path: Path) -> None:
    """zip 里记录的 0755 必须被还原，而不是留成 0644。"""
    z = tmp_path / "cft.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("chrome-mac-arm64/Helpers/chrome_crashpad_handler")
        info.external_attr = 0o755 << 16
        zf.writestr(info, MACHO_ARM64)

    out = tmp_path / "out"
    out.mkdir()
    assert builder.restore_zip_perms(z, out) == 0  # 元数据已带 x，无需兜底

    exe = out / "chrome-mac-arm64/Helpers/chrome_crashpad_handler"
    assert exe.is_file()
    assert os.access(exe, os.X_OK), "zip 记录的 0755 没有被还原，helper 将无法 spawn"


def test_fallback_adds_x_bit_when_zip_metadata_says_0644(builder, tmp_path: Path) -> None:
    """zip 元数据说 0644，但内容是可执行映像 —— 必须按魔数兜底补 x。"""
    z = tmp_path / "cft.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name in ("chrome-mac-arm64/Helpers/chrome_crashpad_handler",
                     "chrome-linux64/chrome_crashpad_handler"):
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o644 << 16
            zf.writestr(info, MACHO_ARM64 if "mac" in name else ELF64)

    out = tmp_path / "out"
    out.mkdir()
    fixed = builder.restore_zip_perms(z, out)
    assert fixed == 2, f"应补 2 个可执行映像，实际 {fixed}"
    for name in ("chrome-mac-arm64/Helpers/chrome_crashpad_handler",
                 "chrome-linux64/chrome_crashpad_handler"):
        assert os.access(out / name, os.X_OK)


def test_non_executable_data_files_stay_untouched(builder, tmp_path: Path) -> None:
    """普通数据文件不该被误加执行位。"""
    z = tmp_path / "cft.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("chrome-mac-arm64/README.md")
        info.external_attr = 0o644 << 16
        zf.writestr(info, b"# not a binary\n")

    out = tmp_path / "out"
    out.mkdir()
    builder.restore_zip_perms(z, out)
    assert not os.access(out / "chrome-mac-arm64/README.md", os.X_OK)


def test_factory_assert_rejects_missing_exec_bit(builder, tmp_path: Path) -> None:
    """出厂断言：缺执行位必须直接构建失败，而不是产出一个客户机必崩的包。"""
    out = tmp_path / "chromium"
    helper = out / "Helpers/chrome_crashpad_handler"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(MACHO_ARM64)
    helper.chmod(0o644)

    with pytest.raises(RuntimeError, match="缺少执行位"):
        builder.assert_executables(out)

    helper.chmod(0o755)
    builder.assert_executables(out)   # 修好后不抛


def test_factory_assert_passes_clean_tree(builder, tmp_path: Path) -> None:
    out = tmp_path / "chromium"
    exe = out / "chrome-linux64/chrome"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(ELF64)
    exe.chmod(0o755)
    builder.assert_executables(out)


def test_runtime_heal_repairs_installed_bundle(tmp_path: Path) -> None:
    """已装好的目录（老包）也要能自愈，不用用户重装。"""
    root = tmp_path / "chromium"
    helper = root / "chrome-mac-arm64/Helpers/chrome_crashpad_handler"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(MACHO_ARM64)
    helper.chmod(0o644)
    renderer = root / "chrome-mac-arm64/Helpers/Helper (Renderer).app/Contents/MacOS/x"
    renderer.parent.mkdir(parents=True)
    renderer.write_bytes(MACHO_ARM64)
    renderer.chmod(0o644)

    assert bp.heal_executable_perms(root) == 2
    assert os.access(helper, os.X_OK)
    assert os.access(renderer, os.X_OK)
    assert bp.heal_executable_perms(root) == 0   # 幂等


def test_bundled_chromium_heals_once(monkeypatch, tmp_path: Path) -> None:
    """bundled_chromium() 首次解析内置内核时顺带自愈，且只做一次。"""
    root = tmp_path / "chromium"
    exe = root / "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/cft"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(MACHO_ARM64)
    exe.chmod(0o755)
    helper = root / "chrome-mac-arm64/Helpers/chrome_crashpad_handler"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_bytes(MACHO_ARM64)
    helper.chmod(0o644)
    (root / "EXECUTABLE").write_text(
        "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/cft",
        encoding="utf-8",
    )

    monkeypatch.setattr(bp, "MARKER", root / "EXECUTABLE")
    monkeypatch.setattr(bp, "_PERMS_HEALED", False)
    monkeypatch.setattr(bp.sys, "platform", "darwin")

    assert bp.bundled_chromium() == str(exe.resolve())
    assert os.access(helper, os.X_OK), "bundled_chromium 没有触发权限自愈"
    assert bp._PERMS_HEALED is True


class _FakePage:
    def goto(self, *a, **k):
        return None


class _FakeCtx:
    def new_page(self):
        return _FakePage()

    def close(self):
        pass


class _FakeBrowser:
    def new_context(self):
        return _FakeCtx()

    def close(self):
        pass


def test_launch_chromium_prefers_builtin(monkeypatch, tmp_path: Path) -> None:
    """执行位修好后，内置内核重回第一候选（版本可控、离线可用）。"""
    calls: list[str] = []

    class FakeBT:
        def launch(self, **kw):
            calls.append("builtin" if kw.get("executable_path") else f"channel={kw.get('channel')}")
            return _FakeBrowser()

    monkeypatch.setattr(bp, "MARKER", tmp_path / "chromium" / "EXECUTABLE")
    monkeypatch.setattr(bp, "bundled_chromium", lambda: "/bundle/chrome")
    assert bp.launch_chromium(FakeBT(), headless=True, channel="chrome", args=[]) is not None
    assert calls == ["builtin"], f"候选顺序不对：{calls}"


def test_broken_mark_skips_builtin_next_time(monkeypatch, tmp_path: Path) -> None:
    """内置内核探活失败后落标记，下一次直接走系统浏览器，不再反复弹崩溃窗。"""
    marker = tmp_path / "chromium" / "EXECUTABLE"
    marker.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bp, "MARKER", marker)
    monkeypatch.setattr(bp, "bundled_chromium", lambda: "/bundle/chrome")

    calls: list[str] = []

    class DeadBrowser(_FakeBrowser):
        def new_context(self):
            raise RuntimeError("TargetClosedError: 渲染子进程已死")

    class FakeBT:
        def launch(self, **kw):
            name = "builtin" if kw.get("executable_path") else f"channel={kw.get('channel')}"
            calls.append(name)
            return DeadBrowser() if name == "builtin" else _FakeBrowser()

    b1 = bp.launch_chromium(FakeBT(), headless=True, channel="chrome", args=[])
    assert b1 is not None and calls == ["builtin", "channel=chrome"]
    assert bp._is_marked_broken(), "探活失败应写下 .broken 标记"

    calls.clear()
    assert bp.launch_chromium(FakeBT(), headless=True, channel="chrome", args=[]) is not None
    assert calls == ["channel=chrome"], f"标记存在时不该再试内置内核：{calls}"
