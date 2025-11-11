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

from app.routers import bots_router, sessions_router, messages_router, rag_router
from infrastructure.config_manager import config
from infrastructure.storage_manager import storage_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.load()
    await storage_manager.init()

    if not hasattr(app, "state"):
        app.state = State()

    app.state.config = config
    app.state.storage = storage_manager.get()

    try:
        yield
    finally:
        # 关闭资源（连接池、线程池等）
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
    app = FastAPI(title="multi-agent-hub", lifespan=lifespan)
    app.include_router(bots_router.router, prefix="/bots", tags=["models"])
    app.include_router(sessions_router.router, prefix="/sessions", tags=["sessions"])
    app.include_router(messages_router.router, prefix="/messages", tags=["messages"])
    app.include_router(rag_router.router, prefix="/rag", tags=["rag"])

    # 静态文件
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(BASE_DIR, "../web/static")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
