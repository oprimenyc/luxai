# Phase B3 — Trade Idea Workbench Completion Report

**Date:** 2026-05-30  
**Tests:** 177/177 pass (zero regressions from B1)

---

## Files Built

### Backend — Options analytics (`apps/api/src/options/`)

| File                | Description                                                                                                                                                                                                         |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py`       | Package header                                                                                                                                                                                                      |
| `greeks.py`         | Black-Scholes Greeks engine. Delta, Gamma, Theta, Vega for calls and puts. IV via bisection. Pure Python, no scipy. Uses `math.erfc` for exact normal CDF. Edge cases: T≤0 (expiry today/past), IV=0, deep ITM/OTM. |
| `scorer.py`         | 5-factor Options Scorer 0–10. Weights: Liquidity 25%, Spread 20%, Delta 20%, IV 20%, DTE 15%. Tier-aware: Tiny tier DTE < 7 → score forced to 0.0 with violation flag.                                              |
| `tradier_client.py` | Async Tradier free-tier client. Chain fetch + quote fetch. Redis TTL: chain=60s, quote=30s. Retries × 2. HTTP 429 → `TradierRateLimitError`. Filters stale contracts (bid+ask+last = 0).                            |

### Backend — Workbench orchestration (`apps/api/src/workbench/`)

| File             | Description                                                                                                                                                                                                                                                 |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py`    | Package header                                                                                                                                                                                                                                              |
| `recommender.py` | `ContractRecommender` — enriches all contracts with Black-Scholes, scores them, returns Best Value / Best Probability / Spread Version. Budget override: returns cheapest + `budget_exceeded` flag. Debit spread builder: ATM long + 1–2 strikes OTM short. |
| `calendar.py`    | `MacroCalendarChecker` — static 2025 FOMC/CPI/NFP/PCE/GDP calendar (Fed-published dates). `fetch_earnings_date()` — Yahoo Finance public endpoint, 5s timeout, non-fatal.                                                                                   |
| `router.py`      | `POST /api/v1/workbench/analyze` — full 8-step pipeline. Auth required. Tradier credentials from settings only. Verdict: Accept / Caution / Reject with rationale. All Pydantic v2 models.                                                                  |

### Backend — Main (`apps/api/src/main.py`)

- Added `workbench_router` import and `app.include_router(workbench_router, prefix="/api/v1")`

### Frontend (`apps/web/`)

| File                                             | Description                                                                             |
| ------------------------------------------------ | --------------------------------------------------------------------------------------- |
| `app/(dashboard)/workbench/page.tsx`             | Server component with metadata                                                          |
| `app/(dashboard)/workbench/workbench-client.tsx` | Full client — form, score ring, contract cards, spread card, macro banner, verdict chip |
| `app/(dashboard)/layout.tsx`                     | Added Workbench nav item (ScanSearch icon, "beta" badge)                                |

### Package reference

| File                           | Description                                                                                                     |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `packages/options/__init__.py` | Documents that authoritative Python lives in `apps/api/src/options/` — extraction path for future uv workspaces |

---

## API Contract

```
POST /api/v1/workbench/analyze
Authorization: Bearer <supabase_jwt>
Content-Type: application/json

{
  "symbol": "AAPL",
  "direction": "bullish",
  "expiration": "2025-08-15",
  "budget_usd": 150,
  "account_size_usd": 3000,
  "source": "optional note"
}
```

Response: `WorkbenchResult` — see `router.py` for full schema. Key fields:

```json
{
  "symbol": "AAPL",
  "underlying_price": 213.50,
  "account_tier": "aggressive",
  "best_value": { "strike": 215, "score": 7.3, ... },
  "best_probability": { "strike": 210, "score": 6.8, ... },
  "spread_version": { "long_strike": 215, "short_strike": 220, "net_debit": 82.00, ... },
  "macro_events": [{ "name": "FOMC Rate Decision", "event_date": "2025-07-30", "risk_level": "high" }],
  "earnings_warning": false,
  "verdict": "accept",
  "verdict_rationale": "Score 7.3/10. Clean setup — within budget, no major macro conflicts, delta and liquidity on target."
}
```

---

## Architecture Decisions

### Greeks: pure Python, math.erfc

`scipy` not added (bundle cost, no other scipy use). Normal CDF implemented via `math.erfc(-x/√2)/2` which is exact to floating-point precision. Bisection IV converges in ≤50 iterations at 1e-6 tolerance.

### Tradier free tier

200 req/hr limit. Redis cache at 60s (chains) and 30s (quotes) prevents hitting the limit in normal use. If Redis is unavailable, the cache is skipped and requests go direct — acceptable degradation.

### Earnings: Yahoo Finance public endpoint

No API key. 5-second timeout. Failure is non-fatal — the workbench proceeds and `earnings_warning` is simply omitted. This is the correct behavior: better to miss the warning than to block the analysis.

### Macro events: static list

Fed/BLS/BEA publish FOMC/CPI/NFP dates 12–18 months in advance. The static list is more reliable than scraping Forex Factory (rate-limited, anti-bot). Update the list in `calendar.py` annually.

### Python package location

Core Python code lives in `apps/api/src/options/` and `apps/api/src/workbench/` — not in `packages/` — because `packages/` is the TypeScript workspace in this monorepo and Python code there is not on the API's import path. The `packages/options/__init__.py` documents this and serves as the extraction marker.

### Score formula: IV as proxy for IV Rank

IV Rank requires 52-week historical IV which is not available in the Tradier free tier. Current IV is used directly. At $1,000+ account size (per CLAUDE.md paid data threshold), upgrade to Unusual Whales or OPRA feed to get true IV Rank.

---

## Flags for Manual Review

1. **TRADIER_API_KEY must be set before live use.** Sandbox returns simulated data. A sandbox-mode notice is shown in the UI. Set `TRADIER_SANDBOX=false` in `.env` to switch to live chains once the account exceeds $1,000.

2. **Supabase migrations 002 and 003 must be applied.** The workbench router does not write to Supabase directly, but the B1 safety chain (kill switch, idempotency) requires those tables. Apply via Supabase dashboard or `supabase db push`.

3. **No authentication bypass in the form.** The `fetch` call uses `credentials: "include"` for cookie-based auth. If the frontend auth cookie is not set, the API returns 401. Wire the Supabase session before testing.

4. **Yahoo Finance URL stability.** The `query2.finance.yahoo.com` endpoint is undocumented. If it breaks, `fetch_earnings_date()` returns `None` and the workbench continues without an earnings warning. No code change needed — just a data gap.

5. **Max profit for single-leg calls is illustrative.** Theoretical max profit for a long call is unbounded. The displayed value uses `underlying_price × 2 - strike - cost` as a heuristic double. This is clearly labelled as illustrative in `risk_reward_note`.

6. **`packages/workbench/shadow_report.py` untouched.** Per the user constraint: shadow mode files were not modified.

---

## Phase B3 Checklist (CLAUDE.md)

- [x] Tip intake form: symbol, direction, expiration, budget
- [x] Options chain fetch via Tradier free tier
- [x] Greeks calculated internally (Black-Scholes, no external purchase)
- [x] Budget-aware alternatives: always return 3 tiers (Best Value, Best Probability, Spread)
- [x] Debit spread auto-builder
- [x] Options Score /10 (5-factor weighted, one decimal precision)
- [x] Macro calendar warning (FOMC, CPI, NFP, PCE, GDP; earnings via Yahoo Finance)
- [x] Verdict engine: Accept / Caution / Reject with rationale

**Ready for Phase B2 — Options Intelligence Layer.**  
Next gate: Shadow Mode 2-week run before any live trading discussion.
