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
echo "  [准备] 检查并清理可能正在运行的旧服务进程..."
lsof -ti:8790 | xargs kill -9 2>/dev/null || true

echo ""
echo "  [1/5] 检查 Python 运行环境..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv || { echo "  ❌ 创建虚拟环境失败"; exit 1; }
fi

echo ""
echo "  [2/5] 正在同步拉取最新系统代码..."
UPDATE_SUCCESS=0

if [ -d ".git" ]; then
  echo "  [检测] 当前为 Git 源码仓库，正在同步拉取最新分支..."
  git stash >/dev/null 2>&1 || true
  if git pull origin main; then
    UPDATE_SUCCESS=1
  else
    echo "  [提示] 直连 GitHub 网络受阻，尝试切换至高速加速镜像拉取..."
    if git pull https://ghfast.top/https://github.com/yimuhub/yimu-baokuanstudio.git main; then
      UPDATE_SUCCESS=1
    fi
  fi
  git stash pop >/dev/null 2>&1 || true
else
  echo "  [检测] 当前为 Release 发行包环境，通过在线中枢安全同步最新代码..."
  if .venv/bin/python -m core.updater --upgrade; then
    UPDATE_SUCCESS=1
  fi
fi

if [ "$UPDATE_SUCCESS" -ne 1 ]; then
  echo ""
  echo "  ❌ 代码同步失败！请检查您的网络连接或代理，本地版本未发生更改。"
  exit 1
fi

echo ""
echo "  [3/5] 正在升级并同步依赖库..."
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade || true

echo ""
echo "  [4/5] 正在备份数据库并对齐表结构..."
if [ -f "data/mediaflow.db" ]; then
  cp data/mediaflow.db data/mediaflow.db.bak
  echo "  ✅ 数据库已安全备份至: data/mediaflow.db.bak"
fi

.venv/bin/python -c "from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine); print('  ✅ 数据库表结构自动对齐完毕。')"

echo ""
echo "  [5/5] 获取升级后最新系统版本信息："
.venv/bin/python -c "import version; print('  ' + '=' * 56); print(f'  🎉 恭喜！一幕·YIMU 爆款工作室已成功升级至最新版本：V{version.__version__}'); print(f'  📌 版本代号: {version.__codename__} ({version.__codename_en__})'); print(f'  🏷️  宣传标语: {version.__slogan__}'); print('  ' + '=' * 56)"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   现在您可以双击 [一键启动.command] 开启创作。       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
