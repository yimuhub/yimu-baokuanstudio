#!/usr/bin/env bash
# ============================================================
#  一幕·YIMU 爆款工作室 - Unix (macOS / Linux) 通用一键升级脚本
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

OS_NAME="$(uname -s)"
if [ "$OS_NAME" = "Darwin" ]; then
  exec ./一键升级.command "$@"
else
  exec ./一键升级_linux.sh "$@"
fi
