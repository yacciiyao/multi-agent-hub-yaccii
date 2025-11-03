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
    source: str = "web"
    use_kg: bool = False
    timestamp: int = field(default_factory=lambda: int(time.time()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "source": self.source,
            "use_kg": self.use_kg,
            "timestamp": self.timestamp,
            "metadata": self.metadata or {},
        }
