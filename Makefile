# ══════════════════════════════════════════════════════════════════════════════
# LuxAI — Makefile
# Usage: make <target>
# ══════════════════════════════════════════════════════════════════════════════

.DEFAULT_GOAL := help
.PHONY: help setup install dev dev-web dev-api dev-orchestrator \
        build typecheck lint format test \
        docker-dev docker-prod docker-down docker-logs \
        db-migrate db-reset \
        husky-install clean

# ── Colours ───────────────────────────────────────────────────────────────────
CYAN  := \033[36m
RESET := \033[0m
BOLD  := \033[1m

help: ## Show this help
	@printf "$(BOLD)LuxAI Monorepo$(RESET)\n\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────────────

setup: install husky-install ## Full first-time setup
	@printf "\n✅ Setup complete. Copy .env.example files and run 'make dev'.\n"

install: ## Install all Node.js dependencies
	pnpm install --frozen-lockfile

husky-install: ## Install Husky git hooks
	pnpm dlx husky
	chmod +x .husky/pre-commit .husky/commit-msg .husky/pre-push

install-python: ## Install Python dependencies for all services
	cd apps/api && pip install -e ".[dev]"
	cd apps/orchestrator && pip install -e ".[dev]"

# ── Development ───────────────────────────────────────────────────────────────

dev: ## Start all services with Docker Compose (hot reload)
	docker compose up --build --watch

dev-web: ## Start Next.js dev server only
	pnpm --filter @luxai/web run dev

dev-api: ## Start FastAPI dev server only
	cd apps/api && uvicorn src.main:app --reload --port 8000

dev-orchestrator: ## Start LangGraph orchestrator dev server only
	cd apps/orchestrator && uvicorn src.main:app --reload --port 8001

# ── Quality ───────────────────────────────────────────────────────────────────

typecheck: ## TypeScript typecheck across all packages
	pnpm run typecheck

typecheck-api: ## mypy typecheck for FastAPI service
	cd apps/api && mypy src

typecheck-orchestrator: ## mypy typecheck for orchestrator service
	cd apps/orchestrator && mypy src

lint: ## ESLint all TypeScript packages
	pnpm --filter @luxai/web run lint

lint-python: ## Ruff lint all Python services
	cd apps/api && ruff check src
	cd apps/orchestrator && ruff check src

format: ## Format all files with Prettier & Ruff
	pnpm --filter @luxai/web exec prettier --write .
	cd apps/api && ruff format src
	cd apps/orchestrator && ruff format src

format-check: ## Check formatting without writing
	pnpm --filter @luxai/web exec prettier --check .
	cd apps/api && ruff format --check src
	cd apps/orchestrator && ruff format --check src

build: ## Build all packages for production
	pnpm run build

# ── Testing ───────────────────────────────────────────────────────────────────

test: test-api test-orchestrator ## Run all tests

test-api: ## Run FastAPI tests
	cd apps/api && pytest --cov=src --cov-report=term-missing -q

test-orchestrator: ## Run orchestrator tests
	cd apps/orchestrator && pytest -q

# ── Docker ────────────────────────────────────────────────────────────────────

docker-dev: ## Build and start all containers (development)
	docker compose up --build -d

docker-prod: ## Build and start all containers (production)
	docker compose -f docker-compose.prod.yml up --build -d

docker-down: ## Stop all containers
	docker compose down

docker-down-prod: ## Stop production containers
	docker compose -f docker-compose.prod.yml down

docker-logs: ## Tail logs from all containers
	docker compose logs -f

docker-logs-api: ## Tail API container logs
	docker compose logs -f api

docker-logs-orchestrator: ## Tail orchestrator container logs
	docker compose logs -f orchestrator

docker-ps: ## Show running containers
	docker compose ps

# ── Database ──────────────────────────────────────────────────────────────────

db-migrate: ## Push Supabase schema migrations
	pnpm --filter @workspace/db run push

db-types: ## Regenerate Supabase TypeScript types
	@echo "Run: supabase gen types typescript --project-id <id> > packages/supabase/src/types/database.ts"

# ── Clean ─────────────────────────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	find . -name ".next" -type d -not -path "*/node_modules/*" -exec rm -rf {} + 2>/dev/null || true
	find . -name "dist" -type d -not -path "*/node_modules/*" -exec rm -rf {} + 2>/dev/null || true
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".mypy_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name ".ruff_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.tsbuildinfo" -delete 2>/dev/null || true
	@echo "✅ Clean complete."

clean-all: clean ## Remove build artifacts AND node_modules
	find . -name "node_modules" -type d -not -path "*/node_modules/node_modules" -exec rm -rf {} + 2>/dev/null || true
	find . -name ".venv" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Deep clean complete."
