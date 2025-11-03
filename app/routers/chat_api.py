# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:50
@Desc:
"""
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.bridge_manager import bridge
from core.dialogue_service import dialog_service
from infrastructure.logger import logger

router = APIRouter(prefix="/api/chat", tags=["Chat"])


class NewSessionRequest(BaseModel):
    user_id: int
    model_name: str = "gpt-3.5-turbo"
    use_kg: bool = False


class ChatRequest(BaseModel):
    user_id: int
    session_id: Optional[str] = None
    query: str
    use_kg: bool = False
    source: str = "web"


class ClearRequest(BaseModel):
    user_id: str | int
    session_id: str


class RenameRequest(BaseModel):
    user_id: str | int
    session_id: str
    new_name: str


@router.post("/start")
async def start(request: NewSessionRequest):
    """ 创建新会话 """
    model_name = request.model_name or "gpt-3.5-turbo"

    session_id = dialog_service.new_session(
        user_id=request.user_id,
        model_name=model_name,
        use_kg=request.use_kg or False,
    )
    logger.info(f"[ChatAPI] 新会话创建 user={request.user_id}, session={session_id}")

    return {
        "ok": True,
        "data": {
            "session_id": session_id,
        },
        "error": None,
    }

@router.post("/")
async def chat(request: ChatRequest):
    """ 标准聊天接口 """
    user_id = request.user_id
    use_kg = request.use_kg or False
    session_id = request.session_id or dialog_service.new_session(user_id=user_id, use_kg=use_kg)

    reply = bridge.handle_message(query=request.query,
                                  session_id=session_id,
                                  user_id=user_id,
                                  use_kg=request.use_kg,
                                  source=request.source)

    # return {"ok": True, "data": reply.model_dump(), "error": None}

    return success(reply)

@router.get("/history")
async def get_chat_history(user_id: int = Query(...), session_id: str = Query(...)):
    """ 获取指定用户的会话历史记录 """

    messages = dialog_service.get_messages(user_id=user_id, session_id=session_id)

    return {"ok": True, "data": {"messages": messages}, "error": None}


@router.get("/sessions")
async def list_sessions(user_id: int = Query(..., description="用户ID")):
    """ 获取用户所有会话 """

    sessions = dialog_service.list_sessions(user_id=user_id)

    return {"ok": True, "data": {"sessions": sessions}, "error": None}


@router.post("/clear")
async def clear_session(request: ClearRequest):
    dialog_service.clear_session(request.user_id, request.session_id)

    return {"ok": True, "session_id": request.session_id, "error": None}


@router.post("/clear_all")
async def clear_all_sessions(user_id: int = Query(...)):
    """清空用户的全部会话"""
    dialog_service.clear_all_sessions(user_id)
    return {"ok": True, "data": {"user_id": user_id}, "error": None}