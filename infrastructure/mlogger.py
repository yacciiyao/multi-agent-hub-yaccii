# -*- coding: utf-8 -*-
# @File: mlogger.py
# @Author: yaccii
# @Time: 2025-11-07 11:46
# @Description:
# -*- coding: utf-8 -*-
# @File: mlogger.py
# @Author: yaccii
# @Description: 统一结构化日志：mlogger.info("Module", "event", "msg", k=v, ...)
# -*- coding: utf-8 -*-
# @File: mlogger.py
# @Author: yaccii
# @Description: 统一结构化日志：mlogger.info("Module", "event", "msg", k=v, ...)

import logging
from typing import Any, Optional


def _setup_logger(name: str = "Multi-Agent", level: int = logging.INFO) -> logging.Logger:
    """
    初始化底层 logger，只做一次。
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        # 统一全局日志格式：时间 + 等级 + 文本
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)

    return logger


class StructuredLogger:
    """
    统一规范的结构化日志封装。

    使用方式：

        mlogger.info("RagService", "ingest_success",
                     "ingest done",
                     doc_id=doc_id, user_id=user_id, chunks=len(parts))

        mlogger.warning("RagService", "vector_store_not_available",
                        "skip RAG ingest",
                        doc_id=doc_id, user_id=user_id)

        mlogger.exception("MilvusStore", "upsert_failed",
                          doc_id=doc_id, user_id=user_id, error=e)

    约定：
        - module: 模块名（RagService / MilvusStore / QwenBot / Main 等）
        - event: 事件名（ingest_success / search_failed / unknown_model 等）
        - msg:   可选的人类可读补充描述
        - kwargs: 结构化 key=value，会拼到最后，方便检索
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def debug(self, module: str, event: str, msg: Optional[str] = None, **kwargs: Any) -> None:
        self._logger.debug(self._format(module, event, msg, **kwargs))

    def info(self, module: str, event: str, msg: Optional[str] = None, **kwargs: Any) -> None:
        self._logger.info(self._format(module, event, msg, **kwargs))

    def warning(self, module: str, event: str, msg: Optional[str] = None, **kwargs: Any) -> None:
        self._logger.warning(self._format(module, event, msg, **kwargs))

    def error(self, module: str, event: str, msg: Optional[str] = None, **kwargs: Any) -> None:
        self._logger.error(self._format(module, event, msg, **kwargs))

    def exception(self, module: str, event: str, msg: Optional[str] = None, **kwargs: Any) -> None:

        self._logger.exception(self._format(module, event, msg, **kwargs))

    # --------------- 内部工具 -----------------

    @staticmethod
    def _format(module: str, event: str, msg: Optional[str], **kwargs: Any) -> str:
        base = f"[{module}] {event}"
        if msg:
            base += f" {msg}"

        if kwargs:
            parts = []
            for k, v in kwargs.items():
                if isinstance(v, str):
                    v_str = v.replace("\n", "\\n")
                else:
                    v_str = repr(v)
                parts.append(f"{k}={v_str}")
            base += " | " + " ".join(parts)

        return base


# 对外唯一实例
mlogger = StructuredLogger(_setup_logger())
