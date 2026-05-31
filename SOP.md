# Standard Operating Procedures — LuxAI OS / .fylr

Daily and weekly workflows for disciplined small-account options trading.
These SOPs assume shadow mode is active and the account is in the $100–$500 (Tiny Tier) range
unless otherwise noted.

---

## Table of Contents

1. [Morning Routine (Pre-Market)](#1-morning-routine-pre-market)
2. [Market Open Procedure](#2-market-open-procedure)
3. [Intraday Monitoring](#3-intraday-monitoring)
4. [Market Close + Journal Review](#4-market-close--journal-review)
5. [New User Walkthrough](#5-new-user-walkthrough)
6. [Shadow Mode Monitoring Guide](#6-shadow-mode-monitoring-guide)
7. [Escalation: When Something Breaks](#7-escalation-when-something-breaks)

---

## 1. Morning Routine (Pre-Market)

**Time:** 8:00–9:25 AM ET (before 9:30 AM open)

### System Health Check

- [ ] Open LuxAI OS — confirm the amber **Shadow Mode** banner is visible.
- [ ] Confirm the dashboard loads without errors (top-right: "System Nominal" indicator).
- [ ] Verify paper trading status: `GET /api/v1/trading/status` — `configured: true`, `broker_connected: true`.
- [ ] Shadow P&L counter on banner is updating (not stuck at $0.00 if you have prior signals).

### Macro Calendar Scan

Check all of the following for events within the next **5 trading days**:

- **FOMC meetings** — rate decisions, Powell statements
- **CPI / PPI** — inflation prints (first week of month)
- **Jobs Report (NFP)** — first Friday of month
- **GDP / PCE** — quarterly and monthly
- **Earnings** — for any symbol you are considering

Free calendars:

- Forex Factory: https://www.forexfactory.com/calendar
- Investing.com: https://www.investing.com/economic-calendar

**Rule:** If a macro event falls within your intended expiration window, that trade gets a **Caution** or **Reject** verdict automatically. Do not override this.

### Pre-Market Movers Scan

Using Alpaca or TradingView (free):

- Identify symbols with unusual pre-market volume (>2x normal).
- Note direction (gap up or gap down) and catalyst (news, earnings beat/miss).
- These become candidates for Trade Idea Workbench analysis once it is built (Phase B3).

### Account Snapshot

- [ ] Open Trading dashboard → note current paper equity.
- [ ] Confirm no open positions are approaching stop-loss levels.
- [ ] Confirm max risk per trade: if account < $500, max risk = $5 or 3% (lower wins).

### Pre-Market Checklist Summary

```
[ ] Shadow banner visible and updating
[ ] System health nominal
[ ] Macro calendar clear for next 5 days (or flags noted)
[ ] Pre-market movers scanned
[ ] Account equity noted
[ ] No unexpected open positions
```

---

## 2. Market Open Procedure

**Time:** 9:30–10:00 AM ET

### First 30 Minutes — Observe, Don't Trade

The first 30 minutes of market open have elevated volatility and wide bid-ask spreads. Options premiums are often inflated during this window.

- Do not submit any shadow trade signals in the first 10 minutes.
- Watch for the initial trend to establish direction on your watchlist.
- Note if pre-market gaps are holding or reversing.

### Trade Signal Workflow (Shadow Mode)

Once the market settles (after 10:00 AM):

1. **Identify the tip or idea.** Source: price action, news, pre-market mover.
2. **Open the Trade Idea Workbench** (Phase B3 — not yet live; when available: `/workbench`).
3. **Input the signal:**
   - Symbol
   - Direction (bullish / bearish)
   - Suggested contract or "let the system choose"
   - Target expiration
   - Budget (max $5 for Tiny Tier accounts)
4. **Review the three alternatives:**
   - Best Value (highest Options Score within budget)
   - Best Probability (highest delta)
   - Spread Version (debit spread, ~50% of single-leg cost)
5. **Review the verdict:** Accept / Caution / Reject.
6. **If Caution or Reject:** do not override. Log the reason in your personal journal.
7. **If Accept:** submit via Trading page — shadow mode intercepts it, logs it, and tracks shadow P&L.

### Manual Signal Logging (While Workbench is in B3)

Until the Trade Idea Workbench is built, log signals manually:

```
Date: 2026-05-30
Time: 10:15 AM ET
Symbol: SPY
Direction: Bullish
Intended Contract: SPY 240C 6/14 exp
Intended Entry: $1.20 (ask)
Budget: $5 (4 shares / 0.04 contracts — note: 1 contract min)
Reason: Gap above 50 EMA, macro calendar clear
Verdict (manual): Accept
Shadow P&L (to be logged at close): TBD
```

---

## 3. Intraday Monitoring

**Time:** 10:00 AM – 3:45 PM ET

### Monitoring Dashboard

Keep the LuxAI OS dashboard open during market hours. Check:

- **Event stream** (Monitoring page): any `TRADE_RISK_TRIGGERED` events.
- **Portfolio panel**: unrealized P&L on open paper positions.
- **Shadow trades**: any signals intercepted and their current theoretical value.

### Risk Alerts to Act On Immediately

| Event                             | Action                                                         |
| --------------------------------- | -------------------------------------------------------------- |
| `TRADE_RISK_TRIGGERED: stop_loss` | Review — stop-loss fired on a paper position. Log it.          |
| `degraded_risk_mode: true`        | Quotes are stale (>15s). No new signals until resolved.        |
| `circuit_opened: alpaca_trading`  | Alpaca API degraded. Pause all activity. Wait for recovery.    |
| Shadow banner disappears          | **Critical** — Redis or API is down. Check system immediately. |

### Intraday Rules

- Do not submit more than **1 shadow signal per symbol per day** (Tiny Tier).
- Do not average down: if a position moves against you by 30%+, log it as a loss. Do not add.
- Respect DTE: Tiny Tier minimum is 7 DTE. Do not enter contracts expiring this week.
- Monitor bid-ask spreads on open shadow positions — if spread exceeds 15% of mid, log as illiquid.

### Mid-Day Review (12:30 PM ET)

Take 5 minutes at mid-day:

- [ ] Count open shadow positions.
- [ ] Note which are winning, losing, flat.
- [ ] Check if any macro events are releasing this afternoon.
- [ ] Confirm shadow banner is still showing.

---

## 4. Market Close + Journal Review

**Time:** 3:45–4:30 PM ET

### Pre-Close (3:45–4:00 PM)

- [ ] Note final prices on all open shadow positions.
- [ ] If any paper positions are in-the-money and expiring this week: flag them for review.
- [ ] No new signals in the last 15 minutes before close (spreads widen, thin liquidity).

### Market Close (4:00 PM)

- [ ] Record closing equity from the Trading dashboard.
- [ ] Note daily paper P&L (realized + unrealized).
- [ ] Screenshot or note shadow P&L counter from the banner.

### Journal Review

For each shadow trade signal submitted today, record:

```
Symbol: [symbol]
Direction: [call/put, bull/bear]
Entry signal time: [HH:MM ET]
Intended entry price: [from shadow log]
EOD theoretical price: [look up on broker or options platform]
Theoretical P&L: [calc]
What worked: [1 sentence]
What to improve: [1 sentence]
```

Keep this in a personal file (Obsidian, Notion, plain text — your choice). The shadow report generator produces the aggregate view; this manual log captures the why.

### Weekly Close (Friday 4:00 PM)

On Fridays, additionally:

1. Generate the shadow report:

   ```bash
   python packages/workbench/shadow_report.py generate --days 7 --output weekly_shadow_$(date +%Y%m%d).md
   ```

2. Review:
   - Hit rate: is it above 40%?
   - Total shadow P&L: directionally correct?
   - Largest loss: was the stop-loss respected?
   - Worst miss: did you violate DTE or budget rules on any signal?

3. Adjust your watchlist and strategy focus for next week.

---

## 5. New User Walkthrough

Complete these steps in order. Do not skip.

### Step 1: Account Setup

1. Create a Supabase account and project.
2. Create an Alpaca paper trading account (not live).
3. Create an Upstash Redis database.
4. Clone the repo and copy `.env.example` to `.env`.
5. Fill in all required environment variables (see README).

### Step 2: Run Migrations

```bash
# In Supabase SQL editor or via Supabase CLI:
supabase db push

# Or manually — run each SQL file in supabase/migrations/ in numerical order.
```

Verify all three shadow mode tables appear in your Supabase Table Editor:

- `shadow_mode_config`
- `shadow_trades`
- `shadow_pnl`

### Step 3: Start the System

```bash
# Terminal 1: Backend
cd apps/api && uv run uvicorn src.main:app --reload --port 8000

# Terminal 2: Frontend
cd apps/web && pnpm dev
```

Open http://localhost:3000. Sign up or sign in with Supabase Auth.

### Step 4: Verify Shadow Mode is Active

- [ ] The amber **Shadow Mode** banner appears at the top of every dashboard page.
- [ ] It cannot be dismissed (there is no X button — this is correct).
- [ ] API check: `GET /api/v1/trading/shadow-status` returns `is_active: true`.

### Step 5: Submit Your First Shadow Trade

Go to the Trading page. Submit an order:

- Symbol: SPY
- Side: Buy
- Qty: 1
- Type: Market
- Idempotency Key: (any UUID)

Expected response:

```json
{
  "shadow_mode": true,
  "status": "SHADOW_ACKNOWLEDGED",
  "shadow_trade_id": "...",
  "message": "Shadow mode is active. No order was submitted to the broker."
}
```

This confirms the interception is working.

### Step 6: Run Your First Shadow Report

After a few days of signals:

```bash
python packages/workbench/shadow_report.py generate --days 7
```

Review the output. Understand what each section means.

### Step 7: Wait

Shadow mode runs for **14 consecutive days minimum**. There is no shortcut.
Use this time to:

- Refine your signal quality
- Learn the options scoring criteria
- Study the macro calendar
- Get comfortable with the platform

After 14 days, generate the full report, review it honestly, and only then discuss the shadow gate with an admin.

---

## 6. Shadow Mode Monitoring Guide

### What Shadow Mode Is

Shadow mode is the launch permission system for LuxAI OS. While active:

- All order submissions are intercepted before reaching Alpaca.
- Each intercepted order is logged in `shadow_trades` with the intended entry price.
- Shadow P&L is tracked separately from any real P&L (there is none).
- The amber banner is always visible and cannot be dismissed.

Shadow mode is **not** a sandbox or demo mode. Every signal matters for the gate audit.

### What to Watch During Shadow Mode

**Daily:**

- Banner is showing (system health)
- Shadow P&L counter is updating (persistence is working)
- No unexpected `shadow_mode: false` API responses

**Weekly:**

- Hit rate trending above 40% on closed shadow trades
- No DTE violations (all signals > 7 DTE for Tiny Tier)
- No budget violations (all signals ≤ $5 risk for Tiny Tier)
- Macro calendar respected (no signals on FOMC/CPI/NFP days)

### Shadow Gate Criteria

All of these must be true before requesting gate clearance:

| Criterion                 | Minimum        |
| ------------------------- | -------------- |
| Days active               | 14 consecutive |
| Total shadow signals      | 10+            |
| Hit rate (closed trades)  | 40%+           |
| DTE violations            | 0              |
| Budget violations         | 0              |
| Macro calendar violations | 0              |

If any criterion is not met, shadow mode continues. There is no appeal process.

### Requesting Gate Clearance

1. Generate the 14-day shadow report:

   ```bash
   python packages/workbench/shadow_report.py generate --days 14 --output gate_report.md
   ```

2. Review the report honestly. If criteria are met:

3. Contact the admin (yourself, if you are the admin) and request gate clearance.

4. Admin runs:

   ```bash
   curl -X DELETE \
     -H "Authorization: Bearer <admin-jwt>" \
     http://localhost:8000/api/v1/trading/shadow/deactivate
   ```

5. Verify shadow banner disappears.

6. Re-read the account tier rules before submitting any real paper orders.

### Re-Activating Shadow Mode

If you want to re-enter shadow mode at any time:

```bash
curl -X POST \
  -H "Authorization: Bearer <your-jwt>" \
  http://localhost:8000/api/v1/trading/shadow/activate
```

Shadow mode can always be re-activated. It cannot be accidentally deactivated.

---

## 7. Escalation: When Something Breaks

### Tier 1 — Self-Resolve (5 minutes)

| Symptom                     | Resolution                                                            |
| --------------------------- | --------------------------------------------------------------------- |
| Shadow banner not showing   | Hard-reload browser (Ctrl+Shift+R). Check browser console for errors. |
| Trading dashboard shows 503 | Backend is down. Restart: `uv run uvicorn src.main:app --reload`      |
| API returns 401             | Session expired. Sign out and sign back in.                           |
| Redis connection refused    | Start local Redis: `docker start luxai-redis`                         |
| "Alpaca not configured"     | Set `ALPACA_API_KEY` and `ALPACA_API_SECRET` in `.env` and restart.   |

### Tier 2 — Check Logs (15 minutes)

```bash
# FastAPI structured logs
cd apps/api
uv run uvicorn src.main:app --log-level debug

# Look for:
# - shadow_redis_unavailable_*  → Redis connectivity issue
# - shadow_supabase_read_failed → Supabase connectivity issue
# - circuit_opened              → Alpaca API degraded
# - degraded_risk_mode          → Quote stream issue
```

### Tier 3 — Emergency Halt

If any of the following occur:

- A paper order reaches Alpaca while shadow mode should be active
- The shadow banner disappears and you cannot determine why
- The system shows `is_active: false` unexpectedly

**Immediately:**

```bash
# Step 1: Activate shadow mode forcefully
curl -X POST \
  -H "Authorization: Bearer <jwt>" \
  http://localhost:8000/api/v1/trading/shadow/activate

# Step 2: Trigger emergency halt on the engine
curl -X POST \
  -H "Authorization: Bearer <jwt>" \
  http://localhost:8000/api/v1/trading/emergency-halt

# Step 3: Verify
curl -H "Authorization: Bearer <jwt>" \
  http://localhost:8000/api/v1/trading/shadow-status
# Expected: is_active: true

curl -H "Authorization: Bearer <jwt>" \
  http://localhost:8000/api/v1/trading/status
# Expected: broker_connected may be true but no orders should reach it
```

**Then:**

1. Check the `shadow_trades` table in Supabase for any unexpected entries.
2. Check the `trade_journal` table for any orders that may have slipped through.
3. Review the `system_halts` table (B1 — when implemented) for halt audit records.
4. Do not restart the system until you understand why the failure occurred.

### Incident Log Template

Keep a file `incidents/YYYY-MM-DD.md` for any Tier 2+ event:

```markdown
## Incident: [brief description]

Date: YYYY-MM-DD HH:MM ET
Tier: 2 / 3

### What happened

[Description]

### Timeline

- HH:MM — noticed
- HH:MM — investigated
- HH:MM — resolved

### Root cause

[What caused it]

### Resolution

[What fixed it]

### Prevention

[What to change to prevent recurrence]
```

---

---

## 8. Shadow Mode Monitoring Guide

### Reading the Shadow Banner

The amber banner at the top of every dashboard page shows:

| Field           | What it means                                                 |
| --------------- | ------------------------------------------------------------- |
| **Shadow P&L**  | Cumulative shadow profit/loss across all closed shadow trades |
| **Hit rate**    | Percentage of closed shadow trades that were profitable       |
| **Day counter** | Days since shadow mode was activated (gate requires ≥14)      |
| **Trade count** | Total shadow trades intercepted                               |

The banner cannot be dismissed. If it disappears, shadow mode has been deactivated or the frontend cannot reach the API — treat this as a Tier 3 event.

### Generating the Shadow Report

```bash
# Full 14-day report (recommended at day 7 and day 14)
python packages/workbench/shadow_report.py generate --days 14

# With output file
python packages/workbench/shadow_report.py generate \
  --days 14 \
  --output shadow-report-$(date +%Y-%m-%d).md

# Single user (required if multi-tenant)
python packages/workbench/shadow_report.py generate \
  --user-id <your-uuid> --days 14
```

Requires `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in your environment.

### Metrics to Review Daily

| Metric               | Healthy range   | Flag if                                       |
| -------------------- | --------------- | --------------------------------------------- |
| Hit rate             | 45–70%          | < 30% or > 85% (both suspicious)              |
| Avg win / avg loss   | Win ≥ 1.5× loss | Loss consistently larger than win             |
| Macro warning rate   | < 40% of trades | > 60% means you're ignoring calendar          |
| CAUTION verdict rate | < 50%           | > 70% means setup quality is poor             |
| REJECT override      | 0               | Any REJECT that was manually submitted anyway |

### What a Healthy Shadow Run Looks Like

After 14 days, a gate-ready run shows:

- At least 10 workbench analyses submitted
- At least 5 shadow trades logged (the system intercepted at least 5 orders)
- Hit rate between 40% and 75%
- No single trade exceeded 5% of account size
- No 0DTE, earnings plays, or naked options in the trade log
- Health endpoint returning `"supabase": "ok"` and `"redis": "ok"` consistently
- No entries in `system_halts` table (no kill switch triggers)

### Red Flags That Indicate a Problem

Stop the shadow run and investigate immediately if:

- Shadow P&L shows gains > +50% in under a week (probably a data error)
- Hit rate > 90% (probably the monitor isn't closing losing trades)
- `shadow_trades` table has rows stuck in `status: 'open'` for > 48 hours
- `system_halts` has any rows (something triggered the kill switch)
- Health endpoint showing `"redis": "error"` — idempotency and locks are disabled

---

## 9. Trade Idea Workbench Daily Use

### Entering a Tip

1. Navigate to **Workbench** in the left sidebar.
2. Fill in:
   - **Symbol** — the underlying ticker (e.g. `AAPL`, `SPY`, `TSLA`)
   - **Direction** — Bullish (calls) or Bearish (puts)
   - **Target expiration** — pick a Friday 7–21 days out for best score
   - **Budget** — max you are willing to pay in premium per contract (e.g. `$50`)
   - **Account size** — your current paper equity (e.g. `$300`)
3. Click **Analyze trade idea**.

### Reading the Contract Cards

Three cards appear after analysis:

| Card                 | What it shows                                                   |
| -------------------- | --------------------------------------------------------------- |
| **Best Value**       | Highest Options Score within your budget                        |
| **Best Probability** | Highest delta — best chance of expiring in the money            |
| **Spread Version**   | Debit spread: buy near ATM, sell 1–2 strikes OTM for lower cost |

Each card shows:

- **Score ring** — colored 0–10 (green ≥ 7, amber 5–7, red < 5)
- **Greeks** — Delta, IV, Theta, Open Interest
- **Budget bar** — how much of your budget the trade uses
- **Breakeven** — price the underlying must reach for the trade to be profitable
- Expand **Score breakdown** to see all 5 factors

### Interpreting the Options Score

| Score    | Meaning                                                                       |
| -------- | ----------------------------------------------------------------------------- |
| 7.0–10.0 | High quality — good liquidity, tight spread, delta in range, low IV, good DTE |
| 5.0–6.9  | Adequate — passes most filters but has at least one weakness                  |
| 0–4.9    | Poor — do not trade this. Tight budget may force this; expand budget or skip  |

Score weights: Liquidity 25% · Spread 20% · Delta 20% · IV 20% · DTE 15%.

### Interpreting the Verdict

| Verdict             | Meaning                                                            |
| ------------------- | ------------------------------------------------------------------ |
| **Accept** (green)  | Score ≥ 6.5, no earnings in window, no high-risk macro events      |
| **Caution** (amber) | Earnings in window, major macro event, or score 4–6.5              |
| **Reject** (red)    | Score < 4.0, no contracts fit budget, or tier constraint violation |

### When to Accept CAUTION Trades

CAUTION is acceptable when:

- The earnings warning is for a different date than your expiration (check `days_away`)
- The macro event is PCE or GDP (medium risk) not FOMC or CPI (high risk)
- Score is ≥ 6.0 and all other factors are clean

CAUTION is not acceptable when:

- Earnings fall within the expiration window
- FOMC rate decision is within the expiration window
- Score is below 5.0

### When to Override REJECT

Almost never. The only valid override is a data error — e.g. Tradier returns no chain because the expiration is not a valid options Friday. In that case, change the expiration and reanalyze. Do not submit an order that scored REJECT based on trade quality.

---

## 10. Two-Week Shadow Run Checklist

Complete this checklist before requesting shadow gate clearance. All boxes must be checked.

```
WEEK 1
□ Shadow mode confirmed active (amber banner visible day 1)
□ Health endpoint returning all green (supabase, redis, tradier, alpaca)
□ At least 3 Workbench analyses run in first 3 days
□ At least 1 shadow trade intercepted
□ No kill switch triggers (system_halts table empty)
□ No duplicate order attempts in order_idempotency_log
□ Shadow report generated at day 7 — review hit rate and P&L

WEEK 2
□ At least 7 more Workbench analyses (total ≥ 10)
□ At least 4 more shadow trades (total ≥ 5)
□ Hit rate 40–75% across all closed trades
□ No single trade exceeded 5% of account size
□ No 0DTE, earnings, naked, or averaging_down tags in shadow_trades
□ Macro calendar warnings heeded — CAUTION trades reviewed before noting
□ Health endpoint consistent across both weeks
□ Shadow report generated at day 14 — full 14-day window

GATE REVIEW
□ Shadow report reviewed by admin
□ Journal audit: signal quality, risk adherence, P&L realism assessed
□ Admin explicitly confirms gate passed (written confirmation required)
□ Only AFTER confirmation: live trading discussion may begin
```

---

_LuxAI OS / .fylr — Discipline is the edge. Shadow mode is the gate._
