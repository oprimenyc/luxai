"""
Unit tests for Black-Scholes Greeks engine.

Covers:
- Delta bounds: call [0,1], put [-1,0]
- Put-call parity for same strike/expiry
- Gamma symmetry
- Theta is negative for long positions (time decay)
- Vega is positive
- IV bisection: recovered IV matches input
- Edge cases: T=0, IV=0, deep ITM, deep OTM
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.options.greeks import BlackScholesGreeks, GreeksResult


def _expiry(days: int) -> date:
    return (datetime.now(UTC) + timedelta(days=days)).date()


# ── Delta bounds ──────────────────────────────────────────────────────────────

class TestDelta:
    def test_call_delta_between_0_and_1(self) -> None:
        r = BlackScholesGreeks.compute(100, 100, _expiry(30), 0.25, "call")
        assert 0.0 <= r.delta <= 1.0

    def test_put_delta_between_minus1_and_0(self) -> None:
        r = BlackScholesGreeks.compute(100, 100, _expiry(30), 0.25, "put")
        assert -1.0 <= r.delta <= 0.0

    def test_deep_itm_call_delta_near_1(self) -> None:
        r = BlackScholesGreeks.compute(200, 100, _expiry(30), 0.25, "call")
        assert r.delta > 0.95

    def test_deep_otm_call_delta_near_0(self) -> None:
        r = BlackScholesGreeks.compute(50, 200, _expiry(30), 0.25, "call")
        assert r.delta < 0.05

    def test_atm_call_delta_near_half(self) -> None:
        r = BlackScholesGreeks.compute(100, 100, _expiry(30), 0.20, "call")
        assert 0.45 <= r.delta <= 0.65

    def test_put_call_delta_sum_close_to_1(self) -> None:
        S, K, iv = 100.0, 100.0, 0.20
        call = BlackScholesGreeks.compute(S, K, _expiry(30), iv, "call")
        put  = BlackScholesGreeks.compute(S, K, _expiry(30), iv, "put")
        assert abs(call.delta + abs(put.delta) - 1.0) < 0.01


# ── Gamma ─────────────────────────────────────────────────────────────────────

class TestGamma:
    def test_gamma_positive(self) -> None:
        r = BlackScholesGreeks.compute(100, 100, _expiry(30), 0.25, "call")
        assert r.gamma > 0.0

    def test_put_and_call_same_gamma(self) -> None:
        S, K, iv = 100.0, 105.0, 0.20
        call = BlackScholesGreeks.compute(S, K, _expiry(30), iv, "call")
        put  = BlackScholesGreeks.compute(S, K, _expiry(30), iv, "put")
        assert abs(call.gamma - put.gamma) < 1e-8


# ── Theta ─────────────────────────────────────────────────────────────────────

class TestTheta:
    def test_call_theta_negative(self) -> None:
        r = BlackScholesGreeks.compute(100, 100, _expiry(30), 0.25, "call")
        assert r.theta < 0.0

    def test_put_theta_negative(self) -> None:
        r = BlackScholesGreeks.compute(100, 100, _expiry(30), 0.25, "put")
        assert r.theta < 0.0

    def test_theta_larger_near_expiry(self) -> None:
        far  = BlackScholesGreeks.compute(100, 100, _expiry(60), 0.25, "call")
        near = BlackScholesGreeks.compute(100, 100, _expiry(7),  0.25, "call")
        assert abs(near.theta) > abs(far.theta)


# ── Vega ──────────────────────────────────────────────────────────────────────

class TestVega:
    def test_vega_positive(self) -> None:
        r = BlackScholesGreeks.compute(100, 100, _expiry(30), 0.25, "call")
        assert r.vega > 0.0

    def test_put_call_same_vega(self) -> None:
        S, K, iv = 100.0, 100.0, 0.25
        call = BlackScholesGreeks.compute(S, K, _expiry(30), iv, "call")
        put  = BlackScholesGreeks.compute(S, K, _expiry(30), iv, "put")
        assert abs(call.vega - put.vega) < 1e-8


# ── Put-call parity ───────────────────────────────────────────────────────────

class TestPutCallParity:
    def test_put_call_parity(self) -> None:
        """C - P ≈ S - K*e^(-rT) (Black-Scholes put-call parity)."""
        import math
        S, K, iv, r = 100.0, 100.0, 0.20, 0.045
        T = 30 / 365.0
        call = BlackScholesGreeks.compute(S, K, _expiry(30), iv, "call", r)
        put  = BlackScholesGreeks.compute(S, K, _expiry(30), iv, "put",  r)
        lhs = call.price - put.price
        rhs = S - K * math.exp(-r * T)
        assert abs(lhs - rhs) < 0.01


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_expired_call_intrinsic_only(self) -> None:
        r = BlackScholesGreeks.compute(110, 100, _expiry(-1), 0.25, "call")
        assert r.price == pytest.approx(10.0, abs=0.01)

    def test_expired_otm_call_zero(self) -> None:
        r = BlackScholesGreeks.compute(90, 100, _expiry(-1), 0.25, "call")
        assert r.price == pytest.approx(0.0, abs=0.001)

    def test_zero_iv_returns_intrinsic(self) -> None:
        # IV=0 → time value=0, price = intrinsic = max(S-K,0) = 10
        r = BlackScholesGreeks.compute(110, 100, _expiry(30), 0.0, "call")
        assert r.price == pytest.approx(10.0, abs=0.01)
        assert r.gamma == 0.0
        assert r.vega == 0.0

    def test_price_non_negative(self) -> None:
        for S in [50, 100, 150]:
            r = BlackScholesGreeks.compute(S, 100, _expiry(30), 0.30, "call")
            assert r.price >= 0.0


# ── IV bisection ──────────────────────────────────────────────────────────────

class TestImpliedVolatility:
    def test_iv_recovers_input_iv(self) -> None:
        S, K, target_iv = 100.0, 100.0, 0.25
        expiry = _expiry(30)
        result = BlackScholesGreeks.compute(S, K, expiry, target_iv, "call")
        recovered = BlackScholesGreeks.implied_volatility(
            result.price, S, K, expiry, "call"
        )
        assert recovered is not None
        assert abs(recovered - target_iv) < 0.001

    def test_iv_recovers_for_put(self) -> None:
        S, K, target_iv = 100.0, 105.0, 0.30
        expiry = _expiry(21)
        result = BlackScholesGreeks.compute(S, K, expiry, target_iv, "put")
        recovered = BlackScholesGreeks.implied_volatility(
            result.price, S, K, expiry, "put"
        )
        assert recovered is not None
        assert abs(recovered - target_iv) < 0.001

    def test_iv_returns_none_on_expired(self) -> None:
        iv = BlackScholesGreeks.implied_volatility(5.0, 100, 100, _expiry(-1), "call")
        assert iv is None

    def test_iv_returns_none_on_zero_price(self) -> None:
        iv = BlackScholesGreeks.implied_volatility(0.0, 100, 100, _expiry(30), "call")
        assert iv is None

    def test_greeks_result_to_dict(self) -> None:
        r = BlackScholesGreeks.compute(100, 100, _expiry(30), 0.25, "call")
        d = r.to_dict()
        for key in ("delta", "gamma", "theta", "vega", "iv", "price"):
            assert key in d
