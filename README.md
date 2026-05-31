# LuxAI OS / .fylr

AI-assisted options trading command center for small account traders ($100–$10,000). Surfaces affordable, risk-scored, budget-adjusted options recommendations from any trade tip. Paper trading only — live trading is locked behind a two-week shadow gate and manual journal audit.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLIENT (Browser / Mobile)                    │
│   Next.js 15 App Router · Tailwind · shadcn/ui · Framer Motion      │
│   Hosted: Cloudflare Pages                                           │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │ HTTPS + JWT (Supabase Auth)
┌─────────────────────────────────▼────────────────────────────────────┐
│                         API GATEWAY (FastAPI)                         │
│   /api/v1/trading     — Paper order submission + shadow interception  │
│   /api/v1/workbench   — Trade Idea Workbench (B3)                    │
│   /api/v1/memory      — pgvector semantic memory                     │
│   /api/v1/governance  — Risk policies                                │
│   Hosted: Railway                                                     │
└──────┬────────────────────┬──────────────────────┬───────────────────┘
       │                    │                       │
┌──────▼──────┐    ┌────────▼────────┐    ┌────────▼────────┐
│   Supabase  │    │  Upstash Redis  │    │   Alpaca Paper  │
│  PostgreSQL │    │  SETNX locks    │    │   Broker API    │
│  + pgvector │    │  Shadow state   │    │   (paper only)  │
│  + Auth     │    │  Idempotency    │    └─────────────────┘
│  + RLS      │    └─────────────────┘
└──────┬──────┘
       │
