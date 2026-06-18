# SETTINGS_REPORT.md

Generated: 2026-06-17

---

## Summary

Account Settings Panel is complete. Users can view their account tier, review
hardcoded risk rules, and configure shadow testing parameters through the
Settings UI. All settings persist to Supabase. Live trading remains locked.

---

## 1. Migration Applied — 006_account_settings

Table: `account_settings`

| Column                | Type          | Default  | Constraint              |
| --------------------- | ------------- | -------- | ----------------------- |
| id                    | UUID PK       | gen_uuid | —                       |
| user_id               | TEXT UNIQUE   | required | One row per user        |
| shadow_min_dte        | INTEGER       | 3        | 1–7                     |
| shadow_max_dte        | INTEGER       | 21       | 7–60                    |
| shadow_max_contracts  | INTEGER       | 3        | 1–3                     |
| shadow_max_risk_usd   | NUMERIC(10,2) | 15.00    | 5.00–15.00              |
| shadow_allow_earnings | BOOLEAN       | false    | —                       |
| score_threshold       | NUMERIC(4,1)  | 7.0      | 6.0–9.0                 |
| created_at            | TIMESTAMPTZ   | now()    | —                       |
| updated_at            | TIMESTAMPTZ   | now()    | Auto-updated by trigger |

RLS policies:

- `users_read_own_settings` — SELECT on own user_id
- `users_insert_own_settings` — INSERT for own user_id
- `users_update_own_settings` — UPDATE on own user_id

Migration applied via Supabase MCP. Status: `{ "success": true }`

---

## 2. Settings API

**GET `/api/v1/settings`**

- Auth required (Supabase JWT)
- Returns current settings for the authenticated user
- If no row exists, returns default values (does not write to DB)
- Never returns another user's settings (user_id from JWT, not request body)

**PATCH `/api/v1/settings`**

- Auth required
- Partial update — only provided fields are changed
- Uses upsert with `on_conflict=user_id` — idempotent first write
- Cross-field validation: `shadow_min_dte` must be < `shadow_max_dte`
- All fields validated to permitted ranges before DB write
- Returns the saved row

File: `apps/api/src/routers/settings.py`
Wired at: `apps/api/src/main.py` → `app.include_router(settings_router, prefix="/api/v1")`

---

## 3. account_constraints.py Changes

### Added: ShadowTestingOverrides

```python
@dataclass(frozen=True)
class ShadowTestingOverrides:
    min_dte: int = 3
    max_dte: int = 21
    max_contracts: int = 3
    max_risk_usd: float = 15.0
    allow_earnings: bool = False
    score_threshold: float = 7.0
```

Frozen dataclass — values cannot be mutated after creation.

### Added: load_shadow_overrides()

```python
async def load_shadow_overrides(user_id: str, supabase: Any) -> ShadowTestingOverrides
```

- Reads from `account_settings` table for the given user
- Falls back to `ShadowTestingOverrides.defaults()` on any exception or missing row
- **Callers should cache the result** — calling this per-scan is fine, per-order is not

### Critical constraint preserved

These values are ONLY used by scanner/workbench signal discovery during shadow mode.
`AccountConstraintEnforcer.check()` is unchanged — it still enforces hardcoded tier
limits on every order submission. Shadow overrides never touch the order path.

---

## 4. Live Trading Hard Wall

Added Gate 0 to `submit_order` in `apps/api/src/trading/router.py`:

```python
# 0DTE options are prohibited at every tier, in every mode, forever.
if body.dte is not None and body.dte < 1:
    raise HTTPException(422, "0DTE options are prohibited. Minimum DTE is 1.")
```

This runs before kill switch, shadow intercept, constraints, and idempotency.
It cannot be bypassed by any settings, shadow override, or UI state.

The shadow mode intercept (Gate 2) continues to ensure no real orders reach the
broker during the shadow run. The Gate 0 DTE check adds an additional invariant
that survives even if shadow mode were somehow inactive.

No "enable live trading" endpoint exists. No UI button for live trading exists.
Live trading is locked until admin explicitly confirms shadow gate passage.

---

## 5. Settings UI — 4 New Trading Panels

File: `apps/web/app/(dashboard)/settings/page.tsx` (replaced stub)

The settings page now has two navigation sections:

**Trading section:**

- Account — tier classification, mode badge, quick rules reference
- Risk Controls — read-only comparison table (Tiny / Growth / Aggressive)
- Shadow Testing — editable range sliders + earnings toggle with live save
- Danger Zone — live trading gate status, kill switch status

**System section (preserved from original):**

- Profile, API Keys, Security, Notifications

Component files:

- `apps/web/components/settings/AccountPanel.tsx`
- `apps/web/components/settings/RiskPanel.tsx`
- `apps/web/components/settings/ShadowPanel.tsx` — fetches/patches via `/api/v1/settings`

### Shadow Panel UX

- Range sliders for all numeric values — no free-text entry avoids invalid input
- Toggle switch for earnings allowance
- Save button enabled only when values differ from initial (dirty state detection)
- Info banner: "Shadow overrides only affect scanner and workbench analysis"
- Saved timestamp displayed after successful save

---

## 6. Test Coverage

**File: `apps/api/tests/test_settings.py`** — 7 tests

| Test                                                         | Description                                              |
| ------------------------------------------------------------ | -------------------------------------------------------- |
| `test_shadow_overrides_defaults`                             | ShadowTestingOverrides.defaults() returns correct values |
| `test_shadow_overrides_immutable`                            | Frozen dataclass raises on mutation attempt              |
| `test_load_shadow_overrides_returns_db_values`               | Reads and maps DB row correctly                          |
| `test_load_shadow_overrides_returns_defaults_on_missing_row` | Empty DB → defaults                                      |
| `test_load_shadow_overrides_returns_defaults_on_exception`   | DB error → defaults, no raise                            |
| `test_patch_settings_validates_min_dte_range`                | Range bounds enforced (0 rejected, 8 rejected)           |
| `test_patch_settings_rejects_score_threshold_out_of_range`   | 5.5 and 9.5 rejected                                     |

**Full suite: 279 passed, 1 skipped** (up from 272).

---

## 7. Security Audit

| Check                                              | Status                                          |
| -------------------------------------------------- | ----------------------------------------------- |
| User can only read/write own settings              | PASS — user_id comes from JWT, not request body |
| Shadow overrides cannot be used in live order path | PASS — enforcer.check() unchanged               |
| 0DTE permanently blocked                           | PASS — Gate 0 in submit_order                   |
| Live trading button absent from UI                 | PASS — Danger Zone is informational only        |
| Kill switch can't be cleared from UI               | PASS — no clear endpoint exposed to UI          |
| RLS enforced on account_settings                   | PASS — three policies applied in migration      |
| No fire-and-forget async                           | PASS — settings router is pure request/response |

---

## 8. Shadow Run Gate — No Change

The 2-week shadow run is unaffected by this feature. Shadow testing parameters
relax signal discovery limits during the run, which allows more diverse signals
to be tested — helping accumulate the ≥5 shadow trade and ≥10 analyses criteria
faster without degrading safety infrastructure.

Gate criteria remain unchanged (from CLAUDE.md):

- [ ] ≥ 10 workbench analyses submitted
- [ ] ≥ 5 shadow trades intercepted and logged
- [ ] Hit rate between 40% and 75% across closed trades
- [ ] No kill switch triggers
- [ ] Health endpoint green across both weeks
- [ ] Shadow report at day 7 and day 14
- [ ] Journal audit by admin
