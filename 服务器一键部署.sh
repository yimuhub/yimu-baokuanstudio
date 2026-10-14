#!/usr/bin/env bash
# ==============================================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - 服务器一键部署脚本 (Server Auto-Deployer)
#  官方网站: https://yimu.hyipf.com
#  版本: V9.4.1
#  支持系统: Ubuntu 20.04+ / Debian 11+ / CentOS 8+ / RHEL 8+ / Rocky Linux / Fedora / Arch / Alpine
#
#  使用方法:
#    方式一（本地仓库内执行）：
#      chmod +x 服务器一键部署.sh && ./服务器一键部署.sh
#
#    方式二（全新空服务器单行命令部署）：
#      curl -fsSL https://raw.githubusercontent.com/yimuhub/yimu-baokuanstudio/main/服务器一键部署.sh | bash
# ==============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

PORT="${PORT:-8790}"
REPO_URL="https://github.com/yimuhub/yimu-baokuanstudio.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/yimu-baokuanstudio}"
CURRENT_DIR="$(pwd)"

banner() {
  echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${PURPLE}║${NC}   ${CYAN}🎬 一幕·YIMU 爆款工作室 (YIMU Studio) - 服务器生产环境一键部署${NC}      ${PURPLE}║${NC}"
  echo -e "${PURPLE}║${NC}   版本: ${GREEN}V9.4.1${NC} · 官网: ${BLUE}https://yimu.hyipf.com${NC} · 自动化云原生部署中枢     ${PURPLE}║${NC}"
  echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
  echo ""
}

log_step() {
  echo -e "${CYAN}▶ [$1] $2${NC}"
}

log_succ() {
  echo -e "${GREEN}  ✔ $1${NC}"
}

log_warn() {
  echo -e "${YELLOW}  ⚠ $1${NC}"
}

log_err() {
  echo -e "${RED}  ✖ [错误] $1${NC}"
}

# 1. 检查权限与是否具备 sudo
IS_ROOT=0
if [ "$(id -u)" -eq 0 ]; then
  IS_ROOT=1
fi

SUDO=""
if [ "$IS_ROOT" -eq 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    log_warn "当前不是 root 用户且未找到 sudo，若缺少系统底层依赖可能会提示权限不足。"
  fi
fi

# 2. 识别 Linux 发行版与包管理器
detect_pm() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v yum >/dev/null 2>&1; then
    echo "yum"
  elif command -v pacman >/dev/null 2>&1; then
    echo "pacman"
  elif command -v apk >/dev/null 2>&1; then
    echo "apk"
  else
    echo "unknown"
  fi
}

install_system_deps() {
  log_step "1/6" "检测并安装服务器系统核心依赖 (Git, Python 3.10+, venv, FFmpeg, Curl)..."
  local pm
  pm=$(detect_pm)

  case "$pm" in
    apt)
      log_succ "检测到 Debian/Ubuntu 系列，使用 apt 更新并安装依赖..."
      $SUDO apt-get update -y
      $SUDO apt-get install -y git curl wget python3 python3-venv python3-pip ffmpeg sqlite3 lsof build-essential
      ;;
    dnf|yum)
      log_succ "检测到 RHEL/CentOS/Rocky 系列，使用 $pm 安装依赖..."
      $SUDO "$pm" install -y git curl wget python3 python3-pip sqlite lsof gcc
      # 尝试安装 ffmpeg (EPEL / RPM Fusion)
      if ! command -v ffmpeg >/dev/null 2>&1; then
        $SUDO "$pm" install -y epel-release || true
        $SUDO "$pm" install -y ffmpeg || log_warn "未能直接安装 ffmpeg，视频生成模块建议后续自行编译或通过包源补充"
      fi
      ;;
    pacman)
      log_succ "检测到 Arch Linux，使用 pacman 安装依赖..."
      $SUDO pacman -Sy --noconfirm git curl python python-pip ffmpeg sqlite lsof
      ;;
    apk)
      log_succ "检测到 Alpine Linux，使用 apk 安装依赖..."
      $SUDO apk update
      $SUDO apk add git curl python3 py3-pip ffmpeg sqlite lsof bash build-base
      ;;
    *)
      log_warn "未识别到主流包管理器，跳过系统依赖自动安装，请确保已安装 Python 3.10+、Git、Curl。"
      ;;
  esac
  log_succ "系统底层运行环境检查完毕。"
}

