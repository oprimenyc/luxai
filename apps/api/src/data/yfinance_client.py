"""
Path: apps/api/src/data/yfinance_client.py
Security: Read-only. No credentials required. yfinance fetches public market data.
          Cache keys are non-sensitive (symbol + data type). No PII stored.
Scale: Single-tenant. Cache TTLs tuned for free-tier usage patterns.
       yfinance is best-effort — 15-min delayed data, no SLA guarantees.

yfinance client with Redis caching for LuxAI free data stack.

Replaces Alpha Vantage / FMP for price and fundamental data.
Tradier remains authoritative for options chains (already connected).

Cache TTLs:
  Quote:       60 seconds  (near-real-time for scanner pre-filter)
  Historical:  4 hours     (bars don't change intraday)
  Options:     60 seconds  (chains update frequently)
  Earnings:    24 hours    (quarterly events)
  Insiders:    24 hours    (SEC filings lag by days)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, UTC
from typing import Any, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis

log = structlog.get_logger(__name__)

_TTL_QUOTE = 60
_TTL_HISTORY = 4 * 3600
_TTL_OPTIONS = 60
_TTL_EARNINGS = 24 * 3600
_TTL_INSIDERS = 24 * 3600


class YFinanceClient:
    """
    Async-friendly yfinance wrapper with Redis caching.

    All yfinance calls are synchronous and run via asyncio.run_in_executor
    to avoid blocking the event loop.

    Graceful degradation: if yfinance raises any exception, the method
    returns None/empty rather than propagating — callers must handle
    missing data rather than assuming it is always available.
    """

    def __init__(self, redis: "aioredis.Redis") -> None:
        self._redis = redis

    # ── Quote (15-min delayed) ────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> dict[str, Any] | None:
        """Return latest price data for symbol. Cached 60 seconds."""
        key = f"yf:quote:{symbol}"
        cached = await self._redis.get(key)
        if cached:
            return json.loads(cached)

        data = await self._run_sync(_fetch_quote, symbol)
        if data:
            await self._redis.set(key, json.dumps(data), ex=_TTL_QUOTE)
        return data

    async def get_price(self, symbol: str) -> float | None:
        """Return last close price. Used by scanner pre-filter."""
        quote = await self.get_quote(symbol)
        if quote:
            return quote.get("regularMarketPrice") or quote.get("currentPrice")
        return None

    async def get_previous_close(self, symbol: str) -> float | None:
        """Return previous close for movement calculation."""
        quote = await self.get_quote(symbol)
        if quote:
            return quote.get("regularMarketPreviousClose") or quote.get("previousClose")
        return None

    async def price_moved_pct(self, symbol: str) -> float | None:
        """Return % price change from previous close. None on data failure."""
        quote = await self.get_quote(symbol)
        if not quote:
            return None
        current = quote.get("regularMarketPrice") or quote.get("currentPrice")
        prev = quote.get("regularMarketPreviousClose") or quote.get("previousClose")
        if current and prev and prev != 0:
            return abs((current - prev) / prev) * 100.0
        return None

    # ── Historical OHLCV ─────────────────────────────────────────────────────

    async def get_bars(
        self,
        symbol: str,
        period: str = "3mo",
        interval: str = "1d",
    ) -> list[dict[str, Any]]:
        """Return OHLCV bars. Cached 4 hours."""
        key = f"yf:bars:{symbol}:{period}:{interval}"
        cached = await self._redis.get(key)
        if cached:
            return json.loads(cached)

        data = await self._run_sync(_fetch_bars, symbol, period, interval)
        if data:
            await self._redis.set(key, json.dumps(data), ex=_TTL_HISTORY)
        return data or []

    # ── Options chain ─────────────────────────────────────────────────────────

    async def get_options_expiries(self, symbol: str) -> list[str]:
        """Return available options expiry dates. Cached 60 seconds."""
        key = f"yf:options:expiries:{symbol}"
        cached = await self._redis.get(key)
        if cached:
            return json.loads(cached)

        data = await self._run_sync(_fetch_options_expiries, symbol)
        if data:
            await self._redis.set(key, json.dumps(data), ex=_TTL_OPTIONS)
        return data or []

    # ── Earnings dates ────────────────────────────────────────────────────────

    async def get_earnings_dates(self, symbol: str) -> list[str]:
        """Return upcoming earnings dates as ISO strings. Cached 24 hours."""
        key = f"yf:earnings:{symbol}"
        cached = await self._redis.get(key)
        if cached:
            return json.loads(cached)

        data = await self._run_sync(_fetch_earnings_dates, symbol)
        if data is None:
            data = []
        await self._redis.set(key, json.dumps(data), ex=_TTL_EARNINGS)
        return data

    # ── Insider transactions ──────────────────────────────────────────────────

    async def get_insider_transactions(self, symbol: str) -> list[dict[str, Any]]:
        """Return recent insider transactions. Cached 24 hours."""
        key = f"yf:insiders:{symbol}"
        cached = await self._redis.get(key)
        if cached:
            return json.loads(cached)

        data = await self._run_sync(_fetch_insiders, symbol)
        if data is None:
            data = []
        await self._redis.set(key, json.dumps(data), ex=_TTL_INSIDERS)
        return data

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    async def _run_sync(fn: Any, *args: Any) -> Any:
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, fn, *args)
        except Exception as exc:
            log.warning("yfinance_error", fn=fn.__name__, error=str(exc)[:80])
            return None


# ── Sync fetch helpers (run in thread pool) ───────────────────────────────────

def _fetch_quote(symbol: str) -> dict[str, Any] | None:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        # fast_info returns a LazyFastInfo object — convert to plain dict
        fields = [
            "lastPrice", "previousClose", "regularMarketPrice",
            "regularMarketPreviousClose", "currentPrice",
            "open", "dayHigh", "dayLow", "volume",
        ]
        result: dict[str, Any] = {}
        for f in fields:
            try:
                v = getattr(info, f, None)
                if v is not None:
                    result[f] = float(v)
            except Exception:
                pass
        # Normalise to common field names used by callers
        if "lastPrice" in result and "regularMarketPrice" not in result:
            result["regularMarketPrice"] = result["lastPrice"]
        if "previousClose" in result and "regularMarketPreviousClose" not in result:
            result["regularMarketPreviousClose"] = result["previousClose"]
        return result if result else None
    except Exception:
        return None


def _fetch_bars(symbol: str, period: str, interval: str) -> list[dict[str, Any]] | None:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)
        if hist.empty:
            return None
        rows = []
        for ts, row in hist.iterrows():
            rows.append({
                "timestamp": ts.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        return rows
    except Exception:
        return None


def _fetch_options_expiries(symbol: str) -> list[str] | None:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        return list(ticker.options)
    except Exception:
        return None


def _fetch_earnings_dates(symbol: str) -> list[str] | None:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None:
            return []
        # calendar is a dict with 'Earnings Date' key (list of Timestamps)
        dates = cal.get("Earnings Date", [])
        return [d.isoformat() if hasattr(d, "isoformat") else str(d) for d in dates]
    except Exception:
        return []


def _fetch_insiders(symbol: str) -> list[dict[str, Any]] | None:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.insider_transactions
        if df is None or df.empty:
            return []
        # Return only last 10 transactions for brevity
        rows = []
        for _, row in df.head(10).iterrows():
            rows.append({
                "date": str(row.get("startDate", "")),
                "insider": str(row.get("filerName", "")),
                "relation": str(row.get("filerRelation", "")),
                "transaction": str(row.get("transactionText", "")),
                "shares": int(row.get("shares", 0)),
                "value": float(row.get("value", 0)) if row.get("value") else 0.0,
            })
        return rows
    except Exception:
        return []
