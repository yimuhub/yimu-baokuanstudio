#!/usr/bin/env python3
"""YIMU Studio Release Management Tool (一幕版本升级与发布管理中枢).

使用方式：
    python scripts/release.py --status               # 查看当前版本、Git Tag 归档与状态
    python scripts/release.py 9.0.1 --codename "新代号" # 自动化版本步进与安全发布流程
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def get_current_version() -> str:
    version_file = ROOT / "version.py"
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', version_file.read_text(encoding="utf-8"))
    if not match:
        raise ValueError("Could not find __version__ in version.py")
    return match.group(1)


def list_git_tags() -> list[str]:
    try:
        out = subprocess.check_output(["git", "tag", "-l", "--sort=-v:refname"], cwd=str(ROOT), text=True)
        return [t.strip() for t in out.splitlines() if t.strip()]
    except Exception:
        return []


def print_status():
    cur = get_current_version()
    tags = list_git_tags()
    print("=" * 60)
    print("🎬 一幕·YIMU Studio Release Status")
    print(f"📌 Current Active Version: V{cur}")
    print(f"🏷️  Archived Git Tags ({len(tags)}):")
    for t in tags[:5]:
        print(f"    - {t}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="YIMU Studio Release Tool")
    parser.add_argument("version", nargs="?", help="New version to release (e.g. 9.0.1, 9.1.0)")
    parser.add_argument("--codename", default="", help="Optional release codename (e.g. '破晓')")
    parser.add_argument("--status", action="store_true", help="Display current release status")
    args = parser.parse_args()

    if args.status or not args.version:
        print_status()
        if not args.version:
            print("\n💡 提示：升级新版本示例: python scripts/release.py 9.1.0 --codename '新版本代号'")
        return

    new_ver = args.version.lstrip("v").strip()
    if not re.match(r"^\d+\.\d+\.\d+$", new_ver):
        print(f"❌ 错误: 版本号 '{new_ver}' 不符合语义化版本规范 (X.Y.Z，如 9.0.1)")
        sys.exit(1)

    cur_ver = get_current_version()
    print(f"🚀 准备从 V{cur_ver} 升级至新版本 V{new_ver}...")

    # 1. 更新 version.py
    ver_path = ROOT / "version.py"
    content = ver_path.read_text(encoding="utf-8")
    content = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', f'__version__ = "{new_ver}"', content)
    if args.codename:
        content = re.sub(r'__codename__\s*=\s*["\'][^"\']+["\']', f'__codename__ = "{args.codename}"', content)
    ver_path.write_text(content, encoding="utf-8")
    print(f"✅ 已更新 version.py 单一真源为 {new_ver}")

    print("\n💡 升级完成提示：")
    print(f"1. 请在 CHANGELOG.md 中追加 V{new_ver} 的更新日志；")
    print("2. 运行 `bash ci.sh` 确保所有质量门禁全绿；")
    print(f"3. 提交并打标签推送：")
    print(f"   git commit -am 'feat(release): 发布 V{new_ver}'")
    print(f"   git tag -a v{new_ver} -m 'Release v{new_ver}'")
    print(f"   git push origin main --tags")


if __name__ == "__main__":
    main()
