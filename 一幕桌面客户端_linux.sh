#!/usr/bin/env bash
# ============================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - Linux 独立桌面客户端启动器
#  官网: https://yimu.hyipf.com
# ============================================================
set -euo pipefail
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
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

if [ -f "app/launch_desktop.py" ]; then
  exec "$PY" app/launch_desktop.py
fi
exec "$PY" desktop.py
