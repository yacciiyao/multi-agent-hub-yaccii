# -*- coding: utf-8 -*-
# @File: vector_store_base.py
# @Author: yaccii
# @Time: 2025-11-19 15:01
# @Description:
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod


@dataclass
class VectorSearchResult:
    doc_id: str
    chunk_index: int
    user_id: Optional[int]
    title: str
    url: Optional[str]
    content: str
    score: float
    metadata: Dict[str, Any]


class VStore(ABC):
    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def delete_document(self, doc_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
            self,
            query_embedding: List[float],
            top_k: int,
    ) -> List[VectorSearchResult]:
        raise NotImplementedError
