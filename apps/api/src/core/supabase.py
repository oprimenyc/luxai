"""
Supabase client factory — service role and anon clients.

Path: apps/api/src/core/supabase.py
Security: Service role key used ONLY for server-side writes (shadow mode, kill switch,
          idempotency ledger). Never returned to the client or used in user-facing reads
          that could expose other users' data — RLS enforces that at the DB layer.
          Anon key used for client-side reads where the user's JWT scopes the data.
          Fails fast at startup if SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY are absent.
Scale: Each FastAPI request gets a new async client (supabase-py is not connection-pooled
       in the same way as psycopg — the async client holds an httpx session internally).
       For Railway single-instance deployment this is fine; revisit with a connection
       pool wrapper if request volume exceeds ~500 req/s.
"""

from __future__ import annotations

import structlog
from fastapi import Depends
from supabase import AsyncClient, acreate_client

from src.config import settings

log = structlog.get_logger(__name__)

# ── Startup validation ────────────────────────────────────────────────────────

def _assert_supabase_configured() -> None:
    """Raise at startup if required Supabase env vars are missing."""
    missing = []
    if not getattr(settings, "supabase_url", ""):
        missing.append("SUPABASE_URL")
    if not getattr(settings, "supabase_service_role_key", ""):
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        raise RuntimeError(
            f"Supabase misconfigured — missing env vars: {', '.join(missing)}. "
            "Set them in .env before starting the API."
        )


# ── Client factories ──────────────────────────────────────────────────────────

async def get_service_client() -> AsyncClient:
    """
    Return a Supabase AsyncClient authenticated with the service role key.

    Use for: server-side writes that bypass RLS — shadow mode config, kill switch
    ledger, idempotency log. Never use this in code paths reachable by user input
    without explicit RLS consideration.
    """
    _assert_supabase_configured()
    return await acreate_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_role_key,
    )


async def get_anon_client() -> AsyncClient:
    """
    Return a Supabase AsyncClient authenticated with the anon key.

    Use for: reads where the calling user's JWT scopes the data via RLS.
    The caller must set the Authorization header on the client before use:
        client.auth.set_session(access_token, refresh_token)
    """
    _assert_supabase_configured()
    anon_key = getattr(settings, "supabase_anon_key", "")
    if not anon_key:
        raise RuntimeError(
            "SUPABASE_ANON_KEY not configured. Set it in .env for client-scoped reads."
        )
    return await acreate_client(
        supabase_url=settings.supabase_url,
        supabase_key=anon_key,
    )


# ── FastAPI dependencies ──────────────────────────────────────────────────────

async def get_supabase_client() -> AsyncClient:
    """
    FastAPI dependency — returns the service role client.

    Alias for get_service_client() for use as a Depends() injection target.
    All B1 services (shadow, kill switch, idempotency) inject this.
    """
    return await get_service_client()
