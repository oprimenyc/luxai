# LuxAI — Setup Guide

Complete guide for getting the LuxAI multi-agent AI operating system running locally, in staging, and in production.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Node.js | ≥ 22 | [nodejs.org](https://nodejs.org) |
| pnpm | ≥ 10 | `npm i -g pnpm` |
| Python | ≥ 3.12 | [python.org](https://python.org) |
| Docker | ≥ 27 | [docker.com](https://docker.com) |
| Git | ≥ 2.40 | System package manager |

---

## Repository Structure

```
luxai/
├── apps/
│   ├── web/              # Next.js 15 frontend (TypeScript, Tailwind v4)
│   ├── api/              # FastAPI backend (Python 3.12, Pydantic v2)
│   └── orchestrator/     # LangGraph multi-agent orchestrator (Python 3.12)
├── packages/
│   ├── ui/               # Shared React component library
│   ├── types/            # Shared TypeScript type definitions
│   ├── supabase/         # Supabase client (browser + server + service)
│   ├── ai-sdk/           # Typed orchestrator HTTP client + model registry
│   └── config/           # Shared ESLint, TSConfig, Prettier configs
├── infra/
│   ├── docker/           # Nginx configs + DB init SQL
│   └── cloudflare/       # Wrangler config + routes manifest
├── .github/
│   └── workflows/        # CI (lint/typecheck/build) + deploy (staging/prod)
├── docker-compose.yml     # Development stack
├── docker-compose.prod.yml # Production stack
├── Makefile               # All developer commands
└── SETUP.md               # This file
```

---

## 1. First-Time Setup

```bash
# Clone the repo
git clone https://github.com/your-org/luxai.git
cd luxai

# Install Node.js dependencies + Husky git hooks
make setup

# Install Python dependencies
make install-python
```

---

## 2. Environment Variables

Copy the example files and fill in your values:

```bash
# Web app
cp apps/web/.env.local.example apps/web/.env.local

# FastAPI backend
cp apps/api/.env.example apps/api/.env

# LangGraph orchestrator
cp apps/orchestrator/.env.example apps/orchestrator/.env
```

### Required values

**Supabase** (create a project at [supabase.com](https://supabase.com)):
- `SUPABASE_URL` — Project URL from Settings → API
- `SUPABASE_ANON_KEY` — Anon key from Settings → API
- `SUPABASE_SERVICE_ROLE_KEY` — Service role key (server-side only, keep secret)
- `SUPABASE_JWT_SECRET` — JWT secret from Settings → API

**LLM**:
- `OPENAI_API_KEY` — Required for GPT-4o (orchestrator + API)
- `ANTHROPIC_API_KEY` — Optional, enables Claude fallback

**LangSmith** (optional, for tracing):
- `LANGCHAIN_API_KEY` — From [smith.langchain.com](https://smith.langchain.com)
- `LANGCHAIN_TRACING_V2=true`

---

## 3. Database Setup

### Supabase (recommended for production)

Run the initialization SQL in your Supabase SQL editor:

```bash
# Copy the contents of this file into Supabase → SQL Editor → New query
cat infra/docker/postgres/init.sql
```

### Local PostgreSQL (development via Docker)

```bash
# Start the full dev stack — Postgres is included
make docker-dev

# Or start Postgres only
docker compose up postgres -d
```

---

## 4. Development

### Option A — Docker (recommended, all services hot-reload)

```bash
make dev
# or
docker compose up --build --watch
```

Services:
| Service | URL |
|---------|-----|
| Web (Next.js) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 |
| Orchestrator (LangGraph) | http://localhost:8001 |
| Nginx proxy | http://localhost:80 |
| API docs | http://localhost:8000/api/docs |
| Orchestrator docs | http://localhost:8001/docs |
| Prometheus metrics | http://localhost:8000/api/metrics |

### Option B — Individual services

```bash
# Terminal 1: Next.js
make dev-web

# Terminal 2: FastAPI
make dev-api

# Terminal 3: LangGraph orchestrator
make dev-orchestrator
```

---

## 5. Code Quality

```bash
# TypeScript typecheck
make typecheck

# Python typecheck (mypy)
make typecheck-api
make typecheck-orchestrator

# ESLint
make lint

# Ruff (Python lint)
make lint-python

# Format everything
make format

# Format check (CI mode)
make format-check
```

---

## 6. Testing

```bash
# All tests
make test

# FastAPI tests only (with coverage)
make test-api

# Orchestrator tests only
make test-orchestrator
```

---

## 7. Commit Conventions

This repo uses [Conventional Commits](https://www.conventionalcommits.org/), enforced by commitlint:

```
<type>(<scope>): <subject>

Types:  feat | fix | docs | style | refactor | perf | test | build | ci | chore | revert
Scopes: web | api | orchestrator | ui | types | supabase | ai-sdk | config | infra | ci

Examples:
  feat(api): add session streaming endpoint
  fix(web): correct dashboard redirect on logout
  ci: add Docker build check to CI pipeline
```

---

## 8. Staging Deployment

Staging deploys automatically on every push to `develop`:

- **Web** → Cloudflare Pages (`luxai-staging`)
- **API + Orchestrator** → Docker images pushed to `ghcr.io/<org>/luxai/api:staging-latest`

Required GitHub secrets:
```
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

---

## 9. Production Deployment

Production deploys on every Git tag matching `v*.*.*`:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Pipeline:
1. Builds versioned Docker images for API + Orchestrator
2. Pushes to `ghcr.io/<org>/luxai/{api,orchestrator}:1.0.0`
3. SSH deploys to your production server via `docker compose -f docker-compose.prod.yml`
4. Builds + deploys Next.js to Cloudflare Pages (production branch)

Required GitHub secrets:
```
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY
NEXT_PUBLIC_APP_URL
NEXT_PUBLIC_API_URL
PROD_HOST
PROD_USER
PROD_SSH_KEY
```

### Production server setup

```bash
# On your production server
mkdir -p /opt/luxai
cd /opt/luxai

# Copy compose file and env files
scp docker-compose.prod.yml user@server:/opt/luxai/
scp apps/api/.env.production user@server:/opt/luxai/apps/api/.env.production
scp apps/orchestrator/.env.production user@server:/opt/luxai/apps/orchestrator/.env.production

# First run
docker compose -f docker-compose.prod.yml up -d
```

---

## 10. Cloudflare Pages (Web)

The web app deploys to Cloudflare Pages via `wrangler`:

```bash
cd infra/cloudflare

# Configure your project
wrangler pages project create luxai

# Set secrets
wrangler secret put NEXT_PUBLIC_SUPABASE_URL
wrangler secret put NEXT_PUBLIC_SUPABASE_ANON_KEY
wrangler secret put SUPABASE_SERVICE_ROLE_KEY

# Deploy manually
wrangler pages deploy ../../apps/web/.next --project-name=luxai
```

---

## 11. Supabase Type Generation

After updating the database schema, regenerate TypeScript types:

```bash
supabase gen types typescript \
  --project-id <your-project-id> \
  > packages/supabase/src/types/database.ts
```

---

## 12. LangSmith Tracing

To enable full LangGraph tracing:

```bash
# In apps/orchestrator/.env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-key
LANGCHAIN_PROJECT=luxai-orchestrator
```

Traces appear at [smith.langchain.com](https://smith.langchain.com) under your project.

---

## Troubleshooting

**`pnpm install` fails with lockfile error**
→ Run `pnpm install --no-frozen-lockfile` once, then commit the updated lockfile.

**Docker build fails for Python services**
→ Ensure `pyproject.toml` lists all dependencies. Run `pip install -e ".[dev]"` locally first to confirm.

**Supabase JWT auth fails**
→ Confirm `SUPABASE_JWT_SECRET` matches your project's JWT secret exactly (Settings → API → JWT Settings).

**LangGraph orchestrator hangs**
→ Check `MAX_ITERATIONS` isn't too high. Default is 10, max is 25. Add LangSmith tracing to inspect the graph.

**Next.js type errors after package changes**
→ Run `pnpm install` then `pnpm run typecheck` from root.
