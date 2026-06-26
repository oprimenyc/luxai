# Intelligence Report — Lumibot + Optopsy Integration Audit

**Generated:** 2026-06-26  
**Author:** Engineering session (post-shadow-run-recovery)  
**Status:** Backtest layer built. Scanner NOT replaced (shadow run active).

---

## 1. Executive Summary

Lumibot adds genuine value as a **backtesting framework** for LuxAI. It does not replace any existing production component. The scanner, broker adapter, and TradingAgents pipeline are all more sophisticated than their Lumibot equivalents for production use.

Optopsy (v2.0.0b6) is incompatible with our Python 3.11+ stack and requires historical options chain CSV files that are only available on paid data tiers. A functionally equivalent DTE/delta sweep has been implemented using our existing Black-Scholes engine.

**Shadow run is not disrupted.** The scanner at `apps/api/src/trading/scanner.py` was not modified.

---

## 2. What Was Built

| Artifact                  | Path                                                     | Status     |
| ------------------------- | -------------------------------------------------------- | ---------- |
| Lumibot strategy class    | `packages/backtest/lumibot_strategy.py`                  | ✅ Created |
| Backtest runner script    | `scripts/run_backtest.py`                                | ✅ Created |
| DTE/delta analysis script | `scripts/run_options_analysis.py`                        | ✅ Created |
| Backtest optional deps    | `apps/api/pyproject.toml` `[backtest]`                   | ✅ Added   |
| Migration 009             | `supabase/migrations/009_backtest_results.sql`           | ✅ Applied |
| 3 new Supabase tables     | `backtest_runs`, `backtest_trades`, `dte_delta_analysis` | ✅ Created |

---

## 3. Audit: Our Code vs Lumibot

### 3A. Scanner (`scanner.py`) vs Lumibot's Strategy Loop

| Dimension       | Our `scanner.py`                                             | Lumibot `Strategy.on_trading_iteration()`                |
| --------------- | ------------------------------------------------------------ | -------------------------------------------------------- |
| Execution model | Async (`asyncio`), embedded in FastAPI lifespan              | Synchronous, runs inside Lumibot's own scheduler process |
| Scheduling      | `_seconds_until_market_open()` — DST-aware, fires at 9:31 ET | Configurable via `self.sleeptime = "1D"`                 |
| Integrations    | Redis + Supabase + shadow mode + kill switch                 | Broker API only                                          |
| Timeout safety  | `asyncio.timeout(120.0)` per scan                            | None built in                                            |
| Self-healing    | 30-minute backoff on error                                   | `on_bot_crash()` hook                                    |

**Verdict: Do not replace scanner.py.** Lumibot's loop cannot embed in FastAPI's async lifespan without running in a separate thread pool — which adds complexity without any benefit. The scanner is also actively running in Shadow Run 4 (Day 1 = 2026-06-27). Replacing it now would void the run.

The correct architecture is two separate systems:

- **Production:** `apps/api/src/trading/scanner.py` (async, FastAPI-embedded, shadow mode)
- **Backtesting:** `packages/backtest/lumibot_strategy.py` (sync, standalone Lumibot process)

### 3B. yfinance Client vs Lumibot Data Sources

| Dimension      | Our `YFinanceClient`                     | Lumibot's `get_historical_prices()`      |
| -------------- | ---------------------------------------- | ---------------------------------------- |
| Async          | ✅ Full async with `run_in_executor`     | ❌ Synchronous                           |
| Redis caching  | ✅ TTL-keyed cache (60s quotes, 4h bars) | ❌ None                                  |
| Options chains | Via Tradier (authoritative)              | Via yfinance (current only — no history) |
| Earnings dates | ✅ `get_earnings_dates()`                | ❌ Not provided                          |
| Insiders       | ✅ `get_insider_transactions()`          | ❌ Not provided                          |

**Verdict: Keep `YFinanceClient`.** It is more capable for our async production stack. Lumibot's data access is used inside `LuxAIOptionsStrategy` only for backtesting where async is not needed.

### 3C. Alpaca Broker (`alpaca.py`) vs Lumibot's Alpaca Broker

