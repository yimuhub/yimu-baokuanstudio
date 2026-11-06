#!/usr/bin/env bash
# ==============================================================================
#  一幕·YIMU 爆款工作室 - Linux .deb 全功能离线安装包
#  基于 dist/bundle_linux（自带 Python / 全量依赖 / 内置 Chromium / 出厂配额）
#  客户机上不装 Python、不建 venv、不跑 pip、不联网即可启动。
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
BUNDLE_DIR="$DIST_DIR/bundle_linux"

cd "$ROOT_DIR"

VERSION="$(python3 -c "import version; print(version.__version__)")"
PKG_NAME="yimu-studio_${VERSION}_amd64"
STAGE_DIR="$DIST_DIR/deb_stage/$PKG_NAME"
OUTPUT_DEB="$DIST_DIR/$PKG_NAME.deb"

echo "============================================================"
echo "  开始构建 Linux 全功能离线安装包 (.deb): V${VERSION}"
echo "============================================================"

if [ ! -f "$BUNDLE_DIR/MANIFEST.json" ]; then
  echo "未发现完整 bundle，先构建全功能离线包 ..."
  python3 scripts/build_full_bundle.py --platform linux --no-pack
fi
if ! grep -q 'A2-full-offline' "$BUNDLE_DIR/MANIFEST.json"; then
  echo "错误: bundle_linux 不是 A2 全功能离线包，拒绝产出只有源码的安装器" >&2
  exit 1
fi

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/DEBIAN" "$STAGE_DIR/opt/yimu-studio" "$STAGE_DIR/usr/bin" "$STAGE_DIR/usr/share/applications"

# Depends 只保留内置 Chromium 与原生窗口需要的系统图形/音频库；
# 系统 Python 与 pip 不再是依赖，apt 也不会在客户机上跑任何安装脚本。
cat <<EOF > "$STAGE_DIR/DEBIAN/control"
Package: yimu-studio
Version: ${VERSION}
Section: video
Priority: optional
Architecture: amd64
Maintainer: YIMU Studio Team <support@hyipf.com>
Depends: libc6, libnss3, libatk-bridge2.0-0, libgtk-3-0, libgbm1, libasound2, libxss1
Description: 一幕·YIMU 爆款工作室桌面客户端（全功能离线版）
 全自主 Multi-Agent 全媒体内容与影视短剧创作系统。
 内置 Python 运行时、全量依赖与浏览器内核，安装后即可离线启动。
EOF

echo "正在注入完整离线 bundle ..."
cp -R "$BUNDLE_DIR"/. "$STAGE_DIR/opt/yimu-studio/"

cat <<'EOF' > "$STAGE_DIR/usr/bin/yimu-studio"
#!/usr/bin/env bash
set -e
INSTALL_DIR="/opt/yimu-studio"
cd "$INSTALL_DIR/app"
exec "$INSTALL_DIR/runtime/bin/python3" "$INSTALL_DIR/app/desktop.py" "$@"
EOF
chmod 755 "$STAGE_DIR/usr/bin/yimu-studio"

cat <<EOF > "$STAGE_DIR/usr/share/applications/yimu-studio.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=一幕·YIMU 爆款工作室
GenericName=影视短剧与爆款图文创作平台
Comment=全自主 Multi-Agent 全媒体内容与影视短剧创作系统
Exec=/usr/bin/yimu-studio
Icon=video-x-generic
Terminal=false
Categories=AudioVideo;Development;AudioVideoEditing;
Keywords=YIMU;Video;Studio;MediaFlow;
EOF
chmod 644 "$STAGE_DIR/usr/share/applications/yimu-studio.desktop"

cat <<'EOF' > "$STAGE_DIR/DEBIAN/postinst"
#!/bin/sh
set -e
chmod -R 777 /opt/yimu-studio/app/data /opt/yimu-studio/app/logs /opt/yimu-studio/app/runs 2>/dev/null || true
chmod 755 /opt/yimu-studio/runtime/bin/python3 /usr/bin/yimu-studio 2>/dev/null || true
echo "一幕·YIMU 爆款工作室已安装完成，直接在应用菜单启动即可（无需安装 Python 或配置环境）。"
exit 0
EOF
chmod 755 "$STAGE_DIR/DEBIAN/postinst"

if command -v dpkg-deb >/dev/null 2>&1; then
  echo "正在使用 dpkg-deb 打包 .deb 安装文件..."
  dpkg-deb --build "$STAGE_DIR" "$OUTPUT_DEB"
  echo "============================================================"
  echo "Linux 全功能 DEB 安装包构建成功: $OUTPUT_DEB"
  ls -lh "$OUTPUT_DEB"
  echo "============================================================"
else
  echo "当前系统无 dpkg-deb，构建目录已就绪: $STAGE_DIR"
fi
