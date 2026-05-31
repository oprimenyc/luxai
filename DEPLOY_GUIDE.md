# LuxAI OS — Cloud Deployment Guide

**Updated:** 2026-05-30  
**Backend:** Fly.io (FastAPI + shadow monitor) — shared-cpu-1x 256MB, region iad  
**Frontend:** Cloudflare Pages (Next.js 15)  
**Redis:** Upstash — already configured, no action needed  
**Database:** Supabase — already configured, no action needed  
**Cost:** $0/month — Fly.io $5 free credit covers ~$1.94/month VM

---

## Architecture

```
Browser
  └─▶ Cloudflare Pages  (luxai-web.pages.dev or custom domain)
        │   serves static Next.js shell
        └─▶ Fly.io API   (luxai-api.fly.dev — FastAPI + shadow monitor)
              ├─▶ Supabase  (PostgreSQL + Auth — public HTTPS)
              ├─▶ Upstash   (Redis — public TLS rediss://)
              ├─▶ Alpaca Paper API (order interception — public HTTPS)
              └─▶ Tradier Sandbox (options chain — public HTTPS)
```

No VPC, no private networking. Fly.io connects to all services over the
public internet via TLS. Upstash Redis uses `rediss://` — fully encrypted.

---

## Part 1 — Fly.io Account Setup

### Step 1 — Create account and install flyctl

```bash
# Install flyctl (macOS / Linux / WSL)
curl -L https://fly.io/install.sh | sh

# Windows (PowerShell)
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"

# Verify
flyctl version
```

1. Go to https://fly.io → **Sign up** (GitHub login recommended)
2. Fly.io gives **$5/month free credit** automatically — no card required for the first app
3. A `shared-cpu-1x 256MB` machine costs **~$1.94/month** — well within the credit

### Step 2 — Login

```bash
flyctl auth login
# Opens browser — sign in with your Fly.io account
```

---

## Part 2 — First-Time Fly.io Deploy

### Step 3 — Launch the app (first time only)

```bash
cd apps/api

# fly launch reads fly.toml — DO NOT overwrite it when prompted.
flyctl launch \
  --name luxai-api \
  --region iad \
  --no-deploy
# When asked "overwrite fly.toml?" → type: N (No)
# When asked to set up a Postgres/Redis database → N (we use Upstash/Supabase)
```

This registers `luxai-api` as your app on Fly.io. You only do this once.

### Step 4 — Set secrets (copy-paste this entire block)

```bash
# Run from apps/api/ — sets all secrets in one command.
# Fly.io encrypts these and injects them as env vars at runtime.
# They are NEVER visible in logs or the dashboard after being set.

flyctl secrets set \
  SUPABASE_URL="$(grep SUPABASE_URL .env | cut -d= -f2)" \
  SUPABASE_ANON_KEY="$(grep ^SUPABASE_ANON_KEY .env | cut -d= -f2)" \
  SUPABASE_SERVICE_ROLE_KEY="$(grep SUPABASE_SERVICE_ROLE_KEY .env | cut -d= -f2)" \
  SUPABASE_JWT_SECRET="$(grep SUPABASE_JWT_SECRET .env | cut -d= -f2)" \
  UPSTASH_REDIS_URL="$(grep UPSTASH_REDIS_URL .env | cut -d= -f2)" \
  UPSTASH_REDIS_TOKEN="$(grep UPSTASH_REDIS_TOKEN .env | cut -d= -f2)" \
  ANTHROPIC_API_KEY="$(grep ANTHROPIC_API_KEY .env | cut -d= -f2)" \
  ALPACA_API_KEY="$(grep ^ALPACA_API_KEY .env | cut -d= -f2)" \
  ALPACA_API_SECRET="$(grep ALPACA_API_SECRET .env | cut -d= -f2)" \
  ALPACA_SECRET_KEY="$(grep ALPACA_SECRET_KEY .env | cut -d= -f2)" \
  TRADIER_API_KEY="$(grep TRADIER_API_KEY .env | cut -d= -f2)" \
  LANGCHAIN_API_KEY="$(grep LANGCHAIN_API_KEY .env | cut -d= -f2)" \
  CORS_ORIGINS="https://luxai-web.pages.dev" \
  --app luxai-api

# Note: the commands above read values directly from your .env file.
# Run this from the repository root where .env lives.
```

