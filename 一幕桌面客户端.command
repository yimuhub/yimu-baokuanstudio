#!/bin/bash
# ============================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - macOS 独立桌面客户端启动器
#  双击此文件即可直接打开一幕独立桌面客户端窗口
#  官网: https://yimu.hyipf.com
# ============================================================
set -eu
cd "$(dirname "$0")"

# 1. 优先使用便携运行时或已配置虚拟环境
PY=""
if [ -f "runtime/bin/python3" ]; then
  PY="runtime/bin/python3"
elif [ -f ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  # 首次启动若无环境，转入标准一键引导配置
  ./一键启动.command
  exit 0
fi

# 2. 启动原生桌面应用
exec "$PY" desktop.py
