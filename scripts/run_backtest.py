"""
Path: scripts/run_backtest.py
Security: Read-only. No broker credentials needed for YahooDataBacktesting.
          Do not pass Alpaca keys here — backtesting uses offline Yahoo data.
Scale: One-off script. Not part of the FastAPI server. Run locally or in CI.

Run the LuxAI options strategy backtest via Lumibot + YahooDataBacktesting.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --start 2025-12-01 --end 2026-06-01
    python scripts/run_backtest.py --cash 100 --output results/backtest.json

SYNTHETIC DATA WARNING
----------------------
yfinance does not provide historical options chain data. Options prices in
this backtest are synthesised from underlying OHLCV + constant IV assumptions
using Black-Scholes. Results are strategy screening indicators, NOT real
performance attribution. See packages/backtest/lumibot_strategy.py for details.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure packages/ is on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "packages"))
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api" / "src"))

try:
    from lumibot.backtesting import YahooDataBacktesting
    from lumibot.traders import Trader
except ImportError as exc:
    raise SystemExit(
        "lumibot is required. Install with:\n"
        "  pip install 'lumibot>=4.5.0'\n"
        "or:\n"
        "  pip install 'apps/api[backtest]'\n"
    ) from exc

from backtest.lumibot_strategy import LuxAIOptionsStrategy


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LuxAI options strategy backtest")
    p.add_argument("--start", default="2025-12-01", help="Backtest start date (YYYY-MM-DD)")
    p.add_argument("--end", default="2026-06-01", help="Backtest end date (YYYY-MM-DD)")
    p.add_argument("--cash", type=float, default=100.0, help="Starting cash (default: $100)")
    p.add_argument(
        "--output",
        default="backtest_results/results.json",
        help="Path to write JSON results",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    start_dt = datetime.strptime(args.start, "%Y-%m-%d")
    end_dt = datetime.strptime(args.end, "%Y-%m-%d")

    print(f"LuxAI Options Backtest")
    print(f"  Period:       {args.start} → {args.end}")
    print(f"  Starting $:   ${args.cash:.2f}")
    print(f"  Mode:         SYNTHETIC (Black-Scholes options pricing)")
    print(f"  Watchlist:    SPY / QQQ / TSLA / NVDA / AAPL / META / AMZN")
    print()
    print("  ⚠  Results use synthetic options prices. Not suitable for")
    print("     production capital allocation decisions.")
    print()

    # Lumibot backtesting configuration
    backtesting_start = start_dt
    backtesting_end = end_dt

    # Run the backtest
    results = LuxAIOptionsStrategy.backtest(
        YahooDataBacktesting,
        backtesting_start,
        backtesting_end,
        benchmark_asset="SPY",
        parameters={},
        budget=args.cash,
        show_plot=False,
        show_tearsheet=False,
        save_tearsheet=False,
        show_indicators=False,
        save_logfile=False,
        quiet_logs=True,
    )

    # Collect strategy-level results
    strategy_results: dict = {}
    if results:
        strategy_results = {
            "period": {"start": args.start, "end": args.end},
            "starting_cash": args.cash,
            "data_mode": "SYNTHETIC_BLACK_SCHOLES",
            "synthetic_iv": 0.25,
            "lumibot_results": results if isinstance(results, dict) else str(results),
        }

    # Write output
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(strategy_results, indent=2, default=str))
    print(f"\nResults written to: {out_path}")
    print("\nNext steps:")
    print("  • Review trade events in results.json")
    print("  • Compare vs SPY benchmark in tearsheet")
    print("  • At $1,000+ account: replace synthetic IV with Tradier IV Rank")
    print("  • At $1,000+ account: replace synthetic OI=250 with real open interest")


if __name__ == "__main__":
    main()
