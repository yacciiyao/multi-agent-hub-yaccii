# -*- coding: utf-8 -*-
# @File: memory_storage.py
# @Author: yaccii
# @Time: 2025-11-07 12:39
# @Description: 基于内存的数据存储实现，适用于本地开发与单元测试场景。不提供持久化能力，进程结束后数据即丢失。
import asyncio
import time
from typing import List, Optional, Dict, Any

from domain.message import Message
from domain.rag import RagChunk, RagDocument
from domain.session import Session
from storage.base import IStorage


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

    # ------------- rag -------------

    async def upsert_rag_document(self, doc: RagDocument, chunks: List[RagChunk]) -> None:
        async with self._lock:
            self._docs[doc.doc_id] = doc
            self._docs_by_user.setdefault(doc.user_id, [])
            if doc.doc_id not in self._docs_by_user[doc.user_id]:
                self._docs_by_user[doc.user_id].append(doc.doc_id)

            # 替换分片
            self._chunks_by_doc[doc.doc_id] = []
            if chunks:
                # 维持传入顺序，chunk_index 由上游负责
                self._chunks_by_doc[doc.doc_id].extend(chunks)

    async def list_rag_documents(self, user_id: int) -> List[RagDocument]:
        async with self._lock:
            ids = self._docs_by_user.get(user_id, [])
            docs = []
            for doc_id in ids:
                d = self._docs.get(doc_id)
                if d and not int(getattr(d, "is_deleted", 0)):
                    docs.append(d)
            docs.sort(key=lambda d: int(getattr(d, "updated_at", 0)), reverse=True)
            return docs

    async def delete_rag_document(self, user_id: int, doc_id: str) -> None:
        async with self._lock:
            d = self._docs.get(doc_id)
            if not d:
                return
            if d.user_id != user_id:
                return
            d.is_deleted = 1
            d.updated_at = int(time.time())

    async def get_rag_chunks_with_embeddings(
            self,
            *,
            scan_limit: int,
            user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        async with self._lock:
            visible_docs: Dict[str, RagDocument] = {}
            for doc_id, d in self._docs.items():
                if int(getattr(d, "is_deleted", 0)):
                    continue
                scope = getattr(d, "scope", "global") or "global"
                if user_id is None:
                    if scope == "global":
                        visible_docs[doc_id] = d
                else:
                    if scope == "global" or (scope == "private" and int(getattr(d, "user_id", -1)) == int(user_id)):
                        visible_docs[doc_id] = d

            rows: List[Dict[str, Any]] = []
            for doc_id in visible_docs.keys():
                chunks = self._chunks_by_doc.get(doc_id, [])
                if not chunks:
                    continue
                for c in chunks:
                    emb = getattr(c, "embedding", None)
                    if emb is None:
                        continue
                    rows.append({
                        "doc_id": c.doc_id,
                        "user_id": int(getattr(c, "user_id", 0)),
                        "chunk_index": int(getattr(c, "chunk_index", 0)),
                        "content": c.content,
                        "embedding": emb,
                        "created_at": int(getattr(c, "created_at", 0)),
                        "title": getattr(self._docs.get(c.doc_id), "title", None),
                        "url": getattr(self._docs.get(c.doc_id), "url", None),
                    })

            rows.sort(key=lambda r: (r["doc_id"], r["chunk_index"]))
            if scan_limit is not None and scan_limit > 0:
                rows = rows[:int(scan_limit)]
            return rows

    # ------------- default -------------

    async def close(self):
        return