| Dimension               | Our `AlpacaPaperBroker`                                                   | Lumibot's `Alpaca` broker      |
| ----------------------- | ------------------------------------------------------------------------- | ------------------------------ |
| Paper-mode enforcement  | ✅ Hard-coded `paper-api.alpaca.markets`; raises if live account detected | Configurable — can submit live |
| Circuit breaker         | ✅ `CircuitBreaker` with failure threshold + recovery timeout             | ❌ None                        |
| Retry logic             | ✅ Exponential backoff (3x) on 429/5xx                                    | ❌ None                        |
| Kill switch integration | ✅ Via `KillSwitchService` at engine level                                | ❌ None                        |
| Shadow mode             | ✅ All orders intercepted and logged                                      | ❌ No concept                  |

**Verdict: Keep our `AlpacaPaperBroker`.** Lumibot's broker is appropriate for backtesting (used by `LuxAIOptionsStrategy` via `YahooDataBacktesting`). Our broker is the only choice for production — it has safety layers that Lumibot does not know about.

### 3D. TradingAgentsAdapter vs Lumibot Agent Teams

| Dimension         | Our `TradingAgentsAdapter`                                                                | Lumibot Agent Capability                |
| ----------------- | ----------------------------------------------------------------------------------------- | --------------------------------------- |
| Purpose           | Market sentiment analysis (BULLISH/BEARISH/NEUTRAL verdict)                               | Trading decision orchestration          |
| LLM backend       | DeepSeek (analysts) + Anthropic Haiku (risk gate)                                         | OpenAI / Anthropic                      |
| Debate structure  | Multi-agent: technical + sentiment + news analysts → bull/bear researchers → risk manager | Single strategy agent                   |
| Cost              | ~$0.0007/symbol/day                                                                       | Variable                                |
| Integration point | Pre-Tradier filter in scanner                                                             | Replaces `on_trading_iteration()` logic |

**Verdict: Keep `TradingAgentsAdapter`.** These serve fundamentally different purposes. Our adapter is a market signal generator (should we enter?). Lumibot's agent capabilities are for strategy orchestration (how do we manage this position?). They can coexist — in a future B2 phase, you could feed the TradingAgents verdict INTO a Lumibot strategy to gate position entry.

### 3E. Backtester: We Had None; Lumibot Provides One

This is where Lumibot adds genuine new capability:

| Capability             | Before       | After                                                                 |
| ---------------------- | ------------ | --------------------------------------------------------------------- |
| Backtest framework     | ❌ Not built | ✅ `LuxAIOptionsStrategy` via Lumibot                                 |
| Portfolio tracking     | ❌ None      | ✅ Lumibot manages cash/positions/P&L                                 |
| Benchmark comparison   | ❌ None      | ✅ SPY buy-and-hold auto-computed                                     |
| Exit rule simulation   | ❌ None      | ✅ `-5%/-10%` rules in `_check_exit_rules()`                          |
| Self-healing lifecycle | ❌ None      | ✅ `on_bot_crash()`, `before_market_opens()`, `after_market_closes()` |

---

## 4. Critical Data Limitation: No Historical Options Chains on Free Tier

This is the most important constraint for backtesting.

**yfinance does not store historical options chain data.** `yf.Ticker("SPY").options` returns today's available expiry dates. `yf.Ticker("SPY").option_chain("2025-12-19")` only works for currently-listed expiries — not past ones.

This means:

- Any "6-month backtest" of options strategies using yfinance **cannot** use real 2025-12-01 to 2026-06-01 options prices
- Lumibot's `YahooDataBacktesting.get_chains()` has the same limitation

**Our approach:** Synthesise option prices from underlying OHLCV + constant IV (25%) using Black-Scholes. Every synthetic data point is labeled `data_mode: "SYNTHETIC_BLACK_SCHOLES"` in all outputs and Supabase rows.

**What synthetic backtesting is useful for:**

- Validating the signal pipeline (does the scanner logic find contracts?)
- Comparing DTE/delta combinations on a relative basis (which param set produces better synthetic win rates)
- Infrastructure testing (does the Lumibot lifecycle work end-to-end?)

**What it cannot tell you:**

- Real fill prices (actual bid-ask spreads are 10-30% of mid for liquid options)
- Realistic slippage on small-cap watchlist symbols
- IV crush around earnings or FOMC events (we use constant IV)

**Upgrade path:** At `$1,000+` account size, add the Unusual Whales basic plan (per CLAUDE.md) which includes historical IV rank data. At `$5,000+`, add OPRA-grade options feed.

---

## 5. Optopsy Assessment

**optopsy (`pip install optopsy==2.0.0b6`):**

