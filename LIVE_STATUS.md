# LuxAI OS — Live Status

**Updated:** 2026-05-31  
**Declaration: LUXAI OS IS LIVE**

---

## Service Status

| Service               | Status        | URL                                                  |
| --------------------- | ------------- | ---------------------------------------------------- |
| Backend (Fly.io)      | **LIVE**      | https://luxai-api.fly.dev                            |
| Health endpoint       | **ALL GREEN** | https://luxai-api.fly.dev/api/v1/health              |
| Frontend (Vercel)     | **LIVE**      | https://luxai-web-snowy.vercel.app                   |
| Frontend HTTP status  | **200**       | confirmed 2026-05-31                                 |
| GitHub Actions CI     | **PASSING**   | typecheck + lint + format + 225 Python tests         |
| GitHub Actions Deploy | **PASSING**   | backend auto-deploys; frontend via Vercel GitHub app |
| Shadow mode           | **ACTIVE**    | shadow_mode: true confirmed                          |
| Kill switch           | Clear         | kill_switch: true = health-check user only, expected |

---

## Backend Health (confirmed 2026-05-31)

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

---

## Frontend (Vercel)

| Field           | Value                                          |
| --------------- | ---------------------------------------------- |
| Production URL  | https://luxai-web-snowy.vercel.app             |
| Project         | oprime-s-projects3/luxai-web                   |
| Project ID      | prj_txsHxDsATzUPR3Qol89eEUpS3gtF               |
| Node version    | 24.x                                           |
| Root directory  | apps/web                                       |
| Deploy trigger  | Vercel GitHub app — auto-deploys on push       |
| Build command   | cd ../.. && pnpm --filter @luxai/web run build |
| Install command | cd ../.. && pnpm install --frozen-lockfile     |

---

## GitHub Secrets Status

| Secret                          | Status      | Notes                                                       |
| ------------------------------- | ----------- | ----------------------------------------------------------- |
| `FLY_API_TOKEN`                 | **SET**     | Fresh deploy token, 8760h TTL (regenerated 2026-05-31)      |
| `NEXT_PUBLIC_SUPABASE_URL`      | **SET**     | `https://dlpkggsfbxihfaybrqvt.supabase.co`                  |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | **SET**     | Anon key                                                    |
| `NEXT_PUBLIC_API_URL`           | **SET**     | `https://luxai-api.fly.dev`                                 |
| `NEXT_PUBLIC_APP_URL`           | **SET**     | `https://luxai-web-snowy.vercel.app`                        |
| `VERCEL_PROJECT_ID`             | **SET**     | `prj_txsHxDsATzUPR3Qol89eEUpS3gtF`                          |
| `VERCEL_ORG_ID`                 | **SET**     | `oprime-s-projects3`                                        |
| `VERCEL_TOKEN`                  | **PENDING** | Create at vercel.com/account/tokens → name "github-actions" |

Once `VERCEL_TOKEN` is added, the GitHub Actions `deploy-frontend` job
will also run `vercel deploy --prod` (currently skips gracefully without it).

---

## Route Map

| URL           | Served By                                        |
| ------------- | ------------------------------------------------ |
| `/`           | `app/page.tsx` — landing page (Server Component) |
| `/dashboard`  | `app/(dashboard)/dashboard/page.tsx` — overview  |
| `/monitoring` | `app/(dashboard)/monitoring/page.tsx`            |
| `/memory`     | `app/(dashboard)/memory/page.tsx`                |
| `/trading`    | `app/(dashboard)/trading/page.tsx`               |
| `/workbench`  | `app/(dashboard)/workbench/page.tsx`             |
| `/governance` | `app/(dashboard)/governance/page.tsx`            |
| `/workflows`  | `app/(dashboard)/workflows/page.tsx`             |
| `/settings`   | `app/(dashboard)/settings/page.tsx`              |
| `/api/health` | `app/api/health/route.ts`                        |

---

## Shadow Mode

| Field               | Value                                                      |
| ------------------- | ---------------------------------------------------------- |
| Status              | **ACTIVE**                                                 |
| Activated           | 2026-05-31 (backend confirms `shadow_mode: true`)          |
| Day 7 checkpoint    | 2026-06-07                                                 |
| Day 14 checkpoint   | 2026-06-14                                                 |
| Gate criteria       | 10 analyses, 5 trades, 40–75% hit, no kill-switch triggers |
| Admin journal audit | 2026-06-14                                                 |

See `SHADOW_RUN_LOG.md` for daily tracking.

---

## Cost

| Service                      | Monthly Cost                       |
| ---------------------------- | ---------------------------------- |
| Fly.io (shared-cpu-1x 256MB) | ~$1.94 — covered by $5 free credit |
| Vercel (hobby)               | $0                                 |
| Upstash Redis                | $0 (free tier)                     |
| Supabase                     | $0 (free tier)                     |
| **Total**                    | **$0/month**                       |

---

## CI/CD Pipeline

```
push to main
  ├─▶ CI (parallel)
  │     ├─▶ TypeScript typecheck (apps/web) ✓
  │     ├─▶ ESLint lint (apps/web) ✓
  │     ├─▶ Prettier format-check (apps/web) ✓
  │     └─▶ Python pytest 225 tests (apps/api) ✓
  └─▶ Deploy (parallel)
        ├─▶ Backend → Fly.io ✓
        └─▶ Frontend → Vercel (skips until VERCEL_TOKEN added — exit 0) ✓
              (Vercel GitHub app auto-deploys independently on every push)
```

---

## Build Fixes Applied This Session

| Issue                                    | Root Cause                                                                                                               | Fix                                                                                                       | Commit           |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- | ---------------- |
| ENOENT page_client-reference-manifest.js | `app/(dashboard)/page.tsx` conflicted with `app/page.tsx` at `/`; Next.js didn't generate manifest for conflicting route | Moved dashboard overview to `app/(dashboard)/dashboard/page.tsx` (`/dashboard`); deleted conflicting page | 695ed0c, 85a4213 |
| Vercel blocked: vulnerable Next.js       | next@15.3.2 had known CVE                                                                                                | Upgraded to next@15.3.9 (latest 15.3.x patch)                                                             | 41f4374          |
| FLY_API_TOKEN invalid                    | Token expired                                                                                                            | Regenerated via `fly tokens create deploy`                                                                | —                |
| Next.js build crash on `/_not-found`     | `new URL(NEXT_PUBLIC_APP_URL)` threw on trailing whitespace                                                              | Wrapped in try/catch with .trim()                                                                         | 6ac3a43          |
| CI lint failures                         | 30+ pre-existing ESLint errors                                                                                           | Fixed across 19 files                                                                                     | 1cf8197          |
| CI format failures                       | `.next/` not excluded from prettier                                                                                      | Added `apps/web/.prettierignore`                                                                          | 0d3153a          |

---

## Next Action

**Check in 2026-06-07 for Day 7 shadow report.**

Before then, one manual step:

1. Go to **vercel.com/account/tokens**
2. Create token named `github-actions`, scope: Full Account
3. `gh secret set VERCEL_TOKEN --repo oprimenyc/luxai` and paste the token
4. Next push to main will fully auto-deploy frontend via GitHub Actions too

Day 7 checklist:

- [ ] Count workbench analyses submitted
- [ ] Count shadow trades intercepted and logged
- [ ] Calculate hit rate on closed trades
- [ ] Confirm health endpoint all-green
- [ ] Update SHADOW_RUN_LOG.md
