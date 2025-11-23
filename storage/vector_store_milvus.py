# -*- coding: utf-8 -*-
# @File: vector_store_milvus.py
# @Author: yaccii
# @Time: 2025-11-19 15:01
# @Description:
from __future__ import annotations

import json
from typing import List, Optional

from pymilvus import (
    connections,
    utility,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
)

from storage.vector_store_base import VStore, VectorSearchResult


class MilvusVectorStore(VStore):
    """
    基于 Milvus / Zilliz 向量库：
    - collection字段: doc_id/chunk_index/user_id/title/url/content/scope/tags/embedding
    """

    def __init__(
            self,
            mode: str,
            collection_name: str,
            dim: int,
            zilliz_uri: Optional[str] = None,
            zilliz_token: Optional[str] = None,
            host: Optional[str] = None,
            port: Optional[int] = None,
    ) -> None:
        self.collection_name = collection_name
        self.dim = dim

        if mode == "zilliz":
            if not zilliz_uri or not zilliz_token:
                raise ValueError("zilliz_uri / zilliz_token 必须在 mode='zilliz' 时提供")
            connections.connect(
                alias="default",
                uri=zilliz_uri,
                token=zilliz_token,
            )
        else:
            if not host or not port:
                raise ValueError("host / port 必须在 mode='self_host' 时提供")
            connections.connect(
                alias="default",
                host=host,
                port=str(port),
            )

        if not utility.has_collection(self.collection_name):
            self._create_collection()

        self._col = Collection(self.collection_name)
        self._create_index_if_needed()
        self._col.load()

    def upsert_document(
            self,
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

        self.delete_document(doc_id)

        n = len(chunks)
        doc_ids = [doc_id] * n
        chunk_indices = list(range(n))
        user_ids = [user_id if user_id is not None else -1] * n
        titles = [title] * n
        urls = [url or ""] * n
        contents = chunks
        scopes = [scope] * n
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        tags_list = [tags_json] * n

        entities = [
            doc_ids,
            chunk_indices,
            user_ids,
            titles,
            urls,
            contents,
            scopes,
            tags_list,
            embeddings,
        ]

        self._col.insert(entities)
        self._col.flush()

    def delete_document(self, doc_id: str) -> None:
        if not doc_id:
            return
        expr = f'doc_id == "{doc_id}"'
        self._col.delete(expr)

    def search(self, query_embedding: List[float], top_k: int) -> List[VectorSearchResult]:
        if self._col.num_entities == 0:
            return []

        k = max(1, int(top_k))

        search_params = {
            "metric_type": "IP",
            "params": {"nprobe": 10},
        }

        results = self._col.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=k,
            output_fields=[
                "doc_id",
                "chunk_index",
                "user_id",
                "title",
                "url",
                "content",
                "scope",
                "tags",
            ],
        )

        out: List[VectorSearchResult] = []
        if not results:
            return out

        hits = results[0]
        for hit in hits:
            doc_id = hit.entity.get("doc_id")
            chunk_index = hit.entity.get("chunk_index")
            user_id = hit.entity.get("user_id")
            title = hit.entity.get("title")
            url = hit.entity.get("url")
            content = hit.entity.get("content")
            scope = hit.entity.get("scope")
            tags_json = hit.entity.get("tags") or "[]"

            try:
                tags = json.loads(tags_json)
            except Exception:
                tags = []

            r = VectorSearchResult(
                doc_id=str(doc_id or ""),
                chunk_index=int(chunk_index or 0),
                user_id=int(user_id) if user_id is not None else None,
                title=str(title or ""),
                url=str(url or "") or None,
                content=str(content or ""),
                score=float(hit.distance),  # IP 情况下 distance 就是相似度
                metadata={
                    "scope": scope,
                    "tags": tags,
                },
            )
            out.append(r)

        return out

    def _create_collection(self) -> None:
        fields = [
            FieldSchema(
                name="id",
                dtype=DataType.INT64,
                is_primary=True,
                auto_id=True,
            ),
            FieldSchema(
                name="doc_id",
                dtype=DataType.VARCHAR,
                is_primary=False,
                max_length=128,
            ),
            FieldSchema(
                name="chunk_index",
                dtype=DataType.INT64,
                is_primary=False,
            ),
            FieldSchema(
                name="user_id",
                dtype=DataType.INT64,
                is_primary=False,
            ),
            FieldSchema(
                name="title",
                dtype=DataType.VARCHAR,
                is_primary=False,
                max_length=256,
            ),
            FieldSchema(
                name="url",
                dtype=DataType.VARCHAR,
                is_primary=False,
                max_length=512,
            ),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                is_primary=False,
                max_length=8192,
            ),
            FieldSchema(
                name="scope",
                dtype=DataType.VARCHAR,
                is_primary=False,
                max_length=64,
            ),
            FieldSchema(
                name="tags",
                dtype=DataType.VARCHAR,
                is_primary=False,
                max_length=512,
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=self.dim,
            ),
        ]

        schema = CollectionSchema(
            fields=fields,
            description="RAG chunks for multi-agent-hub",
        )

        Collection(
            name=self.collection_name,
            schema=schema,
            using="default",
            shards_num=2,
        )

    def _create_index_if_needed(self) -> None:
        indexes = self._col.indexes
        if indexes:
            return

        index_params = {
            "index_type": "HNSW",
            "metric_type": "IP",
            "params": {"M": 8, "efConstruction": 64},
        }
        self._col.create_index(
            field_name="embedding",
            index_params=index_params,
        )
