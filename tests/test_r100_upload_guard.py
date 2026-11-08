# SPDX-License-Identifier: BUSL-1.1
"""R10.0 安全整改回归：上传守卫（路径穿越 / 类型白名单 / 大小上限）。"""
from __future__ import annotations

import os
import pathlib
import tempfile

import pytest
from fastapi import HTTPException

os.environ.setdefault("YIMU_DB_PATH", tempfile.mkdtemp(prefix="yimu-t-r100-") + "/t.db")
os.environ.setdefault("MEDIAFLOW_DB", tempfile.mkdtemp(prefix="yimu-t-r100-mf-") + "/mf.db")

from core.upload_guard import (  # noqa: E402
    AUDIO_EXTS,
    IMAGE_EXTS,
    save_upload,
)


class _FakeUpload:
    """最小化模拟 fastapi UploadFile 接口（filename + read）。"""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


@pytest.mark.asyncio
async def test_traversal_filename_is_never_used_in_path():
    """恶意文件名 ../../evil.mp3 不得逃出目标目录（后缀合法但路径部分必须被丢弃）。"""
    dest_dir = pathlib.Path(tempfile.mkdtemp(prefix="yimu-t-up-"))
    dest, orig = await save_upload(
        _FakeUpload("../../evil.mp3", b"x" * 10), dest_dir, "bgm", AUDIO_EXTS
    )
    assert dest.parent.resolve() == dest_dir.resolve()
    assert dest.name.startswith("bgm_")
    assert ".." not in dest.name
    assert orig.endswith("evil.mp3")  # 原名仅用于展示


@pytest.mark.asyncio
async def test_traversal_with_exec_extension_rejected_by_whitelist():
    """携带可执行后缀的恶意名直接被白名单拦截。"""
    with pytest.raises(HTTPException):
        await save_upload(_FakeUpload("../../evil.sh", b"x" * 10),
                          pathlib.Path(tempfile.mkdtemp()), "bgm", AUDIO_EXTS)


@pytest.mark.asyncio
async def test_extension_whitelist_rejects_executable():
    with pytest.raises(HTTPException) as ei:
        await save_upload(_FakeUpload("song.sh", b"x"), pathlib.Path(tempfile.mkdtemp()), "bgm", AUDIO_EXTS)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_size_limit_rejects_oversize():
    with pytest.raises(HTTPException):
        await save_upload(
            _FakeUpload("a.mp3", b"x" * 1024), pathlib.Path(tempfile.mkdtemp()), "bgm", AUDIO_EXTS, max_mb=0
        )  # 0MB 上限 => 必拒


@pytest.mark.asyncio
async def test_empty_file_rejected():
    with pytest.raises(HTTPException):
        await save_upload(_FakeUpload("a.png", b""), pathlib.Path(tempfile.mkdtemp()), "ed", IMAGE_EXTS)


@pytest.mark.asyncio
async def test_happy_path_writes_unique_names():
    dest_dir = pathlib.Path(tempfile.mkdtemp(prefix="yimu-t-up2-"))
    d1, _ = await save_upload(_FakeUpload("封面 大图.PNG", b"hello"), dest_dir, "ed", IMAGE_EXTS)
    d2, _ = await save_upload(_FakeUpload("cover.png", b"hello2"), dest_dir, "ed", IMAGE_EXTS)
    assert d1.exists() and d2.exists() and d1 != d2
    assert d1.suffix == ".png"


def test_draft_dir_rejects_traversal_ids():
    """draft_id 为 URL 路径参数，".." 与分隔符必须被拒绝。"""
    from core import db as core_db
    for bad in ("..", ".", "a/b", "a\\b", "x..y", ""):
        with pytest.raises(ValueError):
            core_db.draft_dir(bad)
    # 正常 ID 不受影响
    good = core_db.draft_dir("did-ok-1")
    assert good.name == "did-ok-1"
