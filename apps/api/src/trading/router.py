"""
Trading REST API — orders, portfolio, positions, PnL, replay, options chain.

B1 safety chain on every order submission (in order):
  1. Kill switch check   — reject if halted (Redis+Supabase, fail-safe halted)
  2. Shadow mode check   — intercept and log if shadow active
  3. Constraint check    — reject if account tier limits violated
  4. Idempotency check   — reject duplicate; return cached response if available
  5. Engine submit       — validated paper order to broker
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.config import settings
from src.middleware.auth import AuthenticatedUser, get_current_user
from src.trading.account_constraints import (
    AccountConstraintEnforcer,
    get_account_enforcer,
)
from src.trading.idempotency import (
    DuplicateRequestError,
    IdempotencyService,
    IdempotencyServiceUnavailable,
    get_idempotency_service,
)
from src.trading.kill_switch import KillSwitchService, get_kill_switch_service
from src.trading.models import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    RiskConstraints,
    TimeInForce,
)
from src.trading.queue_monitor import get_queue_monitor
from src.trading.shadow import ShadowModeService, get_shadow_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/trading", tags=["trading"])


# ══════════════════════════════════════════════════════════════════════════════
# Dependency: get trading engine (lazy-init, paper mode only)
# ══════════════════════════════════════════════════════════════════════════════

_engine: Any = None
_engine_init_lock: asyncio.Lock | None = None


def _get_init_lock() -> asyncio.Lock:
    global _engine_init_lock
    if _engine_init_lock is None:
        _engine_init_lock = asyncio.Lock()
    return _engine_init_lock


async def _get_engine() -> Any:
    """
    Returns the singleton TradingEngine (paper mode).
    Uses a lock to prevent duplicate initialisation on concurrent first requests.
    Raises 503 if Alpaca credentials are not configured.
    """
    global _engine
    if _engine is not None:
        return _engine

    async with _get_init_lock():
        if _engine is not None:
            return _engine

        alpaca_key = getattr(settings, "alpaca_api_key", "")
        alpaca_secret = getattr(settings, "alpaca_api_secret", "")

        if not alpaca_key or not alpaca_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Alpaca paper trading credentials not configured "
                       "(ALPACA_API_KEY / ALPACA_API_SECRET)",
            )

        import redis.asyncio as aioredis

        from src.services.supabase_service import get_supabase_client
        from src.trading.alpaca import AlpacaPaperBroker
        from src.trading.engine import TradingEngine
        from src.trading.journal import ExecutionJournal
        from src.trading.portfolio import PortfolioManager

        broker = AlpacaPaperBroker(alpaca_key, alpaca_secret)
        await broker.connect()

        client = await get_supabase_client()
        journal = ExecutionJournal(client, ExecutionMode.PAPER)
        portfolio = PortfolioManager(
            account_id="paper",
            initial_cash=100_000.0,
            execution_mode=ExecutionMode.PAPER,
        )
        constraints = RiskConstraints(execution_mode=ExecutionMode.PAPER)

        # Wire position close lock Redis client into engine
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

        _engine = TradingEngine(
            broker,
            journal,
            portfolio,
            constraints,
            position_lock_redis=redis_client,
            queue_monitor=get_queue_monitor(),
        )
        await _engine.start()

    return _engine


# ══════════════════════════════════════════════════════════════════════════════
# Request / Response schemas
# ══════════════════════════════════════════════════════════════════════════════


class OrderSubmitRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    side: OrderSide
    qty: int = Field(ge=1, le=10_000)
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    trail_percent: float | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    idempotency_key: str = Field(
        min_length=1, max_length=64, description="Caller-supplied UUID for deduplication"
    )
    # Optional options metadata
    dte: int | None = Field(default=None, description="Days to expiration (options only)")
    estimated_risk_usd: float = Field(
        default=0.0,
        description="Max loss estimate for the order (premium for options, "
                    "stop-loss distance × qty for equity)",
    )
    num_contracts: int | None = Field(default=None, description="Contract count (options only)")
    strategy_tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderSizeResponse(BaseModel):
    symbol: str
    price: float
    suggested_qty: int
    estimated_value: float
    execution_mode: str


class PortfolioResponse(BaseModel):
    account_id: str
    execution_mode: str
    cash: float
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    position_count: int
    positions: dict[str, Any]


class ReplayRequest(BaseModel):
    symbol: str
    start_date: date
    end_date: date
    initial_cash: float = Field(default=100_000.0, ge=1_000.0, le=10_000_000.0)
    strategy_orders: list[dict[str, Any]] = Field(default_factory=list)
    constraints: RiskConstraints = Field(default_factory=RiskConstraints)


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/status")
async def trading_status(engine: Any = Depends(_get_engine)) -> dict[str, Any]:
    """Returns paper trading system status — no auth required."""
    alpaca_key = getattr(settings, "alpaca_api_key", "")
    queue_status = get_queue_monitor().get_status()
    return {
        "execution_mode": ExecutionMode.PAPER,
        "broker": "alpaca_paper",
        "configured": bool(alpaca_key),
        "live_trading_enabled": False,
        "telemetry": {
            "broker_connected": engine._broker.is_connected,
            "degraded_risk_mode": engine._degraded_risk_mode,
            "queue_status": queue_status["status"],
            "queue_lag_ms": queue_status["avg_lag_ms"],
        },
    }


@router.post("/orders", response_model=dict[str, Any])
async def submit_order(
    body: OrderSubmitRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
    kill_switch: KillSwitchService = Depends(get_kill_switch_service),
    shadow: ShadowModeService = Depends(get_shadow_service),
    idempotency: IdempotencyService = Depends(get_idempotency_service),
) -> dict[str, Any]:
    """
    Submit a paper trade order through the full B1 safety chain.

    Order of checks:
      1. Kill switch  — reject immediately if halted
      2. Shadow mode  — intercept and log if shadow active
      3. Constraints  — enforce account tier hard limits
      4. Idempotency  — reject duplicates; return cached response if available
      5. Engine       — submit to broker
    """
    user_id_str = str(user.user_id)

    # ── Gate 1: Kill switch ──────────────────────────────────────────────────
    if await kill_switch.is_halted(user_id_str):
        log.warning("order_rejected_kill_switch_active", user_id=user_id_str)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trading is halted. An emergency kill switch is active for this account. "
                   "Contact an admin to clear the halt.",
        )

    # ── Gate 2: Shadow mode ──────────────────────────────────────────────────
    if await shadow.is_active(user_id_str):
        intended_price = 0.0
        try:
            quote = await engine._broker.get_quote(body.symbol.upper())
            intended_price = quote.last
        except Exception:
            log.warning("shadow_quote_fetch_failed", symbol=body.symbol)

        shadow_id = await shadow.record_shadow_trade(
            user_id=user_id_str,
            symbol=body.symbol.upper(),
            side=body.side.value,
            qty=body.qty,
            intended_entry_price=intended_price,
            order_type=body.order_type.value,
            intended_idempotency_key=body.idempotency_key,
            metadata={**body.metadata, "submitted_by": user_id_str},
        )
        log.info(
            "shadow_order_intercepted",
            symbol=body.symbol,
            side=body.side,
            qty=body.qty,
            shadow_id=shadow_id,
        )
        return {
            "shadow_mode": True,
            "shadow_trade_id": shadow_id,
            "status": "SHADOW_ACKNOWLEDGED",
            "message": (
                "Shadow mode is active. No order was submitted to the broker. "
                "This trade has been logged for shadow P&L tracking."
            ),
            "symbol": body.symbol.upper(),
            "side": body.side.value,
            "qty": body.qty,
            "intended_price": intended_price,
        }

    # ── Gate 3: Account constraints ──────────────────────────────────────────
    snap = await engine.portfolio()
    enforcer: AccountConstraintEnforcer = get_account_enforcer()
    result = enforcer.check(
        account_size=snap.equity,
        qty=body.qty,
        estimated_risk_usd=body.estimated_risk_usd,
        dte=body.dte,
        strategy_tags=body.strategy_tags or [],
        num_contracts=body.num_contracts,
    )
    if not result.passed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "account_constraint_violation",
                "tier": result.tier,
                "violations": result.violations,
                "effective_max_risk_usd": result.effective_max_risk_usd,
            },
        )

    # ── Gate 4: Idempotency ──────────────────────────────────────────────────
    payload_for_hash = {
        "symbol": body.symbol.upper(),
        "side": body.side.value,
        "qty": body.qty,
        "order_type": body.order_type.value,
        "idempotency_key": body.idempotency_key,
    }
    payload_hash = IdempotencyService.compute_hash(user_id_str, payload_for_hash)

    try:
        await idempotency.check_and_reserve(
            user_id=user_id_str,
            payload_hash=payload_hash,
            request_payload=payload_for_hash,
        )
        # Belt-and-suspenders: check Supabase ledger for post-restart duplicates
        await idempotency.check_restart_scenario(
            user_id=user_id_str,
            payload_hash=payload_hash,
            request_payload=payload_for_hash,
        )
    except DuplicateRequestError as exc:
        if exc.cached_response:
            return exc.cached_response
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate order request rejected (idempotency conflict). "
                   "Use a new idempotency_key to submit a different order.",
        ) from exc
    except IdempotencyServiceUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    # ── Gate 5: Engine submit ────────────────────────────────────────────────
    request = OrderRequest(
        symbol=body.symbol.upper(),
        side=body.side,
        qty=body.qty,
        order_type=body.order_type,
        limit_price=body.limit_price,
        stop_price=body.stop_price,
        trail_percent=body.trail_percent,
        time_in_force=body.time_in_force,
        execution_mode=ExecutionMode.PAPER,
        idempotency_key=body.idempotency_key,
        metadata={**body.metadata, "submitted_by": user_id_str},
    )
    try:
        order = await engine.submit(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    order_dict = order.model_dump()

    # Persist the successful response for idempotency replay on duplicates
    await idempotency.mark_completed(user_id_str, payload_hash, order_dict)

    return order_dict


@router.delete("/orders/{broker_order_id}")
async def cancel_order(
    broker_order_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    order = await engine.cancel(broker_order_id)
    return order.model_dump()


@router.post("/emergency-halt", response_model=dict[str, Any])
async def emergency_halt(
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    """Trigger the in-process emergency halt (RAM). Also activates the durable kill switch."""
    await engine.emergency_halt()
    return {
        "status": "halted",
        "message": "Emergency halt activated. Trading engine locked.",
    }


@router.get("/portfolio", response_model=PortfolioResponse)
async def get_portfolio(
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> PortfolioResponse:
    snap = await engine.portfolio()
    return PortfolioResponse(
        account_id=snap.account_id,
        execution_mode=snap.execution_mode,
        cash=round(snap.cash, 2),
        equity=round(snap.equity, 2),
        unrealized_pnl=round(snap.unrealized_pnl, 2),
        realized_pnl=round(snap.realized_pnl, 2),
        total_pnl=round(snap.total_pnl, 2),
        position_count=snap.position_count,
        positions={
            sym: {
                "qty": p.qty,
                "avg_cost": round(p.avg_cost, 4),
                "current_price": round(p.current_price, 4),
                "market_value": round(p.market_value, 2),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 4),
                "side": p.side,
            }
            for sym, p in snap.positions.items()
        },
    )


@router.get("/pnl", response_model=list[dict[str, Any]])
async def get_pnl_history(
    limit: int = Query(default=50, ge=1, le=500),
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> list[dict[str, Any]]:
    records = await engine._portfolio.pnl_history(limit=limit)
    return [r.model_dump() for r in records]


@router.get("/journal", response_model=list[dict[str, Any]])
async def get_journal(
    limit: int = Query(default=100, ge=1, le=1000),
    symbol: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> list[dict[str, Any]]:
    if symbol:
        entries = await engine._journal.for_symbol(symbol.upper(), limit=limit)
    else:
        entries = await engine._journal.recent(limit=limit)
    return [e.model_dump() for e in entries]


@router.get("/size")
async def suggest_order_size(
    symbol: str = Query(min_length=1, max_length=20),
    price: float = Query(gt=0.0),
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> OrderSizeResponse:
    qty = await engine.size_order(symbol.upper(), price)
    return OrderSizeResponse(
        symbol=symbol.upper(),
        price=price,
        suggested_qty=qty,
        estimated_value=round(qty * price, 2),
        execution_mode=ExecutionMode.PAPER,
    )


@router.get("/quote/{symbol}")
async def get_quote(
    symbol: str,
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    quote = await engine._broker.get_quote(symbol.upper())
    return quote.model_dump()


@router.get("/options/{underlying}", response_model=dict[str, Any])
async def get_options_chain(
    underlying: str,
    expiration: date = Query(..., description="Expiration date YYYY-MM-DD"),
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    chain = await engine._broker.get_options_chain(underlying.upper(), expiration)
    return chain.model_dump()


@router.get("/queue-status")
async def get_queue_status(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return current risk engine queue lag statistics."""
    return get_queue_monitor().get_status()


