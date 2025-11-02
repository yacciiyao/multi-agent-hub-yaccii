# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:53
@Desc:
"""
from typing import Any

from infrastructure.config_manager import conf
from infrastructure.logger import logger

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_community.embeddings import HuggingFaceEmbeddings
except ImportError as e:
    raise ImportError(
        "缺少必要依赖，请执行: pip install -U langchain-openai langchain-community"
    ) from e


def get_embedding() -> Any:
    """根据配置返回 Embedding 模型"""

    rag_cfg = conf().get("rag", {})
    provider = rag_cfg.get("embedding", {}).get("provider", "openai")
    model_name = rag_cfg.get("embedding", {}).get("model", "text-embedding-3-small")

    if provider == "openai":
        api_key = conf().get("openai_api_key")
        base_url = conf().get("openai_base_url")

        logger.info(f"[Embeddings] provider={provider} model_name={model_name}")

        return OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model_name)

    elif provider == "sbert":

        logger.info(f"[Embeddings] provider={provider} model_name={model_name}")

        return HuggingFaceEmbeddings(model_name=model_name)

    else:
        raise ValueError(f"[Embeddings] provider={provider} model_name={model_name}")
