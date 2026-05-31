# CLAUDE.md — LuxAI OS / .fylr

## How Claude Code Should Use This File

This file is the single source of truth for all autonomous engineering decisions made in this repository. Every session, Claude Code must read this file before writing any code, proposing any architecture, or responding to any task. The rules, constraints, and priorities defined here override any default Claude behavior, any inferred convention from the codebase, and any instruction that conflicts with them. When in doubt, return to this file. Do not drift.

---

## Project Identity

| Field     | Value                                                                                                       |
| --------- | ----------------------------------------------------------------------------------------------------------- |
| Name      | LuxAI OS / .fylr                                                                                            |
| Type      | AI-assisted options trading platform                                                                        |
| Account   | $100 starting capital, scaling to $10,000                                                                   |
| Mode      | Paper trading ONLY — live trading locked behind shadow gates                                                |
| Core Goal | Trade Idea Workbench: take any tip → return affordable, risk-scored, budget-adjusted options recommendation |

---

## Tech Stack

| Layer          | Technology                                                    |
| -------------- | ------------------------------------------------------------- |
| Frontend       | Next.js 15 App Router, Tailwind CSS, shadcn/ui, Framer Motion |
| Backend        | FastAPI, async-first, Pydantic v2, LangGraph                  |
| Database       | Supabase PostgreSQL + pgvector, RLS always enforced           |
| Cache / Locks  | Upstash Redis (SETNX idempotency + distributed locks)         |
| Broker (paper) | Alpaca — current paper trading adapter                        |
| Broker (live)  | Tastytrade — target live broker (NOT wired yet)               |
| Options Data   | Tradier API free tier                                         |
| Frontend Host  | Cloudflare Pages                                              |
| Backend Host   | Railway                                                       |
| Auth           | Supabase Auth                                                 |
| Storage        | Cloudflare R2                                                 |

---

## Broker Architecture

### Current: Alpaca (paper mode only)

All order submission today routes through the Alpaca paper adapter. The engine hard-locks `ExecutionMode.PAPER` at construction — passing any other mode raises `ValueError`. This cannot be relaxed without explicit written confirmation that shadow gates have passed.

### Target live broker: Tastytrade

When shadow gates pass and admin confirms, the live adapter will be Tastytrade.

| Detail     | Value                                                              |
| ---------- | ------------------------------------------------------------------ |
| API docs   | https://developer.tastytrade.com                                   |
| Python SDK | `tastytrade` (async-native, `pip install tastytrade`)              |
| Auth model | Session-based — obtain session token, refresh before expiry        |
| Sandbox    | Available — use `api.cert.tastytrade.com` for all pre-live testing |
| Options    | Full options chain + order submission natively supported           |

**Integration constraints (enforced until shadow gates pass):**

- Do NOT install `tastytrade` as a dependency yet — it signals live-trading intent
- Do NOT write any `TastytradeAdapter` class until B1 + B3 + B2 are complete and shadow has run two weeks
- Do NOT store Tastytrade credentials in `.env.example` until the adapter is being actively built
- Any code that imports `tastytrade` is automatically a security review trigger

When the time comes, the adapter must slot into `packages/broker/` behind the same abstract interface as the Alpaca adapter so the engine layer never knows which broker it is talking to.

---

## Absolute Rules

These rules are non-negotiable. No exception is valid without explicit, written user confirmation in the session.

1. **No placeholder code.** No mock data unless the file or function is explicitly annotated `# MOCK — replace before B3`.
2. **No toy architecture.** No shortcuts that create future debt. Every design decision must survive a production audit.
3. **No live trading enablement. Ever.** Until shadow gate criteria are confirmed, no code path may submit a real order. Period.
4. **Kill switch MUST write to Redis AND Supabase.** A kill switch that lives only in RAM is not a kill switch. Both writes must succeed or the kill is rejected.
5. **Every `asyncio.create_task()` must be flagged and bounded.** Add a comment with the task name and its cancellation/timeout strategy. No fire-and-forget.
6. **Every new file must include three annotations in its module docstring:** folder path, security note, scale note.
7. **Position sizing hard cap:** max 5% of account per trade. Under $500 accounts: max $5 risk, max 1 contract.
8. **No new agents or strategies during Phase B1.** B1 is safety infrastructure only. Feature work waits.
9. **No paid data subscriptions under $1,000 account size.** All data sources must be free-tier until the account crosses $1,000.
10. **Greeks (Delta, Gamma, Theta, Vega) are always calculated internally** via Black-Scholes. They are never purchased as a data product.
11. **Do not use Cloudflare Workers for persistent Python processes.** Workers are stateless edge functions. All persistent async logic runs on Railway.

---

## Current Build Phase

### COMPLETE: Phase B1 — Broker Safety & Durable Risk Guards

177 tests pass. All five items verified. Ready for B3.

