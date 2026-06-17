"""Tests for scanner pre-filter logic (movement threshold + agent gating)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.scanner import MarketScannerService, _next_friday_in_range, is_market_day
from datetime import date


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    # Expose connection_pool for legacy code path still used in scanner
    pool = MagicMock()
    pool.connection_kwargs = {"path": ""}
    redis.connection_pool = pool
    return redis


def _make_supabase() -> AsyncMock:
    mock = AsyncMock()
    mock.table = MagicMock(return_value=MagicMock(
        insert=MagicMock(return_value=MagicMock(execute=AsyncMock()))
    ))
    return mock


def _make_scanner(**kwargs) -> MarketScannerService:
    return MarketScannerService(
        redis=_make_redis(),
        supabase=_make_supabase(),
        tradier_api_key="test-tradier",
        alpaca_api_key="test-alpaca",
        alpaca_api_secret="test-secret",
        deepseek_api_key=kwargs.get("deepseek_api_key", ""),
        anthropic_api_key=kwargs.get("anthropic_api_key", ""),
    )


# ── is_market_day ─────────────────────────────────────────────────────────────

def test_is_market_day_weekday() -> None:
    monday = date(2024, 1, 8)
    assert is_market_day(monday) is True


def test_is_market_day_saturday() -> None:
    saturday = date(2024, 1, 6)
    assert is_market_day(saturday) is False


def test_is_market_day_sunday() -> None:
    sunday = date(2024, 1, 7)
    assert is_market_day(sunday) is False


# ── _next_friday_in_range ─────────────────────────────────────────────────────

def test_next_friday_in_range_finds_friday() -> None:
    today = date(2024, 1, 8)  # Monday
    friday = _next_friday_in_range(today, min_dte=7, max_dte=21)
    assert friday is not None
    assert friday.weekday() == 4  # Friday


def test_next_friday_in_range_returns_none_when_no_friday() -> None:
    # Very narrow range that skips all Fridays
    today = date(2024, 1, 12)  # Friday itself
    result = _next_friday_in_range(today, min_dte=1, max_dte=3)
    assert result is None


# ── Pre-filter: low-movement symbols are skipped ──────────────────────────────

@pytest.mark.asyncio
async def test_scan_symbol_skipped_on_low_movement() -> None:
    """Symbols with < 0.5% movement return 0 without calling TradingAgents."""
    scanner = _make_scanner(deepseek_api_key="fake-key")

    # Return 0.1% movement — below threshold
    with patch(
        "src.data.yfinance_client.YFinanceClient.price_moved_pct",
        new_callable=AsyncMock,
        return_value=0.1,
    ):
        result = await scanner._scan_symbol("SPY", "test-user")

    assert result == 0


@pytest.mark.asyncio
async def test_scan_symbol_proceeds_on_high_movement() -> None:
    """Symbols with >= 0.5% movement proceed to TradingAgents (mocked)."""
    from src.agents.trading_agents_adapter import AgentVerdict

    scanner = _make_scanner(deepseek_api_key="fake-key")

    neutral_verdict = AgentVerdict(
        "NVDA", "NEUTRAL", 0.50, "unclear", {}, "2024-01-01", 0, 0
    )

    with (
        patch(
            "src.data.yfinance_client.YFinanceClient.price_moved_pct",
            new_callable=AsyncMock,
            return_value=1.5,  # above threshold
        ),
        patch(
            "src.agents.trading_agents_adapter.TradingAgentsAdapter.run_debate",
            new_callable=AsyncMock,
            return_value=neutral_verdict,
        ),
        patch(
            "src.agents.trading_agents_adapter.TradingAgentsAdapter.log_debate_to_supabase",
            new_callable=AsyncMock,
        ),
    ):
        # Neutral verdict → no shadow trade created
        result = await scanner._scan_symbol("NVDA", "test-user")

    assert result == 0  # NEUTRAL verdict, no shadow trade


@pytest.mark.asyncio
async def test_scan_symbol_no_deepseek_key_skips_debate() -> None:
    """Without a DeepSeek key, scanner falls through to price fetch (no debate)."""
    scanner = _make_scanner(deepseek_api_key="")  # no key

    with (
        patch(
            "src.data.yfinance_client.YFinanceClient.price_moved_pct",
            new_callable=AsyncMock,
            return_value=2.0,
        ),
        patch(
            "src.data.yfinance_client.YFinanceClient.get_price",
            new_callable=AsyncMock,
            return_value=None,  # no price → exit early
        ),
    ):
        result = await scanner._scan_symbol("SPY", "test-user")

    assert result == 0  # no price → no shadow trade
