"""
Trade replay engine — deterministic replay of execution journal for backtesting
and post-trade analysis.

IMPORTANT: Replay always runs in SIMULATION mode. No orders are routed to any broker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from src.trading.models import (
    Bar,
    ExecutionMode,
    Fill,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PnLRecord,
    PortfolioSnapshot,
    RiskConstraints,
)
from src.trading.portfolio import PortfolioManager
from src.trading.risk import (
    PositionSizer,
    StopLossEngine,
    TakeProfitEngine,
    TrailingStopEngine,
)

log = structlog.get_logger(__name__)


class SimulationFill:
    """Fills an order against a price bar — deterministic, zero network I/O."""

    @staticmethod
    def fill(order: OrderRequest, bar: Bar) -> tuple[bool, float]:
        """
        Simulate fill against a bar.

        Returns (filled, fill_price).

        Fill rules:
        - MARKET: always fills at bar.open (next-bar-open execution)
        - LIMIT buy: fills if bar.low <= limit_price
        - LIMIT sell: fills if bar.high >= limit_price
        - STOP buy: fills if bar.high >= stop_price
        - STOP sell: fills if bar.low <= stop_price
        """
        if order.order_type == OrderType.MARKET:
            return True, bar.open

        if order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and order.limit_price is not None:
                if bar.low <= order.limit_price:
                    return True, min(order.limit_price, bar.open)
            elif order.side == OrderSide.SELL and order.limit_price is not None:
                if bar.high >= order.limit_price:
                    return True, max(order.limit_price, bar.open)

        if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            if order.side == OrderSide.BUY and order.stop_price is not None:
                if bar.high >= order.stop_price:
                    fill_price = order.stop_price
                    if order.limit_price is not None and bar.close > order.limit_price:
                        return False, 0.0
                    return True, fill_price
            elif order.side == OrderSide.SELL and order.stop_price is not None:
                if bar.low <= order.stop_price:
                    fill_price = order.stop_price
                    if order.limit_price is not None and bar.close < order.limit_price:
                        return False, 0.0
                    return True, fill_price

        return False, 0.0


class ReplaySession:
    """
    Single replay session — replays a sequence of order requests against
    historical OHLCV bars.

    Usage:
        session = ReplaySession(constraints, initial_cash=100_000)
        for bar in bars:
            fills = session.step(bar)
        result = session.result()
    """

    def __init__(
        self,
        constraints: RiskConstraints,
        initial_cash: float = 100_000.0,
    ) -> None:
        self._portfolio = PortfolioManager(
            account_id="replay",
            initial_cash=initial_cash,
            execution_mode=ExecutionMode.SIMULATION,
        )
        self._constraints = constraints
        self._stop_loss = StopLossEngine(constraints)
        self._take_profit = TakeProfitEngine(constraints)
        self._trailing = TrailingStopEngine(constraints)
        self._sizer = PositionSizer(constraints)

        self._pending: list[OrderRequest] = []
        self._fills: list[Fill] = []
        self._pnl_records: list[PnLRecord] = []
        self._risk_triggers: list[dict[str, Any]] = []
        self._bars_processed: int = 0

    async def queue_order(self, request: OrderRequest) -> None:
        """Queue an order to be filled on the next step()."""
        self._pending.append(request)

    async def step(self, bar: Bar) -> list[Fill]:
        """
        Advance the simulation by one bar.

        1. Fill pending orders against this bar
        2. Mark positions to bar.close
        3. Run risk checks
        Returns list of fills generated this step.
        """
        step_fills: list[Fill] = []
        still_pending: list[OrderRequest] = []

        for req in self._pending:
            filled, price = SimulationFill.fill(req, bar)
            if filled:
                fill = Fill(
                    order_id=req.id,
                    broker_order_id=str(req.id),
                    symbol=req.symbol,
                    side=req.side,
                    qty=req.qty,
                    price=price,
                    filled_at=bar.timestamp,
                )
                pnl = await self._portfolio.apply_fill(fill)
                step_fills.append(fill)
                self._fills.append(fill)
                if pnl:
                    self._pnl_records.append(pnl)
            else:
                still_pending.append(req)

        self._pending = still_pending

        # Mark positions to close price
        await self._portfolio.mark_to_market({bar.symbol: bar.close})

        # Risk checks
        snap = await self._portfolio.snapshot()
        exit_orders: list[OrderRequest] = []
        for sym, pos in snap.positions.items():
            price = bar.close
            for trigger in [
                self._stop_loss.check(pos, price),
                self._take_profit.check(pos, price),
                self._trailing.update_and_check(pos, price),
            ]:
                if trigger:
                    self._risk_triggers.append({
                        "bar_timestamp": bar.timestamp.isoformat(),
                        "symbol": sym,
                        "action": trigger.action.value,
                        "reason": trigger.reason,
                        "entry_price": trigger.entry_price,
                        "trigger_price": trigger.trigger_price,
                        "current_price": price,
                    })
                    exit_orders.append(OrderRequest(
                        symbol=sym,
                        side=OrderSide.SELL if pos.qty > 0 else OrderSide.BUY,
                        qty=abs(pos.qty),
                        order_type=OrderType.MARKET,
                        execution_mode=ExecutionMode.SIMULATION,
                    ))
                    self._trailing.remove(sym)
                    break  # one trigger per position per bar is enough

        # Process exit orders immediately against this bar
        for req in exit_orders:
            fill = Fill(
                order_id=req.id,
                broker_order_id=str(req.id),
                symbol=req.symbol,
                side=req.side,
                qty=req.qty,
                price=bar.close,
                filled_at=bar.timestamp,
            )
            pnl = await self._portfolio.apply_fill(fill)
            step_fills.append(fill)
            self._fills.append(fill)
            if pnl:
                self._pnl_records.append(pnl)

        self._bars_processed += 1
        return step_fills

    async def result(self) -> dict[str, Any]:
        """Return full replay statistics."""
        snap = await self._portfolio.snapshot()
        total_trades = len(self._pnl_records)
        winning = [r for r in self._pnl_records if r.realized_pnl > 0]
        losing = [r for r in self._pnl_records if r.realized_pnl <= 0]

        win_rate = len(winning) / total_trades if total_trades > 0 else 0.0
        gross_profit = sum(r.realized_pnl for r in winning)
        gross_loss = abs(sum(r.realized_pnl for r in losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        avg_win = (sum(r.realized_pnl for r in winning) / len(winning)) if winning else 0.0
        avg_loss = (sum(r.realized_pnl for r in losing) / len(losing)) if losing else 0.0

        return {
            "bars_processed": self._bars_processed,
            "total_trades": total_trades,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(win_rate, 4),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "total_realized_pnl": round(snap.realized_pnl, 2),
            "unrealized_pnl": round(snap.unrealized_pnl, 2),
            "ending_equity": round(snap.equity, 2),
            "risk_triggers": self._risk_triggers,
            "pnl_records": [r.model_dump() for r in self._pnl_records],
            "fills": [
                {
                    "symbol": f.symbol,
                    "side": f.side,
                    "qty": f.qty,
                    "price": f.price,
                    "filled_at": f.filled_at.isoformat(),
                }
                for f in self._fills
            ],
        }
