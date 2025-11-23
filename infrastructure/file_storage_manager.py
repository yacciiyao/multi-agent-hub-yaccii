# -*- coding: utf-8 -*-
# @File: file_storage_manager.py
# @Author: yaccii
# @Time: 2025-11-22 17:06
# @Description:
from infrastructure.config_manager import config
from storage.file_storage_base import FStorage
from storage.file_storage_local import LocalFileStorage
from storage.file_storage_s3 import S3FileStorage


def get_file_storage() -> FStorage:
    """
    根据配置返回正确的存储实例。
    """
    storage_type = config.get("file_storage", "local")

    if storage_type == "s3":
        # S3存储配置
        bucket_name = config.get("aws_s3_bucket")
        aws_access_key_id = config.get("aws_access_key_id")
        aws_secret_access_key = config.get("aws_secret_access_key")
        region_name = config.get("aws_region", "us-west-1")

        return S3FileStorage(
            bucket_name=bucket_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )

    # 默认返回本地文件存储
    base_dir = config.get("upload_base_dir", "./data/uploads")
    public_base_url = config.get("upload_public_base", "/uploads")

    return LocalFileStorage(base_dir=base_dir, public_base_url=public_base_url)
