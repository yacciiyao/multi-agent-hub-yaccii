# -*- coding: utf-8 -*-
# @File: main.py
# @Author: yaccii
# @Time: 2025-11-09 11:34
# @Description: 主服务入口, 注册路由、中间件、依赖
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import State
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from app.routers import bot_router, session_router, message_router, rag_router, agent_router, file_router
from infrastructure.config_manager import config
from infrastructure.mlogger import mlogger
from infrastructure.data_storage_manager import storage_manager
from infrastructure.vector_store_manager import get_vector_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.load()
    await storage_manager.init()

    if not hasattr(app, "state"):
        app.state = State()

    app.state.config = config
    app.state.storage = storage_manager.get()

    try:
        vector_store = get_vector_store()
        app.state.vector_store = vector_store
    except Exception as e:
        mlogger.exception("Main", "vector_store_init_failed", msg=e)

    try:
        yield
    finally:
        await storage_manager.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Multi-Agent Hub", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_headers=["*"],
        allow_methods=["*"],
        allow_credentials=True,
    )

    # 路由注册
    app.include_router(bot_router.router)
    app.include_router(session_router.router)
    app.include_router(message_router.router)
    app.include_router(rag_router.router)
    app.include_router(agent_router.router)
    app.include_router(file_router.router)

    # 静态文件路径修改为 /static
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(BASE_DIR, "../web")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="web")

    UPLOAD_DIR = os.path.join(BASE_DIR, "../data/uploads")
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

    # 路由注册
    @app.get("/")
    async def index():
        return JSONResponse({
            "service": "Multi-Agent Hub",
            "docs": "/docs",
        })

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
