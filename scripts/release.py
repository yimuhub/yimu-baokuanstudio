#!/usr/bin/env python3
"""YIMU Studio Release Management Tool (一幕版本升级与发布管理中枢).

版本号不是「改一个文件」，而是六处真源必须同时对齐：``version.py``、
``pyproject.toml``、``release-codenames.json``、中英语言包、README 徽章，
再加上代号序列的指针前进。以前只改 ``version.py``，其余五处全靠手工补，
漏一处就被门禁打红（2026-11-18 发版即因为漏了 ``pyproject.toml`` 与代号续批，
六条用例同时失败）。本脚本一次性全部写完，并在代号序列耗尽时明确报错。

使用方式：
    python scripts/release.py --status                  # 查看当前版本、Git Tag 归档与状态
    python scripts/release.py 15.9.4                    # 自动领取下一个代号并同步六处真源
    python scripts/release.py 15.9.4 --codename "四海宁" # 指定代号（须在代号序列内）
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION_PY = ROOT / "version.py"
PYPROJECT = ROOT / "pyproject.toml"
REGISTRY = ROOT / "release-codenames.json"
LOCALES = (ROOT / "web/static/locales/zh-CN.json", ROOT / "web/static/locales/en-US.json")
BADGES = (ROOT / "README.md", ROOT / "README_EN.md")


def get_current_version() -> str:
    version_file = VERSION_PY
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


def _read_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def print_status():
    cur = get_current_version()
    tags = list_git_tags()
    state = _read_registry()
    nxt = state.get("next_index", 0)
    seq = state.get("sequence", [])
    nxt_name = seq[nxt]["zh"] if nxt < len(seq) else "（已耗尽，需续批）"
    print("=" * 60)
    print("🎬 一幕·YIMU Studio Release Status")
    print(f"📌 Current Active Version: V{cur}")
    print(f"🔖 Codename: {state.get('current_codename_zh', '?')} / {state.get('current_codename_en', '?')}")
    print(f"⏭️  Next Codename: {nxt_name}  (index {nxt}/{len(seq)})")
    print(f"🏷️  Archived Git Tags ({len(tags)}):")
    for t in tags[:5]:
        print(f"    - {t}")
    print("=" * 60)


def _is_utf8_json_ok(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def _bump_version_py(new_ver: str, zh: str, en: str) -> None:
    content = VERSION_PY.read_text(encoding="utf-8")
    content = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']', f'__version__ = "{new_ver}"', content)
    content = re.sub(r'__codename__\s*=\s*["\'][^"\']+["\']', f'__codename__ = "{zh}"', content)
    content = re.sub(r'__codename_en__\s*=\s*["\'][^"\']+["\']', f'__codename_en__ = "{en}"', content)
    VERSION_PY.write_text(content, encoding="utf-8")


def _bump_pyproject(new_ver: str, zh: str, en: str) -> None:
    """pyproject 的 version 同样被门禁校验，必须与 version.py 同步。"""
    s = PYPROJECT.read_text(encoding="utf-8")
    s = re.sub(r'^version\s*=\s*"[^"]+"', f'version = "{new_ver}"', s, count=1, flags=re.M)
    s = re.sub(
        r'^description\s*=\s*"[^"]*"',
        f'description = "一幕·YIMU 爆款工作室 V{new_ver} ({zh} · {en}) — 全自主 Multi-Agent 全媒体内容与影视短剧创作系统"',
        s,
        count=1,
        flags=re.M,
    )
    PYPROJECT.write_text(s, encoding="utf-8")


def _bump_locales(new_ver: str, zh: str, en: str) -> None:
    """中英语言包各存一份 version/codename，是「关于」页与页脚的数据源。"""
    for path, name in zip(LOCALES, (zh, en)):
        s = path.read_text(encoding="utf-8")
        s = re.sub(r'"version"\s*:\s*"[^"]*"', f'"version": "{new_ver}"', s, count=1)
        s = re.sub(r'"codename"\s*:\s*"[^"]*"', f'"codename": "{name}"', s, count=1)
        path.write_text(s, encoding="utf-8")
        if not _is_utf8_json_ok(path):
            raise ValueError(f"{path.name} 写坏成非法 JSON，请检查")


def _bump_badges(new_ver: str) -> None:
    for path in BADGES:
        s = path.read_text(encoding="utf-8")
        s = re.sub(r"badge/version-[0-9.]+-orange", f"badge/version-{new_ver}-orange", s)
        path.write_text(s, encoding="utf-8")


def _bump_registry(new_ver: str, zh: str, en: str) -> dict:
    """代号登记簿：当前版本 + 指针前进 + 历史追加，指针越界即报错。"""
    state = _read_registry()
    seq = state["sequence"]
    nxt = state.get("next_index", 0)
    if nxt >= len(seq):
        raise ValueError(
            f"代号序列已耗尽（next_index={nxt}, len={len(seq)}）。"
            "请先在 release-codenames.json 的 sequence 里续批新代号，再发版。"
        )
    used_zh = {h["zh"] for h in state.get("history", [])}
    if zh in used_zh:
        raise ValueError(f"代号「{zh}」已在历史中使用过，代号只能前进不可回退。")

    state["current_version"] = new_ver
    state["current_codename_zh"] = zh
    state["current_codename_en"] = en
    state["next_index"] = nxt + 1
    state.setdefault("history", []).append({"version": f"v{new_ver}", "zh": zh, "en": en, "date": _today()})
    REGISTRY.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def _today() -> str:
    try:
        return subprocess.check_output(["date", "+%Y-%m-%d"], text=True).strip()
    except Exception:
        import datetime

        return datetime.date.today().isoformat()


def resolve_codename(requested: str, state: dict) -> tuple[str, str]:
    """确定中英代号：显式指定须命中序列；未指定则领取序列当前位置。"""
    seq = state["sequence"]
    nxt = state.get("next_index", 0)
    if requested:
        for item in seq:
            if item["zh"] == requested:
                return item["zh"], item["en"]
        raise ValueError(f"代号「{requested}」不在 release-codenames.json 的 sequence 里，先登记再发版。")
    if nxt >= len(seq):
        raise ValueError(f"代号序列已耗尽（next_index={nxt}, len={len(seq)}），请续批后再发版。")
    return seq[nxt]["zh"], seq[nxt]["en"]


def main():
    parser = argparse.ArgumentParser(description="YIMU Studio Release Tool")
    parser.add_argument("version", nargs="?", help="New version to release (e.g. 9.0.1, 9.1.0)")
    parser.add_argument("--codename", default="", help="可选：指定中文代号（须已在代号序列中登记）")
    parser.add_argument("--codename-en", default="", help="可选：英文代号（默认取序列内的英文名）")
    parser.add_argument("--status", action="store_true", help="Display current release status")
    args = parser.parse_args()

    if args.status or not args.version:
        print_status()
        if not args.version:
            print("\n💡 提示：升级新版本示例: python scripts/release.py 15.9.4")
        return

    new_ver = args.version.lstrip("v").strip()
    if not re.match(r"^\d+\.\d+\.\d+$", new_ver):
        print(f"❌ 错误: 版本号 '{new_ver}' 不符合语义化版本规范 (X.Y.Z，如 9.0.1)")
        sys.exit(1)

    cur_ver = get_current_version()
    if new_ver == cur_ver:
        print(f"❌ 错误: 新版本号与当前版本相同（V{cur_ver}），无需步进。")
        sys.exit(1)

    state = _read_registry()
    try:
        zh, en = resolve_codename(args.codename, state)
    except ValueError as exc:
        print(f"❌ 错误: {exc}")
        sys.exit(1)
    if args.codename_en:
        en = args.codename_en

    print(f"🚀 准备从 V{cur_ver} 升级至 V{new_ver}（{zh} · {en}）...")

    _bump_version_py(new_ver, zh, en)
    print(f"✅ version.py            → __version__ = {new_ver} / {zh} · {en}")
    _bump_pyproject(new_ver, zh, en)
    print(f"✅ pyproject.toml        → version = {new_ver}")
    _bump_locales(new_ver, zh, en)
    print("✅ 中英语言包            → version / codename 已对齐")
    _bump_badges(new_ver)
    print("✅ README 徽章           → 已对齐")
    try:
        new_state = _bump_registry(new_ver, zh, en)
    except ValueError as exc:
        print(f"❌ 错误: {exc}")
        sys.exit(1)
    print(f"✅ release-codenames.json → 当前 {new_ver}，下一代号 {new_state['sequence'][new_state['next_index']]['zh']}")
    print("\n💡 还差两步（脚本不代劳，避免空提交）：")
    print(f"1. 在 CHANGELOG.md / RELEASES.md 顶部补 V{new_ver} 的更新说明；")
    print("2. bash ci.sh 全绿后：")
    print(f"   git commit -am 'release(v{new_ver}): {zh} · <一句话主题>'")
    print(f"   git tag -a v{new_ver} -m 'Release v{new_ver}'")
    print("   git push origin main --tags   # 推 tag 即触发三平台构建与 Release 发布")


if __name__ == "__main__":
    main()
