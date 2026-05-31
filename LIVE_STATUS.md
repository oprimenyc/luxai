# LuxAI OS — Live Status

**Updated:** 2026-05-31  
**Declaration: LUXAI OS IS LIVE (backend) — Frontend CI/CD wired and passing**

---

## Service Status

| Service                  | Status                         | URL                                                                 |
| ------------------------ | ------------------------------ | ------------------------------------------------------------------- |
| Backend (Fly.io)         | **LIVE**                       | https://luxai-api.fly.dev                                           |
| Health endpoint          | **ALL GREEN**                  | https://luxai-api.fly.dev/api/v1/health                             |
| Frontend CI build        | **PASSING**                    | Next.js 15.3.2 build clean                                          |
| Frontend deploy (Vercel) | **PENDING SETUP**              | vercel.com → import repo                                            |
| GitHub Actions CI        | **PASSING**                    | typecheck + lint + format all green                                 |
| GitHub Actions Deploy    | **PASSING**                    | Backend auto-deploys; Frontend skips gracefully until Vercel linked |
| Shadow mode              | **ACTIVE**                     | shadow_mode: true confirmed                                         |
| Kill switch              | Clear (health-check user only) | kill_switch: true expected                                          |

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

## GitHub Secrets Status

| Secret                          | Status                                  | Notes                                            |
| ------------------------------- | --------------------------------------- | ------------------------------------------------ |
| `FLY_API_TOKEN`                 | **SET** — fresh deploy token, 8760h TTL | Regenerated 2026-05-31                           |
| `NEXT_PUBLIC_SUPABASE_URL`      | **SET**                                 | `https://dlpkggsfbxihfaybrqvt.supabase.co`       |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | **SET**                                 | Anon key                                         |
| `NEXT_PUBLIC_API_URL`           | **SET**                                 | `https://luxai-api.fly.dev`                      |
| `NEXT_PUBLIC_APP_URL`           | **SET**                                 | `https://luxai.app` (update after Vercel linked) |
| `VERCEL_TOKEN`                  | **MANUAL ACTION REQUIRED**              | vercel.com → Settings → Tokens → Create          |
| `VERCEL_ORG_ID`                 | **MANUAL ACTION REQUIRED**              | After `vercel link` in apps/web/                 |
| `VERCEL_PROJECT_ID`             | **MANUAL ACTION REQUIRED**              | After `vercel link` in apps/web/                 |
| `CLOUDFLARE_API_TOKEN`          | Not needed (not in workflow)            | N/A                                              |
| `CLOUDFLARE_ACCOUNT_ID`         | Not needed (not in workflow)            | N/A                                              |

---

## Frontend — One-Time Vercel Setup (Manual, ~5 min)

1. Go to **https://vercel.com** → sign in with `opportunistprimeny@gmail.com`
2. Click **Add New → Project**
3. Import from GitHub → select **oprimenyc/luxai**
4. Configure:
   - Root Directory: `apps/web`
   - Framework Preset: Next.js (auto-detected)
   - Build / Output: leave as default (reads `vercel.json`)
5. Add Environment Variables:
   - `NEXT_PUBLIC_SUPABASE_URL` = `https://dlpkggsfbxihfaybrqvt.supabase.co`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` = _(from .env)_
   - `NEXT_PUBLIC_API_URL` = `https://luxai-api.fly.dev`
   - `NEXT_PUBLIC_APP_URL` = `https://luxai-web.vercel.app` _(update after first deploy)_
   - `NEXT_TELEMETRY_DISABLED` = `1`
6. Click **Deploy** — first deploy ~2 min

### After first deploy — get IDs for GitHub CI

```bash
cd apps/web
npx vercel link          # select account + luxai project
cat .vercel/project.json # → {"orgId": "...", "projectId": "..."}
```

Then add to GitHub → Settings → Secrets:

- `VERCEL_TOKEN` (vercel.com → Settings → Tokens → github-actions)
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

After adding those three secrets, every push to `main` will deploy both
backend (Fly.io) and frontend (Vercel) automatically.

### Update CORS after Vercel URL is confirmed

```powershell
$env:PATH = "C:\Users\jp718\.fly\bin;" + $env:PATH
flyctl secrets set "CORS_ORIGINS=https://luxai-web.vercel.app" --app luxai-api
```

---

## Shadow Mode

| Field             | Value                                                      |
| ----------------- | ---------------------------------------------------------- |
| Status            | **ACTIVE**                                                 |
| Activated         | 2026-05-31 (backend health confirms `shadow_mode: true`)   |
| Day 7 checkpoint  | 2026-06-07                                                 |
| Day 14 checkpoint | 2026-06-14                                                 |
| Gate criteria     | 10 analyses, 5 trades, 40–75% hit, no kill-switch triggers |
| Journal audit     | 2026-06-14                                                 |

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

## CI/CD Pipeline Status

```
push to main
  ├─▶ CI (parallel)
  │     ├─▶ TypeScript typecheck (apps/web) ✓
  │     ├─▶ ESLint lint (apps/web) ✓
  │     ├─▶ Prettier format-check (apps/web) ✓
  │     └─▶ Python pytest 225 tests (apps/api) ✓
  └─▶ Deploy (parallel)
        ├─▶ Backend → Fly.io (FLY_API_TOKEN valid) ✓
        └─▶ Frontend → Vercel (skips until VERCEL_TOKEN set — exit 0) ✓
```

---

## Fixes Made This Session

| Fix                                                                 | Commit  |
| ------------------------------------------------------------------- | ------- |
| Remove @replit/\* imports blocking Vercel build                     | 7699d75 |
| Decouple frontend deploy from backend; guard missing Vercel secrets | c4c79a7 |
| Guard metadataBase new URL() against invalid NEXT_PUBLIC_APP_URL    | 6ac3a43 |
| Resolve all ESLint errors in 19 files; add SHADOW_RUN_LOG.md        | 1cf8197 |
| Prettier format 5 pre-existing files                                | b92770c |
| Add apps/web/.prettierignore to exclude .next from format check     | 0d3153a |
| FLY_API_TOKEN regenerated (expired token replaced)                  | —       |
| NEXT_PUBLIC_APP_URL reset to clean https://luxai.app                | —       |

---

## Next Action

**Check in 2026-06-07 for Day 7 shadow report.**

Checklist for that session:

- [ ] Count analyses submitted via workbench
- [ ] Count shadow trades intercepted and logged
- [ ] Calculate hit rate on closed trades
- [ ] Confirm health endpoint still all-green
- [ ] Complete Vercel project setup (see above) if not done
- [ ] Update NEXT_PUBLIC_APP_URL secret and CORS_ORIGINS with real Vercel URL
