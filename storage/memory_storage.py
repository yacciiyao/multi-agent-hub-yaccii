# -*- coding: utf-8 -*-
# @File: memory_storage.py
# @Author: yaccii
# @Time: 2025-11-07 12:39
# @Description:
import asyncio
import time
from typing import List, Optional, Dict, Any

from domain.message import Message
from domain.rag import RagChunk, RagDocument
from domain.session import Session
from storage.base import IStorage


class MemoryStorage(IStorage):
    """
    简易内存实现：仅供开发/测试。
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._sessions: Dict[int, Dict[str, Session]] = {}
        self._messages: Dict[str, List[Message]] = {}

        self._docs: Dict[str, RagDocument] = {}
        self._docs_by_user: Dict[int, List[str]] = {}
        self._chunks_by_doc: Dict[str, List[RagChunk]] = {}

    # ------------- session -------------
    async def create_session(self, session: Session) -> None:
        async with self._lock:
            now = int(time.time())
            if not session.created_at:
                session.created_at = now
            if not session.updated_at:
                session.updated_at = now
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

    async def get_session(self, user_id: int, session_id: str) -> Optional[Session]:
        async with self._lock:
            sess = self._sessions.get(user_id, {}).get(session_id)
            if not sess or sess.is_deleted:
                return None
            return sess

    async def list_sessions(self, user_id: int) -> List[Session]:
        async with self._lock:
            items = list(self._sessions.get(user_id, {}).values())
            # 过滤逻辑删除
            items = [s for s in items if not s.is_deleted]
            # 按更新时间倒序
            items.sort(key=lambda s: (s.updated_at, s.created_at), reverse=True)
            return items

    async def delete_session(self, user_id: int, session_id: str) -> None:
        async with self._lock:
            sess = self._sessions.get(user_id, {}).get(session_id)
            if sess and not sess.is_deleted:
                sess.is_deleted = True
                sess.updated_at = int(time.time())

            msgs = self._messages.get(session_id, [])
            for m in msgs:
                m.is_deleted = True

    async def delete_all_sessions(self, user_id: int) -> None:
        async with self._lock:
            for sess in self._sessions.get(user_id, {}).values():
                sess.is_deleted = 1
                sess.updated_at = int(time.time())
                msgs = self._messages.get(sess.session_id, [])
                for m in msgs:
                    m.is_deleted = True

    # ------------- message -------------
    async def append_message(self, msg: Message) -> None:
        async with self._lock:
            if msg.created_at is None or msg.created_at == 0:
                msg.created_at = int(time.time())
            self._messages.setdefault(msg.session_id, [])
            self._messages[msg.session_id].append(msg)

            for user_id, sess_map in self._sessions.items():
                sess = sess_map.get(msg.session_id)
                if sess and not sess.is_deleted:
                    sess.updated_at = int(time.time())
                    break

    async def get_messages(self, user_id: int, session_id: str) -> List[Message]:
        async with self._lock:
            sess = self._sessions.get(user_id, {}).get(session_id)
            if not sess or sess.is_deleted:
                return []
            msgs = self._messages.get(session_id, [])
            return [m for m in msgs if not m.is_deleted]

    # ------------- rag -------------
    async def upsert_rag_document(self, doc: RagDocument, chunks: List[RagChunk]) -> None:
        self._docs[doc.doc_id] = doc
        self._docs_by_user.setdefault(doc.user_id, [])
        if doc.doc_id not in self._docs_by_user[doc.user_id]:
            self._docs_by_user[doc.user_id].append(doc.doc_id)

        # replace chunks
        self._chunks_by_doc[doc.doc_id] = []
        for c in chunks:
            self._chunks_by_doc[doc.doc_id].append(c)

    async def list_rag_documents(self, user_id: int) -> List[RagDocument]:
        pass

    async def delete_rag_document(self, user_id: int, doc_id: str) -> None:
        pass

    async def get_rag_chunks_with_embeddings(self, limit: int) -> List[Dict[str, Any]]:
        pass

    # ------------- default -------------
    async def close(self):
        return