#!/usr/bin/env bash
# ==============================================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - Linux 原生一键升级脚本
#  官方网站: https://yimu.hyipf.com
#  支持环境: Ubuntu / Debian / CentOS / RHEL / Rocky / Fedora / Arch / Alpine
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${PURPLE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║${NC}   ${CYAN}一幕·YIMU 爆款工作室 - Linux 一键升级与数据迁移助手${NC}         ${PURPLE}║${NC}"
echo -e "${PURPLE}║${NC}   官网: ${BLUE}https://yimu.hyipf.com${NC} · 纯自研全媒体超级创作引擎      ${PURPLE}║${NC}"
echo -e "${PURPLE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${YELLOW}本工具将自动执行：${NC}"
echo -e "  1. 从官方 GitHub 仓库同步最新代码 (git pull)"
echo -e "  2. 自动升级虚拟环境中的所有 Python 运行依赖 (pip install -r requirements.txt --upgrade)"
echo -e "  3. 自动安全备份本地数据库 (data/mediaflow.db.bak)"
echo -e "  4. 自动无损对齐数据库表结构"
echo -e "  5. 若后台服务正在运行，将自动平滑重启加载最新版本"
echo ""

read -p "是否确认立即开始升级？(y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo -e "${YELLOW}[提示] 用户已取消本次升级。${NC}"
  exit 0
fi

echo ""
echo -e "${CYAN}[1/5] 从 GitHub 拉取最新版本代码...${NC}"
git pull origin main || echo -e "${YELLOW}[警告] git pull 提示有本地修改冲突或网络波动，将继续执行本地环境同步...${NC}"

echo ""
echo -e "${CYAN}[2/5] 检查虚拟运行环境...${NC}"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv || {
    echo -e "${RED}[错误] 创建虚拟环境失败，请确保安装了 python3-venv。${NC}"
    exit 1
  }
fi

echo ""
echo -e "${CYAN}[3/5] 升级并对齐 Python 依赖包...${NC}"
.venv/bin/pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >/dev/null 2>&1 || true
.venv/bin/pip install -r requirements.txt --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple

echo ""
echo -e "${CYAN}[4/5] 备份数据库并无损迁移结构...${NC}"
if [ -f "data/mediaflow.db" ]; then
  cp data/mediaflow.db data/mediaflow.db.bak
  echo -e "${GREEN}  ✅ 数据库已安全备份至: data/mediaflow.db.bak${NC}"
fi

.venv/bin/python -c "from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine); print('  ✅ 数据库架构表结构自动对齐完毕。')"

echo ""
echo -e "${CYAN}[5/5] 执行模块加载自检并平滑重启...${NC}"
.venv/bin/python -c "import studio; print('  ✅ 核心模块加载自检通过。')"

if [ -f "runs/yimu.pid" ]; then
  PID=$(cat runs/yimu.pid 2>/dev/null || true)
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo -e "${YELLOW}检测到后台服务正在运行 (PID: $PID)，正在平滑重启应用新版本...${NC}"
    ./一键启动_linux.sh restart
  fi
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   🎉 升级圆满完成！一幕·YIMU 爆款工作室已升级至最新版本！     ║${NC}"
echo -e "${GREEN}║   您可随时运行: ./一键启动_linux.sh start 启动后台守护         ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
