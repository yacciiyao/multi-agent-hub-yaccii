# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:52
@Desc: OpenAI 聊天接口
"""
from typing import Optional, List, Dict

from openai import OpenAI

from bots.base_bot import BaseBot
from infrastructure.config_manager import conf
from infrastructure.logger import logger


class OpenAIBot(BaseBot):
    """ OpenAI 聊天模型, 通过 model_name 区分不同模型 """

    family = "openai"
    models_info = {
        "gpt-3.5-turbo": {"desc": "经典稳定版，适合常规任务"},
        "gpt-4o-mini": {"desc": "轻量快速版 GPT-4"},
        "gpt-4o": {"desc": "旗舰多模态模型"},
    }

    def __init__(self, model_name: Optional[str] = None):
        cfg = conf().as_dict()

        api_key = cfg.get('openai_api_key')
        if not api_key:
            raise Exception('OpenAI API key not found.')

        base_url = cfg.get('openai_base_url', "https://api.openai.com/v1")

        self.model_name = model_name or (cfg.get('openai_default_model', "gpt-3.5-turbo"))
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def reply(self, query: str, context=None):

        return self.reply_with_context([{"role": "user", "content": query}])

    def reply_with_context(self, messages: List[Dict[str, str]]) -> str:
        try:
            logger.info(f"[OpenAIBot] model_name={self.model_name}, {messages}={len(messages)}")

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
            )

            content = response.choices[0].message.content

            return content

        except Exception as e:
            logger.error(f"[OpenAIBot] 调用失败: {e}")

            return f"模型调用出错: {e}"
