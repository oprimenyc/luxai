"""
Redis distributed lock for position close operations.

Path: apps/api/src/trading/position_lock.py
Security: Lock key namespaced by account_id + symbol to prevent cross-account
          lock conflicts in future multi-tenant scenarios. Lock TTL of 30s
          ensures automatic release if the holder crashes mid-close.
Scale: One Redis round-trip to acquire, one to release. O(1) per operation.
       Lock contention is expected to be near-zero under normal operation;
       the lock only matters under rapid tick pressure or duplicate signals.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis

log = structlog.get_logger(__name__)

_LOCK_TTL_SECONDS = 30
_LOCK_KEY_PREFIX = "lock:close"


class PositionLockConflict(RuntimeError):
    """
    Raised when a close operation cannot acquire the distributed lock because
    another close for the same position is already in flight.
    """

    def __init__(self, symbol: str) -> None:
        super().__init__(
            f"Position close lock conflict for {symbol}: "
            "duplicate close attempt prevented."
        )
        self.symbol = symbol


class PositionLockUnavailable(RuntimeError):
    """Raised when Redis is unreachable and the lock cannot be verified."""


@asynccontextmanager
async def position_close_lock(
    symbol: str,
    account_id: str,
    redis: "aioredis.Redis",
) -> AsyncGenerator[None, None]:
    """
    Async context manager that acquires a Redis distributed lock before
    executing a position close. Raises PositionLockConflict if the lock is
    already held (duplicate close in flight).

    Usage:
        async with position_close_lock(symbol, account_id, redis_client):
            await engine.submit(close_request)

    Lock key: lock:close:{account_id}:{symbol}
    TTL: 30 seconds — auto-releases if holder crashes

    On Redis failure: raises PositionLockUnavailable. Callers should treat
    this as a close rejection — better to miss a close than to double-close.
    """
    lock_key = f"{_LOCK_KEY_PREFIX}:{account_id}:{symbol}"

    try:
        acquired = await redis.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
    except Exception as exc:
        log.error(
            "position_lock_redis_unavailable",
            symbol=symbol,
            account_id=account_id,
            error=str(exc),
        )
        raise PositionLockUnavailable(
            f"Position close lock unavailable for {symbol} (Redis unreachable). "
            "Close rejected — retry is safe."
        ) from exc

    if not acquired:
        log.warning(
            "position_lock_conflict",
            symbol=symbol,
            account_id=account_id,
            message="Duplicate close attempt prevented by distributed lock",
        )
        raise PositionLockConflict(symbol)

    log.debug("position_lock_acquired", symbol=symbol, account_id=account_id)
    try:
        yield
    finally:
        # Release the lock — fire-and-forget deletion is safe here because
        # the TTL ensures the lock auto-releases after 30s even on crash.
        try:
            await redis.delete(lock_key)
            log.debug("position_lock_released", symbol=symbol, account_id=account_id)
        except Exception:
            log.warning(
                "position_lock_release_failed",
                symbol=symbol,
                account_id=account_id,
                note="Lock will auto-release after 30s TTL",
            )
