"""Unit tests for all deterministic risk engines."""

from __future__ import annotations

import pytest

from src.trading.models import (
    ExecutionMode,
    OrderSide,
    PortfolioSnapshot,
    Position,
    RiskAction,
    RiskConstraints,
)
from src.trading.risk import (
    DailyLossGuard,
    OptionsRiskFilter,
    PositionSizer,
    StopLossEngine,
    TakeProfitEngine,
    TrailingStopEngine,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _long(symbol: str = "AAPL", qty: int = 10, avg_cost: float = 100.0) -> Position:
    return Position(symbol=symbol, qty=qty, avg_cost=avg_cost, current_price=avg_cost)


def _short(symbol: str = "AAPL", qty: int = -10, avg_cost: float = 100.0) -> Position:
    return Position(symbol=symbol, qty=qty, avg_cost=avg_cost, current_price=avg_cost)


def _snap(cash: float = 100_000.0) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="test",
        execution_mode=ExecutionMode.PAPER,
        cash=cash,
        positions={},
        realized_pnl=0.0,
    )


# ── StopLossEngine ────────────────────────────────────────────────────────────


class TestStopLossEngine:
    def test_long_triggers_below_stop(self, constraints: RiskConstraints) -> None:
        engine = StopLossEngine(constraints)
        pos = _long(avg_cost=100.0)
        # 5% stop → stop at $95; current $94 → trigger
        trigger = engine.check(pos, 94.0)
        assert trigger is not None
        assert trigger.action == RiskAction.STOP_LOSS
        assert trigger.trigger_price == pytest.approx(95.0)

    def test_long_no_trigger_above_stop(self, constraints: RiskConstraints) -> None:
        engine = StopLossEngine(constraints)
        pos = _long(avg_cost=100.0)
        assert engine.check(pos, 96.0) is None

    def test_long_triggers_at_exact_stop(self, constraints: RiskConstraints) -> None:
        engine = StopLossEngine(constraints)
        pos = _long(avg_cost=100.0)
        # At exactly $95.00 the condition current_price <= stop_price is True — must trigger.
        # Hard stops are inclusive: touching the stop price executes the exit.
        assert engine.check(pos, 95.0) is not None

    def test_short_triggers_above_stop(self, constraints: RiskConstraints) -> None:
        engine = StopLossEngine(constraints)
        pos = _short(avg_cost=100.0)
        # 5% stop → stop at $105; current $106 → trigger
        trigger = engine.check(pos, 106.0)
        assert trigger is not None
        assert trigger.action == RiskAction.STOP_LOSS

    def test_zero_pct_disabled(self) -> None:
        c = RiskConstraints(execution_mode=ExecutionMode.PAPER, stop_loss_pct=0.0)
        engine = StopLossEngine(c)
        pos = _long(avg_cost=100.0)
        assert engine.check(pos, 0.01) is None  # price near zero, but stop disabled

    def test_override_pct(self, constraints: RiskConstraints) -> None:
        engine = StopLossEngine(constraints)
        pos = _long(avg_cost=100.0)
        # Default is 5% → $95 stop; override with 2% → $98 stop
        assert engine.check(pos, 97.0, override_pct=0.02) is not None
        assert engine.check(pos, 97.0, override_pct=0.05) is None


# ── TakeProfitEngine ──────────────────────────────────────────────────────────


class TestTakeProfitEngine:
    def test_long_triggers_at_target(self, constraints: RiskConstraints) -> None:
        engine = TakeProfitEngine(constraints)
        pos = _long(avg_cost=100.0)
        # 10% target → $110; current $111 → trigger
        trigger = engine.check(pos, 111.0)
        assert trigger is not None
        assert trigger.action == RiskAction.TAKE_PROFIT
        assert trigger.trigger_price == pytest.approx(110.0)

    def test_long_no_trigger_below_target(self, constraints: RiskConstraints) -> None:
        engine = TakeProfitEngine(constraints)
        pos = _long(avg_cost=100.0)
        assert engine.check(pos, 109.0) is None

    def test_short_triggers_below_target(self, constraints: RiskConstraints) -> None:
        engine = TakeProfitEngine(constraints)
        pos = _short(avg_cost=100.0)
        # 10% target → $90; current $89 → trigger
        trigger = engine.check(pos, 89.0)
        assert trigger is not None
        assert trigger.action == RiskAction.TAKE_PROFIT

    def test_zero_pct_disabled(self) -> None:
        c = RiskConstraints(execution_mode=ExecutionMode.PAPER, take_profit_pct=0.0)
        engine = TakeProfitEngine(c)
        pos = _long(avg_cost=100.0)
        assert engine.check(pos, 200.0) is None


# ── TrailingStopEngine ────────────────────────────────────────────────────────


