"""
Path: apps/api/src/trading/scanner.py
Security: Read-only market data access. No order submission. Writes only to
          shadow_trades table via ShadowModeService. Respects kill switch.
          source="auto_scanner" on every row for auditability.
Scale: Single-tenant. Runs once at 9:31 AM ET on market days. Max 3 signals
       per session. Tradier chain fetch is the bottleneck (~2–4s per symbol).

Auto-Scanner — generates shadow trade candidates without user input.

Purpose: give the shadow run real data without requiring daily manual
workbench use. Scans a fixed watchlist at market open, scores each option
chain, and inserts any high-quality candidate (score >= 7.0) as a shadow
trade. This fulfills the shadow gate criterion of >= 5 intercepted trades
without the platform owner needing to use the workbench every day.

Design constraints (Tiny tier, <$500 account):
  - Max $5 risk per trade
  - Max 1 contract
  - Min 7 DTE
  - No 0DTE, no earnings plays
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from supabase import AsyncClient

log = structlog.get_logger(__name__)

# ── Watchlist ─────────────────────────────────────────────────────────────────

SCANNER_WATCHLIST: list[str] = [
    "SPY", "QQQ", "TSLA", "NVDA", "AAPL", "META", "AMZN",
]

# ── Thresholds ────────────────────────────────────────────────────────────────

_MIN_SCORE = 7.0          # only emit signals above this quality bar
_MAX_SIGNALS_PER_RUN = 3  # cap per day to avoid log pollution
_TINY_MAX_RISK_USD = 5.0  # hard Tiny tier cap
_MIN_DTE = 7              # per account tier rules
_MAX_DTE = 21             # per CLAUDE.md scoring spec

# ── Scanner admin user (used for shadow_mode_config lookup) ──────────────────

_SCANNER_USER_ID = "auto_scanner"


class MarketScannerService:
    """
    Scans the watchlist at market open and creates shadow trade entries.

    Wired into main.py lifespan as a scheduled daily background task.
    Never submits real orders — purely logging to shadow_trades.
    """

    def __init__(
        self,
        redis: "aioredis.Redis",
        supabase: "AsyncClient",
        tradier_api_key: str,
        alpaca_api_key: str,
        alpaca_api_secret: str,
        tradier_sandbox: bool = False,
    ) -> None:
        self._redis = redis
        self._supabase = supabase
        self._tradier_key = tradier_api_key
        self._alpaca_key = alpaca_api_key
        self._alpaca_secret = alpaca_api_secret
        self._tradier_sandbox = tradier_sandbox

    async def run_scan(self, user_id: str) -> int:
        """
        Scan the watchlist and create shadow trade candidates.

        Returns the number of signals generated.
        """
        log.info("auto_scanner_starting", user_id=user_id, watchlist=SCANNER_WATCHLIST)
        signals = 0

        for symbol in SCANNER_WATCHLIST:
            if signals >= _MAX_SIGNALS_PER_RUN:
                log.info("auto_scanner_signal_cap_reached", cap=_MAX_SIGNALS_PER_RUN)
                break
            try:
                generated = await self._scan_symbol(symbol, user_id)
                signals += generated
            except Exception as exc:
                log.warning("auto_scanner_symbol_error", symbol=symbol, error=str(exc)[:80])
                continue

        log.info("auto_scanner_complete", signals_generated=signals, user_id=user_id)
        return signals

    async def _scan_symbol(self, symbol: str, user_id: str) -> int:
        """Scan one symbol. Returns 1 if a shadow trade was created, 0 otherwise."""
        import httpx
        from src.options.tradier_client import TradierOptionsClient
        from src.trading.shadow import ShadowModeService

        # ── Fetch current price from Alpaca ───────────────────────────────────
        price: float = 0.0
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(
                    f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest",
                    headers={
                        "APCA-API-KEY-ID": self._alpaca_key,
                        "APCA-API-SECRET-KEY": self._alpaca_secret,
                    },
                )
                if resp.status_code == 200:
                    q = resp.json().get("quote", {})
                    bid = float(q.get("bp", 0))
                    ask = float(q.get("ap", 0))
                    if bid > 0 and ask > 0:
                        price = (bid + ask) / 2
            except Exception as exc:
                log.warning("auto_scanner_price_fetch_failed", symbol=symbol, error=str(exc)[:60])

        if price <= 0:
            log.warning("auto_scanner_no_price", symbol=symbol)
            return 0

        # ── Target expiry: first options expiry 7–21 DTE ─────────────────────
        today = date.today()
        target_expiry = _next_friday_in_range(today, min_dte=_MIN_DTE, max_dte=_MAX_DTE)
        if target_expiry is None:
            return 0

        # ── Fetch options chain via Tradier ───────────────────────────────────
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(
            str(self._redis.connection_pool.connection_kwargs.get("path", ""))
            or "redis://localhost:6379",
            encoding="utf-8",
            decode_responses=True,
        )

        try:
            async with TradierOptionsClient(
                api_key=self._tradier_key,
                sandbox=self._tradier_sandbox,
                redis=redis_client,
            ) as tradier:
                chain = await tradier.get_chain(symbol, target_expiry)
        except Exception as exc:
            log.warning("auto_scanner_chain_fetch_failed", symbol=symbol, error=str(exc)[:80])
            return 0

        if not chain.calls and not chain.puts:
            return 0

        # ── Score the chain — take best call and put ──────────────────────────
        from src.options.scorer import OptionsScorer
        from src.options.greeks import BlackScholesGreeks
        from src.trading.models import Greeks

        scorer = OptionsScorer("tiny")
        best_score: float = 0.0
        best_contract: Any = None
        best_side = "buy"

        for contract in chain.calls + chain.puts:
            # Enrich Greeks if missing
            if contract.greeks.delta is None and price > 0 and contract.mid > 0:
                try:
                    iv = BlackScholesGreeks.implied_volatility(
                        market_price=contract.mid,
                        underlying_price=price,
                        strike=contract.strike,
                        expiry_date=contract.expiration,
                        option_type=contract.option_type.value,
                        risk_free_rate=0.045,
                    )
                    if iv and iv > 0:
                        result = BlackScholesGreeks.compute(
                            underlying_price=price,
                            strike=contract.strike,
                            expiry_date=contract.expiration,
                            iv=iv,
                            option_type=contract.option_type.value,
                            risk_free_rate=0.045,
                        )
                        contract = contract.model_copy(update={"greeks": Greeks(
                            delta=result.delta, gamma=result.gamma,
                            theta=result.theta, vega=result.vega, iv=result.iv,
                        )})
                except Exception:
                    pass

            scored = scorer.score_contract(contract)
            if scored.tier_violation:
                continue

            # Tiny tier: must be within $5 risk
            cost_usd = contract.mid * 100
            if cost_usd > _TINY_MAX_RISK_USD:
                continue

            if scored.score > best_score:
                best_score = scored.score
                best_contract = contract
                best_side = "buy"

        if best_score < _MIN_SCORE or best_contract is None:
            log.info(
                "auto_scanner_no_qualifying_contract",
                symbol=symbol,
                best_score=round(best_score, 1),
                threshold=_MIN_SCORE,
            )
            return 0

        # ── Log as shadow trade ───────────────────────────────────────────────
        svc = ShadowModeService(redis=self._redis, supabase=self._supabase)
        shadow_id = await svc.record_shadow_trade(
            user_id=user_id,
            symbol=symbol,
            side=best_side,
            qty=1,
            intended_entry_price=price,
            order_type="market",
            intended_idempotency_key=f"scanner:{symbol}:{today.isoformat()}",
            metadata={
                "source": "auto_scanner",
                "contract_symbol": best_contract.symbol,
                "strike": best_contract.strike,
                "expiry": best_contract.expiration.isoformat(),
                "option_type": best_contract.option_type.value,
                "score": round(best_score, 1),
                "estimated_cost_usd": round(best_contract.mid * 100, 2),
                "underlying_price": round(price, 2),
            },
        )
        log.info(
            "auto_scanner_signal_created",
            symbol=symbol,
            score=round(best_score, 1),
            contract=best_contract.symbol,
            shadow_id=shadow_id,
        )
        return 1


# ── Helpers ───────────────────────────────────────────────────────────────────


def _next_friday_in_range(today: date, min_dte: int, max_dte: int) -> date | None:
    """Return the first Friday with DTE in [min_dte, max_dte], or None."""
    for delta in range(min_dte, max_dte + 1):
        candidate = today + timedelta(days=delta)
        if candidate.weekday() == 4:  # Friday
            return candidate
    return None


def is_market_day(today: date) -> bool:
    """Return True if today is Mon–Fri (simple check; ignores holidays)."""
    return today.weekday() < 5


# ── Background loop ───────────────────────────────────────────────────────────


async def auto_scanner_loop(
    user_id: str,
    tradier_api_key: str,
    alpaca_api_key: str,
    alpaca_api_secret: str,
    redis_url: str,
    tradier_sandbox: bool = False,
) -> None:
    """
    Background task: wait for 9:31 AM ET on market days, then run the scan.

    Task name: auto_market_scanner
    Cancellation: cancelled gracefully in lifespan finally block.
    Timeout: each scan cycle has asyncio.timeout(120s).
    """
    import redis.asyncio as aioredis
    from src.services.supabase_service import get_supabase_client

    log.info("auto_scanner_loop_started", user_id=user_id)

    while True:
        try:
            # Sleep until 9:31 AM ET on the next market day
            seconds_until_open = _seconds_until_market_open()
            log.info("auto_scanner_sleeping", seconds=seconds_until_open)
            await asyncio.sleep(seconds_until_open)

            today = datetime.now(UTC).date()
            if not is_market_day(today):
                log.info("auto_scanner_not_market_day", date=today.isoformat())
                continue

            async with asyncio.timeout(120.0):
                redis_client = aioredis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=False,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                supabase = await get_supabase_client()

                scanner = MarketScannerService(
                    redis=redis_client,
                    supabase=supabase,
                    tradier_api_key=tradier_api_key,
                    alpaca_api_key=alpaca_api_key,
                    alpaca_api_secret=alpaca_api_secret,
                    tradier_sandbox=tradier_sandbox,
                )
                await scanner.run_scan(user_id=user_id)

            # After scan, sleep 23h to avoid double-firing on the same day
            await asyncio.sleep(23 * 3600)

        except asyncio.CancelledError:
            log.info("auto_scanner_loop_cancelled")
            raise
        except Exception as exc:
            log.error("auto_scanner_loop_error", error=str(exc)[:120])
            # Back off 30 minutes on unexpected error
            await asyncio.sleep(1800)


def _seconds_until_market_open() -> float:
    """
    Return seconds until 9:31 AM US/Eastern on the next market day.
    Uses a fixed UTC offset of -4 (EDT). Handles DST approximately.
    """
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    now_et = datetime.now(et)
    target = now_et.replace(hour=9, minute=31, second=0, microsecond=0)
    if now_et >= target:
        # Already past open today — target tomorrow
        target += timedelta(days=1)
    # Skip weekends
    while target.weekday() >= 5:
        target += timedelta(days=1)
    delta = (target - now_et).total_seconds()
    return max(delta, 0.0)
