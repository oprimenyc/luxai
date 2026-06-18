"""LuxAI FastAPI application entry point."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from src.config import settings
from src.events.bus import event_bus
from src.governance.router import router as governance_router
from src.memory.router import router as memory_router
from src.middleware.logging import LoggingMiddleware
from src.middleware.request_id import RequestIDMiddleware
from src.routers import agents, health, sessions
from src.routers.settings import router as settings_router
from src.security.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from src.telemetry.setup import configure_logging, configure_tracing, instrument_app
from src.websocket.gateway import router as ws_router
from src.websocket.manager import ws_manager
from src.trading.router import router as trading_router
from src.trading.scanner import auto_scanner_loop
from src.workflows.router import router as workflows_router
from src.workbench.router import router as workbench_router

log = structlog.get_logger(__name__)


async def _shadow_trade_monitor_loop() -> None:
    """
    Background task: monitor open shadow trades and close at stop/take-profit.

    Task name: shadow_trade_monitor
    Cancellation: cancelled gracefully in lifespan finally block.
    Timeout: each monitoring cycle has a 10s timeout; hangs are not permanent.

    Exit rules applied per trade:
      - Stop-loss:   -5% from entry price
      - Take-profit: +10% from entry price
    """
    import redis.asyncio as aioredis
    from src.services.supabase_service import get_supabase_client
    from src.trading.shadow import ShadowModeService

    _STOP_LOSS_PCT  = -0.05
    _TAKE_PROFIT_PCT = 0.10
    _POLL_INTERVAL  = 60  # seconds

    log.info("shadow_trade_monitor_started", poll_interval=_POLL_INTERVAL)

    while True:
        try:
            await asyncio.sleep(_POLL_INTERVAL)

            async with asyncio.timeout(10.0):
                redis_client = aioredis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=False,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                supabase = await get_supabase_client()
                svc = ShadowModeService(redis=redis_client, supabase=supabase)

                # Fetch all users with open shadow trades
                try:
                    open_res = await supabase.table("shadow_trades").select(
                        "id, user_id, symbol, side, qty, intended_entry_price"
                    ).eq("status", "open").execute()
                    open_trades = open_res.data or []
                except Exception as exc:
                    log.warning("shadow_monitor_fetch_failed", error=str(exc)[:80])
                    continue

                if not open_trades:
                    continue

                # Group by symbol, fetch current prices via Alpaca market data
                import httpx
                alpaca_key    = getattr(settings, "alpaca_api_key", "")
                alpaca_secret = getattr(settings, "alpaca_api_secret", "")
                if not alpaca_key:
                    continue

                symbols = list({t["symbol"] for t in open_trades})
                prices: dict[str, float] = {}

                async with httpx.AsyncClient(timeout=5.0) as client:
                    for sym in symbols:
                        try:
                            resp = await client.get(
                                f"https://data.alpaca.markets/v2/stocks/{sym}/quotes/latest",
                                headers={
                                    "APCA-API-KEY-ID": alpaca_key,
                                    "APCA-API-SECRET-KEY": alpaca_secret,
                                },
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                q = data.get("quote", {})
                                bid = float(q.get("bp", 0))
                                ask = float(q.get("ap", 0))
                                if bid > 0 and ask > 0:
                                    prices[sym] = (bid + ask) / 2
                        except Exception:
                            pass

                # Evaluate each trade against exit conditions
                for trade in open_trades:
                    sym    = trade["symbol"]
                    price  = prices.get(sym)
                    if price is None or price <= 0:
                        continue

                    entry  = float(trade["intended_entry_price"])
                    if entry <= 0:
                        continue

                    pct_change = (price - entry) / entry

                    reason: str | None = None
                    if pct_change <= _STOP_LOSS_PCT:
                        reason = "stop_loss"
                    elif pct_change >= _TAKE_PROFIT_PCT:
                        reason = "take_profit"

                    if reason:
                        await svc.close_shadow_trade(
                            shadow_id=trade["id"],
                            user_id=trade["user_id"],
                            exit_price=price,
                            close_reason=reason,
                        )

        except asyncio.CancelledError:
            log.info("shadow_trade_monitor_cancelled")
            raise
        except Exception as exc:
            log.error("shadow_trade_monitor_error", error=str(exc)[:120])
            # Continue loop — transient errors should not kill the monitor


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info(
        "luxai_api_starting",
        environment=settings.environment,
        version=settings.app_version,
    )
    ws_manager.start_heartbeat()

    # asyncio.create_task — task: shadow_trade_monitor
    # Cancellation: explicitly cancelled in finally block below.
    # Timeout: each cycle has asyncio.timeout(10.0) internally.
    shadow_monitor: asyncio.Task[None] = asyncio.create_task(
        _shadow_trade_monitor_loop(),
        name="shadow_trade_monitor",
    )

    # asyncio.create_task — task: auto_market_scanner
    # Cancellation: explicitly cancelled in finally block below.
    # Timeout: each scan cycle has asyncio.timeout(120s) internally.
    # Only starts if Alpaca + Tradier keys are configured.
    auto_scanner: asyncio.Task[None] | None = None
    _alpaca_key = getattr(settings, "alpaca_api_key", "")
    _tradier_key = getattr(settings, "tradier_api_key", "")
    # Reserved UUID for the scanner service identity — must be a valid UUID
    # because shadow_trades.user_id is a UUID column.
    _scanner_user = getattr(settings, "scanner_user_id", "00000000-0000-0000-0000-000000000001")
    if _alpaca_key and _tradier_key:
        auto_scanner = asyncio.create_task(
            auto_scanner_loop(
                user_id=_scanner_user,
                tradier_api_key=_tradier_key,
                alpaca_api_key=_alpaca_key,
                alpaca_api_secret=getattr(settings, "alpaca_api_secret", ""),
                redis_url=settings.redis_url,
                tradier_sandbox=getattr(settings, "tradier_sandbox", True),
            ),
            name="auto_market_scanner",
        )
        log.info("auto_scanner_task_created", user_id=_scanner_user)
    else:
        log.warning("auto_scanner_not_started_missing_keys")

    try:
        yield
    finally:
        log.info("luxai_api_shutting_down")
        shadow_monitor.cancel()
        try:
            await shadow_monitor
        except asyncio.CancelledError:
            pass
        if auto_scanner is not None:
            auto_scanner.cancel()
            try:
                await auto_scanner
            except asyncio.CancelledError:
                pass
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

    # ── Routers ──────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(governance_router, prefix="/api/v1")
    app.include_router(workflows_router, prefix="/api/v1")
    app.include_router(trading_router, prefix="/api/v1")
    app.include_router(workbench_router, prefix="/api/v1")
    app.include_router(settings_router, prefix="/api/v1")
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
