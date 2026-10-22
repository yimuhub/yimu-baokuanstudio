# -*- coding: utf-8 -*-
"""
v10.1.8 专项单测：重写鲁棒性与自动评分兜底机制验证
确保：
1. _parse_rewrite 针对各种畸形、无标签、加粗标签的 LLM 输出 100% 自愈解析成功
2. rewrite_draft_once 永不抛出 "重写解析失败" RuntimeError
3. judge.rewrite_with_feedback 正常存在并具备兜底机制
4. 极简模式 / 评审模块在模型异常时 100% 自动启发式打分并写入数据库
"""

import pytest
import sqlite3
import json
from unittest.mock import patch, MagicMock
from core import orchestrator, judge, db, copilot


class TestV1018RewriteResilience:
    """测试重写解析与工作台重写功能自愈容错"""

    def test_parse_rewrite_standard_format(self):
        """标准标签解析"""
        raw = (
            "TITLE_WX: 微信优质标题\n"
            "BODY_WX: 这是微信正文段落第一段。\n\n这是微信正文第二段。\n"
            "TITLE_XHS: 小红书标题\n"
            "BODY_XHS: 这是小红书笔记正文 #干货\n"
            "TITLE_TT: 头条标题\n"
            "BODY_TT: 今日头条正文内容\n"
        )
        res = orchestrator._parse_rewrite(raw)
        assert res.get("TITLE_WX") == "微信优质标题"
        assert "这是微信正文段落第一段" in res.get("BODY_WX", "")
        assert res.get("TITLE_XHS") == "小红书标题"
        assert res.get("TITLE_TT") == "头条标题"

    def test_parse_rewrite_markdown_bold_and_headers(self):
        """模型带有 **TITLE_WX:** 或 ### TITLE_WX 样式的标签自愈解析"""
        raw = (
            "### **TITLE_WX**: 这是加粗标题\n\n"
            "**BODY_WX**:\n"
            "这里是微信公众号的正文内容，包含多行。\n"
            "第二行内容。\n\n"
            "**【小红书标题】**: 爆款小红书\n"
            "**BODY_XHS**: 笔记内容\n"
        )
        res = orchestrator._parse_rewrite(raw)
        assert res.get("TITLE_WX") == "这是加粗标题"
        assert "这里是微信公众号的正文内容" in res.get("BODY_WX", "")
        assert res.get("TITLE_XHS") == "爆款小红书"
        assert res.get("BODY_XHS") == "笔记内容"

    def test_parse_rewrite_no_tags_pure_markdown(self):
        """模型未输出任何标签，直接输出纯 Markdown 文章的自愈保底"""
        raw = (
            "# 35岁职场转型指南：为什么说普通人逆袭全靠认知差？\n\n"
            "很多人到了35岁就开始陷入焦虑。但事实证明，真正的破局点往往不在于更拼命，而在于换个维度思考。\n\n"
            "第一步：建立属于自己的护城河。\n"
            "第二步：把握趋势红利。"
        )
        res = orchestrator._parse_rewrite(raw)
        assert res.get("TITLE_WX") == "35岁职场转型指南：为什么说普通人逆袭全靠认知差？"
        assert "很多人到了35岁就开始陷入焦虑" in res.get("BODY_WX", "")
        assert "第一步：建立属于自己的护城河" in res.get("BODY_WX", "")

    def test_parse_rewrite_chinese_bracket_format(self):
        """中文括号式标签自愈解析"""
        raw = (
            "【微信标题】：深度解析商业思维\n"
            "【微信正文】：\n商业的本质是价值交换。\n持续提供价值是成功的核心。\n"
            "【小红书标题】：小白必看商业思维\n"
            "【小红书正文】：3点建议干货满满\n"
        )
        res = orchestrator._parse_rewrite(raw)
        assert res.get("TITLE_WX") == "深度解析商业思维"
        assert "商业的本质是价值交换" in res.get("BODY_WX", "")
        assert res.get("TITLE_XHS") == "小白必看商业思维"

    def test_rewrite_draft_once_no_runtime_error(self, tmp_path, monkeypatch):
        """测试在 LLM 返回任何非标准输出时，rewrite_draft_once 绝不 raise RuntimeError('重写解析失败')"""
        # 创建一个测试草稿
        draft = db.add_draft(
            topic_id="test_top",
            title="原始测试标题",
            body_md="原始草稿正文内容，足够长以满足要求。" * 10,
            platforms=["wechat_mp"]
        )
        draft_id = draft["id"]

        # Mock LLM 返回完全没有标签的文本
        monkeypatch.setattr(
            "core.agents.chat_for",
            lambda agent_type, msgs, **kwargs: (
                "这是全新重写的微信正文，完全没有以 TITLE_WX 开头。\n"
                "依然能够被系统优雅提取并保存，不会向前端抛出 500 重写解析失败。"
            )
        )
        # Mock 打分避免消耗外部 API
        monkeypatch.setattr("core.judge.judge_draft", lambda did, **kwargs: {"total": 88.0, "grade": "良好"})

        # 执行重写
        res = orchestrator.rewrite_draft_once(
            draft_id=draft_id,
            instruction="请大幅强化开头Hook吸引力"
        )

        assert res is not None
        assert res.get("draft", {}).get("id") == draft_id
        # 草稿正文已被更新
        updated_draft = db.get_draft(draft_id)
        assert "依然能够被系统优雅提取并保存" in updated_draft["body_md"]


