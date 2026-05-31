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
    Quote,
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
from src.trading.queue_monitor import QueueMonitor, get_queue_monitor

log = structlog.get_logger(__name__)


class TradingEngine:
    """
    Central execution coordinator.

    - All OrderRequests flow through validate() before reaching the broker
    - Fills are polled asynchronously and applied to the PortfolioManager
    - Risk engines are evaluated on every mark-to-market update
    - The engine is permanently locked to ExecutionMode.PAPER
    - start() MUST be called before submit(); raises if not

    Usage:
        engine = TradingEngine(broker, journal, portfolio, constraints)
        await engine.start()
        order = await engine.submit(OrderRequest(...))
        await engine.stop()
    """

    _POLL_INTERVAL_SECONDS = 5.0
    _MARK_INTERVAL_SECONDS = 1.0

    def __init__(
        self,
        broker: BrokerABC,
        journal: ExecutionJournal,
        portfolio: PortfolioManager,
        constraints: RiskConstraints,
        position_lock_redis: Any | None = None,
        queue_monitor: QueueMonitor | None = None,
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

        # Optional Redis client for distributed position close locks.
        # When None, position locks are skipped (backward-compat for tests).
        self._position_lock_redis = position_lock_redis

        # Queue lag monitor — shared singleton injected or created here.
        self._queue_monitor: QueueMonitor = queue_monitor or get_queue_monitor()

        self._pending_orders: dict[str, Order] = {}  # broker_order_id → Order
        self._poll_task: asyncio.Task[None] | None = None
        self._mark_task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()
        self._emergency_lock: bool = False
        self._started: bool = False

        self._idempotency_cache: dict[str, datetime] = {}
        self._idempotency_lock = asyncio.Lock()

        self._quote_cache: dict[str, Quote] = {}
        self._subscribed_symbols: set[str] = set()
        self._subscription_lock = asyncio.Lock()

        # Per-symbol in-flight guard: prevents stacking concurrent risk evaluations
        # for the same symbol when WebSocket quotes arrive faster than evaluations complete.
        self._risk_eval_in_flight: set[str] = set()

        self._degraded_risk_mode = False

        # DailyLossGuard is None until start() fetches actual portfolio equity.
        # submit() will raise if called before start().
        self._loss_guard: DailyLossGuard | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start background polling and mark-to-market tasks."""
        snap = await self._portfolio.snapshot()

        # Initialise loss guard against ACTUAL starting equity, not a hardcoded default.
        self._loss_guard = DailyLossGuard(self._constraints, snap.equity)

        self._shutdown.clear()
        self._poll_task = asyncio.create_task(
            self._poll_fills_loop(), name="trading_engine:poll_fills"
        )
        self._mark_task = asyncio.create_task(
            self._mark_to_market_loop(), name="trading_engine:mark"
        )
        self._started = True
        log.info("trading_engine_started", mode=ExecutionMode.PAPER, starting_equity=snap.equity)

    async def stop(self) -> None:
        """Gracefully shut down background tasks and drain the journal queue."""
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
        self._started = False

        # Drain journal before exit so no audit entries are lost.
        await self._journal.close()

        log.info("trading_engine_stopped")

    async def emergency_halt(self) -> None:
        """Immediately cancel all pending orders and lock the engine."""
        self._emergency_lock = True
        log.critical("emergency_halt_triggered", pending_count=len(self._pending_orders))

        cancel_tasks = [
            self.cancel(broker_id) for broker_id in list(self._pending_orders.keys())
        ]
        if cancel_tasks:
            results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    log.error("emergency_cancel_failed", error=str(res))

        await self._emit_trade_event(
            EventType.TRADE_RISK_TRIGGERED,
            symbol="GLOBAL",
            severity=EventSeverity.CRITICAL,
            payload={"action": "EMERGENCY_HALT", "reason": "Operator triggered global kill-switch"},
        )

    # ── Order Submission ─────────────────────────────────────────────────────

    async def submit(self, request: OrderRequest) -> Order:
        """
        Validate and submit an order.

        Raises:
            RuntimeError: if engine not started, emergency lock engaged,
                          degraded risk mode (non-exit orders), or daily loss triggered
            ValueError: if risk constraints are violated
        """
        if not self._started:
            raise RuntimeError("TradingEngine.start() must be called before submitting orders")

        if self._emergency_lock:
            raise RuntimeError("Trading engine is locked down due to Emergency Halt")

        is_risk_exit = "risk_trigger" in request.metadata
        if self._degraded_risk_mode and not is_risk_exit:
            raise RuntimeError(
                "New orders are blocked during Degraded Risk Mode (stale quotes). "
                "Risk exits are still permitted."
            )

        if request.idempotency_key:
            async with self._idempotency_lock:
                now = datetime.now(UTC)
                expired = [
                    k for k, v in self._idempotency_cache.items()
                    if (now - v).total_seconds() > 3600
                ]
                for k in expired:
                    del self._idempotency_cache[k]

                if request.idempotency_key in self._idempotency_cache:
                    raise RuntimeError("Duplicate order request rejected (idempotency conflict)")

                self._idempotency_cache[request.idempotency_key] = now

        self._validate(request)

        # loss_guard is always set after start(), but guard defensively
        assert self._loss_guard is not None
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
                    self._pending_orders.pop(broker_id, None)
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

                elif updated.status in (
                    OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED
                ):
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

    async def _on_quote_update(self, quote: Quote) -> None:
        """Callback for WebSocket streaming — fires on every quote tick."""
        self._quote_cache[quote.symbol] = quote

        # Record tick receipt for queue lag monitoring.
        await self._queue_monitor.record_tick_received(quote.symbol)

        # Guard against stacking concurrent risk evaluations for the same symbol.
        # If an evaluation is already in flight, the updated quote in _quote_cache
        # will be used when that in-flight evaluation reads it — no data is lost.
        if quote.symbol not in self._risk_eval_in_flight:
            self._risk_eval_in_flight.add(quote.symbol)
            task = asyncio.create_task(
                self._evaluate_risk_for_symbol(quote.symbol, quote.last),
                name=f"risk_eval:{quote.symbol}",
                # Cancellation: task is discarded on engine.stop() via _shutdown event.
                # If cancelled mid-evaluation, the quote cache retains the last price.
            )
            task.add_done_callback(
                lambda _: self._risk_eval_in_flight.discard(quote.symbol)
            )

    async def _evaluate_risk_for_symbol(self, symbol: str, price: float) -> None:
        snap = await self._portfolio.snapshot()
        position = snap.positions.get(symbol)
        if not position:
            await self._queue_monitor.record_tick_processed(symbol)
            return

        triggers: list[RiskTrigger] = []
        for check in (
            self._stop_loss.check(position, price),
            self._take_profit.check(position, price),
            self._trailing_stop.update_and_check(position, price),
        ):
            if check:
                triggers.append(check)

        for trigger in triggers:
            await self._handle_risk_trigger(trigger, price)

        # Record tick processing complete — lag is now measurable.
        await self._queue_monitor.record_tick_processed(symbol)

    async def _run_risk_checks(self) -> None:
        snap = await self._portfolio.snapshot()
        if not snap.positions:
            return

        symbols = list(snap.positions.keys())
        now = datetime.now(UTC)

        # Sync WebSocket subscriptions under a lock to prevent concurrent
        # subscribe calls from racing if _run_risk_checks is called re-entrantly.
        async with self._subscription_lock:
            if set(symbols) != self._subscribed_symbols:
                self._subscribed_symbols = set(symbols)
                await self._broker.subscribe_quotes(symbols, self._on_quote_update)

        prices: dict[str, float] = {}
        for sym in symbols:
            q = self._quote_cache.get(sym)
            if q and (now - q.timestamp).total_seconds() < 15.0:
                prices[sym] = q.last
            else:
                try:
                    q = await self._broker.get_quote(sym)
                    self._quote_cache[sym] = q
                    prices[sym] = q.last
                except Exception:
                    log.warning("mark_to_market_quote_failed", symbol=sym)

        all_prices_fresh = len(prices) == len(symbols)
        if not all_prices_fresh:
            if not self._degraded_risk_mode:
                self._degraded_risk_mode = True
                log.warning("entering_degraded_risk_mode", missing_count=len(symbols) - len(prices))
                await self._emit_trade_event(
                    EventType.SYSTEM_ERROR,
                    "GLOBAL",
                    {"error": "degraded_risk_mode", "missing_symbols": len(symbols) - len(prices)},
                    EventSeverity.WARNING,
                )
        else:
            if self._degraded_risk_mode:
                self._degraded_risk_mode = False
                log.info("exiting_degraded_risk_mode")
                await self._emit_trade_event(
                    EventType.SYSTEM_INFO,
                    "GLOBAL",
                    {"info": "exiting_degraded_risk_mode"},
                    EventSeverity.INFO,
                )

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

        request = OrderRequest(
            symbol=trigger.symbol,
            side=OrderSide.SELL if position.qty > 0 else OrderSide.BUY,
            qty=abs(position.qty),
            order_type=OrderType.MARKET,
            execution_mode=ExecutionMode.PAPER,
            metadata={"risk_trigger": trigger.action.value, "reason": trigger.reason},
        )

        if self._position_lock_redis is not None:
            # Distributed lock: prevents duplicate stop-loss/take-profit exits
            # under high-volatility tick pressure where the same symbol is
            # evaluated concurrently from multiple quote callbacks.
            from src.trading.position_lock import (
                PositionLockConflict,
                PositionLockUnavailable,
                position_close_lock,
            )
            account_id = self._portfolio._account_id
            try:
                async with position_close_lock(
                    symbol=trigger.symbol,
                    account_id=account_id,
                    redis=self._position_lock_redis,
                ):
                    await self.submit(request)
                    self._trailing_stop.remove(trigger.symbol)
            except PositionLockConflict:
                log.warning(
                    "risk_exit_duplicate_prevented",
                    symbol=trigger.symbol,
                    action=trigger.action.value,
                )
                return
            except PositionLockUnavailable:
                log.error(
                    "risk_exit_lock_unavailable",
                    symbol=trigger.symbol,
                    note="Redis unreachable — close rejected to prevent duplicate",
                )
                return
            except Exception:
                log.exception("risk_exit_failed", symbol=trigger.symbol)
        else:
            # No Redis client — run without distributed lock (test/fallback mode).
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
