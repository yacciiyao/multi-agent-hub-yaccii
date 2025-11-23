# -*- coding: utf-8 -*-
# @File: openai_bot.py
# @Author: yaccii
# @Time: 2025-11-09 07:22
# @Description: OpenAI 模型
import asyncio
from typing import Optional, List, Dict, Union, AsyncIterator, Any, cast

from openai import AsyncOpenAI, DefaultAioHttpClient, OpenAIError

from bots.base_bot import BaseBot
from domain.message import Attachment
from infrastructure.config_manager import config
from infrastructure.mlogger import mlogger


class OpenAIBot(BaseBot):
    name = "OpenAI"
    bots = {
        "gpt-4.1-mini": {"desc": "默认推荐：轻量多模态模型，性价比最高，适合日常对话和数据分析", "allow_image": True},
        "gpt-4.1": {"desc": "高质量多模态旗舰模型，适合复杂品牌/项目分析和长篇报告生成", "allow_image": True},
        "o3-mini": {"desc": "强化推理模型，适合复杂打分、排序逻辑和代码类任务", "allow_image": True},
        "gpt-4o-mini": {"desc": "多模态轻量版，成本更低，可作为备选或大规模批量任务模型", "allow_image": True},
    }

    def __init__(self, bot_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        _config = config.as_dict()
        self.bot_name = bot_name or _config.get("openai_default_model")

        if self.bot_name not in self.bots:
            mlogger.warning(self.__class__.__name__, "init", msg="unknown model", model=self.bot_name)

        self.allow_image = bool(self.bots.get(self.bot_name, {}).get("allow_image"))

        api_key = _config.get("openai_api_key")
        if not api_key:
            raise RuntimeError("OpenAI API key is required")

        base_url = _config.get("openai_base_url", "https://api.openai.com/v1")

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=DefaultAioHttpClient())
        self._max_token = _config.get("openai_max_token")

    async def aclose(self) -> None:
        try:
            await self.client.close()
        except Exception as e:
            mlogger.warning(self.__class__.__name__, "close model", msg=e)

    @staticmethod
    def _to_messages(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        output: List[Dict[str, Any]] = []
        for message in messages:
            role = (message.get("role") or "user").strip()
            text = (message.get("text") or message.get("content") or "").strip()
            if not text:
                continue

            part_type = "input_text" if role in ("user", "system") else "output_text"

            output.append({"role": role, "content": [{"type": part_type, "text": text}]})

        return output

    async def _chat_completion(self, messages: List[Dict[str, str]]) -> str:
        messages = self._to_messages(messages)

        response = await self.client.responses.create(
            model=self.bot_name,
            input=cast(Any, messages),
            max_output_tokens=self._max_token
        )

        text = getattr(response, "output_text", None)
        if text:
            return text

        chunks: List[str] = []
        for output in getattr(response, "output", []) or []:
            if getattr(output, "type", "") == "output_text":
                chunks.append(getattr(output, "content", "") or "")

        return "".join(chunks) if chunks else ""

    async def _chat_stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        messages = self._to_messages(messages)
        stream = self.client.responses.stream(
            model=self.bot_name,
            input=cast(Any, messages),
            max_output_tokens=self._max_token
        )

        async def generator() -> AsyncIterator[str]:
            buffer = ""
            async with stream as s:
                async for event in s:
                    event_type = getattr(event, "type", "")
                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", None)
                        if not delta:
                            continue

                        buffer += delta
                        if any(buffer.endswith(x) for x in [".", "!", "?", "\n", "。", "！", "？"]):
                            yield buffer
                            buffer = ""

                    elif event_type == "response.completed":
                        pass

                    elif event_type == "response.error" or event_type == "error":
                        error = getattr(event, "error", None)
                        message = getattr(error, "message", None) if error else None
                        mlogger.error(self.__class__.__name__, "stream generator", msg=message)

                        yield f"[Error]: {message}]"
                        return

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

    async def chat_with_attachments(
            self,
            messages: List[Dict[str, str]],
            attachments: List[Attachment],
            stream: bool = False,
    ) -> Union[str, AsyncIterator[str]]:
        """多模态对话接口"""
        parts: List[Dict[str, Any]] = self._to_messages(messages)

        if attachments:
            # 找到最后一条 user 消息
            last_user_idx: Optional[int] = None
            for idx in range(len(parts) - 1, -1, -1):
                if (parts[idx].get("role") or "").strip() == "user":
                    last_user_idx = idx
                    break

            if last_user_idx is None:
                parts.append({"role": "user", "content": []})
                last_user_idx = len(parts) - 1

            content: List[Dict[str, Any]] = parts[last_user_idx].get("content") or []

            for att in attachments:
                att_type = getattr(att, "type", None)
                if hasattr(att_type, "value"):
                    att_type = att_type.value
                if att_type != "image":
                    continue

                image_url = getattr(att, "url", "") or ""
                if not image_url:
                    continue

                content.append(
                    {
                        "type": "input_image",
                        "image_url": image_url,
                    }
                )

            parts[last_user_idx]["content"] = content

        if stream:
            stream_resp = self.client.responses.stream(
                model=self.bot_name,
                input=cast(Any, parts),
                max_output_tokens=self._max_token,
            )

            async def generator() -> AsyncIterator[str]:
                buffer = ""
                async with stream_resp as s:
                    async for event in s:
                        event_type = getattr(event, "type", "")
                        if event_type == "response.output_text.delta":
                            delta = getattr(event, "delta", None)
                            if not delta:
                                continue

                            buffer += delta
                            if any(buffer.endswith(x) for x in [".", "!", "?", "\n", "。", "！", "？"]):
                                yield buffer
                                buffer = ""

                        elif event_type == "response.completed":
                            pass

                        elif event_type in ("response.error", "error"):
                            error = getattr(event, "error", None)
                            message = getattr(error, "message", None) if error else None
                            mlogger.error(self.__class__.__name__, "stream generator", msg=message)

                            yield f"[Error]: {message}]"
                            return

                    if buffer.strip():
                        yield buffer.strip()

            return generator()

        # 非流式
        response = await self.client.responses.create(
            model=self.bot_name,
            input=cast(Any, parts),
            max_output_tokens=self._max_token,
        )

        text = getattr(response, "output_text", None)
        if text:
            return text

        chunks: List[str] = []
        for output in getattr(response, "output", []) or []:
            if getattr(output, "type", "") == "output_text":
                chunks.append(getattr(output, "content", "") or "")

        return "".join(chunks) if chunks else ""
