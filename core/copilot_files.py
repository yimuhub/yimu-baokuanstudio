# SPDX-License-Identifier: BUSL-1.1
"""对话附件解析（V14）。

只做一件事：把用户拖进对话框的文件，尽量转成可读文本，交给 Copilot 当上下文。

设计取舍：
  · 纯标准库优先。docx 本质是 zip + XML，用 zipfile 拆开正则取 <w:t> 即可，
    不引入 python-docx；这样离线包体积不增加，也不怕依赖缺失。
  · PDF 用 pypdf（若环境里正好有），没有就返回空正文，绝不因为缺依赖而让上传失败。
  · 文本类文件做多编码兜底（utf-8 / utf-8-sig / gb18030 / utf-16 / latin-1），
    中文用户从 Windows 复制来的 txt 常常是 GBK。
  · 正文一律截断到 MAX_CHARS，避免把整本 PDF 塞进 prompt 打爆上下文。
"""
from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path

MAX_CHARS = 12000
MAX_BYTES = 10 * 1024 * 1024

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log",
    ".yaml", ".yml", ".ini", ".toml", ".xml", ".html", ".htm",
    ".py", ".js", ".ts", ".css", ".sql", ".sh",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _docx_text(data: bytes) -> str:
    """从 .docx 里抽正文：zipfile 取出 word/document.xml，按段落切分。"""
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            try:
                xml = zf.read("word/document.xml")
            except KeyError:
                return ""
    except (zipfile.BadZipFile, OSError):
        return ""
    text = xml.decode("utf-8", errors="replace")
    # 段 -> 行：先按段落切，再在段内取 <w:t>，这样换行不会丢
    paras = re.split(r"</w:p>", text)
    lines = []
    for para in paras:
        para = re.sub(r"<w:tab[^>]*/>", "\t", para)
        para = re.sub(r"<w:br[^>]*/>", "\n", para)
        chunks = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, flags=re.S)
        line = "".join(chunks)
        if not line.strip():
            line = re.sub(r"<[^>]+>", "", para) if "<w:t" not in para else ""
        lines.append(line.strip())
    body = "\n".join(ln for ln in lines if ln)
    body = (
        body.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&apos;", "'")
    )
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _pdf_text(data: bytes) -> str:
    """PDF 抽取是可选能力：有 pypdf 就用，没有则返回空正文。"""
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""
    try:
        reader = PdfReader(BytesIO(data))
        out = []
        for page in reader.pages[:60]:
            try:
                out.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(out).strip()
    except Exception:
        return ""


def extract(filename: str, data: bytes) -> dict:
    """返回 {kind, text, truncated, size, name}。任何异常都收敛成空正文。"""
    name = Path(filename or "附件").name
    ext = Path(name).suffix.lower()
    size = len(data)

    if ext in IMAGE_EXTS:
        return {"kind": "image", "text": "", "truncated": False, "size": size, "name": name}

    kind = "binary"
    text = ""
    try:
        if ext in TEXT_EXTS:
            kind = "text"
            text = _decode(data)
        elif ext == ".docx":
            kind = "docx"
            text = _docx_text(data)
        elif ext == ".pdf":
            kind = "pdf"
            text = _pdf_text(data)
    except Exception:
        text = ""

    text = (text or "").strip()
    # 去掉行尾空白与连续空行，别把 prompt 撑成一片空白
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS] + "\n……（正文过长，已截断）"
    return {"kind": kind, "text": text, "truncated": truncated, "size": size, "name": name}
