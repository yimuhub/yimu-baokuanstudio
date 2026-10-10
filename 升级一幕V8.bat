@echo off
chcp 65001 >nul
title 一幕·YIMU 爆款工作室 V8 - 版本升级工具
echo ============================================================
echo   一幕·YIMU 爆款工作室 V8 - Windows 升级与数据迁移助手
echo ============================================================
echo.

cd /d "%~dp0"

echo 本工具将执行以下升级步骤：
echo  1. 更新 Python 运行依赖包（pip install -r requirements.txt）
echo  2. 自动检查并对齐数据库结构（memberships / ledger / invites 等）
echo  3. [V8新增] 规范化 users 表历史时间戳（Unix 秒 -> ISO），修复 500 崩溃
echo  4. 保持现有 data/mediaflow.db 原有草稿、素材与已配置 Key 不受影响
echo.
echo 升级前会先备份 data/mediaflow.db 到 mediaflow.db.bak_V8。
echo.
set /p CONFIRM="是否立即开始升级？(Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo 已取消升级。
    pause
    exit /b 0
)

echo.
echo [1/5] 检测 Python 环境...
set VENV_PY=.venv\Scripts\python.exe
set VENV_PIP=.venv\Scripts\pip.exe

if not exist "%VENV_PY%" (
    echo 未发现 .venv 虚拟环境，正在新建...
    python -m venv .venv
)

echo.
echo [2/5] 正在升级并同步依赖...
%VENV_PIP% install -r requirements.txt --upgrade
if errorlevel 1 (
    echo [警告] 依赖包安装存在异常，请检查网络。
)

echo.
echo [3/5] 正在备份并执行数据库兼容与结构迁移...
if exist "data\mediaflow.db" (
    copy /Y "data\mediaflow.db" "data\mediaflow.db.bak_V8" >nul
    echo 已备份 data\mediaflow.db -> data\mediaflow.db.bak_V8
)
%VENV_PY% -c "from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine); print('数据库架构表结构自动对齐完毕。')"
if errorlevel 1 (
    echo [错误] 数据库初始化迁移失败，请检查文件锁定或权限。
    pause
    exit /b 1
)

echo.
echo [4/5] [V8新增] 正在规范化 users 表历史时间戳（修复 P0-A 500）...
%VENV_PY% scripts\migrate_users_ts.py
if errorlevel 1 (
    echo [提示] 时间戳规范化未执行（可能脚本缺失或库被锁定），不影响本次升级主流程。
)

echo.
echo [5/5] 正在清理缓存...
del /s /q *.pyc >nul 2>nul

echo.
echo ============================================================
echo   恭喜！一幕·YIMU V8 升级与环境配置完成。
echo  双击运行【启动一幕V8.bat】即可畅享新版！
echo  提示：V8 已封堵历史弱口令后门，未配置强口令时本机不再免密。
echo ============================================================
pause
