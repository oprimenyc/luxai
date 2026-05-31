"""
Account constraint enforcer — hard tier-based limits at the engine level.

Path: apps/api/src/trading/account_constraints.py
Security: These limits CANNOT be bypassed by any strategy, agent, or UI.
          Enforcement is at the engine level, not the UI level.
          Any violation is logged with structured fields for audit.
Scale: Pure Python, no I/O. O(1) check. Designed to be called on every
       order submission before it reaches the broker adapter.

Tier definitions from CLAUDE.md:
  Tiny      $0 – $499.99
  Growth    $500 – $2,499.99
  Aggressive $2,500 – $9,999.99
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

log = structlog.get_logger(__name__)


# ── Tier definitions ──────────────────────────────────────────────────────────


class AccountTier(StrEnum):
    TINY = "tiny"
    GROWTH = "growth"
    AGGRESSIVE = "aggressive"


def classify_tier(account_size: float) -> AccountTier:
    """Classify an account into a tier by equity."""
    if account_size < 500.0:
        return AccountTier.TINY
    if account_size < 2_500.0:
        return AccountTier.GROWTH
    return AccountTier.AGGRESSIVE


@dataclass(frozen=True)
class TierLimits:
    tier: AccountTier
    max_risk_usd: float                    # hard dollar cap on risk per trade
    max_risk_pct: float                    # hard percentage cap (applied to account)
    max_contracts: int                     # max option contracts per order
    min_dte: int                           # minimum days to expiration
    prohibited_strategies: frozenset[str]  # strategy tags that are rejected
    earnings_allowed: bool = False


_TIER_LIMITS: dict[AccountTier, TierLimits] = {
    AccountTier.TINY: TierLimits(
        tier=AccountTier.TINY,
        max_risk_usd=5.0,
        max_risk_pct=0.03,          # 3%
        max_contracts=1,
        min_dte=7,
        prohibited_strategies=frozenset(
            ["0DTE", "earnings", "naked", "averaging_down"]
        ),
        earnings_allowed=False,
    ),
    AccountTier.GROWTH: TierLimits(
        tier=AccountTier.GROWTH,
        max_risk_usd=25.0,
        max_risk_pct=0.05,          # 5%
        max_contracts=2,
        min_dte=5,
        prohibited_strategies=frozenset(["0DTE", "naked", "averaging_down"]),
        earnings_allowed=True,
    ),
    AccountTier.AGGRESSIVE: TierLimits(
        tier=AccountTier.AGGRESSIVE,
        max_risk_usd=float("inf"),   # governed by percentage only
        max_risk_pct=0.05,          # 5% hard cap — no exceptions
        max_contracts=5,
        min_dte=1,
        prohibited_strategies=frozenset(["naked", "averaging_down"]),
        earnings_allowed=True,
    ),
}


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class ConstraintCheckResult:
    passed: bool
    tier: AccountTier
    violations: list[str] = field(default_factory=list)
    effective_max_risk_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "tier": self.tier.value,
            "violations": self.violations,
            "effective_max_risk_usd": self.effective_max_risk_usd,
        }


# ── Enforcer ──────────────────────────────────────────────────────────────────


class AccountConstraintEnforcer:
    """
    Enforces per-tier hard limits on every order submission.

    This class has no I/O. It operates purely on the OrderConstraintInput
    provided by the caller. The caller (router) is responsible for assembling
    the input from the portfolio snapshot and the submitted order.

    Wiring:
        kill_switch check → shadow check → constraint check → idempotency → engine
    """

    def check(
        self,
        account_size: float,
        qty: int,
        estimated_risk_usd: float,
        dte: int | None,
        strategy_tags: list[str] | None = None,
        num_contracts: int | None = None,
    ) -> ConstraintCheckResult:
        """
        Run all tier-based constraint checks for an incoming order.

        Args:
            account_size: Current portfolio equity in USD.
            qty: Number of shares / contracts being ordered.
            estimated_risk_usd: Maximum loss estimate for the order (premium paid
                for options, or stop-loss distance × qty for equity).
            dte: Days to expiration. None for equity orders (DTE check skipped).
            strategy_tags: Optional list of strategy tags on the order (e.g. ["0DTE"]).
            num_contracts: For options, the contract count (may differ from qty).

        Returns:
            ConstraintCheckResult with passed=True if all checks clear,
            or passed=False with populated violations list.
        """
        tier = classify_tier(account_size)
        limits = _TIER_LIMITS[tier]
        violations: list[str] = []

        # Effective max risk = minimum of dollar cap and percentage cap
        pct_cap = account_size * limits.max_risk_pct
        effective_max = min(limits.max_risk_usd, pct_cap)

        # ── Check 1: Risk dollar amount ──────────────────────────────────────
        if estimated_risk_usd > effective_max:
            violations.append(
                f"Risk ${estimated_risk_usd:.2f} exceeds tier limit "
                f"${effective_max:.2f} ({tier} tier: "
                f"min(${ limits.max_risk_usd:.0f}, "
                f"{limits.max_risk_pct*100:.0f}% of account))"
            )

        # ── Check 2: Contract count ───────────────────────────────────────────
        contracts = num_contracts if num_contracts is not None else qty
        if contracts > limits.max_contracts:
            violations.append(
                f"Contract count {contracts} exceeds tier maximum "
                f"{limits.max_contracts} ({tier} tier)"
            )

        # ── Check 3: DTE minimum ──────────────────────────────────────────────
        if dte is not None and dte < limits.min_dte:
            violations.append(
                f"DTE {dte} is below tier minimum {limits.min_dte} ({tier} tier)"
            )

        # ── Check 4: Prohibited strategies ───────────────────────────────────
        tags = set(t.upper() for t in (strategy_tags or []))
        blocked = tags & {s.upper() for s in limits.prohibited_strategies}
        if blocked:
            violations.append(
                f"Strategy tag(s) {sorted(blocked)} are prohibited for "
                f"{tier} tier accounts"
            )

        passed = len(violations) == 0

        if not passed:
            log.warning(
                "account_constraint_violation",
                tier=tier,
                account_size=account_size,
                violations=violations,
                qty=qty,
                estimated_risk_usd=estimated_risk_usd,
                dte=dte,
                strategy_tags=strategy_tags,
            )

        return ConstraintCheckResult(
            passed=passed,
            tier=tier,
            violations=violations,
            effective_max_risk_usd=effective_max,
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_enforcer: AccountConstraintEnforcer | None = None


def get_account_enforcer() -> AccountConstraintEnforcer:
    """Return the shared AccountConstraintEnforcer singleton."""
    global _enforcer
    if _enforcer is None:
        _enforcer = AccountConstraintEnforcer()
    return _enforcer
