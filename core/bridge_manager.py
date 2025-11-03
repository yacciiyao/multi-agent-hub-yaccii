# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:51
@Desc: 模型桥接与对话调度
"""
import traceback

from core.dialogue_service import dialog_service
from core.message import Message
from core.model_registry import get_model_registry
from core.reply import Reply
from infrastructure.logger import logger


class BridgeManager:
    """请求调度中心：统一调度普通对话与知识库问答"""

    def __init__(self):
        self.models = get_model_registry()

    def handle_message(
            self, query: str,
            session_id: str,
            user_id: int,
            use_kg: bool = False,
            source: str = "web") -> Reply:
        """ 核心对话处理逻辑 """

        logger.info(f"[BridgeManager] query={query[:40]}, session={session_id}")

        session = dialog_service.get_session(user_id, session_id)
        bot = self.models.get_model(session.model_name)

        history = [{"role": m.role, "content": m.content} for m in session.messages]
        messages = history + [{"role": "user", "content": query}]
        try:
            if use_kg:
                from core.rag_engine import rag_engine
                rag_result = rag_engine.query(query=query, namespace="default", model_name=session.model_name)
                answer = rag_result.get("answer", "未获取到答案。")
                sources = rag_result.get("sources", [])

            else:
                answer = bot.reply_with_context(messages)
                sources = []

            dialog_service.append_message(user_id=user_id, session_id=session_id,
                                          message=Message(role="user", content=query, use_kg=session.use_kg, source=source))
            dialog_service.append_message(user_id=user_id, session_id=session_id,
                                          message=Message(role="assistant", content=answer, use_kg=session.use_kg, source=source))

            # 自动命名会话（首次消息）
            if not session.session_name:
                try:
                    title_prompt = f"请用10个字以内总结以下对话的主题（不要带问号和标点）：{query}"
                    title = bot.reply(title_prompt).strip()
                    if title:
                        dialog_service.rename_session(user_id=user_id, session_id=session_id, session_name=title)
                except Exception as e:
                    logger.warning(f"[Bridge] 自动命名失败: {e}")

            # 响应
            return Reply(
                user_id=user_id,
                session_id=session_id,
                text=answer,
                sources=sources,
            )
        except Exception as e:
            logger.error(f"[Bridge] 异常: {e}\n{traceback.format_exc()}")

            return Reply(
                user_id=user_id,
                session_id=session_id,
                text=f"查询失败: {str(e)}",
                sources=[],
            )


bridge = BridgeManager()