┌──────▼──────┐    ┌─────────────────┐
│ Orchestrator│    │   Tradier API   │
│  (LangGraph)│    │  Options chains │
│  Railway    │    │  (free tier)    │
└─────────────┘    └─────────────────┘
```

**Shadow mode** sits between the API gateway and Alpaca. While active, all order submissions are intercepted, nullified, and logged. No order ever reaches Alpaca during shadow mode.

---

## Prerequisites

| Tool           | Version  | Notes                                          |
| -------------- | -------- | ---------------------------------------------- |
| Node.js        | 22.x LTS | pnpm requires this minimum                     |
| pnpm           | 9.x      | `npm install -g pnpm`                          |
| Python         | 3.12+    | 3.14 tested in CI                              |
| uv             | latest   | `pip install uv` — fast Python package manager |
| Docker Desktop | 4.x      | For local Redis                                |
| Git            | 2.x      | —                                              |

External accounts required (all free tier):

| Service        | Purpose                    | URL                           |
| -------------- | -------------------------- | ----------------------------- |
| Supabase       | Database + Auth            | https://supabase.com          |
| Upstash Redis  | Shadow state + idempotency | https://upstash.com           |
| Alpaca Markets | Paper broker               | https://alpaca.markets        |
| Tradier        | Options chains (B3)        | https://developer.tradier.com |
| Cloudflare     | Frontend hosting           | https://cloudflare.com        |
| Railway        | Backend hosting            | https://railway.app           |

---

## Environment Variables

Copy `.env.example` to `.env` in the repo root and fill in all values.

### General

| Variable      | Description          | Example       |
| ------------- | -------------------- | ------------- |
| `ENVIRONMENT` | Runtime environment  | `development` |
| `DEBUG`       | Enable debug logging | `false`       |

### Frontend (Next.js)

| Variable                        | Description                              |
| ------------------------------- | ---------------------------------------- |
| `NEXT_PUBLIC_APP_URL`           | Public URL of the web app                |
| `NEXT_PUBLIC_API_URL`           | Public URL of the FastAPI backend        |
| `NEXT_PUBLIC_ORCHESTRATOR_URL`  | Public URL of the LangGraph orchestrator |
| `NEXT_PUBLIC_SUPABASE_URL`      | Your Supabase project URL                |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key (safe for browser)     |

### Backend (FastAPI)

| Variable                    | Description                                             |
| --------------------------- | ------------------------------------------------------- |
| `SUPABASE_URL`              | Your Supabase project URL                               |
| `SUPABASE_ANON_KEY`         | Supabase anon key                                       |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (backend only — never expose) |
| `SUPABASE_JWT_SECRET`       | JWT secret from Supabase project settings               |
| `REDIS_URL_API`             | Upstash Redis URL for the API service                   |
| `API_PORT`                  | FastAPI listening port (default `8000`)                 |
| `CORS_ORIGINS`              | Comma-separated allowed origins                         |

### Broker

| Variable            | Description                  |
| ------------------- | ---------------------------- |
| `ALPACA_API_KEY`    | Alpaca paper account API key |
| `ALPACA_API_SECRET` | Alpaca paper account secret  |

> **IMPORTANT:** Use paper account keys only. The engine validates account type at connect time and raises an error if a live account key is detected.

### Options Data

| Variable          | Description                                          |
| ----------------- | ---------------------------------------------------- |
| `TRADIER_API_KEY` | Tradier free-tier API key (for Workbench, Phase B3)  |
| `TRADIER_SANDBOX` | Use Tradier sandbox (`true`) or production (`false`) |

### AI

| Variable            | Description                                |
| ------------------- | ------------------------------------------ |
| `ANTHROPIC_API_KEY` | Claude API key (orchestrator)              |
| `OPENAI_API_KEY`    | OpenAI key (optional fallback)             |
| `DEFAULT_MODEL`     | Default Claude model (`claude-sonnet-4-6`) |

### Observability (optional)

| Variable               | Description                               |
| ---------------------- | ----------------------------------------- |
| `LANGCHAIN_API_KEY`    | LangSmith tracing key                     |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing (`true`/`false`) |
| `OTLP_ENDPOINT`        | OpenTelemetry collector endpoint          |

---

## Supabase Setup

1. Create a new Supabase project at https://supabase.com/dashboard.

2. Copy your project URL and keys from **Project Settings → API**:
   - **Project URL** → `SUPABASE_URL`
   - **anon / public key** → `SUPABASE_ANON_KEY` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - **service_role key** (secret — never expose to browser) → `SUPABASE_SERVICE_ROLE_KEY`

3. Copy the **JWT Secret** from **Project Settings → API → JWT Settings** → `SUPABASE_JWT_SECRET`.

4. Set all four values in your `.env`:

   ```
   SUPABASE_URL=https://xxxxxxxxxxxxxxxxxxx.supabase.co
   SUPABASE_ANON_KEY=eyJhbGci...
   SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...
   SUPABASE_JWT_SECRET=your-jwt-secret
   ```

5. Run all migrations in order (via Supabase MCP, CLI, or Dashboard SQL Editor):

   ```
   supabase/migrations/001_shadow_mode.sql        — shadow_mode_config, shadow_trades, shadow_pnl
   supabase/migrations/002_idempotency_ledger.sql — order_idempotency_log
   supabase/migrations/003_system_halts.sql       — system_halts (kill switch audit log)
   supabase/migrations/004_workbench_analyses.sql — workbench_analyses (analysis history)
   ```

   Via CLI: `cd supabase && supabase db push`

6. RLS is enforced in every migration. Verify in **Table Editor → [table] → RLS** — all tables must show "RLS enabled".

> **Service role key note:** The service role key bypasses RLS. It is used only in server-side code (kill switch, shadow mode, idempotency ledger). Never include it in frontend code or API responses.

---

## Upstash Redis Setup

1. Create a free Redis database at https://console.upstash.com.

2. Select **Global** replication for lowest latency.

3. Copy the **Redis URL** from the database dashboard.

4. Set `REDIS_URL_API` in your `.env`:

   ```
   REDIS_URL_API=rediss://default:<password>@<host>.upstash.io:6379
   ```

   Note the `rediss://` (TLS) prefix — Upstash requires TLS in production.

5. For local development, you can use a local Redis via Docker:
   ```bash
   docker run -d -p 6379:6379 redis:7-alpine
   # Then set:
   REDIS_URL_API=redis://localhost:6379/0
   ```

---

## Alpaca Paper Account Setup

1. Sign up at https://alpaca.markets and verify your email.

2. Go to your dashboard: https://app.alpaca.markets/paper/dashboard/overview  
   Make sure you are on the **Paper Trading** tab (not Live Trading).

3. Click **API Keys** in the left sidebar → **Generate New Key**.