> After your Cloudflare Pages URL is confirmed, update CORS_ORIGINS:
>
> ```bash
> flyctl secrets set CORS_ORIGINS="https://luxai-web.pages.dev" --app luxai-api
> ```

### Step 5 — Deploy

```bash
# From apps/api/
flyctl deploy --remote-only

# Fly.io will:
#   1. Send apps/api/ to the remote builder
#   2. Build Dockerfile (python:3.11-slim, ~2-3 minutes)
#   3. Push the image to Fly's container registry
#   4. Start a shared-cpu-1x 256MB machine in iad
#   5. Run the healthcheck at /api/v1/health (grace period 15s)
#   6. Mark the deploy as live when the check passes
```

### Step 6 — Verify

```bash
# Check machine status
flyctl status --app luxai-api

# Stream live logs
flyctl logs --app luxai-api

# Test the health endpoint
curl https://luxai-api.fly.dev/api/v1/health
```

Expected response:

```json
{
  "supabase": "ok",
  "redis": "ok",
  "shadow_mode": true,
  "kill_switch": false,
  "tradier": "ok",
  "alpaca": "ok",
  "version": "0.1.0",
  "phase": "B3-complete"
}
```

### Step 7 — Activate shadow mode

```bash
# Get a Supabase JWT: Dashboard → Authentication → Users → your user → copy JWT
# Or sign in to the frontend once deployed and copy the token from localStorage.

curl -X POST https://luxai-api.fly.dev/api/v1/trading/shadow/activate \
  -H "Authorization: Bearer <your-supabase-jwt>" \
  -H "Content-Type: application/json"
```

---

## Part 3 — Fly.io Environment Variable Reference

Non-secret vars live in `fly.toml [env]`. Secrets are set via `fly secrets set`.

### fly.toml [env] (committed to repo — non-secret only)

| Variable               | Value                              | Set in   |
| ---------------------- | ---------------------------------- | -------- |
| `ENVIRONMENT`          | `production`                       | fly.toml |
| `ALPACA_PAPER`         | `true`                             | fly.toml |
| `ALPACA_BASE_URL`      | `https://paper-api.alpaca.markets` | fly.toml |
| `TRADIER_SANDBOX`      | `true`                             | fly.toml |
| `LANGCHAIN_TRACING_V2` | `false`                            | fly.toml |
| `LANGCHAIN_PROJECT`    | `luxai-os`                         | fly.toml |

### fly secrets set (one-time — never committed)

| Secret                      | Notes                           |
| --------------------------- | ------------------------------- |
| `SUPABASE_URL`              | Your project URL                |
| `SUPABASE_ANON_KEY`         | Public anon JWT                 |
| `SUPABASE_SERVICE_ROLE_KEY` | Admin JWT — keep secret         |
| `SUPABASE_JWT_SECRET`       | Used to verify user JWTs        |
| `UPSTASH_REDIS_URL`         | Full `rediss://` connection URL |
| `UPSTASH_REDIS_TOKEN`       | REST token for Upstash HTTP API |
| `ANTHROPIC_API_KEY`         | Claude API key                  |
| `ALPACA_API_KEY`            | Paper trading key only          |
| `ALPACA_API_SECRET`         | Paper trading secret            |
| `ALPACA_SECRET_KEY`         | Alias of ALPACA_API_SECRET      |
| `TRADIER_API_KEY`           | Sandbox token                   |
| `LANGCHAIN_API_KEY`         | LangSmith (optional)            |
| `CORS_ORIGINS`              | Cloudflare Pages URL            |

Fly.io does **not** need `PORT` set manually — it's injected automatically to match `internal_port = 8000` in fly.toml.

