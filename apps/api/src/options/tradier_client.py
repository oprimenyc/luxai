"""
Tradier options chain client — free-tier, Redis-cached.

Path: apps/api/src/options/tradier_client.py
Security: API key read from settings only, never from caller input.
          Sandbox flag is always True unless TRADIER_SANDBOX=false in env AND
          account has crossed the $1,000 threshold per CLAUDE.md.
Scale: Redis TTL=60s for chains, 30s for quotes. httpx async with retry.
       Rate limit: Tradier free tier allows 200 req/hr — cache is essential.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from src.trading.models import Greeks, OptionContract, OptionType, OptionsChain

if TYPE_CHECKING:
    import redis.asyncio as aioredis

log = structlog.get_logger(__name__)

_PROD_BASE  = "https://api.tradier.com/v1"
_SANDBOX_BASE = "https://sandbox.tradier.com/v1"

_CHAIN_TTL_SECONDS = 60
_QUOTE_TTL_SECONDS = 30
_CACHE_KEY_CHAIN = "tradier:chain:{symbol}:{expiry}"
_CACHE_KEY_QUOTE = "tradier:quote:{symbol}"

_TIMEOUT = httpx.Timeout(10.0)
_MAX_RETRIES = 2


class TradierRateLimitError(RuntimeError):
    """Raised when Tradier returns HTTP 429."""


class TradierOptionsClient:
    """
    Async client for the Tradier free-tier options chain API.

    Caches full chains in Redis at 60-second TTL to stay within the
    200 req/hr free-tier rate limit. Quotes cached at 30s.

    Usage:
        async with TradierOptionsClient(api_key, sandbox=True, redis=redis_client) as client:
            chain = await client.get_chain("AAPL", date(2025, 1, 17))
            price = await client.get_underlying_price("AAPL")
    """

    def __init__(
        self,
        api_key: str,
        sandbox: bool = True,
        redis: "aioredis.Redis | None" = None,
    ) -> None:
        self._api_key = api_key
        self._sandbox = sandbox
        self._base = _SANDBOX_BASE if sandbox else _PROD_BASE
        self._redis = redis
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "TradierOptionsClient":
        self._client = httpx.AsyncClient(headers=self._headers, timeout=_TIMEOUT)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_chain(
        self, symbol: str, expiration: date
    ) -> OptionsChain:
        """
        Fetch the full options chain for symbol at expiration.
        Returns cached response if within TTL.
        Strips contracts where both bid and ask are 0 (stale/illiquid).
        """
        cache_key = _CACHE_KEY_CHAIN.format(
            symbol=symbol.upper(), expiry=expiration.isoformat()
        )

        # ── Cache read ────────────────────────────────────────────────────────
        if self._redis:
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return OptionsChain.model_validate(data)
            except Exception:
                log.warning("tradier_cache_read_failed", symbol=symbol)

        # ── Fetch from Tradier ────────────────────────────────────────────────
        underlying_price = await self.get_underlying_price(symbol)
        raw_chain = await self._fetch_chain(symbol, expiration)

        chain = self._parse_chain(
            raw_chain, symbol.upper(), expiration, underlying_price
        )

        # ── Cache write ───────────────────────────────────────────────────────
        if self._redis:
            try:
                await self._redis.set(
                    cache_key,
                    chain.model_dump_json(),
                    ex=_CHAIN_TTL_SECONDS,
                )
            except Exception:
                log.warning("tradier_cache_write_failed", symbol=symbol)

        return chain

    async def get_underlying_price(self, symbol: str) -> float:
        """
        Fetch latest quote for the underlying.
        Returns cached price if within 30s TTL.
        Falls back to 0.0 on error (caller must handle).
        """
        cache_key = _CACHE_KEY_QUOTE.format(symbol=symbol.upper())

        if self._redis:
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    return float(cached)
            except Exception:
                pass

        try:
            raw = await self._get(
                "/markets/quotes",
                params={"symbols": symbol.upper(), "greeks": "false"},
            )
            quote_data = raw.get("quotes", {}).get("quote", {})
            # Tradier returns a list if multiple symbols, object if single
            if isinstance(quote_data, list):
                quote_data = quote_data[0] if quote_data else {}
            price = float(quote_data.get("last") or quote_data.get("close") or 0.0)

            if price > 0 and self._redis:
                try:
                    await self._redis.set(
                        cache_key, str(price), ex=_QUOTE_TTL_SECONDS
                    )
                except Exception:
                    pass

            return price

        except Exception as exc:
            log.warning("tradier_quote_fetch_failed", symbol=symbol, error=str(exc))
            return 0.0

    async def list_expirations(self, symbol: str) -> list[date]:
        """Return all available expiration dates for a symbol."""
        try:
            raw = await self._get(
                "/markets/options/expirations",
                params={"symbol": symbol.upper(), "includeAllRoots": "true"},
            )
            dates_raw = raw.get("expirations", {}).get("date", [])
            if isinstance(dates_raw, str):
                dates_raw = [dates_raw]
            return [date.fromisoformat(d) for d in dates_raw if d]
        except Exception as exc:
            log.warning("tradier_expirations_failed", symbol=symbol, error=str(exc))
            return []

    # ── HTTP layer ────────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("TradierOptionsClient must be used as async context manager")

        url = f"{self._base}{path}"
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await self._client.get(url, params=params)
                if resp.status_code == 401:
                    # 401 = invalid token or API plan does not include this endpoint.
                    # Tradier sandbox tokens require the "Markets" API product enabled
                    # on the application in developer.tradier.com → Applications.
                    env = "sandbox" if self._sandbox else "production"
                    raise RuntimeError(
                        f"Tradier 401 Unauthorized on {path} ({env}). "
                        "Check that your API token has the 'Markets' product enabled: "
                        "developer.tradier.com → Applications → [your app] → Subscriptions."
                    )
                if resp.status_code == 429:
                    raise TradierRateLimitError(
                        "Tradier rate limit hit (200 req/hr free tier). "
                        "Redis cache should prevent this — check cache wiring."
                    )
                resp.raise_for_status()
                return resp.json()
            except (TradierRateLimitError, RuntimeError):
                raise
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    log.warning(
                        "tradier_request_retry",
                        path=path,
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                continue

        raise last_exc or RuntimeError(f"Tradier request failed: {path}")

    async def _fetch_chain(self, symbol: str, expiration: date) -> list[dict[str, Any]]:
        raw = await self._get(
            "/markets/options/chains",
            params={
                "symbol": symbol.upper(),
                "expiration": expiration.isoformat(),
                "greeks": "true",
            },
        )
        options = raw.get("options", {}) or {}
        option_list = options.get("option", []) or []
        if isinstance(option_list, dict):
            option_list = [option_list]
        return option_list

    # ── Parsers ───────────────────────────────────────────────────────────────

    def _parse_chain(
        self,
        option_list: list[dict[str, Any]],
        symbol: str,
        expiration: date,
        underlying_price: float,
    ) -> OptionsChain:
        calls: list[OptionContract] = []
        puts: list[OptionContract] = []

        for raw in option_list:
            contract = self._parse_contract(raw)
            if contract is None:
                continue
            if contract.option_type == OptionType.CALL:
                calls.append(contract)
            else:
                puts.append(contract)

        # Sort by strike ascending
        calls.sort(key=lambda c: c.strike)
        puts.sort(key=lambda c: c.strike)

        return OptionsChain(
            underlying=symbol,
            expiration=expiration,
            underlying_price=underlying_price,
            calls=calls,
            puts=puts,
            fetched_at=datetime.now(UTC),
        )

    @staticmethod
    def _parse_contract(raw: dict[str, Any]) -> OptionContract | None:
        """
        Parse a single Tradier option record.
        Returns None for contracts with no tradeable market (both bid+ask=0).
        """
        bid = float(raw.get("bid") or 0.0)
        ask = float(raw.get("ask") or 0.0)
        last = float(raw.get("last") or 0.0)
        volume = int(raw.get("volume") or 0)
        oi = int(raw.get("open_interest") or 0)
        strike = float(raw.get("strike") or 0.0)

        # Filter stale / no-market contracts
        if bid == 0.0 and ask == 0.0 and last == 0.0:
            return None
        if strike <= 0.0:
            return None

        opt_type_str = str(raw.get("option_type", "")).lower()
        if opt_type_str not in ("call", "put"):
            return None

        option_type = OptionType.CALL if opt_type_str == "call" else OptionType.PUT

        # Greeks from Tradier (may be null — caller enriches via BlackScholesGreeks)
        greeks_raw = raw.get("greeks") or {}
        greeks = Greeks(
            delta=_safe_float(greeks_raw.get("delta")),
            gamma=_safe_float(greeks_raw.get("gamma")),
            theta=_safe_float(greeks_raw.get("theta")),
            vega=_safe_float(greeks_raw.get("vega")),
            rho=_safe_float(greeks_raw.get("rho")),
            iv=_safe_float(greeks_raw.get("mid_iv") or greeks_raw.get("smv_vol")),
        )

        expiry_str = str(raw.get("expiration_date", ""))
        try:
            expiry = date.fromisoformat(expiry_str)
        except ValueError:
            return None

        return OptionContract(
            symbol=str(raw.get("symbol", "")),
            underlying=str(raw.get("underlying") or raw.get("root_symbol", "")),
            option_type=option_type,
            strike=strike,
            expiration=expiry,
            bid=bid,
            ask=ask,
            last=last,
            volume=volume,
            open_interest=oi,
            greeks=greeks,
        )


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_tradier_client(
    redis: "aioredis.Redis | None" = None,
) -> "TradierOptionsClient":
    """
    Return a configured TradierOptionsClient from application settings.
    Caller is responsible for using it as an async context manager.
    """
    from src.config import settings

    return TradierOptionsClient(
        api_key=settings.tradier_api_key,
        sandbox=settings.tradier_sandbox,
        redis=redis,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


import math  # noqa: E402 — placed after _safe_float to avoid circular refs
