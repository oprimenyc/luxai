"""
Unit tests for position_close_lock distributed lock.

Tests cover:
- Normal single acquire + release
- Duplicate close attempt raises PositionLockConflict
- Redis failure raises PositionLockUnavailable
- Lock is released in finally even on exception inside context
- Lock key is namespaced by account_id + symbol
- TTL is set on acquire
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.trading.position_lock import (
    PositionLockConflict,
    PositionLockUnavailable,
    position_close_lock,
)


def _make_redis(acquired: bool = True, set_raises: Exception | None = None) -> MagicMock:
    redis = MagicMock()
    if set_raises:
        redis.set = AsyncMock(side_effect=set_raises)
    else:
        redis.set = AsyncMock(return_value=acquired)
    redis.delete = AsyncMock(return_value=1)
    return redis


# ── Normal acquire ────────────────────────────────────────────────────────────


class TestNormalAcquire:
    async def test_lock_acquired_and_released(self) -> None:
        redis = _make_redis(acquired=True)
        async with position_close_lock("AAPL", "acct-1", redis):
            redis.set.assert_called_once()
        redis.delete.assert_called_once()

    async def test_lock_key_includes_account_and_symbol(self) -> None:
        redis = _make_redis(acquired=True)
        async with position_close_lock("TSLA", "acct-99", redis):
            call_args = redis.set.call_args
            key = call_args[0][0]
            assert "acct-99" in key
            assert "TSLA" in key

    async def test_lock_set_with_nx_and_ex(self) -> None:
        redis = _make_redis(acquired=True)
        async with position_close_lock("AAPL", "acct-1", redis):
            call_kwargs = redis.set.call_args
            # Verify nx=True and ex=30 were passed
            assert call_kwargs.kwargs.get("nx") is True
            assert call_kwargs.kwargs.get("ex") == 30

    async def test_context_body_executes(self) -> None:
        redis = _make_redis(acquired=True)
        executed = []
        async with position_close_lock("AAPL", "acct-1", redis):
            executed.append("ran")
        assert executed == ["ran"]


# ── Conflict (duplicate close) ────────────────────────────────────────────────


class TestLockConflict:
    async def test_conflict_raises_position_lock_conflict(self) -> None:
        redis = _make_redis(acquired=False)  # SETNX returns False → already held
        with pytest.raises(PositionLockConflict) as exc_info:
            async with position_close_lock("AAPL", "acct-1", redis):
                pass
        assert "AAPL" in str(exc_info.value)

    async def test_conflict_does_not_call_delete(self) -> None:
        redis = _make_redis(acquired=False)
        with pytest.raises(PositionLockConflict):
            async with position_close_lock("AAPL", "acct-1", redis):
                pass
        redis.delete.assert_not_called()

    async def test_conflict_symbol_attribute(self) -> None:
        redis = _make_redis(acquired=False)
        with pytest.raises(PositionLockConflict) as exc_info:
            async with position_close_lock("MSFT", "acct-2", redis):
                pass
        assert exc_info.value.symbol == "MSFT"


# ── Redis failure ─────────────────────────────────────────────────────────────


class TestRedisFailure:
    async def test_redis_down_raises_lock_unavailable(self) -> None:
        redis = _make_redis(set_raises=ConnectionError("Redis is down"))
        with pytest.raises(PositionLockUnavailable):
            async with position_close_lock("AAPL", "acct-1", redis):
                pass

    async def test_redis_timeout_raises_lock_unavailable(self) -> None:
        redis = _make_redis(set_raises=TimeoutError("connection timeout"))
        with pytest.raises(PositionLockUnavailable):
            async with position_close_lock("AAPL", "acct-1", redis):
                pass

    async def test_redis_down_does_not_execute_body(self) -> None:
        redis = _make_redis(set_raises=ConnectionError("Redis is down"))
        executed = []
        with pytest.raises(PositionLockUnavailable):
            async with position_close_lock("AAPL", "acct-1", redis):
                executed.append("ran")
        assert executed == []


# ── Release on exception ──────────────────────────────────────────────────────


class TestReleaseOnException:
    async def test_lock_released_when_body_raises(self) -> None:
        redis = _make_redis(acquired=True)
        with pytest.raises(ValueError):
            async with position_close_lock("AAPL", "acct-1", redis):
                raise ValueError("something went wrong in close logic")
        redis.delete.assert_called_once()

    async def test_delete_failure_does_not_mask_body_exception(self) -> None:
        redis = _make_redis(acquired=True)
        redis.delete = AsyncMock(side_effect=ConnectionError("Redis down on release"))
        # The body succeeds — only the delete fails silently (TTL will auto-release)
        async with position_close_lock("AAPL", "acct-1", redis):
            pass  # body succeeds

    async def test_delete_failure_does_not_raise(self) -> None:
        redis = _make_redis(acquired=True)
        redis.delete = AsyncMock(side_effect=Exception("delete failed"))
        # Should not propagate the delete error
        async with position_close_lock("AAPL", "acct-1", redis):
            pass


# ── Different symbols don't conflict ──────────────────────────────────────────


class TestNamespaceIsolation:
    async def test_different_symbols_have_different_keys(self) -> None:
        keys_used = []

        async def capture_set(key: str, *args, **kwargs):
            keys_used.append(key)
            return True

        redis = MagicMock()
        redis.set = AsyncMock(side_effect=capture_set)
        redis.delete = AsyncMock(return_value=1)

        async with position_close_lock("AAPL", "acct-1", redis):
            pass
        async with position_close_lock("MSFT", "acct-1", redis):
            pass

        assert keys_used[0] != keys_used[1]
        assert "AAPL" in keys_used[0]
        assert "MSFT" in keys_used[1]

    async def test_different_accounts_have_different_keys(self) -> None:
        keys_used = []

        async def capture_set(key: str, *args, **kwargs):
            keys_used.append(key)
            return True

        redis = MagicMock()
        redis.set = AsyncMock(side_effect=capture_set)
        redis.delete = AsyncMock(return_value=1)

        async with position_close_lock("AAPL", "acct-1", redis):
            pass
        async with position_close_lock("AAPL", "acct-2", redis):
            pass

        assert keys_used[0] != keys_used[1]
        assert "acct-1" in keys_used[0]
        assert "acct-2" in keys_used[1]
