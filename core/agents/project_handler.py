# -*- coding: utf-8 -*-
# @File: project_agent_handler.py
# @Description: 众筹项目 Agent 业务编排：众筹榜单 / 单项目分析 / 多项目分析 / QA

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from core.agents.project_repository import ProjectRepository
from core.rag_service import RagService
from domain.agent import AgentConfig
from domain.message import Message, RagSource
from domain.session import Session
from infrastructure.mlogger import mlogger


class ProjectHandler:
    """
    众筹 Agent 统一入口：
      - 解析用户意图（榜单 / 单项目分析 / 多项目分析 / QA）
      - 调用 ProjectRepository 做真实数据计算
      - 结合 RAG 生成“文章级报告”或“对话式回答”
    """

    def __init__(
        self,
        agent_config: AgentConfig,
        bot: Any,
        rag_service: Optional[RagService],
        storage: Any,
    ) -> None:
        self._agent = agent_config
        self._bot = bot
        self._rag = rag_service
        self._storage = storage
        self._repo = ProjectRepository(storage)

    # ========== 对外主入口 ==========

    async def run(
        self,
        *,
        session: Session,
        message: Message,
        context: List[Dict[str, str]],
        rag_sources: Optional[List[RagSource]] = None,
    ) -> Tuple[str, List[RagSource]]:
        user_text = (message.content or "").strip()
        if not user_text:
            return "请描述你想看的众筹榜单或要分析的项目，例如：最近90天科技类众筹项目榜单。", rag_sources or []

        rag_sources = rag_sources or []

        intent = await self._parse_intent(user_text)
        if not intent:
            # 解析失败回退普通对话
            reply = await self._bot.chat(context, stream=False)
            reply_text = str(reply or "").strip()
            return reply_text, rag_sources

        scenario = (intent.get("scenario") or "project_qa").strip()
        reply_mode = (intent.get("reply_mode") or "").strip().lower()
        if reply_mode not in ("qa", "report"):
            if scenario in ("ranking", "single_project_analysis", "multi_project_analysis"):
                reply_mode = "report"
            else:
                reply_mode = "qa"

        try:
            if scenario == "ranking":
                if reply_mode == "report":
                    return await self._handle_ranking_report(user_text, intent, rag_sources)
                else:
                    return await self._handle_ranking_qa(user_text, intent, rag_sources)

            if scenario == "single_project_analysis":
                if reply_mode == "report":
                    return await self._handle_single_project_analysis_report(user_text, intent, rag_sources)
                else:
                    return await self._handle_single_project_analysis_qa(user_text, intent, rag_sources)

            if scenario == "multi_project_analysis":
                if reply_mode == "report":
                    return await self._handle_multi_project_analysis_report(user_text, intent, rag_sources)
                else:
                    return await self._handle_multi_project_analysis_qa(user_text, intent, rag_sources)

            # 统一落在 project_qa
            return await self._handle_project_qa(user_text, intent, rag_sources)
        except Exception as e:
            mlogger.error(self.__class__.__name__, "run", msg=str(e))
            reply = await self._bot.chat(context, stream=False)
            reply_text = str(reply or "").strip()
            return reply_text, rag_sources

    # ========== 意图解析 ==========

    async def _parse_intent(self, user_query: str) -> Optional[Dict[str, Any]]:
        """
        使用 LLM 解析众筹助手意图，只返回 JSON，不要任何多余文字。

        目标 JSON 结构示例：

        {
          "scenario": "ranking" | "multi_project_analysis" | "single_project_analysis" | "project_qa",
          "reply_mode": "qa" | "report",

          "ranking": {
            "metric": "funds_total" | "funds_speed",
            "days": 90,
            "category": "科技",
            "source": "kickstarter" | "indiegogo" | "makuake" | null,
            "country": "US" | "JP" | null,
            "top_n": 30
          },

          "analysis": {
            "projects": ["项目名或链接1", "项目名或链接2"],
            "category": "科技",
            "source": null,
            "days": 365
          },

          "qa": {
            "focus": "single_project" | "multi_project" | "category_overview",
            "question_type": "funding_status" | "time_left" | "performance_compare" | "risk_hint" | "other"
          }
        }
        """
        sys_prompt = (
            "你是一个“众筹助手意图解析器”，负责把用户的自然语言问题解析成 JSON。\n"
            "必须遵守：只输出一个 JSON 对象，不要出现任何解释或多余文字。\n\n"
            "解析思路：\n"
            "1）先判断用户想要的是哪一类任务（scenario）：\n"
            "   - ranking: 想看某时间范围内的众筹项目榜单，如“最近90天科技类众筹项目榜单”。\n"
            "   - single_project_analysis: 想看某一个具体众筹项目的深度分析，比如“帮我分析一下这个 Kickstarter 项目”。\n"
            "   - multi_project_analysis: 想对多个项目做对比分析，比如“对比下这几个耳机众筹项目”。\n"
            "   - project_qa: 只是问一个关于某个项目或某个类目众筹情况的具体问题，比如“这个项目现在筹了多少”。\n\n"
            "2）判断 reply_mode：\n"
            "   - 如果用户明显说“写一篇/出一份/做一个详细报告/深度分析”等，reply_mode 用 \"report\"；\n"
            "   - 如果用户只是随口问问题、希望简单说明，reply_mode 用 \"qa\"。\n\n"
            "3）ranking 字段：\n"
            "   - metric: 'funds_total' 按总筹款额排序，'funds_speed' 按筹款速度排序；用户没说明用 'funds_total'。\n"
            "   - days: 最近多少天内的项目，如 30/90/365；用户没说用 90。\n"
            "   - category: 类目关键词，如“科技”“家电”，不确定则为 null。\n"
            "   - source: 具体平台 'kickstarter' / 'indiegogo' / 'makuake'，没说则为 null（表示全部）。\n"
            "   - country: 国家代码，如 US/JP，没说则为 null。\n"
            "   - top_n: 榜单条数，默认 30，范围 1~100。\n\n"
            "4）analysis 字段：\n"
            "   - projects: 用户提到的项目名或项目链接列表；\n"
            "   - category/source/days 可酌情填入，没说则为 null / 合理默认。\n\n"
            "5）qa 字段：\n"
            "   - focus: 问题主要围绕哪一层：\n"
            "       - single_project: 单个项目；\n"
            "       - multi_project: 多个项目对比；\n"
            "       - category_overview: 某类目或平台整体表现；\n"
            "   - question_type：\n"
            "       - funding_status: 当前筹款情况（金额/完成度等）；\n"
            "       - time_left: 还剩多少时间；\n"
            "       - performance_compare: 项目间表现对比；\n"
            "       - risk_hint: 风险提示、项目稳不稳；\n"
            "       - other: 其它难以归类的问题。\n"
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_query},
        ]

        try:
            raw = await self._bot.chat(messages, stream=False)
        except Exception as e:
            mlogger.error(self.__class__.__name__, "_parse_intent_chat", msg=str(e))
            return None

        text = str(raw or "").strip()
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 3:
                text = parts[1]
        text = text.strip()

        lines = text.splitlines()
        if lines:
            first = lines[0].strip().lower()
            if first in ("json", "```json", "```json{", "```json:", "```json,"):
                text = "\n".join(lines[1:]).strip()

        if text.lower().startswith("json{"):
            text = text[4:].lstrip()

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception as e:
            mlogger.error(self.__class__.__name__, "_parse_intent_json", msg=str(e), raw=text[:200])
            return None

        return None

    # ========== 时间窗口转换（按天） ==========

    def _convert_days(self, days: Optional[int]) -> Tuple[int, int]:
        now = int(time.time())
        d = int(days or 90)
        if d <= 0 or d > 365 * 3:
            d = 90
        return now - d * 86400, now

    # ========== 榜单：报告模式 / QA 模式 ==========

    async def _handle_ranking_report(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        ranking = intent.get("ranking") or {}
        metric = (ranking.get("metric") or "funds_total").strip()
        days = int(ranking.get("days") or 90)
        category = (ranking.get("category") or "").strip() or None
        source = (ranking.get("source") or "").strip() or None
        country = (ranking.get("country") or "").strip() or None
        top_n = int(ranking.get("top_n") or 30)

        start_ts, end_ts = self._convert_days(days)

        rows = await self._repo.calc_project_ranking(
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            category=category,
            source=source,
            country=country,
            top_n=top_n,
        )
        if not rows:
            return "在当前条件下没有查询到合适的众筹项目记录，你可以尝试放宽时间范围或更换类目。", rag_sources

        payload = {
            "scenario": "ranking",
            "metric": metric,
            "days": days,
            "category": category,
            "source": source,
            "country": country,
            "top_n": top_n,
            "ranking": rows,
        }

        rag_text, merged_sources = await self._enrich_rag_for_project(
            base_sources=rag_sources,
            query=f"众筹项目榜单分析：{category or ''} {source or ''} 最近{days}天 {user_text}",
        )

        reply_text = await self._summarize_project_ranking_report(
            user_text=user_text,
            payload=payload,
            rag_background=rag_text,
        )
        return reply_text, merged_sources

    async def _handle_ranking_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        ranking = intent.get("ranking") or {}
        metric = (ranking.get("metric") or "funds_total").strip()
        days = int(ranking.get("days") or 90)
        category = (ranking.get("category") or "").strip() or None
        source = (ranking.get("source") or "").strip() or None
        country = (ranking.get("country") or "").strip() or None
        top_n = int(ranking.get("top_n") or 20)

        start_ts, end_ts = self._convert_days(days)

        rows = await self._repo.calc_project_ranking(
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            category=category,
            source=source,
            country=country,
            top_n=top_n,
        )
        if not rows:
            return "当前条件下没有查到合适的众筹项目榜单数据。", rag_sources

        payload = {
            "metric": metric,
            "days": days,
            "category": category,
            "source": source,
            "country": country,
            "top_n": top_n,
            "ranking": rows,
        }

        sys_prompt = (
            "你是一名众筹数据分析师，现在需要基于给定的众筹项目榜单数据，"
            "用简洁的对话方式回答用户问题，而不是写完整报告。\n"
            "请用 3~6 段话概括：\n"
            "1）榜单头部项目的大致情况；\n"
            "2）筹款金额或筹款速度表现突出的项目；\n"
            "3）从榜单中能看出的明显趋势（如品类/地区特征等）。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是众筹项目榜单的结构化数据（JSON）：\n" + json.dumps(payload, ensure_ascii=False),
            },
            {
                "role": "user",
                "content": "请基于这些数据，简要回答用户问题。用户原始问题是：\n" + user_text,
            },
        ]

        raw = await self._bot.chat(messages, stream=False)
        reply_text = str(raw or "").strip()
        return reply_text, rag_sources

    async def _summarize_project_ranking_report(
        self,
        *,
        user_text: str,
        payload: Dict[str, Any],
        rag_background: str,
    ) -> str:
        metric = payload.get("metric")
        metric_desc = {
            "funds_total": "总筹款金额",
            "funds_speed": "筹款速度（单位时间筹款额）",
        }.get(metric, "众筹筹款表现")

        sys_prompt = (
            "你是一名专注于 Kickstarter / Indiegogo / Makuake 等平台的众筹数据分析师，"
            "需要基于给定的结构化榜单数据，输出一篇专业的榜单解读文章。\n"
            "建议结构：\n"
            "1）导语：用 1~2 句话概括本期榜单的核心结论；\n"
            "2）统计口径说明：时间范围、平台范围、指标类型（例如总筹款额或筹款速度）、类目/国家等；\n"
            "3）榜单总览：\n"
            "   - 用表格列出 TOP 项目（至少包含：排名、项目名称、平台、筹款金额、支持人数、国家/地区等）；\n"
            "   - 给出头部集中度的定性描述；\n"
            "4）代表性项目解读：挑选几个头部或有特色的项目，分析其筹款表现、品类、价格带、目标人群等；\n"
            "5）品类 / 区域趋势：从数据中归纳主要品类、主要市场，以及可能的机会点和风险点；\n"
            "6）结论与建议：给潜在项目方或从业者 3~5 条可执行建议。\n"
            "不要捏造数据库中不存在的具体金额或人数，只能基于已给数据合理推断。"
            f"\n本次分析的核心指标是：{metric_desc}。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是众筹项目榜单数据（JSON）：\n" + json.dumps(payload, ensure_ascii=False),
            },
        ]
        if rag_background:
            messages.append(
                {
                    "role": "system",
                    "content": "下面是与众筹行业/项目相关的一些文本背景资料（来自知识库与公开报道）：\n"
                               + rag_background,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": "请基于以上信息撰写完整的众筹项目榜单分析文章。用户原始问题是：\n" + user_text,
            }
        )

        raw = await self._bot.chat(messages, stream=False)
        return str(raw or "").strip()

    # ========== 单项目 / 多项目分析：报告 + QA ==========

    async def _handle_single_project_analysis_report(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        analysis = intent.get("analysis") or {}
        projects = analysis.get("projects") or []
        if not projects:
            return "请提供你要分析的众筹项目名称或链接。", rag_sources

        query_str = str(projects[0])
        candidates = await self._repo.search_projects(keyword=query_str, limit=5)
        if not candidates:
            return "没有在众筹项目库中找到相关项目，请尝试提供更明确的项目名称或链接。", rag_sources

        target = candidates[0]
        ys_id = int(target.get("id"))
        source = target.get("source") or ""
        project_id = target.get("project_id")

        ctx = await self._repo.get_project_full_context(
            ys_id=ys_id,
            source=source,
            project_id=project_id,
        )

        payload = {
            "scenario": "single_project_analysis",
            "query": query_str,
            "target": target,
            "context": ctx,
        }

        rag_text, merged_sources = await self._enrich_rag_for_project(
            base_sources=rag_sources,
            query=f"众筹项目深度分析：{target.get('title') or ''} {user_text}",
        )

        reply_text = await self._summarize_single_project_analysis_report(
            user_text=user_text,
            payload=payload,
            rag_background=rag_text,
        )
        return reply_text, merged_sources

    async def _handle_single_project_analysis_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        analysis = intent.get("analysis") or {}
        projects = analysis.get("projects") or []
        if not projects:
            return "请提供你要了解的众筹项目名称或链接。", rag_sources

        query_str = str(projects[0])
        candidates = await self._repo.search_projects(keyword=query_str, limit=3)
        if not candidates:
            return "在众筹项目库中没有找到匹配的项目。", rag_sources

        target = candidates[0]
        ys_id = int(target.get("id"))
        source = target.get("source") or ""
        project_id = target.get("project_id")

        ctx = await self._repo.get_project_full_context(
            ys_id=ys_id,
            source=source,
            project_id=project_id,
        )

        payload = {
            "scenario": "single_project_analysis",
            "query": query_str,
            "target": target,
            "context": ctx,
        }

        sys_prompt = (
            "你是一名众筹项目分析师，现在需要基于给定的单项目数据，"
            "用简洁的对话方式回答用户的问题，而不是写完整报告。\n"
            "请从项目概况、筹款表现、风险点等角度，用 3~6 段话给出回答。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是该项目的结构化数据（JSON）：\n" + json.dumps(payload, ensure_ascii=False),
            },
            {
                "role": "user",
                "content": "请基于这些数据，回答用户的问题。用户原始问题是：\n" + user_text,
            },
        ]

        raw = await self._bot.chat(messages, stream=False)
        reply_text = str(raw or "").strip()
        return reply_text, rag_sources

    async def _handle_multi_project_analysis_report(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        analysis = intent.get("analysis") or {}
        projects = analysis.get("projects") or []
        if not projects or len(projects) < 2:
            return "请至少提供两个众筹项目名称或链接，用于对比分析。", rag_sources

        targets: List[Dict[str, Any]] = []
        contexts: List[Dict[str, Any]] = []

        for q in projects:
            q_str = str(q)
            cand = await self._repo.search_projects(keyword=q_str, limit=1)
            if not cand:
                continue
            t = cand[0]
            targets.append(t)
            ys_id = int(t.get("id"))
            source = t.get("source") or ""
            project_id = t.get("project_id")
            ctx = await self._repo.get_project_full_context(
                ys_id=ys_id,
                source=source,
                project_id=project_id,
            )
            contexts.append(ctx)

        if not targets:
            return "没有在众筹项目库中找到这些项目，请尝试提供更明确的项目名称或链接。", rag_sources

        payload = {
            "scenario": "multi_project_analysis",
            "queries": [str(p) for p in projects],
            "targets": targets,
            "contexts": contexts,
        }

        titles = [t.get("title") or "" for t in targets]
        rag_text, merged_sources = await self._enrich_rag_for_project(
            base_sources=rag_sources,
            query=f"众筹项目对比分析：{'、'.join(titles)} {user_text}",
        )

        reply_text = await self._summarize_multi_project_analysis_report(
            user_text=user_text,
            payload=payload,
            rag_background=rag_text,
        )
        return reply_text, merged_sources

    async def _handle_multi_project_analysis_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        analysis = intent.get("analysis") or {}
        projects = analysis.get("projects") or []
        if not projects or len(projects) < 2:
            return "请至少提供两个众筹项目名称或链接，用于对比说明。", rag_sources

        targets: List[Dict[str, Any]] = []
        for q in projects:
            q_str = str(q)
            cand = await self._repo.search_projects(keyword=q_str, limit=1)
            if cand:
                targets.append(cand[0])

        if not targets:
            return "在众筹项目库中没有找到这些项目。", rag_sources

        payload = {
            "scenario": "multi_project_analysis",
            "queries": [str(p) for p in projects],
            "targets": targets,
        }

        sys_prompt = (
            "你是一名众筹项目分析师，现在需要基于多个项目的基础信息，"
            "用简洁的方式回答用户提出的对比类问题。\n"
            "可以从筹款规模、支持人数、平台和品类等维度，概括这些项目的大致差异，控制在 4~8 段话。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是这些项目的基础信息（JSON）：\n" + json.dumps(payload, ensure_ascii=False),
            },
            {
                "role": "user",
                "content": "请基于这些信息，回答用户的问题。用户原始问题是：\n" + user_text,
            },
        ]

        raw = await self._bot.chat(messages, stream=False)
        reply_text = str(raw or "").strip()
        return reply_text, rag_sources

    async def _summarize_single_project_analysis_report(
        self,
        *,
        user_text: str,
        payload: Dict[str, Any],
        rag_background: str,
    ) -> str:
        sys_prompt = (
            "你是一名专注众筹平台（Kickstarter / Indiegogo / Makuake）的项目分析师，"
            "需要基于给定的结构化数据，输出一份详细的单项目分析报告。\n"
            "建议结构：\n"
            "1）项目概况：平台、类目、筹款目标与实际筹款、支持人数、上线/结束时间等；\n"
            "2）产品与卖点：根据标题和简介，概括产品定位、核心卖点和差异化；\n"
            "3）筹款表现与节奏：从筹款金额、完成率、筹款周期等角度分析项目表现；\n"
            "4）风险与不确定性：结合筹款进度、项目时长、支持者数量、平台属性等，指出潜在风险；\n"
            "5）市场前景与竞品环境：在合理范围内进行推断，并明确说明是推断；\n"
            "6）结论与建议：给出针对项目方或潜在支持者的建议。\n"
            "不要捏造数据库中不存在的具体数字，只能基于已知数据和合理假设进行分析。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是该项目的结构化上下文数据（JSON）：\n" + json.dumps(payload, ensure_ascii=False),
            },
        ]
        if rag_background:
            messages.append(
                {
                    "role": "system",
                    "content": "下面是与该项目/品类相关的一些文本背景资料（来自知识库与公开报道）：\n"
                               + rag_background,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": "请基于以上信息撰写完整的项目深度分析文章。用户原始问题是：\n" + user_text,
            }
        )

        raw = await self._bot.chat(messages, stream=False)
        return str(raw or "").strip()

    async def _summarize_multi_project_analysis_report(
        self,
        *,
        user_text: str,
        payload: Dict[str, Any],
        rag_background: str,
    ) -> str:
        sys_prompt = (
            "你是一名众筹项目分析师，需要基于多个项目的结构化数据，撰写一篇“多项目对比分析”文章。\n"
            "建议结构：\n"
            "1）样本说明：参与对比的项目列表、平台、品类、时间范围；\n"
            "2）整体对比概览：用表格或要点说明各项目在筹款额、支持人数、完成率等方面的差异；\n"
            "3）逐个项目小结：每个项目 1~2 段，总结其亮点、潜在问题和适配的人群/场景；\n"
            "4）共性与差异：归纳头部项目的共性打法，以及表现不佳项目的共性问题；\n"
            "5）结论与建议：给出面向项目方或选品方的建议。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是这些项目的结构化上下文数据（JSON）：\n" + json.dumps(payload, ensure_ascii=False),
            },
        ]
        if rag_background:
            messages.append(
                {
                    "role": "system",
                    "content": "下面是与这些项目/品类相关的一些文本背景资料（来自知识库与公开报道）：\n"
                               + rag_background,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": "请基于以上信息撰写完整的多项目对比分析文章。用户原始问题是：\n" + user_text,
            }
        )

        raw = await self._bot.chat(messages, stream=False)
        return str(raw or "").strip()

    # ========== QA 场景 ==========

    async def _handle_project_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        """
        众筹 QA：尽量用结构化数据回答，如果不够再结合 RAG。
        这里不细分 question_type 的逻辑，统一通过 LLM 解释。
        """
        qa = intent.get("qa") or {}
        focus = (qa.get("focus") or "").strip() or "single_project"

        payload: Dict[str, Any] = {"focus": focus}

        if focus == "single_project":
            # 尝试直接在 ys_project 中搜项目
            candidates = await self._repo.search_projects(keyword=user_text, limit=3)
            if candidates:
                target = candidates[0]
                ys_id = int(target.get("id"))
                source = target.get("source") or ""
                project_id = target.get("project_id")
                ctx = await self._repo.get_project_full_context(
                    ys_id=ys_id,
                    source=source,
                    project_id=project_id,
                )
                payload["target"] = target
                payload["context"] = ctx
        elif focus == "multi_project":
            # 简化处理：复用 analysis 流程
            analysis = intent.get("analysis") or {}
            projects = analysis.get("projects") or []
            targets = []
            for q in projects:
                cand = await self._repo.search_projects(keyword=str(q), limit=1)
                if cand:
                    targets.append(cand[0])
            payload["targets"] = targets
        else:  # category_overview
            ranking = intent.get("ranking") or {}
            metric = (ranking.get("metric") or "funds_total").strip()
            days = int(ranking.get("days") or 90)
            category = (ranking.get("category") or "").strip() or None
            source = (ranking.get("source") or "").strip() or None
            country = (ranking.get("country") or "").strip() or None
            start_ts, end_ts = self._convert_days(days)
            rows = await self._repo.calc_project_ranking(
                metric=metric,
                start_ts=start_ts,
                end_ts=end_ts,
                category=category,
                source=source,
                country=country,
                top_n=int(ranking.get("top_n") or 30),
            )
            payload["ranking"] = rows
            payload["metric"] = metric
            payload["days"] = days
            payload["category"] = category
            payload["source"] = source
            payload["country"] = country

        rag_text_extra, merged_sources = await self._enrich_rag_for_project(
            base_sources=rag_sources,
            query=f"众筹项目问答：{user_text}",
        )

        sys_prompt = (
            "你是一名众筹数据问答助手，现在需要结合结构化数据和部分文本背景，"
            "用简洁的中文回答用户的问题。\n"
            "优先依据结构化数据做判断，当需要解释项目背景或行业情况时，可以参考文本背景，"
            "但要注意区分“数据事实”和“推断结论”。\n"
            "回答风格偏对话化、清晰、有逻辑，一般控制在 3~8 段。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是本次可用的结构化数据（JSON）：\n" + json.dumps(payload, ensure_ascii=False),
            },
        ]
        if rag_text_extra:
            messages.append(
                {
                    "role": "system",
                    "content": "下面是与问题相关的一些文本背景资料（来自知识库与公开报道）：\n"
                               + rag_text_extra,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": "请结合以上信息，直接回答下面这个问题，不要重复粘贴原始数据：\n" + user_text,
            }
        )

        raw = await self._bot.chat(messages, stream=False)
        reply_text = str(raw or "").strip()
        return reply_text, merged_sources

    # ========== RAG 增强 ==========

    async def _enrich_rag_for_project(
        self,
        *,
        base_sources: List[RagSource],
        query: str,
    ) -> Tuple[str, List[RagSource]]:
        merged_sources: List[RagSource] = list(base_sources or [])
        if not getattr(self._agent, "enable_rag", False) or not self._rag:
            snippets: List[str] = []
            for i, s in enumerate(merged_sources, start=1):
                snippet = (s.snippet or "").replace("\n", " ")
                if snippet:
                    snippets.append(f"{i}. {snippet}")
            return "\n".join(snippets), merged_sources

        try:
            hits = await self._rag.semantic_search(
                query=query,
                top_k=getattr(self._agent, "rag_top_k", 5) or 5,
            )
        except Exception as e:
            mlogger.error(self.__class__.__name__, "project_agent_rag", msg=str(e))
            hits = []

        if not hits:
            snippets: List[str] = []
            for i, s in enumerate(merged_sources, start=1):
                snippet = (s.snippet or "").replace("\n", " ")
                if snippet:
                    snippets.append(f"{i}. {snippet}")
            return "\n".join(snippets), merged_sources

        snippets: List[str] = []
        for i, h in enumerate(hits, start=1):
            snip = (h.get("content") or "").replace("\n", " ")
            if snip:
                snippets.append(f"{i}. {snip}")

        from domain.message import RagSource as RagSourceModel  # 避免循环导入

        for h in hits:
            meta = h.get("meta") or {}
            meta_str = {str(k): ("" if v is None else str(v)) for k, v in meta.items()}
            merged_sources.append(
                RagSourceModel(
                    title=h.get("title") or "",
                    url=h.get("url"),
                    snippet=h.get("snippet") or h.get("content"),
                    score=h.get("score"),
                    meta=meta_str,
                )
            )

        return "\n".join(snippets), merged_sources
