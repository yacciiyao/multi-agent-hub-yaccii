# -*- coding: utf-8 -*-
"""
@Author: yaccii
@Date: 2025-10-29 14:51
@Desc: RAG 引擎: 统一封装, 文档加载 -> 切分 -> 向量化 -> 向量检索 -> 生成问答
"""
from typing import Optional, Dict

from infrastructure.logger import logger
from knowledge import rag_pipeline


class RAGEngine:
    """ RAG 统一封装层 """

    def __init__(self):
        self.pipeline = rag_pipeline.rag

    def index_file(self, file_path: str, namespace: Optional[str] = None) -> Dict:
        try:
            chunks = self.pipeline.index_file(file_path, namespace)

            return {"ok": True, "chunks": chunks, "namespace": namespace}

        except Exception as e:
            logger.error(f"[RAGEngine] 索引失败: {e}")

            return {"ok": False, "error": str(e)}

    def query(self, query: str, model_name: Optional[str] = None,
              namespace: Optional[str] = None, top_k: int = 5) -> Dict:

        """统一知识问答接口"""
        try:
            result = self.pipeline.query(
                question=query,
                namespace=namespace,
                model_name=model_name,
                top_k=top_k
            )

            return {
                "ok": True,
                "answer": result.get("answer"),
                "sources": result.get("sources", []),
            }

        except Exception as e:
            logger.error(f"[RAGEngine] 查询失败: {e}")

            return {"ok": False, "error": str(e), "text": "检索出错"}


rag_engine = RAGEngine()