4. Copy both values to your `.env`:

   ```
   ALPACA_API_KEY=PKxxxxxxxxxxxxxxxxxxxxxxxx
   ALPACA_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

   The key starts with `PK` for paper accounts. Live keys start with `AK` — those are rejected at startup.

5. The backend calls `GET /v2/account` at startup and confirms `paper_trading: true`. If a live key is detected, the application raises immediately and refuses to start. This is intentional and cannot be bypassed.

6. Required `.env` variables:
   | Variable | Where to find it |
   |---|---|
   | `ALPACA_API_KEY` | Paper dashboard → API Keys |
   | `ALPACA_API_SECRET` | Paper dashboard → API Keys (shown once) |

---

## Tradier API Key (Free Tier)

1. Sign up for a free developer account at https://developer.tradier.com/user/sign_up.

2. Once logged in, go to **Dashboard → Applications** → click your app → **API Access**.

3. Your **Sandbox Access Token** is shown on that page. Copy it to your `.env`:

   ```
   TRADIER_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TRADIER_SANDBOX=true
   ```

   Do **not** include the `Bearer ` prefix — the client adds that automatically.

4. The sandbox endpoint is `https://sandbox.tradier.com` (set automatically when `TRADIER_SANDBOX=true`). Sandbox data is simulated — real quotes are from `https://api.tradier.com` (requires a brokerage account or paid plan).

5. Required `.env` variables:
   | Variable | Value |
   |---|---|
   | `TRADIER_API_KEY` | Your sandbox token from the Tradier dashboard |
   | `TRADIER_SANDBOX` | `true` (default) — set to `false` for live chains |

> **Rate limit:** Tradier free tier allows 200 requests/hour. The workbench Redis-caches chains for 60 seconds and quotes for 30 seconds. Normal use stays well under the limit.

---

## Local Development

### 1. Clone and install

```bash
git clone https://github.com/your-org/luxai-os.git
cd luxai-os
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install Node dependencies

```bash
pnpm install
```

### 3. Install Python dependencies (API)

```bash
cd apps/api
uv sync
# Or with pip:
pip install -e ".[dev]"
```

### 4. Start local Redis (if not using Upstash)

```bash
docker run -d --name luxai-redis -p 6379:6379 redis:7-alpine
```

### 5. Start the FastAPI backend

```bash
cd apps/api
uv run uvicorn src.main:app --reload --port 8000
# API docs: http://localhost:8000/api/docs
```

### 6. Start the Next.js frontend

```bash
cd apps/web
pnpm dev
# App: http://localhost:3000
```

### 7. Run both services together (optional one-liner)

```bash
# From repo root — starts backend + frontend in parallel
# Requires tmux or two terminals. Simpler option:
cd apps/api && uv run uvicorn src.main:app --reload --port 8000 &
cd apps/web && pnpm dev
```

Or using `concurrently` if you have it installed:

```bash
npx concurrently \
  "cd apps/api && uv run uvicorn src.main:app --reload --port 8000" \
  "cd apps/web && pnpm dev"
```

### 8. Verify setup

```bash
# Deep trading health check (all services + safety state)
curl http://localhost:8000/api/v1/health | jq .

# Expected when configured:
# {
#   "supabase": "ok",
#   "redis": "ok",
#   "shadow_mode": true,       ← shadow is active (normal/safe)
#   "kill_switch": false,      ← kill switch is off (normal)
#   "tradier": "ok",
#   "alpaca": "ok",
#   "version": "0.1.0",
#   "phase": "B3-complete"
# }

# Shadow mode status (requires auth)
curl -H "Authorization: Bearer <your-jwt>" \
  http://localhost:8000/api/v1/trading/shadow-status
```

---

## Cloudflare Pages Deploy (Frontend)

1. Push your repo to GitHub.

2. In the Cloudflare dashboard, go to **Workers & Pages → Create → Pages → Connect to Git**.

3. Select your repo. Build settings:
   - **Framework preset:** Next.js
   - **Build command:** `cd apps/web && pnpm build`
   - **Build output directory:** `apps/web/.next`
   - **Root directory:** `/`

4. Add all `NEXT_PUBLIC_*` environment variables in **Settings → Environment Variables**.

5. Deploy. Cloudflare Pages handles CDN, HTTPS, and edge caching automatically.

6. Set `NEXT_PUBLIC_API_URL` to your Railway backend URL after deploying the backend.

---

## Railway Backend Deploy

1. Create a new project at https://railway.app.

2. **New Service → GitHub Repo** → select your repo.

3. In service settings:
   - **Root directory:** `apps/api`
   - **Build command:** `pip install uv && uv sync`
   - **Start command:** `uv run uvicorn src.main:app --host 0.0.0.0 --port $PORT`

4. Add all backend environment variables in **Variables**.

5. Set `NEXT_PUBLIC_API_URL` in your Cloudflare Pages env vars to the Railway public URL.

6. Enable **Health checks** pointing to `/api/health`.

---

## Emergency Halt Procedure

If trading needs to be stopped immediately:

### Option 1: API call (fastest)

```bash
curl -X POST \
  -H "Authorization: Bearer <admin-jwt>" \
  http://localhost:8000/api/v1/trading/emergency-halt
