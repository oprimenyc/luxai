"""Execution journal — immutable append-only audit log for all trading events."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from supabase import AsyncClient

from src.trading.models import (
    ExecutionMode,
    Fill,
    JournalEntry,
    Order,
    PnLRecord,
    RiskTrigger,
)

log = structlog.get_logger(__name__)


class ExecutionJournal:
    """
    Append-only audit log for all order, fill, risk, and PnL events.

    - In-memory ring buffer (last N entries) for fast queries
    - Async persistence to Supabase `trade_journal` table
    - All writes are fire-and-forget (non-blocking) with error isolation

    IMPORTANT: Never modifies existing records — append only.
    """

    _BUFFER_SIZE = 5_000

    def __init__(
        self,
        client: Any,  # supabase.AsyncClient — typed via TYPE_CHECKING only
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> None:
        self._client = client
        self._execution_mode = execution_mode
        self._buffer: list[JournalEntry] = []
        self._lock = asyncio.Lock()
        
        # Bounded persistence queue
        self._queue: asyncio.Queue[JournalEntry] = asyncio.Queue(maxsize=1000)
        self._worker_task = asyncio.create_task(self._persistence_worker(), name="journal_persistence_worker")

    # ── Write API ────────────────────────────────────────────────────────────

    async def record_order_submitted(self, order: Order) -> None:
        await self._append(JournalEntry(
            entry_type="order_submitted",
            order_id=order.id,
            symbol=order.symbol,
            execution_mode=self._execution_mode,
            payload={
                "broker_order_id": order.broker_order_id,
                "side": order.side,
                "qty": order.qty,
                "order_type": order.order_type,
                "limit_price": order.limit_price,
                "stop_price": order.stop_price,
                "time_in_force": order.time_in_force,
            },
        ))

    async def record_order_filled(self, order: Order, fill: Fill) -> None:
        await self._append(JournalEntry(
            entry_type="order_filled",
            order_id=order.id,
            symbol=order.symbol,
            execution_mode=self._execution_mode,
            payload={
                "broker_order_id": order.broker_order_id,
                "filled_qty": fill.qty,
                "avg_fill_price": fill.price,
                "commission": fill.commission,
                "fill_value": fill.qty * fill.price,
                "filled_at": fill.filled_at.isoformat(),
            },
        ))

    async def record_order_cancelled(self, order: Order, reason: str = "") -> None:
        await self._append(JournalEntry(
            entry_type="order_cancelled",
            order_id=order.id,
            symbol=order.symbol,
            execution_mode=self._execution_mode,
            payload={"reason": reason, "broker_order_id": order.broker_order_id},
        ))

    async def record_order_rejected(self, order: Order, reason: str = "") -> None:
        await self._append(JournalEntry(
            entry_type="order_rejected",
            order_id=order.id,
            symbol=order.symbol,
            execution_mode=self._execution_mode,
            payload={"reason": reason, "broker_order_id": order.broker_order_id},
        ))

    async def record_pnl(self, record: PnLRecord) -> None:
        await self._append(JournalEntry(
            entry_type="pnl_closed",
            symbol=record.symbol,
            execution_mode=self._execution_mode,
            payload={
                "trade_id": str(record.id),
                "side": record.side,
                "qty": record.qty,
                "entry_price": record.entry_price,
                "exit_price": record.exit_price,
                "commission": record.commission,
                "realized_pnl": record.realized_pnl,
                "realized_pnl_pct": record.realized_pnl_pct,
                "holding_period_seconds": record.holding_period_seconds,
                "opened_at": record.opened_at.isoformat(),
                "closed_at": record.closed_at.isoformat(),
            },
        ))

    async def record_risk_trigger(self, trigger: RiskTrigger) -> None:
        await self._append(JournalEntry(
            entry_type="risk_trigger",
            symbol=trigger.symbol,
            execution_mode=self._execution_mode,
            payload={
                "action": trigger.action,
                "reason": trigger.reason,
                "entry_price": trigger.entry_price,
                "trigger_price": trigger.trigger_price,
                "current_price": trigger.current_price,
            },
        ))

    async def record_portfolio_snapshot(self, payload: dict[str, Any]) -> None:
        await self._append(JournalEntry(
            entry_type="portfolio_snapshot",
            execution_mode=self._execution_mode,
            payload=payload,
        ))

    async def close(self) -> None:
        """
        Drain the persistence queue then shut down the worker.

        Waits up to 30 seconds for queued entries to be written to Supabase.
        Called automatically by TradingEngine.stop() to prevent audit-log loss.
        """
        try:
            await asyncio.wait_for(self._queue.join(), timeout=30.0)
        except asyncio.TimeoutError:
            log.warning(
                "journal_close_timeout",
                remaining=self._queue.qsize(),
            )
        finally:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        log.info("journal_closed")

    # ── Read API ─────────────────────────────────────────────────────────────

    async def recent(self, limit: int = 100) -> list[JournalEntry]:
        async with self._lock:
            return list(reversed(self._buffer[-limit:]))

    async def for_symbol(self, symbol: str, limit: int = 50) -> list[JournalEntry]:
        async with self._lock:
            return [e for e in reversed(self._buffer) if e.symbol == symbol][:limit]

    async def for_order(self, order_id: UUID) -> list[JournalEntry]:
        async with self._lock:
            return [e for e in self._buffer if e.order_id == order_id]

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _append(self, entry: JournalEntry) -> None:
        async with self._lock:
            self._buffer.append(entry)
            # Trim ring buffer
            if len(self._buffer) > self._BUFFER_SIZE:
                self._buffer = self._buffer[self._BUFFER_SIZE // 2 :]

        log.info(
            "journal_entry",
            type=entry.entry_type,
            symbol=entry.symbol,
            order_id=str(entry.order_id) if entry.order_id else None,
            mode=self._execution_mode,
        )

        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            log.critical("journal_persistence_queue_full", entry_id=str(entry.id))
            from src.events.bus import event_bus
            from src.events.models import BaseEvent, EventType, EventSeverity
            asyncio.create_task(
                event_bus.publish(BaseEvent(
                    type=EventType.SYSTEM_ERROR,
                    severity=EventSeverity.CRITICAL,
                    payload={"error": "journal_queue_full", "entry_id": str(entry.id)}
                ))
            )

    async def _persistence_worker(self) -> None:
        while True:
            try:
                entry = await self._queue.get()
                await self._persist_with_retry(entry)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("journal_worker_error")
                await asyncio.sleep(1.0)

    async def _persist_with_retry(self, entry: JournalEntry) -> None:
        max_retries = 5
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                await self._persist(entry)
                return
            except Exception:
                if attempt == max_retries - 1:
                    log.exception("journal_persist_failed_permanent", entry_id=str(entry.id))
                    return
                delay = min(base_delay * (2 ** attempt), 30.0)
                log.warning("journal_persist_retry", entry_id=str(entry.id), attempt=attempt+1, delay=delay)
                await asyncio.sleep(delay)

    async def _persist(self, entry: JournalEntry) -> None:
        await self._client.table("trade_journal").insert({
            "id": str(entry.id),
            "entry_type": entry.entry_type,
            "order_id": str(entry.order_id) if entry.order_id else None,
            "symbol": entry.symbol,
            "payload": entry.payload,
            "execution_mode": entry.execution_mode,
            "recorded_at": entry.recorded_at.isoformat(),
        }).execute()
