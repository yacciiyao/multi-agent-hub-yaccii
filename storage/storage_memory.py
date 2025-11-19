# -*- coding: utf-8 -*-
# @File: storage_memory.py
# @Author: yaccii
# @Time: 2025-11-07 12:39
# @Description: 基于内存的数据存储实现，适用于本地开发与单元测试场景。不提供持久化能力，进程结束后数据即丢失。
import asyncio
import time
from typing import List, Optional, Dict, Any

from domain.message import Message
from domain.rag import RagChunk, RagDocument
from domain.session import Session
from storage.storage_base import IStorage


class MemoryStorage(IStorage):
    def __init__(self):
        self._lock = asyncio.Lock()

        # sessions: user_id -> {session_id: Session}
        self._sessions: Dict[int, Dict[str, Session]] = {}
        # messages: session_id -> [Message]
        self._messages: Dict[str, List[Message]] = {}

        # RAG documents
        # docs: doc_id -> RagDocument
        self._docs: Dict[str, RagDocument] = {}
        # docs_by_user: user_id -> [doc_id]
        self._docs_by_user: Dict[int, List[str]] = {}
        # chunks_by_doc: doc_id -> [RagChunk]
        self._chunks_by_doc: Dict[str, List[RagChunk]] = {}

    # ------------- session -------------

    async def create_session(self, session: Session) -> None:
        async with self._lock:
            now = int(time.time())
            session.created_at = session.created_at or now
            session.updated_at = session.updated_at or now
            self._sessions.setdefault(session.user_id, {})
            self._sessions[session.user_id][session.session_id] = session
            self._messages.setdefault(session.session_id, [])

    async def rename_session(self, user_id: int, session_id: str, new_name: str) -> None:
        async with self._lock:
            sess = self._sessions.get(user_id, {}).get(session_id)
            if not sess or sess.is_deleted:
                return
            sess.session_name = new_name
            sess.updated_at = int(time.time())

    async def update_session_flag(self, user_id: int, session_id: str,
                                  rag_enabled: bool, stream_enabled: bool) -> None:
        async with self._lock:
            sess = self._sessions.get(user_id, {}).get(session_id)
            if not sess or sess.is_deleted:
                return
            sess.rag_enabled = bool(rag_enabled)
            sess.stream_enabled = bool(stream_enabled)
            sess.updated_at = int(time.time())

    async def get_session(self, user_id: int, session_id: str) -> Optional[Session]:
        async with self._lock:
            sess = self._sessions.get(user_id, {}).get(session_id)
            if not sess or sess.is_deleted:
                return None
            return sess

    async def list_sessions(self, user_id: int) -> List[Session]:
        async with self._lock:
            items = list(self._sessions.get(user_id, {}).values())
            items = [s for s in items if not s.is_deleted]
            items.sort(key=lambda s: (s.updated_at or 0, s.created_at or 0), reverse=True)
            return items

    async def delete_session(self, user_id: int, session_id: str) -> None:
        async with self._lock:
            sess = self._sessions.get(user_id, {}).get(session_id)
            if sess and not sess.is_deleted:
                sess.is_deleted = 1
                sess.updated_at = int(time.time())
            for m in self._messages.get(session_id, []):
                m.is_deleted = True

    async def delete_all_sessions(self, user_id: int) -> None:
        async with self._lock:
            for sess in self._sessions.get(user_id, {}).values():
                if not sess.is_deleted:
                    sess.is_deleted = 1
                    sess.updated_at = int(time.time())
                for m in self._messages.get(sess.session_id, []):
                    m.is_deleted = True

    # ------------- message -------------

    async def append_message(self, msg: Message) -> None:
        async with self._lock:
            msg.created_at = msg.created_at or int(time.time())
            self._messages.setdefault(msg.session_id, [])
            self._messages[msg.session_id].append(msg)

            # touch session.updated_at
            for sess_map in self._sessions.values():
                sess = sess_map.get(msg.session_id)
                if sess and not sess.is_deleted:
                    sess.updated_at = int(time.time())
                    break

    async def get_messages(self, user_id: int, session_id: str) -> List[Message]:
        async with self._lock:
            sess = self._sessions.get(user_id, {}).get(session_id)
            if not sess or sess.is_deleted:
                return []
            msgs = [m for m in self._messages.get(session_id, []) if not m.is_deleted]
            msgs.sort(key=lambda m: m.created_at or 0)
            return msgs

    # ------------- default -------------

    async def close(self):
        return
