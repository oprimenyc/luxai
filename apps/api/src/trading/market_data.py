"""Market data ingestion — quotes, bars, and volatility from Alpaca Data API."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import json
import structlog
import websockets
from websockets.client import WebSocketClientProtocol

from src.trading.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from src.trading.models import Bar, OptionsChain, OptionType, Quote

log = structlog.get_logger(__name__)

_ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
_ALPACA_OPTIONS_BASE = "https://data.alpaca.markets/v1beta1"
_ALPACA_STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"

_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0


class MarketDataClient:
    """
    Lightweight async market data client for Alpaca Data API.

    All data is fetched read-only — no order submission goes through here.

    HTTP requests use:
    - Circuit breaker (fast-fail when Alpaca data API is down)
    - Retry with exponential backoff for transient errors

    WebSocket connection uses exponential backoff on disconnect.
    """

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Accept": "application/json",
        }
        self._client: httpx.AsyncClient | None = None
        self._ws: WebSocketClientProtocol | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._ws_callback: Any = None

        self._data_circuit = CircuitBreaker(
            "alpaca_data_api",
            failure_threshold=5,
            recovery_timeout=30.0,
        )

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
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        if self._client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("MarketDataClient not connected — call connect() first")
        return self._client

    # ── Resilient HTTP helper ────────────────────────────────────────────────

    async def _request(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET request with circuit breaker + exponential-backoff retry."""
        async def _attempt() -> httpx.Response:
            last_exc: Exception | None = None

            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await self._http().get(url, **kwargs)
                    if resp.status_code in _RETRYABLE_STATUS:
                        raise httpx.HTTPStatusError(
                            f"Retryable HTTP {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                    resp.raise_for_status()
                    return resp
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in _RETRYABLE_STATUS:
                        last_exc = exc
                        if attempt < _MAX_RETRIES - 1:
                            delay = _RETRY_BASE_DELAY * (2 ** attempt)
                            log.warning(
                                "market_data_retry",
                                url=url,
                                status=exc.response.status_code,
                                attempt=attempt + 1,
                                delay=delay,
                            )
                            await asyncio.sleep(delay)
                        continue
                    raise
                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_exc = exc
                    if attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        log.warning(
                            "market_data_network_retry",
                            url=url,
                            error=str(exc),
                            attempt=attempt + 1,
                            delay=delay,
                        )
                        await asyncio.sleep(delay)

            assert last_exc is not None
            raise last_exc

        return await self._data_circuit.call(_attempt())

    # ── Streaming ────────────────────────────────────────────────────────────

    async def subscribe_quotes(self, symbols: list[str], callback: Any) -> None:
        """Subscribe to real-time quotes via WebSocket."""
        self._ws_callback = callback
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        self._ws_task = asyncio.create_task(
            self._ws_loop(symbols), name=f"alpaca_ws:{','.join(symbols[:3])}"
        )

    async def _ws_loop(self, symbols: list[str]) -> None:
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(_ALPACA_STREAM_URL) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({
                        "action": "auth",
                        "key": self._api_key,
                        "secret": self._api_secret,
                    }))
                    # Drain auth response
                    await ws.recv()

                    await ws.send(json.dumps({
                        "action": "subscribe",
                        "quotes": symbols,
                    }))

                    backoff = 1.0  # reset on successful connect
                    log.info("alpaca_ws_connected", symbols=symbols)

                    async for msg in ws:
                        data = json.loads(msg)
                        for ev in data:
                            if ev.get("T") == "q" and self._ws_callback:
                                bid = float(ev.get("bp", 0.0))
                                ask = float(ev.get("ap", 0.0))
                                # Use mid as mark price — conservative for both long
                                # and short, avoids pure bid/ask skew in risk checks.
                                mid = (bid + ask) / 2.0 if (bid + ask) > 0 else bid
                                q = Quote(
                                    symbol=ev["S"],
                                    bid=bid,
                                    ask=ask,
                                    bid_size=ev.get("bs", 0),
                                    ask_size=ev.get("as", 0),
                                    last=mid,
                                    volume=0,
                                    timestamp=(
                                        datetime.fromisoformat(ev["t"].replace("Z", "+00:00"))
                                        if "t" in ev
                                        else datetime.now(UTC)
                                    ),
                                )
                                await self._ws_callback(q)
            except asyncio.CancelledError:
                self._ws = None
                break
            except Exception as exc:
                self._ws = None
                log.warning("alpaca_ws_disconnected", error=str(exc), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    # ── Quotes ───────────────────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Quote:
        resp = await self._request(
            f"{_ALPACA_DATA_BASE}/stocks/{symbol}/quotes/latest",
        )
        data = resp.json().get("quote", {})
        bid = data.get("bp", 0.0)
        ask = data.get("ap", 0.0)
        mid = (bid + ask) / 2.0 if (bid + ask) > 0 else bid
        ts_raw = data.get("t")
        ts = (
            datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts_raw
            else datetime.now(UTC)
        )
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            bid_size=data.get("bs", 0),
            ask_size=data.get("as", 0),
            last=mid,
            volume=0,
            timestamp=ts,
        )

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Bulk quote fetch — returns a dict keyed by symbol."""
        resp = await self._request(
            f"{_ALPACA_DATA_BASE}/stocks/quotes/latest",
            params={"symbols": ",".join(symbols)},
        )
        quotes: dict[str, Quote] = {}
        for sym, data in resp.json().get("quotes", {}).items():
            bid = data.get("bp", 0.0)
            ask = data.get("ap", 0.0)
            mid = (bid + ask) / 2.0 if (bid + ask) > 0 else bid
            ts_raw = data.get("t")
            ts = (
                datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts_raw
                else datetime.now(UTC)
            )
            quotes[sym] = Quote(
                symbol=sym,
                bid=bid,
                ask=ask,
                bid_size=data.get("bs", 0),
                ask_size=data.get("as", 0),
                last=mid,
                volume=0,
                timestamp=ts,
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
        resp = await self._request(
            f"{_ALPACA_DATA_BASE}/stocks/{symbol}/bars",
            params={
                "timeframe": timeframe,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": limit,
                "adjustment": "split",
            },
        )
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

        resp = await self._request(
            f"{_ALPACA_OPTIONS_BASE}/options/snapshots/{underlying}",
            params=params,
        )
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
                expiration=date.fromisoformat(
                    details.get("expiration_date", expiration.isoformat())
                ),
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
