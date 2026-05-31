"""
Options Scorer — 5-factor weighted score 0–10.

Path: apps/api/src/options/scorer.py
Security: Pure computation, no I/O. Account tier passed in — never derived
          from user input directly (caller reads from engine snapshot).
Scale: O(1) per contract. Safe to call across an entire options chain in a loop.

Score factors (CLAUDE.md spec):
  Liquidity  — Open Interest > 500           25%
  Spread     — Spread < 10% of mid           20%
  Delta      — Delta in 0.25–0.55 range      20%
  IV         — IV < 65% (proxy for IV Rank)  20%
  DTE        — DTE between 7 and 21 days     15%

Score is 0–10 with one decimal place of precision.
Tier-aware: Tiny tier rejects DTE < 7 before scoring (returns 0.0 with violation flag).
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Score factor weights (must sum to 1.0) ────────────────────────────────────

_W_LIQUIDITY = 0.25
_W_SPREAD    = 0.20
_W_DELTA     = 0.20
_W_IV        = 0.20
_W_DTE       = 0.15

assert abs(_W_LIQUIDITY + _W_SPREAD + _W_DELTA + _W_IV + _W_DTE - 1.0) < 1e-9


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ScoreResult:
    """
    Scoring result for a single option contract.

    score: Overall weighted score 0–10 (one decimal precision).
    breakdown: Per-factor raw scores 0–1 before weighting.
    tier_violation: True if the contract is prohibited for the account tier
                    (e.g. Tiny tier, DTE < 7). Score is forced to 0.0 if True.
    violation_reason: Human-readable explanation if tier_violation is True.
    """
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    tier_violation: bool = False
    violation_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 1),
            "breakdown": {k: round(v, 3) for k, v in self.breakdown.items()},
            "tier_violation": self.tier_violation,
            "violation_reason": self.violation_reason,
        }


# ── Scorer ────────────────────────────────────────────────────────────────────

class OptionsScorer:
    """
    Scores a single option contract 0–10 based on five quality factors.

    Instantiate once and reuse across a full chain — the scorer is stateless.

    Args:
        account_tier: "tiny" | "growth" | "aggressive" — controls min DTE enforcement.
    """

    _MIN_DTE: dict[str, int] = {
        "tiny": 7,
        "growth": 5,
        "aggressive": 1,
    }

    def __init__(self, account_tier: str = "tiny") -> None:
        self._tier = account_tier.lower()
        self._min_dte = self._MIN_DTE.get(self._tier, 7)

    def score(
        self,
        open_interest: int,
        bid: float,
        ask: float,
        delta: float | None,
        iv: float | None,
        dte: int,
    ) -> ScoreResult:
        """
        Compute the options score for a single contract.

        Args:
            open_interest: Number of open contracts.
            bid: Best bid price.
            ask: Best ask price.
            delta: Absolute delta value (0–1). Pass None if unknown.
            iv: Implied volatility as decimal (0.25 = 25%). Pass None if unknown.
            dte: Days to expiration.

        Returns:
            ScoreResult with weighted score and per-factor breakdown.
        """
        # ── Tier enforcement ──────────────────────────────────────────────────
        if dte < self._min_dte:
            return ScoreResult(
                score=0.0,
                breakdown={},
                tier_violation=True,
                violation_reason=(
                    f"DTE {dte} below minimum {self._min_dte} for {self._tier} tier"
                ),
            )

        # ── Factor 1: Liquidity (OI > 500) ───────────────────────────────────
        f_liquidity = min(open_interest / 500.0, 1.0) if open_interest > 0 else 0.0

        # ── Factor 2: Spread < 10% of mid ────────────────────────────────────
        mid = (bid + ask) / 2.0 if (bid + ask) > 0 else 0.0
        spread = ask - bid
        if mid > 0:
            spread_pct = spread / mid
            # Full score at ≤10%, linear decay to 0 at ≥20%
            f_spread = max(0.0, 1.0 - max(0.0, spread_pct - 0.10) / 0.10)
        else:
            f_spread = 0.0

        # ── Factor 3: Delta in 0.25–0.55 ─────────────────────────────────────
        if delta is None:
            f_delta = 0.5  # neutral penalty when delta unknown
        else:
            abs_delta = abs(delta)
            if 0.25 <= abs_delta <= 0.55:
                f_delta = 1.0
            elif abs_delta < 0.25:
                # Linear decay from 0.25 down to 0
                f_delta = abs_delta / 0.25
            else:
                # abs_delta > 0.55: linear decay from 0.55 up to 1.0
                f_delta = max(0.0, 1.0 - (abs_delta - 0.55) / 0.45)

        # ── Factor 4: IV < 65% (proxy for IV Rank) ───────────────────────────
        if iv is None:
            f_iv = 0.5  # neutral penalty when IV unknown
        else:
            if iv <= 0.30:
                f_iv = 1.0
            elif iv <= 0.65:
                # Linear decay from 1.0 at 30% to 0.5 at 65%
                f_iv = 1.0 - 0.5 * (iv - 0.30) / 0.35
            else:
                # Above 65% threshold: further decay to 0
                f_iv = max(0.0, 0.5 - 0.5 * (iv - 0.65) / 0.35)

        # ── Factor 5: DTE 7–21 ────────────────────────────────────────────────
        if 7 <= dte <= 21:
            f_dte = 1.0
        elif dte < 7:
            # Already handled by tier check above for tiny; growth/aggressive may land here
            f_dte = max(0.0, dte / 7.0)
        else:
            # dte > 21: linear decay from 1.0 at 21 to 0.0 at 90
            f_dte = max(0.0, 1.0 - (dte - 21) / 69.0)

        # ── Weighted sum → 0–10 scale ─────────────────────────────────────────
        raw_score = (
            f_liquidity * _W_LIQUIDITY
            + f_spread   * _W_SPREAD
            + f_delta    * _W_DELTA
            + f_iv       * _W_IV
            + f_dte      * _W_DTE
        )
        score = round(raw_score * 10.0, 1)

        breakdown = {
            "liquidity": f_liquidity,
            "spread":    f_spread,
            "delta":     f_delta,
            "iv":        f_iv,
            "dte":       f_dte,
        }

        return ScoreResult(score=score, breakdown=breakdown)

    def score_contract(self, contract: "OptionContract") -> ScoreResult:  # type: ignore[name-defined]
        """Convenience wrapper that unpacks an OptionContract."""
        return self.score(
            open_interest=contract.open_interest,
            bid=contract.bid,
            ask=contract.ask,
            delta=contract.greeks.delta,
            iv=contract.greeks.iv,
            dte=contract.dte,
        )


# ── Type hint import (avoid circular at module level) ─────────────────────────
from src.trading.models import OptionContract  # noqa: E402
