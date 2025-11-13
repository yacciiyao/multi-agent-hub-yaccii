# -*- coding: utf-8 -*-
# @File: bots_router.py
# @Author: yaccii
# @Time: 2025-11-09 19:04
# @Description: 模型展示
from fastapi import APIRouter

from bots.bot_registry import BotRegistry
from infrastructure.response import success

router = APIRouter(prefix="/bots", tags=["messages"])


@router.get("", summary="获取模型列表")
def list_bots():
    bots = BotRegistry.list_bots()
    return success(data={"bots": bots})
