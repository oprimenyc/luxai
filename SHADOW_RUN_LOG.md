# LuxAI OS — Shadow Run Log

## Run 1 — VOIDED (2026-05-31)

**Reason:** No authenticated user existed at the time this log was created. All 6 Supabase tables confirmed empty (0 rows) on 2026-06-05 audit. Shadow mode was never activated for a real user. No workbench analyses, shadow trades, or P&L data was collected. The shadow clock does not start until first successful login + shadow activation + first workbench analysis.

---

## Run 2 — VOIDED (2026-06-05)

**Reason:** Gate criteria were never met. The run was initialised but 0 workbench analyses and 0 shadow trades were logged across the window. Clock voided. Replaced by Run 3 below with corrected start date and holiday-adjusted schedule.

---

## Run 3 — ACTIVE

### Run Parameters

| Field              | Value                                         |
| ------------------ | --------------------------------------------- |
| Backend            | https://luxai-api.fly.dev                     |
| Frontend           | https://luxai-web-snowy.vercel.app            |
| Shadow mode        | ACTIVE                                        |
| Kill switch        | Clear                                         |
| Day 1              | 2026-06-18 (Wednesday)                        |
| Day 7 checkpoint   | 2026-06-26 (Thursday)                         |
| Day 14 checkpoint  | 2026-07-08 (Tuesday)                          |
| Market holiday     | 2026-07-04 (Independence Day — not counted)   |
| Total trading days | 14                                            |
| Gate criteria      | 10 analyses, 5 shadow trades, 40–75% hit rate |

### Trading Day Count

| Day | Date       | Notes                                 |
| --- | ---------- | ------------------------------------- |
| 1   | 2026-06-18 | Wed                                   |
| 2   | 2026-06-19 | Thu                                   |
| 3   | 2026-06-20 | Fri                                   |
| —   | 2026-06-21 | Sat — skip                            |
| —   | 2026-06-22 | Sun — skip                            |
| 4   | 2026-06-23 | Mon                                   |
| 5   | 2026-06-24 | Tue                                   |
| 6   | 2026-06-25 | Wed                                   |
| 7   | 2026-06-26 | **Day 7 checkpoint**                  |
| 8   | 2026-06-27 | Fri                                   |
| —   | 2026-06-28 | Sat — skip                            |
| —   | 2026-06-29 | Sun — skip                            |
| 9   | 2026-06-30 | Mon                                   |
| 10  | 2026-07-01 | Tue                                   |
| 11  | 2026-07-02 | Wed                                   |
| 12  | 2026-07-03 | Thu                                   |
| —   | 2026-07-04 | **Market holiday — Independence Day** |
| —   | 2026-07-05 | Sat — skip                            |
| —   | 2026-07-06 | Sun — skip                            |
| 13  | 2026-07-07 | Mon                                   |
| 14  | 2026-07-08 | **Day 14 checkpoint**                 |

---

### Auto-Scanner Schedule Confirmation

The scanner fires via `auto_scanner_loop` in `apps/api/src/trading/scanner.py`.

**Target time: 9:31 AM US/Eastern every market day.**

The scheduler uses `ZoneInfo("America/New_York")` — not a fixed UTC offset. This
means DST is handled correctly and automatically.

| Season                | Offset | 9:31 AM ET in UTC |
| --------------------- | ------ | ----------------- |
| Summer (EDT, current) | UTC-4  | **13:31 UTC**     |
| Winter (EST)          | UTC-5  | 14:31 UTC         |

We are currently in EDT. The scanner fires at **13:31 UTC**.

Code reference: `apps/api/src/trading/scanner.py:_seconds_until_market_open()`

```python
from zoneinfo import ZoneInfo
et = ZoneInfo("America/New_York")
now_et = datetime.now(et)
target = now_et.replace(hour=9, minute=31, second=0, microsecond=0)
```

No manual UTC conversion is needed. The timezone library handles the offset
correctly regardless of season.

---

### Gate Criteria Tracker

| Criterion                        | Target    | Current | Status  |
| -------------------------------- | --------- | ------- | ------- |
| Workbench analyses submitted     | ≥ 10      | 0       | Pending |
| Shadow trades intercepted/logged | ≥ 5       | 0       | Pending |
| Hit rate (closed trades)         | 40%–75%   | N/A     | Pending |
| Kill switch triggers             | 0         | 0       | OK      |
| Health endpoint green (7 days)   | 7/7       | 0/7     | Running |
| Health endpoint green (14 days)  | 14/14     | 0/14    | Running |
| Day 7 shadow report              | Generated | Pending | Pending |
| Day 14 shadow report             | Generated | Pending | Pending |
| Admin journal audit              | Complete  | Pending | Pending |

---

### Day 7 Checkpoint — 2026-06-26

_To be filled on 2026-06-26._

```
Analyses submitted:
Shadow trades logged:
Closed trades:
Hit rate:
Kill switch triggers:
Health: all green / degraded
Notes:
```

---

### Day 14 Checkpoint — 2026-07-08

_To be filled on 2026-07-08._

```
Analyses submitted:
Shadow trades logged:
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
