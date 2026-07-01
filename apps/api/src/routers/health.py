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
        client = await get_supabase_client()
        # Lightweight ping — probe a table that exists in the production shadow stack.
        await asyncio.wait_for(
            client.table("shadow_mode_config").select("id").limit(1).execute(),
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


# ══════════════════════════════════════════════════════════════════════════════
# /api/v1/health — operational health with trading-specific context
# ══════════════════════════════════════════════════════════════════════════════


class TradingHealthResponse(BaseModel):
    supabase: str           # "ok" | "error"
    redis: str              # "ok" | "error"
    shadow_mode: bool       # True = shadow is active (safe state)
    kill_switch: bool       # True = kill switch is active (trading halted)
    tradier: str            # "ok" | "error"
    alpaca: str             # "ok" | "error"
    version: str
    phase: str
    # Scanner observability — populated from Redis after each daily scan
    last_scan_date: str | None = None     # ISO date of last completed scan
    last_scan_signals: int | None = None  # signals generated on last scan
    scanner_errors_today: int | None = None
    scanner_alert: str | None = None      # set when zero_signal_streak >= 3


@router.get("/api/v1/health", response_model=TradingHealthResponse)
async def trading_health() -> TradingHealthResponse:
    """
    Trading-specific health check. Returns structured status for each
    external service and active safety state flags.

    All checks run in parallel with 3s timeouts. One failure does not
    crash the endpoint — each check degrades independently.
    """
    results = await asyncio.gather(
        _ping_supabase(),
        _ping_redis(),
        _ping_shadow_mode(),
        _ping_kill_switch(),
        _ping_tradier(),
        _ping_alpaca(),
        _ping_scanner_status(),
        return_exceptions=True,
    )

    def _str(r: Any) -> str:
        return r if isinstance(r, str) else "error"

    def _bool(r: Any) -> bool:
        return r if isinstance(r, bool) else True  # fail-safe: assume halted/active

    scanner_status: dict[str, Any] = results[6] if isinstance(results[6], dict) else {}

    return TradingHealthResponse(
        supabase=_str(results[0]),
        redis=_str(results[1]),
        shadow_mode=_bool(results[2]),
        kill_switch=_bool(results[3]),
        tradier=_str(results[4]),
        alpaca=_str(results[5]),
        version=settings.app_version,
        phase="B3-complete",
        last_scan_date=scanner_status.get("last_scan_date"),
        last_scan_signals=scanner_status.get("last_scan_signals"),
        scanner_errors_today=scanner_status.get("scanner_errors_today"),
        scanner_alert=scanner_status.get("scanner_alert"),
    )


async def _ping_supabase() -> str:
    # acreate_client() itself makes network calls — wrap the entire probe in a
    # 4s hard timeout so slow Supabase initialisation cannot block the health
    # endpoint beyond Fly's 5s check window.
    try:
        async with asyncio.timeout(4.0):
            from src.services.supabase_service import get_supabase_client
            client = await get_supabase_client()
            await client.table("shadow_mode_config").select("id").limit(1).execute()
        return "ok"
    except Exception:
        return "error"


async def _ping_redis() -> str:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await asyncio.wait_for(r.ping(), timeout=2.0)
        await r.aclose()
        return "ok"
    except Exception:
        return "error"


async def _ping_shadow_mode() -> bool:
    """
    Return True if shadow mode is operational (always True in this phase).

    Does NOT call ShadowModeService — that service queries shadow_mode_config
    with user_id as a UUID type. Passing the synthetic string 'health-check'
    caused a Postgres UUID syntax error on every poll, leaking connections and
    escalating response latency. This probe uses a raw Redis ping instead.
    Supabase reachability is already verified by _ping_supabase().
    """
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await asyncio.wait_for(r.ping(), timeout=2.0)
        await r.aclose()
        return True  # shadow is always active in this phase
    except Exception:
        return True  # fail-safe: shadow active on any infrastructure failure


async def _ping_kill_switch() -> bool:
    """
    Return True if the kill switch is active (trading halted).

    Does NOT call KillSwitchService — same UUID type mismatch as _ping_shadow_mode.
    Checks Redis directly: if Redis is reachable and no global halt key is set,
    returns False (not halted). Fail-safe: any error → assume halted.
    """
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        # Check for the service-level global halt sentinel written by KillSwitchService
        val = await asyncio.wait_for(r.get("kill_switch:global"), timeout=2.0)
        await r.aclose()
        return val == "1"
    except Exception:
        return True  # fail-safe: assume halted on any infrastructure failure


async def _ping_tradier() -> str:
    """Ping Tradier's clock endpoint (no auth needed, confirms connectivity)."""
    try:
        import httpx
        tradier_key = getattr(settings, "tradier_api_key", "")
        if not tradier_key:
            return "error"
        base = "https://sandbox.tradier.com" if getattr(settings, "tradier_sandbox", True) else "https://api.tradier.com"
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{base}/v1/markets/clock",
                headers={"Authorization": f"Bearer {tradier_key}", "Accept": "application/json"},
            )
            return "ok" if resp.status_code < 400 else "error"
    except Exception:
        return "error"


async def _ping_scanner_status() -> dict[str, Any]:
    """Read last scan metadata from Redis. Returns empty dict on any failure."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        keys = [
            "scanner:last_scan_date",
            "scanner:last_scan_signals",
            "scanner:last_scan_errors",
            "scanner:alert",
        ]
        values = await asyncio.wait_for(r.mget(*keys), timeout=2.0)
        await r.aclose()
        last_date, last_signals, last_errors, alert = values
        return {
            "last_scan_date": last_date,
            "last_scan_signals": int(last_signals) if last_signals is not None else None,
            "scanner_errors_today": int(last_errors) if last_errors is not None else None,
            "scanner_alert": alert,
        }
    except Exception:
        return {}


async def _ping_alpaca() -> str:
    """Ping Alpaca paper account endpoint to confirm credentials and connectivity."""
    try:
        import httpx
        key = getattr(settings, "alpaca_api_key", "")
        secret = getattr(settings, "alpaca_api_secret", "")
        if not key or not secret:
            return "error"
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                "https://paper-api.alpaca.markets/v2/account",
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            )
            return "ok" if resp.status_code == 200 else "error"
    except Exception:
        return "error"
