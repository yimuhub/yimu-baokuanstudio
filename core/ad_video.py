"""AI 产品广告短片流水线（全AI 视频大模型生成模式）。

双 Agent 架构：
    ad_creative（广告创意分析 Agent）：卖点提炼 → 广告脚本(Hook+正文+CTA)
        → 分镜（7-slot 产品镜头公式，产品描述全片逐字一致）
    ad_video（广告视频生成 Agent）：按分镜逐镜头调用视频大模型生成视频片段
        → ffmpeg 无损拼接成片（+ 单轨 TTS 配音 + 字幕）

创意层方法论：skills/agents/ad-video-creative.md（5 Hook + 5 结构 + 6 CTA）
    + ad-category-playbook.md（16 角度 + 类目套路）
    + ad-reverse-engineer.md（竞品拆解） + ad-creative-evaluator.md（成片自检）；
视频层方法论：skills/agents/ad-video-prompt-craft.md（SLCT 四要素 + 7-slot 公式）。

降级策略：视频大模型未配置/失败 → AI 图片 + ffmpeg 轮播保底（不报错）。

不重复造轮子：LLM 调用走 core/agents.chat_for，视频模型走 core/llm.resolve_llm_endpoint，
拼接/配音/字幕复用 core/video_native 的 _concat_videos/_make_tts_audio/_mux_audio_subtitle。
"""
import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)

SECONDS_WORDS = {15: (70, 90), 30: (140, 170), 60: (280, 320)}


def _llm(stage: str, prompt: str, **kw) -> str:
    from core import agents
    return agents.chat_for(stage, [{"role": "user", "content": prompt}], **kw)


def _encode_image_base64(path: str) -> str | None:
    """图片转 base64 data URI（供视觉大模型分析用）。"""
    import base64
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size < 1000:
            return None
        ext = p.suffix.lower().lstrip(".") or "jpeg"
        if ext == "jpg":
            ext = "jpeg"
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:image/{ext};base64,{data}"
    except Exception as exc:  # noqa: BLE001
        log.warning("[ad_video] 图片 base64 编码失败 [%s]: %s", path, exc)
        return None


def analyze_reference_images(ref_images: list | None = None,
                             person_ref_image: str | None = None) -> dict:
    """用视觉大模型分析参考图，提取产品/人物特征描述。

    Returns: {"product_desc": str, "person_desc": str, "style_desc": str}
    无图或分析失败时返回空 dict（不报错，调用方按无 visual_context 处理）。
    """
    out = {"product_desc": "", "person_desc": "", "style_desc": ""}
    jobs = []
    for rp in (ref_images or [])[:3]:
        uri = _encode_image_base64(rp)
        if uri:
            jobs.append(("product", uri))
    if person_ref_image:
        uri = _encode_image_base64(person_ref_image)
        if uri:
            jobs.append(("person", uri))
    if not jobs:
        return {}

    # OpenAI 兼容的 vision 消息格式；不支持的供应商会报错，走 except 兜底
    try:
        from core import llm as _llm_mod
        contents = [
            {"type": "text", "text":
             "请分析以下参考图片，用中文输出 JSON："
             "{\"product_desc\": \"产品外观/颜色/材质/视觉卖点（≤60字，无产品图则空）\", "
             "\"person_desc\": \"人物性别/年龄感/服装/气质（≤60字，无人物图则空）\", "
             "\"style_desc\": \"整体视觉风格关键词（≤30字，如：明亮电商风/高级质感）\"}。"
             "只输出 JSON，不要其他内容。"}
        ]
        for kind, uri in jobs:
            contents.append({
                "type": "image_url",
                "image_url": {"url": uri},
            })
        raw = _llm_mod.chat(
            [{"role": "user", "content": contents}],
            stage="ad_creative", temperature=0.3,
        )
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            out["product_desc"] = str(d.get("product_desc", ""))[:80]
            out["person_desc"] = str(d.get("person_desc", ""))[:80]
            out["style_desc"] = str(d.get("style_desc", ""))[:40]
            log.info("[ad_video] 视觉分析: %s", out)
            return out
    except Exception as exc:  # noqa: BLE001
        log.warning("[ad_video] 视觉分析失败（已降级为空）: %s", exc)
    return {}


