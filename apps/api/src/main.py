"""LuxAI FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from src.config import settings
from src.middleware.logging import LoggingMiddleware
from src.middleware.request_id import RequestIDMiddleware
from src.routers import agents, health, sessions

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info(
        "luxai_api_starting",
        environment=settings.environment,
        version=settings.app_version,
    )
    yield
    log.info("luxai_api_shutting_down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="LuxAI API",
        description="Multi-agent AI orchestration API",
        version=settings.app_version,
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url="/api/redoc" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
        lifespan=lifespan,
    )

    # ── Middleware ──────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)

    # ── Observability ───────────────────────────────────────────────────
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/api/health"],
    ).instrument(app).expose(app, endpoint="/api/metrics", include_in_schema=False)

    # ── Routers ─────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.environment == "development",
        log_config=None,  # structlog handles logging
        access_log=False,
    )
