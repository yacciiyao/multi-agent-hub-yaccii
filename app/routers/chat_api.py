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
    session_name: Optional[str] = None
    model_name: str = "gpt-3.5-turbo"
    use_kg: bool = False
    namespace: Optional[str] = "default"


class ChatRequest(BaseModel):
    user_id: int
    session_id: Optional[str] = None
    query: str
    model: str
    use_kg: bool = False
    namespace: Optional[str] = "default"


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

    session_name = request.session_name

    session_id = dialog_service.new_session(
        user_id=request.user_id,
        session_name=request.session_name,
        model_name=request.model_name,
        use_kg=request.use_kg or False,
        namespace=request.namespace or "default",
    )
    logger.info(f"[ChatAPI] 新会话创建 user={request.user_id}, session={session_id}")

    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "session_name": session_name,
            "model_name": request.model_name,
            "use_kg": request.use_kg,
            "namespace": request.namespace,
        },
        "error": None,
    }

@router.post("/")
async def chat(request: ChatRequest):
    """ 标准聊天接口 """
    user_id = request.user_id
    model_name = request.model or "gpt-3.5-turbo"
    use_kg = request.use_kg or False
    session_id = request.session_id or dialog_service.new_session(user_id=user_id, model_name=model_name, use_kg=use_kg)

    dialog_service.update_session_config(user_id=user_id, session_id=session_id, use_kg=use_kg, namespace=request.namespace)

    reply = bridge.handle_message(query=request.query,
                                  model_name=model_name,
                                  session_id=session_id,
                                  user_id=user_id,
                                  use_kg=request.use_kg,
                                  namespace=request.namespace or "default")

    return {"ok": True, "data": reply.model_dump(), "error": None}


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