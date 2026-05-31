# Shadow Mode Completion Report

**Generated:** 2026-05-30
**Phase:** B1 — Shadow Mode System + Documentation

---

## Test Results

```
55 passed in 0.22s
```

All pre-existing tests pass unchanged. No regressions introduced.

Test files covered:

- `tests/test_engine_safety.py` — 17 tests (mode enforcement, halt, idempotency, degraded risk)
- `tests/test_portfolio.py` — 13 tests (fill, PnL, cost basis, mark-to-market)
- `tests/test_risk_engines.py` — 25 tests (stop-loss, take-profit, trailing stop, position sizer, daily loss guard)

---

## Files Built

### Task 1 — Shadow Mode System

| File                                      | Status   | Description                                                      |
| ----------------------------------------- | -------- | ---------------------------------------------------------------- |
| `supabase/migrations/001_shadow_mode.sql` | Created  | Three tables with RLS, indexes, and rollback instructions        |
| `apps/api/src/trading/shadow.py`          | Created  | `ShadowModeService` — dual-write Redis+Supabase, fail-safe reads |
| `apps/api/src/trading/router.py`          | Modified | Shadow interception on order submission + 3 new endpoints        |
| `apps/web/components/ShadowBanner.tsx`    | Created  | Persistent amber banner with P&L, hit rate, day counter          |
| `apps/web/app/(dashboard)/layout.tsx`     | Modified | `<ShadowBanner />` inserted between topbar and main content      |
| `packages/workbench/__init__.py`          | Created  | Python package marker                                            |
| `packages/workbench/shadow_report.py`     | Created  | CLI markdown report generator                                    |

### Task 2 — README.md

| File        | Status  | Description                               |
| ----------- | ------- | ----------------------------------------- |
| `README.md` | Created | Full project documentation (1,100+ lines) |

### Task 3 — SOP.md

| File     | Status  | Description                             |
| -------- | ------- | --------------------------------------- |
| `SOP.md` | Created | Full daily trader workflow (700+ lines) |

---

## Architecture Summary

### Shadow Mode Interception Flow

```
POST /api/v1/trading/orders
        │
        ▼
[get_shadow_service() dependency]
        │
        ▼
shadow.is_active(user_id)
        │
   ┌────▼────────────────┐
   │  active?            │
   │  YES                │  NO
   └────┬────────────────┘
        │                        │
        ▼                        ▼
get_quote() for entry price   engine.submit(request)
        │                        │
        ▼                        ▼
shadow.record_shadow_trade()  broker.submit_order()
        │
        ▼
return SHADOW_ACKNOWLEDGED
  {shadow_mode: true, shadow_trade_id: "..."}
```

### Fail-Safe Invariants

| Scenario                                        | Behavior                                                |
| ----------------------------------------------- | ------------------------------------------------------- |
| Redis unreachable on `is_active()`              | Assume shadow ACTIVE — no order reaches broker          |
| Supabase unreachable on `is_active()`           | Assume shadow ACTIVE — no order reaches broker          |
| `activate()` Redis write fails                  | Raise error — state unchanged (safe)                    |
| `activate()` Supabase write fails               | Rollback Redis — raise error (safe)                     |
| `deactivate()` Supabase write fails             | Abort — shadow stays ACTIVE (safe)                      |
| `deactivate()` Redis write fails after Supabase | Log warning — next `is_active()` re-syncs from Supabase |

### New API Endpoints

| Method   | Path                                | Auth  | Description                      |
| -------- | ----------------------------------- | ----- | -------------------------------- |
| `GET`    | `/api/v1/trading/shadow-status`     | User  | Shadow summary for UI banner     |
| `POST`   | `/api/v1/trading/shadow/activate`   | User  | Activate shadow mode             |
| `DELETE` | `/api/v1/trading/shadow/deactivate` | Admin | Clear shadow gate (writes audit) |

### Supabase Tables Created

| Table                | RLS                      | Purpose                                    |
| -------------------- | ------------------------ | ------------------------------------------ |
| `shadow_mode_config` | Users read own row only  | Per-user shadow active/inactive state      |
| `shadow_trades`      | Users read own rows only | Every intercepted order logged here        |
| `shadow_pnl`         | Users read own rows only | Aggregated P&L (all-time + period buckets) |

All tables: no user writes permitted. Service role only for all inserts/updates.

### Shadow Banner

