"""
Path: apps/api/src/trading/regime.py
Security: Read-only. Uses only yfinance SPY data. No LLM calls. No credentials.
Scale: Cached in Redis for 4 hours. Single SPY ticker fetch per cache miss.
       EMA/RSI/ATR computed in pure Python — no pandas dependency required.

Market Regime Detector — classifies current market conditions using SPY OHLCV.

Zero token cost. Zero API cost. Used by scanner to gate strategy selection.

Regimes:
  TRENDING_UP:   price > EMA20 > EMA50, RSI 45–70
  TRENDING_DOWN: price < EMA20 < EMA50, RSI 30–55
  CHOPPY:        price crossing EMA20, RSI 40–60
  HIGH_VOL:      ATR > 1.5x 20-day average
  RISK_OFF:      SPY down > 1.5% at open (checked intraday)

Cache: Redis key `regime:current`, TTL 4 hours.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis

log = structlog.get_logger(__name__)

Regime = Literal["TRENDING_UP", "TRENDING_DOWN", "CHOPPY", "HIGH_VOL", "RISK_OFF"]

_REDIS_KEY = "regime:current"
_REDIS_TTL = 4 * 3600

_EMA_FAST = 20
_EMA_SLOW = 50
_RSI_PERIOD = 14
_ATR_PERIOD = 20
_RISK_OFF_DROP_PCT = 1.5   # SPY down > 1.5% at open
_HIGH_VOL_MULTIPLIER = 1.5


class RegimeResult:
    def __init__(self, regime: Regime, detail: dict[str, float], computed_at: str) -> None:
        self.regime = regime
        self.detail = detail
        self.computed_at = computed_at

    def to_dict(self) -> dict[str, object]:
        return {
            "regime": self.regime,
            "detail": {k: round(v, 4) for k, v in self.detail.items()},
            "computed_at": self.computed_at,
        }


async def get_regime(redis: "aioredis.Redis") -> RegimeResult:
    """
    Return current market regime. Reads from Redis cache when warm.

    Task: not a background task — called synchronously on demand.
    """
    cached = await redis.get(_REDIS_KEY)
    if cached:
        raw = json.loads(cached)
        return RegimeResult(
            regime=raw["regime"],
            detail=raw["detail"],
            computed_at=raw["computed_at"],
        )

    result = await _compute_regime()
    payload = json.dumps(result.to_dict())
    await redis.set(_REDIS_KEY, payload, ex=_REDIS_TTL)
    log.info("regime_computed", regime=result.regime, detail=result.detail)
    return result


async def _compute_regime() -> RegimeResult:
    """Fetch 60 days of SPY bars from yfinance and classify regime."""
    import asyncio
    loop = asyncio.get_event_loop()
    bars = await loop.run_in_executor(None, _fetch_spy_bars)

    computed_at = datetime.now(UTC).isoformat()

    if len(bars) < _EMA_SLOW + 5:
        log.warning("regime_insufficient_bars", n=len(bars))
        return RegimeResult(regime="CHOPPY", detail={}, computed_at=computed_at)

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    opens = [b["open"] for b in bars]

    ema20 = _ema(closes, _EMA_FAST)
    ema50 = _ema(closes, _EMA_SLOW)
    rsi = _rsi(closes, _RSI_PERIOD)
    atr_now, atr_avg = _atr_ratio(highs, lows, closes, _ATR_PERIOD)
    current = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else current
    today_open = opens[-1]

    pct_from_open = (current - today_open) / today_open * 100 if today_open else 0.0
    pct_from_prev = (current - prev_close) / prev_close * 100 if prev_close else 0.0

    detail = {
        "price": current,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr_now,
        "atr_avg": atr_avg,
        "pct_from_open": pct_from_open,
        "pct_from_prev": pct_from_prev,
    }

    # Priority order: RISK_OFF > HIGH_VOL > TRENDING > CHOPPY
    if pct_from_prev <= -_RISK_OFF_DROP_PCT or pct_from_open <= -_RISK_OFF_DROP_PCT:
        return RegimeResult(regime="RISK_OFF", detail=detail, computed_at=computed_at)

    if atr_avg > 0 and atr_now > _HIGH_VOL_MULTIPLIER * atr_avg:
        return RegimeResult(regime="HIGH_VOL", detail=detail, computed_at=computed_at)

    if current > ema20 > ema50 and 45 <= rsi <= 70:
        return RegimeResult(regime="TRENDING_UP", detail=detail, computed_at=computed_at)

    if current < ema20 < ema50 and 30 <= rsi <= 55:
        return RegimeResult(regime="TRENDING_DOWN", detail=detail, computed_at=computed_at)

    return RegimeResult(regime="CHOPPY", detail=detail, computed_at=computed_at)


def _fetch_spy_bars() -> list[dict[str, float]]:
    try:
        import yfinance as yf
        ticker = yf.Ticker("SPY")
        hist = ticker.history(period="3mo", interval="1d")
        if hist.empty:
            return []
        rows = []
        for _, row in hist.iterrows():
            rows.append({
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
            })
        return rows
    except Exception as exc:
        log.warning("regime_spy_fetch_failed", error=str(exc)[:80])
        return []


# ── Pure-Python technical indicators ─────────────────────────────────────────

def _ema(values: list[float], period: int) -> float:
    """Exponential moving average — returns final value."""
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: list[float], period: int) -> float:
    """Wilder RSI — returns current RSI value (0–100)."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def _atr_ratio(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int,
) -> tuple[float, float]:
    """
    Return (current_atr, period_avg_atr).
    current_atr = most recent true range.
    period_avg_atr = simple average of last `period` true ranges.
    """
    if len(closes) < 2:
        return 0.0, 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if not trs:
        return 0.0, 0.0
    current_atr = trs[-1]
    avg_atr = sum(trs[-period:]) / len(trs[-period:]) if len(trs) >= period else sum(trs) / len(trs)
    return current_atr, avg_atr
