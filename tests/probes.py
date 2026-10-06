# SPDX-License-Identifier: BUSL-1.1
"""真活探针 runner：判据 = 产物存在，而非 HTTP 200。

用法（从仓库根目录）：
    python -m tests.probes      # 推荐：包模式运行
    python tests/probes.py      # 直接运行亦可

⭐ 硬规则：
- 每条探针跑在独立临时目录，数据库用隔离测试库（conftest.make_test_db）。
- 绝不写 <repo>/runs/ 或生产账本表；main() 会在探针前后检查 runs/ 是否被创建。
- 未实现的功能 → SKIP（ok=None），不算失败；骨架期 ci.sh 可全绿通过。

探针函数签名：probe_xxx(ctx) -> {"ok", "skipped", "step", "artifact", "evidence"}，
其中 ctx 含 tmp_dir（本探针独占临时目录）、db_url（隔离测试库 URL）。

被测入口契约（供 WS-B~F 实现，签名按此对接）：
- studio.pipeline.generate_draft(topic: str, out_path: str, db_url: str) -> str
- studio.pipeline.rewrite_draft(material_path: str, out_path: str, db_url: str) -> str
- studio.pipeline.deliver_draft(draft_path: str, out_dir: str, platforms: tuple, db_url: str) -> list[str]
- studio.tts.synthesize(text: str, out_path: str, db_url: str) -> str
- 视频探针不依赖 studio 实现：本机有 ffmpeg 即可合成 1 秒测试视频并断言产物存在。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 优先复用 conftest 的隔离库逻辑；直接运行时（无包上下文）退回最小本地实现。
try:
    from tests.conftest import assert_test_db_isolated, make_test_db
except ImportError:  # pragma: no cover - 仅 python tests/probes.py 直接运行时

    def assert_test_db_isolated(db_path: str) -> str:
        lowered = str(db_path).lower().replace("\\", "/")
        for marker in ("prod", "production", "生产", "主库", "yimu.db", "ledger.db", "runs/"):
            if marker in lowered:
                raise RuntimeError(f"⛔ 拦截疑似生产库路径：{db_path}")
        return db_path

    def make_test_db(prefix: str = "yimu_probe_") -> tuple[str, str]:
        import tempfile as _tf

        fd, db_path = _tf.mkstemp(prefix=prefix, suffix=".db")
        os.close(fd)
        assert_test_db_isolated(db_path)
        os.environ["YIMU_TEST_DB"] = db_path
        return db_path, f"sqlite:///{db_path}"


def _skip(step: str, reason: str) -> dict:
    """骨架期：功能未实现 → SKIP，不算失败。"""
    return {"ok": None, "skipped": True, "step": step, "artifact": None, "evidence": f"SKIP（骨架期未实现）：{reason}"}


def _fail(step: str, evidence: str) -> dict:
    return {"ok": False, "skipped": False, "step": step, "artifact": None, "evidence": evidence}


def probe_draft(ctx: dict) -> dict:
    """出稿探针：一句话 → 稿件文件存在且 ≥300 字。"""
    step = "出稿"
    try:
        from studio.pipeline import generate_draft  # type: ignore[import-not-found]
    except ImportError:
        return _skip(step, "studio.pipeline.generate_draft 未实现")
    out_path = os.path.join(ctx["tmp_dir"], "draft.md")
    try:
        generate_draft("一句话热点：社区团购买菜", out_path=out_path, db_url=ctx["db_url"])
    except Exception:
        return _fail(step, f"generate_draft 抛错：\n{traceback.format_exc(limit=3)}")
    if not os.path.exists(out_path):
        return _fail(step, f"产物缺失：{out_path} 未生成")
    size = len(Path(out_path).read_text(encoding="utf-8", errors="ignore"))
    if size < 300:
        return _fail(step, f"稿件仅 {size} 字（要求 ≥300 字）：{out_path}")
    return {"ok": True, "skipped": False, "step": step, "artifact": out_path, "evidence": f"稿件 {size} 字，文件存在"}


def probe_rewrite(ctx: dict) -> dict:
    """仿写探针：素材文件 → 初稿文件存在。"""
    step = "仿写"
    try:
        from studio.pipeline import rewrite_draft  # type: ignore[import-not-found]
    except ImportError:
        return _skip(step, "studio.pipeline.rewrite_draft 未实现")
    material = os.path.join(ctx["tmp_dir"], "material.txt")
    Path(material).write_text("社区团购的菜比菜市场便宜一半，年轻人开始算账。", encoding="utf-8")
    out_path = os.path.join(ctx["tmp_dir"], "rewrite.md")
    try:
        rewrite_draft(material_path=material, out_path=out_path, db_url=ctx["db_url"])
    except Exception:
        return _fail(step, f"rewrite_draft 抛错：\n{traceback.format_exc(limit=3)}")
    if not os.path.exists(out_path):
        return _fail(step, f"产物缺失：{out_path} 未生成")
    return {"ok": True, "skipped": False, "step": step, "artifact": out_path, "evidence": "初稿文件存在"}


def probe_deliver(ctx: dict) -> dict:
    """交付探针：稿件 → 3 平台成品文件存在（微信/小红书/抖音）。"""
    step = "交付"
    try:
        from studio.pipeline import deliver_draft  # type: ignore[import-not-found]
    except ImportError:
        return _skip(step, "studio.pipeline.deliver_draft 未实现")
    draft = os.path.join(ctx["tmp_dir"], "draft_for_deliver.md")
    Path(draft).write_text("# 50 元买菜挑战\n" + "正文。" * 200, encoding="utf-8")
    out_dir = os.path.join(ctx["tmp_dir"], "deliver")
    os.makedirs(out_dir, exist_ok=True)
    platforms = ("wechat", "xiaohongshu", "douyin")
    try:
        artifacts = deliver_draft(draft_path=draft, out_dir=out_dir, platforms=platforms, db_url=ctx["db_url"])
    except Exception:
        return _fail(step, f"deliver_draft 抛错：\n{traceback.format_exc(limit=3)}")
    artifacts = list(artifacts or [])
    missing = [a for a in artifacts if not os.path.exists(a)]
    if len(artifacts) < 3 or missing:
        return _fail(step, f"成品不足 3 平台：返回 {artifacts}，缺失 {missing}")
    return {"ok": True, "skipped": False, "step": step, "artifact": out_dir, "evidence": f"3 平台成品存在：{artifacts}"}


def probe_tts(ctx: dict) -> dict:
    """语音探针：短句 → 音频文件存在且 >0 字节。"""
    step = "语音"
    try:
        from studio.tts import synthesize  # type: ignore[import-not-found]
    except ImportError:
        return _skip(step, "studio.tts.synthesize 未实现")
    out_path = os.path.join(ctx["tmp_dir"], "hello.wav")
    try:
        synthesize("你好，一幕开场。", out_path=out_path, db_url=ctx["db_url"])
    except Exception:
        return _fail(step, f"synthesize 抛错：\n{traceback.format_exc(limit=3)}")
    if not os.path.exists(out_path):
        return _fail(step, f"产物缺失：{out_path} 未生成")
    size = os.path.getsize(out_path)
    if size <= 0:
        return _fail(step, f"音频文件 0 字节：{out_path}")
    return {"ok": True, "skipped": False, "step": step, "artifact": out_path, "evidence": f"音频 {size} 字节"}


def _video_duration_sec(path: str) -> float | None:
    """用 ffprobe 读取视频时长；无 ffprobe 时返回 None（不断言时长）。"""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(proc.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


def probe_video(ctx: dict) -> dict:
    """视频探针：ffmpeg 存在且可合成 ≥1 秒视频（产物存在性判据）。"""
    step = "视频"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return _skip(step, "本机无 ffmpeg，可安装后再跑视频探针")
    out_path = os.path.join(ctx["tmp_dir"], "probe.mp4")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
           "-pix_fmt", "yuv420p", "-y", out_path]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        return _fail(step, f"ffmpeg 合成失败：{exc}")
    if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
        return _fail(step, f"产物缺失或 0 字节：{out_path}")
    duration = _video_duration_sec(out_path)
    if duration is not None and duration < 1.0:
        return _fail(step, f"视频时长 {duration:.2f}s（要求 ≥1s）：{out_path}")
    evidence = f"ffmpeg 合成 1s 测试视频，{os.path.getsize(out_path)} 字节"
    if duration is not None:
        evidence += f"，时长 {duration:.2f}s"
    return {"ok": True, "skipped": False, "step": step, "artifact": out_path, "evidence": evidence}


PROBES = (probe_draft, probe_rewrite, probe_deliver, probe_tts, probe_video)


def main() -> int:
    """跑全部探针并打印汇总；有 FAIL 返回 1，否则返回 0（SKIP 不算失败）。"""
    tmp_dir = tempfile.mkdtemp(prefix="yimu_probe_")
    _, db_url = make_test_db(prefix="yimu_probe_db_")
    ctx = {"tmp_dir": tmp_dir, "db_url": db_url}
    runs_dir = REPO_ROOT / "runs"
    runs_existed_before = runs_dir.exists()

    print("真活探针开始（判据=产物存在；临时目录=%s）" % tmp_dir)
    results = []
    for probe in PROBES:
        try:
            result = probe(ctx)
        except Exception:
            result = _fail(probe.__name__, f"探针自身抛错：\n{traceback.format_exc(limit=3)}")
        results.append(result)
        status = "SKIP" if result["skipped"] else ("PASS" if result["ok"] else "FAIL")
        print(f"[{status}] {result['step']}：{result['evidence']}")
        if result["artifact"]:
            print(f"         产物：{result['artifact']}")

    # ⭐ 硬规则复核：探针不得写 <repo>/runs/
    if runs_dir.exists() and not runs_existed_before:
        print("⛔ FAIL：探针在仓库下创建了 runs/ 目录——探针只允许写临时目录。")
        return 1

    n_pass = sum(1 for r in results if r["ok"] is True)
    n_skip = sum(1 for r in results if r["skipped"])
    n_fail = sum(1 for r in results if r["ok"] is False)
    print(f"真活探针汇总：{n_pass} 通过，{n_skip} 跳过（骨架期未实现），{n_fail} 失败。")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
