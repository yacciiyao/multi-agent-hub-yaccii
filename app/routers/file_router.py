# -*- coding: utf-8 -*-
# @File: file_router.py
# @Author: yaccii
# @Time: 2025-11-21 21:50
# @Description:
from typing import Dict, Any

from fastapi import APIRouter, Form, File, UploadFile, HTTPException
from starlette import status

from core.file_service import FileService
from infrastructure.mlogger import mlogger

router = APIRouter(prefix="/files", tags=["files"])

_file_service = FileService()


@router.post("/upload")
async def upload_file(
        user_id: int = Form(...),
        session_id: str = Form(...),
        file: UploadFile = File(...),
) -> Dict[str, Any]:
    try:
        file_bytes = await file.read()

        attachment = await _file_service.save_uploaded_file(
            user_id=user_id,
            session_id=session_id,
            file_bytes=file_bytes,
            file_name=file.filename or "upload",
            mime_type=file.content_type,
        )

        attachment_dict = (
            attachment.model_dump()
            if hasattr(attachment, "model_dump")
            else dict(attachment)
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        mlogger.error(f"File upload failed: {str(e)}")  # 记录日志
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="文件上传失败",
        )

    return {
        "success": True,
        "data": {
            "attachment": attachment_dict,
        },
    }
