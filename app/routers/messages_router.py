# -*- coding: utf-8 -*-
# @File: messages_router.py
# @Author: yaccii
# @Time: 2025-11-09 19:03
# @Description: 发送消息、流式返回、RAG开关动作推送
import time
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from core.message_service import MessageService
from core.session_service import SessionService
from domain.enums import Role, Channel
from domain.message import Message
from infrastructure.response import failure, success


def get_message_service() -> MessageService:
    return MessageService()


def get_session_service() -> SessionService:
    return SessionService()


class ChatRequest(BaseModel):
    user_id: int = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    role: Role = Field(default=Role.USER, description="消息角色")
    content: str = Field(..., description="消息内容")
    stream: bool = Field(default=False, description="是否流式返回")
    rag_enabled: bool = Field(default=False, description="是否启用RAG")
    channel: Channel = Field(default=Channel.WEB, description="渠道")


router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/history", summary="获取消息历史")
async def history(user_id: int = Query(..., description="用户ID"),
                  session_id: str = Query(..., description="会话ID")):
    svc = get_message_service()
    data = await svc.get_messages(user_id=user_id, session_id=session_id)
    return success(data={"history": data})


@router.post("/chat", summary="发送消息")
async def chat(request: ChatRequest):
    msg = Message(
        session_id=request.session_id,
        role=request.role,
        content=request.content,
        rag_enabled=bool(request.rag_enabled),
        stream_enabled=bool(request.stream),
    )

    message_svc = get_message_service()
    try:
        if request.stream:
            gen = await message_svc.send_message(
                user_id=request.user_id,
                message=msg,
                stream=True,
            )
            return StreamingResponse(gen, media_type="text/plain; charset=utf-8")
        else:
            result = await message_svc.send_message(
                user_id=request.user_id,
                message=msg,
                stream=False,
            )
            return success(data=result)
    except Exception as e:
        return failure(message=str(e))


@router.post("/system", summary="系统提示")
async def system_tip(user_id: int = Query(..., description="用户ID"),
                     session_id: str = Query(..., description="会话ID"),
                     rag: Optional[int] = Query(None, description="若提供则同步RAG状态，1启用/0关闭")):
    if rag is None:
        return success()

    session_svc = get_session_service()
    session = await session_svc.get_session(user_id=user_id, session_id=session_id)
    if not session_svc:
        return failure(message="session not found")

    await session_svc.update_session_flag(
        user_id=user_id,
        session_id=session_id,
        rag_enabled=bool(int(rag)),
        stream_enabled=bool(session.get("stream_enabled", False)),
    )
    return success()
