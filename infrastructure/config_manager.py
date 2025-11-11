# -*- coding: utf-8 -*-
# @File: config_manager.py
# @Author: yaccii
# @Time: 2025-11-07 11:46
# @Description:
import json
import os
from typing import Dict, Any

from infrastructure.mlogger import mlogger


class ConfigManager:
    """
    管理项目配置:
    - 从 config.json 读取配置
    - 提供 as_dict() 导出
    - 支持热加载
    """

    _instance = None
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config.json")

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self.loaded = False

    def load(self):
        """从 JSON 文件加载配置"""
        if self.loaded:
            mlogger.info("[ConfigManager] 配置已加载，跳过。")
            return

        if not os.path.exists(self.CONFIG_PATH):
            raise FileNotFoundError(f"未找到配置文件: {self.CONFIG_PATH}")

        with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
            self._config = json.load(f)

        self.loaded = True
        mlogger.info(f"[ConfigManager] 当前配置: {self._config}")

    def as_dict(self) -> Dict[str, Any]:
        """返回配置字典"""
        if not self.loaded:
            self.load()
        return self._config

    def get(self, key: str, default=None):
        """便捷访问单项"""
        return self._config.get(key, default)


# === 全局单例 ===
config = ConfigManager()