class TestTrailingStopEngine:
    def test_long_ratchets_high_water_mark(self, constraints: RiskConstraints) -> None:
        engine = TrailingStopEngine(constraints)
        pos = _long(avg_cost=100.0)
        # First call — sets high-water at 105
        assert engine.update_and_check(pos, 105.0) is None
        # Price drops but not below trail (3% from 105 = 101.85)
        assert engine.update_and_check(pos, 103.0) is None
        # Price rises to 110 — ratchets high-water
        assert engine.update_and_check(pos, 110.0) is None
        # Trail is now 3% from 110 = 106.70; current 106.0 → trigger
        trigger = engine.update_and_check(pos, 106.0)
        assert trigger is not None
        assert trigger.action == RiskAction.TRAILING_STOP

    def test_first_call_never_triggers(self, constraints: RiskConstraints) -> None:
        engine = TrailingStopEngine(constraints)
        pos = _long(avg_cost=100.0)
        # Even at price 0, first call should not trigger — state is just initialised
        assert engine.update_and_check(pos, 0.01) is None

    def test_state_cleared_on_trigger(self, constraints: RiskConstraints) -> None:
        engine = TrailingStopEngine(constraints)
        pos = _long(avg_cost=100.0)
        engine.update_and_check(pos, 110.0)
        # Trigger the stop
        trigger = engine.update_and_check(pos, 106.0)
        assert trigger is not None
        # After trigger, state is cleared; next call re-initialises
        assert engine.update_and_check(pos, 90.0) is None

    def test_remove_clears_state(self, constraints: RiskConstraints) -> None:
        engine = TrailingStopEngine(constraints)
        pos = _long(avg_cost=100.0)
        engine.update_and_check(pos, 110.0)
        engine.remove("AAPL")
        # State gone — re-initialises on next call
        assert engine.update_and_check(pos, 90.0) is None


# ── PositionSizer ─────────────────────────────────────────────────────────────


class TestPositionSizer:
    def test_returns_positive_integer(self, constraints: RiskConstraints) -> None:
        sizer = PositionSizer(constraints)
        snap = _snap(cash=100_000.0)
        qty = sizer.calculate(snap, "AAPL", 150.0)
        assert isinstance(qty, int)
        assert qty >= 0

    def test_zero_price_returns_zero(self, constraints: RiskConstraints) -> None:
        sizer = PositionSizer(constraints)
        snap = _snap()
        assert sizer.calculate(snap, "AAPL", 0.0) == 0

    def test_zero_equity_returns_zero(self, constraints: RiskConstraints) -> None:
        sizer = PositionSizer(constraints)
        snap = _snap(cash=0.0)
        assert sizer.calculate(snap, "AAPL", 100.0) == 0

    def test_cash_capped(self, constraints: RiskConstraints) -> None:
        sizer = PositionSizer(constraints)
        snap = _snap(cash=500.0)  # only $500 available
        qty = sizer.calculate(snap, "AAPL", 100.0)
        assert qty <= 5  # can't buy more than 5 shares with $500

    def test_never_exceeds_max_position_pct(self, constraints: RiskConstraints) -> None:
        sizer = PositionSizer(constraints)
        snap = _snap(cash=100_000.0)
        qty = sizer.calculate(snap, "AAPL", 100.0)
        # max_position_pct = 20%, equity = $100k → max $20k = 200 shares at $100
        assert qty <= 200


# ── DailyLossGuard ────────────────────────────────────────────────────────────


class TestDailyLossGuard:
    def test_no_halt_within_limit(self, constraints: RiskConstraints) -> None:
        guard = DailyLossGuard(constraints, starting_equity=100_000.0)
        # 5% limit → $5,000 max loss; loss of $4,999 is fine
        assert guard.check(-4_999.0) is False

    def test_halts_beyond_limit(self, constraints: RiskConstraints) -> None:
        guard = DailyLossGuard(constraints, starting_equity=100_000.0)
        # 5% limit → $5,000 max loss; loss of $5,001 triggers halt
        assert guard.check(-5_001.0) is True

    def test_stays_halted_after_trigger(self, constraints: RiskConstraints) -> None:
        guard = DailyLossGuard(constraints, starting_equity=100_000.0)
        guard.check(-5_001.0)
        assert guard.is_halted
        # Even if PnL recovers, halt is sticky
        assert guard.check(0.0) is True

    def test_reset_clears_halt(self, constraints: RiskConstraints) -> None:
        guard = DailyLossGuard(constraints, starting_equity=100_000.0)
        guard.check(-5_001.0)
        guard.reset(new_starting_equity=100_000.0)
        assert not guard.is_halted
        assert guard.check(-4_999.0) is False

    def test_exact_limit_does_not_halt(self, constraints: RiskConstraints) -> None:
        guard = DailyLossGuard(constraints, starting_equity=100_000.0)
        # Exactly at the limit (pnl == -max_loss) should not halt
        assert guard.check(-5_000.0) is False

    def test_scales_with_starting_equity(self, constraints: RiskConstraints) -> None:
        guard = DailyLossGuard(constraints, starting_equity=10_000.0)
        # 5% of $10k = $500 limit
        assert guard.check(-499.0) is False
        assert guard.check(-501.0) is True
