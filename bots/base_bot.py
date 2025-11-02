# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:52
@Desc:
"""
from abc import abstractmethod, ABC
from typing import List, Dict


class BaseBot(ABC):
    """ 所有模型的抽象基类 """

    @abstractmethod
    def reply(self, query: str) -> str:
        """ 兼容单轮对话 """
        ...

    @abstractmethod
    def reply_with_context(self, messages: List[Dict[str, str]]) -> str:
        """ 带上下文的对话 """
        ...
