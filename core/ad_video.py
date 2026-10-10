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
                       aspect: str = "9:16", ad_mode: str = "avatar",
                       custom_script: str = "") -> dict:
    """广告脚本：Hook + 正文 + CTA + 素材检索词。支持数字人口播模式与自定义输入。"""
    seconds = 15 if seconds <= 20 else (30 if seconds <= 45 else 60)
    lo, hi = SECONDS_WORDS[seconds]

    if custom_script and custom_script.strip():
        lines = [ln.strip() for ln in custom_script.strip().split("\n") if ln.strip()]
        hook = lines[0] if lines else custom_script[:30]
        cta = lines[-1] if len(lines) > 2 else "赶紧点击抢先体验！"
        body = "。".join(lines[1:-1]) if len(lines) > 2 else ("。".join(lines[1:]) if len(lines) > 1 else custom_script)
        return {
            "hook": hook, "body": body, "cta": cta,
            "script": custom_script.strip(), "terms": ["product", "avatar", "lifestyle"],
            "formulas": {"hook": "自定义/改写", "body": "数字人口播", "cta": "促单"},
        }

    hook_t, body_t, cta_t = _pick_formulas(" ".join(selling_points or []), seconds)
    
    avatar_hint = ""
    if ad_mode == "avatar":
        avatar_hint = (
            "【AI 数字人口播主播人设模式要求】：\n"
            "- 以第一人称'我'面对面与观众对话，语气极其亲切、自然、接地气，消灭一切书面腔。\n"
            "- 黄金3秒第一句话直击痛点，引爆好奇或共鸣。\n"
            "- 关键转折处自然嵌入肢体与微表情标记，例如 [微笑视镜] [拿起展示] [手势强调] [恍然大悟]。\n"
            "- 结尾给出笃定的行动呼吁，引导立即购买或了解详情。\n"
        )

    prompt = (
        "你是顶尖的短视频爆款广告编导与带货口播操盘手。用下面的方法论写一条 "
        + str(seconds) + " 秒产品广告口播脚本：\n\n"
        + "【产品】" + product_name + "\n"
        + "【卖点】" + "; ".join(selling_points or []) + "\n"
        + "【人群】" + audience + "\n"
        + avatar_hint
        + "【Hook 公式】" + hook_t + "\n【正文结构】" + body_t
        + "\n【CTA】" + cta_t + "\n\n"
        + "输出格式（严格遵守）：\n"
        + "HOOK: <前3秒文案，一句话，有穿透力>\n"
        + "BODY: <正文口播，口语化，一句一断句，结合亲测体验或爽点>\n"
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
                     visual_context: dict | None = None,
                     ad_mode: str = "avatar") -> list:
    """分镜：按 Hook/正文/CTA 拆成 3-5 秒一个镜头，支持标记数字人出镜镜头。

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
        return (base + " " + _ctx_suffix).strip() if _ctx_suffix else base

    def _add(dur: int, visual: str, voice: str, is_avatar: bool = False):
        nonlocal t
        shots.append({"shot": len(shots) + 1, "start": t, "dur": dur,
                      "visual": visual, "voice": voice, "subtitle": voice,
                      "is_avatar": is_avatar})
        t += dur

    # 首镜 Hook
    is_hook_av = (ad_mode in ("avatar", "interleaved"))
    hook_v = _visual("Hook 画面：AI 数字人主播出镜面对面口播，强视觉冲击开场" if is_hook_av else "Hook 画面：强视觉冲击开场（产品特写/痛点场景）")
    _add(3, hook_v, hook, is_avatar=is_hook_av)

    body_budget = seconds - 3 - 3
    per = max(3, body_budget // max(1, len(body_sents)))
    for idx, s in enumerate(body_sents):
        if t + per > seconds - 3:
            break
        # 正文段：若为全程数字人模式，且为偶数镜，安排数字人手持讲解；奇数镜安排产品特写
        is_body_av = (ad_mode == "avatar" and idx % 2 == 1)
        b_desc = "AI 数字人主播手持产品出镜讲解：" if is_body_av else "产品细节特写："
        _add(per, _visual(b_desc + s[:20] + "（近景/使用场景）"), s, is_avatar=is_body_av)

    # 尾镜 CTA
    if t < seconds:
        is_cta_av = (ad_mode in ("avatar", "interleaved"))
        cta_v = _visual("CTA 画面：AI 数字人主播手持产品号召行动，强促单指令" if is_cta_av else "CTA 画面：产品全貌 + 行动号召大字")
        _add(seconds - t, cta_v, cta, is_avatar=is_cta_av)
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
                            style_desc: str = "",
                            is_avatar: bool = False) -> str:
    """为单个分镜构造 7-slot 视频生成提示词（英文，视频模型更懂）。
    支持数字人口播镜头（强调人物口播、眼神、表情、手势出镜）。
    """
    visual_cn = shot.get("visual", "")
    dur = int(shot.get("dur", 3) or 3)
    is_av = is_avatar or shot.get("is_avatar", False)
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

    if is_av:
        person_core = (person_desc.strip() or "professional charming presenter")
        prompt_en = (
            f"[1] Photorealistic AI digital human talking avatar of this person ({person_core}), presenting and recommending {product_std_desc.strip()}. "
            f"[2] Action: looking at camera and speaking naturally to audience, lifelike facial expressions, subtle hand gestures. "
            f"[3] Camera: {camera_en}. "
            f"[4] Portrait close-up shot, soft commercial studio lighting, natural depth of field. "
            f"[5] Scene: {scene}. "
            f"[6] {STYLE_SUFFIX_EN}. "
            f"[7] Duration: {dur} seconds, {aspect} vertical video."
            if aspect == "9:16" else
            f"[1] Photorealistic AI digital human talking avatar of this person ({person_core}), presenting and recommending {product_std_desc.strip()}. "
            f"[2] Action: looking at camera and speaking naturally to audience, lifelike facial expressions, subtle hand gestures. "
            f"[3] Camera: {camera_en}. "
            f"[4] Medium portrait shot, soft commercial studio lighting, natural depth of field. "
            f"[5] Scene: {scene}. "
            f"[6] {STYLE_SUFFIX_EN}. "
            f"[7] Duration: {dur} seconds, {aspect} widescreen video."
        )
        return prompt_en

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


def ad_video_model_info(model_override: str = "") -> dict:
    """解析 ad_video stage 配置的视频大模型。

    model_override：显式指定要用的模型（可带「供应商/模型」前缀，如
    "volcengine/ark-video-x" 或 "yimu_official/agnes-video-v2.0"），
    会按该模型重新解析 base/key/供应商，不再沿用 ad_video stage 默认端点。

    Returns: {"ok": bool, "base": str, "key": str, "model": str,
              "provider_id": str, "reason": str}
    ok=False 时调用方走 AI 图片保底。
    """
    from core import agents
    from core.llm import resolve_llm_endpoint, classify_model
    model = (model_override or (agents.model_for("ad_video", "") or "")).strip()
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

    支持两类协议（自动探测，按顺序尝试）：
    1. Agnes 异步任务式：POST {base}/videos 建任务 → GET {base}/videos/{task_id} 轮询
       → 从 completed 响应的 metadata.url 下载 mp4。
    2. 通用同步式：POST {base}/videos/generations（Kling/Veo/Sora 等 OpenAI 风格端点），
       响应直接带 b64_json / url。
    返回 True/False（失败不抛异常，上层决定降级）。
    """
    import httpx
    import base64 as _b64
    import time as _t
    from core import video_rules
    base, key, model = info["base"], info["key"], info["model"]
    is_local = "127.0.0.1" in base or "localhost" in "127.0.0.1" or "localhost" in base
    # 📏 能力表钳制：按模型匹配 data/video_model_rules.json 规则（时长档位/画幅字段/禁用字段/轮询参数/附加头）
    rule = video_rules.match_rule(model)
    dur = video_rules.clamp_duration(duration_s, rule)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    headers.update(video_rules.extra_headers(rule))

    # ── 1. Agnes 异步任务协议（网关 8787 /v1/videos）────────────────────
    if base.endswith("/v1") or "/v1/" in base:
        create_url = f"{base}/videos"
        body = {
            "model": model,
            "mode": "image" if ref_image else "text",
            "prompt": prompt,
            "aspect_ratio": aspect,
        }
        # 参考图驱动（reference-to-video）：有产品图时作为首帧/参考传入（尽力而为）
        if ref_image:
            b64 = _encode_image_base64(ref_image)
            if b64:
                body["image"] = b64
                body["image_url"] = b64
        # 时长字段按能力表决定（Agnes Flash 规则为 drop_field：dur=None 时不传，避免 400）
        if dur is not None:
            body[video_rules.duration_field(rule)] = dur
        try:
            with httpx.Client(timeout=120, trust_env=not is_local) as client:
                # 503 队列满退避重试：上游 Agnes 视频有并发上限，多段并发生成时易撞 503。
                # 等队列释放再试（最多 5 次、每次 20s 退避），避免整段直接失败。
                r = None
                for attempt in range(3):
                    r = client.post(create_url, json=body, headers=headers)
                    if r.status_code == 503:
                        log.warning("[ad_video] 视频队列已满（503），第 %d/3 次退避重试…", attempt + 1)
                        _t.sleep(4 * (attempt + 1))
                        continue
                    break
                if r.status_code == 200:
                    d = r.json()
                    task_id = (d.get("task_id") or d.get("id") or d.get("video_id")
                               or (d.get("metadata") or {}).get("video_id"))
                    if not task_id:
                        log.warning("[ad_video] 异步建任务 200 但响应无 task_id: %s", r.text[:200])
                        return False
                    log.info("[ad_video] 视频任务已创建 task_id=%s，开始轮询…", task_id)
                    poll_url = f"{base}/videos/{task_id}"
                    # 轮询参数按能力表规则（Agnes 默认 5s × 120 次 = 10 分钟，Flash 单次约 1-4 分钟）
                    _iv, _polls = video_rules.poll_params(rule)
                    for _ in range(_polls):
                        _t.sleep(_iv)
                        pr = client.get(poll_url, headers=headers, timeout=60)
                        if pr.status_code != 200:
                            log.warning("[ad_video] 轮询 %s 返回 %s: %s",
                                        poll_url, pr.status_code, pr.text[:200])
                            continue
                        pd = pr.json()
                        status = str(pd.get("status", "")).lower()
                        if status in ("completed", "success", "succeeded", "finished"):
                            meta = pd.get("metadata") or {}
                            vurl = (meta.get("url") or pd.get("url")
                                    or pd.get("video_url") or meta.get("video_url"))
                            b64v = meta.get("b64_json") or pd.get("b64_json")
                            out_path.parent.mkdir(parents=True, exist_ok=True)
                            if b64v:
                                out_path.write_bytes(_b64.b64decode(b64v))
                                log.info("[ad_video] 视频片段下载完成（b64）: %s", out_path.name)
                                return True
                            if vurl:
                                dl = client.get(vurl, timeout=300, follow_redirects=True)
                                if dl.status_code == 200 and len(dl.content) > 1024:
                                    out_path.write_bytes(dl.content)
                                    log.info("[ad_video] 视频片段下载完成: %s (%.1f MB)",
                                             out_path.name, len(dl.content) / 1048576)
                                    return True
                            log.warning("[ad_video] 任务完成但响应无下载地址: %s", pr.text[:300])
                            return False
                        if status in ("failed", "error", "cancelled"):
                            err_msg = str(pd.get("error") or pd.get("message") or pd)
                            log.warning("[ad_video] 视频任务失败: %s", pd)
                            info["last_error"] = f"上游任务执行失败: {err_msg[:200]}"
                            return False
                    log.warning("[ad_video] 视频任务 %s 轮询超时（10 分钟）", task_id)
                    info["last_error"] = f"视频生成任务轮询超时（10分钟）"
                    return False
                # 建任务非 200：404/405 说明该端点不是异步协议，落到通用同步端点尝试
                if r.status_code not in (404, 405):
                    err_msg = ""
                    try:
                        ed = r.json()
                        err_msg = (ed.get("message") or ed.get("error", {}).get("message")
                                   or ed.get("detail") or str(ed))
                    except Exception:
                        err_msg = r.text[:200]
                    log.warning("[ad_video] 异步建任务 %s 返回 %s: %s",
                                create_url, r.status_code, r.text[:300])
                    if r.status_code == 503:
                        info["last_error"] = f"视频服务队列满载繁忙 (503: {err_msg})"
                    elif r.status_code == 401:
                        info["last_error"] = f"视频大模型鉴权失败，请检查 API Key (401: {err_msg})"
                    else:
                        info["last_error"] = f"视频接口返回异常 ({r.status_code}: {err_msg})"
                    # 400（字段/模型不支持）或 503（队列满/无渠道）等：同步端点也救不了，直接判败
                    return False
        except Exception as exc:  # noqa: BLE001
            log.warning("[ad_video] 异步视频任务调用异常: %s", exc)
            info["last_error"] = f"视频接口调用异常: {exc}"
            return False

    # ── 2. 通用同步端点（OpenAI 风格 /videos/generations，如 Kling/Veo/Sora 直连）──
    candidates = []
    if base.endswith("/videos/generations"):
        candidates.append(base)
    elif base.endswith("/v1"):
        candidates.append(f"{base}/videos/generations")
    else:
        candidates.append(f"{base}/v1/videos/generations")
        candidates.append(f"{base}/videos/generations")

    body = {"model": model, "prompt": prompt}
    # 📏 时长/画幅按能力表规则：字段名（duration/seconds/durationSeconds）、钳制档位、
    # Sora 类用 size 字符串；无规则时沿用通用格式（duration + aspect_ratio + size）
    body[video_rules.duration_field(rule)] = dur if dur is not None else duration_s
    body.update(video_rules.aspect_payload(rule, aspect))
    if ref_image:
        b64 = _encode_image_base64(ref_image)
        if b64:
            body["image"] = b64
            body["image_url"] = b64

    for url in candidates:
        try:
            with httpx.Client(timeout=600, trust_env=not is_local) as client:
                r = client.post(url, json=body, headers=headers)
                if r.status_code in (404, 405):
                    continue  # 端点不存在，试下一个
                if r.status_code != 200:
                    err_msg = ""
                    try:
                        ed = r.json()
                        err_msg = (ed.get("message") or ed.get("error", {}).get("message")
                                   or ed.get("detail") or str(ed))
                    except Exception:
                        err_msg = r.text[:200]
                    log.warning("[ad_video] 视频模型 %s 返回 %s: %s",
                                url, r.status_code, r.text[:300])
                    info["last_error"] = f"通用端点返回异常 ({r.status_code}: {err_msg})"
                    return False
                data = r.json()
                arr = data.get("data") if isinstance(data.get("data"), list) else []
                item = arr[0] if arr else data
                b64v = item.get("b64_json") or item.get("video") or data.get("b64_json")
                vurl = (item.get("url") or item.get("video_url")
                        or data.get("url") or data.get("video_url"))
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if b64v:
                    out_path.write_bytes(_b64.b64decode(b64v))
                    return True
                if vurl:
                    dl = client.get(vurl, timeout=300, follow_redirects=True)
                    if dl.status_code == 200 and len(dl.content) > 1024:
                        out_path.write_bytes(dl.content)
                        return True
        except Exception as exc:  # noqa: BLE001
            log.warning("[ad_video] 视频模型调用失败 %s: %s", url, exc)
    return False


