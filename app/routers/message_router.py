# -*- coding: utf-8 -*-
# @File: message_router.py
# @Author: yaccii
# @Time: 2025-11-09 19:03
# @Description: 发送消息、流式返回、RAG开关动作推送
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from core.message_service import MessageService
from core.session_service import SessionService
from domain.enums import Role, Channel, AttachmentType
from domain.message import Message, Attachment
from infrastructure.response import failure, success


class AttachmentDTO(BaseModel):
    id: str
    type: AttachmentType
    url: str
    mime_type: Optional[str] = None
    file_name: Optional[str] = None
    size_bytes: Optional[int] = None
    meta: Dict[str, Any] = Field(default_factory=dict)

    def to_domain(self) -> Attachment:
        return Attachment(
            id=self.id,
            type=self.type,
            url="https://images-na.ssl-images-amazon.com/images/I/615KnbjRmTL._AC_UL225_SR225,160_.jpg",
            mime_type=self.mime_type,
            file_name=self.file_name,
            size_bytes=self.size_bytes,
            meta=dict(self.meta or {}),
        )


class ChatRequest(BaseModel):
    user_id: int = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    role: Role = Field(default=Role.USER, description="消息角色")
    content: str = Field(..., description="消息内容")
    attachments: List[AttachmentDTO] = Field(default_factory=list)
    stream: bool = Field(default=False, description="是否流式返回")
    rag_enabled: bool = Field(default=False, description="是否启用RAG")
    channel: Channel = Field(default=Channel.WEB, description="渠道")


def get_message_service() -> MessageService:
    return MessageService()


def get_session_service() -> SessionService:
    return SessionService()


router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/history", summary="获取消息历史")
async def history(
        user_id: int = Query(..., description="用户ID"),
        session_id: str = Query(..., description="会话ID"),
):
    svc = get_message_service()
    data = await svc.get_messages(user_id=user_id, session_id=session_id)
    return success(data={"history": data})


@router.post("/chat", summary="发送消息")
async def chat(request: ChatRequest):
    message_svc = get_message_service()

    attachments: List[Attachment] = [
        dto.to_domain() for dto in (request.attachments or [])
    ]

    msg = Message(
        session_id=request.session_id,
        role=request.role,
        content=request.content,
        attachments=attachments,
        rag_enabled=bool(request.rag_enabled),
        stream_enabled=bool(request.stream),
    )

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
async def system_tip(
        user_id: int = Query(..., description="用户ID"),
        session_id: str = Query(..., description="会话ID"),
        rag: Optional[int] = Query(None, description="若提供则同步RAG状态，1启用/0关闭"),
):
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
