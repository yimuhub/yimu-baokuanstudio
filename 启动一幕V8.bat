@echo off
chcp 65001 >nul
title 一幕·YIMU 爆款工作室 V8
echo ============================================================
echo   一幕·YIMU 爆款工作室 V8 - Windows 启动脚本
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

if exist "C:\Python312\python.exe" (
    set "PY_BIN=C:\Python312\python.exe"
    goto CREATE_VENV
)

if exist "C:\Python311\python.exe" (
    set "PY_BIN=C:\Python311\python.exe"
    goto CREATE_VENV
)

echo [错误] 未在电脑上找到 Python，请先安装 Python 3.10+。
echo 下载地址：https://www.python.org/downloads/
echo 注意：安装时务必勾选 [Add python.exe to PATH]
pause
exit /b 1

:CREATE_VENV
echo [2/4] 准备虚拟环境...
if not exist ".venv\Scripts\python.exe" (
    %PY_BIN% -m venv .venv
)
set "PY_BIN=.venv\Scripts\python.exe"

:RUN_APP
echo [3/4] 准备依赖包...
%PY_BIN% -c "import fastapi, uvicorn" >nul 2>nul
if %errorlevel% neq 0 (
    echo 正在安装依赖包，请稍候...
    .venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [4/4] 正在清理缓存并启动服务...
del /s /q *.pyc >nul 2>nul

if not exist "data" mkdir data
if not exist "logs" mkdir logs
if not exist "runs" mkdir runs

echo.
echo V8 安全说明：管理口令（ADMIN_PASSWORD）未配置或为历史弱口令时，
echo 本机不再自动免密；首次使用请设置强口令后再访问管理功能。
echo.
echo 访问地址：http://127.0.0.1:8790
echo 正在打开浏览器...
start "" "http://127.0.0.1:8790"
echo.

%PY_BIN% -m uvicorn web.admin:app --host 127.0.0.1 --port 8790
echo.
echo [提示] 服务已停止。
pause
