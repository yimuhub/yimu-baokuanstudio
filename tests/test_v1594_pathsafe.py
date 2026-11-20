# SPDX-License-Identifier: BUSL-1.1
"""V15.9.4 安全回归：路径包含判定收口 + 上传上限。

本轮深审发现的两类问题，都属于"看起来校验了、其实没校验"：

1. **字符串前缀判定**（4 处）
   ``str(target).startswith(str(base))`` 会放过同前缀的兄弟目录：
   base = ``runs/avatars`` 时，``runs/avatars_backup/x.png`` 也算合法。
   其中 ``/api/aivideo/file/{jid}`` 更极端，写成了
   ``str(base).startswith(str(base.parent))``——子目录必然以父目录开头，
   条件恒为 True，等于完全没有校验。

2. **无上限的整份读入**
   ``/api/video/upload_script_file`` 把上传文件一次性 ``read()`` 进内存
   再解析，没有大小上限，也没有 docx（zip）解压上限——一个精心构造的
   docx 就能把进程内存打满。

本文件既测 ``core/pathsafe.py`` 的行为，也用源码断言把这两个模式锁死，
防止以后新增路由时再手写一遍错误的前缀判断。
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from core.pathsafe import is_within, safe_join

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROUTERS = ROOT / "web" / "routers"


def _tree(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """构造 base 目录、同前缀兄弟目录、真实文件。"""
    base = tmp_path / "avatars"
    sibling = tmp_path / "avatars_backup"
    base.mkdir()
    sibling.mkdir()
    (base / "ok.png").write_bytes(b"fine")
    (sibling / "secret.png").write_bytes(b"secret")
    return base, sibling


class TestIsWithin:
    def test_normal_file_inside_base(self, tmp_path):
        base, _ = _tree(tmp_path)
        assert is_within(base / "ok.png", base) is True

    def test_sibling_with_shared_prefix_is_rejected(self, tmp_path):
        """关键用例：旧代码 str().startswith() 会在这里放行。"""
        base, sibling = _tree(tmp_path)
        assert is_within(sibling / "secret.png", base) is False

    def test_dotdot_traversal_is_rejected(self, tmp_path):
        base, _ = _tree(tmp_path)
        assert is_within(base / ".." / "config.yaml", base) is False

    def test_base_itself_is_rejected_by_default(self, tmp_path):
        base, _ = _tree(tmp_path)
        assert is_within(base, base) is False
        assert is_within(base, base, allow_self=True) is True

    def test_nonexistent_path_still_resolves_lexically(self, tmp_path):
        """路径还没生成（视频尚未出片）时也要能判定，不能因为不存在就放行。"""
        base, _ = _tree(tmp_path)
        assert is_within(base / "not-yet.mp4", base) is True

    def test_broken_symlink_fails_closed(self, tmp_path):
        base, _ = _tree(tmp_path)
        link = base / "loop"
        try:
            link.symlink_to(link)
        except (OSError, NotImplementedError):
            pytest.skip("当前文件系统不支持符号链接")
        # 解析失败必须返回 False（失败即拒绝），不能抛异常也不能放行
        assert is_within(link, base) is False

    def test_symlink_loop_fails_closed_on_py313(self, tmp_path):
        """Python 3.13+ 的 resolve(strict=False) 不再对链接环抛错，必须另行兜住。

        why：3.13 起 ``Path.resolve()`` 遇到 ELOOP 改为原样返回未展开路径，
        自指链接会解析成它自己从而通过 relative_to 判定——安全判定变成
        fail-open。本用例直接锁住这条回归，不依赖 Python 版本差异。
        """
        import os
        import sys

        base, _ = _tree(tmp_path)
        link = base / "selfloop"
        try:
            link.symlink_to(link)
        except (OSError, NotImplementedError):
            pytest.skip("当前文件系统不支持符号链接")
        # 前提确认：该链接确实不可达（lexists 真、exists 假）
        assert os.path.lexists(link) and not os.path.exists(link)
        assert is_within(link, base) is False,             f"Python {sys.version_info.major}.{sys.version_info.minor} 下坏链接被判为合法（fail-open）"

    def test_nested_broken_parent_fails_closed(self, tmp_path):
        """父目录是坏链接时，叶子即使不存在也不得放行。"""
        base, _ = _tree(tmp_path)
        bad = base / "badparent"
        try:
            bad.symlink_to(bad)
        except (OSError, NotImplementedError):
            pytest.skip("当前文件系统不支持符号链接")
        assert is_within(bad / "child.mp4", base) is False


class TestSafeJoin:
    def test_normal_join(self, tmp_path):
        base, _ = _tree(tmp_path)
        assert safe_join(base, "ok.png").name == "ok.png"

    def test_absolute_path_cannot_escape(self, tmp_path):
        """Path(base) / '/etc/passwd' 会丢弃 base，safe_join 必须拦住。"""
        base, _ = _tree(tmp_path)
        with pytest.raises(ValueError):
            safe_join(base, "/etc/passwd")

    def test_dotdot_cannot_escape(self, tmp_path):
        base, _ = _tree(tmp_path)
        with pytest.raises(ValueError):
            safe_join(base, "..", "config.yaml")


def _code_lines(text: str) -> list[str]:
    """剥掉注释行——注释里会引用旧写法做说明，不能当代码判。"""
    return [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]


class TestNoStringPrefixPathChecks:
    """源码级防复发：路由层不得再出现字符串前缀判定。"""

    def test_routers_have_no_startswith_path_check(self):
        offenders = []
        for f in sorted(ROUTERS.glob("*.py")):
            for i, line in enumerate(_code_lines(f.read_text(encoding="utf-8")), 1):
                if "startswith(str(" in line:
                    offenders.append(f"{f.name}:{i}: {line.strip()[:90]}")
        assert not offenders, (
            "路由里仍有字符串前缀路径判定，请改用 core.pathsafe.is_within：\n"
            + "\n".join(offenders)
        )

    def test_aivideo_file_validates_jid_shape(self):
        text = (ROUTERS / "media.py").read_text(encoding="utf-8")
        seg = "\n".join(_code_lines(text.split("def aivideo_file(")[1].split("\n@router.")[0]))
        assert "{1,64}" in seg, "jid 必须做形态白名单（长度与字符集）"
        assert "is_within" in seg, "仍须做包含判定作为纵深防御"
        # 恒真的假校验不许回来
        assert "startswith(str(base.parent" not in seg


class TestUploadCaps:
    def test_script_upload_has_size_cap_and_413(self):
        text = (ROUTERS / "media.py").read_text(encoding="utf-8")
        seg = text.split("def video_upload_script_file(")[1].split("\n@router.")[0]
        assert "20 * 1024 * 1024" in seg, "缺少整体大小上限"
        assert "413" in seg, "超限应返回 413 而不是 500"
        assert "file_size" in seg, "docx 需要检查解压后大小（zip bomb）"
        # 413 必须能穿透内层降级解码与外层包裹
        assert seg.count("except HTTPException:") >= 2, (
            "HTTPException 必须在内层与外层都显式重抛，否则会被降级/裹成 500"
        )

    def test_publish_xhs_no_longer_parses_unused_body(self):
        """发布接口不需要请求体，此前读 json 会在空 body 时 500。"""
        text = (ROUTERS / "drafts.py").read_text(encoding="utf-8")
        raw = text.split("def draft_publish_xhs(")[1].split("\n@router.")[0]
        seg = "\n".join(_code_lines(raw))
        assert "request.json()" not in seg


def re_search(pattern: str, text: str) -> bool:
    """小工具：避免为一个断言在文件顶部再引 re。"""
    import re

    return re.search(pattern, text) is not None
