"""AI 数字人形象记忆库管理器。

提供历史数字人肖像的持久化记忆、一键复用、使用计数、重命名及删除管理。
存储：data/avatar_memory.json
"""
import json
import logging
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "avatar_memory.json"
_AVATARS_DIR = Path(__file__).resolve().parent.parent / "runs" / "avatars"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _read_db() -> list[dict]:
    try:
        if _DATA_PATH.exists():
            data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception as exc:
        log.warning("[avatar_memory] 读取数据失败: %s", exc)
    return []


def _write_db(items: list[dict]):
    try:
        _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DATA_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("[avatar_memory] 写入数据失败: %s", exc)


def auto_discover_existing() -> list[dict]:
    """若数据库尚未初始化，自动扫描 runs/avatars 历史已上传肖像并初始化。"""
    if _DATA_PATH.exists():
        return _read_db()
    items = _read_db()
    existing_paths = {it.get("path") for it in items if it.get("path")}
    changed = False

    if _AVATARS_DIR.exists():
        for f in sorted(_AVATARS_DIR.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                str_p = str(f.resolve())
                if str_p not in existing_paths:
                    mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
                    items.append({
                        "id": f"av-{uuid.uuid4().hex[:8]}",
                        "name": f"数字人形象 {f.stem.replace('avatar_', '')[:6]}",
                        "filename": f.name,
                        "path": str_p,
                        "url": f"/api/aivideo/avatar/{f.name}",
                        "person_desc": "专属定制 AI 数字人出镜肖像",
                        "created_at": mtime,
                        "last_used_at": mtime,
                        "use_count": 1,
                    })
                    existing_paths.add(str_p)
                    changed = True

    _write_db(items)
    return items


def list_avatars() -> list[dict]:
    """返回所有历史数字人肖像，按最近使用排序。"""
    items = auto_discover_existing()
    # 验证底层文件是否存在，若丢失则打标
    valid_items = []
    for it in items:
        p = Path(it.get("path") or "")
        if p.exists():
            valid_items.append(it)
        else:
            # 文件不存在但可能有对应 url
            if (Path(_AVATARS_DIR) / (it.get("filename") or "")).exists():
                it["path"] = str((Path(_AVATARS_DIR) / it["filename"]).resolve())
                valid_items.append(it)
    # 按最近使用倒序
    valid_items.sort(key=lambda x: str(x.get("last_used_at") or x.get("created_at") or ""), reverse=True)
    return valid_items


def save_avatar(path: str, filename: str, url: str, name: str = "", person_desc: str = "") -> dict:
    """保存或更新数字人形象记忆。"""
    items = _read_db()
    resolved_path = str(Path(path).resolve())
    
    # 查重：若同路径已存在，则更新
    for it in items:
        if it.get("path") == resolved_path or it.get("filename") == filename:
            it["last_used_at"] = _iso_now()
            it["use_count"] = int(it.get("use_count") or 1) + 1
            if name:
                it["name"] = name
            if person_desc and (not it.get("person_desc") or it.get("person_desc") == "专属定制 AI 数字人出镜肖像"):
                it["person_desc"] = person_desc
            _write_db(items)
            return it

    # 新建条目
    now_str = _iso_now()
    clean_name = name.strip() or f"数字人形象 {filename[:12]}"
    new_item = {
        "id": f"av-{uuid.uuid4().hex[:8]}",
        "name": clean_name,
        "filename": filename,
        "path": resolved_path,
        "url": url,
        "person_desc": person_desc.strip() or "专属定制 AI 数字人出镜肖像",
        "created_at": now_str,
        "last_used_at": now_str,
        "use_count": 1,
    }
    items.insert(0, new_item)
    _write_db(items)
    return new_item


def use_avatar(avatar_id: str) -> dict | None:
    """标记数字人被复用，使用次数自增。"""
    items = _read_db()
    for it in items:
        if it.get("id") == avatar_id:
            it["last_used_at"] = _iso_now()
            it["use_count"] = int(it.get("use_count") or 1) + 1
            _write_db(items)
            return it
    return None


def update_avatar(avatar_id: str, name: str = "", person_desc: str = "") -> dict | None:
    """重命名或更新数字人形象描述。"""
    items = _read_db()
    for it in items:
        if it.get("id") == avatar_id:
            if name:
                it["name"] = name.strip()
            if person_desc:
                it["person_desc"] = person_desc.strip()
            _write_db(items)
            return it
    return None


def delete_avatar(avatar_id: str, delete_file: bool = True) -> bool:
    """从记忆库删除数字人。"""
    items = _read_db()
    deleted = None
    new_items = []
    for it in items:
        if it.get("id") == avatar_id:
            deleted = it
        else:
            new_items.append(it)
    if len(new_items) != len(items):
        _write_db(new_items)
        if delete_file and deleted and deleted.get("path"):
            try:
                p = Path(deleted["path"])
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        return True
    return False
