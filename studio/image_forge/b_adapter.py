# SPDX-License-Identifier: BUSL-1.1
"""B 生图引擎适配器：把 core/imagegen.py 包装成 image_forge 的 client 协议。

协议：``client(prompt=..., n=..., size=...) -> list[{"url": str, "revised_prompt": str}]``

B 原有函数（gen_image / gen_image_pollinations 等）原样保留，对外 API 不变；
本模块只新增一层包装，把 B 的"写文件返回 bool"转换成 forge 需要的"返回候选列表"。
"""

from __future__ import annotations

import uuid
from pathlib import Path


def make_b_image_client(out_dir: str | Path, **gen_kwargs):
    """构造符合 image_forge client 协议的可调用对象。

    Args:
        out_dir: 候选图落盘目录（自动创建）。
        gen_kwargs: 透传给 core.imagegen.gen_image 的额外参数
            （如 context_title / context_sub / angle_idx / is_cover）。

    返回的 client 签名：``client(*, prompt, n=3, size="1024x1024")``。
    单张生成失败不影响其他候选；全部失败时返回空列表，
    上游 generate() 会将其转为 UpstreamNotReady 报错（不静默成功）。
    """

    from core.imagegen import gen_image, photojournalism_prompt_engine

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def client(*, prompt: str, n: int = 3, size: str = "1024x1024") -> list[dict]:
        try:
            count = int(n)
        except (TypeError, ValueError):
            count = 3
        count = max(1, min(4, count))
        # B 内部的提示词升华结果一并返回，给 Judge 做保真评分用
        revised = photojournalism_prompt_engine(prompt)
        candidates: list[dict] = []
        for i in range(count):
            path = out / f"forge_{uuid.uuid4().hex[:8]}_{i}.png"
            try:
                ok = gen_image(prompt, path, size=size, **gen_kwargs)
            except Exception:
                ok = False
            if ok and path.exists() and path.stat().st_size > 0:
                candidates.append({"url": str(path), "revised_prompt": revised})
        return candidates

    return client


def generate_with_forge(
    *,
    prompt: str,
    style_id: str = "cinematic",
    n: int = 3,
    tenant_id: str,
    db_url: str,
    size: str = "1024x1024",
    out_dir: str | Path,
    **gen_kwargs,
) -> dict:
    """一站式生图：B 引擎 → PromptForge → 赛马 → Judge → 记账。

    Args:
        prompt: 用户原始描述；style_id: 风格 id；n: 候选张数（1..4）；
        tenant_id: 租户 id（账本必填）；db_url: 账本库 URL
            （如 "sqlite:////path/to/yimu-baokuanstudio/data/mediaflow.db"）；
        size: 尺寸；out_dir: 候选图落盘目录。

    Returns:
        与 studio.image_forge.generate.generate 一致：
        {"ok", "winner", "candidates", "cost_credits", "request_id"}。
    """
    from .generate import generate

    client = make_b_image_client(out_dir, **gen_kwargs)
    return generate(
        prompt=prompt,
        style_id=style_id,
        n=n,
        tenant_id=tenant_id,
        db_url=db_url,
        client=client,
        size=size,
    )
