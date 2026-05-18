"""
Deterministic paper trading execution engine.

Responsibilities:
- Accept OrderRequest → validate → submit to broker → journal
- Poll order fills → apply to PortfolioManager → journal PnL
- Run risk checks on every price update
- Emit trading events to the platform event bus
- NEVER allow LLM to control exits, sizing, or routing

All execution-critical logic is deterministic Python.
The engine exposes a high-level API for strategies to call.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from src.events.bus import event_bus
from src.events.models import BaseEvent, EventSeverity, EventType
from src.trading.broker import BrokerABC
from src.trading.journal import ExecutionJournal
from src.trading.models import (
    ExecutionMode,
    Fill,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    RiskConstraints,
    RiskTrigger,
)
from src.trading.portfolio import PortfolioManager
from src.trading.risk import (
    DailyLossGuard,
    PositionSizer,
    StopLossEngine,
    TakeProfitEngine,
    TrailingStopEngine,
)

log = structlog.get_logger(__name__)


class TradingEngine:
    """
    Central execution coordinator.

    - All OrderRequests flow through validate() before reaching the broker
    - Fills are polled asynchronously and applied to the PortfolioManager
    - Risk engines are evaluated on every mark-to-market update
    - The engine is permanently locked to ExecutionMode.PAPER

    Usage:
        engine = TradingEngine(broker, journal, portfolio, constraints)
        await engine.start()
        order = await engine.submit(OrderRequest(...))
        await engine.stop()
    """

    _POLL_INTERVAL_SECONDS = 5.0
    _MARK_INTERVAL_SECONDS = 10.0

    def __init__(
        self,
        broker: BrokerABC,
        journal: ExecutionJournal,
        portfolio: PortfolioManager,
        constraints: RiskConstraints,
    ) -> None:
        if constraints.execution_mode != ExecutionMode.PAPER:
            raise ValueError(
                "TradingEngine only supports PAPER execution mode. "
                "Live trading is not enabled."
            )
        self._broker = broker
        self._journal = journal
        self._portfolio = portfolio
        self._constraints = constraints

        self._stop_loss = StopLossEngine(constraints)
        self._take_profit = TakeProfitEngine(constraints)
        self._trailing_stop = TrailingStopEngine(constraints)
        self._sizer = PositionSizer(constraints)

        self._pending_orders: dict[str, Order] = {}  # broker_order_id → Order
        self._poll_task: asyncio.Task[None] | None = None
        self._mark_task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()

        # Daily loss guard — initialised with 100k default; reset on start
        self._loss_guard = DailyLossGuard(constraints, 100_000.0)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start background polling and mark-to-market tasks."""
        snap = await self._portfolio.snapshot()
        self._loss_guard.reset(snap.equity)

        self._shutdown.clear()
        self._poll_task = asyncio.create_task(
            self._poll_fills_loop(), name="trading_engine:poll_fills"
        )
        self._mark_task = asyncio.create_task(
            self._mark_to_market_loop(), name="trading_engine:mark"
        )
        log.info("trading_engine_started", mode=ExecutionMode.PAPER)

    async def stop(self) -> None:
        """Gracefully shut down background tasks."""
        self._shutdown.set()
        for task in (self._poll_task, self._mark_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._poll_task = None
        self._mark_task = None
        log.info("trading_engine_stopped")

    # ── Order Submission ─────────────────────────────────────────────────────

    async def submit(self, request: OrderRequest) -> Order:
        """
        Validate and submit an order.

        Raises:
            ValueError: if constraints are violated
            RuntimeError: if daily loss guard is halted
        """
        self._validate(request)

        snap = await self._portfolio.snapshot()
        if self._loss_guard.check(snap.realized_pnl):
            raise RuntimeError("Daily loss limit reached — trading halted for today")

        order = await self._broker.submit_order(request)
        self._pending_orders[order.broker_order_id] = order
        await self._journal.record_order_submitted(order)

        await self._emit_trade_event(
            EventType.TRADE_ORDER_SUBMITTED,
            symbol=request.symbol,
            payload={
                "order_id": str(order.id),
                "broker_order_id": order.broker_order_id,
                "side": request.side.value,
                "qty": request.qty,
                "order_type": request.order_type.value,
            },
        )

        log.info(
            "order_submitted",
            symbol=request.symbol,
            side=request.side,
            qty=request.qty,
            broker_order_id=order.broker_order_id,
        )
        return order

    async def cancel(self, broker_order_id: str) -> Order:
        order = await self._broker.cancel_order(broker_order_id)
        self._pending_orders.pop(broker_order_id, None)
        await self._journal.record_order_cancelled(order)
        return order

    async def size_order(
        self,
        symbol: str,
        price: float,
    ) -> int:
        """Deterministic position sizing — no LLM involvement."""
        snap = await self._portfolio.snapshot()
        return self._sizer.calculate(snap, symbol, price)

    async def portfolio(self) -> PortfolioSnapshot:
        return await self._portfolio.snapshot()

    # ── Background: Fill Polling ─────────────────────────────────────────────

    async def _poll_fills_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await self._poll_fills()
            except Exception:
                log.exception("fill_poll_error")
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=self._POLL_INTERVAL_SECONDS
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _poll_fills(self) -> None:
        if not self._pending_orders:
            return

        for broker_id in list(self._pending_orders.keys()):
            try:
                updated = await self._broker.get_order(broker_id)
                if updated.status == OrderStatus.FILLED and updated.avg_fill_price:
                    local = self._pending_orders.pop(broker_id, None)
                    fill = Fill(
                        order_id=updated.id,
                        broker_order_id=broker_id,
                        symbol=updated.symbol,
                        side=updated.side,
                        qty=updated.filled_qty,
                        price=updated.avg_fill_price,
                    )
                    pnl_record = await self._portfolio.apply_fill(fill)
                    await self._journal.record_order_filled(updated, fill)

                    if pnl_record:
                        await self._journal.record_pnl(pnl_record)

                    await self._emit_trade_event(
                        EventType.TRADE_ORDER_FILLED,
                        symbol=updated.symbol,
                        payload={
                            "broker_order_id": broker_id,
                            "filled_qty": fill.qty,
                            "avg_fill_price": fill.price,
                            "fill_value": fill.qty * fill.price,
                            "realized_pnl": pnl_record.realized_pnl if pnl_record else None,
                        },
                    )

                elif updated.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
                    self._pending_orders.pop(broker_id, None)
                    if updated.status == OrderStatus.REJECTED:
                        await self._journal.record_order_rejected(updated)
                    else:
                        await self._journal.record_order_cancelled(updated)

            except Exception:
                log.exception("order_poll_error", broker_id=broker_id)

    # ── Background: Mark-to-Market + Risk ────────────────────────────────────

    async def _mark_to_market_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await self._run_risk_checks()
            except Exception:
                log.exception("mark_to_market_error")
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=self._MARK_INTERVAL_SECONDS
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _run_risk_checks(self) -> None:
        snap = await self._portfolio.snapshot()
        if not snap.positions:
            return

        symbols = list(snap.positions.keys())
        try:
            quotes = await self._broker.get_quote(symbols[0]) if len(symbols) == 1 else None
            prices = {}
            for sym in symbols:
                q = await self._broker.get_quote(sym)
                prices[sym] = q.last
        except Exception:
            log.warning("mark_to_market_quote_failed")
            return

        await self._portfolio.mark_to_market(prices)

        triggers: list[RiskTrigger] = []
        for symbol, position in snap.positions.items():
            price = prices.get(symbol)
            if not price:
                continue

            for check in (
                self._stop_loss.check(position, price),
                self._take_profit.check(position, price),
                self._trailing_stop.update_and_check(position, price),
            ):
                if check:
                    triggers.append(check)

        for trigger in triggers:
            await self._handle_risk_trigger(trigger, prices.get(trigger.symbol, 0.0))

    async def _handle_risk_trigger(self, trigger: RiskTrigger, current_price: float) -> None:
        await self._journal.record_risk_trigger(trigger)

        position = await self._portfolio.get_position(trigger.symbol)
        if not position:
            return

        # Deterministic exit order — no LLM involvement
        request = OrderRequest(
            symbol=trigger.symbol,
            side=OrderSide.SELL if position.qty > 0 else OrderSide.BUY,
            qty=abs(position.qty),
            order_type=OrderType.MARKET,
            execution_mode=ExecutionMode.PAPER,
            metadata={"risk_trigger": trigger.action.value, "reason": trigger.reason},
        )
        try:
            await self.submit(request)
            self._trailing_stop.remove(trigger.symbol)
        except Exception:
            log.exception("risk_exit_failed", symbol=trigger.symbol)

        await self._emit_trade_event(
            EventType.TRADE_RISK_TRIGGERED,
            symbol=trigger.symbol,
            severity=EventSeverity.WARNING,
            payload={
                "action": trigger.action.value,
                "reason": trigger.reason,
                "entry_price": trigger.entry_price,
                "trigger_price": trigger.trigger_price,
                "current_price": current_price,
            },
        )

    # ── Validation ───────────────────────────────────────────────────────────

    def _validate(self, request: OrderRequest) -> None:
        if request.execution_mode != ExecutionMode.PAPER:
            raise ValueError("Only PAPER execution mode is allowed")

        if request.qty <= 0:
            raise ValueError("Order qty must be positive")

        if request.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
            if request.limit_price is None:
                raise ValueError(f"{request.order_type} order requires limit_price")

        if request.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            if request.stop_price is None:
                raise ValueError(f"{request.order_type} order requires stop_price")

    # ── Events ───────────────────────────────────────────────────────────────

    async def _emit_trade_event(
        self,
        event_type: EventType,
        symbol: str,
        payload: dict[str, Any],
        severity: EventSeverity = EventSeverity.INFO,
    ) -> None:
        event = BaseEvent(
            type=event_type,
            severity=severity,
            payload={"symbol": symbol, "execution_mode": ExecutionMode.PAPER, **payload},
        )
        await event_bus.publish(event)
