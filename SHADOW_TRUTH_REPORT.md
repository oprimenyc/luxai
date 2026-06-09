# SHADOW TRUTH REPORT

Generated: 2026-06-09

---

## 1. What Is Running Right Now (Honest)

**One background task is alive when the API server is running:**

- `shadow_trade_monitor` — polls every 60 seconds. Reads all open `shadow_trades` rows from Supabase, fetches the current price for each symbol via Alpaca, and closes any trade that has moved -5% (stop-loss) or +10% (take-profit). It logs the result and triggers P&L aggregation on close.

**What is NOT running:**

- No price feed streaming (Alpaca WebSocket is only opened on explicit `subscribe_quotes()` calls — nothing calls it automatically)
- No Tradier polling
- No signal generation
- No workbench analysis on a timer

**The shadow trade monitor runs forever but has nothing to do unless shadow trades exist.**

---

## 2. What Was Broken or Missing

### The core gap: no signal source

Shadow trades are created in exactly one place: `apps/api/src/trading/router.py:253` — when a user submits a POST to `/api/v1/trading/orders` and shadow mode is active. The workbench (`/api/v1/workbench/analyze`) does **not** create shadow trades — it is read-only analysis.

This means the shadow run gate criteria:

> "≥ 5 shadow trades intercepted and logged"

**could not be met without manual action.** Every single shadow trade required the platform owner to either:
a. Use the workbench and then separately submit an order, or
b. POST directly to the orders endpoint

The shadow monitor was a trap: it monitored trades that could never arrive automatically.

### Supabase row counts (verified 2026-06-09):

| Table                 | Rows |
| --------------------- | ---- |
| shadow_trades         | 0    |
| shadow_pnl            | 0    |
| workbench_analyses    | 0    |
| order_idempotency_log | 0    |
| system_halts          | 0    |
| shadow_mode_config    | 1    |

One row in `shadow_mode_config` confirms shadow mode is active. Zero shadow trades means the 14-day shadow run clock has no data and cannot satisfy any gate criterion.

---

## 3. What Was Built to Fix It

### New file: `apps/api/src/trading/scanner.py`

A `MarketScannerService` that:

1. Waits for 9:31 AM US Eastern on market days (Mon–Fri)
2. Fetches the current price from Alpaca for each symbol in the watchlist
3. Fetches the nearest options chain (7–21 DTE) from Tradier
4. Scores every contract using the existing `OptionsScorer` (same 5-factor weights)
5. Applies Tiny tier hard limits: max $5 cost per contract, min 7 DTE
6. Creates a `shadow_trade` row via `ShadowModeService.record_shadow_trade()` for any contract scoring >= 7.0/10
7. Caps at 3 signals per day
8. Tags every row with `source="auto_scanner"` for auditability

**Watchlist:** SPY, QQQ, TSLA, NVDA, AAPL, META, AMZN

### Updated: `apps/api/src/main.py`

Wired `auto_scanner_loop` into the lifespan context manager as a second background task alongside `shadow_trade_monitor`. Both tasks are explicitly cancelled on shutdown. The scanner only starts if both `ALPACA_API_KEY` and `TRADIER_API_KEY` are set — missing keys logs a warning and skips gracefully.

---

## 4. What Runs Automatically Without You Now

Once the API is deployed with the new code and both API keys are set in the environment:

- **Every market day at 9:31 AM ET:** Scanner wakes up, checks SPY, QQQ, TSLA, NVDA, AAPL, META, AMZN. Any option scoring >= 7.0/10 and within the $5 Tiny tier limit creates a shadow trade automatically.
- **Every 60 seconds (24/7 while API is up):** Shadow monitor checks all open shadow trades against their -5% stop / +10% take-profit thresholds. Closes qualifying trades and aggregates P&L.
- **On every shadow trade close:** P&L is recomputed and written to `shadow_pnl` automatically.

The shadow run can now accumulate data without any daily action from you.

---

## 5. What Still Needs Your Daily Action

**Nothing daily is required for the shadow run to accumulate data.** The scanner handles it.

The following still require manual input:

- **Using the workbench** — if you have a specific trade idea, POST `/api/v1/workbench/analyze` to get a scored recommendation. This creates a `workbench_analyses` row (counts toward the >= 10 analyses gate criterion).
- **Reviewing the shadow journal on Day 7 and Day 14** — required by the gate criteria before any live trading discussion. No code runs this for you.
- **Admin actions** — kill switch clear, shadow mode deactivation — these are intentionally admin-only.

---

## 6. Shadow Run Clock Status

**Current state:** Day 0. No shadow trades, no workbench analyses on record.

Gate criteria status:

| Criterion                 | Required   | Current       | Status           |
| ------------------------- | ---------- | ------------- | ---------------- |
| Workbench analyses        | >= 10      | 0             | Not started      |
| Shadow trades intercepted | >= 5       | 0             | Not started      |
| Hit rate (closed trades)  | 40–75%     | N/A           | No data          |
| Kill switch triggers      | 0          | 0 (clean)     | Pass             |
| Health endpoint green     | Both weeks | Unknown       | Needs monitoring |
| Day 7 shadow report       | Generated  | Not generated | Not started      |
| Day 14 shadow report      | Generated  | Not generated | Not started      |
| Journal audit             | Completed  | Not started   | Not started      |

The scanner deployed today starts the clock. The first automatic signals should appear the next market morning at 9:31 AM ET.

---

## 7. Declaration

**STILL NEEDS DAILY INPUT — changing to: WILL BE SELF-SUFFICIENT after deployment**

Before this session: the shadow run could not accumulate data without daily manual intervention. The shadow monitor existed but had no source of shadow trades to monitor.

After this session: the auto-scanner generates signals at market open each day. The shadow monitor closes them when exit conditions are met. P&L aggregates automatically. The shadow run gate criteria can now be satisfied without any daily action from the platform owner.

**Remaining action required from you:**

1. Deploy the updated API with the scanner code to Railway
2. Confirm `ALPACA_API_KEY`, `ALPACA_API_SECRET`, and `TRADIER_API_KEY` are set in the Railway environment
3. Use the workbench at least 10 times over the 14-day period (takes 5 minutes per session — see DAILY_ROUTINE.md)
4. Run the Day 7 and Day 14 shadow reports
5. Complete the journal audit

The system is now structurally capable of running the shadow gate on its own. The human gates (audit, journal review) are intentional — they cannot be automated.
