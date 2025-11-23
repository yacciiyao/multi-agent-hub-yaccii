# -*- coding: utf-8 -*-
# @File: data_storage_manager.py
# @Author: yaccii
# @Time: 2025-11-07 11:38
# @Description:
from typing import Optional

from infrastructure.config_manager import config
from infrastructure.mlogger import mlogger
from storage.data_storage_base import DStorage
from storage.data_storage_memory import MemoryStorage
from storage.data_storage_mysql import MySQLStorage


class StorageManager:
    _instance: Optional["StorageManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.backend: Optional[DStorage] = None
        self.initialized = False

    async def init(self):
        if self.initialized:
            mlogger.info(self.__class__.__name__, "init", msg="success")
            return

        cfg = config.as_dict()
        storage_type = cfg.get("data_storage", "memory").lower()

        if storage_type == "mysql":
            db_cfg = cfg.get("database", {})
            self.backend = MySQLStorage(db_cfg)
        elif storage_type == "memory":
            self.backend = MemoryStorage()
        else:
            raise RuntimeError(f"未知存储类型: {storage_type}")

        await self.backend.init()
        self.initialized = True

    def get(self) -> DStorage:
        if not self.backend:
            raise RuntimeError("Storage backend not initialized.")
        return self.backend

    async def close(self):
        if self.backend:
            try:
                await self.backend.close()
                mlogger.info(self.__class__.__name__, "close", msg="success")
            except Exception as e:
                mlogger.exception(self.__class__.__name__, "close", msg=e)


# === 全局单例 ===
storage_manager = StorageManager()
