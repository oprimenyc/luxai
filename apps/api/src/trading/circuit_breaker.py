"""
HTTP circuit breaker — prevents cascade failures when Alpaca API degrades.

States
------
CLOSED    Normal operation. Calls pass through.
OPEN      Service considered down. Calls fast-fail for `recovery_timeout` seconds.
HALF_OPEN Recovery probe. One call allowed through to test service health.

Transitions
-----------
CLOSED → OPEN      after `failure_threshold` consecutive failures
OPEN → HALF_OPEN   after `recovery_timeout` seconds have elapsed
HALF_OPEN → CLOSED probe call succeeded
HALF_OPEN → OPEN   probe call failed — back to full backoff

LLM cannot affect circuit state.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Awaitable, TypeVar

import structlog

log = structlog.get_logger(__name__)

T = TypeVar("T")


def _close_awaitable(awaitable: Awaitable[Any]) -> None:
    """Close a coroutine that will not be awaited to suppress ResourceWarning."""
    if inspect.iscoroutine(awaitable):
        awaitable.close()


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""


class CircuitBreaker:
    """
    Async circuit breaker.

    Usage
    -----
        cb = CircuitBreaker("alpaca_trading", failure_threshold=5)
        result = await cb.call(client.get("/orders"))

    The `call` method accepts any awaitable. It wraps it with state-machine
    protection: fast-failing when the circuit is open and resetting on recovery.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: datetime | None = None
        self._probe_in_flight = False
        self._lock = asyncio.Lock()

    # ── Public ────────────────────────────────────────────────────────────────

    async def call(self, awaitable: Awaitable[T]) -> T:
        """Execute `awaitable`, respecting circuit state. Raises CircuitBreakerOpen if open."""
        async with self._lock:
            state = self._state

            if state == CircuitState.OPEN:
                assert self._opened_at is not None
                elapsed = (datetime.now(UTC) - self._opened_at).total_seconds()
                if elapsed < self._recovery_timeout:
                    remaining = self._recovery_timeout - elapsed
                    _close_awaitable(awaitable)
                    raise CircuitBreakerOpen(
                        f"Circuit [{self._name}] is OPEN. "
                        f"Retry in {remaining:.0f}s."
                    )
                # Transition to half-open to allow a probe
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = False
                log.info("circuit_half_open", name=self._name)

            if self._state == CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    _close_awaitable(awaitable)
                    raise CircuitBreakerOpen(
                        f"Circuit [{self._name}] is HALF_OPEN — probe already in flight."
                    )
                self._probe_in_flight = True

        try:
            result = await awaitable
            await self._on_success()
            return result
        except CircuitBreakerOpen:
            raise
        except Exception:
            await self._on_failure()
            raise

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state != CircuitState.CLOSED:
                log.info("circuit_closed", name=self._name, previous=self._state.value)
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    async def _on_failure(self) -> None:
        async with self._lock:
            self._probe_in_flight = False
            self._consecutive_failures += 1

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — reopen with full timeout
                self._state = CircuitState.OPEN
                self._opened_at = datetime.now(UTC)
                log.warning(
                    "circuit_reopened",
                    name=self._name,
                    failures=self._consecutive_failures,
                )
                return

            if self._consecutive_failures >= self._failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = datetime.now(UTC)
                log.error(
                    "circuit_opened",
                    name=self._name,
                    failures=self._consecutive_failures,
                    threshold=self._failure_threshold,
                )
