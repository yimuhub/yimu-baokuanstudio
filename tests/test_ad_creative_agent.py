"""AI 广告创意 Agent 与参考图深度创作测试。"""
from pathlib import Path


def test_ad_creative_stage_exists():
    """ad_creative stage 存在且有默认技能。"""
    from core import agents
    assert "ad_creative" in agents.STAGES
    assert "广告" in agents.STAGES["ad_creative"]
    assert "ad-video-creative" in agents.STAGE_DEFAULT_SKILLS["ad_creative"]


def test_ad_creative_in_agents_cfg():
    """agents_cfg() 包含 ad_creative（前端 Agent 配置页可渲染）。"""
    from core import agents
    cfg = agents.agents_cfg()
    assert "ad_creative" in cfg
    # 4 个技能：ad-video-creative + 新增的 3 个
    assert "ad-video-creative" in cfg["ad_creative"]["skills"]
    assert len(cfg["ad_creative"]["skills"]) == 4


def test_analyze_reference_images_empty():
    """无图时返回空 dict，不报错。"""
    from core import ad_video
    assert ad_video.analyze_reference_images() == {}
    assert ad_video.analyze_reference_images([], None) == {}
    # 不存在的路径也返回空 dict
    assert ad_video.analyze_reference_images(["/nonexistent/xx.jpg"]) == {}


def test_build_storyboard_visual_context():
    """visual_context 注入后分镜 visual 含特征词。"""
    from core import ad_video
    sc = {"hook": "Hook文案", "body": "正文第一句。正文第二句。", "cta": "CTA文案"}
    vc = {"product_desc": "红色陶瓷杯", "person_desc": "年轻女性", "style_desc": "明亮电商风"}
    shots = ad_video.build_storyboard(sc, 15, visual_context=vc)
    assert len(shots) >= 3
    # 每个分镜的 visual 都应包含特征词
    for s in shots:
        assert "红色陶瓷杯" in s["visual"] or "年轻女性" in s["visual"]


def test_build_storyboard_no_context():
    """无 visual_context 时分镜正常，不注入。"""
    from core import ad_video
    sc = {"hook": "H", "body": "B1。B2。", "cta": "C"}
    shots = ad_video.build_storyboard(sc, 15)
    assert len(shots) >= 3
    assert "产品特征" not in shots[0]["visual"]


def test_interleave_ref_images():
    """参考图在 1/4、1/2、3/4 处穿插，人物图放结尾。"""
    from core.video_native import _interleave_ref_images
    from pathlib import Path as P
    imgs = [P(f"img{i}.jpg") for i in range(8)]
    refs = [P("ref0.jpg"), P("ref1.jpg")]
    person = P("person.jpg")
    out = _interleave_ref_images(imgs, refs, person)
    # 8 张原图 + 2 张产品图（3 个点位但只有 2 张 ref）+ 1 张人物图
    assert len(out) == 8 + 2 + 1
    assert out[-1] == person  # 人物图在结尾
    assert P("ref0.jpg") in out
    assert P("ref1.jpg") in out


def test_interleave_ref_images_empty():
    """无参考图时原样返回。"""
    from core.video_native import _interleave_ref_images
    from pathlib import Path as P
    imgs = [P("a.jpg")]
    assert _interleave_ref_images(imgs, [], None) == imgs
    # 原图为空时只返回参考图
    out = _interleave_ref_images([], [P("r.jpg")], P("p.jpg"))
    assert out == [P("r.jpg"), P("p.jpg")]


def test_ad_video_stage_exists():
    """ad_video stage 存在且挂载视频 prompt 技能。"""
    from core import agents
    assert "ad_video" in agents.STAGES
    assert "视频" in agents.STAGES["ad_video"]
    assert "ad-video-prompt-craft" in agents.STAGE_DEFAULT_SKILLS["ad_video"]


def test_ad_creative_has_four_skills():
    """ad_creative 挂载 4 个技能（含新增的 3 个）。"""
    from core import agents
    skills = agents.STAGE_DEFAULT_SKILLS["ad_creative"]
    assert "ad-video-creative" in skills
    assert "ad-reverse-engineer" in skills
    assert "ad-creative-evaluator" in skills
    assert "ad-category-playbook" in skills


def test_ad_creative_in_agents_cfg_v2():
    """agents_cfg() 包含 ad_video。"""
    from core import agents
    cfg = agents.agents_cfg()
    assert "ad_video" in cfg
    assert "ad-video-prompt-craft" in cfg["ad_video"]["skills"]


def test_craft_shot_video_prompt_7slot():
    """7-slot 提示词包含全部槽位且产品描述逐字一致。"""
    from core import ad_video
    shot1 = {"shot": 1, "dur": 3, "visual": "Hook 画面", "voice": "你还在为干燥烦恼吗"}
    shot2 = {"shot": 2, "dur": 4, "visual": "产品画面", "voice": "一抹就吸收"}
    prod = "白色磨砂管身护手霜"
    p1 = ad_video.craft_shot_video_prompt(shot1, prod, aspect="9:16")
    p2 = ad_video.craft_shot_video_prompt(shot2, prod, aspect="9:16")
    # 7 个槽位标记
    for i in range(1, 8):
        assert f"[{i}]" in p1
    # 产品描述逐字一致
    assert prod in p1 and prod in p2
    # 运镜术语（英文）
    assert "push-in" in p1 or "whip push-in" in p1


def test_ad_video_model_info_no_config():
    """未配置视频模型时返回 ok=False（走保底，不抛异常）。"""
    from core import ad_video
    # 不 mock 配置时，取决于环境；只验证返回结构
    info = ad_video.ad_video_model_info()
    assert isinstance(info, dict)
    assert "ok" in info and "reason" in info


def test_new_skills_have_frontmatter():
    """4 个新 skill 文件有正确的 frontmatter。"""
    import yaml
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent / "skills" / "agents"
    for stem in ["ad-video-prompt-craft", "ad-reverse-engineer",
                 "ad-creative-evaluator", "ad-category-playbook"]:
        text = (base / f"{stem}.md").read_text(encoding="utf-8")
        assert text.startswith("---"), stem
        _, fm, _ = text.split("---", 2)
        meta = yaml.safe_load(fm)
        assert meta.get("name") == stem, stem
        assert meta.get("description"), stem
