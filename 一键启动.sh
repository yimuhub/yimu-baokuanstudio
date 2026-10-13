#!/usr/bin/env bash
# ============================================================
#  一幕·YIMU 爆款工作室 - Unix (macOS / Linux) 通用一键启动脚本
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

OS_NAME="$(uname -s)"
if [ "$OS_NAME" = "Darwin" ]; then
  exec ./一键启动.command "$@"
else
  exec ./一键启动_linux.sh "$@"
fi
