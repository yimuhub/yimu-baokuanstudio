"""MPT 任务执行器：由 MoneyPrinterTurbo 自己的 venv 解释器运行。

用法: .venv/bin/python core/video_runner.py '<json参数>'
json: {"tid": "...", "subject": "...", "script": "...", "terms": ["..."]}
结束输出一行 RESULT_JSON: {...}
"""
import json
import sys
import os

MPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                       "vendors", "MoneyPrinterTurbo")
sys.path.insert(0, MPT_DIR)


def main():
    cfg = json.loads(sys.argv[1])
    from app.services import task as mpt_task
    from app.models.schema import VideoParams, MaterialInfo

    materials = []
    video_source = "pexels"
    if cfg.get("video_materials"):
        video_source = "local"
        for m in cfg["video_materials"]:
            if isinstance(m, str):
                materials.append(MaterialInfo(url=m, duration=cfg.get("clip", 3)))
            elif isinstance(m, dict):
                materials.append(MaterialInfo(url=m.get("url", ""), duration=m.get("duration", cfg.get("clip", 3))))

    params = VideoParams(
        video_subject=cfg["subject"],
        video_script=cfg["script"],
        video_terms=cfg["terms"],
        video_aspect=cfg.get("aspect", "9:16"),
        video_clip_duration=int(cfg.get("clip", 3)),
        voice_name=cfg.get("voice", "zh-CN-XiaoxiaoNeural"),
        subtitle_enabled=cfg.get("subtitle_enabled", True),
        subtitle_position=cfg.get("subtitle_position", "bottom"),
        text_fore_color=cfg.get("text_fore_color", "#FFFFFF"),
        bgm_type=cfg.get("bgm_type", "random"),
        bgm_file=cfg.get("bgm_file", ""),
        bgm_volume=float(cfg.get("bgm_volume", 0.2)),
        video_source=video_source,
        video_materials=materials if materials else None,
        video_count=1,
    )
    mpt_task.start(cfg["tid"], params)
    mp4 = os.path.join(MPT_DIR, "storage", "tasks", cfg["tid"], "final-1.mp4")
    print("RESULT_JSON:" + json.dumps({"ok": os.path.exists(mp4), "mp4": mp4},
                                       ensure_ascii=False))


if __name__ == "__main__":
    main()