---

## Part 4 — Cloudflare Pages (Frontend)

### Prerequisites

```bash
npm install -g wrangler
wrangler login
```

### Option A — Git Integration (recommended — auto-deploys on push)

1. Go to https://dash.cloudflare.com → **Workers & Pages → Create → Pages → Connect to Git**
2. Select your GitHub repo
3. Configure:

| Setting                | Value                                |
| ---------------------- | ------------------------------------ |
| Project name           | `luxai-web`                          |
| Production branch      | `main`                               |
| Framework preset       | `Next.js`                            |
| Build command          | `pnpm --filter @luxai/web run build` |
| Build output directory | `apps/web/.next`                     |
| Root directory         | _(blank — monorepo root)_            |

4. Add environment variables (table below)
5. Click **Save and Deploy**

### Option B — CLI Manual Deploy

```bash
# From monorepo root
pnpm --filter @luxai/web run build

wrangler pages deploy apps/web/.next \
  --project-name luxai-web \
  --commit-dirty=true
```

### Cloudflare Pages Environment Variables

Set in: Cloudflare dashboard → Pages project → **Settings → Environment Variables → Production**

| Variable                        | Value                                      |
| ------------------------------- | ------------------------------------------ |
| `NEXT_PUBLIC_SUPABASE_URL`      | `https://dlpkggsfbxihfaybrqvt.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `eyJhbGci...` (anon key — safe to expose)  |
| `NEXT_PUBLIC_API_URL`           | `https://luxai-api.fly.dev`                |
| `NEXT_PUBLIC_APP_URL`           | `https://luxai-web.pages.dev`              |
| `NEXT_TELEMETRY_DISABLED`       | `1`                                        |

> The anon key is designed to be public. Supabase's RLS policies enforce
> access regardless of who holds it.

---

## Part 5 — Connecting Frontend to Backend

After both deploys are live:

1. **Backend URL** is `https://luxai-api.fly.dev` (fixed — Fly.io uses the app name)

2. **Set in Cloudflare Pages → Environment Variables:**

   ```
   NEXT_PUBLIC_API_URL = https://luxai-api.fly.dev
   ```

3. **Update CORS_ORIGINS on Fly.io:**

   ```bash
   flyctl secrets set CORS_ORIGINS="https://luxai-web.pages.dev" --app luxai-api
   # This triggers an automatic Fly.io redeploy
   ```

4. Trigger a Cloudflare Pages rebuild (push to main or click Retry).

---

## Part 6 — GitHub Actions CI/CD

### Secrets to add in GitHub

Go to: **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**

Add all of these:

| Secret name                     | Where to get it                                                                                          |
| ------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `FLY_API_TOKEN`                 | `flyctl auth token` (run locally after login)                                                            |
| `CLOUDFLARE_API_TOKEN`          | Cloudflare dashboard → **My Profile → API Tokens → Create Token** → use "Edit Cloudflare Pages" template |
| `CLOUDFLARE_ACCOUNT_ID`         | Cloudflare dashboard → right sidebar → Account ID                                                        |
| `NEXT_PUBLIC_SUPABASE_URL`      | `https://dlpkggsfbxihfaybrqvt.supabase.co`                                                               |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Anon key from `.env`                                                                                     |
| `NEXT_PUBLIC_API_URL`           | `https://luxai-api.fly.dev`                                                                              |
| `NEXT_PUBLIC_APP_URL`           | `https://luxai-web.pages.dev`                                                                            |

### How the workflow works

File: `.github/workflows/deploy.yml` — triggers on every push to `main`.

```
push to main
  └─▶ deploy-backend  (Fly.io)
        flyctl deploy --remote-only
        Fly builds Docker image remotely (~2 min)
        Health check at /api/v1/health passes
        Machine marked started
      └─▶ deploy-frontend  (Cloudflare Pages)
            pnpm install --frozen-lockfile
            pnpm --filter @luxai/web run build
            wrangler pages deploy apps/web/.next
```

