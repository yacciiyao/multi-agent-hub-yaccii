# -*- coding: utf-8 -*-
# @File: __init__.py
# @Author: yaccii
# @Time: 2025-11-13 20:28
# @Description:
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import faiss
import numpy as np

from storage.vector_store_base import VectorSearchResult, VStore


class FaissVectorStore(VStore):
    """
    FAISS 向量库：所有向量存在内存 + embeddings.npy (本地测试用)
    """

    def __init__(self, root_dir: str, dim: int):
        self.root_dir = root_dir
        self.dim = dim
        os.makedirs(self.root_dir, exist_ok=True)

        self._index_path = os.path.join(self.root_dir, "index.faiss")
        self._emb_path = os.path.join(self.root_dir, "embeddings.npy")
        self._meta_path = os.path.join(self.root_dir, "metas.json")

        self._embeddings: Optional[np.ndarray] = None  # shape (N, dim)
        self._metas: List[Dict[str, Any]] = []  # len == N
        self._index: Optional[faiss.Index] = None

        self._load()

    def upsert_document(
            self,
            *,
            doc_id: str,
            user_id: Optional[int],
            title: str,
            url: Optional[str],
            scope: str,
            tags: List[str],
            chunks: List[str],
            embeddings: List[List[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks 和 embeddings 长度必须一致")

        self._remove_doc_from_memory(doc_id)

        new_vecs = np.asarray(embeddings, dtype=np.float32)
        if new_vecs.shape[1] != self.dim:
            raise ValueError(f"embedding dim mismatch: expect {self.dim}, got {new_vecs.shape[1]}")

        new_metas: List[Dict[str, Any]] = []
        for idx, chunk_text in enumerate(chunks):
            meta: Dict[str, Any] = {
                "doc_id": doc_id,
                "chunk_index": idx,
                "user_id": user_id,
                "title": title,
                "url": url,
                "content": chunk_text,
                "scope": scope,
                "tags": tags,
            }
            new_metas.append(meta)

        if self._embeddings is None or len(self._embeddings) == 0:
            self._embeddings = new_vecs
            self._metas = new_metas
        else:
            self._embeddings = np.vstack([self._embeddings, new_vecs])
            self._metas.extend(new_metas)

        self._rebuild_index()
        self._persist()

    def delete_document(self, doc_id: str) -> None:
        self._remove_doc_from_memory(doc_id)
        self._rebuild_index()
        self._persist()

    def search(
            self,
            query_embedding: List[float],
            top_k: int,
    ) -> List[VectorSearchResult]:
        if self._embeddings is None or self._embeddings.shape[0] == 0:
            return []

        if self._index is None:
            self._rebuild_index()

        q = np.asarray(query_embedding, dtype=np.float32).reshape(1, -1)
        if q.shape[1] != self.dim:
            raise ValueError(f"query dim mismatch: expect {self.dim}, got {q.shape[1]}")

        k = max(1, int(top_k))
        distances, indices = self._index.search(q, k)

        results: List[VectorSearchResult] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._metas):
                continue
            meta = self._metas[idx]

            score = float(dist)

            r = VectorSearchResult(
                doc_id=str(meta.get("doc_id") or ""),
                chunk_index=int(meta.get("chunk_index") or 0),
                user_id=meta.get("user_id"),
                title=str(meta.get("title") or ""),
                url=meta.get("url"),
                content=str(meta.get("content") or ""),
                score=score,
                metadata={
                    "scope": meta.get("scope"),
                    "tags": meta.get("tags"),
                },
            )
            results.append(r)

        return results

    # ---------- 内部方法 ----------

    def _load(self) -> None:
        if os.path.exists(self._emb_path) and os.path.exists(self._meta_path):
            try:
                self._embeddings = np.load(self._emb_path).astype(np.float32)
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    self._metas = json.load(f)
            except Exception:
                self._embeddings = None
                self._metas = []

        if self._embeddings is not None and self._embeddings.shape[0] > 0:
            self._rebuild_index()
        else:
            self._index = None

    def _persist(self) -> None:
        if self._embeddings is None or len(self._metas) == 0:
            # 清空文件
            if os.path.exists(self._emb_path):
                os.remove(self._emb_path)
            if os.path.exists(self._meta_path):
                os.remove(self._meta_path)
            if os.path.exists(self._index_path):
                os.remove(self._index_path)
            return

        np.save(self._emb_path, self._embeddings)
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(self._metas, f, ensure_ascii=False)

        if self._index is not None:
            faiss.write_index(self._index, self._index_path)

    def _rebuild_index(self) -> None:
        if self._embeddings is None or self._embeddings.shape[0] == 0:
            self._index = None
            return

        index = faiss.IndexFlatIP(self.dim)  # Inner Product
        faiss.normalize_L2(self._embeddings)  # 归一化方便用 IP 近似 cosine
        index.add(self._embeddings)
        self._index = index

    def _remove_doc_from_memory(self, doc_id: str) -> None:
        if self._embeddings is None or not self._metas:
            return

        keep_indices = [
            i for i, meta in enumerate(self._metas)
            if str(meta.get("doc_id") or "") != str(doc_id)
        ]

        if len(keep_indices) == len(self._metas):
            return

        if keep_indices:
            self._embeddings = self._embeddings[keep_indices]
            self._metas = [self._metas[i] for i in keep_indices]
        else:
            # 全删光了
            self._embeddings = None
            self._metas = []
