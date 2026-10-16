@echo off
chcp 65001 >nul
title 一幕·YIMU 爆款工作室 - 一键启动
echo ============================================================
echo   一幕·YIMU 爆款工作室 (YIMU Studio) - Windows 一键启动
echo   官方网站: https://yimu.hyipf.com
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/4] 检查 Python 环境...
set PY_BIN=

if exist ".venv\Scripts\python.exe" (
    set "PY_BIN=.venv\Scripts\python.exe"
    goto RUN_APP
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_BIN=python"
    goto CREATE_VENV
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_BIN=py -3"
    goto CREATE_VENV
)

if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    set "PY_BIN=%LocalAppData%\Programs\Python\Python312\python.exe"
    goto CREATE_VENV
)

if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PY_BIN=%LocalAppData%\Programs\Python\Python311\python.exe"
    goto CREATE_VENV
)

if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
    set "PY_BIN=%LocalAppData%\Programs\Python\Python310\python.exe"
    goto CREATE_VENV
)

if exist "C:\Python312\python.exe" (
    set "PY_BIN=C:\Python312\python.exe"
    goto CREATE_VENV
)

if exist "C:\Python311\python.exe" (
    set "PY_BIN=C:\Python311\python.exe"
    goto CREATE_VENV
)

echo [错误] 未在电脑上找到 Python 3.10+，请先安装 Python。
echo 下载地址：https://www.python.org/downloads/
echo 注意：安装时务必勾选 [Add python.exe to PATH]
pause
exit /b 1

:CREATE_VENV
echo [2/4] 准备虚拟运行环境 (.venv)...
if not exist ".venv\Scripts\python.exe" (
    %PY_BIN% -m venv .venv
)
set "PY_BIN=.venv\Scripts\python.exe"

:RUN_APP
echo [3/4] 检查并同步运行依赖...
%PY_BIN% -c "import fastapi, uvicorn" >nul 2>nul
if %errorlevel% neq 0 (
    echo 正在安装/同步依赖包，请稍候...
    .venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [4/4] 准备运行数据目录...
if not exist "data" mkdir data
if not exist "data\topics" mkdir data\topics
if not exist "data\drafts" mkdir data\drafts
if not exist "data\cards" mkdir data\cards
if not exist "logs" mkdir logs
if not exist "runs" mkdir runs

rem 自动检查并深度自愈数据库表结构约束与字段
%PY_BIN% -c "from core.db import auto_heal_all_sqlite_databases; auto_heal_all_sqlite_databases(); from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine)" >nul 2>nul

echo.
echo ============================================================
echo   一幕·YIMU 爆款工作室服务正在启动中...
echo   本地访问地址: http://127.0.0.1:8790
echo   局域网可访问: http://localhost:8790
echo ============================================================
echo 正在自动为您打开浏览器...
start "" "http://127.0.0.1:8790"
echo.

%PY_BIN% -m uvicorn web.admin:app --host 0.0.0.0 --port 8790
echo.
echo [提示] 服务已停止。
pause
