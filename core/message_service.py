# -*- coding: utf-8 -*-
# @File: message_service.py
# @Author: yaccii
# @Time: 2025-11-09 18:37
# @Description: Message domain service
import asyncio
import json
import time
from typing import List, Dict, Any, AsyncIterator, Union

from bots.bot_registry import BotRegistry
from core.rag_service import RagService
from domain.enums import Role
from domain.message import Message, RagSource
from infrastructure.config_manager import config


class MessageService:
    def __init__(self):
        self._storage = None
        self._config = config.as_dict()
        self._rag = RagService()

    @property
    def storage(self):
        if not self._storage:
            from infrastructure.storage_manager import storage_manager
            self._storage = storage_manager.get()
        return self._storage

    async def send_message(
            self, user_id: int, message: Message, stream: bool = False
    ) -> Union[Dict[str, Any], AsyncIterator[str]]:
        session_id = message.session_id
        session = await self.storage.get_session(user_id=user_id, session_id=session_id)
        if not session:
            raise ValueError("Session not found.")
        bot = BotRegistry.get(bot_name=session.bot_name)
        if not bot:
            raise ValueError("Bot not found.")

        history = await self.storage.get_messages(user_id=user_id, session_id=session_id)
        limit = int(self._config.get("max_messages_count", 200))
        if len(history) >= limit:
            raise RuntimeError("Message limit exceeded.")
        max_len = int(self._config.get("max_messages_length", 8000))
        if len(message.content or "") > max_len:
            message.content = (message.content or "")[:max_len]

        await self.storage.update_session_flag(
            user_id=user_id,
            session_id=session_id,
            rag_enabled=bool(message.rag_enabled),
            stream_enabled=bool(stream),
        )

        setattr(message, "stream_enabled", bool(stream))
        await self.storage.append_message(message=message)

        history = await self.storage.get_messages(user_id=user_id, session_id=session_id)

        context: List[Dict[str, str]] = []
        for h in history:
            if h.role in (Role.USER, Role.ASSISTANT):
                role_value = h.role.value if hasattr(h.role, "value") else str(h.role)
                context.append({"role": role_value, "content": str(h.content or "")})

        # RAG
        sources: List[RagSource] = []
        if message.rag_enabled:
            rag_reply = await self._rag.semantic_search(query=message.content or "")
            if rag_reply:
                lines: List[str] = []
                for i, r in enumerate(rag_reply, 1):
                    text = (r.get("content") or "").strip().replace("\n", " ")
                    lines.append(f"{i}] {text}")
                prompt_text = (
                        "You are given the following context snippets. Use them when helpful; "
                        "if irrelevant, ignore them.\n" + "\n".join(lines)
                )
                context = [{"role": "system", "content": prompt_text}] + context

                for r in rag_reply:
                    raw_meta = r.get("meta") or {}
                    meta_str = {str(k): ("" if v is None else str(v)) for k, v in raw_meta.items()}
                    sources.append(RagSource(
                        title=r.get("title") or "",
                        url=r.get("url"),
                        snippet=r.get("snippet"),
                        score=r.get("score"),
                        meta=meta_str,
                    ))

        # 流式
        if stream:
            async def generator() -> AsyncIterator[str]:
                buffer: List[str] = []
                streamer = await bot.chat(context, stream=True)

                async for chunk in streamer:
                    s = str(chunk or "")
                    if not s:
                        continue
                    buffer.append(s)
                    yield s

                full = "".join(buffer)

                if sources:
                    meta = {
                        "type": "rag_sources",
                        "sources": [
                            (s.model_dump() if hasattr(s, "model_dump") else dict(s))
                            for s in sources
                        ],
                    }
                    yield "\n[[RAG_SOURCES]]" + json.dumps(meta, ensure_ascii=False) + "\n"

                await self.storage.append_message(Message(
                    session_id=session_id,
                    role=Role.ASSISTANT,
                    content=full,
                    rag_enabled=bool(message.rag_enabled),
                    sources=sources,
                    created_at=int(time.time()),
                    is_deleted=False,
                    stream_enabled=True,  # type: ignore
                ))

                if not session.session_name:
                    try:
                        s_title_ctx = [
                            {"role": "system", "content": "请为这段对话生成一个精炼中文标题，6~12个字，不要标点和引号。"},
                            {"role": "user", "content": (message.content or "")[:200]},
                        ]
                        s_title_raw = await asyncio.wait_for(bot.chat(s_title_ctx, stream=False), timeout=5)
                        s_title_raw = (s_title_raw or "").strip()
                        import re
                        s_titles = re.sub(r"[\"'‘’“”.,，。!！?？:：;；()\[\]{}<>《》【】·\-_/\\@#~`^&*+=|]", " ", s_title_raw)
                        s_title = re.sub(r"\s+", "", s_titles)[:50]
                        if s_title:
                            await self.storage.rename_session(user_id=user_id, session_id=session_id, new_name=s_title)
                    except Exception:
                        pass

            return generator()

        # 非流式
        reply = await bot.chat(context, stream=False)
        reply_text = str(reply or "").strip()

        await self.storage.append_message(Message(
            session_id=session_id,
            role=Role.ASSISTANT,
            content=reply_text,
            rag_enabled=bool(message.rag_enabled),
            sources=sources,
            created_at=int(time.time()),
            is_deleted=False,
            stream_enabled=False,  # type: ignore
        ))

        if not session.session_name:
            try:
                c_title_ctx = [
                    {"role": "system", "content": "请为这段对话生成一个精炼中文标题，6~12个字，不要标点和引号。"},
                    {"role": "user", "content": (message.content or "")[:200]},
                ]
                c_title_raw = await asyncio.wait_for(bot.chat(c_title_ctx, stream=False), timeout=5)
                c_title_raw = (c_title_raw or "").strip()
                import re
                c_titles = re.sub(r"[\"'‘’“”.,，。!！?？:：;；()\[\]{}<>《》【】·\-_/\\@#~`^&*+=|]", " ", c_title_raw)
                c_title = re.sub(r"\s+", "", c_titles)[:50]
                if c_title:
                    await self.storage.rename_session(user_id=user_id, session_id=session_id, new_name=c_title)
            except Exception:
                pass

        return {
            "reply": reply_text,
            "sources": [
                (s.model_dump() if hasattr(s, "model_dump") else dict(s))
                for s in sources
            ] if (message.rag_enabled and sources) else [],
        }

    async def get_messages(self, user_id: int, session_id: str) -> List[Dict[str, Any]]:
        data: List[Dict[str, Any]] = []
        history = await self.storage.get_messages(user_id=user_id, session_id=session_id)
        for h in history:
            data.append(h.to_dict())
        return data
