"""短剧 Step 4/Step 6 风格一致性测试：生成图片时 prompt 必须包含风格 suffix。"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import short_drama


def _make_proj(style_key):
    return {
        "step1": {"style": style_key},
        "step3": {
            "characters": [
                {"id": "c1", "name": "主角", "turnaround_prompt": "a hero standing",
                 "portrait_prompt": "hero portrait"}
            ],
            "scenes": [],
            "props": [],
        },
        "step4": {},
        "step5": {"shots": []},
        "current_step": 4,
    }


def test_step4_turnaround_injects_character_sheet_style():
    """四视图用 character_sheet_style。"""
    proj = _make_proj("cyberpunk_scifi")
    captured = {}

    def fake_gen_image(prompt, out_file, **kwargs):
        captured["prompt"] = prompt
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        Path(out_file).write_bytes(b"x" * 2000)
        return True

    with mock.patch.object(short_drama, "get_pipeline_project", return_value=proj), \
         mock.patch.object(short_drama, "save_pipeline_project"), \
         mock.patch("core.imagegen.gen_image", side_effect=fake_gen_image), \
         mock.patch.object(short_drama, "_get_drama_dir",
                           return_value=Path("/tmp/test_drama_style")):
        short_drama.step4_generate_asset_image("d1", "character", "c1", is_turnaround=True)

    suffix = short_drama.DRAMA_STYLES["cyberpunk_scifi"]["character_sheet_style"]
    assert suffix[:20] in captured["prompt"], "四视图 prompt 未注入风格"
    assert "a hero standing" in captured["prompt"], "原 prompt 丢失"


def test_step4_portrait_injects_suffix():
    """正面/场景图用 suffix。"""
    proj = _make_proj("cyberpunk_scifi")
    captured = {}

    def fake_gen_image(prompt, out_file, **kwargs):
        captured["prompt"] = prompt
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        Path(out_file).write_bytes(b"x" * 2000)
        return True

    with mock.patch.object(short_drama, "get_pipeline_project", return_value=proj), \
         mock.patch.object(short_drama, "save_pipeline_project"), \
         mock.patch("core.imagegen.gen_image", side_effect=fake_gen_image), \
         mock.patch.object(short_drama, "_get_drama_dir",
                           return_value=Path("/tmp/test_drama_style2")):
        short_drama.step4_generate_asset_image("d2", "character", "c1", is_turnaround=False)

    suffix = short_drama.DRAMA_STYLES["cyberpunk_scifi"]["suffix"]
    assert suffix[:20] in captured["prompt"], "正面图 prompt 未注入风格"


def test_different_styles_different_suffix():
    """不同 style_key 注入不同 suffix。"""
    styles = list(short_drama.DRAMA_STYLES.keys())[:3]
    suffixes = {short_drama.DRAMA_STYLES[k]["suffix"][:30] for k in styles}
    assert len(suffixes) == 3, "风格 suffix 应各不相同"


def test_step6_shot_injects_suffix():
    """Step 6 分镜关键帧注入风格。"""
    proj = _make_proj("oriental_mythology")
    proj["step5"] = {"shots": [{"shot_id": 1, "image_prompt_en": "a mountain scene"}]}
    captured = {}

    def fake_gen_image(prompt, out_file, **kwargs):
        captured["prompt"] = prompt
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        Path(out_file).write_bytes(b"x" * 2000)
        return True

    with mock.patch.object(short_drama, "get_pipeline_project", return_value=proj), \
         mock.patch.object(short_drama, "save_pipeline_project"), \
         mock.patch("core.imagegen.gen_image", side_effect=fake_gen_image), \
         mock.patch.object(short_drama, "_get_drama_dir",
                           return_value=Path("/tmp/test_drama_style3")), \
         mock.patch("shutil.copyfile"):
        short_drama.step6_generate_shot_image("d3", 1)

    suffix = short_drama.DRAMA_STYLES["oriental_mythology"]["suffix"]
    assert suffix[:20] in captured["prompt"], "分镜 prompt 未注入风格"