def extract_selling_points(product_name: str, product_desc: str,
                           audience: str = "大众消费者") -> dict:
    """卖点提炼：返回 {points: [...], pain: str}。"""
    prompt = (
        "请从以下产品描述中提炼 3-5 个核心卖点：\n"
        "【产品】" + product_name + "\n【描述】" + product_desc
        + "\n【人群】" + audience + "\n\n"
        "要求：\n"
        "1. 每个卖点 ≤20 字，说人话，不说参数\n"
        "2. 按\"能让用户心动的程度\"排序，最强的放第一\n"
        "3. 至少 1 个功能卖点 + 1 个情绪卖点\n"
        "4. 严格按 JSON 输出：{\"points\": [\"卖点1\", ...], \"pain\": \"用户痛点一句话\"}\n"
        "5. 描述里没有的功效不许编造"
    )
    raw = _llm("ad_creative", prompt, temperature=0.5)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
            points = [str(p)[:30] for p in d.get("points", [])][:5]
            if points:
                return {"points": points, "pain": str(d.get("pain", ""))[:60]}
        except Exception:
            pass
    sents = [s.strip() for s in re.split(r"[。！；\n]", product_desc) if s.strip()]
    return {"points": sents[:4] or [product_desc[:20]], "pain": ""}


def _pick_formulas(product_desc: str, seconds: int):
    """按规则选 Hook/正文/CTA（轻量启发式，LLM 会再校验）。"""
    desc = product_desc
    hook = "痛点提问式"
    if re.search(r"\d+%|\d+万|第一|首款", desc):
        hook = "惊人数据式"
    elif re.search(r"早上|晚上|每天|出门", desc):
        hook = "场景代入式"
    body = "卖点瀑布"
    if re.search(r"痛|烦恼|焦虑|难", desc):
        body = "PAS"
    elif re.search(r"之前|之后|对比|原来", desc):
        body = "前后对比"
    cta = "立即下单"
    if re.search(r"限时|优惠|立减|折", desc):
        cta = "限时优惠"
    elif re.search(r"免费|试用|体验", desc):
        cta = "免费试用"
    return hook, body, cta


def generate_ad_script(product_name: str, selling_points: list,
                       audience: str = "大众消费者", seconds: int = 15,
                       aspect: str = "9:16") -> dict:
    """广告脚本：Hook + 正文 + CTA + 素材检索词。"""
    seconds = 15 if seconds <= 20 else (30 if seconds <= 45 else 60)
    lo, hi = SECONDS_WORDS[seconds]
    hook_t, body_t, cta_t = _pick_formulas(" ".join(selling_points), seconds)
    prompt = (
        "你是短视频广告编导。用下面的方法论写一条 "
        + str(seconds) + " 秒产品广告口播脚本：\n\n"
        + "【产品】" + product_name + "\n"
        + "【卖点】" + "; ".join(selling_points) + "\n"
        + "【人群】" + audience + "\n"
        + "【Hook 公式】" + hook_t + "\n【正文结构】" + body_t
        + "\n【CTA】" + cta_t + "\n\n"
        + "输出格式（严格遵守）：\n"
        + "HOOK: <前3秒文案，一句话>\n"
        + "BODY: <正文口播，口语化，一句一断句>\n"
        + "CTA: <结尾行动号召，一句话>\n"
        + "TERMS: <3-4 个英文素材检索词，逗号分隔>\n\n"
        + "约束：总字数约 " + str(lo) + "~" + str(hi)
        + " 字；禁用\"首先/其次/总之\"；不许编造没有的产品功效。"
    )
    raw = _llm("ad_creative", prompt, temperature=0.7)

    def _grab(tag: str) -> str:
        mm = re.search(tag + r"\s*[:：]\s*(.+?)(?=\n[A-Z]+:|\Z)", raw, re.DOTALL)
        return mm.group(1).strip() if mm else ""

    hook = _grab("HOOK")
    body = _grab("BODY")
    cta = _grab("CTA")
    terms_raw = _grab("TERMS")
    terms = [t.strip() for t in re.split(r"[,，]", terms_raw) if t.strip()][:4]
    if not terms:
        terms = ["product", "lifestyle"]
    script = "。".join(s for s in (hook, body, cta) if s)
    return {
        "hook": hook, "body": body, "cta": cta,
        "script": script, "terms": terms,
        "formulas": {"hook": hook_t, "body": body_t, "cta": cta_t},
    }


