# -*- coding: utf-8 -*-
# @File: session_service.py
# @Author: yaccii
# @Time: 2025-11-09 18:35
# @Description: Session domain service
import time
import uuid
from typing import List, Optional

from bots.bot_registry import BotRegistry
from domain.enums import Channel
from domain.session import Session
from infrastructure.config_manager import config


class SessionService:
    def __init__(self):
        self._storage = None
        self._config = config.as_dict()

    @property
    def storage(self):
        if not self._storage:
            from infrastructure.storage_manager import storage_manager
            self._storage = storage_manager.get()
        return self._storage

    async def create_session(self, user_id: int, bot_name: str, channel: Channel) -> str:
        self._ensure_bot_exists(bot_name)

        limit = int(self._config.get("max_sessions", 50))

        history = await self.storage.list_sessions(user_id=user_id)
        active_count = len(history)
        if active_count >= limit:
            raise ValueError(
                f"Session limit reached ({limit}). Please delete unused sessions before creating a new one.")

        now = int(time.time())
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=user_id,
            bot_name=bot_name,
            channel=channel,
            session_name=None,
            rag_enabled=False,
            stream_enabled=False,
            is_deleted=False,
            created_at=now,
            updated_at=now,
        )
        await self.storage.create_session(session)
        return session_id

    async def get_session(self, user_id: int, session_id: str) -> Optional[dict]:
        session = await self.storage.get_session(user_id=user_id, session_id=session_id)
        if not session:
            return None
        return session.to_dict()

    async def list_sessions(self, user_id: int) -> List[dict]:
        sessions = await self.storage.list_sessions(user_id=user_id)
        return [s.to_dict() for s in sessions]

    async def delete_session(self, user_id: int, session_id: str) -> None:
        await self.storage.delete_session(user_id=user_id, session_id=session_id)

    async def delete_all_sessions(self, user_id: int) -> None:
        await self.storage.delete_all_sessions(user_id=user_id)

    async def update_session_flag(self, user_id: int, session_id: str, rag_enabled: bool, stream_enabled: bool) -> None:
        await self.storage.update_session_flag(
            user_id=user_id,
            session_id=session_id,
            rag_enabled=rag_enabled,
            stream_enabled=stream_enabled,
        )

    @staticmethod
    def _ensure_bot_exists(bot_name: str) -> None:
        bots = BotRegistry.list_bots()
        if not any(m.get("bot_name") == bot_name for m in bots):
            raise ValueError("bot_name not found in bots registry")
