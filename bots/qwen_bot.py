# -*- coding: utf-8 -*-
# @File: qwen_bot.py
# @Author: yaccii
# @Time: 2025-11-09 13:02
# @Description: Qwen 模型
import asyncio
from typing import Optional, List, Dict, cast, Any, AsyncIterator, Union

from openai import AsyncOpenAI, DefaultAioHttpClient, OpenAIError

from bots.base_bot import BaseBot
from infrastructure.config_manager import config
from infrastructure.mlogger import mlogger


class QwenBot(BaseBot):
    name = "Qwen"
    bots = {
        "qwen2.5-7b-instruct": {"desc": "轻量指令模型"},
        "qwen2.5-72b-instruct": {"desc": "高性能指令模型"},
        "qwen3-32b": {"desc": "Qwen3 系列 32B（兼容模式）"},
    }

    def __init__(self, bot_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        _config = config.as_dict()
        self.bot_name = bot_name or _config.get("qwen_default_model")

        if self.bot_name not in self.bots:
            mlogger.warning(f"[QwenBot] unknown model '{self.bot_name}', allowed: {', '.join(self.bots.keys())}")

        api_key = _config.get("qwen_api_key")
        if not api_key:
            raise RuntimeError("Qwen API key is required")

        base_url = _config.get("qwen_base_url", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=DefaultAioHttpClient())
        self._max_token = _config.get("openai_max_token")

    async def aclose(self) -> None:
        try:
            await self.client.close()
        except Exception as e:
            mlogger.warning(f"[QwenBot] Failed to close the QwenBot instance: {e}")

    @staticmethod
    def _to_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        output: List[Dict[str, str]] = []
        for message in messages:
            role = (message.get("role") or "user").strip()
            text = (message.get("text") or message.get("content") or "").strip()
            if not text:
                continue

            output.append({"role": role, "content": text})

        return output

    async def _chat_completion(self, messages: List[Dict[str, str]]) -> str:
        messages = self._to_messages(messages)

        response = await self.client.chat.completions.create(
            model=self.bot_name,
            messages=cast(Any, messages),
            max_tokens=self._max_token,
        )

        if not response.choices:
            return ""

        first = response.choices[0]
        if not getattr(first, "message", None):
            return ""

        return first.message.content or ""

    async def _chat_stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        messages = self._to_messages(messages)
        stream = await self.client.chat.completions.create(
            model=self.bot_name,
            messages=cast(Any, messages),
            max_tokens=self._max_token,
            stream=True
        )

        async def generator() -> AsyncIterator[str]:
            buffer = ""
            async for event in stream:
                try:
                    choice = event.choices[0]
                    delta = getattr(getattr(choice, "delta", None), "content", None)
                    if delta is None:
                        delta = getattr(getattr(choice, "message", None), "content", None)

                    if not delta:
                        continue

                except Exception as e:
                    mlogger.warning(f"[QwenBot] Stream generator error: {e}")
                    continue

                buffer += delta
                if any(buffer.endswith(x) for x in [".", "!", "?", "\n", "。", "！", "？"]):
                    yield buffer
                    buffer = ""

            if buffer.strip():
                yield buffer.strip()

        return generator()

    async def chat(self, messages: List[Dict[str, str]], stream: bool = False) -> Union[str, AsyncIterator[str]]:
        if stream:
            return await self._chat_stream(messages)
        return await self._chat_completion(messages)

    async def healthcheck(self) -> bool:
        try:
            await asyncio.wait_for(self.client.models.list(), timeout=5)
            return True
        except (OpenAIError, asyncio.TimeoutError):
            return False
