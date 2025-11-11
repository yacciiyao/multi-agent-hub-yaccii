# -*- coding: utf-8 -*-
# @File: rag_service.py
# @Author: yaccii
# @Time: 2025-11-10 08:57
# @Description:
import time
import uuid
from typing import Optional, List, Dict, Any

import numpy as np
from fastapi import UploadFile

from domain.rag import RagDocument, RagChunk
from infrastructure.config_manager import config
from rag.embeddings import Embeddings
from rag.loader import load_text_from_upload_file, load_text_from_url, load_text_from_file_path
from rag.splitter import split_text


class RagService:
    def __init__(self):
        self._config = config.as_dict()
        self._storage = None
        self._embedding = Embeddings()

    @property
    def storage(self):
        if not self._storage:
            from infrastructure.storage_manager import storage_manager
            self._storage = storage_manager.get()
        return self._storage

    async def ingest_from_url(
        self, *, user_id: int, url: str, title: Optional[str], tags: Optional[List[str]], scope: str
    ) -> str:
        got_title, content = await load_text_from_url(url)
        final_title = (title or got_title or url)[:255]
        return await self._ingest_raw_text(
            user_id=user_id, source="web", url=url,
            title=final_title, tags=(tags or []), scope=scope,
            content=content,
        )

    async def ingest_from_file(
        self, *, user_id: int, file: UploadFile, title: Optional[str], tags: Optional[List[str]], scope: str
    ) -> str:
        got_title, content = await load_text_from_upload_file(file)
        final_title = (title or got_title or file.filename or "Untitled")[:255]
        return await self._ingest_raw_text(
            user_id=user_id, source="upload", url=None,
            title=final_title, tags=(tags or []), scope=scope,
            content=content,
        )

    async def ingest_from_file_path(
            self, *, user_id: int, file_path: str, title: Optional[str], tags: Optional[List[str]], scope: str
    ) -> str:
        got_title, content = load_text_from_file_path(file_path)
        final_title = (title or got_title or "Untitled")[:255]
        return await self._ingest_raw_text(
            user_id=user_id, source="upload", url=None,
            title=final_title, tags=(tags or []), scope=scope,
            content=content,
        )

    async def _ingest_raw_text(
            self,
            *,
            user_id: int,
            title: str,
            content: str,
            source: str = "upload",  # upload | web | sync
            url: Optional[str] = None,
            tags: Optional[List[str]] = None,
            scope: str = "global",
    ) -> str:

        if not title or not content:
            raise ValueError("[RagService] Title or content must be provided")

        split_config = (self._config.get("rag_split") or {})
        parts: List[str] = split_text(
            content,
            target_tokens=int(split_config.get("target_tokens", 400)),
            max_tokens=int(split_config.get("max_tokens", 800)),
            sentence_overlap=int(split_config.get("sentence_overlap", 2)),
        )

        if not parts:
            raise ValueError("[RagService]Content must be provided")

        vectors: List[List[float]] = await self._embedding.encode(texts=parts)
        if not vectors:
            raise RuntimeError("[RagService] Embedding result is empty")

        dim = len(vectors[0])
        now = int(time.time())
        doc_id = str(uuid.uuid4())

        embed_config = self._config.get("embedding", {}) or {}
        doc = RagDocument(
            doc_id=doc_id,
            user_id=user_id,
            title=title[:255],
            source=source,
            url=url,
            tags=tags or [],
            scope=scope,
            is_deleted=0,
            created_at=now,
            updated_at=now,
            embed_provider=embed_config.get("provider") or "openai",
            embed_model=embed_config.get("model") or "text-embedding-3-small",
            embed_dim=dim,
            embed_version=int(embed_config.get("version", 1)),
            split_params={
                "target_tokens": int(embed_config.get("target_tokens", 400)),
                "max_tokens": int(embed_config.get("max_tokens", 800)),
                "sentence_overlap": int(embed_config.get("sentence_overlap", 2)),
            },
            preprocess_flags="strip=1,html=basic"
        )

        chunk: List[RagChunk] = []
        for i, (txt, vector) in enumerate(zip(parts, vectors)):
            chunk.append(RagChunk(
                doc_id=doc_id,
                user_id=user_id,
                chunk_index=i,
                content=txt,
                embedding=vector,
                created_at=now
            ))
        await self.storage.upsert_rag_document(doc, chunk)

        return doc_id

    async def list_documents(self, user_id: int) -> List[Dict[str, Any]]:
        docs: List[RagDocument] = await self.storage.list_rag_documents(user_id=user_id)
        return [d.model_dump() for d in docs]

    async def delete_document(
            self,
            *,
            user_id: int,
            doc_id: str,
    ) -> None:
        await self.storage.delete_rag_document(user_id=user_id, doc_id=doc_id)

    async def semantic_search(
            self,
            *,
            user_id: int,
            query: str,
            top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        qv = await self._embedding.encode([query])
        if not qv or not qv[0]:
            return []

        q = np.asarray(qv[0], dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0.0:
            return []

        q = q / (q_norm + 1e-8)

        scan_limit = int(self._config.get("embeddings", {}).get("max_chunks_scan", 5000))
        candidates: List[Dict[str, Any]] = await self.storage.get_rag_chunks_with_embeddings(
            scan_limit=scan_limit, user_id=user_id
        )

        want_dim = q.shape[0]
        matrix: List[List[float]] = []
        keep: List[Dict[str, Any]] = []
        for c in candidates:
            vec = c.get("embedding")
            if isinstance(vec, list) and len(vec) == want_dim:
                matrix.append(vec)
                keep.append(c)

        if not matrix:
            return []

        M = np.asarray(matrix, dtype=np.float32)  # (N, dim)
        M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-8)
        sims = (M @ q).tolist()  # (N,)

        k = max(1, int(top_k))
        top_idx = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:k]

        def _mk_snippet(s: str, limit: int = 200) -> str:
            t = " ".join((s or "").split())
            return t if len(t) <= limit else (t[:limit] + "…")

        results: List[Dict[str, Any]] = []
        for i in top_idx:
            c = keep[i]
            sim = float(sims[i])
            results.append({
                "title": c.get("title"),
                "url": c.get("url"),
                "snippet": _mk_snippet(c.get("content") or ""),
                "score": max(0, min(100, round(sim * 100))),
                "meta": {"doc_id": c["doc_id"], "chunk_index": int(c["chunk_index"])},
                "content": c.get("content") or "",
            })
        return results
