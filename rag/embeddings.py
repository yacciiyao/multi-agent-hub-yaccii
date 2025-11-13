# -*- coding: utf-8 -*-
# @File: embeddings.py
# @Author: yaccii
# @Time: 2025-11-10 11:40
# @Description:
import asyncio
from typing import List, Iterable, TypeVar, Callable, Awaitable, Optional, Sequence

from infrastructure.config_manager import config

T = TypeVar("T")


# ---------------- 工具 ----------------
def _chunks(lst: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(lst), size):
        yield lst[i: i + size]


async def _retry_async(
        fn: Callable[[], Awaitable[T]],
        *,
        tries: int = 3,
        base_delay: float = 0.8,
        max_delay: float = 4.0,
) -> T:
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return await fn()
        except Exception as e:
            last = e
            if attempt >= tries:
                break
            await asyncio.sleep(min(max_delay, base_delay * (2 ** (attempt - 1))))

    raise last


class Embeddings:
    def __init__(self):
        _config = config.as_dict()
        self._config = _config.get("embedding", {}) or {}
        self.provider = self._config.get("provider")
        self.bot = self._config.get("model") or ("text-embedding-3-small" if self.provider == "openai" else "")
        self.batch_size = self._config.get("batch_size") or 64
        self.version: int = int(self._config.get("version") or 1)
        self.dim: Optional[int] = None

        self.openai_api_key = _config.get("openai_api_key")
        self.openai_base_url = _config.get("openai_base_url")
        self.qwen_api_key = _config.get("qwen_api_key")
        self.qwen_base_url = _config.get("qwen_base_url")
        self.deepseek_api_key = _config.get("deepseek_api_key")
        self.deepseek_api_base_url = _config.get("deepseek_api_base_url")

        if self.provider not in {"openai", "qwen", "deepseek"}:
            raise ValueError("Unknown embedding provider")

    async def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        clean = [(t or "") for t in texts]
        if not any(clean):
            return [[0.0, 0.0, 0.0] for _ in clean]

        if self.provider == "openai":
            vectors = await self._encode_openai(clean)
        elif self.provider == "qwen":
            vectors = await self._encode_qwen(clean)
        elif self.provider == "deepseek":
            vectors = await self._encode_deepseek(clean)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

        if vectors and self.dim is None:
            self.dim = len(vectors[0])

        return vectors

    async def _encode_openai(self, texts: Sequence[str]) -> List[List[float]]:
        try:
            from openai import AsyncOpenAI
        except Exception as e:
            raise RuntimeError(f"OpenAI is not installed: {e}")

        client = AsyncOpenAI(api_key=self.openai_api_key, base_url=self.openai_base_url)
        batch_size = max(1, self.batch_size)
        output: List[List[float]] = []
        for batch in _chunks(list(texts), batch_size):
            async def run():
                response = await client.embeddings.create(model=self.bot, input=batch)
                return [d.embedding for d in response.data]

            output.extend(await _retry_async(run, tries=3))

        return output

    async def _encode_qwen(self, texts: List[str]) -> List[List[float]]:
        try:
            from httpx import AsyncClient
        except Exception as e:
            raise RuntimeError(f"QWEN is not installed: {e}")

        bot = self.bot or "text-embedding-v3"
        url = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
        headers = {"Authorization": f"Bearer {self.qwen_api_key}"}

        async def call_one(batch: List[str]) -> List[List[float]]:
            async with AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, json={"model": bot, "input": batch})
                response.raise_for_status()
                data = response.json()
                return [item["embedding"] for item in data.get("data", [])]

        batch_size = max(1, self.batch_size)
        output: List[List[float]] = []
        for batch in _chunks(list(texts), batch_size):
            output.extend(await _retry_async(lambda: call_one(batch), tries=3))

        return output

    async def _encode_deepseek(self, texts: List[str]) -> List[List[float]]:
        try:
            from httpx import AsyncClient
        except Exception as e:
            raise RuntimeError(f"DeepSeek is not installed: {e}")

        bot = self.bot or "deepseek-embedding"
        url = "https://api.deepseek.com/v1/embeddings"
        headers = {"Authorization": f"Bearer {self.deepseek_api_key}"}

        async def call_one(batch: List[str]) -> List[List[float]]:
            async with AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, json={"model": bot, "input": batch})
                response.raise_for_status()
                data = response.json()
                return [item["embedding"] for item in data.get("data", [])]

        batch_size = max(1, self.batch_size)
        output: List[List[float]] = []
        for batch in _chunks(list(texts), batch_size):
            output.extend(await _retry_async(lambda: call_one(batch), tries=3))

        return output
