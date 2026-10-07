# SPDX-License-Identifier: BUSL-1.1
"""审美基准集：8 条固定中文 prompt，用于图片质量回归（CI 可复现）。

⭐ 硬规则：
- BENCHMARK_PROMPTS 固定不变：改动任一条都会让历史基准失去可比性。
- 全程不调外部服务：用确定性测试图（benchmark:// 协议）+ 本地 Judge。
"""

from __future__ import annotations

from datetime import datetime, timezone

from .judge import judge_image

BENCHMARK_PROMPTS: list[dict] = [
    {
        "id": "bench_01",
        "prompt": "一位身穿素白汉服的年轻女子站在盛开的桃花树下回眸，柔光，电影感人像",
        "style_id": "cinematic",
    },
    {
        "id": "bench_02",
        "prompt": "黄昏时分的雪山与湖泊倒影，云雾缭绕，广角风光摄影",
        "style_id": "landscape",
    },
    {
        "id": "bench_03",
        "prompt": "一瓶极简设计的香水摆在白色大理石台面上，柔和侧光，产品广告摄影",
        "style_id": "product",
    },
    {
        "id": "bench_04",
        "prompt": "未来城市悬浮在云海之上，飞船穿梭其间，赛博朋克概念艺术",
        "style_id": "cyberpunk",
    },
    {
        "id": "bench_05",
        "prompt": "一位老人布满皱纹的双手捧着一盏暖黄色的油灯，纪实摄影风格",
        "style_id": "documentary",
    },
    {
        "id": "bench_06",
        "prompt": "水墨风格的山水长卷，远山如黛，大面积留白",
        "style_id": "ink",
    },
    {
        "id": "bench_07",
        "prompt": "一双白色运动鞋悬浮在半空，水花飞溅，高速摄影定格",
        "style_id": "product",
    },
    {
        "id": "bench_08",
        "prompt": "一只由星云构成的巨鲸游弋在璀璨夜空中，超现实主义",
        "style_id": "surreal",
    },
]


def run_benchmark(judge_fn=None) -> dict:
    """跑一遍审美基准集。

    对每条基准 prompt 构造确定性测试图
    （url=f"benchmark://{id}"，width=1024, height=1024），
    用 judge_fn（默认 judge_image）打分。

    Returns:
        {"items": [{"id","prompt","quality_score","fidelity_score","defects"}],
         "avg_quality": float, "avg_fidelity": float, "count": 8}。
    """
    judge = judge_fn or judge_image
    items: list[dict] = []
    for bench in BENCHMARK_PROMPTS:
        image = {
            "url": f"benchmark://{bench['id']}",
            "prompt": bench["prompt"],
            "width": 1024,
            "height": 1024,
            "revised_prompt": f"基准图：{bench['prompt']}",
        }
        scored = judge(image)
        items.append(
            {
                "id": bench["id"],
                "prompt": bench["prompt"],
                "quality_score": scored["quality_score"],
                "fidelity_score": scored["fidelity_score"],
                "defects": scored["defects"],
            }
        )
    count = len(items)
    avg_quality = round(sum(i["quality_score"] for i in items) / count, 2)
    avg_fidelity = round(sum(i["fidelity_score"] for i in items) / count, 2)
    return {
        "items": items,
        "avg_quality": avg_quality,
        "avg_fidelity": avg_fidelity,
        "count": count,
    }


def get_benchmark_report() -> dict:
    """基准报告：在 run_benchmark 结果上加 UTC 生成时间。

    供 GET /api/image/benchmark 直接返回（CI 门禁读取）。
    """
    report = run_benchmark()
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    return report
