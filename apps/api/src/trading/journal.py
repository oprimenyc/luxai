"""Execution journal — immutable append-only audit log for all trading events."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
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
        client: AsyncClient,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> None:
        self._client = client
        self._execution_mode = execution_mode
        self._buffer: list[JournalEntry] = []
        self._lock = asyncio.Lock()

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

        # Persist async — do not block the caller
        asyncio.create_task(
            self._persist(entry),
            name=f"journal_persist:{entry.id}",
        )

    async def _persist(self, entry: JournalEntry) -> None:
        try:
            await self._client.table("trade_journal").insert({
                "id": str(entry.id),
                "entry_type": entry.entry_type,
                "order_id": str(entry.order_id) if entry.order_id else None,
                "symbol": entry.symbol,
                "payload": entry.payload,
                "execution_mode": entry.execution_mode,
                "recorded_at": entry.recorded_at.isoformat(),
            }).execute()
        except Exception:
            log.exception("journal_persist_failed", entry_id=str(entry.id))