# 3. 部署代码目录
setup_source_code() {
  log_step "2/6" "部署与对齐工作室源码..."
  # 判断当前目录下是否已经是本项目
  if [ -f "version.py" ] && [ -d "studio" ] && [ -d "web" ]; then
    TARGET_DIR="$(pwd)"
    log_succ "检测到已处于一幕代码仓库根目录: $TARGET_DIR"
    git pull origin main || log_warn "本地已有改动或网络波动，保持当前源码继续部署"
  else
    TARGET_DIR="$INSTALL_DIR"
    log_succ "目标部署目录: $TARGET_DIR"
    if [ ! -d "$TARGET_DIR" ]; then
      $SUDO mkdir -p "$TARGET_DIR"
      if [ "$IS_ROOT" -eq 1 ]; then
        git clone "$REPO_URL" "$TARGET_DIR"
      else
        $SUDO chown -R "$(whoami)" "$TARGET_DIR"
        git clone "$REPO_URL" "$TARGET_DIR"
      fi
    else
      cd "$TARGET_DIR"
      git pull origin main || log_warn "已存在目录，拉取最新代码中..."
    fi
  fi
  cd "$TARGET_DIR"
}

# 4. 虚拟环境与 Python 依赖安装
setup_python_env() {
  log_step "3/6" "配置 Python 独立虚拟环境 (.venv) 与安装依赖库..."
  local py=""
  for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
      if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
        py="$cmd"
        break
      fi
    fi
  done

  if [ -z "$py" ]; then
    log_err "未找到符合要求的 Python 3.10+，请先安装。"
    exit 1
  fi

  if [ ! -d ".venv" ]; then
    log_succ "创建全新虚拟环境: $py -m venv .venv"
    "$py" -m venv .venv
  fi

  log_succ "升级 pip 并使用高速镜像安装 requirements.txt 生产依赖..."
  .venv/bin/pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >/dev/null 2>&1 || true
  .venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || {
    log_warn "清华源超时，正在切换官方 PyPI 源重试..."
    .venv/bin/pip install -r requirements.txt
  }
  log_succ "Python 核心依赖安装完毕。"
}

