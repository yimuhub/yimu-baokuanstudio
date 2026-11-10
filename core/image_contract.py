# SPDX-License-Identifier: BUSL-1.1
"""正文配图命名契约（V15.8 · 客户报告 R3 / R4 / R5 / S1 / S2 / S5）。

问题
----
模型在「一句话成稿 / 对话式改写」时按语义自造图片文件名
（``workflow.png`` / ``kb-compare.png`` / ``qc-dashboard.png``），
而产品真实产物只有 ``cover.png`` 与 ``sec-0.png ~ sec-N.png``。
历史上 ``to_storage`` 无条件保护所有 ``![alt](url)``，
``inject_images_to_markdown`` 一见正文已有 ``![`` 就直接返回，
``layouter.render`` 又把真实配图注入关掉 —— 三处叠加，死链一路无阻
传到预览 HTML，用户看到裂图。

契约
----
1. **落库态**：正文里只允许出现三种图片地址
   - ``![说明]({{IMG:1}})`` / ``{{IMG:cover}}`` 占位符（模型只输出占位符）；
   - ``/img/{did}/cover.png``、``/img/{did}/sec-N.png``、``custom-*.png`` 真实地址；
   - 外部 ``http(s)://`` / ``data:`` 图片。
   其余一律在 :func:`storage_normalize` 里改写成占位符，落库前就不会有死链。
2. **成稿态**：图片生成完毕后由 :func:`normalize` 把占位符与历史遗留死链
   按**出现顺序**映射到磁盘上真实存在的 sec 图（序号匹配，不依赖小节标题文本）。
   映射不上的链接直接移除，绝不把裂图交给浏览器。
3. **校验**：:func:`validate` 供预览编译 / 状态变更 / 诊断日志复用。

本模块只依赖标准库与 ``core.db``，可在清洗层、路由层、渲染层安全复用。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("yimu.image_contract")

#: Markdown 图片语法（不含 title 属性的复杂形态）
MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)\s*\)")
#: 服务端占位符：{{IMG:1}} / {{IMG:cover}}
PLACEHOLDER_RE = re.compile(r"^\{\{IMG:([A-Za-z0-9_-]+)\}\}$", re.I)
#: 本地草稿图片地址 /img/{did}/{name}
LOCAL_IMG_RE = re.compile(r"^/?img/([A-Za-z0-9_-]+)/([^/?#]+)$")
#: 产品允许的图片文件名
SAFE_NAME_RE = re.compile(r"^(?:cover|sec-\d+|custom-[A-Za-z0-9_-]+)\.(?:png|jpg|jpeg|webp)$", re.I)
#: 模型提示词里追加的硬规则（成稿阶段引导模型只输出占位符）
PROMPT_RULE = (
    "配图规则：正文中需要插图时只能写 ![说明]({{IMG:1}}) 这类占位符（序号从 1 开始，"
    "封面用 {{IMG:cover}}），禁止编造 workflow.png 等具体文件名，"
    "服务端会按序号替换为真实配图。"
)


def image_dir(draft_id: str, ddir: Path | None = None) -> Path:
    """图片目录（纯读取，不创建任何目录）。"""
    if ddir is not None:
        return ddir / "img"
    return _draft_dir_readonly(draft_id) / "img"


def _sec_index(name: str) -> int:
    m = re.match(r"^sec-(\d+)\.", name, re.I)
    return int(m.group(1)) if m else -1


def disk_images(draft_id: str, ddir: Path | None = None) -> dict:
    """返回磁盘上真实存在的封面 / 小节配图 URL（按 sec 序号排序）。"""
    img_d = image_dir(draft_id, ddir)
    cover = f"/img/{draft_id}/cover.png" if (img_d / "cover.png").is_file() else ""
    secs = []
    try:
        for p in sorted((f for f in img_d.glob("sec-*.png") if SAFE_NAME_RE.match(f.name)),
                        key=lambda x: _sec_index(x.name)):
            secs.append(f"/img/{draft_id}/{p.name}")
    except OSError:
        pass
    return {"cover": cover, "sections": secs}


def _draft_dir_readonly(draft_id: str) -> Path:
    """只读地推算草稿目录，**不创建目录**。

    ``db.draft_dir()`` 带 ``mkdir(parents=True, exist_ok=True)`` 副作用，
    只适合写路径；存在性校验属于读路径，不能因为它被调用就把空草稿目录
    凭空建出来（历史排查里这类副作用会污染「草稿是否存在」的判断）。
    """
    from core import db
    did = str(draft_id or "").strip()
    root = (db.DATA / "drafts").resolve()
    safe_re = getattr(db, "_SAFE_ID_RE", None)
    if (safe_re is not None and not safe_re.match(did)) or not did:
        return root / "__invalid__"
    d = (root / did).resolve()
    if d != root and root not in d.parents:
        return root / "__invalid__"
    return d


def local_image_exists(src: str, ddir: Path | None = None,
                       *, strict: bool = False) -> bool | None:
    """编译期存在性校验。

    Returns: True=本地图存在；False=本地图不存在（应降级）；
    None=非本地图 / 渲染期无法判定，不检查。

    V15.8：渲染层会被单元测试、外部排版调用、数据盘未挂载等场景传入
    合成 id（例如 ``/img/d1/cover.png``）。只按「草稿目录存在」判断并不可靠
    ——历史运行会留下空目录；真正的判据是 ``img/`` 资源目录是否存在：
    不存在时视为「无法判定」，避免把合法图片静默删掉。
    ``strict=True`` 供发布前质量闸使用：草稿引用了本地图片却没有资源目录，
    必然是死链，必须判为缺失并拦截。
    """
    clean = (src or "").split("?")[0].strip()
    m = LOCAL_IMG_RE.match(clean)
    if not m:
        return None
    did, name = m.group(1), m.group(2)
    if not SAFE_NAME_RE.match(name):
        return False
    img_d = (ddir / "img") if ddir is not None else (_draft_dir_readonly(did) / "img")
    if not img_d.is_dir():
        return False if strict else None
    return (img_d / name).is_file()


def is_canonical(src: str) -> bool:
    """落库态是否允许该图片地址原样保留。"""
    clean = (src or "").split("?")[0].strip()
    if PLACEHOLDER_RE.match(clean):
        return True
    if clean.startswith(("http://", "https://", "data:", "//")):
        return True
    m = LOCAL_IMG_RE.match(clean)
    return bool(m and SAFE_NAME_RE.match(m.group(2)))


def storage_normalize(text: str) -> str:
    """把模型自造的图片文件名改写成受控占位符（供 ``to_storage`` 调用）。"""
    if not text or "![" not in text:
        return text
    counter = [0]

    def _repl(m: re.Match) -> str:
        alt, src = m.group(1), m.group(2)
        if is_canonical(src):
            return m.group(0)
        counter[0] += 1
        logger.info("[image-contract] 落库拦截非契约图片链接 %r → {{IMG:%d}}", src, counter[0])
        return f"![{alt}]({{{{IMG:{counter[0]}}}}})"

    return MD_IMG_RE.sub(_repl, text)


def needs_healing(body_md: str, draft_id: str, ddir: Path | None = None) -> bool:
    """正文里是否还有占位符 / 死链（用于老草稿打开时的自愈判定）。"""
    if not body_md:
        return False
    img_d = image_dir(draft_id, ddir)
    for m in MD_IMG_RE.finditer(body_md):
        src = m.group(2).split("?")[0].strip()
        if PLACEHOLDER_RE.match(src):
            return True
        local = LOCAL_IMG_RE.match(src)
        if local:
            name = local.group(2)
            if not SAFE_NAME_RE.match(name) or not (img_d / name).is_file():
                return True
        elif not src.startswith(("http://", "https://", "data:", "//")):
            return True
    return False


def normalize(body_md: str, draft_id: str, ddir: Path | None = None,
              *, auto_inject: bool = True, images: dict | None = None) -> tuple[str, dict]:
    """把占位符 / 历史死链按出现顺序映射到真实配图；返回 ``(新正文, 报告)``。

    映射规则：
    - ``{{IMG:cover}}`` / ``{{IMG:0}}`` → ``cover.png``；
    - ``{{IMG:N}}`` → 第 N-1 张 sec 图（序号匹配，不看小节标题）；
    - 已有且存在的真实链接原样保留，并把它的 sec 序号标记为「已占用」；
    - 其余（模型自造名、指向不存在文件的 /img 链接）→ 依次取未占用的 sec 图；
    - sec 图用尽 → 删除该图片语法，并在报告里记录。

    ``images`` 允许调用方显式给出 ``{"cover", "sections": [...]}``（默认读磁盘）。
    ``imagegen.inject_images_to_markdown`` 走的就是这条：既保持单一回写入口，
    又让上层可以在测试里注入图片源，不需要伪造磁盘文件。
    """
    report = {"fixed": 0, "removed": 0, "injected": 0, "kept": 0, "missing": []}
    if not body_md:
        return body_md, report
    supplied = images is not None
    imgs = images if supplied else disk_images(draft_id, ddir)
    cover_url = (imgs or {}).get("cover") or ""
    sec_urls = [u for u in ((imgs or {}).get("sections") or []) if u]
    img_d = image_dir(draft_id, ddir)
    trusted = {u.split("?")[0].strip() for u in [cover_url, *sec_urls] if u} if supplied else set()

    def _is_real(src: str) -> bool:
        """该链接是否指向一张可信任的真实配图。"""
        if src in trusted:
            return True
        local = LOCAL_IMG_RE.match(src)
        return bool(local and SAFE_NAME_RE.match(local.group(2)) and (img_d / local.group(2)).is_file())

    matches = list(MD_IMG_RE.finditer(body_md))
    used: set[int] = set()
    for m in matches:
        src = m.group(2).split("?")[0].strip()
        if not _is_real(src):
            continue
        local = LOCAL_IMG_RE.match(src)
        if local:
            idx = _sec_index(local.group(2))
            if idx >= 0:
                used.add(idx)
    free = [i for i in range(len(sec_urls)) if i not in used]
    cursor = [0]

    def _take(idx: int | None = None) -> str:
        if idx is not None and 0 <= idx < len(sec_urls):
            return sec_urls[idx]
        while cursor[0] < len(free):
            i = free[cursor[0]]
            cursor[0] += 1
            if i not in used:
                used.add(i)
                return sec_urls[i]
        return ""

    def _repl(m: re.Match) -> str:
        alt, src = m.group(1), m.group(2)
        clean = src.split("?")[0].strip()
        # 外部图片不受契约约束
        if clean.startswith(("http://", "https://", "data:", "//")):
            report["kept"] += 1
            return m.group(0)
        ph = PLACEHOLDER_RE.match(clean)
        if ph:
            key = ph.group(1).lower()
            if key in ("cover", "0"):
                if cover_url:
                    report["fixed"] += 1
                    return f"![{alt}]({cover_url})"
                report["removed"] += 1
                report["missing"].append(clean)
                return ""
            idx = int(key) - 1 if key.isdigit() else None
            target = _take(idx)
        else:
            if _is_real(clean):
                report["kept"] += 1
                return m.group(0)  # 已是真实地址，保留（含 ?v= 版本号）
            target = _take()
        if not target:
            report["removed"] += 1
            report["missing"].append(clean)
            return ""
        report["fixed"] += 1
        return f"![{alt}]({target})"

    out = MD_IMG_RE.sub(_repl, body_md)

    # 正文完全没有图片但磁盘上有配图：按小节顺序自动注入（对话式成稿路径）
    if auto_inject and "![" not in out and (cover_url or sec_urls):
        out = _inject_by_index(out, draft_id, cover_url, sec_urls)
        report["injected"] = (1 if cover_url else 0) + len(sec_urls)
    if report["fixed"] or report["removed"]:
        logger.info("[image-contract] draft=%s 修复=%d 移除=%d 缺失=%s",
                    draft_id, report["fixed"], report["removed"], report["missing"][:5])
    return _dedupe(out), report


def _dedupe(body_md: str) -> str:
    """同一 URL 只保留第一次出现，避免重复插图。"""
    seen: set[str] = set()
    out = []
    for line in body_md.splitlines():
        m = MD_IMG_RE.search(line.strip())
        if m and line.strip().startswith("!["):
            key = m.group(2).split("?")[0].strip()
            if key in seen:
                continue
            seen.add(key)
        out.append(line)
    return "\n".join(out).strip()


def _heading_label(line: str) -> str:
    """从 H2/H3/H4 / 方头括号 / 中文序号标题里取「人能读懂」的 alt 文本。"""
    s = re.sub(r"^#{2,4}\s*", "", line.strip()).strip().strip("【】").strip()
    return (s or "配图").replace("[", "").replace("]", "")


def _inject_by_index(body_md: str, draft_id: str, cover_url: str, sec_urls: list[str]) -> str:
    """按小节**序号**插入配图（不依赖标题文本匹配，规避 R5 的标题体系不一致）。

    位置与数量只看第几个小节、第几张 sec 图；标题文本仅用作 alt（无障碍/可读性），
    即便提示词里的小节标题与正文标题完全不同也不会插错位置。
    """
    from core.text_denoise import is_section_heading
    lines = body_md.splitlines()
    out: list[str] = []
    sec_idx = 0
    cover_done = False
    for ln in lines:
        heading = is_section_heading(ln)
        if heading and not cover_done and cover_url:
            out.append(f"![封面]({cover_url})\n")
            cover_done = True
        out.append(ln)
        if heading and sec_idx < len(sec_urls):
            out.append(f"\n![{_heading_label(ln)}]({sec_urls[sec_idx]})\n")
            sec_idx += 1
    if not cover_done and cover_url:
        out.insert(0, f"![封面]({cover_url})\n")
    for url in sec_urls[sec_idx:]:
        out.append(f"\n![配图]({url})\n")
    return "\n".join(out).strip()


def validate(body_md: str, draft_id: str, ddir: Path | None = None) -> list[str]:
    """返回正文中所有「本地但不存在」的图片地址，供发布前自检使用。"""
    missing: list[str] = []
    for m in MD_IMG_RE.finditer(body_md or ""):
        src = m.group(2).split("?")[0].strip()
        if PLACEHOLDER_RE.match(src):
            missing.append(src)
            continue
        if local_image_exists(src, ddir, strict=True) is False:
            missing.append(src)
    return missing
