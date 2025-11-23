# -*- coding: utf-8 -*-
# @File: file_service.py
# @Author: yaccii
# @Time: 2025-11-21 21:50
# @Description:
from typing import Optional

import aiohttp

from domain.message import Attachment
from infrastructure.file_storage_manager import get_file_storage


class FileService:
    def __init__(self) -> None:
        self._storage = get_file_storage()

    async def save_uploaded_file(
            self,
            user_id: int,
            session_id: str,
            file_bytes: bytes,
            file_name: str,
            mime_type: Optional[str] = None,
    ) -> Attachment:
        return self._storage.save_file(
            user_id=user_id,
            session_id=session_id,
            file_bytes=file_bytes,
            file_name=file_name,
            mime_type=mime_type,
        )

    async def save_generated_image_from_url(
            self,
            user_id: int,
            session_id: str,
            image_url: str,
            file_name: str = "generated_image.png",
            mime_type: str = "image/png",
    ) -> Attachment:
        file_bytes = await self._download_image(image_url)

        return self._storage.save_file(
            user_id=user_id,
            session_id=session_id,
            file_bytes=file_bytes,
            file_name=file_name,
            mime_type=mime_type,
        )

    async def _download_image(self, image_url: str) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status != 200:
                    raise ValueError(f"Failed to download image from {image_url}, status code {response.status}")
                return await response.read()
