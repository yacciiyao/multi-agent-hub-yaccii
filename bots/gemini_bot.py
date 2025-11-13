# -*- coding: utf-8 -*-
# @File: gemini_bot.py
# @Author: yaccii
# @Time: 2025-11-09 13:13
# @Description: Gemini 模型
import asyncio
from typing import Optional, List, Dict, AsyncIterator, Union

from google import genai
from google.genai import types

from bots.base_bot import BaseBot
from infrastructure.config_manager import config
from infrastructure.mlogger import mlogger


class GeminiBot(BaseBot):
    name = "Gemini"
    bots = {
        "gemini-2.5-pro": {"desc": "高阶推理与复杂任务（旗舰推理）"},
        "gemini-2.5-flash": {"desc": "价格性能最优，通用大规模推理/低延迟"},
        "gemini-2.5-flash-lite": {"desc": "更快更省，极致性价比与高并发场景"},
        # 如需图像生成/编辑再单独接入多模态分支：
        # "gemini-2.5-flash-image": {"desc": "图像生成/编辑（新增 Flash Image 能力）"},
    }

    def __init__(self, bot_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        _config = config.as_dict()
        self.bot_name = bot_name or _config.get("gemini_default_model")

        if self.bot_name not in self.bots:
            mlogger.warning(f"[GeminiBot] unknown model '{self.bot_name}', allowed: {', '.join(self.bots.keys())}")

        api_key = _config.get("gemini_api_key")
        if not api_key:
            raise RuntimeError("Gemini API key is required")

        base_url = _config.get("gemini_base_url", "https://api.openai-proxy.org/google")

        http_options = types.HttpOptions(base_url=base_url) if base_url else None

        self.client = genai.Client(api_key=api_key, vertexai=True, http_options=http_options)

        self.bot_id = self.bot_name if self.bot_name.startswith("models/") else f"models/{self.bot_name}"
        self._gen_config = types.GenerateContentConfig(
            temperature=0.7,
            # top_p=0.95,
            # top_k=40,
            # system_instruction="You are a helpful assistant.",
            # safety_settings=...,   # types.SafetySetting 或列表
            # tools=...,            # 如需函数调用等
        )

    async def aclose(self) -> None:
        return

    @staticmethod
    def _to_messages(messages: List[Dict[str, str]]) -> str:
        output: List[str] = []
        for message in messages:
            role = (message.get("role") or "user").strip()
            text = (message.get("text") or message.get("content") or "").strip()
            if not text:
                continue

            output.append(f"{role}: {text}")
        output.append("assistant:")
        return "\n".join(output)

    async def _chat_completion(self, messages: List[Dict[str, str]]) -> str:
        messages = self._to_messages(messages)

        def _call() -> str:
            response = self.client.models.generate_content(
                model=self.bot_id,
                contents=messages,
                config=self._gen_config,
            )

            try:
                if getattr(response, "text", None):
                    return response.text.strip()
                if getattr(response, "candidates", None):
                    cand = response.candidates[0]
                    parts = getattr(cand, "parts", []) or []
                    return ", ".join(getattr(p, "text", "") or "" for p in parts).strip()

                return ""
            except Exception as e:
                mlogger.warning(f"[GeminiBot] Response error: {e}")
                return ""

        return await asyncio.to_thread(_call)

    async def _chat_stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        messages = self._to_messages(messages)

        async def generator() -> AsyncIterator[str]:
            buffer = ""
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            def _producer():
                try:
                    for event in self.client.models.generate_content_stream(
                            model=self.bot_id,
                            contents=messages,
                            config=self._gen_config,
                    ):
                        try:
                            delta = getattr(event, "text", None)
                            if not delta and getattr(event, "candidates", None):
                                parts = getattr(event.candidates[0].content, "parts", []) or []
                                delta = "".join(getattr(p, "text", "") or "" for p in parts) or None
                            if not delta:
                                continue
                            loop.call_soon_threadsafe(queue.put_nowait, delta)
                        except Exception as ie:
                            loop.call_soon_threadsafe(queue.put_nowait, f"[ERROR]: {ie}")
                except Exception as e:
                    loop.call_soon_threadsafe(queue.put_nowait, f"[ERROR]: {e}")
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            producer = asyncio.create_task(asyncio.to_thread(_producer))
            try:
                while True:
                    delta = await queue.get()
                    if delta is None:
                        break
                    if delta.startswith("[ERROR]"):
                        yield delta
                        break

                    buffer += delta
                    if any(buffer.endswith(x) for x in [".", "!", "?", "\n", "。", "！", "？"]):
                        yield buffer
                        buffer = ""

            finally:
                await producer

            if buffer.strip():
                yield buffer.strip()

        return generator()

    async def chat(self, messages: List[Dict[str, str]], stream: bool = False) -> Union[str, AsyncIterator[str]]:

        if stream:
            return await self._chat_stream(messages)
        return await self._chat_completion(messages)

    async def healthcheck(self) -> bool:
        async def _ping() -> bool:
            def _call() -> bool:
                try:
                    _ = self.client.models.generate_content(
                        model=self.bot_name,
                        contents="ping",
                        config=self._gen_config,
                    )
                    return True
                except Exception as e:
                    mlogger.warning(f"[GeminiBot] ping error: {e}")
                    return False

            return await asyncio.to_thread(_call)

        try:
            return await asyncio.wait_for(_ping(), timeout=5)
        except asyncio.TimeoutError:
            return False
