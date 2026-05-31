"""
Trade Idea Workbench API — POST /workbench/analyze.

Path: apps/api/src/workbench/router.py
Security: Auth required (AuthenticatedUser). Account size comes from the live
          portfolio snapshot, never from the request body (prevents tier spoofing).
          Tradier API key is read from settings only.
Scale: One analyze call = 1 Tradier chain fetch (cached 60s) + 1 Yahoo earnings
       fetch (5s timeout, non-fatal). Pipeline is async-native throughout.

B1 safety chain NOT applied here: workbench is read-only analysis, not order
submission. No order is created by this endpoint.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any, Literal

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.config import settings
from src.middleware.auth import AuthenticatedUser, get_current_user
from src.options.scorer import OptionsScorer
from src.options.tradier_client import TradierOptionsClient
from src.trading.account_constraints import classify_tier
from src.workbench.calendar import CalendarResult, MacroCalendarChecker, fetch_earnings_date
from src.workbench.recommender import (
    ContractRecommendation,
    ContractRecommender,
    RecommendationSet,
    SpreadRecommendation,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/workbench", tags=["workbench"])


# ══════════════════════════════════════════════════════════════════════════════
# Request / Response models
# ══════════════════════════════════════════════════════════════════════════════


class WorkbenchRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=10, description="Underlying ticker (e.g. AAPL)")
    direction: Literal["bullish", "bearish"]
    expiration: date = Field(description="Target expiration date (YYYY-MM-DD)")
    budget_usd: float = Field(gt=0, le=50_000, description="Max premium per contract in USD")
    account_size_usd: float = Field(
        gt=0,
        le=1_000_000,
        description="Current account equity. Used for tier classification and constraint checks.",
    )
    source: str | None = Field(
        default=None,
        max_length=200,
        description="Optional: where you heard about this trade",
    )
    suggested_strike: float | None = Field(
        default=None,
        description="Optional: specific strike to highlight if present in chain",
    )


class ContractRecommendationResponse(BaseModel):
    symbol: str
    underlying: str
    option_type: str
    strike: float
    expiration: str
    bid: float
    ask: float
    mid: float
    open_interest: int
    dte: int
    greeks: dict[str, float | None]
    score: float
    score_breakdown: dict[str, float]
    estimated_cost_usd: float
    within_budget: bool
    max_loss: float
    max_profit: float
    breakeven: float
    risk_reward_note: str


class SpreadRecommendationResponse(BaseModel):
    long_strike: float
    short_strike: float
    long_symbol: str
    short_symbol: str
    option_type: str
    net_debit: float
    max_profit: float
    max_loss: float
    breakeven: float
    risk_reward_ratio: float
    score: float
    within_budget: bool


class MacroEventResponse(BaseModel):
    name: str
    event_date: str
    risk_level: str
    days_away: int


class WorkbenchResult(BaseModel):
    # Request echo
    symbol: str
    direction: str
    expiration: str
    underlying_price: float
    budget_usd: float
    account_tier: str

    # Recommendations
    best_value: ContractRecommendationResponse | None
    best_probability: ContractRecommendationResponse | None
    spread_version: SpreadRecommendationResponse | None

    # Budget flag
    budget_exceeded: bool
    budget_note: str

    # Calendar
    macro_events: list[MacroEventResponse]
    earnings_warning: bool
    earnings_date: str | None

    # Verdict
    verdict: Literal["accept", "caution", "reject"]
    verdict_rationale: str

    # Meta
    analyzed_at: str
    tradier_sandbox: bool


# ══════════════════════════════════════════════════════════════════════════════
# Endpoint
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/analyze", response_model=WorkbenchResult)
async def analyze_trade_idea(
    body: WorkbenchRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> WorkbenchResult:
    """
    Full Trade Idea Workbench pipeline:
      1. Validate Tradier credentials
      2. Fetch options chain (Tradier, Redis-cached 60s)
      3. Enrich Greeks internally (Black-Scholes)
      4. Score all contracts (5-factor weighted)
      5. Build three recommendations (Best Value / Best Prob / Spread)
      6. Fetch earnings date (Yahoo Finance, non-fatal)
      7. Check macro calendar
      8. Compute verdict (Accept / Caution / Reject)
    """
    user_id = str(user.user_id)

    if not settings.tradier_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tradier API key not configured (TRADIER_API_KEY)",
        )

    symbol = body.symbol.upper()
    account_tier = classify_tier(body.account_size_usd).value

    log.info(
        "workbench_analyze_start",
        user=user_id,
        symbol=symbol,
        direction=body.direction,
        expiration=body.expiration.isoformat(),
        budget=body.budget_usd,
        tier=account_tier,
    )

    # ── Step 1: Redis client for Tradier cache ────────────────────────────────
    redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )

    # ── Step 2+3: Fetch chain + enrich Greeks ─────────────────────────────────
    try:
        async with TradierOptionsClient(
            api_key=settings.tradier_api_key,
            sandbox=settings.tradier_sandbox,
            redis=redis_client,
        ) as tradier:
            chain = await tradier.get_chain(symbol, body.expiration)
    except Exception as exc:
        log.error("workbench_chain_fetch_failed", symbol=symbol, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Options chain unavailable for {symbol} — {exc}",
        )

    if not chain.calls and not chain.puts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No options found for {symbol} expiring {body.expiration.isoformat()}. "
                "Verify the expiration date is a valid options expiry."
            ),
        )

    # ── Step 4+5: Score + recommend ───────────────────────────────────────────
    recommender = ContractRecommender(
        account_tier=account_tier,
        budget_usd=body.budget_usd,
        direction=body.direction,
    )
    recs: RecommendationSet = recommender.recommend(chain)

    # ── Step 6: Earnings date (async, non-fatal) ──────────────────────────────
    try:
        earnings_date = await asyncio.wait_for(
            fetch_earnings_date(symbol), timeout=5.0
        )
    except Exception:
        earnings_date = None

    # ── Step 7: Macro calendar check ──────────────────────────────────────────
    cal_checker = MacroCalendarChecker()
    cal_result: CalendarResult = cal_checker.check(
        symbol=symbol,
        expiration=body.expiration,
        earnings_date=earnings_date,
    )

    # ── Step 8: Verdict ───────────────────────────────────────────────────────
    verdict, rationale = _compute_verdict(
        recs=recs,
        cal_result=cal_result,
        account_tier=account_tier,
    )

    # ── Serialise recommendations ─────────────────────────────────────────────
    def _ser_rec(rec: ContractRecommendation | None) -> ContractRecommendationResponse | None:
        if rec is None:
            return None
        c = rec.contract
        return ContractRecommendationResponse(
            symbol=c.symbol,
            underlying=c.underlying,
            option_type=c.option_type.value,
            strike=c.strike,
            expiration=c.expiration.isoformat(),
            bid=c.bid,
            ask=c.ask,
            mid=round(c.mid, 2),
            open_interest=c.open_interest,
            dte=c.dte,
            greeks={
                "delta": round(c.greeks.delta, 4) if c.greeks.delta is not None else None,
                "gamma": round(c.greeks.gamma, 4) if c.greeks.gamma is not None else None,
                "theta": round(c.greeks.theta, 4) if c.greeks.theta is not None else None,
                "vega":  round(c.greeks.vega, 4)  if c.greeks.vega is not None else None,
                "iv":    round(c.greeks.iv, 4)    if c.greeks.iv is not None else None,
            },
            score=rec.score,
            score_breakdown=rec.score_breakdown,
            estimated_cost_usd=rec.estimated_cost_usd,
            within_budget=rec.within_budget,
            max_loss=rec.max_loss,
            max_profit=rec.max_profit,
            breakeven=rec.breakeven,
            risk_reward_note=rec.risk_reward_note,
        )

    def _ser_spread(rec: SpreadRecommendation | None) -> SpreadRecommendationResponse | None:
        if rec is None:
            return None
        s = rec.spread
        return SpreadRecommendationResponse(
            long_strike=s.long_leg.contract.strike,
            short_strike=s.short_leg.contract.strike,
            long_symbol=s.long_leg.contract.symbol,
            short_symbol=s.short_leg.contract.symbol,
            option_type=s.option_type.value,
            net_debit=rec.net_debit,
            max_profit=s.max_profit,
            max_loss=s.max_loss,
            breakeven=s.breakeven,
            risk_reward_ratio=round(s.risk_reward, 2),
            score=rec.score,
            within_budget=rec.within_budget,
        )

    result = WorkbenchResult(
        symbol=symbol,
        direction=body.direction,
        expiration=body.expiration.isoformat(),
        underlying_price=round(chain.underlying_price, 2),
        budget_usd=body.budget_usd,
        account_tier=account_tier,
        best_value=_ser_rec(recs.best_value),
        best_probability=_ser_rec(recs.best_probability),
        spread_version=_ser_spread(recs.spread_version),
        budget_exceeded=recs.budget_exceeded,
        budget_note=recs.budget_note,
        macro_events=[
            MacroEventResponse(
                name=e.name,
                event_date=e.event_date.isoformat(),
                risk_level=e.risk_level,
                days_away=e.days_away,
            )
            for e in cal_result.macro_events
        ],
        earnings_warning=cal_result.earnings_warning,
        earnings_date=cal_result.earnings_date.isoformat() if cal_result.earnings_date else None,
        verdict=verdict,
        verdict_rationale=rationale,
        analyzed_at=datetime.now(UTC).isoformat(),
        tradier_sandbox=settings.tradier_sandbox,
    )

    log.info(
        "workbench_analyze_complete",
        user=user_id,
        symbol=symbol,
        verdict=verdict,
        best_score=recs.best_value.score if recs.best_value else None,
    )

    # ── Persist analysis to audit ledger (non-fatal) ──────────────────────────
    # asyncio.create_task bounded by request lifetime; fire-and-await in same scope
    try:
        from src.services.supabase_service import get_supabase_client as _get_sb
        sb = await _get_sb()
        bv = result.best_value
        sv = result.spread_version
        await sb.table("workbench_analyses").insert({
            "user_id": user_id,
            "symbol": result.symbol,
            "direction": result.direction,
            "expiration": result.expiration,
            "budget_usd": result.budget_usd,
            "account_size_usd": body.account_size_usd,
            "account_tier": result.account_tier,
            "source": body.source,
            "underlying_price": result.underlying_price,
            "best_value_score": bv.score if bv else None,
            "best_value_symbol": bv.symbol if bv else None,
            "best_value_strike": bv.strike if bv else None,
            "best_value_cost_usd": bv.estimated_cost_usd if bv else None,
            "best_value_dte": bv.dte if bv else None,
            "spread_net_debit": sv.net_debit if sv else None,
            "macro_event_count": len(result.macro_events),
            "earnings_warning": result.earnings_warning,
            "verdict": result.verdict,
            "verdict_rationale": result.verdict_rationale,
            "result_payload": result.model_dump(),
            "analyzed_at": result.analyzed_at,
        }).execute()
    except Exception as exc:
        # Audit persistence is non-fatal — never block the analysis response
        log.warning("workbench_audit_persist_failed", user=user_id, error=str(exc)[:120])

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Verdict logic
# ══════════════════════════════════════════════════════════════════════════════


def _compute_verdict(
    recs: RecommendationSet,
    cal_result: CalendarResult,
    account_tier: str,
) -> tuple[Literal["accept", "caution", "reject"], str]:
    """
    Determine Accept / Caution / Reject verdict.

    Reject:  no valid recommendation found, or score < 4.0
    Caution: earnings in window, high-risk macro event, or score < 6.5
    Accept:  score >= 6.5, no earnings, no high-risk macro events
    """
    if recs.best_value is None:
        return "reject", (
            "No valid contracts found for your budget and tier constraints. "
            "Try a higher budget, different expiration, or check that the symbol has options."
        )

    score = recs.best_value.score
    caution_reasons: list[str] = []
    reject_reasons: list[str] = []

    if score < 4.0:
        reject_reasons.append(f"score {score:.1f}/10 below minimum threshold of 4.0")

    if cal_result.earnings_warning:
        caution_reasons.append(
            f"earnings for {cal_result.earnings_symbol} "
            f"({cal_result.earnings_date}) within expiration window"
        )

    high_risk_events = [e for e in cal_result.macro_events if e.risk_level == "high"]
    if high_risk_events:
        names = ", ".join(e.name for e in high_risk_events[:2])
        caution_reasons.append(f"major macro event within window ({names})")

    if recs.budget_exceeded:
        caution_reasons.append("no contracts fit stated budget — showing nearest alternative")

    if reject_reasons:
        return "reject", f"Rejected: {'; '.join(reject_reasons)}."

    if score < 6.5 or caution_reasons:
        parts = [f"Score {score:.1f}/10"]
        if caution_reasons:
            parts.append("Caution: " + "; ".join(caution_reasons))
        return "caution", ". ".join(parts) + "."

    return "accept", (
        f"Score {score:.1f}/10. Clean setup — within budget, "
        f"no major macro conflicts, delta and liquidity on target."
    )