- Last release: 2021. Targets Python 3.6, pandas 0.23.
- Not compatible with Python 3.11+ or pandas 2.x.
- Requires historical options chain CSV files (CBOE bulk download or Think or Swim export format).
- Not available on free tier — CBOE bulk data requires a paid data subscription.

**Decision:** Did not install optopsy. Instead, `scripts/run_options_analysis.py` implements the identical DTE/delta sweep logic using our `BlackScholesGreeks` engine on yfinance OHLCV history. The Supabase table `dte_delta_analysis` stores results in the same schema the script would produce.

When real CBOE CSV data is available, the script can be extended to load it directly instead of synthesising prices.

---

## 6. What to Run

### Install backtest dependencies (local only, NOT deployed to Fly)

```bash
cd apps/api
pip install ".[backtest]"
```

If optopsy fails (expected on Python 3.11+), install without it:

```bash
pip install "lumibot>=4.5.0"
```

### Run the DTE/delta analysis (fastest, no Lumibot needed)

```bash
python scripts/run_options_analysis.py
# Results in backtest_results/dte_delta_analysis.json
```

### Run the Lumibot backtest

```bash
python scripts/run_backtest.py --start 2025-12-01 --end 2026-06-01 --cash 100
# Results in backtest_results/results.json
```

### Upload results to Supabase (when you have actual results)

The three tables (`backtest_runs`, `backtest_trades`, `dte_delta_analysis`) are ready. Write the results with the service role key — same pattern as `scanner._write_daily_log()`.

---

## 7. What NOT to Do (Preserved from Prior Analysis)

Per CLAUDE.md "What Not to Build Right Now":

| Item                                   | Status                                         |
| -------------------------------------- | ---------------------------------------------- |
| Replace scanner.py with Lumibot loop   | ❌ Do not do this. Shadow run is active.       |
| Install `tastytrade` package           | ❌ Not yet (shadow gate not passed)            |
| Add new AI agents                      | ❌ B2 scope — after shadow run                 |
| Autonomous trade execution             | ❌ Shadow gate not passed                      |
| Multi-agent backtesting with LLM calls | ❌ Costs tokens; synthetic data isn't worth it |

---

## 8. Shadow Run Impact

**Zero impact on Shadow Run 4.**

- `scanner.py` not modified
- `main.py` not modified
- No new Fly environment variables
- No new Redis keys
- No new background tasks in the FastAPI lifespan
- Backtest scripts are local-only; they are not deployed to Fly

The shadow run proceeds as planned. Day 1 = 2026-06-27 (tomorrow).

---

## 9. Architecture After This Session

```
luxai-os/
├── apps/api/src/trading/
│   ├── scanner.py          ← PRODUCTION: async, FastAPI, shadow mode, Redis, Supabase
│   ├── alpaca.py           ← PRODUCTION: paper broker, circuit breaker, kill switch
│   └── ...
├── apps/api/src/agents/
│   └── trading_agents_adapter.py  ← PRODUCTION: DeepSeek debate, Haiku risk gate
├── packages/backtest/
│   └── lumibot_strategy.py ← BACKTEST ONLY: LuxAIOptionsStrategy(Strategy)
│                             Lifecycle: initialize, on_trading_iteration,
│                             before_market_opens, after_market_closes, on_bot_crash
└── scripts/
    ├── run_backtest.py      ← Lumibot YahooDataBacktesting runner
    └── run_options_analysis.py  ← DTE/delta sweep (Black-Scholes, no Lumibot needed)
```

---

## 10. Recommended Next Actions (Post Shadow-Run)

Once Shadow Run 4 completes (Day 14 = 2026-07-15) and the admin sign-off happens:

1. **Run the DTE/delta analysis** with `scripts/run_options_analysis.py`. Feed the top win-rate (DTE, delta) combination back into `scanner._MIN_DTE` and the strike selection loop.

2. **Run the Lumibot backtest** to validate the pipeline end-to-end. Compare synthetic win rate vs. shadow run actual hit rate — divergence indicates the synthetic IV assumption is wrong.

3. **B2 phase: Options Intelligence Layer.** This is where Lumibot's agent integration becomes relevant — use TradingAgents verdict to gate `on_trading_iteration()` entry rather than running it independently in the scanner.

4. **Real options data at $1,000+.** Replace `_SYNTHETIC_IV_DEFAULT = 0.25` with Tradier IV rank. Replace `open_interest=250` (proxy) with real Tradier chain data. At that point backtest results become actionable.
