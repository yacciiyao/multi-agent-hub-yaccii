# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-11-02 13:55
@Desc: 会话对象（统一命名 & 强类型）
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from core.message import Message


@dataclass
class Session:
    """
    单个会话的标准结构
    - mode 由 use_kg / agent_name 推导建议，但允许外部设定
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_name: Optional[str] = None
    model_name: str = "gpt-3.5-turbo"
    mode: str = "chat"  # "chat" | "knowledge" | "agent"
    use_kg: bool = False
    namespace: str = "default"
    agent_name: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time()))
    messages: List[Message] = field(default_factory=list)

    def append(self, msg: Message) -> None:
        self.messages.append(msg)

    def light_view(self) -> Dict[str, Any]:
        """列表视图（不包含消息体）"""

        return {
            "session_id": self.session_id,
            "session_name": self.session_name,
            "model_name": self.model_name,
            "mode": self.mode,
            "use_kg": self.use_kg,
            "namespace": self.namespace,
            "agent_name": self.agent_name,
            "created_at": self.created_at,
        }
