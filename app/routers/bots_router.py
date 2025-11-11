# -*- coding: utf-8 -*-
# @File: bots_router.py
# @Author: yaccii
# @Time: 2025-11-09 19:04
# @Description: 模型展示
from fastapi import APIRouter

from bots.bot_registry import BotRegistry
from infrastructure.response import success

router = APIRouter()


@router.get("", summary="获取模型列表")
def list_bots():
    bots = BotRegistry.list_bots()
    return success(data={"bots": bots})
{
  "code": 0,
  "message": "ok",
  "data": {
    "bots": [
      {
        "family": "Claude",
        "bot_name": "claude-3-5-haiku-latest",
        "desc": "性价比/低延迟"
      },
      {
        "family": "Claude",
        "bot_name": "claude-3-5-sonnet-latest",
        "desc": "旗舰对话/推理"
      }
    ]
  }
}