def build_storyboard(script_info: dict, seconds: int = 15,
                     visual_context: dict | None = None) -> list:
    """分镜：按 Hook/正文/CTA 拆成 3-5 秒一个镜头。

    visual_context: analyze_reference_images() 的结果，用于在每个分镜
    的 visual 描述里注入产品/人物特征词，保证全片视觉一致性。
    """
    hook, body, cta = script_info["hook"], script_info["body"], script_info["cta"]
    body_sents = [s.strip() for s in re.split(r"[。！？\n]", body) if s.strip()]
    shots = []
    t = 0

    vc = visual_context or {}
    _prod = (vc.get("product_desc") or "").strip()
    _person = (vc.get("person_desc") or "").strip()
    _style = (vc.get("style_desc") or "").strip()
    _ctx_suffix = " ".join(s for s in (
        f"产品特征：{_prod}。" if _prod else "",
        f"人物特征：{_person}。" if _person else "",
        f"风格：{_style}。" if _style else "",
    ) if s).strip()

    def _visual(base: str) -> str:
        # 视觉一致性注入：每个分镜都带上产品/人物特征词
        return (base + " " + _ctx_suffix).strip() if _ctx_suffix else base

    def _add(dur: int, visual: str, voice: str):
        nonlocal t
        shots.append({"shot": len(shots) + 1, "start": t, "dur": dur,
                      "visual": visual, "voice": voice, "subtitle": voice})
        t += dur

    _add(3, _visual("Hook 画面：强视觉冲击开场（产品特写/痛点场景）"), hook)
    body_budget = seconds - 3 - 3
    per = max(3, body_budget // max(1, len(body_sents)))
    for s in body_sents:
        if t + per > seconds - 3:
            break
        _add(per, _visual("产品画面：" + s[:20] + "（近景/使用场景）"), s)
    if t < seconds:
        _add(seconds - t, _visual("CTA 画面：产品全貌 + 行动号召大字"), cta)
    return shots


# ------------------------------------------------------------------ 7-slot --
# 7 槽位产品镜头公式（ad-video-prompt-craft.md）：
#   [1 产品精确描述] + [2 一个动作] + [3 一个运镜] + [4 镜头与灯光]
#   + [5 场景] + [6 写实风格词] + [7 时长]
# 铁律：槽位 1 的产品标准描述全片逐字一致，只换动作和构图。

CAMERA_TERMS = {
    "推镜": "slow push-in",
    "拉镜": "slow pull-back",
    "横移": "lateral tracking move",
    "环绕": "slow orbit around product",
    "手持": "subtle handheld follow",
    "固定": "static locked-off shot",
    "急推": "whip push-in",
}

STYLE_SUFFIX_EN = (
    "photorealistic commercial photography, 8k detail, "
    "cinematic color grading, no text, no watermark"
)


def craft_shot_video_prompt(shot: dict, product_std_desc: str,
                            aspect: str = "9:16",
                            person_desc: str = "",
                            style_desc: str = "") -> str:
    """为单个分镜构造 7-slot 视频生成提示词（英文，视频模型更懂）。

    shot: build_storyboard() 的分镜 dict（含 shot/dur/visual/voice）
    product_std_desc: 产品标准描述（全片逐字一致）
    """
    visual_cn = shot.get("visual", "")
    dur = int(shot.get("dur", 3) or 3)
    # 按分镜位置选运镜：Hook 用急推/推镜，正文用推镜/横移/环绕，CTA 用固定
    idx = int(shot.get("shot", 1) or 1)
    if idx == 1:
        camera_cn, camera_en = "急推", CAMERA_TERMS["急推"]
    elif "CTA" in visual_cn or "行动号召" in visual_cn:
        camera_cn, camera_en = "固定", CAMERA_TERMS["固定"]
    elif idx % 3 == 0:
        camera_cn, camera_en = "环绕", CAMERA_TERMS["环绕"]
    elif idx % 2 == 0:
        camera_cn, camera_en = "推镜", CAMERA_TERMS["推镜"]
    else:
        camera_cn, camera_en = "横移", CAMERA_TERMS["横移"]

    # 动作：从口播文案提炼一个核心动作（取前 12 字，去标点）
    action = re.sub(r"[，。！？、；：\s]", "", shot.get("voice", ""))[:12] or "产品展示"
    # 场景：优先用视觉分析的风格，否则通用
    scene = style_desc.strip() if style_desc else "clean minimal studio background"
    person_bit = f", featuring {person_desc.strip()}" if person_desc.strip() else ""

    prompt_en = (
        f"[1] {product_std_desc.strip()}{person_bit}. "
        f"[2] Action: {action}. "
        f"[3] Camera: {camera_en}. "
        f"[4] Close-up shot, soft studio lighting with gentle rim light. "
        f"[5] Scene: {scene}. "
        f"[6] {STYLE_SUFFIX_EN}. "
        f"[7] Duration: {dur} seconds, {aspect} vertical video."
        if aspect == "9:16" else
        f"[1] {product_std_desc.strip()}{person_bit}. "
        f"[2] Action: {action}. "
        f"[3] Camera: {camera_en}. "
        f"[4] Medium shot, soft studio lighting with gentle rim light. "
        f"[5] Scene: {scene}. "
        f"[6] {STYLE_SUFFIX_EN}. "
        f"[7] Duration: {dur} seconds, {aspect} widescreen video."
    )
    return prompt_en


def ad_video_model_info() -> dict:
    """解析 ad_video stage 配置的视频大模型。

    Returns: {"ok": bool, "base": str, "key": str, "model": str,
              "provider_id": str, "reason": str}
    ok=False 时调用方走 AI 图片保底。
    """
    from core import agents
    from core.llm import resolve_llm_endpoint, classify_model
    model = (agents.model_for("ad_video", "") or "").strip()
    if not model:
        return {"ok": False, "reason": "ad_video stage 未配置视频大模型（去「🤖 Agent 配置 → 🎬 广告视频生成 Agent」选择模型）"}
    try:
        base, key, resolved, pid = resolve_llm_endpoint(model)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"解析视频模型失败：{exc}"}
    if not key:
        return {"ok": False, "reason": f"视频模型 [{resolved}] 未配置 API Key"}
    if classify_model(resolved) != "video":
        return {"ok": False,
                "reason": f"[{resolved}] 不是视频生成模型（去 Agent 配置换成 Kling/Veo/Sora 等视频模型）"}
    return {"ok": True, "base": (base or "").rstrip("/"), "key": key,
            "model": resolved, "provider_id": pid, "reason": ""}


