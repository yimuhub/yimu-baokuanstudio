# SPDX-License-Identifier: BUSL-1.1
"""图片生成编排：提示词工程 → 可配置的上游直连 → 评分 → 赛马 → 记账。

⭐ 硬规则（丢数据 / 丢钱 / 泄密类）：
- client 为 None 时必须抛 UpstreamNotReady：禁止静默返回假成功（红线）。
- prompt 为空时抛 BadRequest；n 越界钳制到 1..4。
- 每张候选图固定消耗 CREDITS_PER_IMAGE=5（整数 credits）；
  金额换算用整数分（1 credit = 100 分），杜绝浮点。
- 记账失败不阻塞返回，但必须如实写入返回体的 "ledger_warning"，绝不吞掉。
"""

from __future__ import annotations

from studio.errors import BadRequest, UpstreamNotReady, new_request_id
from studio.ledger import calc_cost, record_ledger_entry

from .judge import judge_image
from .race import race

CREDITS_PER_IMAGE = 5  # ⭐ 每张候选图固定消耗 5 credits（整数）
CENTS_PER_CREDIT = 100  # ⭐ 1 credit = 100 分（整数分，杜绝浮点）


def _clamp_n(n: object) -> int:
    """生成张数钳制到 1..4；非整数直接拒绝。"""
    try:
        value = int(n)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise BadRequest("生成张数 n 必须是整数")
    return max(1, min(4, value))


def _parse_size(size: str) -> tuple[int, int]:
    """解析 "1024x1024" 类尺寸；解析失败回落到 1024×1024。"""
    try:
        width_s, height_s = str(size).lower().split("x")
        width, height = int(width_s), int(height_s)
        if width > 0 and height > 0:
            return width, height
    except (ValueError, AttributeError):
        pass
    return 1024, 1024


def generate(
    *,
    prompt: str,
    style_id: str = "cinematic",
    n: int = 3,
    tenant_id: str,
    db_url: str,
    client=None,
    size: str = "1024x1024",
) -> dict:
    """生成图片并走赛马优选，全流程记账。

    Args:
        prompt: 用户原始描述（贫瘠输入也行，PromptForge 会补全）。
        style_id: 风格 id，默认 "cinematic"。
        n: 候选张数，钳制到 1..4。
        tenant_id: 租户 id（账本写入必填）。
        db_url: 数据库 URL。
        client: 可配置的上游直连（可调用对象）；
            签名 ``client(prompt=..., n=..., size=...) ->
            list[{"url": str, "revised_prompt": str}]``。
            为 None 时直接抛 UpstreamNotReady。
        size: 尺寸字符串，如 "1024x1024"。

    Returns:
        {"ok": True, "winner": {...}, "candidates": [...],
         "cost_credits": int, "request_id": str,
         "ledger_warning": str（仅记账失败时出现）}。
    """
    request_id = new_request_id()

    if not str(prompt or "").strip():
        raise BadRequest("请输入图片描述，描述不能为空")
    n = _clamp_n(n)

    # ⭐ 红线：上游未就绪时必须显式报错，禁止静默返回假成功。
    if client is None:
        raise UpstreamNotReady("图片服务暂时不可用，请稍后再试")

    # 1) 提示词工程（并行开发的模块，调用时延迟导入）
    from studio.promptforge import forge_prompt

    forged = forge_prompt(prompt, style_id) or {}
    rich_prompt = str(forged.get("prompt") or prompt).strip()

    # 2) 上游直连生成候选图
    raw_candidates = client(prompt=rich_prompt, n=n, size=size) or []
    if not raw_candidates:
        raise UpstreamNotReady("图片服务暂时没有返回候选图片，请稍后再试")

    # 3) 逐张评分
    width, height = _parse_size(size)
    candidates: list[dict] = []
    for raw in raw_candidates:
        raw = raw or {}
        scored = judge_image(
            {
                "url": str(raw.get("url") or ""),
                "prompt": prompt,
                "width": width,
                "height": height,
                "revised_prompt": str(raw.get("revised_prompt") or ""),
            }
        )
        candidates.append(
            {
                "url": str(raw.get("url") or ""),
                "revised_prompt": str(raw.get("revised_prompt") or ""),
                **scored,
            }
        )

    # 4) 赛马优选
    race_result = race(candidates)

    # 5) ⭐ 记账：每张候选图 5 credits，calc_cost 汇总，只增不改写 ledger。
    entries = [{"cost_credits": CREDITS_PER_IMAGE} for _ in candidates]
    cost_credits = calc_cost(entries)["total_credits"]

    failed = 0
    last_error = ""
    for _entry in entries:
        try:
            record_ledger_entry(
                tenant_id=tenant_id,
                model="image-gen",
                direction="output",
                tokens=0,
                cost_cents=CREDITS_PER_IMAGE * CENTS_PER_CREDIT,
                key_id=None,
                db_url=db_url,
            )
        except Exception as exc:  # 记账失败不阻塞返回，但必须如实告知
            failed += 1
            last_error = str(exc)

    result = {
        "ok": True,
        "winner": race_result["winner"],
        "candidates": race_result["ranking"],
        "cost_credits": cost_credits,
        "request_id": request_id,
    }
    if failed:
        result["ledger_warning"] = f"{failed} 条账本记录写入失败：{last_error}"
    return result
