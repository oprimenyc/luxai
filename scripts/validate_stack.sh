#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# LuxAI Stack Validation Script
# Checks all services are running and healthy before proceeding.
# Usage: ./scripts/validate_stack.sh [--env .env.path]
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
API_URL="${LUXAI_API_URL:-http://localhost:8000}"
ORCHESTRATOR_URL="${LUXAI_ORCHESTRATOR_URL:-http://localhost:8001}"
WEB_URL="${LUXAI_WEB_URL:-http://localhost:3000}"
TIMEOUT=5
PASS=0
FAIL=0

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
pass() { echo -e "  ${GREEN}✓${RESET} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${RESET} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "  ${YELLOW}⚠${RESET} $1"; }
section() { echo -e "\n${BLUE}▶ $1${RESET}"; }

http_ok() {
  local url="$1"
  local expected_status="${2:-200}"
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$url" 2>/dev/null || echo "000")
  [ "$status" = "$expected_status" ]
}

json_field() {
  # Extracts a JSON field value using grep/sed (no jq dependency)
  curl -s --max-time "$TIMEOUT" "$1" 2>/dev/null | grep -o "\"$2\":\"[^\"]*\"" | cut -d'"' -f4
}

# ══════════════════════════════════════════════════════════════════════════════
echo -e "${BLUE}══════════════════════════════════════════${RESET}"
echo -e "${BLUE}  LuxAI Stack Validation${RESET}"
echo -e "${BLUE}══════════════════════════════════════════${RESET}"

# ── 1. Environment ─────────────────────────────────────────────────────────────
section "Environment Variables"

required_vars=(
  "SUPABASE_URL"
  "SUPABASE_ANON_KEY"
  "SUPABASE_SERVICE_ROLE_KEY"
  "SUPABASE_JWT_SECRET"
)
optional_vars=(
  "OPENAI_API_KEY"
  "ANTHROPIC_API_KEY"
  "ALPACA_API_KEY"
  "ALPACA_API_SECRET"
  "REDIS_URL"
  "LANGCHAIN_API_KEY"
)

for var in "${required_vars[@]}"; do
  if [ -n "${!var:-}" ]; then
    pass "$var is set"
  else
    fail "$var is MISSING (required)"
  fi
done

for var in "${optional_vars[@]}"; do
  if [ -n "${!var:-}" ]; then
    pass "$var is set"
  else
    warn "$var is not set (optional)"
  fi
done

# ── 2. FastAPI ─────────────────────────────────────────────────────────────────
section "FastAPI (api)"

if http_ok "$API_URL/api/health"; then
  pass "GET /api/health → 200"

  status=$(json_field "$API_URL/api/health" "status")
  version=$(json_field "$API_URL/api/health" "version")
  env=$(json_field "$API_URL/api/health" "environment")

  if [ "$status" = "ok" ]; then
    pass "Health status: ok (v$version, $env)"
  else
    warn "Health status: $status (degraded dependencies)"
  fi
else
  fail "GET $API_URL/api/health — not reachable (is the API running?)"
fi

if http_ok "$API_URL/api/ready"; then
  pass "GET /api/ready → 200 (all dependencies healthy)"
else
  warn "GET /api/ready failed — some dependencies may be unavailable"
fi

# ── 3. Orchestrator ───────────────────────────────────────────────────────────
section "LangGraph Orchestrator"

if http_ok "$ORCHESTRATOR_URL/health"; then
  pass "GET /health → 200"
else
  warn "Orchestrator not reachable at $ORCHESTRATOR_URL (optional in dev)"
fi

# ── 4. Frontend ───────────────────────────────────────────────────────────────
section "Next.js Frontend"

if http_ok "$WEB_URL"; then
  pass "GET / → 200"
else
  warn "Frontend not reachable at $WEB_URL (may not be started)"
fi

# ── 5. API routes ─────────────────────────────────────────────────────────────
section "API Route Smoke Tests"

routes=(
  "/api/health"
  "/api/ready"
  "/api/docs"
)

for route in "${routes[@]}"; do
  if http_ok "$API_URL$route"; then
    pass "GET $route → 200"
  else
    fail "GET $route → not OK"
  fi
done

# ── 6. Trading status ─────────────────────────────────────────────────────────
section "Paper Trading"

if http_ok "$API_URL/api/v1/trading/status"; then
  configured=$(json_field "$API_URL/api/v1/trading/status" "configured")
  if [ "$configured" = "true" ]; then
    pass "Alpaca paper trading configured"
  else
    warn "Alpaca credentials not set — trading endpoints will return 503"
  fi

  live=$(json_field "$API_URL/api/v1/trading/status" "live_trading_enabled")
  if [ "$live" = "false" ]; then
    pass "Live trading: disabled (correct)"
  else
    fail "CRITICAL: live_trading_enabled is not false!"
  fi
else
  fail "Trading status endpoint not reachable"
fi

# ── 7. Docker (if running) ────────────────────────────────────────────────────
section "Docker Compose (if available)"

if command -v docker &>/dev/null && docker compose ps &>/dev/null 2>&1; then
  services=$(docker compose ps --format "{{.Name}}\t{{.Status}}" 2>/dev/null || true)
  if [ -n "$services" ]; then
    echo "$services" | while IFS=$'\t' read -r name status; do
      if echo "$status" | grep -q "Up\|running"; then
        pass "Docker: $name running"
      else
        fail "Docker: $name status: $status"
      fi
    done
  else
    warn "No Docker services found"
  fi
else
  warn "Docker not available — skipping container checks"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}══════════════════════════════════════════${RESET}"
echo -e "  Passed: ${GREEN}${PASS}${RESET}  Failed: ${RED}${FAIL}${RESET}"
echo -e "${BLUE}══════════════════════════════════════════${RESET}"

if [ "$FAIL" -gt 0 ]; then
  echo -e "${RED}Validation failed — $FAIL check(s) did not pass.${RESET}"
  exit 1
else
  echo -e "${GREEN}All required checks passed.${RESET}"
  exit 0
fi