def generate_video_shots(storyboard: list, product_std_desc: str,
                         work_dir: Path, aspect: str = "9:16",
                         person_desc: str = "", style_desc: str = "",
                         ref_images: list | None = None,
                         person_ref_image: str | None = None,
                         ad_mode: str = "avatar",
                         emit=None) -> dict:
    """ad_video Agent：按分镜逐镜头调用视频大模型。支持数字人出镜与产品参考图双轨驱动。"""
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
        is_avatar_shot = shot.get("is_avatar", False)
        prompt = craft_shot_video_prompt(
            shot, product_std_desc, aspect=aspect,
            person_desc=person_desc, style_desc=style_desc,
            is_avatar=is_avatar_shot)
        prompts.append(prompt)
        out = work_dir / f"shot-{i+1:02d}.mp4"
        emit(f"🎬 AI 生成第 {i+1}/{total} 镜（{'数字人口播' if is_avatar_shot else '产品镜头'}）…")
        
        # 确定参考图：数字人镜头用人物照片驱动，产品镜头用产品图
        if is_avatar_shot and person_ref_image:
            ref = person_ref_image
        elif ref_list:
            ref = ref_list[0]
        elif person_ref_image:
            ref = person_ref_image
        else:
            ref = None

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


def rewrite_ad_script(product_name: str, product_desc: str,
                      selling_points: list | None = None,
                      audience: str = "大众消费者",
                      ad_mode: str = "avatar",
                      seconds: int = 15) -> dict:
    """为 AI 广告短片生成/改写专业口播脚本（支持数字人口播模式）。"""
    sp = selling_points
    if not sp:
        sp_res = extract_selling_points(product_name, product_desc, audience)
        sp = sp_res.get("points") or []
    sc = generate_ad_script(product_name, sp, audience, seconds=seconds, ad_mode=ad_mode)
    clean_txt = re.sub(r"\[.*?\]", "", sc["script"])
    char_count = len(re.sub(r"\s+", "", clean_txt))
    return {
        "ok": True,
        "script": sc["script"],
        "hook": sc["hook"],
        "body": sc["body"],
        "cta": sc["cta"],
        "selling_points": sp,
        "ad_mode": ad_mode,
        "char_count": char_count,
        "estimated_seconds": seconds,
    }


