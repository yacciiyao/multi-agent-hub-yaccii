# -*- coding: utf-8 -*-
# @File: bot_registry.py
# @Author: yaccii
# @Time: 2025-11-08 18:39
# @Description: 模型注册表
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import List, Dict, Type, Optional

from bots.base_bot import BaseBot
from infrastructure.mlogger import mlogger


class BotRegistry:
    _scanned: bool = False
    _bots: List[Dict[str, str]] = []
    _seen: set[str] = set()
    _class: dict[str, Type[BaseBot]] = {}

    @classmethod
    def _scan_once(cls) -> None:
        if cls._scanned:
            return

        pkg_name = __name__.rsplit(".", 1)[0]
        pkg_path = Path(__file__).resolve().parent
        ignore = {"__init__", "base_bot", "bot_registry"}

        for mod in pkgutil.iter_modules([str(pkg_path)]):
            if mod.name in ignore or mod.name.startswith("_"):
                continue

            try:
                module = importlib.import_module(f"{pkg_name}.{mod.name}")
            except Exception as e:
                mlogger.error(f"{pkg_name}.{mod.name} failed to import: {e}")
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if obj is BaseBot or not issubclass(obj, BaseBot):
                    continue
                cls._register_bot_class(obj)

        cls._bots.sort(key=lambda m: (m["family"], m["bot_name"]))
        cls._scanned = True

    @classmethod
    def _register_bot_class(cls, bot_cls: Type[BaseBot]) -> None:
        family = getattr(bot_cls, "name", None) or "unknown"
        bots = getattr(bot_cls, "bots", None)
        if not isinstance(bots, dict) or not bots:
            return

        for bot_name, meta in bots.items():
            if not isinstance(bot_name, str) or not bot_name or bot_name in cls._seen:
                continue
            desc = ""
            if isinstance(meta, dict):
                desc = meta.get("desc", "") or ""
            elif isinstance(meta, str):
                desc = meta
            cls._bots.append({"family": str(family), "bot_name": bot_name, "desc": desc})
            cls._seen.add(bot_name)
            cls._class[bot_name] = bot_cls

    @classmethod
    def list_bots(cls) -> List[Dict[str, str]]:
        cls._scan_once()
        return list(cls._bots)

    @classmethod
    def get(cls, bot_name: str) -> Optional[BaseBot]:
        cls._scan_once()
        bot_cls = cls._class.get(bot_name)
        if not bot_cls:
            return None

        try:
            sig = inspect.signature(bot_cls)
            if "model" in sig.parameters:
                return bot_cls(bot_name=bot_name)
            if "bot_name" in sig.parameters:
                return bot_cls(bot_name=bot_name)

            try:
                return bot_cls(bot_name)  # type: ignore[call-arg]
            except Exception:
                return bot_cls()  # type: ignore[call-arg]
        except Exception as e:
            mlogger.error(f"Instantiate bot '{bot_name}' failed: {e}")
            return None
