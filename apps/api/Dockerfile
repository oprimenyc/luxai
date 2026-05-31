FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ─── builder ────────────────────────────────────────────────────────────
FROM base AS builder

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN pip install hatchling

WORKDIR /app
COPY pyproject.toml ./
# Install deps only (no source yet) — layer is cached until pyproject changes
RUN pip install --no-deps .

COPY src ./src
RUN pip install .

# ─── runner ─────────────────────────────────────────────────────────────
FROM base AS runner

RUN addgroup --system --gid 1001 appgroup && \
    adduser  --system --uid 1001 --gid 1001 appuser

WORKDIR /app

# Copy installed packages from builder, not dev tools
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src ./src
COPY pyproject.toml ./

USER appuser
EXPOSE 8000

# Fly.io sets $PORT to match internal_port (8000).
# --workers 1 is required: the shadow trade monitor runs as an asyncio
# background task inside the lifespan. Multiple workers = multiple monitors =
# duplicate trade closings. Do not increase workers without extracting the
# monitor into a standalone Fly cron machine.
CMD exec uvicorn src.main:app \
      --host 0.0.0.0 \
      --port "${PORT:-8000}" \
      --workers 1 \
      --log-level info \
      --access-log
