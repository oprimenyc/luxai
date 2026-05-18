"""Health and diagnostics endpoints."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from src.config import settings

log = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


class ServiceStatus(BaseModel):
    name: str
    status: str  # "ok" | "degraded" | "error"
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded" | "error"
    service: str
    version: str
    environment: str
    uptime_seconds: float
    dependencies: list[ServiceStatus]


class ReadinessResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]


_START_TIME = time.monotonic()


@router.get("/api/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Deep health check — probes all critical dependencies in parallel.
    Returns 200 even if a dependency is degraded (use /api/ready for
    liveness-gate decisions).
    """
    checks = await asyncio.gather(
        _check_supabase(),
        _check_redis(),
        _check_orchestrator(),
        return_exceptions=True,
    )
    dependencies = [
        c if isinstance(c, ServiceStatus) else ServiceStatus(
            name="unknown", status="error", detail=str(c)
        )
        for c in checks
    ]

    overall = "ok"
    if any(d.status == "error" for d in dependencies):
        overall = "degraded"

    return HealthResponse(
        status=overall,
        service="luxai-api",
        version=settings.app_version,
        environment=settings.environment,
        uptime_seconds=round(time.monotonic() - _START_TIME, 1),
        dependencies=dependencies,
    )


@router.get("/api/ready", response_model=ReadinessResponse)
async def readiness_check() -> ReadinessResponse:
    """
    Kubernetes-style readiness probe.
    Returns 200 only when ALL critical dependencies are healthy.
    """
    supabase_ok = await _is_ok(_check_supabase())
    redis_ok = await _is_ok(_check_redis())

    checks = {
        "supabase": supabase_ok,
        "redis": redis_ok,
    }
    return ReadinessResponse(
        ready=all(checks.values()),
        checks=checks,
    )


@router.get("/api/diagnostics")
async def diagnostics() -> dict[str, Any]:
    """
    Full operational diagnostics — memory, websocket stats, event bus stats.
    Only available in non-production environments.
    """
    if settings.environment == "production":
        return {"detail": "diagnostics disabled in production"}

    from src.events.bus import event_bus
    from src.websocket.manager import ws_manager
    import sys
    import os

    return {
        "service": "luxai-api",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
        "python_version": sys.version,
        "pid": os.getpid(),
        "websocket": ws_manager.stats,
        "event_bus": event_bus.stats,
        "trading": {
            "execution_mode": "paper",
            "live_trading_enabled": False,
            "alpaca_configured": bool(getattr(settings, "alpaca_api_key", "")),
        },
    }


# ── Dependency probes ─────────────────────────────────────────────────────────


async def _check_supabase() -> ServiceStatus:
    start = time.monotonic()
    try:
        from src.services.supabase_service import get_supabase_client
        client = get_supabase_client()
        # Lightweight ping — just read the health endpoint
        await asyncio.wait_for(
            client.table("agents").select("id").limit(1).execute(),
            timeout=3.0,
        )
        return ServiceStatus(
            name="supabase",
            status="ok",
            latency_ms=round((time.monotonic() - start) * 1000, 1),
        )
    except asyncio.TimeoutError:
        return ServiceStatus(name="supabase", status="error", detail="timeout")
    except Exception as exc:
        return ServiceStatus(name="supabase", status="error", detail=str(exc)[:120])


async def _check_redis() -> ServiceStatus:
    start = time.monotonic()
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await asyncio.wait_for(r.ping(), timeout=2.0)
        await r.aclose()
        return ServiceStatus(
            name="redis",
            status="ok",
            latency_ms=round((time.monotonic() - start) * 1000, 1),
        )
    except asyncio.TimeoutError:
        return ServiceStatus(name="redis", status="error", detail="timeout")
    except Exception as exc:
        return ServiceStatus(name="redis", status="error", detail=str(exc)[:120])


async def _check_orchestrator() -> ServiceStatus:
    start = time.monotonic()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.orchestrator_url}/health")
            resp.raise_for_status()
        return ServiceStatus(
            name="orchestrator",
            status="ok",
            latency_ms=round((time.monotonic() - start) * 1000, 1),
        )
    except asyncio.TimeoutError:
        return ServiceStatus(name="orchestrator", status="degraded", detail="timeout")
    except Exception as exc:
        return ServiceStatus(name="orchestrator", status="degraded", detail=str(exc)[:120])


async def _is_ok(coro: Any) -> bool:
    result = await coro
    return isinstance(result, ServiceStatus) and result.status == "ok"
