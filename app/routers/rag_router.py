# -*- coding: utf-8 -*-
# @File: rag_router.py
# @Author: yaccii
# @Time: 2025-11-09 22:30
# @Description:
from typing import Optional, List

from fastapi import APIRouter, Query, Path, Form, UploadFile, File
from pydantic import BaseModel, Field

from core.rag_service import RagService
from infrastructure.response import success, failure


def get_rag_service() -> RagService:
    return RagService()


class UploadURLBody(BaseModel):
    user_id: int
    url: str
    title: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    scope: str = "global"  # or "private"


class SearchRagRequest(BaseModel):
    user_id: int
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


router = APIRouter(prefix="/rag", tags=["messages"])


@router.post("/upload-url", summary="从 URL 导入（后台）")
async def upload_rag_from_url(body: UploadURLBody):
    # 临时“管理员”判断：user_id==1 才允许
    if body.user_id != 1:
        return failure(message="Forbidden: admin only")
    rag_service = get_rag_service()
    try:
        doc_id = await rag_service.ingest_from_url(
            user_id=body.user_id,
            url=body.url,
            title=body.title,
            tags=body.tags,
            scope=body.scope,
        )
        return success(data={"doc_id": doc_id})
    except Exception as e:
        return failure(message=str(e))


@router.post("/upload-file", summary="从文件导入（后台）")
async def upload_rag_from_file(
        user_id: int = Form(...),
        title: Optional[str] = Form(None),
        scope: str = Form("global"),
        tags: Optional[str] = Form(None),  # 逗号分隔，或前端多选自行拼装
        file: UploadFile = File(...),
):
    if user_id != 1:
        return failure(message="Forbidden: admin only")

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    rag_service = get_rag_service()
    try:
        doc_id = await rag_service.ingest_from_file(
            user_id=user_id,
            file=file,
            title=title,
            scope=scope,
            tags=tag_list,
        )
        return success(data={"doc_id": doc_id})
    except Exception as e:
        return failure(message=str(e))


@router.get("/docs", summary="列出我的 RAG 文档")
async def list_docs(
        user_id: int = Query(..., description="用户ID"),
):
    rag_service = get_rag_service()
    try:
        data = await rag_service.list_documents(user_id=user_id)
        return success(data=data)
    except Exception as e:
        return failure(message=str(e))


@router.delete("/{doc_id}", summary="删除 RAG 文档（逻辑删除，后台使用）")
async def delete_doc(
        doc_id: str = Path(..., description="文档ID"),
        user_id: int = Query(..., description="操作者用户ID"),
):
    rag_service = get_rag_service()
    try:
        await rag_service.delete_document(user_id=user_id, doc_id=doc_id)
        return success()
    except Exception as e:
        return failure(message=str(e))


@router.post("/search", summary="RAG 语义检索（前台查询）")
async def search_rag(body: SearchRagRequest):
    rag_service = get_rag_service()
    try:
        hits = await rag_service.semantic_search(user_id=body.user_id, query=body.query, top_k=body.top_k)
        return success(data=hits)
    except Exception as e:
        return failure(message=str(e))
