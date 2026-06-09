# Daily Routine — LuxAI OS Shadow Run

---

## MARKET DAYS (Mon–Fri)

### Morning (5 minutes, optional but counts toward gate):

1. Open the app and check the shadow mode banner — it should show "Shadow Mode Active"
2. If you have a trade idea from news or research: use the workbench — enter symbol, direction, expiry, budget. Takes 30 seconds.
3. Check if the shadow monitor closed any trades overnight — look at the P&L summary in the banner

### That's it. The scanner runs at 9:31 AM without you.

---

## OPTIONAL — When You Have a Specific Tip:

1. Go to the Trade Idea Workbench
2. Enter: symbol, bullish/bearish, expiration date (7–21 days out), budget ($5 max for Tiny tier)
3. Review the verdict and score
4. If verdict is "accept" or "caution", the analysis is logged automatically
5. You can then submit it as an order — it will be intercepted as a shadow trade

---

## WEEKLY (Saturdays — 15 minutes):

1. Review the shadow P&L summary: total trades, hit rate, P&L
2. Check that the auto-scanner is producing signals (at least 1–2 shadow trades per week)
3. Note any symbols that keep triggering — that's signal quality data for the journal

---

## DAY 7 AND DAY 14 (Required for gate):

1. Run the shadow report generator (if wired) or manually review:
   - Total shadow trades logged
   - Hit rate (must be 40–75%)
   - Any kill switch events (must be zero)
   - Health endpoint status
2. Write a brief journal note: "Signal quality looks X, hit rate is Y%, no anomalies / anomaly noted"
3. On Day 14: complete the full journal audit before any live trading discussion

---

## WHAT RUNS WITHOUT YOU:

- **Auto-scanner** — 9:31 AM ET every market day, scans SPY/QQQ/TSLA/NVDA/AAPL/META/AMZN, creates up to 3 shadow trade entries if any option scores >= 7.0/10
- **Shadow trade monitor** — every 60 seconds, closes any trade that hits -5% stop-loss or +10% take-profit
- **P&L aggregation** — runs automatically every time a trade closes
- **Shadow mode enforcement** — all order submissions are intercepted until admin manually deactivates shadow mode

## WHAT NEEDS YOUR INPUT:

- Workbench analyses (10 required over 14 days — roughly 1 per weekday)
- Day 7 and Day 14 shadow reports
- Journal audit on Day 14
- Admin gate confirmation before any live trading discussion
- Deploying new code when changes are made
