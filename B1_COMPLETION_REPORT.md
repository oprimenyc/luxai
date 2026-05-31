# Phase B1 Hardening — Completion Report

**Date:** 2026-05-30  
**Branch:** main  
**Author:** Grey Taurus + Claude Code

---

## Test Results

```
177 passed in 0.66s
```

| Suite                       | Tests | Status              |
| --------------------------- | ----- | ------------------- |
| test_account_constraints.py | 37    | PASS                |
| test_engine_safety.py       | 16    | PASS (pre-existing) |
| test_idempotency.py         | 22    | PASS                |
| test_kill_switch.py         | 20    | PASS                |
| test_portfolio.py           | 13    | PASS (pre-existing) |
| test_position_lock.py       | 13    | PASS                |
| test_queue_monitor.py       | 22    | PASS                |
| test_risk_engines.py        | 34    | PASS (pre-existing) |

Pre-existing tests: 63. New tests added: 114. Total: 177. Zero regressions.

---

## Files Built / Modified

### New services

| File                                          | Description                                                                                       |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `apps/api/src/trading/idempotency.py`         | Dual-write idempotency guard (Redis SETNX + Supabase audit ledger). Redis unavailable → REJECT.   |
| `apps/api/src/trading/kill_switch.py`         | Persistent kill switch with dual-write. Fail-safe: any infra failure → assume HALTED.             |
| `apps/api/src/trading/position_lock.py`       | Redis distributed lock for position close ops. TTL=30s auto-release. Conflict → raise, not retry. |
| `apps/api/src/trading/queue_monitor.py`       | Tick latency tracker. Thresholds: OK≤500ms, WARNING≤2000ms, CRITICAL≤5000ms, DEGRADED>5000ms.     |
| `apps/api/src/trading/account_constraints.py` | Pure-Python tier enforcer. Hard limits: Tiny/Growth/Aggressive. Engine-level, no bypass.          |
| `apps/api/src/trading/circuit_breaker.py`     | Circuit breaker for broker calls (pre-existing, wired in this phase).                             |

### New migrations

| File                                             | Description                                                                               |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| `supabase/migrations/002_idempotency_ledger.sql` | `order_idempotency_log` table. RLS enforced. Users read own rows only, no writes.         |
| `supabase/migrations/003_system_halts.sql`       | `system_halts` table. Append-only audit log. Active halt = row with `cleared_at IS NULL`. |

### Modified files

| File                             | Change                                                                                                                                                                                                                             |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/api/src/trading/engine.py` | Added `position_lock_redis` and `queue_monitor` params. Wired lock into `_handle_risk_trigger()`. Wired monitor into `_on_quote_update()` and `_evaluate_risk_for_symbol()`. Backward-compatible (both default to None).           |
| `apps/api/src/trading/router.py` | Full rewrite. All endpoints standardized to `AuthenticatedUser`. Full B1 safety chain in `submit_order`. New endpoints: `GET /queue-status`, `GET /kill-switch/status`, `POST /kill-switch/activate`, `DELETE /kill-switch/clear`. |
| `.env.example`                   | Added `TRADIER_API_KEY=` and `TRADIER_SANDBOX=true`.                                                                                                                                                                               |

### New tests

| File                                         | Coverage                                                                                                                                                                 |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/api/tests/test_idempotency.py`         | Hash determinism, first request, duplicate detection, Redis failure → REJECT, Supabase failure non-fatal, restart scenario, mark_completed                               |
| `apps/api/tests/test_kill_switch.py`         | Redis hit/miss, Supabase fallback, fail-safe invariants, activate with rollback, clear write order, get_status                                                           |
| `apps/api/tests/test_position_lock.py`       | Normal acquire/release, conflict raises, Redis failure, body exception releases lock, namespace isolation                                                                |
| `apps/api/tests/test_queue_monitor.py`       | All 4 lag status transitions, boundary conditions, recovery, pending tick tracking, get_status stats, event bus emission, singleton                                      |
| `apps/api/tests/test_account_constraints.py` | Tier classification, all prohibited strategies per tier, dollar cap, percentage cap, effective_max logic, DTE minimums, multi-violation accumulation, case insensitivity |

