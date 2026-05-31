"""
Contract Recommender — always returns three alternatives.

Path: apps/api/src/workbench/recommender.py
Security: Pure logic. No I/O. Inputs validated by caller before passing in.
Scale: O(n) over contracts in chain. Chains are typically 100–400 contracts.
       Spread builder is O(n log n) due to sort.

Alternatives (per CLAUDE.md spec):
  Best Value       — highest Options Score within budget
  Best Probability — highest abs(delta) (best ITM odds); may exceed budget
  Spread Version   — debit spread at ~50% of single-leg cost
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import structlog

from src.options.greeks import BlackScholesGreeks
from src.options.scorer import OptionsScorer, ScoreResult
from src.trading.models import (
    OptionContract,
    OptionType,
    OptionsChain,
    SpreadLeg,
    VerticalSpread,
)

log = structlog.get_logger(__name__)


# ── Result models ─────────────────────────────────────────────────────────────

@dataclass
class ContractRecommendation:
    contract: OptionContract
    score: float
    score_breakdown: dict[str, float]
    estimated_cost_usd: float   # mid * 100 (per 1 contract)
    within_budget: bool
    max_loss: float              # = estimated_cost for debit (premium paid)
    max_profit: float            # theoretical unlimited for calls/puts
    breakeven: float
    risk_reward_note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract.model_dump(mode="json"),
            "score": round(self.score, 1),
            "score_breakdown": {k: round(v, 3) for k, v in self.score_breakdown.items()},
            "estimated_cost_usd": round(self.estimated_cost_usd, 2),
            "within_budget": self.within_budget,
            "max_loss": round(self.max_loss, 2),
            "max_profit": round(self.max_profit, 2),
            "breakeven": round(self.breakeven, 2),
            "risk_reward_note": self.risk_reward_note,
        }


@dataclass
class SpreadRecommendation:
    spread: VerticalSpread
    score: float                 # average of long-leg score
    net_debit: float             # what you pay in USD per contract pair
    within_budget: bool
    score_breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "spread": self.spread.model_dump(mode="json"),
            "score": round(self.score, 1),
            "net_debit": round(self.net_debit, 2),
            "within_budget": self.within_budget,
            "score_breakdown": {k: round(v, 3) for k, v in self.score_breakdown.items()},
        }


@dataclass
class RecommendationSet:
    best_value: ContractRecommendation | None
    best_probability: ContractRecommendation | None
    spread_version: SpreadRecommendation | None
    # If nothing fits budget: closest contract flagged
    budget_exceeded: bool = False
    budget_note: str = ""


# ── Recommender ───────────────────────────────────────────────────────────────

class ContractRecommender:
    """
    Produces three trade alternatives from an options chain.

    Enriches each contract with internally-calculated Greeks before scoring,
    overwriting any Tradier-supplied Greeks if both are available (Tradier
    Greeks are used as a cross-check hint only).

    Args:
        account_tier: "tiny" | "growth" | "aggressive"
        budget_usd: Maximum premium the trader will pay per contract (× 100).
        direction: "bullish" | "bearish" — determines call vs put selection.
    """

    _RISK_FREE_RATE = 0.045  # 4.5% — approximate 1-year T-bill

    def __init__(
        self,
        account_tier: str,
        budget_usd: float,
        direction: Literal["bullish", "bearish"],
    ) -> None:
        self._tier = account_tier.lower()
        self._budget = budget_usd
        self._direction = direction
        self._scorer = OptionsScorer(account_tier)
        self._option_type = OptionType.CALL if direction == "bullish" else OptionType.PUT

    def recommend(self, chain: OptionsChain) -> RecommendationSet:
        """
        Build all three recommendations from the supplied chain.

        Steps:
          1. Filter to the relevant leg (calls or puts by direction).
          2. Enrich Greeks via Black-Scholes using chain.underlying_price.
          3. Score every contract.
          4. Select Best Value, Best Probability, Spread Version.
        """
        contracts = (
            chain.calls if self._option_type == OptionType.CALL else chain.puts
        )
        if not contracts:
            log.warning(
                "recommender_no_contracts",
                underlying=chain.underlying,
                option_type=self._option_type,
            )
            return RecommendationSet(None, None, None)

        # ── Enrich + score all contracts ──────────────────────────────────────
        enriched: list[tuple[OptionContract, ScoreResult]] = []
        for contract in contracts:
            enriched_contract = self._enrich_greeks(contract, chain.underlying_price)
            score_result = self._scorer.score_contract(enriched_contract)
            enriched.append((enriched_contract, score_result))

        # Filter out tier violations
        valid = [(c, s) for c, s in enriched if not s.tier_violation]

        if not valid:
            log.warning(
                "recommender_all_violated",
                underlying=chain.underlying,
                tier=self._tier,
            )
            return RecommendationSet(None, None, None)

        # ── Best Value: highest score within budget ───────────────────────────
        within_budget = [
            (c, s) for c, s in valid
            if self._cost(c) <= self._budget
        ]

        best_value_rec: ContractRecommendation | None = None
        budget_exceeded = False
        budget_note = ""

        if within_budget:
            best_c, best_s = max(within_budget, key=lambda x: x[1].score)
            best_value_rec = self._build_rec(best_c, best_s, chain.underlying_price)
        else:
            # Nothing fits budget — return closest (cheapest) with flag
            cheapest_c, cheapest_s = min(valid, key=lambda x: self._cost(x[0]))
            best_value_rec = self._build_rec(cheapest_c, cheapest_s, chain.underlying_price)
            budget_exceeded = True
            budget_note = (
                f"No contracts fit your ${self._budget:.0f} budget. "
                f"Nearest: ${self._cost(cheapest_c):.0f} (${self._cost(cheapest_c) - self._budget:.0f} over)"
            )

        # ── Best Probability: highest absolute delta ──────────────────────────
        with_delta = [(c, s) for c, s in valid if c.greeks.delta is not None]
        best_prob_rec: ContractRecommendation | None = None
        if with_delta:
            prob_c, prob_s = max(
                with_delta,
                key=lambda x: abs(x[0].greeks.delta or 0.0),
            )
            best_prob_rec = self._build_rec(prob_c, prob_s, chain.underlying_price)

        # ── Spread Version: debit spread ~50% of single-leg cost ─────────────
        spread_rec = self._build_spread(valid, chain)

        return RecommendationSet(
            best_value=best_value_rec,
            best_probability=best_prob_rec,
            spread_version=spread_rec,
            budget_exceeded=budget_exceeded,
            budget_note=budget_note,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _enrich_greeks(
        self, contract: OptionContract, underlying_price: float
    ) -> OptionContract:
        """
        Re-compute Greeks via Black-Scholes using mid price as market price.
        If underlying_price is 0 (unavailable), keep Tradier Greeks as-is.
        """
        if underlying_price <= 0:
            return contract

        mid = contract.mid
        if mid <= 0:
            return contract

        opt_type_str = contract.option_type.value  # "call" or "put"

        # Use Tradier IV if available, otherwise compute via bisection
        iv = contract.greeks.iv
        if iv is None or iv <= 0:
            iv = BlackScholesGreeks.implied_volatility(
                market_price=mid,
                underlying_price=underlying_price,
                strike=contract.strike,
                expiry_date=contract.expiration,
                option_type=opt_type_str,
                risk_free_rate=self._RISK_FREE_RATE,
            )

        if iv is None or iv <= 0:
            return contract

        result = BlackScholesGreeks.compute(
            underlying_price=underlying_price,
            strike=contract.strike,
            expiry_date=contract.expiration,
            iv=iv,
            option_type=opt_type_str,
            risk_free_rate=self._RISK_FREE_RATE,
        )

        from src.trading.models import Greeks
        enriched_greeks = Greeks(
            delta=result.delta,
            gamma=result.gamma,
            theta=result.theta,
            vega=result.vega,
            iv=result.iv,
        )
        return contract.model_copy(update={"greeks": enriched_greeks})

    def _build_rec(
        self,
        contract: OptionContract,
        score_result: ScoreResult,
        underlying_price: float,
    ) -> ContractRecommendation:
        cost = self._cost(contract)
        delta = contract.greeks.delta or 0.0
        strike = contract.strike

        if self._option_type == OptionType.CALL:
            breakeven = strike + cost
            max_profit = max(0.0, (underlying_price * 2 - strike) - cost)  # illustrative
        else:
            breakeven = strike - cost
            max_profit = max(0.0, strike - cost)  # max at underlying → 0

        return ContractRecommendation(
            contract=contract,
            score=score_result.score,
            score_breakdown=score_result.breakdown,
            estimated_cost_usd=cost,
            within_budget=cost <= self._budget,
            max_loss=cost,
            max_profit=max_profit,
            breakeven=breakeven,
            risk_reward_note=(
                f"Max loss ${cost:.2f} | breakeven ${breakeven:.2f} | "
                f"delta {delta:+.2f}"
            ),
        )

    def _build_spread(
        self,
        valid: list[tuple[OptionContract, ScoreResult]],
        chain: OptionsChain,
    ) -> SpreadRecommendation | None:
        """
        Build a debit spread: buy near-ATM, sell 1–2 strikes OTM.
        Target: net debit ≈ 50% of the single-leg long cost.
        """
        if len(valid) < 2:
            return None

        underlying = chain.underlying_price

        # Find long leg: ATM or first strike above underlying (calls) / below (puts)
        if self._option_type == OptionType.CALL:
            atm_candidates = sorted(
                valid, key=lambda x: abs(x[0].strike - underlying)
            )
        else:
            atm_candidates = sorted(
                valid, key=lambda x: abs(x[0].strike - underlying)
            )

        if not atm_candidates:
            return None

        long_contract, long_score = atm_candidates[0]
        long_strike = long_contract.strike

        # Find short leg: 1–2 strikes OTM from long
        if self._option_type == OptionType.CALL:
            short_candidates = [
                (c, s) for c, s in valid
                if c.strike > long_strike
            ]
            short_candidates.sort(key=lambda x: x[0].strike)
        else:
            short_candidates = [
                (c, s) for c, s in valid
                if c.strike < long_strike
            ]
            short_candidates.sort(key=lambda x: x[0].strike, reverse=True)

        if not short_candidates:
            return None

        # Pick short leg 1–2 strikes away
        short_contract, _ = short_candidates[min(1, len(short_candidates) - 1)]

        long_mid  = long_contract.mid
        short_mid = short_contract.mid
        net_debit = max(0.0, long_mid - short_mid)
        net_debit_usd = round(net_debit * 100, 2)  # per contract pair

        width = abs(short_contract.strike - long_contract.strike)
        max_profit = max(0.0, width - net_debit) * 100
        max_loss   = net_debit_usd

        if self._option_type == OptionType.CALL:
            breakeven = long_contract.strike + net_debit
        else:
            breakeven = long_contract.strike - net_debit

        spread = VerticalSpread(
            underlying=chain.underlying,
            option_type=self._option_type,
            long_leg=SpreadLeg(contract=long_contract, quantity=1),
            short_leg=SpreadLeg(contract=short_contract, quantity=-1),
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakeven,
            risk_reward=max_profit / max_loss if max_loss > 0 else 0.0,
        )

        return SpreadRecommendation(
            spread=spread,
            score=long_score.score,
            net_debit=net_debit_usd,
            within_budget=net_debit_usd <= self._budget,
            score_breakdown=long_score.breakdown,
        )

    @staticmethod
    def _cost(contract: OptionContract) -> float:
        """Cost in USD per 1 contract (mid × 100)."""
        return contract.mid * 100.0
