"""Shared test fixtures — no external credentials required."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.trading.models import (
    ExecutionMode,
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    Position,
    Quote,
    RiskConstraints,
    TimeInForce,
)
from src.trading.portfolio import PortfolioManager


# ── Risk constraints fixture ──────────────────────────────────────────────────


@pytest.fixture
def constraints() -> RiskConstraints:
    return RiskConstraints(
        execution_mode=ExecutionMode.PAPER,
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
        trailing_stop_pct=0.03,
        max_daily_loss_pct=0.05,
        max_position_pct=0.20,
        max_portfolio_risk_pct=0.02,
    )


# ── Portfolio fixture ─────────────────────────────────────────────────────────


@pytest.fixture
def portfolio() -> PortfolioManager:
    return PortfolioManager(
        account_id="test-paper",
        initial_cash=100_000.0,
        execution_mode=ExecutionMode.PAPER,
    )


# ── Mock broker ───────────────────────────────────────────────────────────────


@pytest.fixture
def mock_broker() -> MagicMock:
    """Broker that accepts orders and returns them as immediately filled."""
    broker = MagicMock()
    broker.is_connected = True
    broker.execution_mode = ExecutionMode.PAPER

    async def _submit(request: Any) -> Order:
        return Order(
            broker_order_id=str(uuid4()),
            symbol=request.symbol,
            side=request.side,
            qty=request.qty,
            order_type=request.order_type,
            status=OrderStatus.SUBMITTED,
            execution_mode=ExecutionMode.PAPER,
            submitted_at=datetime.now(UTC),
        )

    async def _get_order(broker_id: str) -> Order:
        return Order(
            broker_order_id=broker_id,
            symbol="TEST",
            side=OrderSide.BUY,
            qty=1,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            filled_qty=1,
            avg_fill_price=100.0,
            execution_mode=ExecutionMode.PAPER,
            filled_at=datetime.now(UTC),
        )

    async def _cancel(broker_id: str) -> Order:
        return Order(
            broker_order_id=broker_id,
            symbol="TEST",
            side=OrderSide.BUY,
            qty=1,
            order_type=OrderType.MARKET,
            status=OrderStatus.CANCELLED,
            execution_mode=ExecutionMode.PAPER,
        )

    async def _get_quote(symbol: str) -> Quote:
        return Quote(
            symbol=symbol,
            bid=99.0,
            ask=101.0,
            bid_size=100,
            ask_size=100,
            last=100.0,
            volume=10000,
            timestamp=datetime.now(UTC),
        )

    async def _subscribe_quotes(symbols: list[str], callback: Any) -> None:
        pass

    broker.submit_order = AsyncMock(side_effect=_submit)
    broker.get_order = AsyncMock(side_effect=_get_order)
    broker.cancel_order = AsyncMock(side_effect=_cancel)
    broker.get_quote = AsyncMock(side_effect=_get_quote)
    broker.subscribe_quotes = AsyncMock(side_effect=_subscribe_quotes)
    return broker


# ── Mock journal ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_journal() -> MagicMock:
    journal = MagicMock()
    journal.record_order_submitted = AsyncMock()
    journal.record_order_filled = AsyncMock()
    journal.record_order_cancelled = AsyncMock()
    journal.record_order_rejected = AsyncMock()
    journal.record_pnl = AsyncMock()
    journal.record_risk_trigger = AsyncMock()
    journal.close = AsyncMock()
    return journal


# ── Full engine fixture ───────────────────────────────────────────────────────


@pytest.fixture
async def engine(mock_broker: MagicMock, mock_journal: MagicMock, portfolio: PortfolioManager, constraints: RiskConstraints) -> Any:  # type: ignore[misc]
    from src.trading.engine import TradingEngine

    eng = TradingEngine(mock_broker, mock_journal, portfolio, constraints)
    await eng.start()
    yield eng
    await eng.stop()
