"""Tests for regime detector — pure-Python indicator logic + caching."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.trading.regime import (
    RegimeResult,
    _ema,
    _rsi,
    _atr_ratio,
    _compute_regime,
    get_regime,
)


# ── Pure indicator tests ──────────────────────────────────────────────────────

def test_ema_basic() -> None:
    # 5-period EMA on a flat series should equal the series value
    values = [100.0] * 20
    assert abs(_ema(values, 5) - 100.0) < 0.001


def test_ema_short_series_returns_last() -> None:
    assert _ema([50.0, 60.0], 10) == 60.0


def test_rsi_all_gains_returns_100() -> None:
    # All up days → RSI = 100
    closes = [float(i) for i in range(1, 20)]
    rsi = _rsi(closes, 14)
    assert rsi == 100.0


def test_rsi_all_losses_returns_0() -> None:
    closes = [float(20 - i) for i in range(20)]
    rsi = _rsi(closes, 14)
    assert rsi == 0.0


def test_rsi_short_series_returns_50() -> None:
    # Not enough data → default 50
    assert _rsi([100.0, 101.0], 14) == 50.0


def test_atr_ratio_flat_market() -> None:
    n = 25
    highs = [101.0] * n
    lows = [99.0] * n
    closes = [100.0] * n
    atr_now, atr_avg = _atr_ratio(highs, lows, closes, 20)
    assert abs(atr_now - 2.0) < 0.01  # last TR = high - low = 2
    assert abs(atr_avg - 2.0) < 0.01


def test_atr_ratio_single_bar_returns_zeros() -> None:
    atr_now, atr_avg = _atr_ratio([105.0], [95.0], [100.0], 20)
    assert atr_now == 0.0
    assert atr_avg == 0.0


# ── Regime classification ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_regime_cache_hit() -> None:
    cached_payload = json.dumps({
        "regime": "TRENDING_UP",
        "detail": {"ema20": 450.0, "rsi": 60.0},
        "computed_at": "2024-01-01T09:31:00+00:00",
    })
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached_payload)
    redis.set = AsyncMock()

    result = await get_regime(redis)

    assert result.regime == "TRENDING_UP"
    redis.set.assert_not_called()


@pytest.mark.asyncio
async def test_get_regime_cache_miss_fetches_spy() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    # Build a trending-up SPY dataset (60 bars, price rising above EMA50)
    base = 450.0
    bars = []
    for i in range(60):
        close = base + i * 0.5  # steady uptrend
        bars.append({"open": close - 0.2, "high": close + 0.5, "low": close - 0.5, "close": close})

    with patch("src.trading.regime._fetch_spy_bars", return_value=bars):
        result = await get_regime(redis)

    assert result.regime in {"TRENDING_UP", "CHOPPY", "HIGH_VOL", "RISK_OFF", "TRENDING_DOWN"}
    redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_get_regime_insufficient_bars_returns_choppy() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    with patch("src.trading.regime._fetch_spy_bars", return_value=[{"open": 400, "high": 401, "low": 399, "close": 400}]):
        result = await get_regime(redis)

    assert result.regime == "CHOPPY"


@pytest.mark.asyncio
async def test_get_regime_risk_off_on_large_drop() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    # Build 60 bars, last bar drops 2% from open → RISK_OFF
    bars = []
    for i in range(59):
        close = 450.0
        bars.append({"open": close, "high": close + 1, "low": close - 1, "close": close})
    # Last bar: open 450, close 441 (-2%)
    bars.append({"open": 450.0, "high": 450.0, "low": 440.0, "close": 441.0})

    with patch("src.trading.regime._fetch_spy_bars", return_value=bars):
        result = await get_regime(redis)

    assert result.regime == "RISK_OFF"
