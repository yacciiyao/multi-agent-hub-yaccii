# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:52
@Desc:
"""
from typing import Optional, List, Dict

from pydantic import BaseModel


class Reply(BaseModel):
    """ 标准的回复输出 """
    user_id: int
    session_id: str
    session_name: Optional[str] = None
    text: str
    sources: Optional[List[Dict[str, str]]] = []
    metadata: Optional[Dict[str, Optional[str]]] = None