```

This cancels all pending orders and locks the engine. The lock survives until the process restarts (in-memory). For a durable halt, see Option 2.

### Option 2: Shadow mode activation (durable)

```bash
curl -X POST \
  -H "Authorization: Bearer <user-jwt>" \
  http://localhost:8000/api/v1/trading/shadow/activate
```

This writes to both Redis and Supabase. It survives restarts. All subsequent order submissions are intercepted and logged as shadow trades.

### Option 3: Kill the process

```bash
# Railway: go to Service → ... → Restart (suspends all processing)
# Local: Ctrl+C in the uvicorn terminal
```

### Verifying halt is active

```bash
curl -H "Authorization: Bearer <jwt>" \
  http://localhost:8000/api/v1/trading/shadow-status
# is_active: true = shadow mode on, no orders reaching broker
```

---

## Troubleshooting

### "Alpaca credentials not configured (503)"

Set `ALPACA_API_KEY` and `ALPACA_API_SECRET` in `.env`. Restart the backend.

### "Shadow mode: Redis write failed"

Check that `REDIS_URL_API` is reachable. The fail-safe is that shadow mode remains **active** — no orders will reach the broker while Redis is unreachable.

### "JWT decode failed / 401 Unauthorized"

Ensure `SUPABASE_JWT_SECRET` matches the secret in your Supabase project settings (**Project Settings → API → JWT Secret**).

### Frontend cannot reach API (CORS error)

Add your frontend URL to `CORS_ORIGINS` in `.env`. Example:

```
CORS_ORIGINS=http://localhost:3000,https://your-app.pages.dev
```

### Redis connection refused (local)

Start the local Redis container:

```bash
docker start luxai-redis
# Or recreate:
docker run -d --name luxai-redis -p 6379:6379 redis:7-alpine
```

### Shadow banner not appearing

The banner defaults to **showing** on all errors (fail-safe). If you don't see it:

1. Check browser console for fetch errors.
2. Verify `NEXT_PUBLIC_API_URL` is set and the backend is running.
3. Verify `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are set.

### Tests failing locally

```bash
cd apps/api
uv run pytest apps/api/tests/ -v
```

Check that `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set — some tests need a live Supabase connection. Unit tests that mock the DB can run without credentials.

---

## Running Tests

```bash
# From repo root
cd apps/api && uv run pytest tests/ -v

# Specific test file
uv run pytest tests/test_engine_safety.py -v

# With coverage
uv run pytest tests/ --cov=src --cov-report=term-missing
```

---

## Shadow Mode — Two-Week Gate

All new accounts start in shadow mode. No orders reach Alpaca while shadow mode is active.

To exit shadow mode:

1. Run shadow mode for **14 consecutive days minimum**.
2. Generate and review the shadow report:
   ```bash
   python packages/workbench/shadow_report.py generate --days 14
   ```
3. Review hit rate, P&L realism, and risk adherence.
4. Admin clears the gate:
   ```bash
   curl -X DELETE \
     -H "Authorization: Bearer <admin-jwt>" \
     http://localhost:8000/api/v1/trading/shadow/deactivate
   ```
5. Only then is a live trading discussion appropriate.

---

## Current Phase Status

| Phase                                    | Status       | Notes                                                                                |
| ---------------------------------------- | ------------ | ------------------------------------------------------------------------------------ |
| B1 — Broker Safety & Durable Risk Guards | **Complete** | 177 tests pass. All 5 safety systems wired and tested.                               |
| B3 — Trade Idea Workbench                | **Complete** | Tradier integration, Greeks engine, scorer, recommender, calendar, API, UI all live. |
| Shadow Mode                              | **Active**   | Default state for all accounts. Two-week run required before any live discussion.    |
| Supabase Migrations                      | **Applied**  | 001–004 applied. All tables with RLS live.                                           |
| Live Trading                             | **Locked**   | Hard-locked until shadow gate passes and admin confirms. No exceptions.              |
| B2 — Options Intelligence Layer          | Not started  | Begins after shadow run completes.                                                   |
| B4 — Whale / Flow Engine                 | Not started  | Depends on B2.                                                                       |

---

_LuxAI OS / .fylr — Dark luxury fintech. Built for small accounts, designed for discipline._
"# luxai"