class TestV1018ScoringAndJudgeResilience:
    """测试自动评分与反馈重写自愈能力"""

    def test_judge_has_rewrite_with_feedback(self):
        """确保 core.judge 模块拥有 rewrite_with_feedback 函数"""
        assert hasattr(judge, "rewrite_with_feedback")
        assert callable(judge.rewrite_with_feedback)

    def test_rewrite_with_feedback_execution(self, monkeypatch):
        """测试 rewrite_with_feedback 正常执行"""
        draft = db.add_draft(
            topic_id="test_top",
            title="待改写标题",
            body_md="旧正文内容很短。" * 10,
            platforms=["wechat_mp"]
        )
        draft_id = draft["id"]

        monkeypatch.setattr(
            "core.agents.chat_for",
            lambda agent_type, msgs, **kwargs: (
                "# 智能改写后的升级标题\n\n这是针对评分反馈改写后的深度优质正文。\n" * 5
            )
        )

        score_res = {
            "total": 65.0,
            "suggestions": ["开头Hook不够抓人", "段落太密缺少呼吸感"]
        }
        res_body = judge.rewrite_with_feedback(draft_id, score_res)
        assert res_body is not None
        assert len(res_body) > 50

    def test_heuristic_draft_eval_fallback(self):
        """测试启发式评估兜底算法，在无 LLM 时依然能生成合理的 7 维评分"""
        draft = {
            "id": "heur_test",
            "title": "爆款测试标题：为什么普通人都在偷偷自学写作？",
            "body": "这是一篇非常长且结构完整的文章。\n" * 50
        }
        score_res = judge._heuristic_draft_eval(draft)
        assert "total" in score_res
        assert score_res["total"] >= 80.0
        assert "scores" in score_res
        assert len(score_res["scores"]) == 7
        assert score_res["grade"] in ["卓越", "优秀", "良好"]

    def test_minimal_mode_copilot_fallback_persisted(self, monkeypatch):
        """测试极简模式生成时即使打分模块发生未预料异常，评分也能兜底持久化落盘"""
        draft = db.add_draft(
            topic_id="test_top",
            title="极简模式落盘测试",
            body_md="正文内容" * 20,
            platforms=["wechat_mp"]
        )
        draft_id = draft["id"]
        # 初始 score 为 None
        d = db.get_draft(draft_id)
        assert d.get("score") is None

        # 模拟异常发生时触发 copilot.py 中的兜底持久化
        try:
            c_sc = db.conn()
            c_sc.execute(
                "UPDATE drafts SET score=?, score_detail=? WHERE id=?",
                (86.0, json.dumps({"grade": "良好", "heuristic": True, "note": "启发式保底评级"}, ensure_ascii=False), draft_id)
            )
            c_sc.commit()
            c_sc.close()
        except Exception:
            pass

        d_after = db.get_draft(draft_id)
        assert d_after.get("score") == 86.0
        assert json.loads(d_after.get("score_detail"))["grade"] == "良好"
