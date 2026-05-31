"""
Unit tests for KillSwitchService.

Tests cover:
- is_halted: Redis "1" → True, Redis "0" → False
- is_halted: Redis miss → Supabase active record → True, back-populate Redis
- is_halted: Redis miss → Supabase no record → False
- is_halted: Redis failure → assume HALTED (fail-safe)
- is_halted: Supabase failure (after Redis miss) → assume HALTED (fail-safe)
- activate: Redis + Supabase both succeed → halted
- activate: Redis failure → raises KillSwitchError, no state change
- activate: Supabase failure → raises KillSwitchError, Redis rolled back
- clear: Supabase first, Redis second → not halted
- clear: Supabase failure → raises KillSwitchError, halt remains active
- clear: Redis failure after Supabase → logged, not raised (re-sync on next read)
- get_status: returns is_halted + last record
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from src.trading.kill_switch import KillSwitchError, KillSwitchService


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_redis(
    get_value: bytes | None = None,
    get_raises: Exception | None = None,
    set_raises: Exception | None = None,
    delete_raises: Exception | None = None,
) -> MagicMock:
    redis = MagicMock()
    if get_raises:
        redis.get = AsyncMock(side_effect=get_raises)
    else:
        redis.get = AsyncMock(return_value=get_value)
    if set_raises:
        redis.set = AsyncMock(side_effect=set_raises)
    else:
        redis.set = AsyncMock(return_value=True)
    if delete_raises:
        redis.delete = AsyncMock(side_effect=delete_raises)
    else:
        redis.delete = AsyncMock(return_value=1)
    return redis


def _make_supabase(
    select_data: list[dict] | None = None,
    select_raises: Exception | None = None,
    insert_raises: Exception | None = None,
    update_raises: Exception | None = None,
) -> MagicMock:
    sb = MagicMock()

    # select chain
    sel = MagicMock()
    sel.eq.return_value = sel
    sel.is_.return_value = sel
    sel.order.return_value = sel
    sel.limit.return_value = sel
    if select_raises:
        sel.execute = AsyncMock(side_effect=select_raises)
    else:
        sel.execute = AsyncMock(return_value=MagicMock(data=select_data or []))
    sb.table.return_value.select.return_value = sel

    # insert chain
    ins = MagicMock()
    if insert_raises:
        ins.execute = AsyncMock(side_effect=insert_raises)
    else:
        ins.execute = AsyncMock(return_value=MagicMock(data=[{"id": "row-1"}]))
    sb.table.return_value.insert.return_value = ins

    # update chain
    upd = MagicMock()
    upd.eq.return_value = upd
    upd.is_.return_value = upd
    if update_raises:
        upd.execute = AsyncMock(side_effect=update_raises)
    else:
        upd.execute = AsyncMock(return_value=MagicMock(data=[]))
    sb.table.return_value.update.return_value = upd

    return sb


# ── is_halted: Redis hit ───────────────────────────────────────────────────────


class TestIsHaltedRedisHit:
    async def test_redis_returns_1_means_halted(self) -> None:
        redis = _make_redis(get_value=b"1")
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        assert await svc.is_halted("user-1") is True

    async def test_redis_returns_0_means_not_halted(self) -> None:
        redis = _make_redis(get_value=b"0")
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        assert await svc.is_halted("user-1") is False

    async def test_redis_returns_string_1(self) -> None:
        redis = _make_redis(get_value="1")
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        assert await svc.is_halted("user-1") is True


# ── is_halted: Redis miss → Supabase fallback ─────────────────────────────────


class TestIsHaltedSupabaseFallback:
    async def test_redis_miss_supabase_active_record_is_halted(self) -> None:
        redis = _make_redis(get_value=None)
        sb = _make_supabase(select_data=[{"id": "halt-row-1"}])
        svc = KillSwitchService(redis, sb)
        assert await svc.is_halted("user-1") is True

    async def test_redis_miss_supabase_no_record_is_not_halted(self) -> None:
        redis = _make_redis(get_value=None)
        sb = _make_supabase(select_data=[])
        svc = KillSwitchService(redis, sb)
        assert await svc.is_halted("user-1") is False

    async def test_redis_back_populated_from_supabase(self) -> None:
        redis = _make_redis(get_value=None)
        sb = _make_supabase(select_data=[{"id": "halt-row-1"}])
        svc = KillSwitchService(redis, sb)
        await svc.is_halted("user-1")
        # Redis.set should have been called to back-populate cache
        redis.set.assert_called_once()


# ── is_halted: fail-safe ──────────────────────────────────────────────────────


class TestIsHaltedFailSafe:
    async def test_redis_failure_assumes_halted(self) -> None:
        redis = _make_redis(get_raises=ConnectionError("Redis down"))
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        assert await svc.is_halted("user-1") is True

    async def test_supabase_failure_after_redis_miss_assumes_halted(self) -> None:
        redis = _make_redis(get_value=None)
        sb = _make_supabase(select_raises=Exception("Supabase down"))
        svc = KillSwitchService(redis, sb)
        assert await svc.is_halted("user-1") is True


# ── activate ──────────────────────────────────────────────────────────────────


class TestActivate:
    async def test_activate_sets_halted(self) -> None:
        redis = _make_redis()
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        await svc.activate("user-1", activated_by="admin", reason="manual")
        redis.set.assert_called_once()
        sb.table.return_value.insert.assert_called_once()

    async def test_activate_redis_failure_raises_and_no_supabase_write(self) -> None:
        redis = _make_redis(set_raises=ConnectionError("Redis down"))
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        with pytest.raises(KillSwitchError, match="Redis write failed"):
            await svc.activate("user-1", activated_by="admin")
        sb.table.return_value.insert.assert_not_called()

    async def test_activate_supabase_failure_rolls_back_redis(self) -> None:
        redis = _make_redis()
        sb = _make_supabase(insert_raises=Exception("Supabase down"))
        svc = KillSwitchService(redis, sb)
        with pytest.raises(KillSwitchError, match="Supabase write failed"):
            await svc.activate("user-1", activated_by="admin")
        # Redis should have been rolled back (delete called)
        redis.delete.assert_called_once()

    async def test_activate_stores_reason_and_audit_notes(self) -> None:
        redis = _make_redis()
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        await svc.activate(
            "user-1",
            activated_by="admin-1",
            reason="daily_loss_limit",
            audit_notes="Hit -5% intraday",
        )
        call_payload = sb.table.return_value.insert.call_args[0][0]
        assert call_payload["reason"] == "daily_loss_limit"
        assert call_payload["audit_notes"] == "Hit -5% intraday"
        assert call_payload["activated_by"] == "admin-1"


# ── clear ─────────────────────────────────────────────────────────────────────


class TestClear:
    async def test_clear_writes_supabase_then_redis(self) -> None:
        redis = _make_redis()
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        await svc.clear("user-1", cleared_by="admin")
        sb.table.return_value.update.assert_called_once()
        redis.set.assert_called_once()

    async def test_clear_supabase_failure_raises_halt_stays_active(self) -> None:
        redis = _make_redis()
        sb = _make_supabase(update_raises=Exception("Supabase down"))
        svc = KillSwitchService(redis, sb)
        with pytest.raises(KillSwitchError, match="halt remains ACTIVE"):
            await svc.clear("user-1", cleared_by="admin")
        # Redis should NOT have been cleared
        redis.set.assert_not_called()

    async def test_clear_redis_failure_does_not_raise(self) -> None:
        redis = _make_redis(set_raises=Exception("Redis down"))
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        # Should NOT raise — Supabase succeeded, Redis failure is logged
        await svc.clear("user-1", cleared_by="admin")

    async def test_clear_sets_redis_to_0(self) -> None:
        redis = _make_redis()
        sb = _make_supabase()
        svc = KillSwitchService(redis, sb)
        await svc.clear("user-1", cleared_by="admin")
        call_args = redis.set.call_args
        assert call_args[0][1] == "0"


# ── get_status ────────────────────────────────────────────────────────────────


class TestGetStatus:
    async def test_get_status_returns_is_halted(self) -> None:
        redis = _make_redis(get_value=b"1")
        sb = _make_supabase(select_data=[{
            "activated_at": "2024-01-01T12:00:00+00:00",
            "activated_by": "admin",
            "reason": "manual",
            "cleared_at": None,
            "cleared_by": None,
        }])
        svc = KillSwitchService(redis, sb)
        status = await svc.get_status("user-1")
        assert status["is_halted"] is True

    async def test_get_status_includes_last_record(self) -> None:
        redis = _make_redis(get_value=b"1")
        sb = _make_supabase(select_data=[{
            "activated_at": "2024-01-01T12:00:00+00:00",
            "activated_by": "admin",
            "reason": "manual",
            "cleared_at": None,
            "cleared_by": None,
        }])
        svc = KillSwitchService(redis, sb)
        status = await svc.get_status("user-1")
        assert status["activated_by"] == "admin"
        assert status["reason"] == "manual"

    async def test_get_status_empty_when_no_record(self) -> None:
        redis = _make_redis(get_value=b"0")
        sb = _make_supabase(select_data=[])
        svc = KillSwitchService(redis, sb)
        status = await svc.get_status("user-1")
        assert status["is_halted"] is False
        assert status["activated_at"] is None

    async def test_get_status_supabase_failure_does_not_raise(self) -> None:
        redis = _make_redis(get_value=b"0")
        sb = _make_supabase(select_raises=Exception("Supabase down"))
        svc = KillSwitchService(redis, sb)
        status = await svc.get_status("user-1")
        assert "is_halted" in status
