# -*- coding: utf-8 -*-
# @File: file_storage_base.py
# @Author: yaccii
# @Time: 2025-11-22 16:55
# @Description:
from abc import ABC, abstractmethod
from typing import Optional

from domain.message import Attachment


class FStorage(ABC):
    @abstractmethod
    def save_file(
            self,
            user_id: int,
            session_id: str,
            file_bytes: bytes,
            file_name: str,
            mime_type: Optional[str] = None,
    ) -> "Attachment":
        """
        保存文件并返回附件信息。

        :param user_id: 用户ID
        :param session_id: 会话ID
        :param file_bytes: 文件字节内容
        :param file_name: 文件名
        :param mime_type: 文件MIME类型
        :return: 附件对象
        """
        pass

    @abstractmethod
    def get_file_url(self, attachment_id: str) -> str:
        pass