# 5. 生产配置与密钥初始化
setup_config() {
  log_step "4/6" "初始化生产配置、目录结构与高强度安全密钥..."
  mkdir -p data/topics data/drafts data/cards data/cookies logs runs

  if [ ! -f ".env" ]; then
    log_succ "自动生成高强度随机生产秘钥与管理员凭证 (.env)..."
    local secret
    secret=$(.venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
    local rand_pass
    rand_pass="yimu-$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(4))')"
    cat <<EOF > .env
# 一幕·YIMU 爆款工作室生产环境配置文件
YIMU_SECRET_KEY=${secret}
ADMIN_PASSWORD=${rand_pass}
PORT=${PORT}
EOF
    log_succ "已生成高强度随机密码: $rand_pass (后续可在 .env 中修改)"
  else
    log_succ "已检测到现存 .env 生产配置文件，予以保留。"
  fi

  log_succ "自动初始化并无损迁移数据库架构..."
  .venv/bin/python -c "from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine)"
  log_succ "数据库结构对齐完毕。"
}

# 6. 配置 Systemd 开机自启服务（仅 Linux 具备 systemd 时）
setup_systemd_service() {
  log_step "5/6" "配置 Systemd 系统服务 (开机自启与进程守护)..."
  if command -v systemctl >/dev/null 2>&1 && [ -d "/etc/systemd/system" ] && [ -n "$SUDO" -o "$IS_ROOT" -eq 1 ]; then
    local svc_file="/etc/systemd/system/yimu.service"
    local run_user
    run_user="$(whoami)"
    local app_dir
    app_dir="$(pwd)"

    $SUDO bash -c "cat <<EOF > $svc_file
[Unit]
Description=YIMU Studio (一幕·YIMU 爆款工作室) Production Service
After=network.target

[Service]
Type=simple
User=${run_user}
WorkingDirectory=${app_dir}
EnvironmentFile=${app_dir}/.env
ExecStart=${app_dir}/.venv/bin/python -m uvicorn web.admin:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5
StandardOutput=append:${app_dir}/logs/web.out
StandardError=append:${app_dir}/logs/web.out

[Install]
WantedBy=multi-user.target
EOF"

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable yimu.service
    $SUDO systemctl restart yimu.service
    log_succ "Systemd 服务已创建并启动：yimu.service (开机自启已生效)"
  else
    log_warn "环境不支持 systemd 或无 root/sudo 权限，将采用原生一键脚本启动守护模式..."
    chmod +x 一键启动_linux.sh
    ./一键启动_linux.sh restart
  fi
}

# 7. 探测服务器网络与最终面板
show_summary() {
  log_step "6/6" "检测网络连通性与服务状态..."
  sleep 2

  local ext_ip
  ext_ip=$(curl -s --max-time 1.5 https://api.ipify.org 2>/dev/null || curl -s --max-time 1.5 ifconfig.me 2>/dev/null || echo "服务器公网IP")
  local int_ip
  int_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

  local pwd_val="请查看 .env 文件"
  if [ -f ".env" ]; then
    pwd_val=$(grep -E '^ADMIN_PASS' .env | cut -d= -f2-)
  fi
  [ -z "$pwd_val" ] && pwd_val="请查看 .env 文件"

  echo ""
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}🎉 恭喜！一幕·YIMU 爆款工作室 (V9.4.1) 服务器生产环境已成功部署上线！${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "  🌐 ${CYAN}公网浏览器访问:${NC}  ${BLUE}http://${ext_ip}:${PORT}${NC}"
  echo -e "  🏠 ${CYAN}内网/局域网访问:${NC} ${BLUE}http://${int_ip}:${PORT}${NC}"
  echo -e "  🔑 ${CYAN}管理员登录密码:${NC}  ${YELLOW}${pwd_val}${NC}"
  echo -e "  📂 ${CYAN}程序安装目录:${NC}    ${PURPLE}$(pwd)${NC}"
  echo -e "  📋 ${CYAN}生产运行日志:${NC}    ${PURPLE}$(pwd)/logs/web.out${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${YELLOW}常用运维指令：${NC}"
  if command -v systemctl >/dev/null 2>&1 && [ -f "/etc/systemd/system/yimu.service" ]; then
    echo -e "  - 查看服务状态: ${GREEN}sudo systemctl status yimu${NC}"
    echo -e "  - 重启服务:     ${GREEN}sudo systemctl restart yimu${NC}"
    echo -e "  - 停止服务:     ${GREEN}sudo systemctl stop yimu${NC}"
    echo -e "  - 实时查看日志: ${GREEN}tail -f $(pwd)/logs/web.out${NC}"
    echo -e "  - 一键代码升级: ${GREEN}./一键升级_linux.sh${NC}"
  else
    echo -e "  - 状态/停止/重启: ${GREEN}./一键启动_linux.sh {status|stop|restart|logs}${NC}"
    echo -e "  - 一键代码升级:   ${GREEN}./一键升级_linux.sh${NC}"
  fi
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
}

main() {
  banner
  install_system_deps
  setup_source_code
  setup_python_env
  setup_config
  setup_systemd_service
  show_summary
}

main "$@"
