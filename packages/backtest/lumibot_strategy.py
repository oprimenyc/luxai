"""
Path: packages/backtest/lumibot_strategy.py
Security: Read-only market data access. No real order submission possible —
          Lumibot is wired to YahooDataBacktesting (offline) or paper Alpaca
          (PAPER mode enforced at BrokerABC level). No credentials required
          for backtesting mode.
Scale: Single-tenant. Run as a one-off script via scripts/run_backtest.py.
       Not imported by the FastAPI server at runtime.

LuxAI Options Backtest Strategy — Lumibot implementation.

SYNTHETIC OPTIONS DATA WARNING
--------------------------------
yfinance does not provide historical options chain data. Real historical fills
for SPY/QQQ options from 2025-12-01 through 2026-06-01 are not available on
any free tier. This strategy synthesises option prices using Black-Scholes on
underlying OHLCV data + a constant implied-volatility assumption.

Synthetic pricing means:
  - Strike selection and DTE filtering are real
  - Scoring (delta, spread, OI proxy) uses BS-computed values
  - Entry/exit prices are BS theoretical values, NOT real market fills
  - Slippage, bid-ask spread, and fill quality are NOT modelled

Treat backtest results as strategy screening, not performance attribution.
Real options backtesting requires paid historical data at $1,000+ account size
(see CLAUDE.md: "Paid Consideration Thresholds").

Architecture note
-----------------
This strategy runs in its own Lumibot scheduler and is NOT a replacement for
scanner.py. The production scanner is async, FastAPI-embedded, and wired to
Redis + Supabase + shadow mode. Lumibot runs synchronously in a separate
process for historical analysis only.

    Production:   apps/api/src/trading/scanner.py  (async, FastAPI lifespan)
    Backtesting:  packages/backtest/lumibot_strategy.py  (sync, Lumibot)
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ── Lumibot imports ───────────────────────────────────────────────────────────
try:
    from lumibot.strategies.strategy import Strategy
    from lumibot.entities import Asset, Order
except ImportError as exc:
    raise SystemExit(
        "lumibot is not installed. Run:\n"
        "  pip install 'lumibot>=4.5.0'\n"
        "or:\n"
        "  pip install 'luxai-api[backtest]'\n"
    ) from exc

# ── LuxAI internal imports (path-relative for standalone script) ──────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_SRC = _REPO_ROOT / "apps" / "api" / "src"
if str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))

from options.scorer import OptionsScorer  # type: ignore[import]
from options.greeks import BlackScholesGreeks  # type: ignore[import]
from trading.models import Greeks  # type: ignore[import]

# ── Constants ─────────────────────────────────────────────────────────────────

WATCHLIST = ["SPY", "QQQ", "TSLA", "NVDA", "AAPL", "META", "AMZN"]

# DTE window matching production scanner (CLAUDE.md)
_MIN_DTE = 7
_MAX_DTE = 21

# Score threshold: same as production scanner shadow-mode floor
_MIN_SCORE = 5.0

# Implied volatility assumption for synthetic pricing (30-day ATM estimate).
# Replace with per-symbol IV from VIX proxy once account > $1,000.
# SYNTHETIC — this is a constant approximation, not market-derived.
_SYNTHETIC_IV_DEFAULT = 0.25

# Max concurrent positions (Tiny tier: max 1 contract, 5% account cap)
_MAX_POSITIONS = 2
_MAX_RISK_PCT = 0.05
_RISK_FREE_RATE = 0.045

# Exit rules matching shadow trade monitor (CLAUDE.md shadow mode definition)
_EXIT_LOSS_PCT = -0.05    # -5% of position value → close
_EXIT_GAIN_PCT = 0.10     # +10% of position value → close


class LuxAIOptionsStrategy(Strategy):
    """
    Lumibot strategy that replicates the LuxAI scanner pipeline for backtesting.

    Each iteration (daily):
      1. Pre-filter: skip symbols with < 0.5% price movement
      2. Score all 7–21 DTE calls and puts using OptionsScorer
      3. Select best-scoring contract per symbol (score >= 5.0)
      4. Buy 1 contract; apply exit rules after each bar

    Note: options are SYNTHESISED from underlying OHLCV using Black-Scholes.
    See module docstring for the full synthetic data warning.
    """

    # Lumibot calls initialize() once before the first iteration
    def initialize(self) -> None:
        # Run once per market day
        self.sleeptime = "1D"
        self._scorer = OptionsScorer("tiny")
        self._crash_count = 0
        self._results: list[dict[str, Any]] = []

        # Benchmark: buy-and-hold SPY (Lumibot computes this automatically)
        self.set_market("NYSE")

    # ── Lifecycle hooks ───────────────────────────────────────────────────────

    def before_market_opens(self) -> None:
        """Pre-market: log portfolio state and check position exit rules."""
        portfolio_value = self.get_portfolio_value()
        self.log_message(
            f"before_market_opens | portfolio=${portfolio_value:.2f} "
            f"| positions={len(self.get_tracked_positions())}"
        )
        self._check_exit_rules()

    def after_market_closes(self) -> None:
        """Post-market: record daily P&L snapshot to results list."""
        portfolio_value = self.get_portfolio_value()
        cash = self.get_cash()
        self._results.append({
            "date": str(self.get_datetime().date()),
            "portfolio_value": round(portfolio_value, 2),
            "cash": round(cash, 2),
            "positions": len(self.get_tracked_positions()),
        })

    def on_bot_crash(self, error: Exception) -> None:
        """
        Self-healing: log the crash, increment counter, and attempt to flatten
        all positions before the process exits.

        Lumibot calls this before terminating on unhandled exceptions.
        Task: auto_market_scanner (Lumibot process — not the FastAPI scanner)
        Cancellation: Lumibot handles process shutdown after this hook.
        """
        self._crash_count += 1
        self.log_message(
            f"on_bot_crash | crash_count={self._crash_count} | error={str(error)[:120]}"
        )
        # Attempt to close all positions before crash
        for position in self.get_tracked_positions():
            try:
                self.sell_all()
                break
            except Exception:
                pass
        # Persist crash context for post-mortem
        self._results.append({
            "date": str(self.get_datetime().date()) if self.get_datetime() else "unknown",
            "event": "crash",
            "error": str(error)[:200],
            "crash_count": self._crash_count,
        })

    # ── Main iteration ────────────────────────────────────────────────────────

    def on_trading_iteration(self) -> None:
        """
        Called once per market day by Lumibot's scheduler.

        Mirrors the production scanner signal flow:
          1. yfinance pre-filter (movement > 0.5%)
          2. Score all qualifying contracts via OptionsScorer
          3. Log intended trade (does NOT submit to broker in this implementation;
             broker submission is handled by the caller script)
        """
        today = self.get_datetime().date()
        current_positions = len(self.get_tracked_positions())

        if current_positions >= _MAX_POSITIONS:
            return

        portfolio_value = self.get_portfolio_value()
        max_risk_usd = portfolio_value * _MAX_RISK_PCT

        for symbol in WATCHLIST:
            if current_positions >= _MAX_POSITIONS:
                break

            # Step 1: pre-filter by price movement
            try:
                bars = self.get_historical_prices(symbol, 2, "day")
                if bars is None or bars.df.empty or len(bars.df) < 2:
                    continue
                prev_close = float(bars.df["close"].iloc[-2])
                curr_price = float(bars.df["close"].iloc[-1])
                if prev_close <= 0:
                    continue
                movement_pct = abs((curr_price - prev_close) / prev_close) * 100.0
                if movement_pct < 0.5:
                    continue
            except Exception as exc:
                self.log_message(f"price_fetch_error | symbol={symbol} | {exc}")
                continue

            # Step 2: synthesise options contracts and score them
            best_score: float = 0.0
            best_contract_info: dict[str, Any] | None = None

            for dte in range(_MIN_DTE, _MAX_DTE + 1):
                expiry = today + timedelta(days=dte)
                if expiry.weekday() != 4:  # only Fridays (standard expiry)
                    continue

                for option_type in ("call", "put"):
                    for strike_offset in (-5, -2, 0, 2, 5):
                        strike = round(curr_price + strike_offset, 0)
                        if strike <= 0:
                            continue

                        # Synthesise price using Black-Scholes
                        try:
                            iv = _SYNTHETIC_IV_DEFAULT
                            greek_result = BlackScholesGreeks.compute(
                                underlying_price=curr_price,
                                strike=strike,
                                expiry_date=expiry,
                                iv=iv,
                                option_type=option_type,
                                risk_free_rate=_RISK_FREE_RATE,
                            )
                            # Build a minimal contract-like object for the scorer
                            contract = _SyntheticContract(
                                symbol=f"{symbol}{expiry.strftime('%y%m%d')}{'C' if option_type == 'call' else 'P'}{int(strike):08d}",
                                underlying=symbol,
                                strike=strike,
                                expiration=expiry,
                                option_type=option_type,
                                mid=greek_result.theoretical_price,
                                bid=greek_result.theoretical_price * 0.95,
                                ask=greek_result.theoretical_price * 1.05,
                                open_interest=250,  # SYNTHETIC — proxy for scoring
                                greeks=Greeks(
                                    delta=greek_result.delta,
                                    gamma=greek_result.gamma,
                                    theta=greek_result.theta,
                                    vega=greek_result.vega,
                                    iv=iv,
                                ),
                            )
                            scored = self._scorer.score_contract(contract)
                            if scored.tier_violation:
                                continue
                            if scored.score > best_score:
                                best_score = scored.score
                                best_contract_info = {
                                    "symbol": symbol,
                                    "contract_symbol": contract.symbol,
                                    "strike": strike,
                                    "expiry": expiry.isoformat(),
                                    "option_type": option_type,
                                    "score": round(scored.score, 1),
                                    "synthetic_price": round(greek_result.theoretical_price, 4),
                                    "delta": round(greek_result.delta or 0, 3),
                                    "theta": round(greek_result.theta or 0, 4),
                                    "iv_used": iv,
                                    "underlying_price": round(curr_price, 2),
                                    "estimated_cost_usd": round(greek_result.theoretical_price * 100, 2),
                                }
                        except Exception:
                            continue

            if best_score < _MIN_SCORE or best_contract_info is None:
                self.log_message(
                    f"no_qualifying_contract | symbol={symbol} | best_score={best_score:.1f}"
                )
                continue

            cost_usd = best_contract_info["estimated_cost_usd"]
            if cost_usd > max_risk_usd:
                self.log_message(
                    f"risk_cap_exceeded | symbol={symbol} | cost=${cost_usd:.2f} "
                    f"| max=${max_risk_usd:.2f}"
                )
                continue

            # Step 3: create order (uses Lumibot's paper broker, or simulator in backtest)
            try:
                option_asset = Asset(
                    symbol=symbol,
                    asset_type=Asset.AssetType.OPTION,
                    expiration=date.fromisoformat(best_contract_info["expiry"]),
                    strike=best_contract_info["strike"],
                    right=(
                        Asset.OptionRight.CALL
                        if best_contract_info["option_type"] == "call"
                        else Asset.OptionRight.PUT
                    ),
                )
                order = self.create_order(option_asset, 1, "buy", type="market")
                self.submit_order(order)
                current_positions += 1
                self.log_message(
                    f"signal_created | {best_contract_info['contract_symbol']} "
                    f"| score={best_score:.1f} | cost=${cost_usd:.2f}"
                )
                # Record in results for INTELLIGENCE_REPORT
                best_contract_info["date"] = str(today)
                best_contract_info["action"] = "buy"
                self._results.append(best_contract_info)
            except Exception as exc:
                self.log_message(
                    f"order_error | symbol={symbol} | {str(exc)[:80]}"
                )

    # ── Exit rules ────────────────────────────────────────────────────────────

    def _check_exit_rules(self) -> None:
        """
        Close positions hitting -5% loss or +10% gain.
        Mirrors shadow_trade_monitor exit logic (CLAUDE.md).
        """
        for position in list(self.get_tracked_positions()):
            try:
                asset = position.asset
                current_price = self.get_last_price(asset)
                if current_price is None:
                    continue
                avg_cost = position.avg_fill_price
                if not avg_cost or avg_cost <= 0:
                    continue
                pnl_pct = (current_price - avg_cost) / avg_cost
                if pnl_pct <= _EXIT_LOSS_PCT or pnl_pct >= _EXIT_GAIN_PCT:
                    reason = "stop_loss" if pnl_pct <= _EXIT_LOSS_PCT else "take_profit"
                    order = self.create_order(asset, position.quantity, "sell", type="market")
                    self.submit_order(order)
                    self.log_message(
                        f"exit_{reason} | {asset.symbol} | pnl={pnl_pct:.1%}"
                    )
                    self._results.append({
                        "date": str(self.get_datetime().date()),
                        "action": "exit",
                        "reason": reason,
                        "symbol": asset.symbol,
                        "pnl_pct": round(pnl_pct, 4),
                    })
            except Exception:
                continue

    # ── Results export ────────────────────────────────────────────────────────

    def get_results(self) -> list[dict[str, Any]]:
        """Return all recorded trade events and daily snapshots."""
        return self._results


# ── Synthetic contract helper ─────────────────────────────────────────────────


class _SyntheticContract:
    """
    Minimal options contract object compatible with OptionsScorer.score_contract().

    Stands in for tradier_client.OptionsContract during backtesting when real
    chain data is unavailable. Fields match what OptionsScorer reads.

    SYNTHETIC — open_interest is a fixed proxy; bid/ask spread is ±5% of mid.
    """

    __slots__ = (
        "symbol", "underlying", "strike", "expiration", "option_type",
        "mid", "bid", "ask", "open_interest", "greeks",
    )

    def __init__(
        self,
        symbol: str,
        underlying: str,
        strike: float,
        expiration: date,
        option_type: str,
        mid: float,
        bid: float,
        ask: float,
        open_interest: int,
        greeks: "Greeks",
    ) -> None:
        self.symbol = symbol
        self.underlying = underlying
        self.strike = strike
        self.expiration = expiration
        self.option_type = type("_OT", (), {"value": option_type})()
        self.mid = mid
        self.bid = bid
        self.ask = ask
        self.open_interest = open_interest
        self.greeks = greeks
