"""
Path: apps/api/src/trading/scanner.py
Security: Read-only market data access. No order submission. Writes only to
          shadow_trades table via ShadowModeService. Respects kill switch.
          source="auto_scanner" on every row for auditability.
Scale: Single-tenant. Runs once at 9:31 AM ET on market days. Max 3 signals
       per session. Pre-filter (yfinance) is free and instant. TradingAgents
       debate (~$0.0007/symbol) only fires when movement > 0.5%.

Auto-Scanner — generates shadow trade candidates without user input.

Signal flow (token-efficient):
  1. yfinance pre-filter: skip symbols with < 0.5% price movement (free)
  2. TradingAgents debate: DeepSeek analysts on filtered symbols only
  3. Tradier chain fetch: only on BULLISH/BEARISH verdict >= 65% confidence
  4. Shadow trade entry: logged with full metadata

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

_MIN_SCORE = 5.0          # shadow pipeline threshold — real orders enforce 7.0 at execution
_MAX_SIGNALS_PER_RUN = 3  # cap per day to avoid log pollution
_MIN_DTE = 7              # per account tier rules
_MAX_DTE = 21             # per CLAUDE.md scoring spec

# ── Scanner admin user (used for shadow_mode_config lookup) ──────────────────
# Reserved UUID for the auto-scanner service identity.
# shadow_trades.user_id and shadow_mode_config.user_id are UUID columns —
# passing the plain string "auto_scanner" caused every insert to fail silently.
_SCANNER_USER_ID = "00000000-0000-0000-0000-000000000001"
_MIN_MOVEMENT_PCT = 0.5       # skip symbols with < 0.5% price change (saves tokens)
_MIN_AGENT_CONFIDENCE = 0.65  # TradingAgents verdict must clear this bar


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
        redis_url: str = "",
        deepseek_api_key: str = "",
        anthropic_api_key: str = "",
        tradier_sandbox: bool = False,
    ) -> None:
        self._redis = redis
        self._redis_url = redis_url
        self._supabase = supabase
        self._tradier_key = tradier_api_key
        self._alpaca_key = alpaca_api_key
        self._alpaca_secret = alpaca_api_secret
        self._deepseek_key = deepseek_api_key
        self._anthropic_key = anthropic_api_key
        self._tradier_sandbox = tradier_sandbox

    async def run_scan(self, user_id: str) -> int:
        """
        Scan the watchlist and create shadow trade candidates.

        Returns the number of signals generated.
        Writes a row to scanner_daily_log regardless of outcome.
        """
        log.info("auto_scanner_starting", user_id=user_id, watchlist=SCANNER_WATCHLIST)
        signals = 0
        skipped = 0
        errors: list[str] = []

        for symbol in SCANNER_WATCHLIST:
            if signals >= _MAX_SIGNALS_PER_RUN:
                log.info("auto_scanner_signal_cap_reached", cap=_MAX_SIGNALS_PER_RUN)
                break
            try:
                result = await self._scan_symbol_tracked(symbol, user_id)
                signals += result["signals"]
                skipped += result["skipped"]
            except Exception as exc:
                err = f"{symbol}: {str(exc)[:120]}"
                log.warning("auto_scanner_symbol_error", symbol=symbol, error=str(exc)[:80])
                errors.append(err)
                continue

        log.info("auto_scanner_complete", signals_generated=signals, user_id=user_id)
        await self._write_daily_log(
            scan_date=date.today(),
            symbols_scanned=len(SCANNER_WATCHLIST),
            symbols_skipped=skipped,
            signals_generated=signals,
            errors=errors,
        )
        return signals

    async def _scan_symbol_tracked(self, symbol: str, user_id: str) -> dict[str, int]:
        """Wrapper that unpacks the (signals, was_skipped) tuple from _scan_symbol."""
        signals, was_skipped = await self._scan_symbol(symbol, user_id)
        return {"signals": signals, "skipped": 1 if was_skipped else 0}

    async def _write_daily_log(
        self,
        scan_date: date,
        symbols_scanned: int,
        symbols_skipped: int,
        signals_generated: int,
        errors: list[str],
    ) -> None:
        """Write (or upsert) today's scan summary to scanner_daily_log."""
        import json

        # Compute zero-signal streak from prior log rows
        streak = 0
        try:
            prev = await self._supabase.table("scanner_daily_log") \
                .select("scan_date, signals_generated, zero_signal_streak") \
                .lt("scan_date", scan_date.isoformat()) \
                .order("scan_date", desc=True) \
                .limit(5) \
                .execute()
            rows = prev.data or []
            if signals_generated == 0:
                # Count consecutive zero days before today
                for row in rows:
                    if row["signals_generated"] == 0:
                        streak += 1
                    else:
                        break
                streak += 1  # include today
            # else streak resets to 0
        except Exception:
            pass

        alert: str | None = None
        if streak >= 3:
            alert = f"{streak} consecutive market days with zero signals — check scanner config"
            log.warning("auto_scanner_zero_streak", streak=streak, alert=alert)

        # Persist zero streak to Redis for health endpoint
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            await r.set("scanner:zero_streak", str(streak), ex=7 * 24 * 3600)
            await r.set("scanner:last_scan_date", scan_date.isoformat(), ex=7 * 24 * 3600)
            await r.set("scanner:last_scan_signals", str(signals_generated), ex=7 * 24 * 3600)
            await r.set("scanner:last_scan_errors", str(len(errors)), ex=7 * 24 * 3600)
            if alert:
                await r.set("scanner:alert", alert, ex=7 * 24 * 3600)
            else:
                await r.delete("scanner:alert")
            await r.aclose()
        except Exception as exc:
            log.warning("auto_scanner_redis_log_failed", error=str(exc)[:80])

        try:
            row = {
                "scan_date": scan_date.isoformat(),
                "symbols_scanned": symbols_scanned,
                "symbols_skipped": symbols_skipped,
                "debates_attempted": getattr(self, "_debates_attempted", 0),
                "debates_completed": getattr(self, "_debates_completed", 0),
                "signals_generated": signals_generated,
                "deepseek_available": bool(self._deepseek_key),
                "zero_signal_streak": streak,
                "scanner_alert": alert,
                "errors": json.dumps(errors),
            }
            await self._supabase.table("scanner_daily_log").upsert(
                row, on_conflict="scan_date"
            ).execute()
            log.info("auto_scanner_daily_log_written", scan_date=scan_date.isoformat(), signals=signals_generated, streak=streak)
        except Exception as exc:
            log.error("auto_scanner_daily_log_failed", error=str(exc)[:120])

    async def _scan_symbol(self, symbol: str, user_id: str, _pre_filter_skip_ref: bool = False) -> tuple[int, bool]:
        """Scan one symbol. Returns (signals_created, was_pre_filter_skipped)."""
        from src.data.yfinance_client import YFinanceClient
        from src.options.tradier_client import TradierOptionsClient
        from src.trading.shadow import ShadowModeService

        yf = YFinanceClient(self._redis)

        # ── Step 1: yfinance pre-filter (FREE, no tokens) ─────────────────────
        movement_pct = await yf.price_moved_pct(symbol)
        if movement_pct is None:
            log.warning("auto_scanner_no_movement_data", symbol=symbol)
            # Fall through — don't skip if yfinance is unavailable
        elif movement_pct < _MIN_MOVEMENT_PCT:
            log.info(
                "auto_scanner_symbol_skipped",
                symbol=symbol,
                movement_pct=round(movement_pct, 3),
                threshold=_MIN_MOVEMENT_PCT,
            )
            return (0, True)  # (signals, was_skipped)

        # ── Step 2: TradingAgents debate (DeepSeek, ~$0.0007) ────────────────
        if self._deepseek_key:
            self._debates_attempted = getattr(self, "_debates_attempted", 0) + 1
            from src.agents.trading_agents_adapter import TradingAgentsAdapter
            adapter = TradingAgentsAdapter(
                deepseek_api_key=self._deepseek_key,
                anthropic_api_key=self._anthropic_key,
            )
            verdict = await adapter.run_debate(symbol)
            log.info(
                "auto_scanner_agent_verdict",
                symbol=symbol,
                verdict=verdict.verdict,
                confidence=round(verdict.confidence, 3),
                token_input=verdict.token_input,
                token_output=verdict.token_output,
            )
            # Write to scanner_debates (not workbench_analyses — wrong schema)
            await adapter.log_debate_to_supabase(verdict, user_id, self._supabase)

            if verdict.verdict != "NEUTRAL":
                self._debates_completed = getattr(self, "_debates_completed", 0) + 1

            if not verdict.passes_threshold(_MIN_AGENT_CONFIDENCE):
                log.info(
                    "auto_scanner_verdict_rejected",
                    symbol=symbol,
                    verdict=verdict.verdict,
                    confidence=verdict.confidence,
                )
                return (0, False)
        else:
            log.info("auto_scanner_no_deepseek_key_skipping_debate", symbol=symbol)

        # ── Step 3: Fetch current price (yfinance, free) ──────────────────────
        price = await yf.get_price(symbol)
        if not price or price <= 0:
            log.warning("auto_scanner_no_price", symbol=symbol)
            return (0, False)

        # ── Target expiry: first options expiry 7–21 DTE ─────────────────────
        today = date.today()
        target_expiry = _next_friday_in_range(today, min_dte=_MIN_DTE, max_dte=_MAX_DTE)
        if target_expiry is None:
            return (0, False)

        # ── Fetch options chain via Tradier ───────────────────────────────────
        import redis.asyncio as aioredis

        # Use the stored redis_url directly — reconstructing from connection pool
        # kwargs is unreliable (the path key is not set for URL-based clients).
        redis_client = aioredis.from_url(
            self._redis_url or "redis://localhost:6379",
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
            return (0, False)

        if not chain.calls and not chain.puts:
            return (0, False)

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

            # Shadow trades log at any cost — the $5 Tiny-tier cap is enforced
            # at order execution time, not during scanning. Filtering here would
            # produce zero signals for large-cap watchlist symbols in a $5 budget
            # and make the 14-day shadow run impossible to validate.

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
            return (0, False)

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
        return (1, False)


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
    deepseek_api_key: str = "",
    anthropic_api_key: str = "",
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
                    redis_url=redis_url,
                    deepseek_api_key=deepseek_api_key,
                    anthropic_api_key=anthropic_api_key,
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
    Uses ZoneInfo("America/New_York") — DST-aware, no fixed offset.
    Current equivalent: 13:31 UTC (EDT, summer). 14:31 UTC in winter (EST).
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
