# LuxAI — Multi-Agent AI Operating System

Enterprise-grade multi-agent AI orchestration platform combining Next.js 15, FastAPI, and LangGraph for intelligent automation at scale.

## Run & Operate

### Node.js (pnpm workspace)
- `pnpm install` — install all workspace dependencies
- `pnpm run typecheck` — full typecheck across all TypeScript packages
- `pnpm run build` — typecheck + build all packages
- `pnpm run lint` — ESLint across all packages
- `pnpm run format` — Prettier format everything
- `pnpm --filter @luxai/web run dev` — Next.js dev server (port from `PORT` env)
- `pnpm --filter @workspace/api-server run dev` — original Express API (port 5000)

### Python services
- `cd apps/api && uvicorn src.main:app --reload --port 8000` — FastAPI
- `cd apps/orchestrator && uvicorn src.main:app --reload --port 8001` — LangGraph orchestrator

### Docker (all services together)
- `docker compose up --build --watch` — full dev stack with hot reload
- `docker compose -f docker-compose.prod.yml up -d` — production stack
- `make help` — all available commands

## Stack

### Frontend (`apps/web`)
- Next.js 15 with App Router, Turbopack, React 19
- Tailwind CSS v4, shadcn/ui patterns
- TanStack Query v5, Supabase SSR, next-themes
- Deployed to Cloudflare Pages

### Backend (`apps/api`)
- FastAPI + Uvicorn (Python 3.12, Pydantic v2)
- Supabase (PostgreSQL + Auth + RLS)
- Redis for caching/queues
- Prometheus metrics + structlog

### Orchestrator (`apps/orchestrator`)
- LangGraph supervisor graph (researcher → executor → critic loop)
- Multi-model support: GPT-4o + Claude 3.5 Sonnet
- LangSmith tracing integration
- SSE streaming responses

### Shared Packages
- `@luxai/ui` — React component library (Button, Card, Badge)
- `@luxai/types` — TypeScript type definitions (Agent, Session, API)
- `@luxai/supabase` — Supabase browser/server/service clients
- `@luxai/ai-sdk` — Typed orchestrator HTTP client + model registry
- `@luxai/config` — ESLint, TSConfig, Prettier shared configs

## Where things live

- DB schema source of truth: `infra/docker/postgres/init.sql`
- Supabase types: `packages/supabase/src/types/database.ts`
- API contracts: `apps/api/src/models/` (Pydantic) + `packages/types/src/` (TypeScript)
- LangGraph graphs: `apps/orchestrator/src/graphs/supervisor.py`
- Agent state: `apps/orchestrator/src/state/agent_state.py`
- Nginx configs: `infra/docker/nginx.conf` (dev) + `nginx.prod.conf` (prod)
- CI/CD: `.github/workflows/ci.yml`, `deploy-staging.yml`, `deploy-production.yml`
- Cloudflare: `infra/cloudflare/wrangler.toml`

## Architecture decisions

- **Supervisor pattern**: LangGraph uses a researcher → executor → critic loop with conditional re-routing until the critic passes or max_iterations is reached.
- **Service isolation**: API and orchestrator are separate Python services — API handles CRUD + auth, orchestrator handles stateful LLM workloads. The frontend never calls the orchestrator directly.
- **Supabase JWT validation**: FastAPI validates Supabase JWTs directly using `python-jose` — no separate auth service needed.
- **Cloudflare + Docker hybrid**: Frontend deploys to Cloudflare Pages (edge, free SSL); backend deploys to a VPS via Docker Compose — avoids serverless cold starts for long-running LangGraph runs.
- **Contract-first types**: `packages/types` is the single source of truth for TypeScript interfaces; `apps/api/src/models` is the source of truth for Python. Both mirror each other manually (no codegen between Python ↔ TypeScript to keep the stack simple).

## Product

- **Agent management** — create, configure, and manage AI agents with capability declarations and model selection
- **Session orchestration** — run multi-step agentic sessions via the LangGraph supervisor (researcher → executor → critic)
- **Real-time streaming** — SSE streaming for long-running agent sessions
- **Monitoring** — Prometheus metrics on all services, LangSmith tracing for LangGraph
- **Auth** — Supabase Auth with JWT validation and Row Level Security on all tables

## User preferences

- Enterprise-grade, no placeholder code
- Strict TypeScript, ruff + mypy for Python
- Conventional commits enforced by commitlint + Husky
- All env vars documented in `.env.example` files

## Gotchas

- Always run `pnpm install` from the workspace root, never from individual package directories.
- Python services use `uvicorn` directly in dev but `--workers 4` in Docker prod — do not use `--reload` in production.
- Supabase `createServerClient` must be called inside a function (not at module level) because it reads `cookies()` from Next.js headers.
- LangGraph's `ainvoke` blocks for the full run — use `astream_events` for streaming to the client.
- `SUPABASE_JWT_SECRET` must match exactly what's in Supabase Settings → API → JWT Settings.

## Pointers

- Full setup guide: `SETUP.md`
- All developer commands: `make help`
- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