@router.post("/replay", response_model=dict[str, Any])
async def run_replay(
    body: ReplayRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    """
    Run a deterministic paper trade replay against historical bars.
    """
    from datetime import datetime as dt, timezone

    from src.trading.market_data import MarketDataClient
    from src.trading.replay import ReplaySession

    alpaca_key = getattr(settings, "alpaca_api_key", "")
    alpaca_secret = getattr(settings, "alpaca_api_secret", "")

    if not alpaca_key:
        raise HTTPException(status_code=503, detail="Market data credentials not configured")

    async with MarketDataClient(alpaca_key, alpaca_secret) as md:
        bars = await md.get_bars(
            body.symbol.upper(),
            timeframe="1Day",
            start=dt.combine(body.start_date, dt.min.time()).replace(tzinfo=timezone.utc),
            end=dt.combine(body.end_date, dt.min.time()).replace(tzinfo=timezone.utc),
            limit=500,
        )

    if not bars:
        raise HTTPException(status_code=404, detail="No historical data found for this range")

    constraints = body.constraints
    constraints.execution_mode = ExecutionMode.SIMULATION
    session = ReplaySession(constraints=constraints, initial_cash=body.initial_cash)

    for bar in bars:
        for raw_order in body.strategy_orders:
            if raw_order.get("date") == bar.timestamp.date().isoformat():
                req = OrderRequest(
                    symbol=body.symbol.upper(),
                    side=OrderSide(raw_order["side"]),
                    qty=int(raw_order.get("qty", 1)),
                    order_type=OrderType(raw_order.get("order_type", "market")),
                    limit_price=raw_order.get("limit_price"),
                    execution_mode=ExecutionMode.SIMULATION,
                )
                await session.queue_order(req)
        await session.step(bar)

    return await session.result()


# ══════════════════════════════════════════════════════════════════════════════
# Shadow Mode Endpoints
# ══════════════════════════════════════════════════════════════════════════════


class ShadowStatusResponse(BaseModel):
    is_active: bool
    activated_at: str | None
    days_active: int | None
    gate_passed: bool
    total_shadow_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    hit_rate_pct: float


@router.get("/shadow-status", response_model=ShadowStatusResponse)
async def get_shadow_status(
    user: AuthenticatedUser = Depends(get_current_user),
    shadow: ShadowModeService = Depends(get_shadow_service),
) -> ShadowStatusResponse:
    """Return shadow mode status and P&L summary for the UI banner."""
    summary = await shadow.get_summary(str(user.user_id))
    return ShadowStatusResponse(**summary)


@router.post("/shadow/activate", response_model=dict[str, Any])
async def activate_shadow(
    user: AuthenticatedUser = Depends(get_current_user),
    shadow: ShadowModeService = Depends(get_shadow_service),
) -> dict[str, Any]:
    """Activate shadow mode for the current user (idempotent)."""
    await shadow.activate(str(user.user_id), activated_by=user.email)
    return {
        "status": "activated",
        "message": "Shadow mode is now active. No orders will reach the broker.",
    }


@router.delete("/shadow/deactivate", response_model=dict[str, Any])
async def deactivate_shadow(
    user: AuthenticatedUser = Depends(get_current_user),
    shadow: ShadowModeService = Depends(get_shadow_service),
) -> dict[str, Any]:
    """Deactivate shadow mode. ADMIN ROLE ONLY — requires completed gate review."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shadow mode deactivation requires admin role.",
        )
    try:
        await shadow.deactivate(str(user.user_id), cleared_by=user.email)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    log.warning("shadow_mode_admin_deactivated", user_id=str(user.user_id))
    return {
        "status": "deactivated",
        "message": (
            "Shadow mode cleared. Paper orders will now reach the broker. "
            "Verify all risk guards are active before submitting any orders."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Kill Switch Endpoints
# ══════════════════════════════════════════════════════════════════════════════


class KillSwitchStatusResponse(BaseModel):
    is_halted: bool
    activated_at: str | None
    activated_by: str | None
    reason: str | None
    cleared_at: str | None


@router.get("/kill-switch/status", response_model=KillSwitchStatusResponse)
async def get_kill_switch_status(
    user: AuthenticatedUser = Depends(get_current_user),
    kill_switch: KillSwitchService = Depends(get_kill_switch_service),
) -> KillSwitchStatusResponse:
    """Return the current kill switch state for the authenticated user."""
    ks_status = await kill_switch.get_status(str(user.user_id))
    return KillSwitchStatusResponse(**ks_status)


@router.post("/kill-switch/activate", response_model=dict[str, Any])
async def activate_kill_switch(
    user: AuthenticatedUser = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
    kill_switch: KillSwitchService = Depends(get_kill_switch_service),
) -> dict[str, Any]:
    """
    Activate the durable kill switch.
    Writes to Redis + Supabase and also halts the in-process engine.
    """
    try:
        await kill_switch.activate(
            str(user.user_id),
            activated_by=user.email,
            reason="operator_triggered",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    # Also halt the in-process engine to cancel pending orders
    await engine.emergency_halt()

    return {
        "status": "halted",
        "message": (
            "Kill switch activated. Halt written to Redis and Supabase. "
            "All pending orders cancelled. No new orders accepted until cleared by admin."
        ),
    }


@router.delete("/kill-switch/clear", response_model=dict[str, Any])
async def clear_kill_switch(
    user: AuthenticatedUser = Depends(get_current_user),
    kill_switch: KillSwitchService = Depends(get_kill_switch_service),
) -> dict[str, Any]:
    """Clear the kill switch. ADMIN ROLE ONLY. Writes audit log."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kill switch clearance requires admin role.",
        )
    try:
        await kill_switch.clear(
            str(user.user_id),
            cleared_by=user.email,
            clear_notes="Admin cleared via API",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    log.warning("kill_switch_admin_cleared", user_id=str(user.user_id))
    return {
        "status": "cleared",
        "message": (
            "Kill switch cleared by admin. Halt state removed from Redis and Supabase. "
            "Trading may resume after verification."
        ),
    }
