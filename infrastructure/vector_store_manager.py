# -*- coding: utf-8 -*-
# @File: vector_store_manager.py
# @Author: yaccii
# @Time: 2025-11-14 10:00
# @Description: 根据配置初始化并管理全局 VectorStore（Faiss 或 Milvus）
from __future__ import annotations

from typing import Optional

from infrastructure.config_manager import config
from storage.vector_store_base import IStore
from storage.vector_store_faiss import FaissVectorStore
from storage.vector_store_milvus import MilvusVectorStore

# 全局单例
_vector_store: Optional[IStore] = None
_backend_type: Optional[str] = None


def _init_vector_store() -> None:
    global _vector_store, _backend_type

    if _vector_store is not None:
        return

    cfg = config.as_dict()
    rag_cfg = cfg.get("rag") or {}
    embedding_cfg = cfg.get("embedding") or {}

    enabled = rag_cfg.get("enabled", True)
    if not enabled:
        _vector_store = None
        _backend_type = None
        return

    backend = str(rag_cfg.get("backend", "faiss"))
    if backend not in ("faiss", "milvus"):
        backend = "faiss"

    dim = int(embedding_cfg.get("dim") or 1536)

    if backend == "faiss":
        faiss_cfg = rag_cfg.get("faiss") or {}
        index_dir = faiss_cfg.get("index_dir") or "data/vector_store/faiss"
        store = FaissVectorStore(root_dir=index_dir, dim=dim)
        _vector_store = store
        _backend_type = "faiss"
        return

    if backend == "milvus":
        milvus_cfg = rag_cfg.get("milvus") or {}
        mode = str(milvus_cfg.get("mode") or "zilliz").lower()
        collection_name = milvus_cfg.get("collection") or "multi_agent_hub_rag"

        if mode == "zilliz":
            uri = milvus_cfg.get("zilliz_uri") or ""
            token = milvus_cfg.get("zilliz_token") or ""
            store = MilvusVectorStore(
                mode="zilliz",
                collection_name=collection_name,
                dim=dim,
                zilliz_uri=uri,
                zilliz_token=token,
            )
        else:
            host = milvus_cfg.get("host") or "127.0.0.1"
            port = int(milvus_cfg.get("port") or 19530)
            store = MilvusVectorStore(
                mode="self_host",
                collection_name=collection_name,
                dim=dim,
                host=host,
                port=port,
            )

        _vector_store = store
        _backend_type = "milvus"
        return


def get_vector_store() -> Optional[IStore]:
    """
    对外唯一入口：拿到底层向量库实例（Faiss 或 Milvus）。

    - 如果 RAG 未启用 / 配置错误，返回 None
    - core/rag_service 在调用前要处理 None 的情况（比如直接跳过 RAG）
    """
    if _vector_store is None:
        _init_vector_store()
    return _vector_store


def get_backend_type() -> Optional[str]:
    """
    返回当前启用的向量后端类型："faiss" | "milvus" | None
    """
    if _vector_store is None:
        _init_vector_store()
    return _backend_type


def reset_vector_store_for_tests() -> None:
    """
    测试代码可以调用这个重置全局实例（生产环境不会用到）。
    """
    global _vector_store, _backend_type
    _vector_store = None
    _backend_type = None
