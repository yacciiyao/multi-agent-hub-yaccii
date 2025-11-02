# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:50
@Desc:
"""
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Query
from pydantic import BaseModel

from infrastructure.logger import logger
from knowledge.rag_pipeline import rag
from knowledge.vector_store import vectorstore

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

UPLOAD_DIR = Path("./data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class KnowledgeQuery(BaseModel):
    question: str
    namespace: str | None = None
    top_k: int | None = None
    model: str | None = None


@router.post("/upload")
async def upload_and_index(file: UploadFile = File(...), namespace: str = Form(None), admin_token: str = Form(...)):
    """ 仅管理员可用, 上传文件并写入指定 namespace 的向量库 """

    from infrastructure.config_manager import conf
    admin_key = conf().get("rag").get("admin_upload_token", None)
    if admin_token != admin_key:
        return {"ok": False, "error": "权限不足"}

    ns = namespace or conf().get("rag", {}).get("default_namespace", "default")

    tmp_path = UPLOAD_DIR / file.filename
    with tmp_path.open("wb") as f:
        f.write(await file.read())

    try:
        chunks = rag.index_file(str(tmp_path), namespace=ns)

        return {"ok": True, "data": {"namespace": ns, "indexed_docs": chunks}, "error": None}

    except Exception as e:
        logger.error(f"[Knowledge] index error: {e}")

        return {"ok": False, "error": str(e)}

    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except:
            pass


@router.post("/query")
async def query_knowledge(query: KnowledgeQuery):
    """ 查询知识库 """

    if not query.question:
        return {"ok": False, "error": "缺少 question 参数"}

    try:
        answer = rag.query(question=query.question, namespace=query.namespace, model_name=query.model,
                           top_k=query.top_k)

        return {"ok": True, "data": answer, "error": None}

    except Exception as e:
        logger.error(f"[Knowledge] query error: {e}")

        return {"ok": False, "error": str(e)}


@router.get("/list")
async def list_namespaces():
    """列出所有知识库"""

    namespaces = vectorstore.list_namespaces()
    counts = {ns: vectorstore.count(ns) for ns in namespaces}

    return {"ok": True, "data": {"namespaces": namespaces, "counts": counts}, "error": None}


@router.delete("/namespace")
async def delete_namespace(namespace: str = Query(...)):
    """删除知识库（危险操作）"""

    try:
        vectorstore.delete_namespace(namespace)

        return {"ok": True, "data": {"namespace": namespace}, "error": None}

    except Exception as e:

        return {"ok": False, "error": str(e)}
