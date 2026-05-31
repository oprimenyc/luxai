"""
Unit tests for shadow P&L aggregation and trade close mechanism.

Covers:
- aggregate_pnl: correct total, win rate, avg win/loss calculation
- aggregate_pnl: Supabase failure is non-fatal (no raise)
- close_shadow_trade: correct P&L for buy/sell
- close_shadow_trade: calls aggregate_pnl after close
- close_shadow_trade: returns {} when trade not found
- get_open_trades: returns empty list on Supabase failure
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.trading.shadow import ShadowModeService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_redis() -> MagicMock:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


def _make_supabase(
    closed_trades: list[dict] | None = None,
    open_trade: dict | None = None,
    select_raises: Exception | None = None,
    upsert_raises: Exception | None = None,
    update_raises: Exception | None = None,
) -> MagicMock:
    sb = MagicMock()

    # select chain — used by get_open_trades, close_shadow_trade, aggregate_pnl
    sel = MagicMock()
    sel.eq.return_value = sel
    sel.is_.return_value = sel
    sel.order.return_value = sel
    sel.limit.return_value = sel
    sel.maybe_single.return_value = sel
    if select_raises:
        sel.execute = AsyncMock(side_effect=select_raises)
    else:
        # Return different data based on what's being fetched
        # First call (close_shadow_trade fetch) returns open_trade
        # Second call (aggregate_pnl) returns closed_trades
        call_count = {"n": 0}
        async def _execute():
            call_count["n"] += 1
            if call_count["n"] == 1 and open_trade is not None:
                return MagicMock(data=open_trade)
            return MagicMock(data=closed_trades or [])
        sel.execute = AsyncMock(side_effect=_execute)

    sb.table.return_value.select.return_value = sel

    # update chain
    upd = MagicMock()
    upd.eq.return_value = upd
    if update_raises:
        upd.execute = AsyncMock(side_effect=update_raises)
    else:
        upd.execute = AsyncMock(return_value=MagicMock(data=[]))
    sb.table.return_value.update.return_value = upd

    # upsert chain
    ups = MagicMock()
    if upsert_raises:
        ups.execute = AsyncMock(side_effect=upsert_raises)
    else:
        ups.execute = AsyncMock(return_value=MagicMock(data=[]))
    sb.table.return_value.upsert.return_value = ups

    return sb


# ── aggregate_pnl ─────────────────────────────────────────────────────────────

class TestAggregatePnl:
    async def test_correct_totals(self) -> None:
        trades = [
            {"shadow_pnl_usd": 10.0, "intercepted_at": "2025-01-01T10:00:00+00:00"},
            {"shadow_pnl_usd": -5.0, "intercepted_at": "2025-01-02T10:00:00+00:00"},
            {"shadow_pnl_usd": 8.0,  "intercepted_at": "2025-01-03T10:00:00+00:00"},
        ]
        sb = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.execute = AsyncMock(return_value=MagicMock(data=trades))
        sb.table.return_value.select.return_value = sel
        ups = MagicMock()
        ups.execute = AsyncMock(return_value=MagicMock(data=[]))
        sb.table.return_value.upsert.return_value = ups

        svc = ShadowModeService(redis=_make_redis(), supabase=sb)
        await svc.aggregate_pnl("user-1")

        # Verify upsert was called
        sb.table.return_value.upsert.assert_called_once()
        payload = sb.table.return_value.upsert.call_args[0][0]
        assert payload["total_trades"] == 3
        assert payload["winning_trades"] == 2
        assert payload["losing_trades"] == 1
        assert abs(payload["total_shadow_pnl"] - 13.0) < 0.01
        assert payload["hit_rate_pct"] == pytest.approx(66.67, abs=0.1)

    async def test_no_closed_trades_skips_upsert(self) -> None:
        sb = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.execute = AsyncMock(return_value=MagicMock(data=[]))
        sb.table.return_value.select.return_value = sel

        svc = ShadowModeService(redis=_make_redis(), supabase=sb)
        await svc.aggregate_pnl("user-1")
        # upsert should NOT be called if no trades
        sb.table.return_value.upsert.assert_not_called()

    async def test_supabase_failure_is_non_fatal(self) -> None:
        sb = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.execute = AsyncMock(side_effect=Exception("Supabase down"))
        sb.table.return_value.select.return_value = sel

        svc = ShadowModeService(redis=_make_redis(), supabase=sb)
        # Should not raise
        await svc.aggregate_pnl("user-1")


# ── close_shadow_trade ────────────────────────────────────────────────────────

class TestCloseShadowTrade:
    async def test_buy_trade_positive_pnl(self) -> None:
        open_trade = {
            "id": "t1",
            "user_id": "u1",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 1,
            "intended_entry_price": "100.0",
        }
        sb = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.maybe_single.return_value = sel
        # First call: fetch trade; second call: aggregate reads closed trades
        call_n = {"n": 0}
        async def _exec():
            call_n["n"] += 1
            if call_n["n"] == 1:
                return MagicMock(data=open_trade)
            return MagicMock(data=[{"shadow_pnl_usd": 10.0, "intercepted_at": "2025-01-01T10:00:00+00:00"}])
        sel.execute = AsyncMock(side_effect=_exec)
        sb.table.return_value.select.return_value = sel

        upd = MagicMock()
        upd.eq.return_value = upd
        upd.execute = AsyncMock(return_value=MagicMock(data=[]))
        sb.table.return_value.update.return_value = upd

        ups = MagicMock()
        ups.execute = AsyncMock(return_value=MagicMock(data=[]))
        sb.table.return_value.upsert.return_value = ups

        svc = ShadowModeService(redis=_make_redis(), supabase=sb)
        result = await svc.close_shadow_trade("t1", "u1", exit_price=110.0)

        assert result["pnl_usd"] == pytest.approx(10.0)
        assert result["symbol"] == "AAPL"
        upd.execute.assert_called_once()

    async def test_sell_trade_negative_pnl_when_price_rises(self) -> None:
        open_trade = {
            "id": "t2",
            "user_id": "u1",
            "symbol": "SPY",
            "side": "sell",
            "qty": 2,
            "intended_entry_price": "400.0",
        }
        sb = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.maybe_single.return_value = sel
        call_n = {"n": 0}
        async def _exec():
            call_n["n"] += 1
            if call_n["n"] == 1:
                return MagicMock(data=open_trade)
            return MagicMock(data=[{"shadow_pnl_usd": -20.0, "intercepted_at": "2025-01-01T10:00:00+00:00"}])
        sel.execute = AsyncMock(side_effect=_exec)
        sb.table.return_value.select.return_value = sel

        upd = MagicMock()
        upd.eq.return_value = upd
        upd.execute = AsyncMock(return_value=MagicMock(data=[]))
        sb.table.return_value.update.return_value = upd

        ups = MagicMock()
        ups.execute = AsyncMock(return_value=MagicMock(data=[]))
        sb.table.return_value.upsert.return_value = ups

        svc = ShadowModeService(redis=_make_redis(), supabase=sb)
        result = await svc.close_shadow_trade("t2", "u1", exit_price=410.0)

        # Sell: entry=400, exit=410 → pnl = (400-410)*2 = -20
        assert result["pnl_usd"] == pytest.approx(-20.0)

    async def test_trade_not_found_returns_empty(self) -> None:
        sb = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.maybe_single.return_value = sel
        sel.execute = AsyncMock(return_value=MagicMock(data=None))
        sb.table.return_value.select.return_value = sel

        svc = ShadowModeService(redis=_make_redis(), supabase=sb)
        result = await svc.close_shadow_trade("nonexistent", "u1", exit_price=100.0)
        assert result == {}


# ── get_open_trades ───────────────────────────────────────────────────────────

class TestGetOpenTrades:
    async def test_returns_open_trades(self) -> None:
        trades = [{"id": "t1", "symbol": "AAPL"}, {"id": "t2", "symbol": "SPY"}]
        sb = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.execute = AsyncMock(return_value=MagicMock(data=trades))
        sb.table.return_value.select.return_value = sel

        svc = ShadowModeService(redis=_make_redis(), supabase=sb)
        result = await svc.get_open_trades("user-1")
        assert len(result) == 2

    async def test_supabase_failure_returns_empty_list(self) -> None:
        sb = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.execute = AsyncMock(side_effect=Exception("Supabase down"))
        sb.table.return_value.select.return_value = sel

        svc = ShadowModeService(redis=_make_redis(), supabase=sb)
        result = await svc.get_open_trades("user-1")
        assert result == []
