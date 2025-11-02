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
            model_name: str,
            session_id: str,
            user_id: int,
            use_kg: bool = False,
            namespace: str = None,
            top_k: int = 5) -> Reply:
        """ 核心对话处理逻辑 """

        logger.info(f"[BridgeManager] query={query[:40]}, model_name={model_name}, session={session_id}")

        session = dialog_service.get_session(user_id, session_id)
        if session.model_name != model_name:
            raise ValueError(
                f"会话绑定模型为 {session.model_name}，请求模型为 {model_name}。请新建会话以切换模型。"
            )

        bot = self.models.get_model(session.model_name)
        if not bot:
            raise ValueError(f"未知模型: {model_name}")

        history = [{"role": m.role, "content": m.content} for m in session.messages]

        is_first = len(history) == 0

        messages = history + [{"role": "user", "content": query}]
        try:
            if use_kg:
                from core.rag_engine import rag_engine
                rag_result = rag_engine.query(query=query, namespace=namespace, model_name=model_name, top_k=top_k)
                answer = rag_result.get("answer", "未获取到答案。")
                sources = rag_result.get("sources", [])
                mode = "knowledge"

            else:
                answer = bot.reply_with_context(messages)
                sources = []
                mode = "chat"

            dialog_service.append_message(user_id=user_id, session_id=session_id,
                                          message=Message(role="user", content=query, model_name=model_name, mode=mode))
            dialog_service.append_message(user_id=user_id, session_id=session_id,
                                          message=Message(role="assistant", content=answer, model_name=model_name,
                                                          mode=mode))

            # 自动命名会话（首次消息）
            if is_first and not session.session_name:
                try:
                    title_prompt = f"请用10个字以内总结以下对话的主题（不要带问号和标点）：{query}"
                    title = bot.reply(title_prompt).strip()
                    if title:
                        dialog_service.rename_session(user_id=user_id, session_id=session_id, session_name=title)
                except Exception as e:
                    logger.warning(f"[Bridge] 自动命名失败: {e}")

            # 响应
            return Reply(
                text=answer,
                model_name=model_name,
                user_id=user_id,
                session_id=session_id,
                sources=sources,
                metadata={"mode": "chat"},
            )
        except Exception as e:
            logger.error(f"[Bridge] 异常: {e}\n{traceback.format_exc()}")

            return Reply(
                text=f"❌ 查询失败: {str(e)}",
                model_name=model_name,
                user_id=user_id,
                session_id=session_id,
                sources=[],
                metadata={"mode": "chat"},
            )


bridge = BridgeManager()
