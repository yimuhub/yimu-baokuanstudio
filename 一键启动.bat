@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 一幕·YIMU 爆款工作室 - 一键启动
echo ============================================================
echo   一幕·YIMU 爆款工作室 (YIMU Studio) - Windows 一键启动
echo   官方网站: https://yimu.hyipf.com
echo ============================================================
echo.

cd /d "%~dp0"

rem ============================================================
rem 步骤 1: 检查是否已有现存且健康的 .venv 虚拟运行环境
rem ============================================================
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>nul
    if not errorlevel 1 (
        set "PY_BIN=.venv\Scripts\python.exe"
        goto RUN_APP
    )
    echo [提示] 现存 .venv 环境损坏，正在自动重新创建...
    rmdir /s /q .venv >nul 2>nul
)

echo [1/4] 检查系统 Python 环境...
set "FOUND_PY="

rem ============================================================
rem 步骤 2: 扫描常见官方 Python 安装目录（最安全，绝不触发 Store 占位符）
rem ============================================================
for %%P in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
    "%ProgramFiles(x86)%\Python312\python.exe"
    "%ProgramFiles(x86)%\Python311\python.exe"
    "%ProgramFiles(x86)%\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "D:\Python312\python.exe"
    "D:\Python311\python.exe"
    "D:\Python310\python.exe"
) do (
    if exist %%P (
        for %%F in (%%P) do (
            if %%~zF gtr 0 (
                %%P -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
                if not errorlevel 1 (
                    set "FOUND_PY=%%~fP"
                    goto CREATE_VENV
                )
            )
        )
    )
)

rem ============================================================
rem 步骤 3: 探测 py 启动器 (Python Launcher for Windows)
rem ============================================================
where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where py 2^>nul') do (
        echo "%%~fI" | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if %%~zI gtr 0 (
                "%%~fI" -3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
                if not errorlevel 1 (
                    set "FOUND_PY=%%~fI -3"
                    goto CREATE_VENV
                )
            )
        )
    )
)

rem ============================================================
rem 步骤 4: 探测 PATH 中的 python（严格排除 WindowsApps 0 字节假占位符）
rem 绝不直接运行未经过滤的 python，避免 Windows 11 Store 别名闪退或拦截
rem ============================================================
where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        echo "%%~fI" | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if %%~zI gtr 0 (
                "%%~fI" -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
                if not errorlevel 1 (
                    set "FOUND_PY=%%~fI"
                    goto CREATE_VENV
                )
            )
        )
    )
)

rem ============================================================
rem 步骤 5: 系统未安装真实 Python，弹出清晰友好的安装引导，保持窗口不关闭
rem ============================================================
echo.
echo ============================================================
echo [错误] 启动失败：未在您的电脑上检测到可用的 Python 3.10+。
echo.
echo 原因分析：
echo   您的电脑尚未安装 Python 解释器（PATH 中仅有 Windows 11 自带
echo   的 Microsoft Store 0 字节别名占位符，无法用于运行程序）。
echo.
echo 解决方案（仅需安装一次，约 2 分钟）：
echo   1. 请前往 Python 官方网站下载安装包：
echo      https://www.python.org/downloads/windows/
echo      （推荐下载 Python 3.11 或 Python 3.12 稳定版）
echo.
echo   2. 打开安装包时，最下方【务必勾选】：
echo      [√] Add python.exe to PATH   (将 Python 添加到系统环境变量)
echo      [√] Use admin privileges     (使用管理员权限)
echo      然后点击 "Install Now" 完成安装。
echo.
echo   3. 安装完成后，重新双击运行 [一键启动.bat] 即可自动完成配置并启动。
echo ============================================================
echo.
pause
exit /b 1

rem ============================================================
rem 步骤 6: 创建虚拟运行环境 (.venv)
rem ============================================================
:CREATE_VENV
echo 已找到可用 Python 解释器: %FOUND_PY%
echo [2/4] 正在为您创建独立的运行环境 (.venv)...
%FOUND_PY% -m venv .venv
if errorlevel 1 goto VENV_ERROR
if not exist ".venv\Scripts\python.exe" goto VENV_ERROR

set "PY_BIN=.venv\Scripts\python.exe"
goto RUN_APP

:VENV_ERROR
echo.
echo ============================================================
echo [错误] 虚拟环境 (.venv) 创建失败！
echo 可能原因：
echo   1. Python 安装不完整，缺少 venv 组件；
echo   2. 项目所在目录缺少写入权限，或被安全软件阻止；
echo   3. 磁盘空间不足。
echo 建议重新安装官方 Python 3.11/3.12，并在安全软件中添加信任后重试。
echo ============================================================
echo.
pause
exit /b 1

rem ============================================================
rem 步骤 7: 检查并安装同步项目依赖
rem ============================================================
:RUN_APP
set "PY_BIN=.venv\Scripts\python.exe"

echo [3/4] 检查并同步运行依赖库...
%PY_BIN% -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo 正在安装/同步依赖包，请稍候（通常仅在首次运行时需要 1-3 分钟）...
    .venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [提示] 镜像源连接超时，正在切换官方 PyPI 源重试...
        .venv\Scripts\pip.exe install -r requirements.txt
        if errorlevel 1 goto PIP_ERROR
    )
)
goto PREPARE_DATA

:PIP_ERROR
echo.
echo ============================================================
echo [错误] 运行依赖安装失败！
echo 请检查您的网络连接或代理设置后，重新双击 [一键启动.bat]。
echo ============================================================
echo.
pause
exit /b 1

rem ============================================================
rem 步骤 8: 准备运行数据目录、对齐数据库结构并启动服务
rem ============================================================
:PREPARE_DATA
echo [4/4] 准备运行数据目录与数据库架构...
if not exist "data" mkdir data
if not exist "data\topics" mkdir data\topics
if not exist "data\drafts" mkdir data\drafts
if not exist "data\cards" mkdir data\cards
if not exist "logs" mkdir logs
if not exist "runs" mkdir runs

rem 自动检查并深度自愈数据库表结构约束与字段
%PY_BIN% -c "from core.db import auto_heal_all_sqlite_databases; auto_heal_all_sqlite_databases(); from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine)" >nul 2>nul

rem 自动复制 .env.example → .env（若 .env 不存在）
if not exist ".env" (
    if exist ".env.example" (
        echo [提示] 未找到 .env，已自动从 .env.example 复制，可按需修改配置。
        copy ".env.example" ".env" >nul
    )
)

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
echo ============================================================
echo [提示] 一幕服务已正常停止。
echo ============================================================
pause
