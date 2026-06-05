# LuxAI OS — Shadow Run Log

## Run 1 — VOIDED (2026-05-31)

**Reason:** No authenticated user existed at the time this log was created. All 6 Supabase tables confirmed empty (0 rows) on 2026-06-05 audit. Shadow mode was never activated for a real user. No workbench analyses, shadow trades, or P&L data was collected. The shadow clock does not start until first successful login + shadow activation + first workbench analysis.

**New start date:** Pending — starts on first user login + shadow activation.

---

## Run 2 — ACTIVE

## Run Parameters

| Field             | Value                                     |
| ----------------- | ----------------------------------------- |
| Backend           | https://luxai-api.fly.dev                 |
| Frontend          | https://luxai-web-snowy.vercel.app        |
| Shadow mode       | ACTIVE — row written 2026-06-05 05:48 UTC |
| Kill switch       | Clear                                     |
| Day 1             | 2026-06-05                                |
| Day 7 checkpoint  | 2026-06-12                                |
| Day 14 checkpoint | 2026-06-19                                |
| Gate criteria     | 10 analyses, 5 shadow trades, 40–75% hit  |

---

## Health Confirmation (Day 1 — 2026-05-31)

```json
{
  "supabase": "ok",
  "redis": "ok",
  "shadow_mode": true,
  "kill_switch": true,
  "tradier": "ok",
  "alpaca": "ok",
  "version": "0.1.0",
  "phase": "B3-complete"
}
```

> `kill_switch: true` is normal for the synthetic health-check user.
> Real user sessions use their own kill-switch state.

---

## Gate Criteria Tracker

| Criterion                        | Target    | Current | Status  |
| -------------------------------- | --------- | ------- | ------- |
| Workbench analyses submitted     | ≥ 10      | 0       | Pending |
| Shadow trades intercepted/logged | ≥ 5       | 0       | Pending |
| Hit rate (closed trades)         | 40%–75%   | N/A     | Pending |
| Kill switch triggers             | 0         | 0       | OK      |
| Health endpoint green (7 days)   | 14/14     | 0/14    | Running |
| Health endpoint green (14 days)  | 14/14     | 0/14    | Running |
| Day 7 shadow report              | Generated | Pending | Pending |
| Day 14 shadow report             | Generated | Pending | Pending |
| Admin journal audit              | Complete  | Pending | Pending |

---

## Day 7 Checkpoint — 2026-06-07

_To be filled on 2026-06-07._

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

## Day 14 Checkpoint — 2026-06-14

_To be filled on 2026-06-14._

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

## Live Trading Gate

Shadow mode can only be exited when all Day 14 gate criteria are met AND admin
explicitly confirms. No code changes for live trading before that confirmation.
