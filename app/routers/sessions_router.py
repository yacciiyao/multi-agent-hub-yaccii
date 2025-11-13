# -*- coding: utf-8 -*-
# @File: sessions_router.py
# @Author: yaccii
# @Time: 2025-11-09 18:22
# @Description: 会话创建/列表/删除/重开
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core.session_service import SessionService
from domain.enums import Channel
from infrastructure.response import success, failure


def get_session_service() -> SessionService:
    return SessionService()


class CreateSessionRequest(BaseModel):
    user_id: int = Field(..., description="用户ID")
    bot_name: str = Field(..., description="模型名称")
    channel: Channel = Field(default=Channel.WEB, description="渠道（默认WEB）")


class UpdateFlagsRequest(BaseModel):
    user_id: int = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    rag_enabled: bool = Field(default=False, description="是否启用RAG")
    stream_enabled: bool = Field(default=False, description="是否启用流式")


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/create", summary="创建会话")
async def create_session(request: CreateSessionRequest):
    if not request.user_id:
        return failure(message="user_id is required")
    if not request.bot_name:
        return failure(message="bot_name is required")

    svc = get_session_service()
    try:
        session_id = await svc.create_session(
            user_id=request.user_id,
            bot_name=request.bot_name,
            channel=request.channel,
        )
    except ValueError as e:
        return failure(message=str(e))
    return success(data={"session_id": session_id})


@router.post("/list", summary="获取会话列表")
async def list_sessions(user_id: int = Query(..., description="用户ID")):
    svc = get_session_service()
    items = await svc.list_sessions(user_id=user_id)
    return success(data=items)


@router.post("/get", summary="获取会话详情")
async def get_session(user_id: int = Query(..., description="用户ID"),
                      session_id: str = Query(..., description="会话ID")):
    svc = get_session_service()
    sess = await svc.get_session(user_id=user_id, session_id=session_id)
    if not sess:
        return failure(message="session not found")
    return success(data=sess)


@router.post("/update_flags", summary="更新会话RAG/流式状态")
async def update_flags(request: UpdateFlagsRequest):
    svc = get_session_service()
    await svc.update_session_flag(
        user_id=request.user_id,
        session_id=request.session_id,
        rag_enabled=request.rag_enabled,
        stream_enabled=request.stream_enabled,
    )
    return success()


@router.post("/delete", summary="删除会话")
async def delete_session(user_id: int = Query(..., description="用户ID"),
                         session_id: str = Query(..., description="会话ID")):
    svc = get_session_service()
    await svc.delete_session(user_id=user_id, session_id=session_id)
    return success()


@router.post("/delete_all", summary="删除全部会话")
async def delete_all_sessions(user_id: int = Query(..., description="用户ID")):
    svc = get_session_service()
    await svc.delete_all_sessions(user_id)
    return success()
