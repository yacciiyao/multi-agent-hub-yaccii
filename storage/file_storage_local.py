# -*- coding: utf-8 -*-
# @File: file_storage_local.py
# @Author: yaccii
# @Time: 2025-11-22 16:58
# @Description:
import os
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

from domain.enums import AttachmentType
from domain.message import Attachment
from storage.file_storage_base import FStorage


class LocalFileStorage(FStorage):
    """
    本地文件存储实现：把文件写到本地磁盘，并生成可用于前端访问的 URL
    """

    def __init__(self, base_dir: str, public_base_url: str) -> None:
        self._base_dir = Path(base_dir)
        self._public_base_url = public_base_url.rstrip("/")

        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save_file(
            self,
            user_id: int,
            session_id: str,
            file_bytes: bytes,
            file_name: str,
            mime_type: Optional[str] = None,
    ) -> Attachment:
        if not file_bytes:
            raise ValueError("empty file content")

        attachment_id = uuid.uuid4().hex

        _, ext = os.path.splitext(file_name or "")
        ext = ext.lower()

        rel_dir = Path(str(user_id)) / session_id
        dir_path = self._base_dir / rel_dir
        dir_path.mkdir(parents=True, exist_ok=True)

        disk_name = f"{attachment_id}{ext}"
        disk_path = dir_path / disk_name

        with open(disk_path, "wb") as f:
            f.write(file_bytes)

        rel_url_path = str(rel_dir / disk_name).replace(os.sep, "/")
        public_url = f"{self._public_base_url}/{rel_url_path}"

        meta: Dict[str, Any] = {
            "file_name": file_name,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
        }

        return Attachment(
            id=attachment_id,
            type=AttachmentType.image,
            url=public_url,
            mime_type=mime_type,
            file_name=file_name,
            size_bytes=len(file_bytes),
            meta=meta,
        )

    def get_file_url(self, attachment_id: str) -> str:
        return f"{self._public_base_url}/{attachment_id}"
