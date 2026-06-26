# LuxAI OS — Shadow Run Log

## Run 1 — VOIDED (2026-05-31)

**Reason:** No authenticated user existed at the time this log was created. All 6 Supabase tables confirmed empty (0 rows) on 2026-06-05 audit. Shadow mode was never activated for a real user. No workbench analyses, shadow trades, or P&L data was collected. The shadow clock does not start until first successful login + shadow activation + first workbench analysis.

---

## Run 2 — VOIDED (2026-06-05)

**Reason:** Gate criteria were never met. The run was initialised but 0 workbench analyses and 0 shadow trades were logged across the window. Clock voided.

---

## Run 3 — VOIDED (2026-06-18 to 2026-06-26)

**Reason:** Three silent bugs caused zero data collection for all 7 trading days. The scanner loop ran correctly but produced nothing.

**Bugs identified and fixed 2026-06-26:**

1. **Redis URL reconstruction bug** (`scanner.py:179`) — chain fetch fell back to `redis://localhost:6379` in production; all Tradier requests silently failed.
2. **$5 cost cap filtered entire watchlist** — `contract.mid * 100 > 5.0` eliminated every liquid 7–21 DTE option for SPY/QQQ/NVDA/AAPL/META/AMZN/TSLA. Scanner ran daily and produced 0 signals every day.
3. **Health check `acreate_client()` had no timeout** — health endpoint took 5–13s, tripping Fly's 5s window repeatedly.

**Additional fix (same session):**

- `trading_agents_adapter.py` wrote to `workbench_analyses` which has incompatible schema (wrong verdict values, missing required columns). Debate logs now correctly write to `scanner_debates`.

**Evidence:** `shadow_trades` = 0 rows. `workbench_analyses` = 0 rows. `scanner_daily_log` table did not exist.

**Monitoring added:** `scanner_daily_log` and `scanner_debates` tables created (migration 008). Health endpoint now exposes `last_scan_date`, `last_scan_signals`, `scanner_errors_today`, `scanner_alert`. Zero-signal streak alert fires at day 3.

**Day 7 checkpoint report:** `SHADOW_DAY7_REPORT.md`

---

## Run 4 — ACTIVE ✓

### Run Parameters

| Field              | Value                                         |
| ------------------ | --------------------------------------------- |
| Backend            | https://luxai-api.fly.dev                     |
| Frontend           | https://luxai-web-snowy.vercel.app            |
| Shadow mode        | ACTIVE                                        |
| Kill switch        | Clear                                         |
| Day 1              | **2026-06-27 (Friday)**                       |
| Day 7 checkpoint   | **2026-07-07 (Monday)**                       |
| Day 14 checkpoint  | **2026-07-15 (Tuesday)**                      |
| Market holiday     | 2026-07-04 (Independence Day — not counted)   |
| Total trading days | 14                                            |
| Gate criteria      | 10 analyses, 5 shadow trades, 40–75% hit rate |

### Trading Day Count

| Day | Date       | Notes                                   |
| --- | ---------- | --------------------------------------- |
| 1   | 2026-06-27 | Fri — first clean scan                  |
| —   | 2026-06-28 | Sat — skip                              |
| —   | 2026-06-29 | Sun — skip                              |
| 2   | 2026-06-30 | Mon                                     |
| 3   | 2026-07-01 | Tue                                     |
| 4   | 2026-07-02 | Wed                                     |
| 5   | 2026-07-03 | Thu                                     |
| —   | 2026-07-04 | **Market holiday — Independence Day**   |
| —   | 2026-07-05 | Sat — skip                              |
| —   | 2026-07-06 | Sun — skip                              |
| 6   | 2026-07-07 | Mon — **Day 7 checkpoint**              |
| 7   | 2026-07-08 | Tue                                     |
| 8   | 2026-07-09 | Wed                                     |
| 9   | 2026-07-10 | Thu                                     |
| 10  | 2026-07-11 | Fri                                     |
| —   | 2026-07-12 | Sat — skip                              |
| —   | 2026-07-13 | Sun — skip                              |
| 11  | 2026-07-14 | Mon                                     |
| 12  | 2026-07-15 | Tue — **Day 14 checkpoint / gate eval** |

> Note: 12 clean trading days are available. Gate requires 14 calendar days of continuous operation, with 10+ analyses and 5+ shadow trades. Manual submissions can supplement scanner output.

---

### Auto-Scanner Schedule

**Target: 9:31 AM US/Eastern every market day = 13:31 UTC (EDT)**

Code: `apps/api/src/trading/scanner.py:_seconds_until_market_open()`  
Uses `ZoneInfo("America/New_York")` — DST-aware, no fixed offset.

---

### Gate Criteria Tracker

| Criterion                        | Target    | Current | Status  |
| -------------------------------- | --------- | ------- | ------- |
| Workbench analyses submitted     | ≥ 10      | 0       | Pending |
| Shadow trades intercepted/logged | ≥ 5       | 0       | Pending |
| Hit rate (closed trades)         | 40%–75%   | N/A     | Pending |
| Kill switch triggers             | 0         | 0       | ✓       |
| Health endpoint green            | Always    | ✓       | Running |
| scanner_daily_log rows           | ≥ 12      | 0       | Pending |
| Day 7 report                     | Generated | Pending | Pending |
| Day 14 report                    | Generated | Pending | Pending |
| Admin journal audit              | Complete  | Pending | Pending |

---

### Day 7 Checkpoint — 2026-07-07

_To be filled on 2026-07-07._

```
scanner_daily_log rows:
shadow_trades rows:
workbench_analyses rows (manual):
scanner_debates rows:
Closed trades:
Hit rate:
Kill switch triggers:
Health: all green / degraded
scanner_alert active: yes/no
Notes:
```

---

### Day 14 Checkpoint — 2026-07-15

_To be filled on 2026-07-15._

```
scanner_daily_log rows:
shadow_trades rows:
workbench_analyses rows (manual):
Closed trades:
Hit rate:
Kill switch triggers:
Health: all green / degraded
Notes:
Admin sign-off:
```

---

### Live Trading Gate

Shadow mode can only be exited when all Day 14 gate criteria are met AND admin
explicitly confirms. No code changes for live trading before that confirmation.
