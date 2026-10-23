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
echo  1. 从官方 GitHub 仓库同步最新代码 (支持 Git 仓库模式与 Release ZIP 压缩包模式)
echo  2. 自动关闭当前运行的一幕服务进程，释放文件锁与端口占用
echo  3. 自动备份本地核心数据库 (data\mediaflow.db.bak)
echo  4. 自动升级 Python 运行依赖库并无损对齐数据库结构
echo  5. 保留所有草稿箱、素材资产、自定义平台规则与 API 密钥完整不丢失
echo.

set /p CONFIRM="是否立即开始执行一键升级？(Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo [提示] 用户已取消本次升级。
    pause
    exit /b 0
)

echo.
echo [准备] 检查并关闭后台可能正在运行的一幕服务...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8790" ^| findstr "LISTENING"') do (
    echo 正在关闭旧的一幕后台服务进程 (PID: %%a)...
    taskkill /F /PID %%a >nul 2>nul
)
timeout /t 1 /nobreak >nul

rem 确保数据与日志目录存在
if not exist "data" mkdir data
if not exist "logs" mkdir logs
if not exist "runs" mkdir runs

set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PIP=.venv\Scripts\pip.exe"

if exist "%VENV_PY%" goto HAVE_VENV

echo.
echo 未发现 .venv 虚拟环境，正在探测可用 Python 环境...
set SYS_PY=

rem --- 1. 尝试 PATH 中的 python（需通过真实执行验证，排除 Store 0 字节假占位符）---
where python >nul 2>nul
if %errorlevel% equ 0 (
    python --version >nul 2>nul
    if %errorlevel% equ 0 (
        set "SYS_PY=python"
        goto VALIDATE_SYS_PY
    )
)

rem --- 2. 尝试 PATH 中的 py 启动器 ---
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 --version >nul 2>nul
    if %errorlevel% equ 0 (
        set "SYS_PY=py -3"
        goto VALIDATE_SYS_PY
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
            set "SYS_PY=%%~P"
            goto VALIDATE_SYS_PY
        )
    )
)

echo.
echo [错误] 未在电脑上找到可用的 Python 3.10+，无法创建升级环境。
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

:VALIDATE_SYS_PY
%SYS_PY% -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 找到的 Python 版本低于 3.10，请安装 Python 3.11 或 3.12。
    echo 下载地址：https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

echo 正在准备虚拟运行环境 (.venv)...
%SYS_PY% -m venv .venv
if %errorlevel% neq 0 (
    echo [错误] 虚拟运行环境创建失败，请检查 Python 安装是否完整或磁盘权限。
    pause
    exit /b 1
)

:HAVE_VENV
echo.
echo [1/5] 正在同步拉取最新系统代码...
set UPDATE_SUCCESS=0
set GIT_TERMINAL_PROMPT=0
set GCM_INTERACTIVE=never
set GIT_ASKPASS=

if exist ".git" (
    echo 检测到当前为 Git 仓库环境，正在拉取最新代码...
    git stash >nul 2>nul
    git pull origin main
    if not errorlevel 1 (
        set UPDATE_SUCCESS=1
    ) else (
        echo [提示] 直连 GitHub 出现网络波动，正在切换至高速加速源 (ghfast) 重试...
        git pull https://ghfast.top/https://github.com/yimuhub/yimu-baokuanstudio.git main
        if not errorlevel 1 (
            set UPDATE_SUCCESS=1
        ) else (
            echo [提示] 正在切换至备用加速源 (ghproxy) 重试...
            git pull https://ghproxy.net/https://github.com/yimuhub/yimu-baokuanstudio.git main
            if not errorlevel 1 (
                set UPDATE_SUCCESS=1
            ) else (
                echo [提示] Git 链路均受本地网络阻断，自动切换为 Release 归档极速在线覆盖模式...
                %VENV_PY% -m core.updater --upgrade
                if not errorlevel 1 set UPDATE_SUCCESS=1
            )
        )
    )
    git stash pop >nul 2>nul
) else (
    echo 检测到当前为 Release 压缩包发行版，正在通过在线中枢下载最新代码...
    %VENV_PY% -m core.updater --upgrade
    if not errorlevel 1 set UPDATE_SUCCESS=1
)

if "%UPDATE_SUCCESS%"=="0" (
    echo.
    echo ============================================================
    echo [错误] 代码拉取失败！
    echo 原因可能为：
    echo   1. 本地网络无法连接 GitHub，或连接超时；
    echo   2. 本地存在未解决的代码冲突。
    echo 本次升级未完成，本地现有数据与程序未受任何损害。
    echo 建议检查网络或配置代理后，重新运行 [一键升级.bat]。
    echo ============================================================
    pause
    exit /b 1
)

echo.
echo [2/5] 正在升级并同步最新依赖包...
%VENV_PIP% install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [警告] 依赖包安装存在异常，请检查网络连接。
)

echo.
echo [3/5] 正在自动备份并对齐数据库架构与约束自愈...
if exist "data\mediaflow.db" (
    copy /Y "data\mediaflow.db" "data\mediaflow.db.bak" >nul
    echo 已安全备份数据库到: data\mediaflow.db.bak
)

%VENV_PY% -c "from core.db import auto_heal_all_sqlite_databases; auto_heal_all_sqlite_databases(); from studio.db import get_engine, init_db; import os; url = os.environ.get('YIMU_DB_URL', 'sqlite:///./data/mediaflow.db'); engine = get_engine(url); init_db(engine); print('数据库架构表结构自动对齐与无损自愈完毕。')"
if errorlevel 1 (
    echo [错误] 数据库初始化迁移失败，请检查文件锁定或权限。
    pause
    exit /b 1
)

echo.
echo [4/5] 执行核心功能自检与版本核对...
%VENV_PY% -c "import studio, version; print(f'系统核心模块加载成功，当前版本: V{version.__version__} ({version.__codename__})')"
if errorlevel 1 (
    echo [警告] 模块加载自检异常，请检查依赖是否完整。
)

echo.
echo [5/5] 获取升级后最新系统版本信息：
%VENV_PY% -c "import version; print('=' * 60); print(f'🎉 恭喜！一幕·YIMU 爆款工作室已成功升级至最新版本：V{version.__version__}'); print(f'📌 版本代号: {version.__codename__} ({version.__codename_en__})'); print(f'🏷️ 宣传标语: {version.__slogan__}'); print('=' * 60)"

echo.
echo 现在您可以双击运行 [一键启动.bat] 开启创作。
echo.
pause