def _call_video_model(prompt: str, out_path: Path, duration_s: int,
                      aspect: str, info: dict, ref_image: str | None = None) -> bool:
    """调视频大模型生成单个镜头片段。

    端点兼容：{base}/videos/generations 与 {base}/v1/videos/generations。
    返回 True/False（失败不抛异常，上层决定降级）。
    """
    import httpx
    base, key, model = info["base"], info["key"], info["model"]
    candidates = []
    if base.endswith("/videos/generations"):
        candidates.append(base)
    elif base.endswith("/v1"):
        candidates.append(f"{base}/videos/generations")
    else:
        candidates.append(f"{base}/v1/videos/generations")
        candidates.append(f"{base}/videos/generations")

    body = {
        "model": model,
        "prompt": prompt,
        "duration": duration_s,
        "aspect_ratio": aspect,
        "size": "1080x1920" if aspect == "9:16" else "1920x1080",
    }
    # 参考图驱动（reference-to-video）：有产品图时作为首帧/参考传入
    if ref_image:
        b64 = _encode_image_base64(ref_image)
        if b64:
            body["image"] = b64
            body["image_url"] = b64

    is_local = "127.0.0.1" in base or "localhost" in base
    for url in candidates:
        try:
            with httpx.Client(timeout=600, trust_env=not is_local) as client:
                r = client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                )
                if r.status_code != 200:
                    log.warning("[ad_video] 视频模型 %s 返回 %s: %s",
                                url, r.status_code, r.text[:200])
                    continue
                data = r.json()
                arr = data.get("data") if isinstance(data.get("data"), list) else []
                item = arr[0] if arr else data
                import base64 as _b64
                b64v = item.get("b64_json") or item.get("video") or data.get("b64_json")
                vurl = (item.get("url") or item.get("video_url")
                        or data.get("url") or data.get("video_url"))
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if b64v:
                    out_path.write_bytes(_b64.b64decode(b64v))
                    return True
                if vurl:
                    with httpx.Client(timeout=300, follow_redirects=True) as dl:
                        dr = dl.get(vurl)
                        if dr.status_code == 200 and len(dr.content) > 1024:
                            out_path.write_bytes(dr.content)
                            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("[ad_video] 视频模型调用失败 %s: %s", url, exc)
    return False


