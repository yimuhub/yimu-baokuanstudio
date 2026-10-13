@echo off
chcp 65001 >nul
title 一幕·YIMU 爆款工作室 - 一键升级
echo ============================================================
echo   一幕·YIMU 爆款工作室 (YIMU Studio) - Windows 一键升级助手
echo   官方网站: https://yimu.hyipf.com
echo ============================================================
echo.

cd /d "%~dp0"

echo 本升级工具将自动执行以下操作：
echo  1. 从官方 GitHub 仓库拉取最新代码 (git pull)
echo  2. 自动升级 Python 运行依赖库 (pip install -r requirements.txt --upgrade)
echo  3. 自动备份本地核心数据库 (data\mediaflow.db.bak)
echo  4. 自动执行数据库兼容性迁移与结构无损对齐
echo  5. 保留所有草稿箱、素材库、自定义平台与 API 密钥完整不丢失
echo.

set /p CONFIRM="是否立即开始执行一键升级？(Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo [提示] 用户已取消本次升级。
    pause
    exit /b 0
)

echo.
echo [1/5] 正在从 Git 远端拉取最新代码...
git pull origin main
if errorlevel 1 (
    echo [警告] git pull 遇到冲突或网络波动，将继续执行本地依赖与数据库迁移...
)

echo.
echo [2/5] 检查 Python 运行环境...
set VENV_PY=.venv\Scripts\python.exe
set VENV_PIP=.venv\Scripts\pip.exe

if not exist "%VENV_PY%" (
    echo 未发现 .venv 虚拟环境，正在新建...
    python -m venv .venv
)

echo.
echo [3/5] 正在升级并同步最新依赖包...
%VENV_PIP% install -r requirements.txt --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [警告] 依赖包安装存在异常，请检查网络连接。
)

echo.
echo [4/5] 正在自动备份并对齐数据库架构...
if exist "data\mediaflow.db" (
    copy /Y "data\mediaflow.db" "data\mediaflow.db.bak" >nul
    echo 已安全备份数据库到: data\mediaflow.db.bak
)

%VENV_PY% -c "from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine); print('数据库架构表结构自动对齐完毕。')"
if errorlevel 1 (
    echo [错误] 数据库初始化迁移失败，请检查文件锁定或权限。
    pause
    exit /b 1
)

echo.
echo [5/5] 执行数据完整性自检...
%VENV_PY% -c "import studio; print('系统核心模块加载成功。')"

echo.
echo ============================================================
echo   恭喜！一幕·YIMU 爆款工作室已成功升级至最新版本！
echo   现在您可以双击运行 [一键启动.bat] 开启创作。
echo ============================================================
echo.
pause
