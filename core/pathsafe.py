# SPDX-License-Identifier: BUSL-1.1
"""路径包含判定（Path Containment Guard）。

为什么需要单独一个模块
----------------------
路由里判断「用户给的路径是否还在某个目录内」时，仓库历史上写的是

    if not str(target).startswith(str(base)):

这行看起来对，实际有两个问题：

1. **前缀绕过**：base = ``runs/avatars``，而 ``runs/avatars_backup/x.png``
   同样以 ``runs/avatars`` 开头，于是被判为合法——同级的备份目录、导出目录
   全都能读。只差一个字符就能跨出边界。
2. **假校验**：``web/routers/media.py`` 里还有一处写成
   ``str(base.resolve()).startswith(str(base.parent.resolve()))``，
   子目录必然以父目录开头，这个条件恒为 True，等于完全没校验。

正确写法是让路径组件逐个比较（``PurePath.relative_to``），而不是比较字符串
前缀。Python 3.9+ 的 ``Path.is_relative_to`` 就是这个语义，本项目 target 为
py39，故直接用它。

安全不变量：本模块任何函数返回 True 时，``path`` 解析后（含符号链接展开）
一定位于 ``base`` 之内，且 ``path`` 不等于 ``base`` 本身（除非 allow_self）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

PathLike = Union[str, "Path"]


def is_within(path: PathLike, base: PathLike, *, allow_self: bool = False) -> bool:
    """``path`` 解析后是否位于 ``base`` 目录之内。

    Args:
        path: 待校验路径，通常来自请求参数。
        base: 允许的根目录。
        allow_self: 是否允许 ``path`` 恰好等于 ``base``。默认不允许——路由都是
            取具体文件，把目录本身当文件返回只会在 FileResponse 处再炸一次。

    Returns:
        True 表示安全可放行。任何解析失败（坏符号链接、权限、递归链接）都返回
        False，即失败即拒绝。
    """
    try:
        target = Path(path).resolve()
        root = Path(base).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    if target == root:
        return allow_self
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def safe_join(base: PathLike, *parts: str) -> Path:
    """把 ``parts`` 拼到 ``base`` 下，并确认结果没逃出 ``base``。

    与 ``Path(base) / name`` 的区别：后者在 ``name`` 是绝对路径时会**丢弃**
    ``base``（``Path('/a') / '/etc/passwd' == /etc/passwd``），也没有前缀概念。

    Raises:
        ValueError: 拼接结果逃出了 ``base``。
    """
    root = Path(base).resolve()
    target = root.joinpath(*parts).resolve()
    if not is_within(target, root):
        raise ValueError("路径越界")
    return target
