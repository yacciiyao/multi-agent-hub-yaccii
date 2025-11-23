# -*- coding: utf-8 -*-
# @File: data_storage_base.py
# @Author: yaccii
# @Time: 2025-11-07 11:40
# @Description:
from abc import ABC, abstractmethod
from typing import Optional, List

from domain.message import Message
from domain.session import Session


class DStorage(ABC):

    # ------------- session -------------
    @abstractmethod
    async def create_session(self, session: Session) -> None: ...

    @abstractmethod
    async def rename_session(self, user_id: int, session_id: str, new_name: str) -> None: ...

    @abstractmethod
    async def update_session_flag(self, user_id: int, session_id: str,
                                  rag_enabled: bool, stream_enabled: bool) -> None: ...

    @abstractmethod
    async def get_session(self, user_id: int, session_id: str) -> Optional[Session]: ...

    @abstractmethod
    async def list_sessions(self, user_id: int) -> List[Session]: ...

    @abstractmethod
    async def delete_session(self, user_id: int, session_id: str) -> None: ...

    @abstractmethod
    async def delete_all_sessions(self, user_id: int) -> None: ...

    # ------------- message -------------
    @abstractmethod
    async def append_message(self, message: Message) -> None: ...

    @abstractmethod
    async def get_messages(self, user_id: int, session_id: str) -> List[Message]: ...

    # ------------- default -------------
    @abstractmethod
    async def close(self): ...
