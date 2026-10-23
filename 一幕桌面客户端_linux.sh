#!/usr/bin/env bash
# ============================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - Linux 独立桌面客户端启动器
#  官网: https://yimu.hyipf.com
# ============================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=""
if [ -f "runtime/bin/python3" ]; then
  PY="runtime/bin/python3"
elif [ -f ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  ./一键启动_linux.sh start
  exit 0
fi

exec "$PY" desktop.py
