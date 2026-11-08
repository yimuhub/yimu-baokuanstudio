# SPDX-License-Identifier: BUSL-1.1
"""统一上传安全守卫（Upload Safety Guard）。

R10.0 安全整改：修复上传端点路径穿越（web/admin.py 历史 BGM/素材上传未过滤 ``..``），
并补齐文件类型白名单与大小上限。所有写盘型上传端点必须经由 :func:`save_upload` 落盘。

安全不变量：
1. 落盘文件名一律由服务端生成（前缀 + 时间戳/随机串 + 白名单后缀），绝不信任客户端文件名；
2. 扩展名必须在调用方声明的白名单内，否则 400；
3. 文件超出大小上限直接 400，不产生半截文件；
4. 解析后的目标路径必须仍位于目标目录内（防御 symlink / 编码绕过的最后防线）。
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

# 常用类型族白名单（调用方可自由以元组传入自定义组合）
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".avi", ".mkv")
DOC_EXTS = (".pdf", ".docx", ".doc", ".txt", ".md", ".epub")

DEFAULT_MAX_MB = 50


def _reject(msg: str) -> None:
    raise HTTPException(400, msg)


async def save_upload(
    file: UploadFile,
    dest_dir: Path,
    prefix: str,
    allowed_exts: tuple[str, ...] = IMAGE_EXTS + AUDIO_EXTS + VIDEO_EXTS,
    max_mb: int = DEFAULT_MAX_MB,
) -> tuple[Path, str]:
    """把上传文件安全落盘，返回 (服务端安全路径, 原始文件名展示值)。

    - 原始文件名仅用于展示与后缀推断，绝不参与落盘路径拼接；
    - 任何校验失败抛 HTTPException(400)。
    """
    dest_dir = Path(dest_dir)
    raw_name = file.filename or ""
    # 后缀取自客户端名（仅作扩展名推断），剥离空白与非常见字符
    ext = Path(raw_name).suffix.lower().strip()
    if ext not in allowed_exts:
        pretty = "/".join(allowed_exts)
        _reject(f"不支持的文件类型 {ext or '(空)'}，仅支持：{pretty}")

    contents = await file.read()
    if len(contents) == 0:
        _reject("上传文件为空")
    if len(contents) > max_mb * 1024 * 1024:
        _reject(f"文件超过 {max_mb}MB 限制（当前 {len(contents) / 1024 / 1024:.1f}MB）")

    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    dest = dest_dir / safe_name
    # 最后防线：解析后必须仍在目标目录内
    try:
        if dest_dir.resolve() not in dest.resolve().parents:
            _reject("目标路径非法")
    except (OSError, RuntimeError):
        _reject("目标路径非法")

    dest.write_bytes(contents)
    return dest, raw_name