- [x] **Durable idempotency:** Redis SETNX + Supabase audit ledger — every order attempt gets a UUID, checked before submission
- [x] **Persistent kill switch:** survives service restart; cleared only by admin action, never auto-reset
- [x] **Position close lock:** Redis distributed lock prevents duplicate exit attempts on the same position
- [x] **Queue lag monitor:** detects when the risk engine is falling behind the order queue; alerts and halts
- [x] **Account constraint enforcer:** hard limits enforced by tier at the engine level, not the UI level

### COMPLETE: Phase B3 — Trade Idea Workbench

225 tests pass (177 original + 48 new). All checklist items verified.
Supabase MCP connected. All 4 migrations applied. Shadow mode wired end-to-end.

- [x] Tip intake form: symbol, direction, contract type, expiry, budget
- [x] Options chain fetch via Tradier free tier
- [x] Greeks calculated internally (Black-Scholes, no external purchase)
- [x] Budget-aware alternatives: always return 3 tiers
- [x] Debit spread auto-builder
- [x] Options Score /10 (see scoring weights below)
- [x] Macro calendar warning (FOMC, CPI, earnings conflicts)
- [x] Verdict engine: Accept / Caution / Reject with rationale
- [x] Supabase wiring: all B1 services use real client (service role key)
- [x] JWT auth: real Supabase JWT validation, get_admin_user() added
- [x] Health endpoint: GET /api/v1/health with all service pings
- [x] Shadow P&L aggregation: aggregate_pnl() + close_shadow_trade() wired
- [x] Shadow trade monitor: background task (60s poll, -5%/+10% exit rules)
- [x] Workbench analyses persisted to Supabase for history

### ACTIVE: 2-Week Shadow Run

Shadow mode is the gate to live trading. Run for 14 consecutive days before
any live trading discussion is appropriate.

Gate criteria:

- ≥ 10 workbench analyses submitted
- ≥ 5 shadow trades intercepted and logged
- Hit rate between 40% and 75% across closed trades
- No kill switch triggers (system_halts table empty)
- Health endpoint green across both weeks
- Shadow report generated at day 7 and day 14
- Journal audit completed by admin

### THEN: Phase B2 — Options Intelligence Layer

### THEN: Phase B4 — Whale / Flow Engine

### GATE: Shadow Mode — 2-week minimum run before any live trading discussion

---

## Account Tier Rules (Hard Limits)

These limits are enforced at the engine level. The UI may display them, but the backend is the enforcer. UI-only enforcement is a security failure.

### Tiny Tier — $0 to $500

| Rule           | Value                                               |
| -------------- | --------------------------------------------------- |
| Max risk/trade | $5 or 3% of account (lower wins)                    |
| Max contracts  | 1                                                   |
| Min DTE        | 7 days                                              |
| Prohibited     | 0DTE, earnings plays, naked options, averaging down |
| Preferred      | Debit spreads, single cheap calls/puts              |

### Growth Tier — $500 to $2,500

| Rule           | Value                             |
| -------------- | --------------------------------- |
| Max risk/trade | $25 or 5% of account (lower wins) |
| Max contracts  | 2                                 |
| Min DTE        | 5 days                            |

### Aggressive Tier — $2,500 to $10,000

| Rule           | Value                                                |
| -------------- | ---------------------------------------------------- |
| Max risk/trade | 5% hard cap, no exceptions                           |
| Max contracts  | Per position sizing calculation                      |
| Strategy types | Broader set allowed                                  |
| Validation     | Shadow mode still required for any new strategy type |

---

## Trade Idea Workbench — Recommender Logic

When the workbench analyzes any tip, it must always return **three alternatives**, never fewer:

| Alternative      | Definition                                                                 |
| ---------------- | -------------------------------------------------------------------------- |
| Best Value       | Highest Options Score within the stated budget                             |
| Best Probability | Highest delta (best odds of expiring ITM); may slightly exceed budget      |
| Spread Version   | Debit spread capping net debit to approximately 50% of the single-leg cost |

### Options Score Weights (total = 100%)

| Factor                          | Weight |
| ------------------------------- | ------ |
| Liquidity — Open Interest > 500 | 25%    |
| Spread < 10% of mid price       | 20%    |
| Delta in 0.25–0.55 range        | 20%    |
| IV Rank < 65%                   | 20%    |
| DTE between 7 and 21 days       | 15%    |

The Options Score is a number from 0 to 10. Display it with one decimal place. Never round to a whole number — precision signals legitimacy.

---

## Data Sources by Account Tier

### Free Tier — $0 to $1,000 (current operating tier)

| Category       | Sources                                        |
| -------------- | ---------------------------------------------- |
| Price / Charts | Alpaca market data, TradingView                |
| Options chains | Tradier free tier, CBOE delayed data           |
| News           | Benzinga, Yahoo Finance, MarketWatch           |
| Calendar       | Forex Factory, Investing.com                   |
| Whale data     | SEC EDGAR, Capitol Trades, WhaleWisdom (slow)  |
| Greeks         | Always calculated internally — never purchased |

### Paid Consideration Thresholds (do not act on these until account reaches threshold)

| Account Size | Consideration             |
| ------------ | ------------------------- |
| $1,000+      | Unusual Whales basic plan |
| $5,000+      | OPRA-grade options feed   |

---

## Brand & UI Standards

