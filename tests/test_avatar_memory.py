"""Unit tests for studio.avatar_memory."""
import json
import pytest
from pathlib import Path
from studio import avatar_memory


def test_avatar_memory_crud(tmp_path, monkeypatch):
    test_db = tmp_path / "avatar_memory.json"
    test_avatars_dir = tmp_path / "avatars"
    test_avatars_dir.mkdir(parents=True)

    monkeypatch.setattr(avatar_memory, "_DATA_PATH", test_db)
    monkeypatch.setattr(avatar_memory, "_AVATARS_DIR", test_avatars_dir)

    # 1. 初始为空
    assert avatar_memory.list_avatars() == []

    # 2. 模拟图片文件并保存记忆
    fake_img = test_avatars_dir / "avatar_test1.jpg"
    fake_img.write_bytes(b"fake_image_content")

    entry = avatar_memory.save_avatar(
        path=str(fake_img),
        filename="avatar_test1.jpg",
        url="/api/aivideo/avatar/avatar_test1.jpg",
        name="测试主播",
        person_desc="年轻干练的女主播"
    )
    assert entry["id"].startswith("av-")
    assert entry["name"] == "测试主播"
    assert entry["use_count"] == 1

    # 3. 查询记忆库
    items = avatar_memory.list_avatars()
    assert len(items) == 1
    assert items[0]["id"] == entry["id"]

    # 4. 一键复用
    used = avatar_memory.use_avatar(entry["id"])
    assert used is not None
    assert used["use_count"] == 2

    # 5. 更新重命名
    updated = avatar_memory.update_avatar(entry["id"], name="资深带货主播")
    assert updated is not None
    assert updated["name"] == "资深带货主播"

    # 6. 删除形象
    ok = avatar_memory.delete_avatar(entry["id"])
    assert ok is True
    assert len(avatar_memory.list_avatars()) == 0
