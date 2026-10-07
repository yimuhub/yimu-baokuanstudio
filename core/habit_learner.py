"""
创作者习惯自主进化与自学习系统 (Habit-to-Skill Autonomous Learner)
自动跟踪创作者定稿与修改偏好，自主进化沉淀为专属 Prompt 技能 user-evolving-habit.md
"""
import datetime
import logging
import os
import re
from pathlib import Path

from core import db, llm

logger = logging.getLogger(__name__)

HABIT_SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "agents" / "user-evolving-habit.md"

DEFAULT_HABIT_TEMPLATE = """---
name: user-evolving-habit
description: 创作者专属自主进化习惯（根据历史定稿习惯与笔触自动提炼学习）
---
创作者专属笔触与习惯规范（当前为初始基线，随使用自动进化）：
- 表达风格：清爽精炼，避免空话套话
- 段落节奏：段落保持 3-4 行，适度留白与呼吸感
- 视觉重点：核心观点自然加粗，避免过度堆砌
- 情绪基调：真诚、专业、有穿透力
"""

EVOLVE_PROMPT = """你是一名资深文本风格逆向分析专家与 Prompt 架构师。
以下是创作者近期多篇定稿/修改后的优质内容样本：

{samples_text}

请对该创作者的独特写作习惯、语言风格与排版偏好进行深度逆向提炼，提炼出 5-7 条精准、具体、可被大模型执行的【创作笔触军规】：
包括但不限于：
1. 破题方式与 Hook 习惯（如何开篇、如何制造悬念/痛点）
2. 句式与段落节奏（长短句比例、断句习惯、段落行数）
3. 用词口癖与口吻风格（专业冷静、幽默辛辣、金句偏好、常用标点/Emoji）
4. 论证结构与逻辑展开习惯（对比、清单、故事化切入）
5. 结尾与互动习惯（总结方式、行动号召、签名档）

请严格按照以下 Markdown 格式输出（必须包含 frontmatter 元数据）：
---
name: user-evolving-habit
description: 创作者专属自主进化习惯（已学习 {evolved_time}）
---
创作者专属进化笔触与习惯军规（已通过历史稿件自主进化）：
- [维度1] 具体习惯规则
- [维度2] 具体习惯规则
- [维度3] 具体习惯规则
- [维度4] 具体习惯规则
- [维度5] 具体习惯规则
- [维度6] 具体习惯规则
"""

def ensure_habit_skill_exists():
    """确保习惯技能文件存在"""
    if not HABIT_SKILL_PATH.exists():
        HABIT_SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
        HABIT_SKILL_PATH.write_text(DEFAULT_HABIT_TEMPLATE, encoding="utf-8")

def get_habit_status() -> dict:
    """获取当前习惯技能的状态与摘要"""
    ensure_habit_skill_exists()
    try:
        content = HABIT_SKILL_PATH.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        
        # 提取描述与条目（排除 frontmatter 分割线）
        rules = [line.strip().lstrip("-* ").strip() for line in lines if line.strip().startswith(("- ", "* ")) and line.strip().lstrip("-* ").strip()]
        mtime = datetime.datetime.fromtimestamp(HABIT_SKILL_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        
        is_default = "当前为初始基线" in content
        
        return {
            "exists": True,
            "is_default": is_default,
            "last_updated": mtime,
            "rules_count": len(rules),
            "rules": rules,
            "raw_content": content
        }
    except Exception as e:
        logger.error(f"Failed to read habit skill: {e}")
        return {
            "exists": False,
            "error": str(e)
        }

def evolve_from_drafts(limit: int = 5) -> dict:
    """
    从数据库中提取最近的草稿样本进行分析，自主进化习惯技能
    """
    ensure_habit_skill_exists()
    all_drafts = db.list_drafts()
    drafts = all_drafts[:limit] if all_drafts else []
    if not drafts:
        return {"success": False, "message": "暂无足够草稿供学习"}
        
    samples = []
    for idx, d in enumerate(drafts, 1):
        title = d.get("title", "")
        body = d.get("body_md", "") or ""
        if len(body) < 100:
            continue
        # 截取前 800 字作为风格样本
        sample_snippet = body[:800]
        samples.append(f"【样本 {idx} 标题：{title}】\n{sample_snippet}\n")
        
    if not samples:
        return {"success": False, "message": "草稿正文字数不足，无法提取风格特征"}
        
    samples_text = "\n---\n".join(samples)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    prompt = EVOLVE_PROMPT.format(samples_text=samples_text, evolved_time=now_str)
    
    try:
        evolved_md = llm.call(
            prompt=prompt,
            system="你是一名专业的内容风格提炼分析大师。严格按要求格式输出 Markdown 文件内容。",
            temperature=0.4
        )
        
        # 验证返回内容
        if "---" in evolved_md and "user-evolving-habit" in evolved_md:
            HABIT_SKILL_PATH.write_text(evolved_md.strip() + "\n", encoding="utf-8")
            return {
                "success": True,
                "message": "习惯技能已成功自主进化并更新",
                "status": get_habit_status()
            }
        else:
            # 补齐 frontmatter
            clean_rules = evolved_md.strip()
            full_content = f"---\nname: user-evolving-habit\ndescription: 创作者专属自主进化习惯（已学习 {now_str}）\n---\n创作者专属进化笔触与习惯军规：\n{clean_rules}\n"
            HABIT_SKILL_PATH.write_text(full_content, encoding="utf-8")
            return {
                "success": True,
                "message": "习惯技能已自主进化完成",
                "status": get_habit_status()
            }
    except Exception as e:
        logger.error(f"Habit evolution error: {e}")
        return {"success": False, "message": f"习惯提炼失败: {str(e)}"}

def reset_habit_skill() -> dict:
    """重置为默认基准习惯"""
    try:
        HABIT_SKILL_PATH.write_text(DEFAULT_HABIT_TEMPLATE, encoding="utf-8")
        return {"success": True, "message": "已重置为初始基线习惯", "status": get_habit_status()}
    except Exception as e:
        return {"success": False, "message": str(e)}