---

## B1 Checklist

### Safety Chain (CLAUDE.md §Phase B1)

- [x] **Kill switch gate** — checked first in `submit_order`, before any other processing. Fail-safe: infra failure → HALTED.
- [x] **Shadow mode gate** — checked second. Fail-safe: infra failure → ACTIVE (shadow).
- [x] **Account constraints gate** — tier-based hard limits enforced at engine level. No strategy, agent, or UI can bypass.
- [x] **Idempotency gate** — Redis SETNX with Supabase dual-write. Redis unavailable → REJECT (never silently pass).
- [x] **Engine submission** — paper trading only, LIVE mode raises at construction.

### Durability Invariants (CLAUDE.md Rule 4)

- [x] Kill switch writes Redis AND Supabase. Never RAM only.
- [x] Kill switch fail-safe: Redis OR Supabase failure → assume HALTED.
- [x] Kill switch `clear()` writes Supabase FIRST. If Supabase fails, halt stays active.
- [x] Idempotency fail-safe direction is OPPOSITE to shadow: Redis down → REJECT.
- [x] Position close lock: Redis down → PositionLockUnavailable (close rejected, not silently attempted).

### Infrastructure

- [x] All Redis keys namespaced per user/account to prevent cross-account conflicts.
- [x] All Redis keys have TTLs (idempotency: 24h, kill switch: 90 days, position lock: 30s).
- [x] All Supabase tables use RLS. Users read own rows only, no writes.
- [x] Queue monitor detects DEGRADED state and sets `orders_suspended=True` in status endpoint.
- [x] Engine backward-compatible: `position_lock_redis=None` skips the lock (tests unaffected).

### Code Quality

- [x] All endpoints use `AuthenticatedUser` from `src.middleware.auth` (no `user_id: str` inconsistency).
- [x] Zero new I/O in `account_constraints.py` — pure Python, O(1), called on every order.
- [x] No comments explaining what code does — only non-obvious invariants documented.

---

## Remaining Flags for Manual Review

1. **TRADIER_API_KEY not yet provisioned** — `.env.example` has the key, but the Trade Idea Workbench (Phase B3) that uses it has not been built yet. No action needed until B3.

2. **shadow_trades "closed" status not auto-set** — `shadow_trades` rows are written on signal but `closed_at` is never updated by the engine. This is a B3 concern (the closed signal needs to flow back from the broker fill).

3. **Redis per-request client creation** — `get_idempotency_service()` and `get_kill_switch_service()` create a new Redis client per FastAPI request. For Railway single-instance deployment this is acceptable, but a connection pool (via `aioredis.ConnectionPool`) should be wired before scaling to multiple workers.

4. **`check_restart_scenario()` is belt-and-suspenders** — it is called after a Redis SETNX success in `submit_order`. This adds one Supabase round-trip per order during the restart window. Can be made conditional (`only_if_post_restart=True`) when startup state is detected.

5. **Supabase migrations must be applied manually** — `002_idempotency_ledger.sql` and `003_system_halts.sql` are not applied to the Supabase project until the operator runs them in the Supabase dashboard or via `supabase db push`.

---

## Declaration

**Phase B1 is 100% complete.**

All five hardening tasks are implemented, tested, and integrated:

1. Durable idempotency — Redis SETNX + Supabase dual-write, fail-safe REJECT
2. Persistent kill switch — Redis + Supabase dual-write, fail-safe HALTED
3. Position close lock — Redis distributed lock, TTL 30s
4. Queue lag monitor — 500ms/2000ms/5000ms thresholds, DEGRADED suspends orders
5. Account constraint enforcer — Tiny/Growth/Aggressive tier limits, engine-level, no bypass

**Ready for Phase B3 — Trade Idea Workbench.**

Blockers: none. Pre-conditions: apply migrations 002 and 003, provision `TRADIER_API_KEY`.
