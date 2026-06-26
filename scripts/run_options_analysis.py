"""
Path: scripts/run_options_analysis.py
Security: Read-only. Uses yfinance for live underlying prices only.
          No broker credentials. No Supabase writes.
Scale: One-off analysis script. Not part of the FastAPI server.

DTE / Delta win-rate sweep — Options parameter optimisation.

What this does:
  For each (DTE bucket, delta bucket) combination, simulate buying 1 contract
  at the Black-Scholes theoretical price and apply the shadow-mode exit rules
  (-5% loss / +10% gain). Report win rate, avg hold days, avg P&L.

NOTE ON OPTOPSY
---------------
optopsy (https://github.com/michaelchu/optopsy) v2.x requires historical
options chain CSV files in a specific format (CBOE bulk-data or Think or Swim
export). It does NOT work with yfinance live data, and its last PyPI release
(2.0.0b6, 2021) targets Python 3.6 and pandas 0.23 — incompatible with our
Python 3.11+ stack.

This script implements the same DTE/delta sweep logic that optopsy would run,
but using our own Black-Scholes engine on yfinance OHLCV history.
At $1,000+ account size, replace _fetch_ohlcv() with a real CBOE data feed
and the synthetic IV with market-derived IV from Tradier.

Usage:
    python scripts/run_options_analysis.py
    python scripts/run_options_analysis.py --symbol SPY --output results/dte_delta.json
    python scripts/run_options_analysis.py --all --period 6mo
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api" / "src"))

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("yfinance not installed. Run: pip install yfinance")

from options.greeks import BlackScholesGreeks  # type: ignore[import]

# ── Analysis parameters ───────────────────────────────────────────────────────

WATCHLIST = ["SPY", "QQQ", "TSLA", "NVDA", "AAPL", "META", "AMZN"]

# DTE buckets to test
DTE_BUCKETS = [7, 14, 21]

# Delta buckets to test (target call delta; put delta will mirror)
DELTA_BUCKETS = [0.25, 0.35, 0.45, 0.55]

_SYNTHETIC_IV = 0.25   # SYNTHETIC — constant IV; replace with VIX/Tradier at $1,000+
_RISK_FREE_RATE = 0.045
_EXIT_LOSS_PCT = -0.05
_EXIT_GAIN_PCT = 0.10
_MAX_HOLD_DAYS = 21


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DTE/delta win-rate sweep")
    p.add_argument("--symbol", default=None, help="Single symbol (default: full watchlist)")
    p.add_argument("--all", action="store_true", help="Run full watchlist")
    p.add_argument("--period", default="6mo", help="yfinance period string (e.g. 6mo, 1y)")
    p.add_argument(
        "--output",
        default="backtest_results/dte_delta_analysis.json",
        help="Output JSON path",
    )
    return p.parse_args()


def _fetch_ohlcv(symbol: str, period: str) -> list[dict[str, Any]]:
    """Fetch daily OHLCV bars from yfinance."""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period, interval="1d")
    if hist.empty:
        return []
    rows = []
    for ts, row in hist.iterrows():
        rows.append({
            "date": ts.date(),
            "open": float(row["Open"]),
            "close": float(row["Close"]),
        })
    return rows


def _simulate_trade(
    entry_date: date,
    entry_price: float,
    bars: list[dict[str, Any]],
    target_dte: int,
    target_delta: float,
    option_type: str,
    symbol: str,
) -> dict[str, Any] | None:
    """
    Simulate entering a 1-contract position at entry_date and applying exit rules.

    Returns a trade result dict, or None if no strike could be found.
    """
    expiry = entry_date + timedelta(days=target_dte)

    # Find the strike that yields closest delta to target
    best_strike: float | None = None
    best_delta_diff = float("inf")

    for offset in range(-20, 21):
        strike = round(entry_price + offset, 0)
        if strike <= 0:
            continue
        try:
            result = BlackScholesGreeks.compute(
                underlying_price=entry_price,
                strike=strike,
                expiry_date=expiry,
                iv=_SYNTHETIC_IV,
                option_type=option_type,
                risk_free_rate=_RISK_FREE_RATE,
            )
            delta = abs(result.delta or 0)
            if abs(delta - target_delta) < best_delta_diff:
                best_delta_diff = abs(delta - target_delta)
                best_strike = strike
                best_entry_price = result.theoretical_price
        except Exception:
            continue

    if best_strike is None:
        return None

    # Simulate holding until exit rule or expiry
    for bar in bars:
        if bar["date"] <= entry_date:
            continue
        days_held = (bar["date"] - entry_date).days
        if days_held > _MAX_HOLD_DAYS:
            break

        # Re-price contract at current underlying price and remaining DTE
        remaining_dte = (expiry - bar["date"]).days
        if remaining_dte <= 0:
            # Expired worthless or ITM — compute intrinsic value
            intrinsic = max(0, bar["close"] - best_strike) if option_type == "call" else max(0, best_strike - bar["close"])
            exit_price = intrinsic
            pnl_pct = (exit_price - best_entry_price) / best_entry_price if best_entry_price > 0 else 0.0
            return {
                "symbol": symbol,
                "option_type": option_type,
                "target_dte": target_dte,
                "target_delta": target_delta,
                "strike": best_strike,
                "entry_date": str(entry_date),
                "exit_date": str(bar["date"]),
                "entry_price": round(best_entry_price, 4),
                "exit_price": round(exit_price, 4),
                "pnl_pct": round(pnl_pct, 4),
                "days_held": days_held,
                "exit_reason": "expiry",
                "data_mode": "SYNTHETIC",
            }

        try:
            current_result = BlackScholesGreeks.compute(
                underlying_price=bar["close"],
                strike=best_strike,
                expiry_date=expiry,
                iv=_SYNTHETIC_IV,
                option_type=option_type,
                risk_free_rate=_RISK_FREE_RATE,
            )
            current_price = current_result.theoretical_price
        except Exception:
            continue

        pnl_pct = (current_price - best_entry_price) / best_entry_price if best_entry_price > 0 else 0.0

        if pnl_pct <= _EXIT_LOSS_PCT:
            return {
                "symbol": symbol,
                "option_type": option_type,
                "target_dte": target_dte,
                "target_delta": target_delta,
                "strike": best_strike,
                "entry_date": str(entry_date),
                "exit_date": str(bar["date"]),
                "entry_price": round(best_entry_price, 4),
                "exit_price": round(current_price, 4),
                "pnl_pct": round(pnl_pct, 4),
                "days_held": days_held,
                "exit_reason": "stop_loss",
                "data_mode": "SYNTHETIC",
            }
        if pnl_pct >= _EXIT_GAIN_PCT:
            return {
                "symbol": symbol,
                "option_type": option_type,
                "target_dte": target_dte,
                "target_delta": target_delta,
                "strike": best_strike,
                "entry_date": str(entry_date),
                "exit_date": str(bar["date"]),
                "entry_price": round(best_entry_price, 4),
                "exit_price": round(current_price, 4),
                "pnl_pct": round(pnl_pct, 4),
                "days_held": days_held,
                "exit_reason": "take_profit",
                "data_mode": "SYNTHETIC",
            }

    return None  # Did not hit exit within window


def analyse_symbol(symbol: str, period: str) -> list[dict[str, Any]]:
    """Run the full DTE/delta sweep for one symbol."""
    print(f"  Fetching {symbol} OHLCV ({period})...", end=" ", flush=True)
    bars = _fetch_ohlcv(symbol, period)
    if not bars:
        print("no data")
        return []
    print(f"{len(bars)} bars")

    trades = []
    for dte in DTE_BUCKETS:
        for delta in DELTA_BUCKETS:
            for option_type in ("call", "put"):
                # Simulate entering on every 5th bar (weekly-ish cadence)
                for i in range(0, len(bars), 5):
                    bar = bars[i]
                    trade = _simulate_trade(
                        entry_date=bar["date"],
                        entry_price=bar["close"],
                        bars=bars,
                        target_dte=dte,
                        target_delta=delta,
                        option_type=option_type,
                        symbol=symbol,
                    )
                    if trade:
                        trades.append(trade)
    return trades


def summarise(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate by (symbol, option_type, dte, delta) bucket."""
    from collections import defaultdict

    buckets: dict[tuple, list[float]] = defaultdict(list)
    for t in trades:
        key = (t["symbol"], t["option_type"], t["target_dte"], t["target_delta"])
        buckets[key].append(t["pnl_pct"])

    summary = []
    for (symbol, opt_type, dte, delta), pnls in sorted(buckets.items()):
        winners = [p for p in pnls if p > 0]
        summary.append({
            "symbol": symbol,
            "option_type": opt_type,
            "target_dte": dte,
            "target_delta": delta,
            "trades": len(pnls),
            "win_rate": round(len(winners) / len(pnls), 3) if pnls else 0,
            "avg_pnl_pct": round(sum(pnls) / len(pnls), 4) if pnls else 0,
            "max_loss_pct": round(min(pnls), 4) if pnls else 0,
            "max_gain_pct": round(max(pnls), 4) if pnls else 0,
            "data_mode": "SYNTHETIC_BLACK_SCHOLES",
        })
    return summary


