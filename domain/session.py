# -*- coding: utf-8 -*-
# @File: session.py
# @Author: yaccii
# @Time: 2025-11-08 18:46
# @Description:
from typing import Optional

from pydantic import Field, BaseModel

from domain.enums import Channel


class Session(BaseModel):
    session_id: str
    user_id: int
    bot_name: str
    session_name: Optional[str] = None
    stream_enabled: bool = False
    rag_enabled: bool = False
    channel: Channel = Channel.WEB
    is_deleted: int = 0
    created_at: int = Field(default=0)
    updated_at: int = Field(default=0)

    class Config:
        from_attributes = True

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "bot_name": self.bot_name,
            "channel": getattr(self.channel, "value", str(self.channel)),
            "session_name": self.session_name,
            "rag_enabled": bool(self.rag_enabled),
            "stream_enabled": bool(self.stream_enabled),
            "is_deleted": bool(self.is_deleted),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
