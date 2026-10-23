@echo off
rem ==============================================================================
rem  一幕·YIMU 爆款工作室 (YIMU Studio) - Windows 全版本通用一键升级中枢
rem  系统兼容: Windows 7 / Windows 8 / Windows 8.1 / Windows 10 / Windows 11 (x86/x64)
rem  官方网站: https://yimu.hyipf.com
rem ==============================================================================

rem 尝试启用 UTF-8 编码支持（兼容 Win7/8/10/11，抑制旧版点阵字体切换告警）
chcp 65001 >nul 2>nul

title 一幕·YIMU 爆款工作室 - 一键升级

rem 切换工作目录至当前脚本所在目录（带引号防路径空格与特殊符号）
cd /d "%~dp0"

echo ============================================================
echo   一幕·YIMU 爆款工作室 (YIMU Studio) - Windows 一键升级助手
echo   官方网站: https://yimu.hyipf.com
echo ============================================================
echo.

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
rem 延迟等待端口释放（兼容 Win7/8/10/11）
timeout /t 1 /nobreak >nul 2>nul || ping -n 2 127.0.0.1 >nul 2>nul

rem 确保数据与日志目录存在
if not exist "data" mkdir data
if not exist "logs" mkdir logs
if not exist "runs" mkdir runs

if exist "runtime\python.exe" (
    "runtime\python.exe" --version >nul 2>nul
    if not errorlevel 1 (
        set "VENV_PY=runtime\python.exe"
        set "VENV_PIP=runtime\Scripts\pip.exe"
        goto HAVE_VENV
    )
)

set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PIP=.venv\Scripts\pip.exe"

if exist "%VENV_PY%" (
    "%VENV_PY%" --version >nul 2>nul
    if not errorlevel 1 goto HAVE_VENV
    echo [提示] 现存 .venv 损坏，正在自动重新创建...
    rmdir /s /q .venv >nul 2>nul
)

echo.
echo 未发现可用 .venv 虚拟环境，正在探测系统可用 Python 环境 (适配 Win7/8/10/11)...
set "FOUND_PY="

rem --- 扫描常见官方 Python 安装目录（最安全，绝不触发 Store 占位符）---
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
                    goto CREATE_UPGRADE_VENV
                )
            )
        )
    )
)

rem --- 探测 py 启动器 ---
where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where py 2^>nul') do (
        echo "%%~fI" | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if %%~zI gtr 0 (
                "%%~fI" -3 -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
                if not errorlevel 1 (
                    set "FOUND_PY=%%~fI -3"
                    goto CREATE_UPGRADE_VENV
                )
            )
        )
    )
)

rem --- 探测 PATH 中的 python（严格排除 WindowsApps 0 字节假占位符）---
where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        echo "%%~fI" | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if %%~zI gtr 0 (
                "%%~fI" -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
                if not errorlevel 1 (
                    set "FOUND_PY=%%~fI"
                    goto CREATE_UPGRADE_VENV
                )
            )
        )
    )
)

echo.
echo ============================================================
echo [错误] 升级终止：未在您的电脑上检测到可用的 Python 3.9+。
echo.

rem 智能检测 Windows 版本（6.1 为 Windows 7）
set "IS_WIN7="
ver | findstr /i "6.1." >nul 2>nul
if not errorlevel 1 set "IS_WIN7=1"

if defined IS_WIN7 (
    echo 【Windows 7 专属解决方案】：
    echo   请下载 Windows 7 专用 Python 安装包：
    echo   下载地址: https://github.com/adang1345/PythonWin7/releases
    echo   备用镜像: https://ghfast.top/https://github.com/adang1345/PythonWin7/releases
    echo   安装时勾选 [Add Python to PATH]，完成后重新运行本升级脚本。
) else (
    echo 【Windows 10 / 11 解决方案】：
    echo   请前往 Python 官方网站下载安装包：
    echo   https://www.python.org/downloads/windows/
    echo   安装时【务必勾选】[√] Add python.exe to PATH
    echo   安装完成后重新运行 [一键升级.bat]。
)

echo ============================================================
echo.
pause
exit /b 1

:CREATE_UPGRADE_VENV
echo 已找到可用 Python 解释器: %FOUND_PY%
echo 正在准备虚拟运行环境 (.venv)...
%FOUND_PY% -m venv .venv
if errorlevel 1 goto UPGRADE_VENV_ERROR
if not exist ".venv\Scripts\python.exe" goto UPGRADE_VENV_ERROR

:HAVE_VENV
if not defined VENV_PY set "VENV_PY=.venv\Scripts\python.exe"
if not defined VENV_PIP set "VENV_PIP=.venv\Scripts\pip.exe"

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
exit /b 0

:UPGRADE_VENV_ERROR
echo.
echo ============================================================
echo [错误] 虚拟环境 (.venv) 创建失败！
echo 请检查当前磁盘空间与项目目录写入权限后重试。
echo ============================================================
echo.
pause
exit /b 1
