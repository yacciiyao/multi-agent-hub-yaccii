# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:52
@Desc: 标准消息对象（统一命名 & 强类型）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class Message:
    """
    单条消息的标准结构
    - 所有时间戳为 int（秒）
    - role: "user" | "assistant" | "system"
    - mode: "chat" | "knowledge" | "agent"
    - source: "web" | "ai" | "api" | "wechat" | "dingtalk" 等
    """

    role: str
    content: str
    model_name: str
    mode: str = "chat"
    source: str = "web"
    timestamp: int = field(default_factory=lambda: int(time.time()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "model_name": self.model_name,
            "metadata": self.metadata or {},
        }
