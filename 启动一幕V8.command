#!/bin/bash
# ============================================================
#  一幕·YIMU 爆款工作室 V8 - macOS 启动脚本
#  端口 8790
#  双击此文件即可启动；浏览器自动打开
# ============================================================
set -u
cd "$(dirname "$0")"
PORT=8790

trap 'echo ""; echo "按回车关闭窗口..."; read -r _' EXIT

clear
echo "╔══════════════════════════════════════════════════════╗"
echo "║        一幕·YIMU 爆款工作室 V8 启动                  ║"
echo "║        访问地址：http://127.0.0.1:${PORT}             ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 1. Python 检测
PY=""
for cmd in python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" &>/dev/null; then
    if "$cmd" -c "import sys; exit(0 if sys.version_info[:2] >= (3,10) else 1)" 2>/dev/null; then
      PY="$cmd"; break
    fi
  fi
done
if [ -z "$PY" ]; then echo "  ❌ 未找到 Python 3.10+，请先安装"; exit 1; fi

# 2. 虚拟环境与依赖
if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv || { echo "  ❌ 虚拟环境创建失败"; exit 1; }
fi

if ! .venv/bin/python -c "import fastapi, uvicorn" &>/dev/null; then
  .venv/bin/pip install -r requirements.txt || { echo "  ❌ 依赖安装失败"; exit 1; }
fi

# 3. 环境变量
if [ -f ".v7-test.env" ]; then
  set -a; source .v7-test.env; set +a
elif [ ! -f ".env" ]; then
  SECRET=$(.venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
  APASS="yimu-888888"
  printf 'YIMU_SECRET_KEY=%s\nADMIN_PASSWORD=%s\n' "$SECRET" "$APASS" > .v7-test.env
  set -a; source .v7-test.env; set +a
fi

# 4. 目录准备
mkdir -p data/topics data/drafts data/cards data/cookies logs runs

# 5. 端口释放
OLD_PID=$(lsof -ti:$PORT 2>/dev/null)
if [ -n "$OLD_PID" ]; then
  kill -9 $OLD_PID 2>/dev/null; sleep 1
fi

export PYTHONUNBUFFERED=1
nohup .venv/bin/python -m uvicorn web.admin:app --host 127.0.0.1 --port $PORT > logs/web.out 2>&1 &

READY=0
for i in $(seq 1 30); do
  if curl -s -o /dev/null http://127.0.0.1:$PORT/ 2>/dev/null; then READY=1; break; fi
  sleep 1
done

if [ "$READY" = "1" ]; then
  open "http://127.0.0.1:$PORT/"
  echo "  🎉 一幕·YIMU 爆款工作室 V8 启动成功！"
  echo "  🌐 访问地址：http://127.0.0.1:$PORT/"
  echo "  📱 移动端：http://127.0.0.1:$PORT/m"
  echo "  📄 日志文件：logs/web.out"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  trap - EXIT
  tail -f logs/web.out
else
  echo "  ❌ 启动失败，请检查日志 logs/web.out"
  tail -30 logs/web.out 2>/dev/null
fi
