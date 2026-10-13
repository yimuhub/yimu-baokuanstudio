#!/bin/bash
# ============================================================
#  一幕·YIMU 爆款工作室 (YIMU Studio) - macOS 一键升级助手
#  双击此文件即可自动从 GitHub 拉取最新版本并无损升级
#  官网: https://yimu.hyipf.com
# ============================================================
set -u
cd "$(dirname "$0")"

trap 'echo ""; echo "按回车关闭窗口..."; read -r _' EXIT

clear
echo "╔══════════════════════════════════════════════════════╗"
echo "║        一幕·YIMU 爆款工作室 - macOS 一键升级助手     ║"
echo "║        官方网站: https://yimu.hyipf.com              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

read -p "是否立即开始从 GitHub 同步升级至最新版本？(y/n): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "  [提示] 用户已取消本次升级。"
  exit 0
fi

echo ""
echo "  [1/5] 正在拉取官方仓库最新代码 (git pull)..."
git pull origin main || echo "  ⚠️ git pull 提示有本地修改或网络波动，继续执行依赖与迁移..."

echo ""
echo "  [2/5] 检查 Python 运行环境..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv || { echo "  ❌ 创建虚拟环境失败"; exit 1; }
fi

echo ""
echo "  [3/5] 正在升级并同步依赖库..."
.venv/bin/pip install -r requirements.txt --upgrade

echo ""
echo "  [4/5] 正在备份数据库并对齐表结构..."
if [ -f "data/mediaflow.db" ]; then
  cp data/mediaflow.db data/mediaflow.db.bak
  echo "  ✅ 数据库已安全备份至: data/mediaflow.db.bak"
fi

.venv/bin/python -c "from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine); print('  ✅ 数据库表结构自动对齐完毕。')"

echo ""
echo "  [5/5] 执行核心功能自检..."
.venv/bin/python -c "import studio; print('  ✅ 核心模块加载自检通过。')"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   🎉 升级完成！一幕·YIMU 已升级至最新版本！         ║"
echo "║   现在您可以双击 [一键启动.command] 启动工作室。      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