def generate_video_shots(storyboard: list, product_std_desc: str,
                         work_dir: Path, aspect: str = "9:16",
                         person_desc: str = "", style_desc: str = "",
                         ref_images: list | None = None,
                         emit=None) -> dict:
    """ad_video Agent：按分镜逐镜头调用视频大模型。

    Returns: {"clips": [Path...], "prompts": [str...], "video_model": str,
              "fallback": bool, "reason": str}
    fallback=True 表示视频模型不可用，上层走 AI 图片保底。
    """
    emit = emit or (lambda *_: None)
    info = ad_video_model_info()
    if not info["ok"]:
        log.warning("[ad_video] %s，走 AI 图片保底", info["reason"])
        return {"clips": [], "prompts": [], "video_model": "",
                "fallback": True, "reason": info["reason"]}

    clips, prompts = [], []
    ref_list = [p for p in (ref_images or []) if p]
    total = len(storyboard)
    for i, shot in enumerate(storyboard):
        prompt = craft_shot_video_prompt(
            shot, product_std_desc, aspect=aspect,
            person_desc=person_desc, style_desc=style_desc)
        prompts.append(prompt)
        out = work_dir / f"shot-{i+1:02d}.mp4"
        emit(f"🎬 AI 生成第 {i+1}/{total} 镜…")
        # 首镜优先用产品参考图做 reference-to-video
        ref = ref_list[0] if (i == 0 and ref_list) else None
        ok = _call_video_model(prompt, out, int(shot.get("dur", 3) or 3),
                               aspect, info, ref_image=ref)
        if ok and out.exists() and out.stat().st_size > 1024:
            clips.append(out)
            log.info("[ad_video] 第 %d 镜生成成功: %s", i + 1, out)
        else:
            log.warning("[ad_video] 第 %d 镜生成失败", i + 1)
    return {"clips": clips, "prompts": prompts,
            "video_model": info["model"], "fallback": False, "reason": ""}


def _assemble_ad_video(clips: list, script: str, title: str, aspect: str,
                       voice: str, work_dir: Path, emit=None) -> dict:
    """ffmpeg 无损拼接 + 单轨 TTS 配音 + 字幕（不做多余合成）。"""
    emit = emit or (lambda *_: None)
    from core import video_native
    if not video_native.ffmpeg_available():
        raise RuntimeError(
            "ffmpeg 不可用：" + video_native.ffmpeg_install_hint())
    w, h = video_native.RESOLUTIONS.get(aspect, (1080, 1920))

    emit("拼接视频片段…")
    stitched = work_dir / "stitched.mp4"
    video_native._concat_videos([Path(c) for c in clips], stitched, w, h)

    emit("合成配音…")
    audio = video_native._make_tts_audio(script, work_dir / "voice.mp3", voice)
    total_s = video_native._probe_duration(audio) if audio else 0
    total_s = total_s or video_native._probe_duration(stitched) or 15.0

    emit("烧录字幕…")
    srt = video_native._script_to_srt(script, total_s, work_dir / "sub.srt")
    final = work_dir / f"ad-{aspect.replace(':', 'x')}.mp4"
    video_native._mux_audio_subtitle(stitched, audio, srt, final, total_s)

    dur = video_native._probe_duration(final) or total_s
    size_kb = final.stat().st_size // 1024 if final.exists() else 0
    return {"mp4": str(final), "duration_s": round(dur, 1),
            "has_audio": bool(audio), "size_kb": size_kb,
            "material": "ai_video_model", "aspect": aspect}


def _fallback_image_video(product_name: str, script: str, terms: list,
                          seconds: int, aspect: str, voice: str, title: str,
                          work_dir: Path, emit=None) -> dict:
    """保底：视频大模型不可用时，AI 图片 + ffmpeg 轮播（不报错）。"""
    emit = emit or (lambda *_: None)
    from core import video_native
    log.warning("[ad_video] 视频大模型不可用，降级 AI 图片轮播")
    res = video_native.make_video_native(
        script=script, terms=terms, seconds=seconds,
        aspect=aspect, voice=voice, title=title,
        work_dir=work_dir, emit=emit,
        material_mode="ai_only",
    )
    res["material"] = "ai_image_fallback"
    return res


