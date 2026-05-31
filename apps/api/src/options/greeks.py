"""
Black-Scholes Greeks engine — calculated internally, never purchased.

Path: apps/api/src/options/greeks.py
Security: Pure computation. No external calls. No credentials.
          Per CLAUDE.md Rule 10: Greeks are ALWAYS calculated internally.
Scale: O(1) per contract. Bisection IV converges in ≤50 iterations.
       Safe to call in a tight loop over a full options chain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal


# ── Standard normal helpers ───────────────────────────────────────────────────

def _N(x: float) -> float:
    """Standard normal CDF — exact via math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _n(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class GreeksResult:
    """
    Computed Black-Scholes Greeks for a single option contract.

    All values are per-share (divide by 100 for per-contract P&L impact).
    Theta is daily (annualised theta / 365).
    Vega is per 1% move in IV.
    """
    delta: float
    gamma: float
    theta: float   # per calendar day
    vega: float    # per 1% change in IV
    iv: float      # annualised implied volatility (0–1 range; 0.25 = 25%)
    price: float   # theoretical BS price

    def to_dict(self) -> dict[str, float]:
        return {
            "delta": round(self.delta, 4),
            "gamma": round(self.gamma, 4),
            "theta": round(self.theta, 4),
            "vega": round(self.vega, 4),
            "iv": round(self.iv, 4),
            "price": round(self.price, 4),
        }


# ── Core Black-Scholes engine ─────────────────────────────────────────────────

class BlackScholesGreeks:
    """
    Black-Scholes Greeks calculator for European-style options.

    All inputs in standard units:
      - Prices in USD
      - Volatility as decimal (0.25 = 25% IV)
      - Risk-free rate as decimal (0.05 = 5%)
      - Time in years (computed from expiry_date)

    Edge cases handled:
      - T ≤ 0 (expiry today or past): intrinsic value only, Greeks set to boundary values
      - Deep ITM / OTM: numerically stable via math.erfc
      - IV = 0: returns intrinsic with zero Greeks (avoids division by zero)
    """

    _DEFAULT_RISK_FREE_RATE = 0.045   # 4.5% — approximate 1-year T-bill yield

    # ── Public interface ──────────────────────────────────────────────────────

    @classmethod
    def compute(
        cls,
        underlying_price: float,
        strike: float,
        expiry_date: date,
        iv: float,
        option_type: Literal["call", "put"],
        risk_free_rate: float | None = None,
    ) -> GreeksResult:
        """
        Compute all Greeks for a given option.

        Args:
            underlying_price: Current spot price of the underlying (S).
            strike: Option strike price (K).
            expiry_date: Expiration date of the option.
            iv: Implied volatility, annualised (0.25 = 25%).
            option_type: "call" or "put".
            risk_free_rate: Annualised risk-free rate. Defaults to 4.5%.

        Returns:
            GreeksResult with all computed values.
        """
        r = risk_free_rate if risk_free_rate is not None else cls._DEFAULT_RISK_FREE_RATE
        T = cls._time_to_expiry(expiry_date)

        # Edge case: expired or expiring today
        if T <= 0.0:
            return cls._intrinsic_result(underlying_price, strike, option_type, iv)

        # Edge case: zero volatility — return intrinsic + zero Greeks
        if iv <= 0.0:
            price = cls._intrinsic(underlying_price, strike, option_type)
            return GreeksResult(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, iv=0.0, price=price)

        S, K, sigma = underlying_price, strike, iv
        sqrt_T = math.sqrt(T)
        exp_rT = math.exp(-r * T)

        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        if option_type == "call":
            price  = S * _N(d1) - K * exp_rT * _N(d2)
            delta  = _N(d1)
            theta  = (
                -S * _n(d1) * sigma / (2.0 * sqrt_T)
                - r * K * exp_rT * _N(d2)
            ) / 365.0
        else:
            price  = K * exp_rT * _N(-d2) - S * _N(-d1)
            delta  = _N(d1) - 1.0
            theta  = (
                -S * _n(d1) * sigma / (2.0 * sqrt_T)
                + r * K * exp_rT * _N(-d2)
            ) / 365.0

        gamma = _n(d1) / (S * sigma * sqrt_T)
        vega  = S * _n(d1) * sqrt_T / 100.0   # per 1% change in vol

        return GreeksResult(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            iv=iv,
            price=max(price, 0.0),
        )

    @classmethod
    def implied_volatility(
        cls,
        market_price: float,
        underlying_price: float,
        strike: float,
        expiry_date: date,
        option_type: Literal["call", "put"],
        risk_free_rate: float | None = None,
        tolerance: float = 1e-6,
        max_iterations: int = 100,
    ) -> float | None:
        """
        Compute implied volatility via bisection method.

        Args:
            market_price: Observed market price (mid of bid/ask).
            tolerance: Convergence threshold (default 1e-6).
            max_iterations: Safety cap on bisection iterations.

        Returns:
            Annualised IV as decimal (e.g. 0.25 for 25%), or None if
            no solution found (deep ITM/OTM or invalid inputs).
        """
        r = risk_free_rate if risk_free_rate is not None else cls._DEFAULT_RISK_FREE_RATE
        T = cls._time_to_expiry(expiry_date)

        if T <= 0.0 or market_price <= 0.0:
            return None

        # Intrinsic value guard — market price must exceed intrinsic
        intrinsic = cls._intrinsic(underlying_price, strike, option_type)
        if market_price < intrinsic - tolerance:
            return None

        sigma_low, sigma_high = 0.001, 5.0

        def _price(sigma: float) -> float:
            result = cls.compute(underlying_price, strike, expiry_date, sigma, option_type, r)
            return result.price

        # Verify the bisection bracket
        if _price(sigma_low) > market_price or _price(sigma_high) < market_price:
            return None

        for _ in range(max_iterations):
            sigma_mid = (sigma_low + sigma_high) / 2.0
            diff = _price(sigma_mid) - market_price

            if abs(diff) < tolerance:
                return sigma_mid

            if diff < 0:
                sigma_low = sigma_mid
            else:
                sigma_high = sigma_mid

        return (sigma_low + sigma_high) / 2.0

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _time_to_expiry(expiry_date: date) -> float:
        """Return T in years. Returns 0.0 if expiry is today or in the past."""
        today = datetime.now(UTC).date()
        delta = (expiry_date - today).days
        return max(delta / 365.0, 0.0)

    @staticmethod
    def _intrinsic(
        S: float, K: float, option_type: Literal["call", "put"]
    ) -> float:
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    @classmethod
    def _intrinsic_result(
        cls,
        S: float,
        K: float,
        option_type: Literal["call", "put"],
        iv: float,
    ) -> GreeksResult:
        """Greeks at expiry — boundary conditions apply."""
        intrinsic = cls._intrinsic(S, K, option_type)
        # Delta at expiry: 1 if ITM call, 0 if OTM; -1 if ITM put, 0 if OTM
        if option_type == "call":
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return GreeksResult(
            delta=delta, gamma=0.0, theta=0.0, vega=0.0, iv=iv, price=intrinsic
        )
