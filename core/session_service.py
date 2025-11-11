# -*- coding: utf-8 -*-
# @File: session_service.py
# @Author: yaccii
# @Time: 2025-11-09 18:35
# @Description:
import time
import uuid
from typing import List

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
        limit = self._config.get("max_sessions", 50)
        activate_count = await self._statistic_sessions(user_id=user_id)
        if activate_count >= limit:
            raise ValueError(
                f"Session limit reached ({limit}). Please delete unused sessions before creating a new one.")

        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=user_id,
            bot_name=bot_name,
            channel=channel,
            session_name=None,
            is_deleted=False,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )

        await self.storage.create_session(session)
        return session_id

    async def rename_session(self, request):
        ...

    async def delete_session(self, user_id: int, session_id: str) -> None:
        await self.storage.delete_session(user_id=user_id, session_id=session_id)

    async def delete_all_sessions(self, user_id: int) -> None:
        await self.storage.delete_all_sessions(user_id=user_id)

    async def list_sessions(self, user_id: int) -> List[Session]:
        sessions = await self.storage.list_sessions(user_id=user_id)
        return [session.to_dict() for session in sessions]

    def _ensure_bot_exists(self, bot_name: str) -> None:
        bots = BotRegistry.list_bots()
        if not any(m["bot_name"] == bot_name for m in bots):
            raise ValueError("bot_name not found in bots registry")

    async def _statistic_sessions(self, user_id: int) -> int:
        sessions = await self.storage.list_sessions(user_id=user_id)
        return len(sessions)
