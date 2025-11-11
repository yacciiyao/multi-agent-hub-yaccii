# -*- coding: utf-8 -*-
# @File: rag.py
# @Author: yaccii
# @Time: 2025-11-08 16:52
# @Description:
import time
from typing import Optional, List, Dict, Any

from pydantic import Field

from domain.base import DomainModel


class RagDocument(DomainModel):
    doc_id: str
    user_id: int
    title: str = Field(max_length=255)
    source: str = "upload"  # upload | web | sync
    url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    scope: str = "global"  # global | private
    is_deleted: int = 0
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))

    embed_provider: str
    embed_model: str
    embed_dim: int
    embed_version: int = 1
    split_params: Dict[str, Any] = Field(default_factory=dict)
    preprocess_flags: str = "strip=1,html=basic"


class RagChunk(DomainModel):
    doc_id: str
    user_id: int
    chunk_index: int
    content: str
    created_at: int = Field(default_factory=lambda: int(time.time()))
    embedding: Optional[List[float]] = None
