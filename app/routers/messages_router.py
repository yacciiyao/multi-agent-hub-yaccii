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
from domain.enums import Role, Channel
from domain.message import Message
from infrastructure.response import failure, success


def get_message_service() -> MessageService:
    return MessageService()


class SendMessageRequest(BaseModel):
    user_id: int = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    content: str = Field(..., min_length=1, description="消息内容")
    role: Role = Field(default=Role.USER, description="角色：user/assistant/system（默认 user）")
    stream: bool = Field(default=False, description="是否流式输出")
    rag_enabled: Optional[bool] = Field(default=None, description="是否启用知识库（None 表示不改动）")
    channel: Channel = Field(default=Channel.WEB, description="消息来源：web/wechat/dingtalk（默认 web）")


router = APIRouter()


@router.post("/chat", summary="发送消息")
async def send_message(request: SendMessageRequest):
    message_service = get_message_service()

    message = Message(
        session_id=request.session_id,
        role=Role.USER,
        content=request.content,
        rag_enabled=request.rag_enabled,
        sources=[],
        created_at=int(time.time()),
        is_deleted=False,
    )
    try:
        if request.stream:
            reply = await message_service.send_message(user_id=request.user_id, message=message, stream=True)
            return StreamingResponse(reply, media_type="text/plain; charset=utf-8")

        else:
            result = await message_service.send_message(user_id=request.user_id, message=message, stream=False)
            return success(data=result)

    except Exception as e:
        return failure(message=str(e))


@router.get("/system", summary="保存系统提示消息")
async def send_system_tip(user_id: int, session_id: str, content: str, rag_enabled: bool | None = None, ):
    message_service = get_message_service()
    await message_service.add_system_tip(user_id=user_id, session_id=session_id, content=content, rag_enabled=rag_enabled)
    return success()


@router.get("/history", summary="获取会话历史消息")
async def get_history(
        user_id: int = Query(..., description="用户ID"),
        session_id: str = Query(..., description="会话ID"),
):
    message_service = get_message_service()
    history = await message_service.get_messages(user_id=user_id, session_id=session_id)

    return success(data={"history": history})
