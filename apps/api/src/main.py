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
from src.events.bus import event_bus
from src.governance.router import router as governance_router
from src.memory.router import router as memory_router
from src.middleware.logging import LoggingMiddleware
from src.middleware.request_id import RequestIDMiddleware
from src.routers import agents, health, sessions
from src.security.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from src.telemetry.setup import configure_logging, configure_tracing, instrument_app
from src.websocket.gateway import router as ws_router
from src.websocket.manager import ws_manager
from src.workflows.router import router as workflows_router

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info(
        "luxai_api_starting",
        environment=settings.environment,
        version=settings.app_version,
    )
    ws_manager.start_heartbeat()
    try:
        yield
    finally:
        log.info("luxai_api_shutting_down")
        await ws_manager.stop_heartbeat()
        await ws_manager.close_all()


def create_app() -> FastAPI:
    # ── Telemetry ────────────────────────────────────────────────────────
    configure_logging(settings.environment)
    configure_tracing(
        service_name="luxai-api",
        environment=settings.environment,
        otlp_endpoint=getattr(settings, "otlp_endpoint", None),
    )

    app = FastAPI(
        title="LuxAI API",
        description="Multi-agent AI orchestration API",
        version=settings.app_version,
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url="/api/redoc" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
        lifespan=lifespan,
    )

    instrument_app(app)

    # ── Middleware (order matters — outermost first) ──────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        global_rpm=300,
        api_rpm=120,
        auth_rpm=10,
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)

    # ── Observability ────────────────────────────────────────────────────
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/api/health", "/api/metrics"],
    ).instrument(app).expose(app, endpoint="/api/metrics", include_in_schema=False)

    # ── Routers ──────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(governance_router, prefix="/api/v1")
    app.include_router(workflows_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.environment == "development",
        log_config=None,
        access_log=False,
    )
