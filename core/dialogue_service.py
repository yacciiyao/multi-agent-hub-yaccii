# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 20:12
@Desc: 会话与消息管理服务（内存实现版）
"""
import time
from typing import Dict, List, Any

from core.message import Message
from core.session import Session
from infrastructure.logger import logger


class DialogueService:
    """ 管理多轮对话的上下文缓存 """

    def __init__(self):
        self.user_sessions: Dict[int, Dict[str, Session]] = {}

    def _ensure_user(self, user_id):
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {}

    def _require_session(self, user_id: int, session_id: str) -> Session:
        self._ensure_user(user_id)

        if session_id not in self.user_sessions[user_id]:
            raise KeyError(f"Session not found: user={user_id}, session={session_id}")

        return self.user_sessions[user_id][session_id]

    def new_session(self, user_id: int, model_name: str = "gpt-3.5-turbo", use_kg: bool = False) -> str:
        """ 创建新会话 """
        self._ensure_user(user_id)

        session = Session(model_name=model_name,use_kg=use_kg)
        self.user_sessions[user_id][session.session_id] = session

        logger.info(f"[Dialogue] New session user={user_id}, session={session.session_id}, model={model_name}, use_kg={use_kg}")

        return session.session_id

    def get_session(self, user_id: int, session_id: str) -> Session:
        return self._require_session(user_id, session_id)

    def list_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        self._ensure_user(user_id)
        sessions = [
            s for s in self.user_sessions[user_id].values()
            if s.messages  # 过滤空会话
        ]

        sessions.sort(key=lambda x: x.updated_at, reverse=True)

        return [s.light_view() for s in sessions]

    def rename_session(self, user_id: int, session_id: str, session_name: str) -> None:
        session = self._require_session(user_id, session_id)
        session.session_name = session_name
        session.updated_at = int(time.time())
        logger.info(f"[Dialogue] Renamed session {session_id} -> {session_name}")

    def clear_session(self, user_id: int, session_id: str) -> None:
        self._ensure_user(user_id)
        if session_id in self.user_sessions[user_id]:
            del self.user_sessions[user_id][session_id]
            logger.info(f"[Dialogue] Cleared session {session_id} for user {user_id}")

    def clear_all_sessions(self, user_id: int) -> None:
        self._ensure_user(user_id)
        self.user_sessions[user_id].clear()
        logger.info(f"[Dialogue] Cleared sessions for user {user_id}")

    def append_message(self, user_id: int, session_id: str, message: Message) -> None:
        self._ensure_user(user_id)
        session = self._require_session(user_id, session_id)
        session.append(message)

        logger.info(f"[Dialogue] +msg user={user_id} session={session_id} role={message.role}")

    def get_messages(self, user_id: int, session_id: str, *, as_chat_format: bool = True) -> List[Any]:
        session = self._require_session(user_id, session_id)

        if as_chat_format:  # 兼容 OpenAI 格式
            return [{"role": m.role, "content": m.content} for m in session.messages]

        return list(session.messages)


dialog_service = DialogueService()
