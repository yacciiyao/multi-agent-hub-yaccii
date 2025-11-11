# -*- coding: utf-8 -*-
# @File: sessions_router.py
# @Author: yaccii
# @Time: 2025-11-09 18:22
# @Description: 会话创建/列表/删除/重开
from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.session_service import SessionService
from domain.enums import Channel
from infrastructure.response import success, failure


def get_session_server() -> SessionService:
    return SessionService()


class CreateSessionRequest(BaseModel):
    user_id: int
    bot_name: str
    channel: Channel = Channel.WEB


router = APIRouter()


@router.post("/create", summary="创建会话")
async def create_session(request: CreateSessionRequest):
    user_id = request.user_id or None
    bot_name = request.bot_name or "gpt-3.5-turbo"
    channel = request.channel or Channel.WEB
    if not user_id:
        return failure(message="user_id is required")

    session_server = get_session_server()

    try:
        session_id = await session_server.create_session(user_id=user_id, bot_name=bot_name, channel=channel)
    except ValueError as e:
        return failure(message=str(e))

    return success(data={"session_id": session_id})


@router.post("/list", summary="获取会话列表")
async def list_sessions(user_id: int = Query(..., description="用户ID")):
    session_server = get_session_server()
    sessions = await session_server.list_sessions(user_id=user_id)

    return success(data=sessions)


@router.post("/delete", summary="删除会话")
async def delete_session(user_id: int = Query(...), session_id: str = Query(...)):
    session_server = get_session_server()
    await session_server.delete_session(user_id=user_id, session_id=session_id)

    return success()


@router.post("/delete_all", summary="删除全部会话")
async def delete_all_sessions(user_id: int = Query(...)):
    session_server = get_session_server()
    await session_server.delete_all_sessions(user_id)

    return success()
