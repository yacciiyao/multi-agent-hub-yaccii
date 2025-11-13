# -*- coding: utf-8 -*-
# @File: message.py
# @Author: yaccii
# @Time: 2025-11-08 16:47
# @Description:
import time
from typing import List, Optional, Dict

from pydantic import BaseModel, Field

from domain.enums import Role


class RagSource(BaseModel):
    title: str
    url: Optional[str] = None
    snippet: Optional[str] = None
    score: Optional[float] = None
    meta: Dict[str, str] = Field(default_factory=dict)


class Message(BaseModel):
    session_id: str
    role: Role
    content: str
    rag_enabled: bool = False
    stream_enabled: bool = False
    sources: List[RagSource] = Field(default_factory=list)
    created_at: int = Field(default_factory=lambda: int(time.time()))
    is_deleted: bool = False

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "role": getattr(self.role, "value", str(self.role)),
            "content": self.content,
            "rag_enabled": bool(self.rag_enabled),
            "stream_enabled": bool(self.stream_enabled),
            "sources": [
                (s.model_dump() if hasattr(s, "model_dump") else dict(s))
                for s in (self.sources or [])
            ],
            "created_at": int(self.created_at or 0),
            "is_deleted": bool(self.is_deleted),
        }