Frontend deploys **after** backend (via `needs: deploy-backend`) — the UI
never deploys against a backend that hasn't passed its health check.

### Get the FLY_API_TOKEN

```bash
# After flyctl auth login
flyctl auth token
# Copy the output — paste as the FLY_API_TOKEN GitHub secret
```

### Get the Cloudflare API Token

1. Cloudflare dashboard → **My Profile → API Tokens**
2. Click **Create Token**
3. Use template: **Edit Cloudflare Workers** (includes Pages permissions)
4. Under **Zone Resources**: select your account
5. Copy the token → paste as `CLOUDFLARE_API_TOKEN` GitHub secret

---

## Part 7 — Shadow Monitor in the Cloud

The monitor runs as `asyncio.create_task()` in the FastAPI lifespan.

| Condition                                  | Behaviour                                                                        |
| ------------------------------------------ | -------------------------------------------------------------------------------- |
| `--workers 1` (enforced in Dockerfile CMD) | One process → one monitor → correct                                              |
| `auto_stop_machines = false` in fly.toml   | Machine never sleeps — monitor always polling                                    |
| `min_machines_running = 1` in fly.toml     | Fly always keeps at least one machine running                                    |
| Fly machine restart                        | Monitor restarts with process; no state loss — state lives in Supabase + Upstash |
| Upstash via `rediss://`                    | Public TLS — connects from Fly with no special networking                        |
| Alpaca price checks                        | Public HTTPS — works from Fly                                                    |

Poll cycle: 60 seconds. Exit rules: stop-loss −5%, take-profit +10%.

**Future note:** To scale to multiple machines, extract the shadow monitor
into a dedicated Fly cron machine (`fly machine run --schedule hourly ...`).
For a single-machine shadow run, the current setup is correct.

---

## Part 8 — Upstash Redis from Fly.io

```
Fly machine (iad)
  └─▶ rediss://model-basilisk-140297.upstash.io:6379
        TLS over public internet — no VPC, no firewall rules needed
```

The `UPSTASH_REDIS_URL` secret is injected at runtime. Upstash is a global
service — the iad machine routes to the nearest Upstash replica automatically.
Latency: ~5–15ms from US East.

---

## Part 9 — Expected Live URLs

| Service          | URL                                       | Notes                                           |
| ---------------- | ----------------------------------------- | ----------------------------------------------- |
| FastAPI backend  | `https://luxai-api.fly.dev`               | Fixed — based on app name                       |
| Health check     | `https://luxai-api.fly.dev/api/v1/health` | All dependencies should show "ok"               |
| API docs         | Disabled in production                    | `ENVIRONMENT=production` hides /docs and /redoc |
| Cloudflare Pages | `https://luxai-web.pages.dev`             | Auto-assigned                                   |
| Custom domain    | `https://app.yourdomain.com`              | Optional — configure in CF dashboard            |

---

## Part 10 — Cost Breakdown: $0/month

| Service                                | Cost         | Notes                            |
| -------------------------------------- | ------------ | -------------------------------- |
| Fly.io shared-cpu-1x 256MB (always-on) | ~$1.94/month |                                  |
| Fly.io $5 free credit                  | −$5.00/month | Applies every month              |
| **Fly.io net cost**                    | **$0/month** | $3.06 credit remaining           |
| Cloudflare Pages                       | $0/month     | Free tier — unlimited requests   |
| Upstash Redis                          | $0/month     | Free tier — 10,000 req/day       |
| Supabase                               | $0/month     | Free tier — 500MB DB, 50,000 MAU |
| **Total**                              | **$0/month** |                                  |

---

## Part 11 — Custom Domain (Optional)

### Backend (Fly.io)

```bash
flyctl certs add api.yourdomain.com --app luxai-api
# Fly.io gives you an A record and AAAA record to add in your DNS provider
# Certificate is provisioned automatically via Let's Encrypt

# After DNS propagates (~5 min), update CORS_ORIGINS:
flyctl secrets set CORS_ORIGINS="https://luxai-web.pages.dev,https://app.yourdomain.com" --app luxai-api
```

