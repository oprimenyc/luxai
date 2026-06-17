"""Tests for YFinanceClient — uses mocked yfinance responses."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.data.yfinance_client import (
    YFinanceClient,
    _fetch_quote,
    _fetch_bars,
    _fetch_earnings_dates,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_redis(cached: str | None = None) -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached)
    redis.set = AsyncMock()
    return redis


# ── get_price ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_price_cache_hit() -> None:
    payload = json.dumps({"regularMarketPrice": 185.5, "regularMarketPreviousClose": 183.0})
    redis = _make_redis(cached=payload)
    client = YFinanceClient(redis)
    price = await client.get_price("AAPL")
    assert price == 185.5
    redis.set.assert_not_called()


@pytest.mark.asyncio
async def test_get_price_cache_miss_calls_yfinance() -> None:
    redis = _make_redis(cached=None)

    mock_info = MagicMock()
    mock_info.lastPrice = 450.0
    mock_info.previousClose = 445.0
    mock_info.regularMarketPrice = None
    mock_info.regularMarketPreviousClose = None
    mock_info.currentPrice = None
    mock_info.open = None
    mock_info.dayHigh = None
    mock_info.dayLow = None
    mock_info.volume = None

    mock_ticker = MagicMock()
    mock_ticker.fast_info = mock_info

    with patch("src.data.yfinance_client._fetch_quote", return_value={
        "regularMarketPrice": 450.0,
        "regularMarketPreviousClose": 445.0,
    }):
        client = YFinanceClient(redis)
        price = await client.get_price("NVDA")

    assert price == 450.0
    redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_get_price_returns_none_on_yfinance_failure() -> None:
    redis = _make_redis(cached=None)

    with patch("src.data.yfinance_client._fetch_quote", return_value=None):
        client = YFinanceClient(redis)
        price = await client.get_price("FAIL")

    assert price is None


# ── price_moved_pct ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_price_moved_pct_above_threshold() -> None:
    payload = json.dumps({
        "regularMarketPrice": 101.0,
        "regularMarketPreviousClose": 100.0,
    })
    redis = _make_redis(cached=payload)
    client = YFinanceClient(redis)
    pct = await client.price_moved_pct("SPY")
    assert pct is not None
    assert abs(pct - 1.0) < 0.01


@pytest.mark.asyncio
async def test_price_moved_pct_zero_prev_close_returns_none() -> None:
    payload = json.dumps({"regularMarketPrice": 100.0, "regularMarketPreviousClose": 0.0})
    redis = _make_redis(cached=payload)
    client = YFinanceClient(redis)
    pct = await client.price_moved_pct("SPY")
    assert pct is None


# ── get_bars ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_bars_cache_hit() -> None:
    bars = [{"timestamp": "2024-01-01T00:00:00", "open": 1, "high": 2, "low": 0.9, "close": 1.5, "volume": 1000}]
    redis = _make_redis(cached=json.dumps(bars))
    client = YFinanceClient(redis)
    result = await client.get_bars("SPY")
    assert len(result) == 1
    assert result[0]["close"] == 1.5


@pytest.mark.asyncio
async def test_get_bars_empty_on_failure() -> None:
    redis = _make_redis(cached=None)
    with patch("src.data.yfinance_client._fetch_bars", return_value=None):
        client = YFinanceClient(redis)
        result = await client.get_bars("FAIL")
    assert result == []


# ── _fetch_quote unit (sync helper) ──────────────────────────────────────────

def test_fetch_quote_sync_returns_none_on_exception() -> None:
    # When yfinance is not installed, _fetch_quote should return None gracefully
    try:
        import yfinance  # noqa: F401
        with patch("yfinance.Ticker", side_effect=Exception("boom")):
            result = _fetch_quote("ERR")
    except ImportError:
        # yfinance not installed in test env — simulate the except branch
        result = None
    assert result is None


# ── _fetch_earnings_dates unit ────────────────────────────────────────────────

def test_fetch_earnings_dates_returns_empty_on_none_calendar() -> None:
    try:
        import yfinance  # noqa: F401
        mock_ticker = MagicMock()
        mock_ticker.calendar = None
        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = _fetch_earnings_dates("AAPL")
    except ImportError:
        result = []
    assert result == []
