# -*- coding: utf-8 -*-
# @File: base_bot.py
# @Author: yaccii
# @Time: 2025-11-08 17:27
# @Description: 模型统一抽象基类
from abc import ABC, abstractmethod
from typing import Dict, List, Union, AsyncIterator


class BaseBot(ABC):
    name = "unknow"
    bots: Dict[str, Dict] = {}

    def __init__(self, **kwargs):
        self._extras = kwargs

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], stream: bool = False) -> Union[str, AsyncIterator[str]]:
        raise NotImplementedError

    @abstractmethod
    async def healthcheck(self) -> bool:
        raise NotImplementedError
