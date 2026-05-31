"""
Unit tests for IdempotencyService.

Tests cover:
- compute_hash: determinism, sensitivity to each field, case normalization
- check_and_reserve: first request succeeds, duplicate raises DuplicateRequestError
- check_and_reserve: Redis failure raises IdempotencyServiceUnavailable (REJECT)
- check_and_reserve: Supabase ledger write failure is non-fatal (Redis still protects)
- check_restart_scenario: Supabase record found → treat as duplicate
- check_restart_scenario: Supabase down → proceed (non-fatal)
- mark_completed: stores response_payload in ledger
- mark_completed: Supabase failure is non-fatal
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.trading.idempotency import (
    DuplicateRequestError,
    IdempotencyService,
    IdempotencyServiceUnavailable,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_redis(setnx_result: bool | None = True, raises: Exception | None = None) -> MagicMock:
    redis = MagicMock()
    if raises:
        redis.set = AsyncMock(side_effect=raises)
    else:
        redis.set = AsyncMock(return_value=setnx_result)
    redis.delete = AsyncMock(return_value=1)
    redis.get = AsyncMock(return_value=None)
    return redis


def _make_supabase(
    insert_raises: Exception | None = None,
    fetch_data: dict | None = None,
    update_raises: Exception | None = None,
    select_raises: Exception | None = None,
) -> MagicMock:
    sb = MagicMock()

    # Chain for insert
    insert_chain = MagicMock()
    if insert_raises:
        insert_chain.execute = AsyncMock(side_effect=insert_raises)
    else:
        insert_chain.execute = AsyncMock(return_value=MagicMock(data=[{"id": "abc"}]))
    sb.table.return_value.insert.return_value = insert_chain

    # Chain for select (maybe_single)
    select_chain = MagicMock()
    maybe_single_chain = MagicMock()
    if select_raises:
        maybe_single_chain.execute = AsyncMock(side_effect=select_raises)
    else:
        maybe_single_chain.execute = AsyncMock(return_value=MagicMock(data=fetch_data))
    select_chain.eq.return_value = select_chain
    select_chain.gte.return_value = select_chain
    select_chain.maybe_single.return_value = maybe_single_chain
    sb.table.return_value.select.return_value = select_chain

    # Chain for update
    update_chain = MagicMock()
    update_chain.eq.return_value = update_chain
    if update_raises:
        update_chain.execute = AsyncMock(side_effect=update_raises)
    else:
        update_chain.execute = AsyncMock(return_value=MagicMock(data=[]))
    sb.table.return_value.update.return_value = update_chain

    return sb


_PAYLOAD = {
    "symbol": "AAPL",
    "side": "buy",
    "qty": 1,
    "order_type": "market",
    "idempotency_key": "key-001",
}


# ── compute_hash ──────────────────────────────────────────────────────────────


class TestComputeHash:
    def test_deterministic(self) -> None:
        h1 = IdempotencyService.compute_hash("user-1", _PAYLOAD)
        h2 = IdempotencyService.compute_hash("user-1", _PAYLOAD)
        assert h1 == h2

    def test_different_user_different_hash(self) -> None:
        h1 = IdempotencyService.compute_hash("user-1", _PAYLOAD)
        h2 = IdempotencyService.compute_hash("user-2", _PAYLOAD)
        assert h1 != h2

    def test_different_symbol_different_hash(self) -> None:
        p2 = {**_PAYLOAD, "symbol": "MSFT"}
        assert IdempotencyService.compute_hash("u", _PAYLOAD) != IdempotencyService.compute_hash("u", p2)

    def test_different_qty_different_hash(self) -> None:
        p2 = {**_PAYLOAD, "qty": 5}
        assert IdempotencyService.compute_hash("u", _PAYLOAD) != IdempotencyService.compute_hash("u", p2)

    def test_different_idempotency_key_different_hash(self) -> None:
        p2 = {**_PAYLOAD, "idempotency_key": "key-002"}
        assert IdempotencyService.compute_hash("u", _PAYLOAD) != IdempotencyService.compute_hash("u", p2)

    def test_symbol_normalized_to_uppercase(self) -> None:
        lower = {**_PAYLOAD, "symbol": "aapl"}
        upper = {**_PAYLOAD, "symbol": "AAPL"}
        assert IdempotencyService.compute_hash("u", lower) == IdempotencyService.compute_hash("u", upper)

    def test_returns_hex_string(self) -> None:
        h = IdempotencyService.compute_hash("u", _PAYLOAD)
        assert isinstance(h, str)
        int(h, 16)  # valid hex

    def test_hash_is_64_chars(self) -> None:
        h = IdempotencyService.compute_hash("u", _PAYLOAD)
        assert len(h) == 64


# ── check_and_reserve: first request ─────────────────────────────────────────


class TestCheckAndReserveFirstRequest:
    async def test_first_request_succeeds(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)
        redis.set.assert_called_once()

    async def test_redis_key_namespaced_by_user(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        await svc.check_and_reserve("user-99", "hash-abc", _PAYLOAD)
        key = redis.set.call_args[0][0]
        assert "user-99" in key
        assert "hash-abc" in key

    async def test_redis_set_uses_nx_and_ttl(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)
        kw = redis.set.call_args.kwargs
        assert kw.get("nx") is True
        assert kw.get("ex") == 86400

    async def test_supabase_ledger_written_on_first(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)
        sb.table.return_value.insert.assert_called_once()


# ── check_and_reserve: duplicate ─────────────────────────────────────────────


class TestCheckAndReserveDuplicate:
    async def test_duplicate_raises_duplicate_request_error(self) -> None:
        redis = _make_redis(setnx_result=False)  # key already exists
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        with pytest.raises(DuplicateRequestError):
            await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)

    async def test_duplicate_includes_cached_response_when_available(self) -> None:
        redis = _make_redis(setnx_result=False)
        cached = {"order_id": "order-123", "status": "filled"}
        sb = _make_supabase(fetch_data={"response_payload": cached, "status": "completed"})
        svc = IdempotencyService(redis, sb)
        with pytest.raises(DuplicateRequestError) as exc_info:
            await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)
        assert exc_info.value.cached_response == cached

    async def test_duplicate_no_cached_response_when_pending(self) -> None:
        redis = _make_redis(setnx_result=False)
        # status is "received" not "completed" — no cached response
        sb = _make_supabase(fetch_data={"response_payload": {}, "status": "received"})
        svc = IdempotencyService(redis, sb)
        with pytest.raises(DuplicateRequestError) as exc_info:
            await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)
        assert exc_info.value.cached_response is None


# ── check_and_reserve: Redis failure → REJECT ─────────────────────────────────


class TestCheckAndReserveRedisFailure:
    async def test_redis_down_raises_unavailable(self) -> None:
        redis = _make_redis(raises=ConnectionError("Redis unreachable"))
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        with pytest.raises(IdempotencyServiceUnavailable):
            await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)

    async def test_redis_timeout_raises_unavailable(self) -> None:
        redis = _make_redis(raises=TimeoutError("timeout"))
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        with pytest.raises(IdempotencyServiceUnavailable):
            await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)

    async def test_redis_down_does_not_silently_pass(self) -> None:
        # The invariant: Redis failure → REJECT, never silently pass through
        redis = _make_redis(raises=RuntimeError("Redis gone"))
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        with pytest.raises((IdempotencyServiceUnavailable,)):
            await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)


# ── check_and_reserve: Supabase write failure is non-fatal ───────────────────


class TestSupabaseLedgerWriteFailure:
    async def test_supabase_down_does_not_block_first_request(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase(insert_raises=Exception("Supabase unavailable"))
        svc = IdempotencyService(redis, sb)
        # Should NOT raise — Redis key is already set, Supabase failure is non-fatal
        await svc.check_and_reserve("u1", "hash-abc", _PAYLOAD)


# ── check_restart_scenario ────────────────────────────────────────────────────


class TestCheckRestartScenario:
    async def test_supabase_record_found_raises_duplicate(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase(fetch_data={"id": "row-1", "response_payload": {}, "status": "received"})
        svc = IdempotencyService(redis, sb)
        with pytest.raises(DuplicateRequestError):
            await svc.check_restart_scenario("u1", "hash-abc", _PAYLOAD)

    async def test_supabase_record_found_repopulates_redis(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase(fetch_data={"id": "row-1", "response_payload": {}, "status": "received"})
        svc = IdempotencyService(redis, sb)
        with pytest.raises(DuplicateRequestError):
            await svc.check_restart_scenario("u1", "hash-abc", _PAYLOAD)
        # Redis.set should have been called to repopulate
        assert redis.set.call_count >= 1

    async def test_no_supabase_record_proceeds_cleanly(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase(fetch_data=None)
        svc = IdempotencyService(redis, sb)
        # Should not raise — no duplicate found in Supabase
        await svc.check_restart_scenario("u1", "hash-abc", _PAYLOAD)

    async def test_supabase_down_on_restart_check_is_non_fatal(self) -> None:
        redis = _make_redis(setnx_result=True)
        sb = _make_supabase(select_raises=Exception("Supabase down"))
        svc = IdempotencyService(redis, sb)
        # Should not raise — failure during restart check is non-fatal
        await svc.check_restart_scenario("u1", "hash-abc", _PAYLOAD)


# ── mark_completed ────────────────────────────────────────────────────────────


class TestMarkCompleted:
    async def test_mark_completed_updates_supabase(self) -> None:
        redis = _make_redis()
        sb = _make_supabase()
        svc = IdempotencyService(redis, sb)
        await svc.mark_completed("u1", "hash-abc", {"order_id": "order-1"})
        sb.table.return_value.update.assert_called_once()

    async def test_mark_completed_supabase_failure_is_non_fatal(self) -> None:
        redis = _make_redis()
        sb = _make_supabase(update_raises=Exception("Supabase down"))
        svc = IdempotencyService(redis, sb)
        # Should not raise
        await svc.mark_completed("u1", "hash-abc", {"order_id": "order-1"})
