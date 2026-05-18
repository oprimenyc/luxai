"""Trading REST API — orders, portfolio, positions, PnL, replay, options chain."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.config import settings
from src.middleware.auth import get_current_user
from src.trading.models import (
    ExecutionMode,
    OptionsChain,
    Order,
    OrderRequest,
    OrderSide,
    OrderType,
    PortfolioSnapshot,
    PnLRecord,
    RiskConstraints,
    TimeInForce,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/trading", tags=["trading"])


# ══════════════════════════════════════════════════════════════════════════════
# Dependency: get trading engine (lazy-init, paper mode only)
# ══════════════════════════════════════════════════════════════════════════════

_engine: Any = None


async def _get_engine() -> Any:
    """
    Returns the singleton TradingEngine (paper mode).
    Raises 503 if Alpaca credentials are not configured.
    """
    global _engine
    if _engine is not None:
        return _engine

    alpaca_key = getattr(settings, "alpaca_api_key", "")
    alpaca_secret = getattr(settings, "alpaca_api_secret", "")

    if not alpaca_key or not alpaca_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alpaca paper trading credentials not configured (ALPACA_API_KEY / ALPACA_API_SECRET)",
        )

    from src.services.supabase_service import get_supabase_client
    from src.trading.alpaca import AlpacaPaperBroker
    from src.trading.engine import TradingEngine
    from src.trading.journal import ExecutionJournal
    from src.trading.portfolio import PortfolioManager

    broker = AlpacaPaperBroker(alpaca_key, alpaca_secret)
    await broker.connect()

    client = get_supabase_client()
    journal = ExecutionJournal(client, ExecutionMode.PAPER)
    portfolio = PortfolioManager(
        account_id="paper",
        initial_cash=100_000.0,
        execution_mode=ExecutionMode.PAPER,
    )
    constraints = RiskConstraints(execution_mode=ExecutionMode.PAPER)
    _engine = TradingEngine(broker, journal, portfolio, constraints)
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
async def trading_status() -> dict[str, Any]:
    """Returns paper trading system status — no auth required."""
    alpaca_key = getattr(settings, "alpaca_api_key", "")
    return {
        "execution_mode": ExecutionMode.PAPER,
        "broker": "alpaca_paper",
        "configured": bool(alpaca_key),
        "live_trading_enabled": False,
    }


@router.post("/orders", response_model=dict[str, Any])
async def submit_order(
    body: OrderSubmitRequest,
    user_id: str = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    """Submit a paper trade order."""
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
        metadata={**body.metadata, "submitted_by": user_id},
    )
    try:
        order = await engine.submit(request)
        return order.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/orders/{broker_order_id}")
async def cancel_order(
    broker_order_id: str,
    user_id: str = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    order = await engine.cancel(broker_order_id)
    return order.model_dump()


@router.get("/portfolio", response_model=PortfolioResponse)
async def get_portfolio(
    user_id: str = Depends(get_current_user),
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
    user_id: str = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> list[dict[str, Any]]:
    records = await engine._portfolio.pnl_history(limit=limit)
    return [r.model_dump() for r in records]


@router.get("/journal", response_model=list[dict[str, Any]])
async def get_journal(
    limit: int = Query(default=100, ge=1, le=1000),
    symbol: str | None = Query(default=None),
    user_id: str = Depends(get_current_user),
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
    user_id: str = Depends(get_current_user),
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
    user_id: str = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    quote = await engine._broker.get_quote(symbol.upper())
    return quote.model_dump()


@router.get("/options/{underlying}", response_model=dict[str, Any])
async def get_options_chain(
    underlying: str,
    expiration: date = Query(..., description="Expiration date YYYY-MM-DD"),
    user_id: str = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    chain = await engine._broker.get_options_chain(underlying.upper(), expiration)
    return chain.model_dump()


@router.post("/replay", response_model=dict[str, Any])
async def run_replay(
    body: ReplayRequest,
    user_id: str = Depends(get_current_user),
    engine: Any = Depends(_get_engine),
) -> dict[str, Any]:
    """
    Run a deterministic paper trade replay against historical bars.
    The engine fetches OHLCV data and simulates fills against the provided orders.
    """
    from src.trading.market_data import MarketDataClient
    from src.trading.replay import ReplaySession
    from datetime import timezone
    from datetime import datetime as dt

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
