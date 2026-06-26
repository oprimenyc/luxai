# LuxAI OS — Daily Shadow Run Routine

For use during the shadow run (Run 4: 2026-06-27 to 2026-07-15).

---

## Every Morning (9:15–9:30 AM ET, before market open)

### 1. Health check (30 seconds)

```bash
curl -s https://luxai-api.fly.dev/api/v1/health | python -m json.tool
```

Confirm:

- `supabase`, `redis`, `tradier`, `alpaca` all `"ok"`
- `shadow_mode: true`
- `kill_switch: false`
- `scanner_alert: null` (if non-null, investigate immediately)

If any service shows `"error"`, check Fly logs before market open:

```bash
flyctl logs --app luxai-api --no-tail 2>&1 | grep -v "GET /api" | tail -50
```

---

### 2. Morning tip validation (5–10 minutes)

Submit at least **one manual workbench analysis per day** until 10 total are logged.
This ensures the gate criterion is met even if scanner signals are scarce.

**How to submit:**

1. Open the web UI at https://luxai-web-snowy.vercel.app
2. Navigate to Trade Idea Workbench
3. Enter a tip:
   - Symbol: any of SPY / QQQ / NVDA / TSLA / AAPL
   - Direction: bullish or bearish (your call based on pre-market)
   - Budget: $15 (shadow testing limit)
   - Source: manual
4. Submit — the workbench will fetch the chain, score it, and return 3 alternatives
5. Confirm the row appears in Supabase:

```sql
SELECT id, symbol, direction, verdict, analyzed_at
FROM workbench_analyses
ORDER BY analyzed_at DESC LIMIT 5;
```

**Target: 10 total by 2026-07-07 (Day 7 checkpoint)**

---

## After Market Close (4:15–4:30 PM ET)

### 3. Check today's scanner run

After 9:31 AM ET the scanner fires. By end of day, `scanner_daily_log` should have a row for today.

```sql
SELECT scan_date, symbols_scanned, signals_generated, debates_completed,
       deepseek_available, zero_signal_streak, scanner_alert
FROM scanner_daily_log
ORDER BY scan_date DESC LIMIT 7;
```

Expected per day:

- `symbols_scanned`: 7 (or fewer if signal cap hit)
- `signals_generated`: 0–3
- `debates_completed`: > 0 if DeepSeek key is set
- `scanner_alert`: null (healthy)

Also check shadow trades:

```sql
SELECT symbol, side, status, intended_entry_price, created_at, metadata
FROM shadow_trades
ORDER BY created_at DESC LIMIT 10;
```

### 4. Check scanner debates (if DeepSeek enabled)

```sql
SELECT scan_date, symbol, verdict, confidence, token_input
FROM scanner_debates
ORDER BY created_at DESC LIMIT 14;
```

---

## Weekly (Monday morning)

### 5. Gate criteria review

Run the full gate status query:

```sql
SELECT
  (SELECT COUNT(*) FROM workbench_analyses) AS analyses,
  (SELECT COUNT(*) FROM shadow_trades) AS shadow_trades,
  (SELECT COUNT(*) FROM shadow_trades WHERE status = 'closed') AS closed_trades,
  (SELECT COUNT(*) FROM system_halts) AS halts,
  (SELECT COUNT(*) FROM scanner_daily_log) AS scan_days;
```

Update `SHADOW_RUN_LOG.md` with current counts.

---

## If Zero Signals for 3+ Days

The health endpoint will show `scanner_alert` with the streak count.

**Investigate:**

1. Check `scanner_daily_log.errors` column for the affected dates
2. Check Tradier sandbox connectivity: `curl https://sandbox.tradier.com/v1/markets/clock -H "Authorization: Bearer $TRADIER_API_KEY"`
3. Check yfinance data: are prices being fetched? (`auto_scanner_no_movement_data` in Fly logs)
4. Check if `deepseek_available` is `false` — if so, confirm `DEEPSEEK_API_KEY` is still set

**Quick log check:**

```bash
flyctl logs --app luxai-api --no-tail 2>&1 | grep "auto_scanner" | tail -30
```

---

## Fly Log Reference

Healthy scanner sequence (one per market day at ~13:31 UTC):

```
auto_scanner_loop_started
auto_scanner_sleeping  (seconds until 9:31 AM ET)
... [next day] ...
auto_scanner_starting
auto_scanner_symbol_skipped  (if movement < 0.5%)
auto_scanner_agent_verdict   (if DeepSeek key set)
auto_scanner_signal_created  OR auto_scanner_no_qualifying_contract
auto_scanner_complete
auto_scanner_daily_log_written
auto_scanner_sleeping  (23h until next day)
```

---

## Gate Criteria Summary

All must be met by **2026-07-15**:

| Criterion                | How to meet it                                   |
| ------------------------ | ------------------------------------------------ |
| ≥ 10 workbench analyses  | 1 manual tip per morning (10 days)               |
| ≥ 5 shadow trades logged | Auto-scanner fires daily; should produce 1–3/day |
| 40–75% hit rate          | Requires some trades to close with P&L           |
| 0 kill switch triggers   | Automatic — just don't force-set the kill switch |
| Health green throughout  | Auto-monitor — check daily health curl           |
| Day 7 report (Jul 7)     | Run audit, update SHADOW_RUN_LOG.md              |
| Day 14 report (Jul 15)   | Run audit, update SHADOW_RUN_LOG.md              |
| Admin journal audit      | Manual review of signal quality                  |
