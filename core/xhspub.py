"""小红书发布：接入 vendors/XiaohongshuSkills（CDP 方案，需扫码登录一次）。

- 发布：取草稿的 xhs.md（标题+正文）与卡片图，调 cdp_publish.py publish
- 登录：login 命令弹窗扫码（一次即可，登录态本地缓存）
- 风控提醒：用小号、控频，发布前人工审核
"""
import re
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
XS_DIR = BASE / "vendors" / "XiaohongshuSkills"
CLI = XS_DIR / "scripts" / "cdp_publish.py"


CDP_PORT = 9555


def available() -> bool:
    return CLI.exists() and (XS_DIR / ".venv" / "bin" / "python").exists()


def _run(args: list, timeout: int = 600, headed: bool = False) -> tuple[int, str]:
    py = XS_DIR / ".venv" / "bin" / "python"
    cmd = [str(py), str(CLI), "--port", str(CDP_PORT)]
    if not headed:
        cmd.append("--headless")
    cmd += args
    r = subprocess.run(cmd, cwd=str(XS_DIR), capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def _venv_python() -> Path:
    return XS_DIR / ".venv" / "bin" / "python"


def logged_in() -> bool:
    if not available():
        return False
    # 快速探测 127.0.0.1:9555 端口，若端口未开启说明无本地 CDP 实例，绝不后台拉起外部浏览器
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{CDP_PORT}/json/version")
        with urllib.request.urlopen(req, timeout=0.3) as resp:
            if resp.status != 200:
                return False
    except Exception:
        return False
    try:
        code, out = _run(["check-login"], timeout=10)
        low = out.lower()
        return code == 0 and ("已登录" in out or ("logged" in low and "not" not in low))
    except Exception:
        return False


def get_qrcode() -> dict:
    if not available():
        return {"logged_in": False, "qrcode_data_url": "", "error": "小红书技能依赖未安装"}
    code, out = _run(["get-login-qrcode", "--wait-seconds", "15"], timeout=35, headed=False)
    idx = out.find("GET_LOGIN_QRCODE_RESULT:")
    if idx != -1:
        json_str = out[idx + len("GET_LOGIN_QRCODE_RESULT:"):].strip()
        import json
        try:
            return json.loads(json_str)
        except Exception as e:
            return {"logged_in": False, "qrcode_data_url": "", "error": f"解析二维码失败: {e}"}
    return {"logged_in": False, "qrcode_data_url": "", "error": out.strip()[-300:] or "获取二维码超时"}


def _xhs_content(draft_id: str) -> tuple[str, str, list[str]]:
    """从草稿取 (标题, 正文, 图片绝对路径列表)。"""
    from core.db import draft_dir, get_draft
    d = get_draft(draft_id)
    if not d:
        raise RuntimeError("草稿不存在")
    ddir = draft_dir(draft_id)
    xf = ddir / "xhs.md"
    if not xf.exists():
        raise RuntimeError("没有小红书文案：先在小红书 Tab 点「AI 重排（小红书化）」")
    text = xf.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else d["title"]
    content = "\n".join(lines[1:]).strip() or d["title"]
    # 标题长度限制：中文/中文标点按2，英文数字按1，≤38
    def wlen(x):
        return sum(2 if ord(c) > 127 else 1 for c in x)
    if wlen(title) > 38:
        title = title[:19]
    imgs = [str(p.resolve()) for p in sorted(ddir.glob("card-*.png"))]
    if not imgs:
        raise RuntimeError("没有卡片图片：先重渲卡片再发布（小红书图文必须有图）")
    return title, content, imgs


def publish(draft_id: str, emit=None) -> dict:
    emit = emit or (lambda *_: None)
    title, content, imgs = _xhs_content(draft_id)
    emit(f"发布中：{len(imgs)} 张图（约1-2分钟）…")
    code, out = _run(["publish", "--title", title, "--content", content] + imgs, timeout=900)
    tail = out.strip().splitlines()[-8:] if out.strip() else []
    ok = code == 0 and ("成功" in out or "success" in out.lower() or "已发布" in out)
    return {"ok": ok, "title": title, "detail": "\n".join(tail) or f"exit={code}"}


def login(emit=None) -> dict:
    """有窗口模式扫码登录（约2分钟内完成）。"""
    emit = emit or (lambda *_: None)
    emit("弹出浏览器，请用小红书 App 扫码…")
    code, out = _run(["login"], timeout=300, headed=True)
    ok = logged_in()
    return {"ok": ok, "detail": "登录成功" if ok else out.strip()[-300:]}
