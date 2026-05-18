"""Portfolio state manager — tracks positions, applies fills, computes PnL."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from src.trading.models import (
    AssetClass,
    ExecutionMode,
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    PnLRecord,
    PortfolioSnapshot,
    Position,
)

log = structlog.get_logger(__name__)


class PortfolioManager:
    """
    In-memory portfolio state.

    Thread-safe via asyncio.Lock.

    Responsibilities:
    - Apply fills → update positions and cash
    - Track realized PnL on position close
    - Expose portfolio snapshot for risk engine queries
    - Emit PnL records for the journal

    IMPORTANT: always paper/simulation mode — never routes live orders.
    """

    def __init__(
        self,
        account_id: str,
        initial_cash: float = 100_000.0,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> None:
        self._account_id = account_id
        self._cash = initial_cash
        self._positions: dict[str, Position] = {}
        self._realized_pnl = 0.0
        self._execution_mode = execution_mode
        self._lock = asyncio.Lock()
        self._pnl_records: list[PnLRecord] = []

    # ── Public API ───────────────────────────────────────────────────────────

    async def apply_fill(self, fill: Fill) -> PnLRecord | None:
        """Update portfolio state from a fill. Returns a PnLRecord if a position was closed."""
        async with self._lock:
            return self._apply_fill_locked(fill)

    async def mark_to_market(self, prices: dict[str, float]) -> None:
        """Update current_price on all positions with fresh market prices."""
        async with self._lock:
            for symbol, price in prices.items():
                if symbol in self._positions:
                    self._positions[symbol].current_price = price

    async def snapshot(self) -> PortfolioSnapshot:
        async with self._lock:
            return PortfolioSnapshot(
                account_id=self._account_id,
                execution_mode=self._execution_mode,
                cash=self._cash,
                positions=dict(self._positions),
                realized_pnl=self._realized_pnl,
            )

    async def get_position(self, symbol: str) -> Position | None:
        async with self._lock:
            return self._positions.get(symbol)

    async def pnl_history(self, limit: int = 100) -> list[PnLRecord]:
        async with self._lock:
            return list(reversed(self._pnl_records[-limit:]))

    # ── Internal ─────────────────────────────────────────────────────────────

    def _apply_fill_locked(self, fill: Fill) -> PnLRecord | None:
        symbol = fill.symbol
        existing = self._positions.get(symbol)
        pnl_record: PnLRecord | None = None

        if fill.side == OrderSide.BUY:
            if existing is None:
                # Open new long position
                self._positions[symbol] = Position(
                    symbol=symbol,
                    qty=fill.qty,
                    avg_cost=fill.price,
                    current_price=fill.price,
                    asset_class=AssetClass.EQUITY,
                )
                self._cash -= fill.qty * fill.price + fill.commission
            else:
                if existing.qty > 0:
                    # Add to long position — weighted average cost
                    total_qty = existing.qty + fill.qty
                    existing.avg_cost = (
                        existing.avg_cost * existing.qty + fill.price * fill.qty
                    ) / total_qty
                    existing.qty = total_qty
                    existing.current_price = fill.price
                    self._cash -= fill.qty * fill.price + fill.commission
                else:
                    # Covering a short position
                    close_qty = min(fill.qty, abs(existing.qty))
                    realized = (existing.avg_cost - fill.price) * close_qty - fill.commission
                    self._realized_pnl += realized
                    pnl_record = PnLRecord(
                        symbol=symbol,
                        side="short",
                        qty=close_qty,
                        entry_price=existing.avg_cost,
                        exit_price=fill.price,
                        commission=fill.commission,
                        realized_pnl=realized,
                        realized_pnl_pct=realized / (existing.avg_cost * close_qty)
                        if existing.avg_cost else 0.0,
                        holding_period_seconds=(
                            datetime.now(UTC) - existing.opened_at
                        ).total_seconds(),
                        opened_at=existing.opened_at,
                    )
                    self._pnl_records.append(pnl_record)
                    remaining = existing.qty + close_qty
                    if remaining == 0:
                        del self._positions[symbol]
                    else:
                        existing.qty = remaining
                    self._cash -= fill.qty * fill.price + fill.commission

        else:  # SELL
            if existing is None:
                # Opening a new short position
                self._positions[symbol] = Position(
                    symbol=symbol,
                    qty=-fill.qty,
                    avg_cost=fill.price,
                    current_price=fill.price,
                )
                self._cash += fill.qty * fill.price - fill.commission
            elif existing.qty > 0:
                # Reducing / closing long position
                close_qty = min(fill.qty, existing.qty)
                realized = (fill.price - existing.avg_cost) * close_qty - fill.commission
                self._realized_pnl += realized
                pnl_record = PnLRecord(
                    symbol=symbol,
                    side="long",
                    qty=close_qty,
                    entry_price=existing.avg_cost,
                    exit_price=fill.price,
                    commission=fill.commission,
                    realized_pnl=realized,
                    realized_pnl_pct=realized / (existing.avg_cost * close_qty)
                    if existing.avg_cost else 0.0,
                    holding_period_seconds=(
                        datetime.now(UTC) - existing.opened_at
                    ).total_seconds(),
                    opened_at=existing.opened_at,
                )
                self._pnl_records.append(pnl_record)
                remaining = existing.qty - close_qty
                if remaining == 0:
                    del self._positions[symbol]
                else:
                    existing.qty = remaining
                self._cash += fill.qty * fill.price - fill.commission
            else:
                # Adding to short position
                total_qty = abs(existing.qty) + fill.qty
                existing.avg_cost = (
                    existing.avg_cost * abs(existing.qty) + fill.price * fill.qty
                ) / total_qty
                existing.qty = -total_qty
                existing.current_price = fill.price
                self._cash += fill.qty * fill.price - fill.commission

        log.info(
            "fill_applied",
            symbol=symbol,
            side=fill.side,
            qty=fill.qty,
            price=fill.price,
            cash=round(self._cash, 2),
            realized_pnl=round(realized, 2) if pnl_record else None,
        )
        return pnl_record

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "account_id": self._account_id,
            "cash": round(self._cash, 2),
            "position_count": len(self._positions),
            "realized_pnl": round(self._realized_pnl, 2),
            "execution_mode": self._execution_mode,
        }
