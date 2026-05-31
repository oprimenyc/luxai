"""
Unit tests for QueueMonitor.

Tests cover:
- OK lag (≤500ms) — status stays OK
- WARNING lag (>500ms ≤2000ms) — status transitions to WARNING
- CRITICAL lag (>2000ms ≤5000ms) — status transitions to CRITICAL
- DEGRADED lag (>5000ms) — status transitions to DEGRADED, is_degraded=True
- Recovery from DEGRADED back to OK
- get_status() stats (avg, max, p95)
- record_tick_processed without prior record_tick_received is a no-op
- Pending tick tracking
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.queue_monitor import LagStatus, QueueMonitor, get_queue_monitor


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _simulate_lag(monitor: QueueMonitor, symbol: str, lag_ms: float) -> None:
    """Inject a tick with an exact lag by mocking datetime.now."""
    t0 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    from datetime import timedelta
    t1 = t0 + timedelta(milliseconds=lag_ms)

    with patch("src.trading.queue_monitor.datetime") as mock_dt:
        mock_dt.now.side_effect = [t0, t1]
        await monitor.record_tick_received(symbol)
        await monitor.record_tick_processed(symbol)


# ── Lag status transitions ─────────────────────────────────────────────────────


class TestLagStatusTransitions:
    async def test_ok_lag_status(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 100.0)
        assert monitor._current_status == LagStatus.OK
        assert not monitor.is_degraded

    async def test_warning_lag_status(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 600.0)
        assert monitor._current_status == LagStatus.WARNING
        assert not monitor.is_degraded

    async def test_critical_lag_status(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 3000.0)
        assert monitor._current_status == LagStatus.CRITICAL
        assert not monitor.is_degraded

    async def test_degraded_lag_status(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 6000.0)
        assert monitor._current_status == LagStatus.DEGRADED
        assert monitor.is_degraded

    async def test_exactly_at_warning_boundary(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 500.0)  # ≤500ms → OK
        assert monitor._current_status == LagStatus.OK

    async def test_just_above_warning_boundary(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 501.0)
        assert monitor._current_status == LagStatus.WARNING

    async def test_exactly_at_critical_boundary(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 2000.0)  # ≤2000ms → WARNING
        assert monitor._current_status == LagStatus.WARNING

    async def test_just_above_critical_boundary(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 2001.0)
        assert monitor._current_status == LagStatus.CRITICAL

    async def test_exactly_at_degraded_boundary(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 5000.0)  # ≤5000ms → CRITICAL
        assert monitor._current_status == LagStatus.CRITICAL

    async def test_just_above_degraded_boundary(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 5001.0)
        assert monitor._current_status == LagStatus.DEGRADED


# ── Recovery ──────────────────────────────────────────────────────────────────


class TestRecovery:
    async def test_recovery_from_degraded_to_ok(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 6000.0)
        assert monitor.is_degraded
        await _simulate_lag(monitor, "AAPL", 100.0)
        assert monitor._current_status == LagStatus.OK
        assert not monitor.is_degraded

    async def test_recovery_from_critical_to_ok(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 3000.0)
        assert monitor._current_status == LagStatus.CRITICAL
        await _simulate_lag(monitor, "AAPL", 200.0)
        assert monitor._current_status == LagStatus.OK


# ── Pending tick tracking ──────────────────────────────────────────────────────


class TestPendingTicks:
    async def test_pending_increments_on_receive(self) -> None:
        monitor = QueueMonitor()
        await monitor.record_tick_received("AAPL")
        status = monitor.get_status()
        assert status["pending_ticks"] == 1

    async def test_pending_decrements_after_processed(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 100.0)
        status = monitor.get_status()
        assert status["pending_ticks"] == 0

    async def test_orphaned_processed_is_noop(self) -> None:
        monitor = QueueMonitor()
        # process without prior receive — should not raise
        await monitor.record_tick_processed("MSFT")
        status = monitor.get_status()
        assert status["queue_depth"] == 0


# ── get_status() stats ────────────────────────────────────────────────────────


class TestGetStatus:
    async def test_status_keys_present(self) -> None:
        monitor = QueueMonitor()
        status = monitor.get_status()
        for key in ("status", "orders_suspended", "avg_lag_ms", "max_lag_ms",
                    "p95_lag_ms", "pending_ticks", "queue_depth", "last_tick_processed"):
            assert key in status

    async def test_orders_suspended_true_when_degraded(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 6000.0)
        status = monitor.get_status()
        assert status["orders_suspended"] is True

    async def test_orders_suspended_false_when_ok(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 100.0)
        status = monitor.get_status()
        assert status["orders_suspended"] is False

    async def test_avg_lag_reflects_history(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 100.0)
        await _simulate_lag(monitor, "MSFT", 300.0)
        status = monitor.get_status()
        # avg should be between 100 and 300
        assert 100.0 <= status["avg_lag_ms"] <= 300.0

    async def test_last_tick_processed_updates(self) -> None:
        monitor = QueueMonitor()
        await _simulate_lag(monitor, "AAPL", 100.0)
        status = monitor.get_status()
        assert status["last_tick_processed"] is not None

    async def test_empty_monitor_returns_zeros(self) -> None:
        monitor = QueueMonitor()
        status = monitor.get_status()
        assert status["avg_lag_ms"] == 0.0
        assert status["max_lag_ms"] == 0.0
        assert status["last_tick_processed"] is None


# ── Event bus emission ────────────────────────────────────────────────────────


class TestEventBusEmission:
    async def test_critical_lag_emits_event(self) -> None:
        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock()
        monitor = QueueMonitor(event_bus=mock_bus)
        await _simulate_lag(monitor, "AAPL", 3000.0)
        assert mock_bus.publish.called

    async def test_degraded_lag_emits_event(self) -> None:
        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock()
        monitor = QueueMonitor(event_bus=mock_bus)
        await _simulate_lag(monitor, "AAPL", 6000.0)
        assert mock_bus.publish.called

    async def test_ok_lag_does_not_emit_event(self) -> None:
        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock()
        monitor = QueueMonitor(event_bus=mock_bus)
        await _simulate_lag(monitor, "AAPL", 100.0)
        mock_bus.publish.assert_not_called()


# ── Module singleton ──────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_queue_monitor_returns_same_instance(self) -> None:
        import src.trading.queue_monitor as qm_module
        qm_module._monitor = None  # reset
        a = get_queue_monitor()
        b = get_queue_monitor()
        assert a is b
