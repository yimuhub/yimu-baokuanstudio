#!/usr/bin/env bash
# ==============================================================================
#  一幕·YIMU 爆款工作室 - macOS .dmg 全功能离线安装包
#  基于 dist/bundle_mac（自带 Python / 全量依赖 / 内置 Chromium / 出厂配额）
#  不再要求客户 brew install python，也不在客户机上建 venv / 跑 pip。
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
FULL_BUNDLE="$DIST_DIR/bundle_mac"

cd "$ROOT_DIR"

VERSION="$(python3 -c "import version; print(version.__version__)")"
APP_NAME="一幕·YIMU 爆款工作室"
DMG_STAGE="$DIST_DIR/dmg_stage_$(date +%s)"
APP_BUNDLE="$DMG_STAGE/$APP_NAME.app"
OUTPUT_DMG="$DIST_DIR/YIMU-Studio-macOS-v$VERSION.dmg"

echo "============================================================"
echo "  开始构建 macOS 全功能离线安装包 (.dmg): V$VERSION"
echo "============================================================"

if [ ! -f "$FULL_BUNDLE/MANIFEST.json" ]; then
  echo "未发现完整 bundle，先构建全功能离线包 ..."
  python3 scripts/build_full_bundle.py --platform mac --no-pack
fi
if ! grep -q 'A2-full-offline' "$FULL_BUNDLE/MANIFEST.json"; then
  echo "错误: bundle_mac 不是 A2 全功能离线包，拒绝产出只有源码的安装器" >&2
  exit 1
fi

mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources/bundle"

cat <<EOF > "$APP_BUNDLE/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>zh_CN</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleExecutable</key>
    <string>yimu-launcher</string>
    <key>CFBundleIdentifier</key>
    <string>com.yimu.baokuanstudio</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>YIMU Studio</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

cat <<'EOF' > "$APP_BUNDLE/Contents/MacOS/yimu-launcher"
#!/bin/bash
set -u
BUNDLE="$(cd "$(dirname "$0")/../Resources/bundle" && pwd)"
cd "$BUNDLE/app" || exit 1
exec "$BUNDLE/runtime/bin/python3" "$BUNDLE/app/desktop.py"
EOF
chmod +x "$APP_BUNDLE/Contents/MacOS/yimu-launcher"

echo "正在注入完整离线 bundle ..."
python3 - "$FULL_BUNDLE" "$APP_BUNDLE/Contents/Resources/bundle" <<'PYEOF'
import shutil, sys
shutil.copytree(sys.argv[1], sys.argv[2], dirs_exist_ok=True)
PYEOF
ln -s /Applications "$DMG_STAGE/Applications"

cat <<EOF > "$DMG_STAGE/使用说明.txt"
一幕·YIMU 爆款工作室 V${VERSION} · 全功能离线包

把左侧图标拖入 Applications 即可完成安装，双击启动。
本应用已内置 Python 运行时、全量依赖与浏览器内核，
无需安装 Python / Homebrew / Chrome，也无需联网配置环境。
EOF

echo "正在使用 hdiutil 压制原生 DMG 磁盘映像..."
rm -f "$OUTPUT_DMG"
hdiutil create -volname "${APP_NAME}" -srcfolder "$DMG_STAGE" -ov -format UDZO "$OUTPUT_DMG"

echo "============================================================"
echo "macOS 全功能 DMG 安装包构建成功: $OUTPUT_DMG"
ls -lh "$OUTPUT_DMG"
echo "============================================================"