def make_ad_video(product_name: str, product_desc: str, seconds: int = 15,
                  aspect: str = "9:16", audience: str = "大众消费者",
                  voice: str = "zh-CN-XiaoxiaoNeural",
                  work_dir=None, emit=None,
                  selling_points: list | None = None,
                  ref_images: list | None = None,
                  person_ref_image: str | None = None,
                  voice_mode: str = "auto",
                  custom_audio_path: str | None = None,
                  ad_mode: str = "avatar",
                  custom_script: str = "") -> dict:
    """AI 产品广告短片一键生成（全AI 视频大模型生成模式，支持 AI 数字人口播）。

    流程：
      1. ad_creative Agent：卖点提炼 → 广告脚本(Hook+正文+CTA) → 分镜(7-slot)
      2. ad_video Agent：按分镜逐镜头调用视频大模型生成视频片段（支持数字人出镜参考图）
      3. ffmpeg 无损拼接 + 单轨 TTS 配音 + 字幕
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

    emit("生成广告口播脚本（Hook+正文+CTA）…")
    sc = generate_ad_script(product_name, sp["points"], audience, seconds, aspect,
                            ad_mode=ad_mode, custom_script=custom_script)
    log.info("[ad_video] 脚本 %d 字, terms=%s", len(sc["script"]), sc["terms"])

    emit("拆分镜（7-slot 产品镜头公式）…")
    shots = build_storyboard(sc, seconds, visual_context=visual_context, ad_mode=ad_mode)

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
        ref_images=ref_list, person_ref_image=person_ref_image,
        ad_mode=ad_mode, emit=emit)

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
        "ad_mode": ad_mode,
        "ref_image_count": len(ref_list),
        "visual_context": visual_context,
        "product_std_desc": product_std_desc,
    })
    return asm
