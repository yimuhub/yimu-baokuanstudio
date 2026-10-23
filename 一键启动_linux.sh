#!/usr/bin/env bash
# ==============================================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - Linux 原生生产与云服务器一键启动管理脚本
#  官方网站: https://yimu.hyipf.com
#  支持环境: Ubuntu / Debian / CentOS / RHEL / Rocky / Fedora / Arch / Alpine
#  使用方法:
#    ./一键启动_linux.sh          (启动服务，若已启动则显示状态)
#    ./一键启动_linux.sh start    (启动后台守护)
#    ./一键启动_linux.sh stop     (停止服务)
#    ./一键启动_linux.sh restart  (重启服务)
#    ./一键启动_linux.sh status   (查看运行状态与健康检查)
#    ./一键启动_linux.sh logs     (实时追踪运行日志)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8790}"
HOST="${HOST:-0.0.0.0}"
PID_FILE="runs/yimu.pid"
LOG_FILE="logs/web.out"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

mkdir -p data/topics data/drafts data/cards data/cookies logs runs

banner() {
  echo -e "${PURPLE}╔════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${PURPLE}║${NC}   ${CYAN}一幕·YIMU 爆款工作室 (YIMU Studio) - Linux 专版${NC}             ${PURPLE}║${NC}"
  echo -e "${PURPLE}║${NC}   官网: ${BLUE}https://yimu.hyipf.com${NC} · 纯自研全媒体超级创作引擎      ${PURPLE}║${NC}"
  echo -e "${PURPLE}╚════════════════════════════════════════════════════════════════╝${NC}"
}

check_python() {
  local py_candidates=("python3.12" "python3.11" "python3.10" "python3")
  local found=""
  for cmd in "${py_candidates[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
        found="$cmd"
        break
      fi
    fi
  done

  if [ -z "$found" ]; then
    echo -e "${RED}[错误] 未检测到符合要求的 Python 3.10+。${NC}"
    echo -e "${YELLOW}请使用系统包管理器安装 Python 3.10+ 及 venv 组件：${NC}"
    echo -e "  - Ubuntu / Debian: ${GREEN}sudo apt update && sudo apt install -y python3 python3-venv python3-pip curl${NC}"
    echo -e "  - CentOS / RHEL:   ${GREEN}sudo yum install -y python3 python3-pip curl${NC}"
    exit 1
  fi
  echo "$found"
}

