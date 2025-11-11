# -*- coding: utf-8 -*-
# @File: claude_bot.py
# @Author: yaccii
# @Time: 2025-11-09 13:39
# @Description:
import asyncio
from typing import Optional, List, Dict, AsyncIterator, Union, Literal, Tuple

from anthropic import AsyncAnthropic, APIStatusError, AnthropicError
from anthropic.types import MessageParam, TextBlockParam

from bots.base_bot import BaseBot
from infrastructure.config_manager import config
from infrastructure.mlogger import mlogger


class ClaudeBot(BaseBot):
    name = "Claude"
    bots = {
        "claude-3-5-sonnet-latest": {"desc": "旗舰对话/推理"},
        "claude-3-5-haiku-latest": {"desc": "性价比/低延迟"},
        # 如需其它别名，可在这里扩展
    }

    def __init__(self, bot_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        _config = config.as_dict()
        self.bot_name = bot_name or _config.get("claude_default_model")

        if self.bot_name not in self.bots:
            mlogger.warning(f"[ClaudeBot] unknown model '{self.bot_name}', allowed: {', '.join(self.bots.keys())}")

        api_key = _config.get("claude_api_key")
        if not api_key:
            raise RuntimeError("Claude API key is required")

        base_url = _config.get("claude_base_url", "https://api.openai-proxy.org/anthropic")

        self.client = AsyncAnthropic(api_key=api_key, base_url=base_url)

        self._max_token = _config.get("claude_max_token")

    async def aclose(self) -> None:
        return

    @staticmethod
    def _to_messages(messages: List[Dict[str, str]]) -> Tuple[str, List[MessageParam]]:
        system_parts: List[str] = []
        norm: List[MessageParam] = []

        for m in messages:
            role = (m.get("role") or "user").strip()
            text = (m.get("text") or m.get("content") or "").strip()
            if not text:
                continue
            if role == "system":
                system_parts.append(text)
                continue

            role_lit: Literal["user", "assistant"] = "assistant" if role == "assistant" else "user"

            block: TextBlockParam = {"type": "text", "text": text}
            content_list: List[TextBlockParam] = [block]
            message: MessageParam = {"role": role_lit, "content": content_list}
            norm.append(message)

        system_text = "\n".join(system_parts) if system_parts else ""
        return system_text, norm

    async def _chat_completion(self, messages: List[Dict[str, str]]) -> str:
        system, norm = self._to_messages(messages)

        response = await self.client.messages.create(
            model=self.bot_name,
            system=system or None,
            messages=norm,
            max_tokens=self._max_token
        )

        output: List[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", "") == "text":
                output.append(getattr(block, "text", "") or "")

        return "".join(output).strip()

    async def _chat_stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        system, norm = self._to_messages(messages)
        stream = self.client.messages.stream(
            model=self.bot_name,
            messages=norm,
            max_tokens=self._max_token
        )

        async def generator() -> AsyncIterator[str]:
            buffer = ""
            async with stream as s:
                async for ev in s:
                    et = getattr(ev, "type", "")
                    if et == "content_block_delta":
                        delta = getattr(getattr(ev, "delta", None), "text", "") or ""
                        if not delta:
                            continue
                        buffer += delta
                        if any(buffer.endswith(x) for x in [".", "!", "?", "\n", "。", "！", "？"]):
                            yield buffer
                            buffer = ""
                    elif et in ("message_stop", "message_delta"):
                        # 正常结束 / 收尾
                        pass
                    elif et == "error":
                        err = getattr(ev, "error", None)
                        mlogger.error(f"[ClaudeBot] stream error: {err}")
                        yield f"[ERROR]: {err}"
                        return
                # flush 残余
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
        except (APIStatusError, AnthropicError, asyncio.TimeoutError):
            return False
