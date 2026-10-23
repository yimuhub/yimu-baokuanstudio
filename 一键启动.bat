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

rem --- 优先使用已有的 .venv，跳过所有检测 ---
if exist ".venv\Scripts\python.exe" (
    set "PY_BIN=.venv\Scripts\python.exe"
    goto RUN_APP
)

rem ---------------------------------------------------------------
rem 辅助宏：验证候选解释器能真正执行（排除 Microsoft Store 占位符）
rem 用法：先 set "PY_BIN=<候选路径>"，然后 goto TRY_CANDIDATE
rem ---------------------------------------------------------------

rem --- 1. 尝试 PATH 中的 python（需通过真实执行验证）---
where python >nul 2>nul
if %errorlevel% equ 0 (
    rem 用 --version 真正运行一次，Store 占位符会返回非 0 或根本不打印
    python --version >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_BIN=python"
        goto VALIDATE_VERSION
    )
)

rem --- 2. 尝试 PATH 中的 py 启动器 ---
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 --version >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_BIN=py -3"
        goto VALIDATE_VERSION
    )
)

rem --- 3. 扫描常见安装路径（Python 3.12 / 3.11 / 3.10）---
for %%P in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
) do (
    if exist %%P (
        %%P --version >nul 2>nul
        if %errorlevel% equ 0 (
            set "PY_BIN=%%~P"
            goto VALIDATE_VERSION
        )
    )
)

rem --- 找不到任何可用 Python ---
echo.
echo [错误] 未在电脑上找到可用的 Python 3.10+。
echo.
echo   可能原因：
echo     1. 尚未安装 Python——请访问 https://www.python.org/downloads/windows/
echo        下载 Python 3.11 或 3.12（推荐），安装时务必勾选：
echo           [Add python.exe to PATH]
echo     2. 已安装但 PATH 中只有 Microsoft Store 的 Python 占位符（0 字节假 python.exe）。
echo        解决：Windows 设置 → 应用 → 高级应用设置 → 应用执行别名，
echo             关闭 python.exe 和 python3.exe 两个别名。
echo.
pause
exit /b 1

:VALIDATE_VERSION
rem 验证 Python 版本 >= 3.10
%PY_BIN% -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 找到的 Python 版本低于 3.10，请安装 Python 3.11 或 3.12。
    echo 下载地址：https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

:CREATE_VENV
echo [2/4] 准备虚拟运行环境 (.venv)...
if not exist ".venv\Scripts\python.exe" (
    %PY_BIN% -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败，请检查 Python 安装是否完整。
        pause
        exit /b 1
    )
)
set "PY_BIN=.venv\Scripts\python.exe"

:RUN_APP
echo [3/4] 检查并同步运行依赖...
%PY_BIN% -c "import fastapi, uvicorn" >nul 2>nul
if %errorlevel% neq 0 (
    echo 正在安装/同步依赖包，请稍候...
    .venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败，请检查网络连接后重试。
        pause
        exit /b 1
    )
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
echo [提示] 服务已停止。
pause
