# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:55
@Desc:
"""
import json
import os
from pathlib import Path


class ConfigManager:
    """ 系统配置管理器, 负责加载与访问全局配置 """

    def __init__(self, config_path: str = 'config.json'):
        self.config_path = Path(config_path)
        self._config = {}

    def load(self):
        """ 从文件和环境中加载配置 """

        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)

        else:
            self._config = {}

        # 环境变量覆盖
        for key, value in os.environ.items():
            if key.lower() in self._config:
                self._config[key.lower()] = value

    def get(self, key: str, default=None):
        """ 获取配置值 """

        return self._config.get(key, default)

    def set(self, key: str, value):
        """ 设置配置值 """

        self._config[key] = value

    def as_dict(self):
        return self._config


# 全局配置实例
config = ConfigManager()


def conf():
    """ 统一访问配置 """

    return config
