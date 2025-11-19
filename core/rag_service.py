# -*- coding: utf-8 -*-
# @File: rag_service.py
# @Author: yaccii
# @Time: 2025-11-10 08:57
# @Description: RAG 文档上传 / 检索 / 删除（依赖向量库：FAISS / Milvus）
import uuid
from typing import Optional, List, Dict, Any

from fastapi import UploadFile

from infrastructure.config_manager import config
from infrastructure.mlogger import mlogger
from infrastructure.vector_store_manager import get_vector_store
from rag.embeddings import Embeddings
from rag.loader import (
    load_text_from_upload_file,
    load_text_from_url,
    load_text_from_file_path,
)
from rag.splitter import split_text
from storage.vector_store_base import VectorSearchResult


class RagService:
    def __init__(self) -> None:
        self._config: Dict[str, Any] = config.as_dict()
        self._embedding = Embeddings()

    async def ingest_from_url(self, user_id: int, url: str, title: Optional[str], tags: Optional[List[str]],
                              scope: str) -> str:
        got_title, content = await load_text_from_url(url)
        final_title = (title or got_title or url or "Untitled")[:255]
        return await self._ingest_raw_text(
            user_id=user_id,
            url=url,
            title=final_title,
            tags=(tags or []),
            scope=scope,
            content=content,
        )

    async def ingest_from_file(self, user_id: int, file: UploadFile, title: Optional[str], tags: Optional[List[str]],
                               scope: str) -> str:
        """
        从上传文件读取内容并写入向量库。
        """
        got_title, content = await load_text_from_upload_file(file)
        final_title = (title or got_title or file.filename or "Untitled")[:255]
        return await self._ingest_raw_text(
            user_id=user_id,
            url=None,
            title=final_title,
            tags=(tags or []),
            scope=scope,
            content=content,
        )

    async def ingest_from_file_path(self, user_id: int, file_path: str, title: Optional[str], tags: Optional[List[str]],
                                    scope: str) -> str:
        got_title, content = load_text_from_file_path(file_path)
        final_title = (title or got_title or "Untitled")[:255]
        return await self._ingest_raw_text(
            user_id=user_id,
            url=None,
            title=final_title,
            tags=(tags or []),
            scope=scope,
            content=content,
        )

    async def _ingest_raw_text(self, user_id: int, title: str, content: str, url: Optional[str] = None,
                               tags: Optional[List[str]] = None, scope: str = "global") -> str:
        title = (title or "").strip()
        content = (content or "").strip()

        if not title or not content:
            raise ValueError("[RagService] Title or content must be provided")

        # 1. 文本切分
        split_config = self._config.get("rag_split") or {}
        parts: List[str] = split_text(
            content,
            target_tokens=int(split_config.get("target_tokens", 400)),
            max_tokens=int(split_config.get("max_tokens", 800)),
            sentence_overlap=int(split_config.get("sentence_overlap", 2)),
        )

        if not parts:
            raise ValueError("[RagService] Content must be provided after splitting")

        # 2. Embedding
        vectors: List[List[float]] = await self._embedding.encode(texts=parts)
        if not vectors:
            raise RuntimeError("[RagService] Embedding result is empty")

        dim = len(vectors[0])
        embed_cfg = self._config.get("embedding", {}) or {}
        expect_dim = int(embed_cfg.get("dim") or 0)
        if expect_dim and dim != expect_dim:
            mlogger.warning(self.__class__.__name__, "_ingest_raw_text", msg="dim mismatch", config=embed_cfg, got=dim)

        doc_id = str(uuid.uuid4())

        store = get_vector_store()
        if store is None:
            mlogger.warning(self.__class__.__name__, "vector store not available", msg="skip RAG ingest", doc_id=doc_id)
            return doc_id

        try:
            store.upsert_document(
                doc_id=doc_id,
                user_id=user_id,
                title=title[:255],
                url=url,
                scope=scope,
                tags=tags or [],
                chunks=parts,
                embeddings=vectors,
            )
        except Exception as e:
            mlogger.exception(self.__class__.__name__, "upsert_document", user_id=user_id, doc_id=doc_id, msg=e)
            raise

        mlogger.info(self.__class__.__name__, "upsert success", user_id=user_id, doc_id=doc_id)
        return doc_id

    async def list_documents(self, user_id: int) -> List[Dict[str, Any]]:
        """ 暂不实现 """
        return []

    async def delete_document(self, user_id: int, doc_id: str) -> None:

        doc_id = (doc_id or "").strip()
        if not doc_id:
            return

        store = get_vector_store()
        if store is None:
            mlogger.warning(self.__class__.__name__, "delete_document", msg="vector store is None", user_id=user_id,
                            doc_id=doc_id)
            return

        try:
            store.delete_document(doc_id)
            mlogger.info(self.__class__.__name__, "delete success", user_id=user_id, doc_id=doc_id)

        except Exception as e:
            mlogger.exception(self.__class__.__name__, "delete_document", msg=e, user_id=user_id, doc_id=doc_id)
            raise

    async def semantic_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        store = get_vector_store()
        if store is None:
            mlogger.warning(self.__class__.__name__, "semantic_search", msg="store is None", query=query)
            return []

        # 1. query -> embedding
        qv = await self._embedding.encode([query])
        if not qv or not qv[0]:
            return []

        query_emb: List[float] = qv[0]

        # 2. 向量检索
        rag_cfg = self._config.get("rag") or {}
        default_top_k = int(rag_cfg.get("top_k", 5))
        k = int(top_k or default_top_k or 5)

        try:
            raw_results: List[VectorSearchResult] = store.search(
                query_embedding=query_emb,
                top_k=k,
            )
        except Exception as e:
            mlogger.exception(self.__class__.__name__, "semantic_search", msg=e, query=query)
            return []

        def _mk_snippet(s: str, limit: int = 200) -> str:
            t = " ".join((s or "").split())
            return t if len(t) <= limit else (t[:limit] + "…")

        out: List[Dict[str, Any]] = []
        for r in raw_results:
            # score 标准化：score<=1 视为相似度(0~1)，映射到 0~100；否则当百分数截断
            if r.score is None:
                score_100 = 0
            elif r.score <= 1.0:
                score_100 = int(max(0, min(100, round(r.score * 100))))
            else:
                score_100 = int(max(0, min(100, round(r.score))))

            out.append(
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": _mk_snippet(r.content),
                    "score": score_100,
                    "meta": {
                        "doc_id": r.doc_id,
                        "chunk_index": r.chunk_index,
                    },
                    "content": r.content,
                }
            )

        return out
