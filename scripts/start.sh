#!/usr/bin/env bash
# Path: scripts/start.sh
# Security: No secrets — all env vars injected at runtime by Fly.io.
# Scale: Single worker enforced. See apps/api/fly.toml for rationale.
#
# Starts the LuxAI FastAPI backend.
# Used by: Fly.io (via Dockerfile CMD), local testing without Docker.
# PORT defaults to 8000 — matches fly.toml internal_port.

set -euo pipefail

: "${PORT:=8000}"

echo "[start.sh] Starting LuxAI API on port ${PORT}"
echo "[start.sh] Environment: ${ENVIRONMENT:-unknown}"

exec uvicorn src.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers 1 \
  --log-level info \
  --access-log