def main() -> None:
    args = parse_args()

    symbols = WATCHLIST if (args.all or args.symbol is None) else [args.symbol]

    print("LuxAI Options DTE/Delta Analysis")
    print(f"  Symbols:  {', '.join(symbols)}")
    print(f"  Period:   {args.period}")
    print(f"  DTE:      {DTE_BUCKETS}")
    print(f"  Delta:    {DELTA_BUCKETS}")
    print(f"  IV used:  {_SYNTHETIC_IV} (SYNTHETIC — constant approximation)")
    print()
    print("  ⚠  Synthetic pricing. Not real options fills.")
    print()

    all_trades: list[dict[str, Any]] = []
    for symbol in symbols:
        trades = analyse_symbol(symbol, args.period)
        all_trades.extend(trades)

    summary = summarise(all_trades)

    # Print top 10 by win rate
    print("\nTop DTE/Delta combos by win rate:")
    print(f"{'Symbol':<6} {'Type':<5} {'DTE':>4} {'Δ':>5} {'Trades':>7} {'Win%':>6} {'AvgP&L':>8}")
    print("-" * 50)
    for row in sorted(summary, key=lambda r: r["win_rate"], reverse=True)[:10]:
        print(
            f"{row['symbol']:<6} {row['option_type']:<5} {row['target_dte']:>4} "
            f"{row['target_delta']:>5.2f} {row['trades']:>7} "
            f"{row['win_rate']:>5.1%} {row['avg_pnl_pct']:>+8.1%}"
        )

    out = {
        "period": args.period,
        "symbols": symbols,
        "dte_buckets": DTE_BUCKETS,
        "delta_buckets": DELTA_BUCKETS,
        "data_mode": "SYNTHETIC_BLACK_SCHOLES",
        "synthetic_iv": _SYNTHETIC_IV,
        "total_simulated_trades": len(all_trades),
        "summary": summary,
        "raw_trades": all_trades,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nFull results written to: {out_path}")
    print("\nNext steps:")
    print("  • At $1,000+ account: re-run with real CBOE or Think or Swim CSV data")
    print("  • Feed winning DTE/delta params back into scanner._MIN_DTE and strike selection")
    print("  • Compare synthetic win rate vs shadow run actual hit rate")


if __name__ == "__main__":
    main()
