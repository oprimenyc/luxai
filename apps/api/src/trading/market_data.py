"""Market data ingestion — quotes, bars, and volatility from Alpaca Data API."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import structlog

from src.trading.models import Bar, OptionsChain, OptionType, Quote

log = structlog.get_logger(__name__)

_ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
_ALPACA_OPTIONS_BASE = "https://data.alpaca.markets/v1beta1"


class MarketDataClient:
    """
    Lightweight async market data client for Alpaca Data API.

    All data is fetched read-only — no order submission goes through here.
    The class is safe to use concurrently.
    """

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Accept": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> MarketDataClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(10.0),
        )

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("MarketDataClient not connected — call connect() first")
        return self._client

    # ── Quotes ───────────────────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Quote:
        resp = await self._http().get(
            f"{_ALPACA_DATA_BASE}/stocks/{symbol}/quotes/latest",
        )
        resp.raise_for_status()
        data = resp.json().get("quote", {})
        return Quote(
            symbol=symbol,
            bid=data.get("bp", 0.0),
            ask=data.get("ap", 0.0),
            bid_size=data.get("bs", 0),
            ask_size=data.get("as", 0),
            last=data.get("bp", 0.0),  # use bid as last proxy if trade not available
            volume=0,
            timestamp=datetime.fromisoformat(data.get("t", datetime.now(UTC).isoformat())),
        )

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Bulk quote fetch — returns a dict keyed by symbol."""
        resp = await self._http().get(
            f"{_ALPACA_DATA_BASE}/stocks/quotes/latest",
            params={"symbols": ",".join(symbols)},
        )
        resp.raise_for_status()
        quotes: dict[str, Quote] = {}
        for sym, data in resp.json().get("quotes", {}).items():
            quotes[sym] = Quote(
                symbol=sym,
                bid=data.get("bp", 0.0),
                ask=data.get("ap", 0.0),
                bid_size=data.get("bs", 0),
                ask_size=data.get("as", 0),
                last=data.get("bp", 0.0),
                volume=0,
                timestamp=datetime.fromisoformat(data.get("t", datetime.now(UTC).isoformat())),
            )
        return quotes

    # ── Bars / OHLCV ─────────────────────────────────────────────────────────

    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        end = end or datetime.now(UTC)
        start = start or (end - timedelta(days=limit))
        resp = await self._http().get(
            f"{_ALPACA_DATA_BASE}/stocks/{symbol}/bars",
            params={
                "timeframe": timeframe,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": limit,
                "adjustment": "split",
            },
        )
        resp.raise_for_status()
        bars = []
        for raw in resp.json().get("bars", []):
            bars.append(Bar(
                symbol=symbol,
                timestamp=datetime.fromisoformat(raw["t"]),
                open=raw["o"],
                high=raw["h"],
                low=raw["l"],
                close=raw["c"],
                volume=raw["v"],
                vwap=raw.get("vw"),
                trade_count=raw.get("n"),
            ))
        return bars

    # ── Options chain ─────────────────────────────────────────────────────────

    async def get_options_chain(
        self,
        underlying: str,
        expiration: date,
        option_type: OptionType | None = None,
    ) -> OptionsChain:
        """
        Fetch options chain from Alpaca Options Data API.
        Returns OptionsChain with Greeks populated where available.
        """
        from src.trading.models import Greeks, OptionContract, OptionsChain

        params: dict[str, Any] = {
            "expiration_date": expiration.isoformat(),
            "underlying_symbols": underlying,
            "limit": 500,
        }
        if option_type:
            params["type"] = option_type.value

        resp = await self._http().get(
            f"{_ALPACA_OPTIONS_BASE}/options/snapshots/{underlying}",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

        # Fetch underlying price
        quote = await self.get_quote(underlying)

        calls: list[OptionContract] = []
        puts: list[OptionContract] = []

        for symbol, snap in data.get("snapshots", {}).items():
            details = snap.get("details", {})
            greeks_raw = snap.get("greeks", {})
            quote_raw = snap.get("latestQuote", {})

            contract = OptionContract(
                symbol=symbol,
                underlying=underlying,
                option_type=OptionType(details.get("type", "call")),
                strike=float(details.get("strike_price", 0)),
                expiration=date.fromisoformat(details.get("expiration_date", expiration.isoformat())),
                bid=quote_raw.get("bp", 0.0),
                ask=quote_raw.get("ap", 0.0),
                last=quote_raw.get("bp", 0.0),
                volume=snap.get("latestTrade", {}).get("s", 0),
                open_interest=snap.get("openInterest", 0),
                greeks=Greeks(
                    delta=greeks_raw.get("delta"),
                    gamma=greeks_raw.get("gamma"),
                    theta=greeks_raw.get("theta"),
                    vega=greeks_raw.get("vega"),
                    rho=greeks_raw.get("rho"),
                    iv=snap.get("impliedVolatility"),
                ),
            )
            if contract.option_type == OptionType.CALL:
                calls.append(contract)
            else:
                puts.append(contract)

        calls.sort(key=lambda c: c.strike)
        puts.sort(key=lambda c: c.strike)

        return OptionsChain(
            underlying=underlying,
            expiration=expiration,
            underlying_price=quote.last,
            calls=calls,
            puts=puts,
        )

    # ── Volatility helpers ───────────────────────────────────────────────────

    async def historical_volatility(
        self,
        symbol: str,
        window_days: int = 21,
    ) -> float:
        """Annualised historical volatility (close-to-close) over window_days."""
        import math
        bars = await self.get_bars(symbol, timeframe="1Day", limit=window_days + 5)
        if len(bars) < 2:
            return 0.0
        closes = [b.close for b in bars[-window_days:]]
        log_returns = [
            math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
        ]
        n = len(log_returns)
        mean = sum(log_returns) / n
        variance = sum((r - mean) ** 2 for r in log_returns) / (n - 1)
        daily_vol = math.sqrt(variance)
        return daily_vol * math.sqrt(252)  # annualise
