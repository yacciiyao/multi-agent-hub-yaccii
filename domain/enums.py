# -*- coding: utf-8 -*-
# @File: enums.py
# @Author: yaccii
# @Time: 2025-11-08 16:45
# @Description:
from enum import Enum


class Channel(str, Enum):
    WEB = "web"
    WECHAT = "wechat"
    DINGTALK = "dingtalk"


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOLS = "tool"
