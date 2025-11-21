# -*- coding: utf-8 -*-
# @File: agent_runtime.py
# @Author: yaccii
# @Time: 2025-11-20 14:34
# @Description: 公共版本：只实现默认对话逻辑。私有分支在这个基础上扩展真实 Agent。
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from domain.message import Message
from domain.session import Session


class AgentRuntime:
    def __init__(self, agent_config, bot: Any, rag_service: Any, storage: Any):
        self._agent = agent_config
        self._bot = bot
        self._rag = rag_service
        self._storage = storage

    async def run(
        self,
        *,
        agent_key: str,
        session: Session,
        message: Message,
        bot: Any,
        context: List[Dict[str, str]],
        rag_sources: Optional[List[Any]] = None,
        stream: bool = False,
    ) -> Tuple[str, List[Any]]:
        """公共版的 AgentRuntime：agent_key = default_chat"""
        rag_sources = rag_sources or []

        if stream:
            reply = await bot.chat(context, stream=False)
            return (str(reply or "").strip(), rag_sources)

        reply = await bot.chat(context, stream=False)
        return (str(reply or "").strip(), rag_sources)
