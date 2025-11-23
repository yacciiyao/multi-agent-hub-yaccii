# -*- coding: utf-8 -*-
# @File: brand_agent_handler.py
# @Description: 品牌 Agent 业务编排：榜单 / 品牌分析 / 品牌 QA

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from core.agents.brand_analysis import build_brand_analysis_payload
from core.agents.brand_repository import BrandRepository
from core.rag_service import RagService
from domain.agent import AgentConfig
from domain.message import Message, RagSource
from domain.session import Session
from infrastructure.mlogger import mlogger


class BrandHandler:
    """
    品牌 Agent 的统一入口：
      - 解析用户意图（榜单 / 深度分析 / QA）
      - 调用 BrandRepository 做真实数据计算
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
        self._repo = BrandRepository(storage)

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
            return "请描述你想看的品牌榜单或品牌分析，例如：最近一个季度耳机类出海品牌的综合榜单。", rag_sources or []

        rag_sources = rag_sources or []

        # 1. 解析意图
        intent = await self._parse_intent(user_text)

        # 解析失败或类型不对：直接退回普通对话
        if not isinstance(intent, dict):
            mlogger.error(
                self.__class__.__name__,
                "run",
                msg=f"intent is not dict, got={type(intent).__name__}, value={repr(intent)[:200]}",
            )
            reply = await self._bot.chat(context, stream=False)
            reply_text = str(reply or "").strip()
            return reply_text, rag_sources

        scenario = (intent.get("scenario") or "brand_qa").strip()
        reply_mode = (intent.get("reply_mode") or "").strip().lower()
        if reply_mode not in ("qa", "report"):
            # 如果没明显区分，榜单/分析默认走 report，其它默认 qa
            if scenario in (
                "category_ranking",
                "period_ranking",
                "multi_brand_analysis",
                "single_brand_analysis",
            ):
                reply_mode = "report"
            else:
                reply_mode = "qa"

        # 2. 按场景路由
        try:
            if scenario == "category_ranking":
                if reply_mode == "report":
                    return await self._handle_category_ranking_report(user_text, intent, rag_sources)
                else:
                    return await self._handle_category_ranking_qa(user_text, intent, rag_sources)

            if scenario == "period_ranking":
                if reply_mode == "report":
                    return await self._handle_period_ranking_report(user_text, intent, rag_sources)
                else:
                    return await self._handle_period_ranking_qa(user_text, intent, rag_sources)

            if scenario == "multi_brand_analysis":
                if reply_mode == "report":
                    return await self._handle_multi_brand_analysis_report(user_text, intent, rag_sources)
                else:
                    return await self._handle_multi_brand_analysis_qa(user_text, intent, rag_sources)

            if scenario == "single_brand_analysis":
                if reply_mode == "report":
                    return await self._handle_single_brand_analysis_report(user_text, intent, rag_sources)
                else:
                    return await self._handle_single_brand_analysis_qa(user_text, intent, rag_sources)

            # 统一落在 brand_qa
            return await self._handle_brand_qa(user_text, intent, rag_sources)

        except Exception as e:  # 防御，避免业务异常拖垮对话
            mlogger.error(self.__class__.__name__, "run", msg=str(e))
            reply = await self._bot.chat(context, stream=False)
            reply_text = str(reply or "").strip()
            return reply_text, rag_sources

    # ========== 意图解析 ==========

    async def _parse_intent(self, user_query: str) -> Optional[Dict[str, Any]]:
        """
        使用 LLM 解析品牌助手意图，只返回 JSON，不要任何多余文字。
        目标 JSON 结构大致如下（字段允许为 null）：

        {
          "scenario": "category_ranking" | "period_ranking" |
                      "multi_brand_analysis" | "single_brand_analysis" |
                      "brand_qa",
          "reply_mode": "qa" | "report",

          "category": {
            "name": "耳机",
            "id": null
          },

          "period": {
            "type": "last_n_days" | "quarter" | "half_year",
            "days": 90,
            "year": 2024,
            "quarter": 2,
            "half": 1
          },

          "metric": "composite" | "amazon_search" | "google_search" | "independence_traffic",
          "region": "Global" | "US" | "JP" | null,
          "top_n": 50,

          "brands": ["Anker", "Baseus"],

          "qa": {
            "focus": "single_brand" | "multi_brand" | "category_overview",
            "question_type": "metric_trend" | "ranking_position" | "profile" | "compare_simple" | "other"
          }
        }
        """
        sys_prompt = (
            "你是一个“品牌助手意图解析器”，负责把用户的自然语言问题解析成 JSON。\n"
            "必须遵守：只输出一个 JSON 对象，不要出现任何解释或多余文字。\n\n"
            "解析思路：\n"
            "1）先判断用户想要的是哪一类任务（scenario）：\n"
            "   - category_ranking: 想看“某个品类/类目”的品牌榜单，如“耳机类品牌榜单”。\n"
            "   - period_ranking: 想看“某个季度/半年”等时间段的综合榜单，如“2024年Q2出海品牌榜”。\n"
            "   - multi_brand_analysis: 想对多个品牌做对比分析，如“A 和 B 对比分析”。\n"
            "   - single_brand_analysis: 想对单个品牌做深度分析，如“分析一下 Anker 品牌”。\n"
            "   - brand_qa: 只是问一个关于品牌/类目/指标的具体问题，如“Anker最近独立站流量怎么样？”。\n\n"
            "2）判断 reply_mode：\n"
            "   - 如果用户明显说“写一篇/做一份/生成一个报告/深度分析/榜单报告”等，reply_mode 用 \"report\"；\n"
            "   - 如果用户只是简单问问题、说明“简单说说/大概讲讲”，reply_mode 用 \"qa\"。\n\n"
            "3）时间 period：\n"
            "   - 最近N天：type=\"last_n_days\"，days=7/30/90 等；\n"
            "   - 某年某季度：如“2024年二季度” → type=\"quarter\", year=2024, quarter=2；\n"
            "   - 半年：如“2024上半年/下半年” → type=\"half_year\", year=2024, half=1或2；\n"
            "   - 如果用户没说，榜单/分析默认最近90天（type=\"last_n_days\", days=90）。\n\n"
            "4）metric 指标：\n"
            "   - composite: 综合三方数据的综合势能；\n"
            "   - amazon_search: 明确在问亚马逊搜索/热度；\n"
            "   - google_search: 明确在问 Google 趋势/搜索；\n"
            "   - independence_traffic: 明确在问独立站/官网流量；\n"
            "   - 用户没说就用 \"composite\"。\n\n"
            "5）qa 子结构：\n"
            "   - focus: 问题聚焦在哪一层：\n"
            "       - single_brand: 关注某一个品牌；\n"
            "       - multi_brand: 同时提到多个品牌对比；\n"
            "       - category_overview: 关注某个品类整体，如“耳机类最近怎么样”；\n"
            "   - question_type：\n"
            "       - metric_trend: 关注指标走势/是否上涨下滑；\n"
            "       - ranking_position: 关注在榜单中的大致排位；\n"
            "       - profile: 想了解品牌基本情况/档案；\n"
            "       - compare_simple: 多品牌简单优劣对比；\n"
            "       - other: 其它难以归类的问题。\n\n"
            "请根据上述规则，结合用户问题给出最合理的 JSON。"
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
        # 兼容 ```json 包裹
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 3:
                text = parts[1]
        text = text.strip()

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            mlogger.error(
                self.__class__.__name__,
                "_parse_intent_json",
                msg=f"parsed JSON is not dict, type={type(data).__name__}",
            )
            return None
        except Exception as e:
            mlogger.error(self.__class__.__name__, "_parse_intent_json", msg=str(e), raw=text[:200])
            return None

    # ========== 时间窗口转换 ==========

    def _convert_period(self, period: Optional[Dict[str, Any]]) -> Tuple[int, int, str]:
        """
        把 period 结构转换为 [start_ts, end_ts, label]。
        """
        now = int(time.time())
        if not isinstance(period, dict):
            # 默认最近 90 天
            return now - 90 * 86400, now, "最近90天"

        p_type = (period.get("type") or "").strip() or "last_n_days"

        if p_type == "last_n_days":
            days = int(period.get("days") or 90)
            if days <= 0 or days > 365 * 3:
                days = 90
            return now - days * 86400, now, f"最近{days}天"

        if p_type == "quarter":
            import datetime as dt

            year = int(period.get("year") or dt.date.today().year)
            quarter = int(period.get("quarter") or 1)
            if quarter not in (1, 2, 3, 4):
                quarter = 1
            start_month = (quarter - 1) * 3 + 1
            start = dt.datetime(year, start_month, 1)
            if quarter == 4:
                end = dt.datetime(year + 1, 1, 1)
            else:
                end = dt.datetime(year, start_month + 3, 1)
            label = f"{year}年Q{quarter}"
            return int(start.timestamp()), int(end.timestamp()), label

        if p_type == "half_year":
            import datetime as dt

            year = int(period.get("year") or dt.date.today().year)
            half = int(period.get("half") or 1)
            if half not in (1, 2):
                half = 1
            if half == 1:
                start = dt.datetime(year, 1, 1)
                end = dt.datetime(year, 7, 1)
                label = f"{year}年上半年"
            else:
                start = dt.datetime(year, 7, 1)
                end = dt.datetime(year + 1, 1, 1)
                label = f"{year}年下半年"
            return int(start.timestamp()), int(end.timestamp()), label

        # 兜底：最近90天
        return now - 90 * 86400, now, "最近90天"

    # ========== 榜单类：报告模式 ==========

    async def _handle_category_ranking_report(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        category = intent.get("category") or {}
        if not isinstance(category, dict):
            category = {}
        category_name = (category.get("name") or "").strip() or None
        period = intent.get("period") or {}
        metric = (intent.get("metric") or "composite").strip()
        region = (intent.get("region") or None) or None
        top_n = int(intent.get("top_n") or 50)

        start_ts, end_ts, period_label = self._convert_period(period)

        # 1）计算真实榜单
        rows = await self._repo.calc_brand_ranking(
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            category_name=category_name,
            top_n=top_n,
        )
        if not rows:
            return "当前条件下没有查到有效的品牌榜单数据，你可以调整时间范围或类目再试试。", rag_sources

        payload = {
            "scenario": "category_ranking",
            "metric": metric,
            "period": {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "label": period_label,
            },
            "category_name": category_name,
            "region": region,
            "top_n": top_n,
            "ranking": rows,
        }

        # 2）可选品牌类 RAG：比如召回该类目相关的行业文章
        rag_text, merged_sources = await self._enrich_rag_for_brand(
            base_sources=rag_sources,
            query=f"品牌类目榜单分析：{category_name or ''} {period_label} {user_text}",
        )

        # 3）调用 LLM 写报告
        reply_text = await self._summarize_brand_ranking_report(
            user_text=user_text,
            payload=payload,
            rag_background=rag_text,
        )
        return reply_text, merged_sources

    async def _handle_period_ranking_report(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        category = intent.get("category") or {}
        if not isinstance(category, dict):
            category = {}
        category_name = (category.get("name") or "").strip() or None
        period = intent.get("period") or {}
        metric = (intent.get("metric") or "composite").strip()
        region = (intent.get("region") or None) or None
        top_n = int(intent.get("top_n") or 50)

        start_ts, end_ts, period_label = self._convert_period(period)

        rows = await self._repo.calc_brand_ranking(
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            category_name=category_name,
            top_n=top_n,
        )
        if not rows:
            return "在该时间段内没有查到有效的品牌榜单数据，你可以更换时间或类目再试试。", rag_sources

        payload = {
            "scenario": "period_ranking",
            "metric": metric,
            "period": {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "label": period_label,
            },
            "category_name": category_name,
            "region": region,
            "top_n": top_n,
            "ranking": rows,
        }

        rag_text, merged_sources = await self._enrich_rag_for_brand(
            base_sources=rag_sources,
            query=f"品牌周期榜单分析：{category_name or ''} {period_label} {user_text}",
        )

        reply_text = await self._summarize_brand_ranking_report(
            user_text=user_text,
            payload=payload,
            rag_background=rag_text,
        )
        return reply_text, merged_sources

    async def _summarize_brand_ranking_report(
        self,
        *,
        user_text: str,
        payload: Dict[str, Any],
        rag_background: str,
    ) -> str:
        metric = payload.get("metric")
        metric_desc = {
            "amazon_search": "亚马逊搜索热度",
            "google_search": "Google 搜索热度",
            "independence_traffic": "独立站访问流量",
            "composite": "综合搜索与独立站流量的品牌势能指数",
        }.get(metric, "品牌势能指标")

        sys_prompt = (
            "你是一名跨境电商品牌数据分析师，需要基于给定的真实品牌榜单数据，"
            "撰写一篇结构化的中文分析文章，类似行业研究报告。\n"
            "请严格围绕数据本身进行分析，不要捏造任何具体 GMV/销量等业务指标。\n\n"
            "文章结构建议：\n"
            "1）导语：用 1~2 句话概括本期榜单的主题和最核心结论。\n"
            "2）统计口径说明：包括时间范围、指标含义、类目/区域范围等。\n"
            "3）榜单总览：\n"
            "   - 用表格列出 TOP 品牌（至少包含：排名、品牌名、综合得分及各子指标）；\n"
            "   - 简要说明头部集中度，比如头部品牌是否高度集中、新锐品牌是否上升明显。\n"
            "4）重点品牌解读：\n"
            "   - 选取头部和有代表性的几家品牌，从指标表现、变化趋势和渠道结构等角度进行分析；\n"
            "5）新锐与机会：\n"
            "   - 指出榜单中增势明显的新锐品牌，推断其可能的打法或机会点（明确说明是基于指标的推断）。\n"
            "6）结论与建议：\n"
            "   - 针对品牌方/从业者给出 3~5 个可执行建议。\n\n"
            "注意：\n"
            f"- 本次分析的核心指标是：{metric_desc}；\n"
            "- 如引用到任何文本背景（RAG），请以“结合部分公开资料/报道”等方式表述，避免混淆来源；\n"
            "- 全文使用中文。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是本次品牌榜单的结构化数据（JSON）：\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ]

        if rag_background:
            messages.append(
                {
                    "role": "system",
                    "content": "下面是与本次品牌榜单相关的一些文本背景资料（来自知识库与网络公开信息）：\n"
                    + rag_background,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": "请基于以上数据和背景，撰写完整的榜单分析文章。用户原始问题是：\n" + user_text,
            }
        )

        raw = await self._bot.chat(messages, stream=False)
        return str(raw or "").strip()

    # ========== 榜单类：QA 模式（轻量回答） ==========

    async def _handle_category_ranking_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        """
        对于“类目榜单”但只需要简短说明的场景，仍然基于真实榜单数据，生成偏对话式的短回答。
        """
        category = intent.get("category") or {}
        if not isinstance(category, dict):
            category = {}
        category_name = (category.get("name") or "").strip() or None
        period = intent.get("period") or {}
        metric = (intent.get("metric") or "composite").strip()
        region = (intent.get("region") or None) or None
        top_n = int(intent.get("top_n") or 30)

        start_ts, end_ts, period_label = self._convert_period(period)

        rows = await self._repo.calc_brand_ranking(
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            category_name=category_name,
            top_n=top_n,
        )
        if not rows:
            return "当前条件下没有查到有效的品牌榜单数据。", rag_sources

        payload = {
            "metric": metric,
            "period": {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "label": period_label,
            },
            "category_name": category_name,
            "region": region,
            "top_n": top_n,
            "ranking": rows,
        }

        sys_prompt = (
            "你是一名品牌数据分析师，现在需要基于给定的榜单数据，用简洁的对话方式回答用户的问题。\n"
            "要求：\n"
            "1）先用一两句话总结榜单的大致情况（比如：哪些品牌位居前列、头部集中度如何）；\n"
            "2）可以点名 2~3 个典型品牌，并简要说明它们在当前指标中的相对位置；\n"
            "3）整体回答控制在 3~6 段以内，不要写成长篇报告；\n"
            "4）不要捏造不存在的具体销量/GMV 数字。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是当前的品牌榜单数据（JSON）：\n"
                + json.dumps(payload, ensure_ascii=False),
            },
            {
                "role": "user",
                "content": "请基于上述数据，用简洁的方式回答用户问题。用户原始问题是：\n" + user_text,
            },
        ]

        raw = await self._bot.chat(messages, stream=False)
        reply_text = str(raw or "").strip()
        return reply_text, rag_sources

    async def _handle_period_ranking_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        # 和 category_ranking_qa 基本类似，这里不再重复业务逻辑，只是时间口径不同
        return await self._handle_category_ranking_qa(user_text, intent, rag_sources)

    # ========== 品牌分析：单 / 多品牌 ==========

    async def _handle_single_brand_analysis_report(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        brands = intent.get("brands") or []
        if not isinstance(brands, list):
            brands = []
        if not brands:
            return "请说明你要分析的品牌名称。", rag_sources

        period = intent.get("period") or {}
        metric = (intent.get("metric") or "composite").strip()
        region = (intent.get("region") or None) or None

        start_ts, end_ts, period_label = self._convert_period(period)

        payload = await build_brand_analysis_payload(
            repo=self._repo,
            brand_names=[str(brands[0])],
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            period_label=period_label,
            region=region,
        )

        rag_text, merged_sources = await self._enrich_rag_for_brand(
            base_sources=rag_sources,
            query=f"单品牌深度分析：{brands[0]} {period_label} {user_text}",
        )

        reply_text = await self._summarize_single_brand_analysis_report(
            user_text=user_text,
            payload=payload,
            rag_background=rag_text,
        )
        return reply_text, merged_sources

    async def _handle_multi_brand_analysis_report(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        brands = intent.get("brands") or []
        if not isinstance(brands, list):
            brands = []
        if not brands or len(brands) < 2:
            return "请至少提供两个品牌名称用于对比分析。", rag_sources

        period = intent.get("period") or {}
        metric = (intent.get("metric") or "composite").strip()
        region = (intent.get("region") or None) or None

        start_ts, end_ts, period_label = self._convert_period(period)

        brand_names = [str(b) for b in brands]

        payload = await build_brand_analysis_payload(
            repo=self._repo,
            brand_names=brand_names,
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            period_label=period_label,
            region=region,
        )

        rag_text, merged_sources = await self._enrich_rag_for_brand(
            base_sources=rag_sources,
            query=f"多品牌对比分析：{'、'.join(brand_names)} {period_label} {user_text}",
        )

        reply_text = await self._summarize_multi_brand_analysis_report(
            user_text=user_text,
            payload=payload,
            rag_background=rag_text,
        )
        return reply_text, merged_sources

    async def _handle_single_brand_analysis_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        """
        轻量版单品牌分析：基于同样的 payload，但回答更偏对话式、简短。
        """
        brands = intent.get("brands") or []
        if not isinstance(brands, list):
            brands = []
        if not brands:
            return "请说明你要了解的品牌名称。", rag_sources

        period = intent.get("period") or {}
        metric = (intent.get("metric") or "composite").strip()
        region = (intent.get("region") or None) or None

        start_ts, end_ts, period_label = self._convert_period(period)

        payload = await build_brand_analysis_payload(
            repo=self._repo,
            brand_names=[str(brands[0])],
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            period_label=period_label,
            region=region,
        )

        sys_prompt = (
            "你是一名品牌数据分析师，现在需要基于给定的单品牌分析数据，"
            "用简洁的对话方式回答用户的问题，而不是写完整报告。\n"
            "可以从：品牌基本盘、核心指标表现、近期趋势、显著优势/风险等角度，用 3~6 段话进行回答。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是该品牌的分析数据（JSON）：\n"
                + json.dumps(payload, ensure_ascii=False),
            },
            {
                "role": "user",
                "content": "请基于这些数据，简要回答用户问题。用户原始问题是：\n" + user_text,
            },
        ]

        raw = await self._bot.chat(messages, stream=False)
        reply_text = str(raw or "").strip()
        return reply_text, rag_sources

    async def _handle_multi_brand_analysis_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        brands = intent.get("brands") or []
        if not isinstance(brands, list):
            brands = []
        if not brands or len(brands) < 2:
            return "请至少提供两个品牌名称用于对比说明。", rag_sources

        period = intent.get("period") or {}
        metric = (intent.get("metric") or "composite").strip()
        region = (intent.get("region") or None) or None

        start_ts, end_ts, period_label = self._convert_period(period)

        brand_names = [str(b) for b in brands]

        payload = await build_brand_analysis_payload(
            repo=self._repo,
            brand_names=brand_names,
            metric=metric,
            start_ts=start_ts,
            end_ts=end_ts,
            period_label=period_label,
            region=region,
        )

        sys_prompt = (
            "你是一名品牌数据分析师，现在需要基于多个品牌的对比数据，"
            "用简洁的对话方式，回答用户关于这些品牌差异的问题。\n"
            "请重点说明：\n"
            "1）哪些品牌整体势能更强；\n"
            "2）在搜索热度和独立站流量上的明显差异；\n"
            "3）每个品牌最突出的优势或潜在短板。\n"
            "整体回答控制在 4~8 段。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是这些品牌的对比数据（JSON）：\n"
                + json.dumps(payload, ensure_ascii=False),
            },
            {
                "role": "user",
                "content": "请基于这些数据，回答用户的问题。用户原始问题是：\n" + user_text,
            },
        ]

        raw = await self._bot.chat(messages, stream=False)
        reply_text = str(raw or "").strip()
        return reply_text, rag_sources

    async def _summarize_single_brand_analysis_report(
        self,
        *,
        user_text: str,
        payload: Dict[str, Any],
        rag_background: str,
    ) -> str:
        sys_prompt = (
            "你是一名跨境电商品牌分析师，需要基于给定的单品牌数据，"
            "撰写一篇结构化的“品牌深度分析”文章。\n"
            "建议结构：\n"
            "1）品牌概况：品类、地区、成立时间（如有）、官网/独立站情况等；\n"
            "2）核心指标表现：亚马逊搜索、Google 搜索、独立站流量的水平与趋势；\n"
            "3）流量与区域结构：主要流量来源、重点国家/地区（如有数据可推断）；\n"
            "4）同类相对位置：在同品类/同赛道中的大致位次和相对优势/短板（基于指标推断）；\n"
            "5）风险与不确定性：如增速放缓、渠道单一、区域过于集中等；\n"
            "6）机会点与策略建议：给出 3~5 条可执行建议。\n"
            "不要捏造不存在的具体销售额或利润数据。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是该品牌的分析数据（JSON）：\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ]
        if rag_background:
            messages.append(
                {
                    "role": "system",
                    "content": "下面是与该品牌相关的一些文本背景资料（来自知识库与公开报道）：\n"
                    + rag_background,
                }
            )
        messages.append(
            {
                "role": "user",
                "content": "请基于以上信息撰写完整的品牌深度分析文章。用户原始问题是：\n" + user_text,
            }
        )

        raw = await self._bot.chat(messages, stream=False)
        return str(raw or "").strip()

    async def _summarize_multi_brand_analysis_report(
        self,
        *,
        user_text: str,
        payload: Dict[str, Any],
        rag_background: str,
    ) -> str:
        sys_prompt = (
            "你是一名跨境电商品牌分析师，需要基于多个品牌的对比数据，"
            "撰写一篇“多品牌对比分析”文章。\n"
            "建议结构：\n"
            "1）样本说明：对比的品牌列表、品类/地区范围、时间窗口、核心指标；\n"
            "2）整体对比概览：用表格或小结说明各品牌在核心指标上的强弱；\n"
            "3）逐个品牌小结：每个品牌 1~2 段，总结其定位、优势、短板；\n"
            "4）差异化与分层：哪些是头部标杆，哪些是追赶者或细分赛道选手；\n"
            "5）策略与建议：针对不同类型品牌给出可执行建议。\n"
            "避免捏造不存在的具体销售额或利润。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是这些品牌的对比数据（JSON）：\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ]
        if rag_background:
            messages.append(
                {
                    "role": "system",
                    "content": "下面是与这些品牌/品类相关的一些文本背景资料（来自知识库与公开报道）：\n"
                    + rag_background,
                }
            )
        messages.append(
            {
                "role": "user",
                "content": "请基于以上信息撰写完整的多品牌对比分析文章。用户原始问题是：\n" + user_text,
            }
        )

        raw = await self._bot.chat(messages, stream=False)
        return str(raw or "").strip()

    # ========== 品牌 QA 场景 ==========

    async def _handle_brand_qa(
        self,
        user_text: str,
        intent: Dict[str, Any],
        rag_sources: List[RagSource],
    ) -> Tuple[str, List[RagSource]]:
        """
        品牌 QA：优先基于结构化数据回答，如果数据不足再结合 RAG。
        这里为了简化实现，直接复用 build_brand_analysis_payload，
        再让模型针对用户问题做“按需引用”的解释。
        """
        qa = intent.get("qa") or {}
        if not isinstance(qa, dict):
            qa = {}
        focus = (qa.get("focus") or "").strip() or "single_brand"
        _ = focus  # 当前实现暂未细分使用 focus，可按需扩展

        brands = intent.get("brands") or []
        if not isinstance(brands, list):
            brands = []
        period = intent.get("period") or {}
        metric = (intent.get("metric") or "composite").strip()
        region = (intent.get("region") or None) or None

        start_ts, end_ts, period_label = self._convert_period(period)

        # 当前实现：如果有品牌，就构造单/多品牌 payload；如果没有品牌，就看有没有类目
        payload: Dict[str, Any] = {}
        if brands:
            brand_names = [str(b) for b in brands]
            payload = await build_brand_analysis_payload(
                repo=self._repo,
                brand_names=brand_names,
                metric=metric,
                start_ts=start_ts,
                end_ts=end_ts,
                period_label=period_label,
                region=region,
            )
        else:
            category = intent.get("category") or {}
            if not isinstance(category, dict):
                category = {}
            category_name = (category.get("name") or "").strip() or None
            rows = await self._repo.calc_brand_ranking(
                metric=metric,
                start_ts=start_ts,
                end_ts=end_ts,
                category_name=category_name,
                top_n=int(intent.get("top_n") or 30),
            )
            payload = {
                "metric": metric,
                "period": {
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "label": period_label,
                },
                "category_name": category_name,
                "region": region,
                "ranking": rows,
            }

        rag_text_extra, merged_sources = await self._enrich_rag_for_brand(
            base_sources=rag_sources,
            query=f"品牌问答：{user_text}",
        )

        sys_prompt = (
            "你是一个品牌数据问答助手，现在需要结合结构化数据和部分文本背景，"
            "用简洁的中文回答用户的问题。\n"
            "优先依据结构化数据做判断；当需要解释品牌定位、渠道或市场情况时，可以参考文本背景，"
            "但要以“结合部分公开资料可推测”等方式表述，避免混淆真实数据与推测。\n"
            "回答风格偏对话化、简洁清晰，一般控制在 3~8 段以内。"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "system",
                "content": "下面是本次可用的结构化数据（JSON）：\n"
                + json.dumps(payload, ensure_ascii=False),
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
                "content": "请结合以上信息，直接回答下面这个问题，不要再重复数据本身：\n" + user_text,
            }
        )

        raw = await self._bot.chat(messages, stream=False)
        reply_text = str(raw or "").strip()
        return reply_text, merged_sources

    # ========== RAG 增强 ==========

    async def _enrich_rag_for_brand(
        self,
        *,
        base_sources: Optional[List[Any]],
        query: str,
    ) -> Tuple[str, List[RagSource]]:
        """
        在 MessageService 已经做过一次通用 RAG 的基础上，
        品牌 Agent 可以根据更具体的 query 再做一轮补充。
        这里对 base_sources / hits 的类型做了兼容，避免 .get/.snippet 在 str 上报错。
        """
        merged_sources: List[RagSource] = list(base_sources or [])

        # 先把已有 sources 转成简单文本摘要（兜底用）
        def sources_to_text(sources: List[Any]) -> str:
            snippets: List[str] = []
            for i, s in enumerate(sources, start=1):
                snippet = ""
                if hasattr(s, "snippet"):
                    snippet = getattr(s, "snippet", "") or ""
                elif isinstance(s, dict):
                    snippet = s.get("snippet") or s.get("content") or ""
                elif isinstance(s, str):
                    snippet = s
                snippet = (snippet or "").replace("\n", " ").strip()
                if snippet:
                    snippets.append(f"{i}. {snippet}")
            return "\n".join(snippets)

        # 如果 Agent 未开启 RAG 或没有 rag_service，就直接把已有 sources 变成文本返回
        if not getattr(self._agent, "enable_rag", False) or not self._rag:
            return sources_to_text(merged_sources), merged_sources

        # 补充一轮更“品牌定向”的 RAG
        try:
            hits = await self._rag.semantic_search(
                query=query,
                top_k=getattr(self._agent, "rag_top_k", 5) or 5,
            )
        except Exception as e:
            mlogger.error(self.__class__.__name__, "brand_agent_rag", msg=str(e))
            return sources_to_text(merged_sources), merged_sources

        if not hits:
            return sources_to_text(merged_sources), merged_sources

        # 把 hits 转成 snippet 文本 + RagSource 结构
        snippets: List[str] = []
        for i, h in enumerate(hits, start=1):
            snip = ""
            if isinstance(h, dict):
                snip = (h.get("content") or h.get("snippet") or "") or ""
            elif hasattr(h, "get"):
                # 某些自定义对象可能实现了 get
                try:
                    snip = (h.get("content") or h.get("snippet") or "") or ""
                except Exception:
                    snip = str(h)
            else:
                snip = str(h)
            snip = snip.replace("\n", " ").strip()
            if snip:
                snippets.append(f"{i}. {snip}")

        from domain.message import RagSource as RagSourceModel  # 避免循环导入

        for h in hits:
            title = ""
            url = None
            snippet = ""
            score = None
            meta_raw: Dict[str, Any] = {}

            if isinstance(h, dict):
                title = h.get("title") or ""
                url = h.get("url")
                snippet = h.get("snippet") or h.get("content") or ""
                score = h.get("score")
                meta_raw = h.get("meta") or {}
            elif hasattr(h, "get"):
                # 宽松兼容
                try:
                    title = h.get("title") or ""
                    url = h.get("url")
                    snippet = h.get("snippet") or h.get("content") or ""
                    score = h.get("score")
                    meta_raw = h.get("meta") or {}
                except Exception:
                    snippet = str(h)
            else:
                snippet = str(h)

            meta_str = {str(k): ("" if v is None else str(v)) for k, v in (meta_raw or {}).items()}

            merged_sources.append(
                RagSourceModel(
                    title=title,
                    url=url,
                    snippet=snippet,
                    score=score,
                    meta=meta_str,
                )
            )

        return "\n".join(snippets), merged_sources
