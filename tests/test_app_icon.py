"""桌面客户端应用图标回归锁。

背景：v13.0.0 的 macOS .app 只写了 Info.plist，却没有 CFBundleIconFile、也没有
Contents/Resources/AppIcon.icns，装完在 Finder / Dock / 启动台里显示为空白图标。
这里锁住三平台图标链路，防止再次退化。
"""
from __future__ import annotations

from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
ICONS = BASE / "installer" / "icons"
DMG = BASE / "scripts" / "build_macos_dmg.sh"
DEB = BASE / "scripts" / "build_linux_deb.sh"
WIN_ISS = BASE / "installer" / "windows" / "yimu_installer.iss"
BUILDER = BASE / "scripts" / "build_full_bundle.py"
LOGO = BASE / "web" / "static" / "img" / "logo-master.png"


def test_icon_assets_exist() -> None:
    """三平台图标文件必须在仓，CI 才能在 Linux/Windows runner 上直接引用。"""
    assert LOGO.is_file(), "缺少 logo 母版"
    for name in ("AppIcon.icns", "app.ico", "icon-1024.png"):
        p = ICONS / name
        assert p.is_file(), f"缺少图标 {name}"
        assert p.stat().st_size > 1024, f"{name} 体积异常，疑似空文件"


def test_icns_is_valid_container() -> None:
    raw = (ICONS / "AppIcon.icns").read_bytes()
    assert raw[:4] == b"icns", "AppIcon.icns 不是合法 icns 容器"
    # iconutil 对 16/32 用 ARGB 键（ic04/ic05），其余用 PNG 键（ic07/ic08/ic09/ic10）
    for kind in (b"ic04", b"ic05", b"ic07", b"ic08", b"ic09", b"ic10"):
        assert kind in raw, f"icns 缺少 {kind!r} 尺寸"


def test_ico_has_large_size() -> None:
    Image = pytest.importorskip("PIL.Image")
    im = Image.open(ICONS / "app.ico")
    sizes = {s for s in im.info.get("sizes", [])}
    assert (256, 256) in sizes, f"app.ico 缺少 256px（Windows 大图标会模糊）: {sizes}"


def test_linux_hicolor_sizes() -> None:
    for size in (16, 32, 48, 256, 512):
        p = ICONS / "hicolor" / f"{size}x{size}" / "apps" / "yimu-studio.png"
        assert p.is_file(), f"缺少 hicolor {size} 图标"


def test_macos_plist_declares_icon() -> None:
    sh = DMG.read_text(encoding="utf-8")
    assert "CFBundleIconFile" in sh, "Info.plist 未声明 CFBundleIconFile，应用图标会空白"
    assert "CFBundleIconName" in sh, "Info.plist 未声明 CFBundleIconName"
    assert "AppIcon.icns" in sh, "构建脚本未把 AppIcon.icns 复制进 Contents/Resources"
    assert 'Contents/Resources/AppIcon.icns' in sh


def test_windows_installer_uses_app_ico() -> None:
    iss = WIN_ISS.read_text(encoding="utf-8")
    assert "SetupIconFile=" in iss, "安装器本身没有图标"
    assert "app.ico" in iss, "安装器未引用 app.ico"
    assert "web\\static\\favicon.ico" not in iss, "仍在引用不存在的 favicon.ico 路径"
    assert "UninstallDisplayIcon" in iss, "卸载项没有图标"


def test_linux_desktop_entry_uses_brand_icon() -> None:
    sh = DEB.read_text(encoding="utf-8")
    assert "Icon=yimu-studio" in sh, ".desktop 仍使用系统通用图标"
    assert "video-x-generic" not in sh, "仍残留系统占位图标名"
    assert "hicolor" in sh, "deb 未安装 hicolor 图标"


def test_bundler_copies_icons_into_app() -> None:
    src = BUILDER.read_text(encoding="utf-8")
    assert "def copy_app_icons(" in src
    assert "copy_app_icons(stage)" in src, "构建流程未调用图标注入"
    assert "AppIcon.icns" in src and "app.ico" in src