def make_ad_video(product_name: str, product_desc: str, seconds: int = 15,
                  aspect: str = "9:16", audience: str = "大众消费者",
                  voice: str = "zh-CN-XiaoxiaoNeural",
                  work_dir=None, emit=None,
                  selling_points: list | None = None,
                  ref_images: list | None = None,
                  person_ref_image: str | None = None,
                  # --- deprecated（旧三配音模式已下线，前端不再传，仅保兼容） ---
                  voice_mode: str = "auto",
                  custom_audio_path: str | None = None) -> dict:
    """AI 产品广告短片一键生成（全AI 视频大模型生成模式）。

    流程：
      1. ad_creative Agent：卖点提炼 → 广告脚本(Hook+正文+CTA) → 分镜(7-slot)
      2. ad_video Agent：按分镜逐镜头调用视频大模型生成视频片段
      3. ffmpeg 无损拼接 + 单轨 TTS 配音 + 字幕

    Args:
        selling_points: 预生成的卖点列表；传了则跳过自动提炼
        ref_images: 产品参考图路径列表（首镜做 reference-to-video）
        person_ref_image: 卖货人员参考图路径（注入分镜人物描述）

    Returns: {"mp4", "duration_s", "script", "storyboard", "selling_points",
              "video_prompts", "video_model", "fallback", ...}
    """
    emit = emit or (lambda *_: None)
    seconds = 15 if seconds <= 20 else (30 if seconds <= 45 else 60)
    if aspect not in ("16:9", "9:16"):
        aspect = "9:16"
    work_dir = Path(work_dir) if work_dir else (
        Path(__file__).resolve().parent.parent / "runs" / "advideo"
        / f"ad-{int(time.time())}")
    work_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. ad_creative Agent：卖点 → 脚本 → 分镜 ----
    if selling_points:
        sp = {"points": [str(p)[:30] for p in selling_points][:5], "pain": ""}
        emit("使用已确认的卖点…")
    else:
        emit("提炼产品卖点…")
        sp = extract_selling_points(product_name, product_desc, audience)
    log.info("[ad_video] 卖点: %s", sp["points"])

    # 视觉分析：参考图深度 AI 创作（产品/人物特征全片贯穿）
    ref_list = [p for p in (ref_images or []) if p]
    visual_context = {}
    if ref_list or person_ref_image:
        emit("AI 分析参考图（产品/人物特征提取）…")
        visual_context = analyze_reference_images(ref_list, person_ref_image)

    emit("生成广告脚本（Hook+正文+CTA）…")
    sc = generate_ad_script(product_name, sp["points"], audience, seconds, aspect)
    log.info("[ad_video] 脚本 %d 字, terms=%s", len(sc["script"]), sc["terms"])

    emit("拆分镜（7-slot 产品镜头公式）…")
    shots = build_storyboard(sc, seconds, visual_context=visual_context)

    # 产品标准描述：全片逐字一致（视觉分析优先，否则用产品名+描述）
    vc = visual_context or {}
    product_std_desc = ((vc.get("product_desc") or "").strip()
                        or f"{product_name}：{product_desc[:40]}")
    person_desc = (vc.get("person_desc") or "").strip()
    style_desc = (vc.get("style_desc") or "").strip()

    # ---- 2. ad_video Agent：逐镜头生成视频 ----
    gen = generate_video_shots(
        shots, product_std_desc, work_dir, aspect=aspect,
        person_desc=person_desc, style_desc=style_desc,
        ref_images=ref_list, emit=emit)

    # ---- 3. 拼接成片 ----
    if gen["clips"]:
        emit("拼接成片…")
        asm = _assemble_ad_video(gen["clips"], sc["script"], product_name,
                                 aspect, voice, work_dir, emit=emit)
    else:
        emit(f"视频模型不可用（{gen['reason'][:60]}），走 AI 图片保底…")
        asm = _fallback_image_video(product_name, sc["script"], sc["terms"],
                                    seconds, aspect, voice, product_name,
                                    work_dir, emit=emit)

    asm.update({
        "product": product_name,
        "selling_points": sp["points"],
        "script_info": {k: sc[k] for k in ("hook", "body", "cta", "formulas")},
        "storyboard": shots,
        "video_prompts": gen["prompts"],
        "video_model": gen.get("video_model", ""),
        "fallback": gen["fallback"],
        "fallback_reason": gen.get("reason", ""),
        "engine": "ad_video_dual_agent",
        "ref_image_count": len(ref_list),
        "visual_context": visual_context,
        "product_std_desc": product_std_desc,
    })
    return asm
