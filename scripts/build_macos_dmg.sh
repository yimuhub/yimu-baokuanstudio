#!/usr/bin/env bash
# ==============================================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - macOS .dmg 原生应用安装包构建脚本
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"

cd "$ROOT_DIR"

VERSION="$(python3 -c "import version; print(version.__version__)")"
APP_NAME="一幕·YIMU 爆款工作室"
BUNDLE_DIR="$DIST_DIR/dmg_stage/$APP_NAME.app"
DMG_STAGE="$DIST_DIR/dmg_stage"
OUTPUT_DMG="$DIST_DIR/YIMU-Studio-macOS-v$VERSION.dmg"

echo "============================================================"
echo "  🎬 开始构建 macOS 原生应用安装包 (.dmg): V$VERSION"
echo "============================================================"

# 1. 清理并准备临时构建目录
rm -rf "$DMG_STAGE"
mkdir -p "$BUNDLE_DIR/Contents/MacOS"
mkdir -p "$BUNDLE_DIR/Contents/Resources/app"

# 2. 生成 Info.plist
cat <<EOF > "$BUNDLE_DIR/Contents/Info.plist"
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

# 3. 生成可执行启动脚本 yimu-launcher
cat <<'EOF' > "$BUNDLE_DIR/Contents/MacOS/yimu-launcher"
#!/bin/bash
set -u
APP_DIR="$(cd "$(dirname "$0")/../Resources/app" && pwd)"
cd "$APP_DIR"

# 优先查找 Python 3.10+
PY=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" &>/dev/null; then
    if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
      PY="$candidate"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  for brew_py in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [ -x "$brew_py" ]; then
      PY="$brew_py"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  osascript -e 'display alert "未检测到 Python 3.10+ 环境" message "一幕爆款工作室需要 Python 3.10 以上环境支持。\n请在终端运行 brew install python@3.12 或前往 python.org 官方下载安装。"'
  exit 1
fi

# 检查虚拟环境
if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python desktop.py
EOF
chmod +x "$BUNDLE_DIR/Contents/MacOS/yimu-launcher"

# 4. 复制应用程序代码与资源到 Resources/app
echo "正在注入项目代码与运行时资源..."
cp -R core studio web adapters docs requirements.txt version.py pyproject.toml desktop.py .env.example "$BUNDLE_DIR/Contents/Resources/app/"
mkdir -p "$BUNDLE_DIR/Contents/Resources/app/data" "$BUNDLE_DIR/Contents/Resources/app/logs" "$BUNDLE_DIR/Contents/Resources/app/runs"

# 5. 在 DMG 挂载根目录添加 /Applications 快捷替身软连接
ln -s /Applications "$DMG_STAGE/Applications"

# 6. 生成使用说明
cat <<EOF > "$DMG_STAGE/使用说明.txt"
============================================================
  一幕·YIMU 爆款工作室 (YIMU Studio) macOS 原生应用安装
============================================================

【安装方式】
将左侧的【${APP_NAME}】图标拖入右侧的【Applications (应用程序)】文件夹中即可完成安装。

【启动方式】
安装完成后，在【启动台 (Launchpad)】或【访达 -> 应用程序】中双击图标即可直接开启创作！
EOF

# 7. 打包 DMG
echo "正在使用 hdiutil 压制原生 DMG 磁盘映像..."
rm -f "$OUTPUT_DMG"
hdiutil create -volname "${APP_NAME}" -srcfolder "$DMG_STAGE" -ov -format UDZO "$OUTPUT_DMG"

# 8. 清理临时目录
rm -rf "$DMG_STAGE"

echo "============================================================"
echo "✅ macOS 原生 DMG 安装包打包成功: $OUTPUT_DMG"
ls -lh "$OUTPUT_DMG"
echo "============================================================"
