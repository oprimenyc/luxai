"""
Queue lag monitor — detects when the risk engine falls behind on market ticks.

Path: apps/api/src/trading/queue_monitor.py
Security: In-memory only. No credentials. No external writes.
          Metrics are internal diagnostics; they are never user-facing without auth.
Scale: Circular buffer of recent tick records (default 1000). O(1) record and
       O(n_recent) for stats. Designed for single-instance use on Railway.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class LagStatus(StrEnum):
    OK = "OK"
    WARNING = "WARNING"     # lag > 500ms
    CRITICAL = "CRITICAL"   # lag > 2000ms
    DEGRADED = "DEGRADED"   # lag > 5000ms — suspends new order submissions


_WARNING_MS = 500
_CRITICAL_MS = 2_000
_DEGRADED_MS = 5_000

_BUFFER_SIZE = 1_000


class TickRecord:
    __slots__ = ("symbol", "received_at", "processed_at", "lag_ms")

    def __init__(self, symbol: str, received_at: datetime) -> None:
        self.symbol = symbol
        self.received_at = received_at
        self.processed_at: datetime | None = None
        self.lag_ms: float | None = None


class QueueMonitor:
    """
    Tracks per-tick latency between market data receipt and risk evaluation.

    Integration pattern in TradingEngine:
      - Call record_tick_received(symbol) in _on_quote_update() when tick arrives.
      - Call record_tick_processed(symbol) when _evaluate_risk_for_symbol() completes.

    Thresholds (from spec):
      OK        lag ≤ 500ms
      WARNING   500ms < lag ≤ 2000ms   — log warning
      CRITICAL  2000ms < lag ≤ 5000ms  — emit event to event bus
      DEGRADED  lag > 5000ms           — suspend new order submissions
    """

    def __init__(self, event_bus: Any | None = None) -> None:
        self._event_bus = event_bus
        self._pending: dict[str, TickRecord] = {}
        self._history: deque[TickRecord] = deque(maxlen=_BUFFER_SIZE)
        self._lock = asyncio.Lock()
        self._current_status = LagStatus.OK
        self._last_tick_processed: datetime | None = None

    # ── Recording ─────────────────────────────────────────────────────────────

    async def record_tick_received(self, symbol: str) -> None:
        """Called when a market tick arrives (on_quote_update entry point)."""
        async with self._lock:
            self._pending[symbol] = TickRecord(symbol, datetime.now(UTC))

    async def record_tick_processed(self, symbol: str) -> None:
        """Called after risk evaluation for a symbol completes."""
        async with self._lock:
            record = self._pending.pop(symbol, None)
            if record is None:
                return  # record_tick_received was not called — skip

            now = datetime.now(UTC)
            record.processed_at = now
            record.lag_ms = (now - record.received_at).total_seconds() * 1000
            self._last_tick_processed = now
            self._history.append(record)

        await self._evaluate_lag(record.lag_ms, symbol)

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return current lag statistics for the /queue-status endpoint."""
        recent = list(self._history)[-100:]  # last 100 ticks
        lags = [r.lag_ms for r in recent if r.lag_ms is not None]

        avg_lag = sum(lags) / len(lags) if lags else 0.0
        max_lag = max(lags) if lags else 0.0
        p95_lag = sorted(lags)[int(len(lags) * 0.95)] if len(lags) >= 20 else max_lag

        return {
            "status": self._current_status,
            "orders_suspended": self._current_status == LagStatus.DEGRADED,
            "avg_lag_ms": round(avg_lag, 2),
            "max_lag_ms": round(max_lag, 2),
            "p95_lag_ms": round(p95_lag, 2),
            "pending_ticks": len(self._pending),
            "queue_depth": len(self._history),
            "last_tick_processed": (
                self._last_tick_processed.isoformat()
                if self._last_tick_processed
                else None
            ),
        }

    @property
    def is_degraded(self) -> bool:
        """True if lag is in DEGRADED state — callers use this to block submissions."""
        return self._current_status == LagStatus.DEGRADED

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _evaluate_lag(self, lag_ms: float, symbol: str) -> None:
        """Classify the lag, update status, emit events if needed."""
        if lag_ms <= _WARNING_MS:
            new_status = LagStatus.OK
        elif lag_ms <= _CRITICAL_MS:
            new_status = LagStatus.WARNING
        elif lag_ms <= _DEGRADED_MS:
            new_status = LagStatus.CRITICAL
        else:
            new_status = LagStatus.DEGRADED

        prev_status = self._current_status
        self._current_status = new_status

        if new_status == LagStatus.WARNING and prev_status == LagStatus.OK:
            log.warning(
                "queue_lag_warning",
                symbol=symbol,
                lag_ms=round(lag_ms, 1),
            )

        elif new_status == LagStatus.CRITICAL:
            log.error(
                "queue_lag_critical",
                symbol=symbol,
                lag_ms=round(lag_ms, 1),
                threshold_ms=_CRITICAL_MS,
            )
            if self._event_bus:
                try:
                    from src.events.models import BaseEvent, EventSeverity, EventType
                    await self._event_bus.publish(
                        BaseEvent(
                            type=EventType.SYSTEM_ERROR,
                            severity=EventSeverity.WARNING,
                            payload={
                                "error": "queue_lag_critical",
                                "symbol": symbol,
                                "lag_ms": round(lag_ms, 1),
                            },
                        )
                    )
                except Exception:
                    pass

        elif new_status == LagStatus.DEGRADED:
            log.critical(
                "queue_lag_degraded_orders_suspended",
                symbol=symbol,
                lag_ms=round(lag_ms, 1),
                threshold_ms=_DEGRADED_MS,
                message="New order submissions suspended until lag recovers.",
            )
            if self._event_bus:
                try:
                    from src.events.models import BaseEvent, EventSeverity, EventType
                    await self._event_bus.publish(
                        BaseEvent(
                            type=EventType.SYSTEM_ERROR,
                            severity=EventSeverity.CRITICAL,
                            payload={
                                "error": "queue_lag_degraded",
                                "symbol": symbol,
                                "lag_ms": round(lag_ms, 1),
                                "orders_suspended": True,
                            },
                        )
                    )
                except Exception:
                    pass

        elif new_status == LagStatus.OK and prev_status != LagStatus.OK:
            log.info(
                "queue_lag_recovered",
                symbol=symbol,
                lag_ms=round(lag_ms, 1),
                prev_status=prev_status,
            )


# ── Module-level singleton (shared across engine and router) ──────────────────

_monitor: QueueMonitor | None = None


def get_queue_monitor() -> QueueMonitor:
    """Return the module-level QueueMonitor singleton, creating it if needed."""
    global _monitor
    if _monitor is None:
        try:
            from src.events.bus import event_bus
            _monitor = QueueMonitor(event_bus=event_bus)
        except Exception:
            _monitor = QueueMonitor(event_bus=None)
    return _monitor
