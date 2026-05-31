"""
Unit tests for AccountConstraintEnforcer.

All checks are pure-Python, no I/O. Tests cover:
- Tier classification
- Risk dollar cap enforcement
- Percentage cap enforcement (effective_max = min(dollar_cap, pct_cap))
- Contract count limits
- DTE minimums
- Prohibited strategy tags
- Earnings flag per tier
- Multi-violation accumulation
"""

from __future__ import annotations

import pytest

from src.trading.account_constraints import (
    AccountConstraintEnforcer,
    AccountTier,
    ConstraintCheckResult,
    classify_tier,
    get_account_enforcer,
)


# ── Tier classification ───────────────────────────────────────────────────────


class TestClassifyTier:
    def test_zero_balance_is_tiny(self) -> None:
        assert classify_tier(0.0) == AccountTier.TINY

    def test_just_below_growth_is_tiny(self) -> None:
        assert classify_tier(499.99) == AccountTier.TINY

    def test_exactly_500_is_growth(self) -> None:
        assert classify_tier(500.0) == AccountTier.GROWTH

    def test_mid_growth(self) -> None:
        assert classify_tier(1500.0) == AccountTier.GROWTH

    def test_just_below_aggressive_is_growth(self) -> None:
        assert classify_tier(2499.99) == AccountTier.GROWTH

    def test_exactly_2500_is_aggressive(self) -> None:
        assert classify_tier(2500.0) == AccountTier.AGGRESSIVE

    def test_large_account_is_aggressive(self) -> None:
        assert classify_tier(50_000.0) == AccountTier.AGGRESSIVE


# ── Tiny tier ─────────────────────────────────────────────────────────────────


class TestTinyTier:
    @pytest.fixture
    def enforcer(self) -> AccountConstraintEnforcer:
        return AccountConstraintEnforcer()

    def test_0dte_rejected(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=4.0,
            dte=0,
            strategy_tags=["0DTE"],
        )
        assert not result.passed
        assert any("0DTE" in v or "0dte" in v.upper() for v in result.violations)

    def test_earnings_tag_rejected_for_tiny(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=4.0,
            dte=14,
            strategy_tags=["earnings"],
        )
        assert not result.passed
        assert any("EARNINGS" in v.upper() for v in result.violations)

    def test_naked_tag_rejected_for_tiny(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=4.0,
            dte=14,
            strategy_tags=["naked"],
        )
        assert not result.passed

    def test_averaging_down_rejected(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=3.0,
            dte=14,
            strategy_tags=["averaging_down"],
        )
        assert not result.passed

    def test_dollar_risk_exceeds_cap(self, enforcer: AccountConstraintEnforcer) -> None:
        # Tiny: max_risk_usd=5, 3% of $300 = $9 → effective_max = min(5,9) = $5
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=6.0,  # over $5 cap
            dte=14,
        )
        assert not result.passed
        assert result.effective_max_risk_usd == pytest.approx(5.0)
        assert any("Risk" in v for v in result.violations)

    def test_pct_cap_is_binding_when_lower(self, enforcer: AccountConstraintEnforcer) -> None:
        # account_size=$100: 3% pct_cap=$3, dollar_cap=$5 → effective_max=$3
        result = enforcer.check(
            account_size=100.0,
            qty=1,
            estimated_risk_usd=4.0,
            dte=14,
        )
        assert not result.passed
        assert result.effective_max_risk_usd == pytest.approx(3.0)

    def test_two_contracts_rejected_for_tiny(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=3.0,
            dte=14,
            num_contracts=2,
        )
        assert not result.passed
        assert any("Contract" in v for v in result.violations)

    def test_dte_below_minimum_rejected(self, enforcer: AccountConstraintEnforcer) -> None:
        # Tiny min_dte=7
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=3.0,
            dte=6,
        )
        assert not result.passed
        assert any("DTE" in v for v in result.violations)

    def test_valid_tiny_trade_passes(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=4.0,
            dte=14,
        )
        assert result.passed
        assert result.violations == []
        assert result.tier == AccountTier.TINY

    def test_none_dte_skips_dte_check(self, enforcer: AccountConstraintEnforcer) -> None:
        # Equity orders have no DTE — check must be skipped
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=4.0,
            dte=None,
        )
        assert result.passed


# ── Growth tier ───────────────────────────────────────────────────────────────


