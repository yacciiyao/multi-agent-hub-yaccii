# -*- coding: utf-8 -*-
# @File: file_storage_s3.py
# @Author: yaccii
# @Time: 2025-11-22 17:07
# @Description:
import uuid
from typing import Optional, Dict, Any

import boto3
from botocore.exceptions import NoCredentialsError

from domain.enums import AttachmentType
from domain.message import Attachment
from storage.file_storage_base import FStorage


class S3FileStorage(FStorage):
    def __init__(self, bucket_name: str, aws_access_key_id: str, aws_secret_access_key: str,
                 region_name: str = "us-west-1") -> None:
        self.bucket_name = bucket_name
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )

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

        # 目录结构：{user_id}/{session_id}/
        s3_key = f"{user_id}/{session_id}/{attachment_id}_{file_name}"

        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_bytes,
                ContentType=mime_type,
            )

            # 生成可访问的URL
            file_url = f"https://{self.bucket_name}.s3.amazonaws.com/{s3_key}"

            # 返回附件对象
            meta: Dict[str, Any] = {
                "file_name": file_name,
                "mime_type": mime_type,
                "size_bytes": len(file_bytes),
            }

            return Attachment(
                id=attachment_id,
                type=AttachmentType.image,
                url=file_url,
                mime_type=mime_type,
                file_name=file_name,
                size_bytes=len(file_bytes),
                meta=meta,
            )

        except NoCredentialsError:
            raise ValueError("No AWS credentials found for S3 storage.")
        except Exception as e:
            raise ValueError(f"Failed to upload file to S3: {str(e)}")

    def get_file_url(self, attachment_id: str) -> str:
        return f"https://{self.bucket_name}.s3.amazonaws.com/{attachment_id}"
