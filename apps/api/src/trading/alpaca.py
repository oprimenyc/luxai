"""Alpaca paper trading broker adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import httpx
import structlog

from src.core.startup_checks import AlpacaPaperModeError, resolve_paper_account
from src.trading.broker import BrokerABC
from src.trading.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from src.trading.market_data import MarketDataClient
from src.trading.models import (
    AssetClass,
    ExecutionMode,
    Fill,
    OptionsChain,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    Position,
    Quote,
    TimeInForce,
)

log = structlog.get_logger(__name__)

_PAPER_BASE = "https://paper-api.alpaca.markets/v2"

# HTTP status codes that are transient and worth retrying.
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt (1s, 2s, 4s)


class AlpacaPaperBroker(BrokerABC):
    """
    Alpaca paper trading adapter.

    ALWAYS connects to paper-api.alpaca.markets — never live.
    Any attempt to change the base URL to the live endpoint will
    fail validation in connect().

    All outbound HTTP requests go through:
      1. A circuit breaker (fast-fails when Alpaca is down)
      2. Per-request retry with exponential backoff (transient 5xx / 429)

    LLM cannot affect routing, retries, or circuit state.
    """

    execution_mode: ExecutionMode = ExecutionMode.PAPER

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None
        self._market_data: MarketDataClient | None = None
        self._connected = False

        # Separate circuit breakers for trading API vs. market data
        self._trading_circuit = CircuitBreaker(
            "alpaca_trading_api",
            failure_threshold=5,
            recovery_timeout=30.0,
        )

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(15.0),
            base_url=_PAPER_BASE,
        )
        self._market_data = MarketDataClient(self._api_key, self._api_secret)
        await self._market_data.connect()

        # Verify connectivity + confirm paper mode (no retry — intentional: fail fast on connect).
        # Alpaca's /v2/account has no "paper_trading" field; mode is confirmed by
        # checking the key authenticates on paper and is rejected on live.
        try:
            account = await resolve_paper_account(self._api_key, self._api_secret)
        except AlpacaPaperModeError:
            await self.disconnect()
            raise

        self._connected = True
        log.info("alpaca_paper_connected", account_id=account.get("id"))

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._market_data:
            await self._market_data.disconnect()
            self._market_data = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def trading_circuit_state(self) -> str:
        return self._trading_circuit.state.value

    def _http(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("AlpacaPaperBroker not connected — call connect() first")
        return self._client

    # ── Resilient HTTP helper ────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make an HTTP request with:
        - Circuit breaker (fast-fail when Alpaca is known-down)
        - Retry with exponential backoff for transient errors (429, 5xx)
        """
        async def _attempt() -> httpx.Response:
            last_exc: Exception | None = None

            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await self._http().request(method, path, **kwargs)
                    if resp.status_code in _RETRYABLE_STATUS:
                        # Treat retryable status codes as exceptions so the
                        # circuit breaker counts them as failures after all retries.
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
                                "alpaca_request_retry",
                                method=method,
                                path=path,
                                status=exc.response.status_code,
                                attempt=attempt + 1,
                                delay=delay,
                            )
                            await asyncio.sleep(delay)
                        continue
                    # 4xx (except 429) — not retryable
                    raise
                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_exc = exc
                    if attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        log.warning(
                            "alpaca_request_network_retry",
                            method=method,
                            path=path,
                            error=str(exc),
                            attempt=attempt + 1,
                            delay=delay,
                        )
                        await asyncio.sleep(delay)

            assert last_exc is not None
            raise last_exc

        try:
            return await self._trading_circuit.call(_attempt())
        except CircuitBreakerOpen:
            log.error(
                "alpaca_circuit_open",
                method=method,
                path=path,
                circuit=self._trading_circuit.state.value,
            )
            raise

    # ── Orders ───────────────────────────────────────────────────────────────

    async def submit_order(self, request: OrderRequest) -> Order:
        payload: dict[str, Any] = {
            "symbol": request.symbol,
            "qty": str(request.qty),
            "side": request.side.value,
            "type": request.order_type.value,
            "time_in_force": request.time_in_force.value,
        }
        if request.limit_price is not None:
            payload["limit_price"] = str(request.limit_price)
        if request.stop_price is not None:
            payload["stop_price"] = str(request.stop_price)
        if request.trail_percent is not None:
            payload["trail_percent"] = str(request.trail_percent)
        if request.trail_dollars is not None:
            payload["trail_price"] = str(request.trail_dollars)
        if request.client_order_id:
            payload["client_order_id"] = request.client_order_id

        resp = await self._request("POST", "/orders", json=payload)
        return self._parse_order(resp.json(), original_id=request.id)

    async def cancel_order(self, broker_order_id: str) -> Order:
        resp = await self._request("DELETE", f"/orders/{broker_order_id}")
        if resp.status_code == 204:
            # Alpaca returns 204 on successful cancel — re-fetch for state
            return await self.get_order(broker_order_id)
        return self._parse_order(resp.json())

    async def get_order(self, broker_order_id: str) -> Order:
        resp = await self._request("GET", f"/orders/{broker_order_id}")
        return self._parse_order(resp.json())

    async def list_orders(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Order]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        resp = await self._request("GET", "/orders", params=params)
        return [self._parse_order(o) for o in resp.json()]

    # ── Portfolio ─────────────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        resp = await self._request("GET", "/positions")
        return [self._parse_position(p) for p in resp.json()]

    async def get_portfolio(self) -> PortfolioSnapshot:
        resp = await self._request("GET", "/account")
        account = resp.json()

        positions_resp = await self._request("GET", "/positions")
        positions = {
            p.symbol: p
            for p in (self._parse_position(p) for p in positions_resp.json())
        }

        return PortfolioSnapshot(
            account_id=account.get("id", ""),
            execution_mode=ExecutionMode.PAPER,
            cash=float(account.get("cash", 0)),
            positions=positions,
            realized_pnl=0.0,
        )

    # ── Market data ──────────────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Quote:
        if not self._market_data:
            raise RuntimeError("MarketDataClient not available")
        return await self._market_data.get_quote(symbol)

    async def subscribe_quotes(self, symbols: list[str], callback: Any) -> None:
        if not self._market_data:
            raise RuntimeError("MarketDataClient not available")
        await self._market_data.subscribe_quotes(symbols, callback)

    async def get_options_chain(self, underlying: str, expiration: date) -> OptionsChain:
        if not self._market_data:
            raise RuntimeError("MarketDataClient not available")
        return await self._market_data.get_options_chain(underlying, expiration)

    # ── Parsers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_order(raw: dict[str, Any], original_id: Any = None) -> Order:
        status_map = {
            "new": OrderStatus.SUBMITTED,
            "pending_new": OrderStatus.PENDING,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "done_for_day": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.EXPIRED,
            "replaced": OrderStatus.CANCELLED,
            "pending_cancel": OrderStatus.SUBMITTED,
            "pending_replace": OrderStatus.SUBMITTED,
            "held": OrderStatus.SUBMITTED,
            "accepted": OrderStatus.SUBMITTED,
            "rejected": OrderStatus.REJECTED,
        }

        type_map = {
            "market": OrderType.MARKET,
            "limit": OrderType.LIMIT,
            "stop": OrderType.STOP,
            "stop_limit": OrderType.STOP_LIMIT,
            "trailing_stop": OrderType.TRAILING_STOP,
        }

        def _dt(s: str | None) -> datetime | None:
            if not s:
                return None
            return datetime.fromisoformat(s.replace("Z", "+00:00"))

        return Order(
            id=original_id if original_id else uuid4(),
            broker_order_id=raw["id"],
            symbol=raw["symbol"],
            side=OrderSide(raw["side"]),
            qty=int(float(raw.get("qty") or raw.get("notional") or 0)),
            order_type=type_map.get(raw.get("type", "market"), OrderType.MARKET),
            status=status_map.get(raw.get("status", "new"), OrderStatus.SUBMITTED),
            limit_price=float(raw["limit_price"]) if raw.get("limit_price") else None,
            stop_price=float(raw["stop_price"]) if raw.get("stop_price") else None,
            filled_qty=int(float(raw.get("filled_qty") or 0)),
            avg_fill_price=float(raw["filled_avg_price"]) if raw.get("filled_avg_price") else None,
            time_in_force=TimeInForce(raw.get("time_in_force", "day")),
            execution_mode=ExecutionMode.PAPER,
            submitted_at=_dt(raw.get("submitted_at")),
            filled_at=_dt(raw.get("filled_at")),
            cancelled_at=_dt(raw.get("canceled_at")),
        )

    @staticmethod
    def _parse_position(raw: dict[str, Any]) -> Position:
        return Position(
            symbol=raw["symbol"],
            qty=int(float(raw.get("qty", 0))),
            avg_cost=float(raw.get("avg_entry_price", 0)),
            current_price=float(raw.get("current_price", 0)),
        )
