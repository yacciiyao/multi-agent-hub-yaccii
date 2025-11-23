# -*- coding: utf-8 -*-
# @File: agent_runtime.py
# @Author: yaccii
# @Time: 2025-11-20 14:34
# @Description: Agent 运行时调度，根据 Agent 配置路由到不同业务 Handler（品牌 / 众筹 / 默认对话）
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.agents.brand_handler import BrandHandler
from core.agents.project_handler import ProjectHandler
from core.rag_service import RagService
from domain.agent import AgentConfig
from domain.message import Message, RagSource
from domain.session import Session


class AgentRuntime:
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

    async def run(
            self,
            agent_key: str,
            session: Session,
            message: Message,
            bot: Any,
            context: List[Dict[str, str]],
            rag_sources: Optional[List[RagSource]] = None,
            stream: bool = False,
    ) -> Tuple[str, List[RagSource]]:
        """非流式 Agent 统一入口。"""
        if bot is not None and bot is not self._bot:
            self._bot = bot

        rag_sources = rag_sources or []

        if stream:
            reply_text, final_sources_any = await self._run_default_chat(
                session=session,
                message=message,
                context=context,
                rag_sources=rag_sources,
            )
            final_sources: List[RagSource] = list(final_sources_any or [])
            return reply_text, final_sources

        # 品牌助手：榜单 + 品牌分析 + QA
        if agent_key == "brand_agent":
            handler = BrandHandler(
                agent_config=self._agent,
                bot=self._bot,
                rag_service=self._rag,
                storage=self._storage,
            )
            reply_text, final_sources = await handler.run(
                session=session,
                message=message,
                context=context,
                rag_sources=rag_sources,
            )
            return reply_text, final_sources

        # 众筹项目助手：众筹榜单 + 单/多项目分析 + QA
        if agent_key == "project_agent":
            handler = ProjectHandler(
                agent_config=self._agent,
                bot=self._bot,
                rag_service=self._rag,
                storage=self._storage,
            )
            reply_text, final_sources = await handler.run(
                session=session,
                message=message,
                context=context,
                rag_sources=rag_sources,
            )
            return reply_text, final_sources

        reply_text, final_sources_any = await self._run_default_chat(
            session=session,
            message=message,
            context=context,
            rag_sources=rag_sources,
        )
        final_sources: List[RagSource] = list(final_sources_any or [])
        return reply_text, final_sources

    async def _run_default_chat(
            self,
            session: Session,
            message: Message,
            context: List[Dict[str, str]],
            rag_sources: List[Any],
    ) -> Tuple[str, List[Any]]:

        attachments = getattr(message, "attachments", None) or []

        allow_image = bool(getattr(self._bot, "allow_image", False))
        has_mm_chat = hasattr(self._bot, "chat_with_attachments")
        use_vision = bool(attachments) and allow_image and has_mm_chat

        if use_vision:
            reply = await self._bot.chat_with_attachments(
                messages=context,
                attachments=attachments,
                stream=False,
            )
        else:
            reply = await self._bot.chat(context, stream=False)

        reply_text = str(reply or "").strip()
        return reply_text, rag_sources
