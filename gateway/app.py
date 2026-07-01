"""
FastAPI 应用入口
---------------
创建 FastAPI 实例，注册路由和中间件，挂载 LangGraph API 路由。
"""
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from gateway.routes import langgraph_routes, page_routes, chat_routes, ontology_routes
from gateway.middleware.auth import AuthMiddleware
from gateway.middleware.logging import LoggingMiddleware
from gateway.middleware.rate_limiter import RateLimiterMiddleware
from common.config.settings import get_settings


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期：启动时初始化数据库连接，关闭时释放。"""
        from infrastructure.db.neo4j import create_driver, close_driver
        from infrastructure.db.sqlite_db import create_sqlite_db
        from common.utils.logger import get_logger

        logger = get_logger(__name__)

        # ── Neo4j ──
        try:
            await create_driver(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password or "neo4j",
            )
            logger.info("Neo4j driver initialized", extra={"uri": settings.neo4j_uri})
        except Exception as e:
            logger.warning("Neo4j driver init failed — ontology API will be unavailable", extra={"error": str(e)})

        # ── SQLite ──
        await create_sqlite_db()
        logger.info("SQLite database initialized")
        app.state.db_backend = "sqlite"

        yield

        await close_driver()

    app = FastAPI(
        title="LangGraph Cluster Gateway",
        description="面向集群部署的 LangChain/LangGraph 智能服务网关",
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 自定义中间件（按逆序添加，即最先添加的最后执行）
    app.add_middleware(RateLimiterMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware)

    # 注册 API 路由
    app.include_router(langgraph_routes.router, prefix="/api/v1")
    app.include_router(chat_routes.router, prefix="/api/v1")
    app.include_router(ontology_routes.router, prefix="/api/v1")

    # 页面路由 & 静态文件
    app.include_router(page_routes.router)
    app.mount("/static", StaticFiles(directory="gateway/static"), name="static")

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "gateway.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
