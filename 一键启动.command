#!/bin/bash
# ============================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - macOS 一键启动
#  端口: 8790
#  双击此文件即可启动；系统将自动在默认浏览器中打开
#  官网: https://yimu.hyipf.com
# ============================================================
set -u
cd "$(dirname "$0")"
PORT="${PORT:-8790}"
HOST="${HOST:-127.0.0.1}"

trap 'echo ""; echo "按回车关闭窗口..."; read -r _' EXIT

clear
echo "╔══════════════════════════════════════════════════════╗"
echo "║        一幕·YIMU 爆款工作室 - macOS 一键启动         ║"
echo "║        访问地址: http://127.0.0.1:${PORT}             ║"
echo "║        官方网站: https://yimu.hyipf.com              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 1. 查找 Python 3.10+
PY=""
for cmd in python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" &>/dev/null; then
    if "$cmd" -c "import sys; exit(0 if sys.version_info[:2] >= (3,10) else 1)" 2>/dev/null; then
      PY="$cmd"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "  ❌ 未找到 Python 3.10+，请先安装 Python（推荐 brew install python@3.12 或官网下载）"
  exit 1
fi

# 2. 虚拟环境检测与创建
if [ ! -d ".venv" ]; then
  echo "  📦 首次运行，正在创建虚拟环境 .venv..."
  "$PY" -m venv .venv || { echo "  ❌ 虚拟环境创建失败"; exit 1; }
fi

# 3. 依赖检查
if ! .venv/bin/python -c "import fastapi, uvicorn" &>/dev/null; then
  echo "  📦 正在安装运行依赖..."
  .venv/bin/pip install -r requirements.txt || { echo "  ❌ 依赖安装失败"; exit 1; }
fi

# 4. 环境变量与安全配置（自动生成随机高强度口令，杜绝写死弱口令）
if [ -f ".env" ]; then
  set -a; source .env; set +a
else
  echo "  🔑 自动生成安全密钥配置 (.env)..."
  SECRET=$(.venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
  APASS="yimu-$(.venv/bin/python -c "import secrets; print(secrets.token_hex(4))")"
  printf 'YIMU_SECRET_KEY=%s\nADMIN_PASSWORD=%s\n' "$SECRET" "$APASS" > .env
  chmod 600 .env 2>/dev/null || true
  set -a; source .env; set +a
fi

# 5. 准备目录
mkdir -p data/topics data/drafts data/cards data/cookies logs runs

# 6. 对齐数据库表结构
.venv/bin/python -c "from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine)" 2>/dev/null

# 7. 释放旧端口
OLD_PID="$(lsof -ti:$PORT 2>/dev/null || true)"
if [ -n "${OLD_PID:-}" ]; then
  echo "  🔄 发现旧进程 PID: $OLD_PID，正在重启释放端口..."
  kill -9 $OLD_PID 2>/dev/null || true; sleep 1
fi

# 8. 启动服务并在前台/后台就绪（默认仅绑定本机 127.0.0.1，防公共 Wi-Fi/局域网暴露）
export PYTHONUNBUFFERED=1
echo "  🚀 正在启动后台服务并打开浏览器..."
nohup .venv/bin/python -m uvicorn web.admin:app --host "$HOST" --port "$PORT" > logs/web.out 2>&1 &
SERVER_PID=$!

sleep 2
if ps -p $SERVER_PID > /dev/null; then
  echo "  ✅ 服务已成功在后台启动 (PID: $SERVER_PID)"
  echo "  🌐 本地地址: http://127.0.0.1:${PORT}"
  echo "  🔑 管理口令: ${ADMIN_PASSWORD:-请查看 .env}"
  open "http://127.0.0.1:${PORT}"
  echo ""
  echo "  💡 提示：按 Ctrl+C 可停止日志查看，后台服务仍将安全运行；如需关闭服务可运行: kill $SERVER_PID"
  echo "  📋 实时输出如下："
  echo "──────────────────────────────────────────────────────"
  tail -f logs/web.out
else
  echo "  ❌ 启动失败，请检查 logs/web.out 查看详细错误："
  cat logs/web.out
  exit 1
fi