The brand is `.fylr` — dark luxury fintech. Every UI decision must be consistent with this identity. If it looks like a generic SaaS dashboard, it is wrong.

### Visual References

- Linear — information density, monospace precision
- Palantir — data sovereignty aesthetic, no-nonsense layout
- Arc Browser — opinionated, self-assured, not conventional

### Color & Typography

| Element    | Standard                                          |
| ---------- | ------------------------------------------------- |
| Background | Near-black — `#0A0A0B` or equivalent              |
| Accent     | Single high-contrast color — not neon, not pastel |
| Typography | Distinctive — not Inter, not Roboto, not Arial    |
| Icons      | Lucide, outline only, 1.5–2px stroke weight       |

### Interaction & Layout

| Rule                  | Standard                                                   |
| --------------------- | ---------------------------------------------------------- |
| Animations            | Framer Motion — cinematic and purposeful, never decorative |
| Touch targets         | 44px minimum                                               |
| Mobile navigation     | Bottom nav; full-screen drawers for secondary content      |
| Buttons               | Free-floating text interactions — no chunky pill buttons   |
| Emojis                | Never. Not in UI, not in copy, not in logs.                |
| Generic SaaS patterns | Never. Question every component against the brand.         |

---

## Code Quality Standards

Every file, every PR, every change must meet these standards. There are no exceptions for "quick fixes" or "temporary solutions."

- **TypeScript strict mode** on all frontend code — no `any`, no suppressed errors
- **Pydantic v2 models** on every FastAPI route for both input and output
- **Migration-safe DB changes** — every migration file includes a rollback strategy in comments
- **Dependency justification** — every new package requires a one-line comment: why it was added and its approximate bundle/footprint impact
- **No duplicated logic** — if it appears twice, it belongs in `packages/shared`
- **No fire-and-forget async** — every background task has a bounded queue and documented cancellation path
- **RLS enforced** — every Supabase table has Row Level Security policies; never bypass with service role key in user-facing code paths
- **No silent failures** — every error must surface to the user or to a log sink with sufficient context to debug
- **Loading states** — every async UI action has a loading state; spinners are not optional

---

## Shadow Mode — Definition and Rules

Shadow mode is not a feature. It is the launch permission system.

**Definition:** The system runs fully — signals process, risk evaluates, journal writes — but no order is ever submitted to the broker. Every order submission is intercepted, nullified, and logged as `SHADOW_MODE`.

### Shadow Mode Requirements

- Shadow P&L is tracked separately from live P&L; never commingled
- A persistent UI banner is displayed at all times while shadow mode is active — it cannot be dismissed by the user
- Shadow mode is the **default state for all new accounts**
- Shadow mode can only be exited by an admin action after a two-week continuous run and a manual journal audit
- Any code path that could bypass shadow mode is a critical security defect

### Path to Discussing Live Capital

1. Shadow mode runs for a minimum of two consecutive weeks
2. Journal audit is performed: review signal quality, risk adherence, P&L realism
3. Admin explicitly confirms shadow gate passed
4. Only then is a live trading discussion appropriate — no code changes before confirmation

---

## What Not to Build Right Now

Do not propose, prototype, or begin any of the following until explicitly instructed after B1 and B3 are complete:

- Additional AI agents of any kind
- Multi-provider LLM routing
- Live broker connection
- Paid data subscriptions
- Autonomous trade execution of any kind
- Backtesting engine
- Voice interface
- Multi-tenant architecture
- Social or signal-sharing features

If a task request would require any of the above, stop and flag it before proceeding.

---

## Folder Structure

```
luxai-os/
├── apps/
│   ├── web/                  # Next.js 15 frontend (Cloudflare Pages)
│   └── api/                  # FastAPI backend (Railway)
├── packages/
│   ├── options/              # Black-Scholes Greeks engine, IV calc, Options Score
│   ├── risk/                 # Position sizing, kill switch, idempotency layer
│   ├── broker/               # Alpaca abstraction layer (paper mode enforced)
│   ├── workbench/            # Trade Idea Workbench orchestration logic
│   └── shared/               # Types, constants, utilities shared across packages
├── supabase/
│   └── migrations/           # All DB migrations — never run raw SQL outside this folder
└── CLAUDE.md                 # This file — read before every session
```

### New File Checklist

Every new file must include the following in its module docstring or top-level comment block:

```python
# Path: packages/risk/kill_switch.py
# Security: Admin-only clear path. Redis + Supabase dual-write required.
# Scale: Designed for single-tenant; Redis key namespaced by account_id for future multi-tenant.
```

---

## Session Startup Checklist

Before writing any code in a new session, Claude Code must confirm:

1. What is the current build phase? (Should be B1 until all B1 tasks are checked off.)
2. Does the requested task fall within the current phase's scope?
3. Does the task touch the kill switch, order submission, or position sizing? If yes, apply double scrutiny.
4. Does the task require a new dependency? If yes, document justification before adding.
5. Does the task touch any Supabase table? If yes, confirm RLS is in place or being added.

If any answer is unclear, ask before proceeding.
