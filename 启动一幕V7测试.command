#!/bin/bash
# ============================================================
#  一幕·YIMU 爆款工作室 V7 — 测试启动脚本
#  端口 18790（旧项目用 8790，互不冲突）
#  双击此文件即可启动；关闭终端窗口则服务停止
# ============================================================
set -u
cd "$(dirname "$0")"
PORT=18790

trap 'echo ""; echo "脚本已结束，按回车关闭窗口..."; read -r _' EXIT

clear
echo "╔══════════════════════════════════════════════════════╗"
echo "║        一幕·YIMU 爆款工作室 V7  测试启动             ║"
echo "║        端口 ${PORT}（与旧项目 8790 不冲突）          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. Python 检测 ──
echo "【1/5】检测 Python..."
PY=""
for cmd in python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" &>/dev/null; then
    if "$cmd" -c "import sys; exit(0 if sys.version_info[:2] >= (3,10) else 1)" 2>/dev/null; then
      PY="$cmd"; break
    fi
  fi
done
if [ -z "$PY" ]; then echo "  ❌ 未找到 Python 3.10+，请先安装"; exit 1; fi
echo "  ✅ $($PY --version 2>&1)"

# ── 2. 虚拟环境 ──
echo "【2/5】准备虚拟环境..."
if [ -d ".venv" ]; then
  echo "  ✅ 已存在"
else
  echo "  📦 首次创建..."
  "$PY" -m venv .venv || { echo "  ❌ 创建失败"; exit 1; }
fi

# ── 3. 依赖 ──
echo "【3/5】检查依赖..."
if .venv/bin/python -c "import fastapi, uvicorn" &>/dev/null; then
  echo "  ✅ 已就绪"
else
  echo "  📦 安装中（首次约 2-5 分钟，请勿关闭）..."
  .venv/bin/pip install -q --upgrade pip 2>/dev/null
  .venv/bin/pip install -r requirements.txt || { echo "  ❌ 安装失败，请检查网络"; exit 1; }
  .venv/bin/pip install -q "sqlalchemy>=2.0" 2>/dev/null || echo "  ⚠️ sqlalchemy 安装失败（主应用不受影响）"
  echo "  ✅ 依赖安装完成"
fi

# ── 4. 测试凭证（持久化，重启不失效） ──
echo "【4/5】准备测试凭证..."
if [ ! -f ".v7-test.env" ]; then
  SECRET=$(.venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
  APASS="yimu-$(.venv/bin/python -c "import secrets; print(secrets.token_hex(3))")"
  printf 'YIMU_SECRET_KEY=%s\nADMIN_PASSWORD=%s\n' "$SECRET" "$APASS" > .v7-test.env
  echo "  🔑 已生成并保存到 .v7-test.env"
else
  echo "  ✅ 已存在"
fi
grep -q '^\.v7-test\.env$' .gitignore 2>/dev/null || echo ".v7-test.env" >> .gitignore
set -a; source .v7-test.env; set +a

# ── 5. 数据目录（程序启动时挂载 data/，不存在会报错） ──
mkdir -p data/topics data/drafts data/cards data/cookies logs

# ── 6. 启动 ──
echo "【6/6】启动服务..."
OLD_PID=$(lsof -ti:$PORT 2>/dev/null)
if [ -n "$OLD_PID" ]; then
  echo "  🔄 关闭 ${PORT} 旧进程..."
  kill -9 $OLD_PID 2>/dev/null; sleep 1
fi
mkdir -p logs
export PYTHONUNBUFFERED=1
nohup .venv/bin/python -m uvicorn web.admin:app --host 127.0.0.1 --port $PORT > logs/v7-test.out 2>&1 &
echo "  ⏳ 等待就绪（最多 60 秒）..."
READY=0
for i in $(seq 1 60); do
  if curl -s -o /dev/null http://127.0.0.1:$PORT/ 2>/dev/null; then READY=1; break; fi
  sleep 1
  printf "  ⏳ %s 秒..."$'\r' "$i"
done
echo ""
if [ "$READY" = "1" ]; then
  APASS_SHOW=$(grep '^ADMIN_PASSWORD=' .v7-test.env | cut -d= -f2)
  open "http://127.0.0.1:$PORT/"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  🎉 V7 测试服务启动成功！"
  echo ""
  echo "  🌐 访问地址：http://127.0.0.1:$PORT/"
  echo "  📱 移动端：http://127.0.0.1:$PORT/m"
  echo "  🔑 管理员口令：$APASS_SHOW"
  echo "  📄 运行日志：logs/v7-test.out"
  echo ""
  echo "  ⚠️ 旧项目（如在运行）仍在 8790，不受影响"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  trap - EXIT
  echo ""
  echo "📋 实时日志（Ctrl+C 停止显示，服务继续运行）："
  tail -f logs/v7-test.out
else
  echo "  ❌ 启动失败，最后 30 行日志："
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  tail -30 logs/v7-test.out 2>/dev/null || echo "  （无日志）"
fi