- Client-side React component
- Polls `/api/v1/trading/shadow-status` every 60 seconds
- Fails safe: shows banner if API is unreachable (no dismiss option)
- Shows: shadow mode pulse indicator, total shadow P&L, hit rate, day counter
- Framer Motion cinematic entrance from top
- Amber `#0f0c00` background — intentionally not neon, consistent with .fylr brand
- Inserted in `(dashboard)/layout.tsx` between topbar and main content (all dashboard pages)

### Shadow Report Generator

Run from repo root:

```bash
python packages/workbench/shadow_report.py generate
python packages/workbench/shadow_report.py generate --days 14
python packages/workbench/shadow_report.py generate --user-id <uuid> --output gate_report.md
```

Sections: overview, signal summary, shadow P&L, top symbols, best call, worst miss, gate checklist.

---

## Items Requiring Manual Review

### 1. `TRADIER_API_KEY` missing from `.env.example`

`settings.py` already has `tradier_api_key: str = ""` and `tradier_sandbox: bool = True`, but `.env.example` does not document these variables. Add before Phase B3:

```
# ── Tradier (Options Data) ────────────────────────────────────────────────────
TRADIER_API_KEY=
TRADIER_SANDBOX=true
```

### 2. `shadow_pnl` table is not auto-populated

The `shadow_pnl` table is read by the banner and report generator, but nothing writes to it yet. P&L aggregation requires either:

- A Supabase database function / trigger that aggregates `shadow_trades` on close
- Or a scheduled job that runs nightly

This is a Phase B3 item. Until then, the banner will show `$0.00` and the report will show `0 closed trades` until wired up.

### 3. `shadow_trades.status` → `closed` transition not implemented

Shadow trades are written as `status: open` but there is no mechanism yet to close them when the underlying moves to a theoretical exit. This requires either:

- A price monitoring job that checks open shadow trades against stop-loss / take-profit levels
- Or manual entry via the admin SQL editor for now

Flag for Phase B3 workbench integration.

### 4. `AuthenticatedUser` type change in router

The `submit_order` endpoint was changed from `user_id: str` to `user: AuthenticatedUser`. The other endpoints in `router.py` still use `user_id: str = Depends(get_current_user)` — this was a pre-existing inconsistency (FastAPI injects `AuthenticatedUser` regardless of the `str` annotation). All other endpoints work correctly because they don't use the `user_id` value directly. Standardise to `AuthenticatedUser` across all endpoints in a future cleanup pass.

### 5. Redis client created per-request in `get_shadow_service()`

The current `get_shadow_service()` dependency creates a new `redis.asyncio` client on every request. This is correct for correctness but suboptimal for connection efficiency. In production, wire this to an application-lifespan Redis pool (e.g., in `main.py` lifespan context) and inject it as a singleton. Acceptable for current B1 scope.

---

## CLAUDE.md Phase B1 Checklist Progress

| Task                                                 | Status                                                                                                   |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Durable idempotency (Redis SETNX + Supabase audit)   | Deferred — existing in-memory idempotency left intact; Redis+Supabase version is blocked on B1 full pass |
| Persistent kill switch (Redis + Supabase dual-write) | Deferred — shadow mode covers this for order interception; full halt persistence in next B1 pass         |
| Position close lock (Redis distributed lock)         | Deferred — next B1 pass                                                                                  |
| Queue lag monitor                                    | Deferred — next B1 pass                                                                                  |
| Account constraint enforcer                          | Deferred — next B1 pass                                                                                  |
| **Shadow mode system**                               | **COMPLETE**                                                                                             |
| **Shadow mode UI banner**                            | **COMPLETE**                                                                                             |
| **Shadow mode report generator**                     | **COMPLETE**                                                                                             |
| **Supabase migration: shadow tables**                | **COMPLETE**                                                                                             |

Note: The user's current request focused on shadow mode as a standalone deliverable. The remaining B1 tasks (idempotency, kill switch, position lock, queue monitor, account enforcer) are ready to build in the next session — all infrastructure patterns established here apply directly.

---

## Next Session

Complete remaining B1 tasks:

1. Redis SETNX idempotency service (`apps/api/src/trading/idempotency.py`)
2. Persistent kill switch dual-write (`apps/api/src/trading/kill_switch.py`)
3. Position close lock (`apps/api/src/trading/position_lock.py`)
4. Queue lag monitor
5. Account constraint enforcer (Tiny/Growth/Aggressive tier enforcement at engine level)

Then begin Phase B3 — Trade Idea Workbench.
