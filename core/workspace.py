"""多品牌工作区与创作者空间中台 (Multi-Workspace & Brand Kit System)。

支持独立自媒体矩阵操盘手在不同业务/品牌工作区之间秒级平滑切换：
例如：
- 科技极客大V工作区（硬核科技、冷峻排版、16:9横版大片）
- 闺蜜情感美妆工作区（温暖碎碎念、小红书高饱和卡片、轻快口播）
- 商业观察工作区（罗振宇逻辑、思维模型、极简杂志风）

每个工作区具备独立的工作区画像、默认文风设定与数据视图。
"""
import logging
from typing import Any, Dict, List, Optional
from core import db

logger = logging.getLogger(__name__)


def get_current_workspace() -> dict:
    """获取当前活动工作区。"""
    ws = db.get_active_workspace()
    return ws


# 别名兼容
get_active_workspace = get_current_workspace


def list_all_workspaces() -> List[dict]:
    """列出所有已配置的品牌工作区。"""
    return db.list_workspaces()


def switch_workspace(workspace_id: str) -> dict:
    """切换当前系统全局活动工作区。"""
    db.set_active_workspace(workspace_id)
    ws = db.get_active_workspace()
    logger.info(f"[Workspace] 已切换至工作区: [{ws.get('id')}] {ws.get('name')}")
    return ws


def create_new_workspace(name: str, desc: str = "", config: Optional[dict] = None) -> dict:
    """创建全新的品牌工作区。"""
    if not name or not name.strip():
        raise ValueError("工作区名称不能为空")
    ws = db.create_workspace(name.strip(), desc.strip(), config=config or {})
    logger.info(f"[Workspace] 新建工作区成功: [{ws.get('id')}] {ws.get('name')}")
    return ws


def update_workspace_info(workspace_id: str, name: str, desc: str = "", config: Optional[dict] = None) -> dict:
    """编辑更新指定品牌工作区的信息与配置。"""
    if not name or not name.strip():
        raise ValueError("工作区名称不能为空")
    ws = db.update_workspace(workspace_id, name.strip(), desc.strip(), config=config)
    if not ws:
        raise ValueError(f"工作区未找到: {workspace_id}")
    logger.info(f"[Workspace] 更新工作区成功: [{ws.get('id')}] {ws.get('name')}")
    return ws


def delete_workspace_by_id(workspace_id: str) -> dict:
    """删除指定品牌工作区（系统默认兜底工作区受保护不可删除）。"""
    res = db.delete_workspace(workspace_id)
    logger.info(f"[Workspace] 删除工作区成功: [{workspace_id}]")
    return res


# ---------------- 借鉴 Easel: 账号 6 维数字画像档案 (Profile & Long-term Memory) ----------------

DEFAULT_PROFILE = {
    "positioning": "垂直行业深度实操专家与认知破局者",
    "voice_tone": "真诚、犀利、有穿透力、多用短句、杜绝机械公文腔",
    "audience": "22-38岁注重个人成长、追求效率与实战价值的进取型人群",
    "platform": "小红书图文 + 微信公众号深度长文",
    "boundaries": "绝不用'在这个快节奏时代/总而言之'等虚词，不夸大宣传，不空喊口号",
    "memory": "开篇前3句必须制造认知反差；关键交付步骤必须加粗并附清单"
}


def get_workspace_profile(workspace_id: Optional[str] = None) -> dict:
    """获取指定或当前工作区的 6 维账号画像档案。"""
    if workspace_id:
        ws = db.get_workspace(workspace_id)
    else:
        ws = db.get_active_workspace()
    
    cfg = (ws.get("config") if ws else {}) or {}
    prof = dict(DEFAULT_PROFILE)
    prof.update(cfg.get("profile") or {})
    return prof


def update_workspace_profile(workspace_id: str, profile_data: dict) -> dict:
    """更新指定工作区的 6 维账号画像档案。"""
    ws = db.get_workspace(workspace_id)
    if not ws:
        raise ValueError(f"工作区不存在: {workspace_id}")
    
    cfg = ws.get("config") or {}
    cur_prof = dict(DEFAULT_PROFILE)
    cur_prof.update(cfg.get("profile") or {})
    cur_prof.update(profile_data)
    cfg["profile"] = cur_prof
    
    updated = db.update_workspace(workspace_id, name="", config=cfg)
    return cur_prof


def build_profile_system_prompt(workspace_id: Optional[str] = None) -> str:
    """构建注入到大模型创作上下文中的 6 维人格指纹指令。"""
    prof = get_workspace_profile(workspace_id)
    vp = get_workspace_voiceprint(workspace_id)
    return (
        "\n\n【核心创作指令：创作者 6 维数字人格档案与专属声纹记忆约束 (Profile & Voiceprint)】\n"
        f"1. 账号定位 (Positioning): {prof.get('positioning')}\n"
        f"2. 语言声纹 (Voice Tone): {prof.get('voice_tone')}\n"
        f"3. 目标受众 (Target Audience): {prof.get('audience')}\n"
        f"4. 主攻平台 (Platform Affinity): {prof.get('platform')}\n"
        f"5. 表达禁忌 (Expression Boundaries): {prof.get('boundaries')}\n"
        f"6. 爆款长期记忆 (Viral Long-Term Memory): {prof.get('memory')}\n"
        f"7. 声纹特征 (Voiceprint Persona): {vp.get('tone')}（音色：{vp.get('voice_name')}）\n"
        "请在通篇写作中严格贯彻上述人设口吻与表达边界，保持第一人称的真实感与鲜活性，绝不出现泛化公文味！\n"
    )


# ---------------- 账号专属声纹记忆档案 (Voiceprint & Acoustic Memory) ----------------

DEFAULT_VOICEPRINT = {
    "voice_name": "空间专属自然声线",
    "speed": 1.0,
    "pitch": 0,
    "tone": "自然亲和、节奏明快、富有感染力与穿透力",
    "ref_audio": "",
    "voice_model": "cosyvoice-v2",
    "memory_notes": "吐字清晰有力，长句在逻辑重音处自然停顿"
}


def get_workspace_voiceprint(workspace_id: Optional[str] = None) -> dict:
    """获取指定或当前工作区的声纹记忆档案。"""
    if workspace_id:
        ws = db.get_workspace(workspace_id)
    else:
        ws = db.get_active_workspace()
    cfg = (ws.get("config") if ws else {}) or {}
    vp = dict(DEFAULT_VOICEPRINT)
    vp.update(cfg.get("voiceprint") or {})
    return vp


def update_workspace_voiceprint(workspace_id: str, voiceprint_data: dict) -> dict:
    """更新指定工作区的声纹记忆档案。"""
    ws = db.get_workspace(workspace_id)
    if not ws:
        raise ValueError(f"工作区不存在: {workspace_id}")
    cfg = ws.get("config") or {}
    cur_vp = dict(DEFAULT_VOICEPRINT)
    cur_vp.update(cfg.get("voiceprint") or {})
    cur_vp.update(voiceprint_data)
    cfg["voiceprint"] = cur_vp
    db.update_workspace(workspace_id, name="", config=cfg)
    return cur_vp