### Frontend (Cloudflare Pages)

1. Cloudflare dashboard → Pages → your project → **Custom domains**
2. Add your domain (e.g. `app.yourdomain.com`)
3. If the domain is on Cloudflare: DNS is updated automatically
4. Update `NEXT_PUBLIC_APP_URL` → your custom domain
5. Update `CORS_ORIGINS` on Fly.io to include the custom domain

---

## Part 12 — Day-to-Day Operations

```bash
# View live logs
flyctl logs --app luxai-api

# SSH into running machine
flyctl ssh console --app luxai-api

# Check machine status and health
flyctl status --app luxai-api

# Update a single secret (triggers automatic redeploy)
flyctl secrets set KEY="new-value" --app luxai-api

# Manual redeploy (e.g. after code push without CI)
cd apps/api && flyctl deploy --remote-only

# Check Fly.io billing / usage
flyctl billing show
```

---

## Troubleshooting

### App won't start on Fly.io

```bash
flyctl logs --app luxai-api
# Look for: "pydantic_core.ValidationError" → missing secret
# Fix: flyctl secrets set MISSING_VAR="value" --app luxai-api

# Check all currently set secrets (shows keys, not values)
flyctl secrets list --app luxai-api
```

### Health check failing

```bash
# Test directly
curl https://luxai-api.fly.dev/api/v1/health

# Common causes:
# - UPSTASH_REDIS_URL secret not set (redis: "error")
# - SUPABASE_SERVICE_ROLE_KEY wrong (supabase: "error")
# - TRADIER_API_KEY expired (tradier: "error" — non-fatal for startup)
```

### CORS errors in browser

```bash
# Confirm CORS_ORIGINS includes your exact Pages URL (no trailing slash)
flyctl secrets list --app luxai-api | grep CORS

# Update if needed
flyctl secrets set CORS_ORIGINS="https://luxai-web.pages.dev" --app luxai-api
```

### Shadow banner not visible

1. Confirm `NEXT_PUBLIC_API_URL` on Cloudflare Pages = `https://luxai-api.fly.dev`
2. Confirm shadow mode activated: `POST /api/v1/trading/shadow/activate`
3. Browser devtools → Network → look for `shadow-status` call returning `{"is_active": true}`

### GitHub Actions deploy failing

```bash
# Test FLY_API_TOKEN works
FLY_API_TOKEN=<your-token> flyctl status --app luxai-api

# Test Cloudflare token works
CLOUDFLARE_API_TOKEN=<your-token> wrangler whoami
```

---

## .gitignore Confirmation

`.env` is protected from being committed. Confirmed entry in `.gitignore`:

```
.env
.env.local
.env.production
.env.staging
.env.*.local
!.env.example
```

Never commit `.env`. All secrets go into `fly secrets set` (backend) or
Cloudflare dashboard Environment Variables (frontend).

---

## Files Changed by This Guide

| File                           | Status     | Purpose                                                        |
| ------------------------------ | ---------- | -------------------------------------------------------------- |
| `apps/api/fly.toml`            | Created    | Fly.io service config — build, healthcheck, VM spec, auto-stop |
| `apps/api/Dockerfile`          | Updated    | python:3.11-slim, `--workers 1`, shell-form CMD with `$PORT`   |
| `apps/api/railway.toml`        | Deprecated | Replaced by fly.toml — kept to avoid broken references         |
| `apps/api/Procfile`            | Unchanged  | Fallback — ignored when fly.toml is present                    |
| `scripts/start.sh`             | Updated    | Fly.io-compatible, PORT defaults to 8000                       |
| `apps/web/wrangler.toml`       | Unchanged  | Cloudflare Pages config                                        |
| `.github/workflows/deploy.yml` | Created    | Push-to-main CI/CD — Fly.io backend then CF Pages frontend     |
| `DEPLOY_GUIDE.md`              | This file  | Full deployment reference                                      |
