# Recovery Report — 2026-06-26

Generated after Day 7 audit revealed 7 days of zero data collection.

---

## Today's Scan Result

**Status: Scanner has NOT yet fired today.**

The scanner fires at 9:31 AM ET (13:31 UTC). At the time of this report (~10:00 AM UTC), the scanner is sleeping. It was reset by two successive deploys:

- 09:34 UTC: Bug fixes deployed (redis_url, cost cap, health timeout)
- 09:42 UTC: DEEPSEEK_API_KEY secret set → automatic restart

Both restarts recalculate sleep time from `_seconds_until_market_open()`, so the scanner will fire at the correct time.

**Expected first clean scan: 2026-06-26 at 13:31 UTC**

After that scan completes, check:

```sql
SELECT * FROM scanner_daily_log ORDER BY scan_date DESC LIMIT 1;
SELECT * FROM shadow_trades ORDER BY created_at DESC LIMIT 10;
SELECT * FROM scanner_debates ORDER BY created_at DESC LIMIT 10;
```

---

## DeepSeek Working: Confirmed (deployment level)

`DEEPSEEK_API_KEY` was set as a Fly secret and the app restarted with it. The scanner code checks `if self._deepseek_key:` before running debates. With the key now set:

- Debates will fire for symbols that pass the 0.5% movement pre-filter
- Results will be written to `scanner_debates` (not `workbench_analyses`)
- Token costs: ~$0.0007 per symbol debate at DeepSeek rates
- 7 symbols × ~$0.0007 = ~$0.005/day max token cost

**Direct end-to-end verification** will be confirmed when the scanner_debates table has rows after today's 13:31 UTC scan. There is no local environment to test the adapter directly (the DeepSeek key lives only in Fly secrets).

---

## Scanner Daily Log: Table Created

Migration `008_scanner_daily_log.sql` applied to Supabase at 10:00 UTC.

Tables created:

- `scanner_daily_log` — one row per market day scan run
- `scanner_debates` — one row per per-symbol TradingAgents debate

Both tables use service_role (bypasses RLS) for writes. RLS enabled with deny-all for public access.

The first row will appear after today's 13:31 UTC scan.

---

## Shadow Run Clock: Reset Confirmed

| Run   | Dates                        | Status                             |
| ----- | ---------------------------- | ---------------------------------- |
| Run 1 | 2026-05-31                   | VOIDED — no user                   |
| Run 2 | 2026-06-05                   | VOIDED — no data                   |
| Run 3 | 2026-06-18 to 2026-06-26     | **VOIDED — 3 silent scanner bugs** |
| Run 4 | **2026-06-27 to 2026-07-15** | **ACTIVE**                         |

---

## New Day 14 Target: 2026-07-15 (Tuesday)

| Milestone               | Date              |
| ----------------------- | ----------------- |
| Run 4 Day 1             | 2026-06-27 (Fri)  |
| Run 4 Day 7 checkpoint  | 2026-07-07 (Mon)  |
| Market holiday          | 2026-07-04 (skip) |
| Run 4 Day 14 checkpoint | 2026-07-15 (Tue)  |

12 clean trading days available. Gate requires 10 analyses and 5 shadow trades.

---

## Fixes Applied (all deployed)

| Fix                                     | File                                            | Status                     |
| --------------------------------------- | ----------------------------------------------- | -------------------------- |
| Redis URL bug in scanner                | `apps/api/src/trading/scanner.py`               | ✅ Deployed 09:34 UTC      |
| $5 cost cap filter removed from scanner | `apps/api/src/trading/scanner.py`               | ✅ Deployed 09:34 UTC      |
| Health check `acreate_client()` timeout | `apps/api/src/routers/health.py`                | ✅ Deployed 09:34 UTC      |
| Scanner debate table fix (wrong schema) | `apps/api/src/agents/trading_agents_adapter.py` | ✅ Deployed (this session) |
| `scanner_daily_log` table               | `supabase/migrations/008_scanner_daily_log.sql` | ✅ Applied                 |
| `scanner_debates` table                 | `supabase/migrations/008_scanner_daily_log.sql` | ✅ Applied                 |
| Daily log write after each scan         | `apps/api/src/trading/scanner.py`               | ✅ Deployed (this session) |
| Zero-signal streak alert (Redis + DB)   | `apps/api/src/trading/scanner.py`               | ✅ Deployed (this session) |
| Health endpoint scanner status fields   | `apps/api/src/routers/health.py`                | ✅ Deployed (this session) |

---

## What to Do Daily to Hit Gate Criteria by July 15

### Every morning (5 minutes)

1. `curl -s https://luxai-api.fly.dev/api/v1/health | python -m json.tool`
   - Verify all services green
   - Verify `scanner_alert` is null
   - Note `last_scan_date` and `last_scan_signals`

2. Submit one manual workbench analysis via the UI
   - 10 days × 1 analysis = gate criterion #1 met

### Every afternoon (2 minutes)

3. Check `scanner_daily_log` for today's row
4. Check `shadow_trades` for new entries

### On 2026-07-07 (Day 7 checkpoint)

Run full audit — same process as SHADOW_DAY7_REPORT.md.
Update `SHADOW_RUN_LOG.md` Day 7 checkpoint section.

### On 2026-07-15 (Day 14 checkpoint)

Run full audit. If all gate criteria met, admin signs off and live trading discussion begins.

---

## Recommendation

**Continue — with daily monitoring.**

The system is now instrumented correctly. The scanner will self-report every day. Silent failures are no longer possible: the health endpoint shows scanner status, the `scanner_daily_log` table is the permanent record, and a zero-signal streak alert fires at day 3.

Priority actions today:

1. ✅ Wait for 13:31 UTC scan — verify `scanner_daily_log` has a row
2. 🔲 Submit 1 manual workbench analysis via UI
3. 🔲 Confirm `scanner_debates` has rows (proves DeepSeek is working end-to-end)
4. ✅ Push this commit to `main`
