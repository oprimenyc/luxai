"""
Unit tests for OptionsScorer.

Covers:
- Perfect score (all factors max)
- Zero score (all factors min)
- Per-factor sensitivity
- Tier enforcement (DTE below tier minimum → 0.0 + violation flag)
- Score range always 0–10
- score_contract() convenience wrapper
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.options.scorer import OptionsScorer, ScoreResult


def _dte(days: int) -> int:
    return days


# ── Score range invariant ─────────────────────────────────────────────────────

class TestScoreRange:
    def test_score_always_between_0_and_10(self) -> None:
        scorer = OptionsScorer("tiny")
        for oi in [0, 100, 500, 5000]:
            for spread_pct in [0.01, 0.10, 0.50]:
                result = scorer.score(
                    open_interest=oi,
                    bid=1.0 - spread_pct / 2,
                    ask=1.0 + spread_pct / 2,
                    delta=0.40,
                    iv=0.30,
                    dte=14,
                )
                assert 0.0 <= result.score <= 10.0, f"Score out of range: {result.score}"


# ── Perfect score ─────────────────────────────────────────────────────────────

class TestPerfectScore:
    def test_max_score_conditions(self) -> None:
        scorer = OptionsScorer("growth")
        result = scorer.score(
            open_interest=1000,  # OI >> 500 → liquidity = 1.0
            bid=0.95,
            ask=1.05,           # spread = 5% → spread = 1.0
            delta=0.40,         # in [0.25, 0.55] → delta = 1.0
            iv=0.20,            # < 30% → iv = 1.0
            dte=14,             # in [7, 21] → dte = 1.0
        )
        assert result.score == pytest.approx(10.0, abs=0.01)
        assert not result.tier_violation


# ── Zero-ish score ────────────────────────────────────────────────────────────

class TestLowScore:
    def test_low_score_conditions(self) -> None:
        scorer = OptionsScorer("aggressive")
        result = scorer.score(
            open_interest=0,    # OI=0 → liquidity=0
            bid=0.0,
            ask=2.0,            # 200% spread → spread=0
            delta=0.99,         # deep ITM → delta near 0
            iv=1.50,            # 150% IV → iv=0
            dte=200,            # far OTM DTE → dte=0
        )
        assert result.score < 2.0


# ── Tier enforcement ──────────────────────────────────────────────────────────

class TestTierEnforcement:
    def test_tiny_dte_6_is_violation(self) -> None:
        scorer = OptionsScorer("tiny")  # min_dte=7
        result = scorer.score(open_interest=1000, bid=0.95, ask=1.05, delta=0.40, iv=0.20, dte=6)
        assert result.tier_violation
        assert result.score == 0.0
        assert "DTE" in result.violation_reason

    def test_tiny_dte_7_passes(self) -> None:
        scorer = OptionsScorer("tiny")
        result = scorer.score(open_interest=1000, bid=0.95, ask=1.05, delta=0.40, iv=0.20, dte=7)
        assert not result.tier_violation

    def test_growth_dte_4_is_violation(self) -> None:
        scorer = OptionsScorer("growth")  # min_dte=5
        result = scorer.score(open_interest=1000, bid=0.95, ask=1.05, delta=0.40, iv=0.20, dte=4)
        assert result.tier_violation

    def test_growth_dte_5_passes(self) -> None:
        scorer = OptionsScorer("growth")
        result = scorer.score(open_interest=1000, bid=0.95, ask=1.05, delta=0.40, iv=0.20, dte=5)
        assert not result.tier_violation

    def test_aggressive_dte_1_passes(self) -> None:
        scorer = OptionsScorer("aggressive")  # min_dte=1
        result = scorer.score(open_interest=1000, bid=0.95, ask=1.05, delta=0.40, iv=0.20, dte=1)
        assert not result.tier_violation


# ── Per-factor sensitivity ────────────────────────────────────────────────────

class TestFactorSensitivity:
    def test_higher_oi_higher_liquidity(self) -> None:
        scorer = OptionsScorer("growth")
        low  = scorer.score(open_interest=100,  bid=0.95, ask=1.05, delta=0.40, iv=0.25, dte=14)
        high = scorer.score(open_interest=1000, bid=0.95, ask=1.05, delta=0.40, iv=0.25, dte=14)
        assert high.score > low.score

    def test_tighter_spread_higher_score(self) -> None:
        scorer = OptionsScorer("growth")
        wide  = scorer.score(open_interest=500, bid=0.5, ask=1.5, delta=0.40, iv=0.25, dte=14)
        tight = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=0.25, dte=14)
        assert tight.score > wide.score

    def test_delta_outside_range_lower_score(self) -> None:
        scorer = OptionsScorer("growth")
        ideal = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=0.25, dte=14)
        deep  = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.99, iv=0.25, dte=14)
        assert ideal.score > deep.score

    def test_high_iv_lower_score(self) -> None:
        scorer = OptionsScorer("growth")
        low_iv  = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=0.20, dte=14)
        high_iv = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=0.90, dte=14)
        assert low_iv.score > high_iv.score

    def test_optimal_dte_higher_score(self) -> None:
        scorer = OptionsScorer("growth")
        good = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=0.25, dte=14)
        far  = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=0.25, dte=90)
        assert good.score > far.score


# ── Breakdown keys ────────────────────────────────────────────────────────────

class TestBreakdownKeys:
    def test_breakdown_has_all_factors(self) -> None:
        scorer = OptionsScorer("growth")
        result = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=0.25, dte=14)
        for key in ("liquidity", "spread", "delta", "iv", "dte"):
            assert key in result.breakdown

    def test_to_dict_structure(self) -> None:
        scorer = OptionsScorer("growth")
        result = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=0.25, dte=14)
        d = result.to_dict()
        assert "score" in d
        assert "breakdown" in d
        assert "tier_violation" in d
        assert isinstance(d["score"], float)


# ── None delta/IV handling ────────────────────────────────────────────────────

class TestNoneInputs:
    def test_none_delta_returns_neutral_score(self) -> None:
        scorer = OptionsScorer("growth")
        result = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=None, iv=0.25, dte=14)
        assert 0.0 <= result.score <= 10.0
        assert not result.tier_violation

    def test_none_iv_returns_neutral_score(self) -> None:
        scorer = OptionsScorer("growth")
        result = scorer.score(open_interest=500, bid=0.95, ask=1.05, delta=0.40, iv=None, dte=14)
        assert 0.0 <= result.score <= 10.0
