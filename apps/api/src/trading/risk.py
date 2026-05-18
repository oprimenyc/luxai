"""
Deterministic risk engine — stop-loss, take-profit, trailing stop, position sizing.

CRITICAL DESIGN PRINCIPLE:
    All exit logic and position sizing in this module is deterministic Python.
    No language model ever reads from or writes to this module.
    No external I/O occurs during risk evaluation.
    Risk triggers are computed synchronously, in microseconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from src.trading.models import (
    ExecutionMode,
    OrderSide,
    PortfolioSnapshot,
    Position,
    RiskAction,
    RiskConstraints,
    RiskTrigger,
)

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Stop-Loss Engine
# ══════════════════════════════════════════════════════════════════════════════


class StopLossEngine:
    """
    Hard stop-loss — fires when loss exceeds `stop_loss_pct` of cost basis.

    Supports:
    - Percentage stop (default)
    - Absolute dollar stop (per-position override)

    LLM cannot modify, disable, or bypass this engine.
    """

    def __init__(self, constraints: RiskConstraints) -> None:
        self._pct = constraints.stop_loss_pct

    def check(
        self,
        position: Position,
        current_price: float,
        override_pct: float | None = None,
    ) -> RiskTrigger | None:
        """
        Return a RiskTrigger if stop-loss is breached, else None.
        Must be called after each price update for every open position.
        """
        pct = override_pct if override_pct is not None else self._pct
        if pct <= 0:
            return None

        if position.qty > 0:  # long
            stop_price = position.avg_cost * (1 - pct)
            triggered = current_price <= stop_price
        else:  # short
            stop_price = position.avg_cost * (1 + pct)
            triggered = current_price >= stop_price

        if triggered:
            trigger = RiskTrigger(
                symbol=position.symbol,
                action=RiskAction.STOP_LOSS,
                reason=f"Stop-loss triggered: {pct:.1%} threshold",
                entry_price=position.avg_cost,
                trigger_price=stop_price,
                current_price=current_price,
            )
            log.warning(
                "stop_loss_triggered",
                symbol=position.symbol,
                entry=position.avg_cost,
                stop=stop_price,
                current=current_price,
            )
            return trigger

        return None


# ══════════════════════════════════════════════════════════════════════════════
# Take-Profit Engine
# ══════════════════════════════════════════════════════════════════════════════


class TakeProfitEngine:
    """
    Hard take-profit — fires when gain exceeds `take_profit_pct` of cost basis.

    LLM cannot modify, disable, or bypass this engine.
    """

    def __init__(self, constraints: RiskConstraints) -> None:
        self._pct = constraints.take_profit_pct

    def check(
        self,
        position: Position,
        current_price: float,
        override_pct: float | None = None,
    ) -> RiskTrigger | None:
        pct = override_pct if override_pct is not None else self._pct
        if pct <= 0:
            return None

        if position.qty > 0:  # long
            target_price = position.avg_cost * (1 + pct)
            triggered = current_price >= target_price
        else:  # short
            target_price = position.avg_cost * (1 - pct)
            triggered = current_price <= target_price

        if triggered:
            trigger = RiskTrigger(
                symbol=position.symbol,
                action=RiskAction.TAKE_PROFIT,
                reason=f"Take-profit triggered: {pct:.1%} target",
                entry_price=position.avg_cost,
                trigger_price=target_price,
                current_price=current_price,
            )
            log.info(
                "take_profit_triggered",
                symbol=position.symbol,
                entry=position.avg_cost,
                target=target_price,
                current=current_price,
            )
            return trigger

        return None


# ══════════════════════════════════════════════════════════════════════════════
# Trailing Stop Engine
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class _TrailingState:
    symbol: str
    highest_price: float    # long: highest seen; short: lowest seen
    trail_pct: float
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TrailingStopEngine:
    """
    Deterministic trailing stop — ratchets the stop price as the position moves in-favour.

    - For long positions: stop = highest_seen * (1 - trail_pct)
    - For short positions: stop = lowest_seen * (1 + trail_pct)

    LLM cannot modify, disable, or bypass this engine.
    """

    def __init__(self, constraints: RiskConstraints) -> None:
        self._trail_pct = constraints.trailing_stop_pct
        self._states: dict[str, _TrailingState] = {}

    def update_and_check(
        self,
        position: Position,
        current_price: float,
    ) -> RiskTrigger | None:
        """
        Update trailing state and return a RiskTrigger if the stop is breached, else None.
        Must be called on every price tick for each tracked position.
        """
        symbol = position.symbol
        state = self._states.get(symbol)

        if state is None:
            # Initialise trailing state on first call
            state = _TrailingState(
                symbol=symbol,
                highest_price=current_price,
                trail_pct=self._trail_pct,
            )
            self._states[symbol] = state
            return None

        if position.qty > 0:  # long
            # Ratchet high-water mark upward
            if current_price > state.highest_price:
                state.highest_price = current_price
                state.updated_at = datetime.now(UTC)

            stop_price = state.highest_price * (1 - state.trail_pct)
            triggered = current_price <= stop_price

        else:  # short
            # Ratchet low-water mark downward
            if current_price < state.highest_price:
                state.highest_price = current_price
                state.updated_at = datetime.now(UTC)

            stop_price = state.highest_price * (1 + state.trail_pct)
            triggered = current_price >= stop_price

        if triggered:
            del self._states[symbol]  # reset state on trigger
            trigger = RiskTrigger(
                symbol=symbol,
                action=RiskAction.TRAILING_STOP,
                reason=f"Trailing stop triggered: {state.trail_pct:.1%} from peak {state.highest_price:.4f}",
                entry_price=position.avg_cost,
                trigger_price=stop_price,
                current_price=current_price,
            )
            log.warning(
                "trailing_stop_triggered",
                symbol=symbol,
                peak=state.highest_price,
                stop=stop_price,
                current=current_price,
            )
            return trigger

        return None

    def remove(self, symbol: str) -> None:
        """Remove trailing state when a position is closed."""
        self._states.pop(symbol, None)

    def get_stop_price(self, symbol: str) -> float | None:
        state = self._states.get(symbol)
        if state is None:
            return None
        return state.highest_price * (1 - state.trail_pct)


# ══════════════════════════════════════════════════════════════════════════════
# Position Sizer
# ══════════════════════════════════════════════════════════════════════════════


class PositionSizer:
    """
    Deterministic position sizing — risk-based (fixed fractional).

    Limits:
    - Never sizes above max_position_pct of portfolio equity
    - Never risks more than max_portfolio_risk_pct on a single trade
    - Always returns integer share counts (floor)

    LLM cannot influence sizing — inputs come from portfolio state only.
    """

    def __init__(self, constraints: RiskConstraints) -> None:
        self._max_pos_pct = constraints.max_position_pct
        self._risk_pct = constraints.max_portfolio_risk_pct
        self._stop_pct = constraints.stop_loss_pct

    def calculate(
        self,
        portfolio: PortfolioSnapshot,
        symbol: str,
        price: float,
        override_risk_pct: float | None = None,
    ) -> int:
        """
        Return the number of shares to buy/sell.

        Uses fixed-fractional risk sizing:
            risk_amount = equity * risk_pct
            risk_per_share = price * stop_pct
            raw_shares = risk_amount / risk_per_share

        Also caps at max_position_pct of equity.
        Returns 0 if price is 0 or constraints prevent any sizing.
        """
        if price <= 0:
            return 0

        equity = portfolio.equity
        if equity <= 0:
            return 0

        risk_pct = override_risk_pct if override_risk_pct is not None else self._risk_pct
        stop_pct = self._stop_pct

        risk_amount = equity * risk_pct
        risk_per_share = price * stop_pct if stop_pct > 0 else price * 0.01
        risk_based_shares = math.floor(risk_amount / risk_per_share)

        max_position_value = equity * self._max_pos_pct
        position_capped_shares = math.floor(max_position_value / price)

        # Never exceed available cash
        cash_capped_shares = math.floor(portfolio.cash / price)

        shares = min(risk_based_shares, position_capped_shares, cash_capped_shares)
        shares = max(0, shares)

        log.debug(
            "position_sized",
            symbol=symbol,
            equity=round(equity, 2),
            risk_based=risk_based_shares,
            position_capped=position_capped_shares,
            cash_capped=cash_capped_shares,
            final=shares,
        )
        return shares


# ══════════════════════════════════════════════════════════════════════════════
# Daily Loss Guard
# ══════════════════════════════════════════════════════════════════════════════


class DailyLossGuard:
    """
    Circuit-breaker: halt trading if daily realized loss exceeds threshold.

    LLM cannot disable or modify this guard.
    """

    def __init__(self, constraints: RiskConstraints, starting_equity: float) -> None:
        self._max_loss_pct = constraints.max_daily_loss_pct
        self._starting_equity = starting_equity
        self._halted = False

    def check(self, current_realized_pnl: float) -> bool:
        """Return True if trading should be halted."""
        if self._halted:
            return True
        max_loss = self._starting_equity * self._max_loss_pct
        if current_realized_pnl < -max_loss:
            self._halted = True
            log.critical(
                "daily_loss_guard_triggered",
                realized_pnl=current_realized_pnl,
                max_loss=-max_loss,
            )
            return True
        return False

    def reset(self, new_starting_equity: float) -> None:
        """Reset at start of trading day."""
        self._starting_equity = new_starting_equity
        self._halted = False

    @property
    def is_halted(self) -> bool:
        return self._halted


# ══════════════════════════════════════════════════════════════════════════════
# Options Risk Filters
# ══════════════════════════════════════════════════════════════════════════════


class OptionsRiskFilter:
    """
    Pre-trade options risk filters — deterministic, no LLM involvement.

    Checks:
    - Minimum liquidity (bid/ask spread and open interest)
    - IV regime filter
    - DTE range filter
    - Delta range filter
    """

    def __init__(
        self,
        min_open_interest: int = 100,
        max_spread_pct: float = 0.10,
        min_dte: int = 1,
        max_dte: int = 60,
        min_delta: float = 0.10,
        max_delta: float = 0.90,
        max_iv: float = 3.0,  # 300% IV cap
    ) -> None:
        self.min_open_interest = min_open_interest
        self.max_spread_pct = max_spread_pct
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.min_delta = min_delta
        self.max_delta = max_delta
        self.max_iv = max_iv

    def passes(self, contract: Any) -> tuple[bool, str]:
        """Return (passes, reason_if_rejected)."""
        from src.trading.models import OptionContract

        if not isinstance(contract, OptionContract):
            return False, "not an OptionContract"

        if contract.open_interest < self.min_open_interest:
            return False, f"low open_interest {contract.open_interest} < {self.min_open_interest}"

        if contract.mid > 0 and contract.spread_pct > self.max_spread_pct:
            return False, f"wide spread {contract.spread_pct:.1%} > {self.max_spread_pct:.1%}"

        if not (self.min_dte <= contract.dte <= self.max_dte):
            return False, f"DTE {contract.dte} outside [{self.min_dte}, {self.max_dte}]"

        if contract.greeks.delta is not None:
            abs_delta = abs(contract.greeks.delta)
            if not (self.min_delta <= abs_delta <= self.max_delta):
                return False, f"delta {abs_delta:.2f} outside [{self.min_delta}, {self.max_delta}]"

        if contract.greeks.iv is not None and contract.greeks.iv > self.max_iv:
            return False, f"IV {contract.greeks.iv:.1%} > {self.max_iv:.1%}"

        return True, ""
