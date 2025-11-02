# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:51
@Desc:
"""
from typing import Dict, Tuple, Type

from bots.openai_bot import OpenAIBot
from infrastructure.logger import logger


class ModelRegistry:
    """ 模型注册中心 """

    def __init__(self):
        self._factories: Dict[str, Tuple[Type, Dict]] = {}
        self._instances: Dict[str, object] = {}
        self._bootstrap_default()

    def _bootstrap_default(self):
        """注册系统默认可用模型"""

        self.register("gpt-3.5-turbo", OpenAIBot, model_name="gpt-3.5-turbo")
        self.register("gpt-4o-mini", OpenAIBot, model_name="gpt-4o-mini")
        self.register("gpt-4o", OpenAIBot, model_name="gpt-4o")

        logger.info(f"[ModelRegistry] 默认模型注册完成: {list(self._factories.keys())}")

    def register(self, name: str, bot_cls: Type, **kwargs):
        """注册模型工厂"""

        self._factories[name] = (bot_cls, kwargs)
        logger.info(f"[ModelRegistry] 注册模型: {name}")

    def get_model(self, name: str):
        """获取模型实例（懒加载）"""

        if name not in self._instances:
            if name not in self._factories:
                raise ValueError(f"未知模型: {name}")

            bot_cls, kwargs = self._factories[name]
            logger.info(f"[ModelRegistry] 初始化模型: {name}")
            self._instances[name] = bot_cls(**kwargs)

        return self._instances[name]

    def get_available_models(self):
        """返回可用模型清单"""

        models = []
        for name, (bot_cls, _) in self._factories.items():
            info = getattr(bot_cls, "models_info", {}).get(name, {})
            models.append({
                "id": name,
                "name": name,
                "desc": info.get("desc", ""),
                "family": getattr(bot_cls, "family", "unknown"),
            })

        return models


_model_registry = None


def get_model_registry() -> ModelRegistry:
    """安全获取模型注册中心单例"""

    global _model_registry
    if _model_registry is None:
        _model_registry = ModelRegistry()
    return _model_registry