class TestGrowthTier:
    @pytest.fixture
    def enforcer(self) -> AccountConstraintEnforcer:
        return AccountConstraintEnforcer()

    def test_earnings_allowed_for_growth(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=1000.0,
            qty=1,
            estimated_risk_usd=20.0,
            dte=10,
            strategy_tags=["earnings"],
        )
        assert result.passed

    def test_0dte_still_rejected_for_growth(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=1000.0,
            qty=1,
            estimated_risk_usd=20.0,
            dte=0,
            strategy_tags=["0DTE"],
        )
        assert not result.passed

    def test_three_contracts_rejected_for_growth(self, enforcer: AccountConstraintEnforcer) -> None:
        # Growth max_contracts=2
        result = enforcer.check(
            account_size=1000.0,
            qty=1,
            estimated_risk_usd=20.0,
            dte=10,
            num_contracts=3,
        )
        assert not result.passed

    def test_two_contracts_allowed_for_growth(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=1000.0,
            qty=1,
            estimated_risk_usd=20.0,
            dte=10,
            num_contracts=2,
        )
        assert result.passed

    def test_risk_above_dollar_cap_rejected(self, enforcer: AccountConstraintEnforcer) -> None:
        # Growth: max_risk_usd=25, 5% of $1000=$50 → effective_max=min(25,50)=$25
        result = enforcer.check(
            account_size=1000.0,
            qty=1,
            estimated_risk_usd=26.0,
            dte=10,
        )
        assert not result.passed

    def test_risk_at_pct_boundary_rejected(self, enforcer: AccountConstraintEnforcer) -> None:
        # account=$2000: 5% pct_cap=$100, dollar_cap=$25 → effective_max=$25
        result = enforcer.check(
            account_size=2000.0,
            qty=1,
            estimated_risk_usd=26.0,
            dte=10,
        )
        assert not result.passed

    def test_dte_at_minimum_passes(self, enforcer: AccountConstraintEnforcer) -> None:
        # Growth min_dte=5
        result = enforcer.check(
            account_size=1000.0,
            qty=1,
            estimated_risk_usd=20.0,
            dte=5,
        )
        assert result.passed

    def test_dte_below_minimum_rejected(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=1000.0,
            qty=1,
            estimated_risk_usd=20.0,
            dte=4,
        )
        assert not result.passed


# ── Aggressive tier ───────────────────────────────────────────────────────────


class TestAggressiveTier:
    @pytest.fixture
    def enforcer(self) -> AccountConstraintEnforcer:
        return AccountConstraintEnforcer()

    def test_five_contracts_allowed(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=5000.0,
            qty=1,
            estimated_risk_usd=200.0,
            dte=5,
            num_contracts=5,
        )
        assert result.passed

    def test_six_contracts_rejected(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=5000.0,
            qty=1,
            estimated_risk_usd=200.0,
            dte=5,
            num_contracts=6,
        )
        assert not result.passed

    def test_pct_cap_enforced_no_dollar_cap(self, enforcer: AccountConstraintEnforcer) -> None:
        # Aggressive: max_risk_usd=inf, max_risk_pct=5%
        # account=$5000: effective_max = min(inf, $250) = $250
        result = enforcer.check(
            account_size=5000.0,
            qty=1,
            estimated_risk_usd=260.0,  # over 5%
            dte=5,
        )
        assert not result.passed

    def test_exactly_at_pct_cap_passes(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=5000.0,
            qty=1,
            estimated_risk_usd=250.0,  # exactly 5%
            dte=5,
        )
        assert result.passed

    def test_naked_still_prohibited_aggressive(self, enforcer: AccountConstraintEnforcer) -> None:
        result = enforcer.check(
            account_size=5000.0,
            qty=1,
            estimated_risk_usd=100.0,
            dte=5,
            strategy_tags=["naked"],
        )
        assert not result.passed

    def test_1dte_allowed_aggressive(self, enforcer: AccountConstraintEnforcer) -> None:
        # Aggressive min_dte=1
        result = enforcer.check(
            account_size=5000.0,
            qty=1,
            estimated_risk_usd=100.0,
            dte=1,
        )
        assert result.passed

    def test_0dte_rejected_aggressive(self, enforcer: AccountConstraintEnforcer) -> None:
        # dte=0 < min_dte=1
        result = enforcer.check(
            account_size=5000.0,
            qty=1,
            estimated_risk_usd=100.0,
            dte=0,
        )
        assert not result.passed


# ── Multi-violation ───────────────────────────────────────────────────────────


class TestMultiViolation:
    def test_all_violations_collected(self) -> None:
        enforcer = AccountConstraintEnforcer()
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=100.0,  # over cap
            dte=3,                      # below min_dte=7
            strategy_tags=["0DTE", "naked"],  # both prohibited
            num_contracts=5,            # over max_contracts=1
        )
        assert not result.passed
        assert len(result.violations) >= 3

    def test_result_to_dict(self) -> None:
        enforcer = AccountConstraintEnforcer()
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=4.0,
            dte=14,
        )
        d = result.to_dict()
        assert "passed" in d
        assert "tier" in d
        assert "violations" in d
        assert "effective_max_risk_usd" in d


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_account_enforcer_returns_same_instance(self) -> None:
        a = get_account_enforcer()
        b = get_account_enforcer()
        assert a is b


# ── Strategy tag case insensitivity ──────────────────────────────────────────


class TestTagCaseInsensitivity:
    def test_mixed_case_tag_detected(self) -> None:
        enforcer = AccountConstraintEnforcer()
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=3.0,
            dte=14,
            strategy_tags=["EaRnInGs"],  # mixed case
        )
        assert not result.passed

    def test_uppercase_0dte_detected(self) -> None:
        enforcer = AccountConstraintEnforcer()
        result = enforcer.check(
            account_size=300.0,
            qty=1,
            estimated_risk_usd=3.0,
            dte=8,
            strategy_tags=["0dte"],  # lowercase
        )
        assert not result.passed
