#!/usr/bin/env bash
# ==============================================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - Linux .deb 原生应用安装包构建脚本
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"

cd "$ROOT_DIR"

VERSION="$(python3 -c "import version; print(version.__version__)")"
PKG_NAME="yimu-studio_${VERSION}_amd64"
STAGE_DIR="$DIST_DIR/deb_stage/$PKG_NAME"
OUTPUT_DEB="$DIST_DIR/$PKG_NAME.deb"

echo "============================================================"
echo "  🐧 开始构建 Linux 原生安装包 (.deb): V${VERSION}"
echo "============================================================"

# 1. 清理并创建 deb 包目录结构
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/DEBIAN"
mkdir -p "$STAGE_DIR/opt/yimu-studio"
mkdir -p "$STAGE_DIR/usr/bin"
mkdir -p "$STAGE_DIR/usr/share/applications"

# 2. 生成 DEBIAN/control 元数据
cat <<EOF > "$STAGE_DIR/DEBIAN/control"
Package: yimu-studio
Version: ${VERSION}
Section: video
Priority: optional
Architecture: amd64
Maintainer: YIMU Studio Team <support@hyipf.com>
Depends: python3 (>= 3.10), python3-venv, python3-pip, curl
Description: 一幕·YIMU 爆款工作室桌面客户端
 全自主 Multi-Agent 全媒体内容与影视短剧创作系统原生桌面客户端，
 支持热榜挖掘、爆款仿写、AI配图、口播TTS与视频渲染。
EOF

# 3. 复制项目代码与资源到 /opt/yimu-studio
echo "正在注入项目代码与运行时资源..."
cp -R core studio web adapters docs requirements.txt version.py pyproject.toml desktop.py .env.example "$STAGE_DIR/opt/yimu-studio/"
mkdir -p "$STAGE_DIR/opt/yimu-studio/data" "$STAGE_DIR/opt/yimu-studio/logs" "$STAGE_DIR/opt/yimu-studio/runs"

# 4. 生成 /usr/bin/yimu-studio 系统命令引导
cat <<'EOF' > "$STAGE_DIR/usr/bin/yimu-studio"
#!/usr/bin/env bash
set -e
INSTALL_DIR="/opt/yimu-studio"
cd "$INSTALL_DIR"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python desktop.py "$@"
EOF
chmod 755 "$STAGE_DIR/usr/bin/yimu-studio"

# 5. 生成系统桌面快捷方式 /usr/share/applications/yimu-studio.desktop
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

# 6. 生成 DEBIAN/postinst
cat <<'EOF' > "$STAGE_DIR/DEBIAN/postinst"
#!/bin/sh
set -e
chmod -R 777 /opt/yimu-studio/data /opt/yimu-studio/logs /opt/yimu-studio/runs 2>/dev/null || true
echo "一幕·YIMU 爆款工作室已成功安装至 /opt/yimu-studio。"
echo "您可以在系统应用菜单搜索【一幕·YIMU 爆款工作室】直接启动，或在终端输入 yimu-studio 启动。"
exit 0
EOF
chmod 755 "$STAGE_DIR/DEBIAN/postinst"

# 7. 打包 DEB (需在 dpkg-deb 可用环境或 Linux runner 中执行)
if command -v dpkg-deb >/dev/null 2>&1; then
  echo "正在使用 dpkg-deb 打包 .deb 安装文件..."
  dpkg-deb --build "$STAGE_DIR" "$OUTPUT_DEB"
  echo "============================================================"
  echo "✅ Linux 原生 DEB 安装包打包成功: $OUTPUT_DEB"
  ls -lh "$OUTPUT_DEB"
  echo "============================================================"
else
  echo "⚠️ 当前系统无 dpkg-deb 工具，构建目录已就绪: $STAGE_DIR"
  echo "💡 该脚本在 GitHub Actions (ubuntu-latest) 流水线中将全自动打包输出 .deb 安装包。"
fi
