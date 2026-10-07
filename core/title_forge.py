"""标题五式赛马池引擎（Title Forge）。

基于百万爆款提炼的 5 大爆款标题公式：
1. 数字悬念式（量化对比 + 留白悬念）
2. 反常识避坑式（击碎认知 + 规避损失）
3. 干货清单式（极高利他 + 收藏驱动）
4. 身份代入式（人群定位 + 情感共鸣）
5. 场景故事式（30字场景 + 戏剧性冲突）

为每篇稿件并行产出 5 大赛马标题，支持在手机壳预览上一键切换。
"""
import json
import re
from typing import Optional
from core import agents, llm

TITLE_SYSTEM_PROMPT = """你是顶级新媒体爆款操盘手，深谙今日头条、微信公众号和小红书的点击率算法逻辑。
请为文章提炼并生成 5 个不同策略的顶级爆款标题（每个标题 ≤ 30 字，严禁口水话，必须带钩子）。

按以下 5 种模式严格输出，不要输出任何额外废话：
1. 数字悬念式：包含具体数字反差（如《3个内幕曝光后，我彻底改变了看法》）
2. 反常识避坑式：击碎固有常识（如《千万别再跟风了！很多人第一步就踩大坑》）
3. 干货清单式：极具利他收藏属性（如《建议全家收藏：2026超全避坑指南完整版》）
4. 身份代入式：精准点名人群（如《给所有新手的一份大实话：真没你想的那么容易》）
5. 场景故事式：30字内现场画面感（如《在工坊坐了整整三天，我终于看懂了这门绝活》）

严格按以下 JSON 数组格式返回，不要代码块标记：
[
  {"type": "数字悬念", "title": "标题内容", "score": 95, "hook": "数字量化+悬念留白"},
  {"type": "反常识避坑", "title": "标题内容", "score": 93, "hook": "打破固有认知，规避损失"},
  {"type": "干货清单", "title": "标题内容", "score": 90, "hook": "极高利他价值，引爆收藏"},
  {"type": "身份代入", "title": "标题内容", "score": 88, "hook": "人群精准对齐，心理共鸣"},
  {"type": "场景故事", "title": "标题内容", "score": 87, "hook": "电影级画面开场，沉浸代入"}
]"""


def _fallback_titles(title: str) -> list[dict]:
    clean = re.sub(r"[：:·\s]+", " ", title).strip()[:20]
    return [
        {"type": "数字悬念", "title": f"3个关键细节：{clean}背后的真实真相", "score": 92, "hook": "数字量化+悬念留白"},
        {"type": "反常识避坑", "title": f"别再盲目跟风了！关于{clean}的几个大实话", "score": 90, "hook": "打破固有认知，规避损失"},
        {"type": "干货清单", "title": f"建议永久收藏：{clean}最全实操避坑指南", "score": 88, "hook": "极高利他价值，引爆收藏"},
        {"type": "身份代入", "title": f"给所有爱生活的人：一定要尽早知道{clean}", "score": 86, "hook": "人群精准对齐，心理共鸣"},
        {"type": "场景故事", "title": f"深入现场探访：在真实的场景里看懂{clean}", "score": 85, "hook": "现场画面开场，沉浸代入"}
    ]


def generate_candidate_titles(current_title: str, body_text: str, model: Optional[str] = None) -> list[dict]:
    """调用 LLM 生成 5 大维度的赛马候选标题。"""
    if not llm.available():
        return _fallback_titles(current_title)

    try:
        user_msg = f"【当前文章标题】：{current_title}\n【文章核心正文摘要】：\n{body_text[:2000]}"
        raw = agents.chat_for("write", [
            {"role": "system", "content": TITLE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg}
        ], fallback_model=model or "", temperature=0.85)

        m = re.search(r"\[.*\]", raw, re.S)
        if m:
            items = json.loads(m.group(0))
            if isinstance(items, list) and len(items) >= 3:
                for it in items:
                    it["type_name"] = it.get("type", "爆款公式")
                return items[:5]
    except Exception:
        pass

    fallback = _fallback_titles(current_title)
    for it in fallback:
        it["type_name"] = it.get("type", "爆款公式")
    return fallback
