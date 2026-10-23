@echo off
rem ==============================================================================
rem  一幕·YIMU 爆款工作室 (YIMU Studio) - Windows 全版本通用一键启动中枢
rem  系统兼容: Windows 7 / Windows 8 / Windows 8.1 / Windows 10 / Windows 11 (x86/x64)
rem  官方网站: https://yimu.hyipf.com
rem ==============================================================================

rem 尝试启用 UTF-8 编码支持（兼容 Win7/8/10/11，抑制旧版点阵字体切换告警）
chcp 65001 >nul 2>nul

title 一幕·YIMU 爆款工作室 - 一键启动

rem 切换工作目录至当前脚本所在目录（带引号防路径空格与特殊符号）
cd /d "%~dp0"

echo ============================================================
echo   一幕·YIMU 爆款工作室 (YIMU Studio) - Windows 一键启动
echo   官方网站: https://yimu.hyipf.com
echo ============================================================
echo.

rem ============================================================
rem 步骤 1: 优先检查已有 .venv 虚拟运行环境是否完好可用
rem ============================================================
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>nul
    if not errorlevel 1 (
        set "PY_BIN=.venv\Scripts\python.exe"
        goto RUN_APP
    )
    echo [提示] 检测到已存 .venv 环境异常，正在自动重置并重新构建...
    rmdir /s /q .venv >nul 2>nul
)

echo [1/4] 检查系统 Python 运行环境 (适配 Win7/8/10/11)...
set "FOUND_PY="

rem ============================================================
rem 步骤 2: 优先扫描官方/系统标准安装路径（100%% 安全，彻底规避 Store 假占位符）
rem 覆盖 Windows 7、8、10、11 各架构与各版本（Python 3.12 / 3.11 / 3.10 / 3.9）
rem ============================================================
for %%P in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%LocalAppData%\Programs\Python\Python39\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
    "%ProgramFiles%\Python39\python.exe"
    "%ProgramFiles(x86)%\Python312\python.exe"
    "%ProgramFiles(x86)%\Python311\python.exe"
    "%ProgramFiles(x86)%\Python310\python.exe"
    "%ProgramFiles(x86)%\Python39\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
    "D:\Python312\python.exe"
    "D:\Python311\python.exe"
    "D:\Python310\python.exe"
    "D:\Python39\python.exe"
    "E:\Python312\python.exe"
    "E:\Python311\python.exe"
    "E:\Python310\python.exe"
    "E:\Python39\python.exe"
    "%UserProfile%\anaconda3\python.exe"
    "%UserProfile%\miniconda3\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
    "C:\ProgramData\miniconda3\python.exe"
) do (
    if exist %%P (
        for %%F in (%%P) do (
            if %%~zF gtr 0 (
                %%P -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
                if not errorlevel 1 (
                    set "FOUND_PY=%%~fP"
                    goto CREATE_VENV
                )
            )
        )
    )
)

rem ============================================================
rem 步骤 3: 探测 py 官方启动器 (Python Launcher for Windows)
rem ============================================================
where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where py 2^>nul') do (
        echo "%%~fI" | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if %%~zI gtr 0 (
                "%%~fI" -3 -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
                if not errorlevel 1 (
                    set "FOUND_PY=%%~fI -3"
                    goto CREATE_VENV
                )
            )
        )
    )
)

rem ============================================================
rem 步骤 4: 探测 PATH 环境变量中的 python
rem 【核心防御机制】：在调用前静态排除 WindowsApps 路径与 0 字节文件，
rem 彻底杜绝在 Windows 10/11 上因触发 Microsoft Store 假解释器而发生秒退！
rem ============================================================
where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        echo "%%~fI" | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if %%~zI gtr 0 (
                "%%~fI" -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
                if not errorlevel 1 (
                    set "FOUND_PY=%%~fI"
                    goto CREATE_VENV
                )
            )
        )
    )
)

rem ============================================================
rem 步骤 5: 系统未检测到真实 Python 解释器（按 Win7 与 Win10/11 智能引导）
rem 保持控制台窗口常开，输出完整排查说明与直达下载链接
rem ============================================================
echo.
echo ============================================================
echo [错误] 启动失败：未在您的电脑上检测到可用的 Python 3.9+。
echo.

rem 智能检测 Windows 版本（6.1 为 Windows 7）
set "IS_WIN7="
ver | findstr /i "6.1." >nul 2>nul
if not errorlevel 1 set "IS_WIN7=1"

if defined IS_WIN7 (
    echo 【Windows 7 专属解决方案】：
    echo   由于官方自 Python 3.9 起停止原生支持 Win7，请按以下步骤安装：
    echo   1. 下载 Windows 7 专用 Python 安装包：
    echo      GitHub 源码站: https://github.com/adang1345/PythonWin7/releases
    echo      国内极速镜像: https://ghfast.top/https://github.com/adang1345/PythonWin7/releases
    echo      （推荐下载 Python 3.10 或 3.11 for Windows 7 版本）
    echo   2. 安装时【务必勾选】：
    echo      [√] Add Python to PATH
    echo   3. 若缺少系统运行库，请同时安装微软 VC++ 2015-2022 运行库合集。
) else (
    echo 【Windows 10 / 11 解决方案】：
    echo   您的电脑尚未安装官方 Python（PATH 中仅有 Windows 11 自带
    echo   的 0 字节别名占位符，无法用于运行项目）。
    echo.
    echo   1. 请前往 Python 官方网站下载安装包：
    echo      https://www.python.org/downloads/windows/
    echo      （强烈推荐下载 Python 3.11 或 Python 3.12 稳定版）
    echo.
    echo   2. 打开安装包时，最下方【务必勾选】：
    echo      [√] Add python.exe to PATH   (将 Python 添加到系统环境变量)
    echo      [√] Use admin privileges     (使用管理员权限)
    echo      然后点击 "Install Now" 完成安装。
)

echo.
echo 完成安装后，请重新双击运行 [一键启动.bat] 即可自动就绪启动。
echo ============================================================
echo.
pause
exit /b 1

rem ============================================================
rem 步骤 6: 准备虚拟运行环境 (.venv)
rem ============================================================
:CREATE_VENV
echo 已找到可用 Python 解释器: %FOUND_PY%
echo [2/4] 正在为您创建独立的虚拟运行环境 (.venv)...
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
echo   1. Python 安装时未勾选完整标准库组件；
echo   2. 项目所在目录缺少写入权限，或被安全管家/杀毒软件拦截；
echo   3. 磁盘空间不足。
echo 建议重新安装官方 Python 并在安全软件中添加信任后重试。
echo ============================================================
echo.
pause
exit /b 1

rem ============================================================
rem 步骤 7: 检查并安装同步运行依赖
rem ============================================================
:RUN_APP
set "PY_BIN=.venv\Scripts\python.exe"

echo [3/4] 检查并同步运行依赖库...
%PY_BIN% -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo 正在安装/同步依赖包，请稍候（首次启动需下载，耗时 1-3 分钟）...
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
echo [错误] 运行依赖库安装失败！
echo 请检查您的网络连接或代理设置后，重新双击 [一键启动.bat]。
echo ============================================================
echo.
pause
exit /b 1

rem ============================================================
rem 步骤 8: 准备运行数据目录、对齐数据库架构并启动服务
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
