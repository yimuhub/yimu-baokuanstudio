# SPDX-License-Identifier: BUSL-1.1
"""一幕·YIMU 爆款工作室 · 版本更新与发布历史展示页 (Releases & Version Evolution).

展示内容：
1. 当前系统运行版本（单一真源，version.py）；
2. 新老版本核心差异对比矩阵与升级演进说明；
3. 历史里程碑时间轴详细功能说明；
4. Git 标签归档说明与多版本按需切换指引。

v15.9.1 巨石拆分：790 行单函数（内联 HTML f-string，全仓最长函数）→ 模板文件
``studio/templates/releases.html`` + 本渲染器（~40 行）。模板插值标记：

``__YIMU_CUR_VER__`` / ``__YIMU_CODENAME__`` / ``__YIMU_SLOGAN_CN__`` /
``__YIMU_SLOGAN_EN__``
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import version

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "releases.html"


@lru_cache(maxsize=1)
def _load_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def get_releases_html() -> str:
    import importlib
    importlib.reload(version)
    cur_ver = version.__version__
    codename = getattr(version, "__codename__", "万象生")
    slogan_cn = getattr(version, "__slogan_cn__", "一念起 一幕开 万象生")
    slogan_en = getattr(version, "__slogan_en__", "One Thought. One Scene. Infinite Worlds.")
    html = _load_template()
    # 模板里只有这四个插值点，其余花括号是 CSS/JS 字面量
    html = html.replace("__YIMU_CUR_VER__", str(cur_ver))
    html = html.replace("__YIMU_CODENAME__", str(codename))
    html = html.replace("__YIMU_SLOGAN_CN__", str(slogan_cn))
    html = html.replace("__YIMU_SLOGAN_EN__", str(slogan_en))
    return html
