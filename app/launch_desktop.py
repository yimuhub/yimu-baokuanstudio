# SPDX-License-Identifier: BUSL-1.1
"""桌面客户端启动垫片（V15.8 正式内置，替换客户侧临时脚本）。

为什么需要它
------------
Windows ``pythonw.exe`` 不绑定 stdout/stderr，用 ``WshShell.Run ..., 0`` 隐藏窗口
启动时，程序里第一条 print 就会抛异常、第一个顶层窗体会被隐藏，表现为
「双击没反应」但任务管理器里有进程（客户报告 R1 / R2）。

垫片做的事：
1. 统一 UTF-8 输出环境，避免中文 / emoji 在 GBK 控制台下编码失败；
2. 把工作目录与 sys.path 固定到 app/，保证离线包与开发模式都能找到源码；
3. 用 runpy 执行 ``desktop.py``（由它完成日志重定向、自举、单实例与窗口创建）。

日志重定向、单实例锁等全部收敛在 desktop.py 内，垫片不重复实现，
避免出现两份日志文件 / 两把锁。
"""
from __future__ import annotations

import os
import sys
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent

# bundle 布局：app/desktop.py；开发布局：<repo>/desktop.py
CANDIDATES = [HERE / "desktop.py", HERE.parent / "desktop.py"]
DESKTOP = next((p for p in CANDIDATES if p.is_file()), CANDIDATES[0])

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.chdir(str(DESKTOP.parent))
sys.path.insert(0, str(DESKTOP.parent))

runpy.run_path(str(DESKTOP), run_name="__main__")