setup_env() {
  local sys_py
  sys_py=$(check_python)

  if [ ! -d ".venv" ]; then
    echo -e "${CYAN}[1/4] 首次运行，正在创建虚拟运行环境 (.venv)...${NC}"
    "$sys_py" -m venv .venv || {
      echo -e "${RED}[错误] 虚拟环境创建失败。若在 Debian/Ubuntu 下，请执行: sudo apt install -y python3-venv${NC}"
      exit 1
    }
  fi

  if ! .venv/bin/python -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo -e "${CYAN}[2/4] 正在安装与同步运行依赖库 (requirements.txt)...${NC}"
    .venv/bin/pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >/dev/null 2>&1 || true
    .venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || {
      echo -e "${RED}[错误] 依赖安装失败，请检查网络连接。${NC}"
      exit 1
    }
  fi

  # 环境变量与安全密钥配置
  if [ ! -f ".env" ]; then
    echo -e "${CYAN}[3/4] 自动生成高强度安全凭证 (.env)...${NC}"
    local secret
    secret=$(.venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
    local apass="yimu-888888"
    cat <<EOF > .env
YIMU_SECRET_KEY=${secret}
ADMIN_PASSWORD=${apass}
EOF
  fi

  # 自动自愈表约束与对齐数据库结构
  .venv/bin/python -c "from core.db import auto_heal_all_sqlite_databases; auto_heal_all_sqlite_databases(); from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine)" 2>/dev/null || true
}

get_server_ip() {
  local ip=""
  # 优先尝试获取外网/公网 IP
  ip=$(curl -s --max-time 1.5 https://api.ipify.org 2>/dev/null || curl -s --max-time 1.5 ifconfig.me 2>/dev/null || true)
  if [ -z "$ip" ]; then
    # 尝试获取局域网 IP
    ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
  fi
  echo "${ip:-127.0.0.1}"
}

is_running() {
  if [ -f "$PID_FILE" ]; then
    local pid
    pid=$(cat "$PID_FILE")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  # 检查端口占用是否为 uvicorn
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids=$(lsof -ti:"$PORT" 2>/dev/null || true)
    if [ -n "$pids" ]; then
      return 0
    fi
  fi
  return 1
}

start_server() {
  banner
  if is_running; then
    echo -e "${YELLOW}[提示] 服务已经在运行中！${NC}"
    status_server
    return 0
  fi

  setup_env

  echo -e "${CYAN}[4/4] 启动高并发服务端并开启后台守护...${NC}"

  # 释放异常占用的旧端口
  if command -v lsof >/dev/null 2>&1; then
    local stale_pid
    stale_pid=$(lsof -ti:"$PORT" 2>/dev/null || true)
    if [ -n "$stale_pid" ]; then
      echo -e "${YELLOW}释放已占用的旧进程 PID: $stale_pid${NC}"
      kill -9 $stale_pid 2>/dev/null || true
      sleep 1
    fi
  fi

  set -a
  source .env
  set +a

  export PYTHONUNBUFFERED=1
  nohup .venv/bin/python -m uvicorn web.admin:app --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
  local new_pid=$!
  echo "$new_pid" > "$PID_FILE"

  sleep 1.5
  if kill -0 "$new_pid" 2>/dev/null; then
    local s_ip
    s_ip=$(get_server_ip)
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✅ 一幕·YIMU 爆款工作室已成功在 Linux 后台启动！${NC}"
    echo -e "   🔹 运行进程 PID: ${YELLOW}${new_pid}${NC}"
    echo -e "   🔹 本地访问地址: ${CYAN}http://127.0.0.1:${PORT}${NC}"
    echo -e "   🔹 服务器外网地址: ${CYAN}http://${s_ip}:${PORT}${NC}"
    echo -e "   🔹 默认管理员密码: ${YELLOW}${ADMIN_PASSWORD:-yimu-888888}${NC}"
    echo -e "   🔹 实时日志路径: ${BLUE}${LOG_FILE}${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}常用管理命令：${NC}"
    echo -e "  查看状态: ${GREEN}./一键启动_linux.sh status${NC}"
    echo -e "  查看日志: ${GREEN}./一键启动_linux.sh logs${NC}"
    echo -e "  停止服务: ${GREEN}./一键启动_linux.sh stop${NC}"
    echo -e "  重启服务: ${GREEN}./一键启动_linux.sh restart${NC}"
    echo -e "  一键升级: ${GREEN}./一键升级_linux.sh${NC}"
  else
    echo -e "${RED}[错误] 启动失败，查看日志尾部：${NC}"
    tail -n 20 "$LOG_FILE" || true
    rm -f "$PID_FILE"
    exit 1
  fi
}

stop_server() {
  banner
  echo -e "${CYAN}正在停止一幕·YIMU 服务...${NC}"
  local stopped=0
  if [ -f "$PID_FILE" ]; then
    local pid
    pid=$(cat "$PID_FILE")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
      stopped=1
    fi
    rm -f "$PID_FILE"
  fi

  if command -v lsof >/dev/null 2>&1; then
    local stale_pids
    stale_pids=$(lsof -ti:"$PORT" 2>/dev/null || true)
    if [ -n "$stale_pids" ]; then
      kill -9 $stale_pids 2>/dev/null || true
      stopped=1
    fi
  fi

  if [ $stopped -eq 1 ]; then
    echo -e "${GREEN}✅ 服务已安全停止。${NC}"
  else
    echo -e "${YELLOW}[提示] 未发现正在运行的服务。${NC}"
  fi
}

status_server() {
  if is_running; then
    local pid=""
    [ -f "$PID_FILE" ] && pid=$(cat "$PID_FILE")
    echo -e "${GREEN}● 一幕·YIMU 正在健康运行中${NC} (PID: ${YELLOW}${pid:-运行中}${NC}, 监听端口: ${PORT})"
    local s_ip
    s_ip=$(get_server_ip)
    echo -e "  本地地址: ${CYAN}http://127.0.0.1:${PORT}${NC}"
    echo -e "  远程地址: ${CYAN}http://${s_ip}:${PORT}${NC}"
  else
    echo -e "${RED}○ 一幕·YIMU 未运行${NC}"
  fi
}

logs_server() {
  if [ -f "$LOG_FILE" ]; then
    echo -e "${CYAN}正在追踪服务实时日志 (按 Ctrl+C 退出)...${NC}"
    tail -f "$LOG_FILE"
  else
    echo -e "${YELLOW}暂无日志文件 ($LOG_FILE)${NC}"
  fi
}

ACTION="${1:-start}"
case "$ACTION" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    sleep 1
    start_server
    ;;
  status)
    banner
    status_server
    ;;
  logs)
    logs_server
    ;;
  *)
    echo "使用方式: $0 {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
