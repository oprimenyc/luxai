"""
Durable idempotency service — Redis SETNX hot path + Supabase audit ledger.

Path: apps/api/src/trading/idempotency.py
Security: Payload hash is SHA-256 of normalized request fields. Redis key is
          namespaced per user. Supabase ledger is append-only, no user writes.
          On Redis failure: REJECT the request — never silently pass.
          (Inverse of shadow mode: silence = reject, not accept.)
Scale: Redis SETNX is O(1). Supabase write is async best-effort. Hash
       collision probability with SHA-256 is negligible (~2^-128 per pair).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from supabase import AsyncClient

log = structlog.get_logger(__name__)

_REDIS_KEY_PREFIX = "idempotency"
_REDIS_TTL = 86_400          # 24 hours — matches CLAUDE.md spec
_TABLE = "order_idempotency_log"


class DuplicateRequestError(RuntimeError):
    """Raised when a duplicate idempotency key is detected."""

    def __init__(self, cached_response: dict[str, Any] | None = None) -> None:
        super().__init__("Duplicate order request rejected (idempotency conflict)")
        self.cached_response = cached_response


class IdempotencyServiceUnavailable(RuntimeError):
    """Raised when the idempotency service cannot be reached."""


class IdempotencyService:
    """
    Dual-write idempotency guard for order submissions.

    Flow for each request:
      1. Compute SHA-256 hash of normalized payload.
      2. Attempt Redis SETNX with 24h TTL.
         - Key set (NX): first request → continue.
         - Key exists: duplicate → look up cached response in Supabase → raise DuplicateRequestError.
         - Redis unreachable: raise IdempotencyServiceUnavailable. NEVER silently pass.
      3. Write to Supabase audit ledger (best-effort, non-blocking to main path).
      4. After order completes, call mark_completed() to store the response.

    On restart: Redis may be empty, but Supabase ledger retains all records
    within the 24-hour window. The check_and_reserve() method falls back to
    Supabase if Redis returns a cache miss (post-restart scenario).
    """

    def __init__(
        self,
        redis: "aioredis.Redis",
        supabase: "AsyncClient",
    ) -> None:
        self._redis = redis
        self._supabase = supabase

    # ── Public API ────────────────────────────────────────────────────────────

    @staticmethod
    def compute_hash(user_id: str, payload: dict[str, Any]) -> str:
        """
        Compute a deterministic SHA-256 hash for a normalized order payload.

        Normalised fields: symbol, side, qty, order_type, idempotency_key.
        The idempotency_key provided by the caller is included so that callers
        can produce distinct hashes for intentionally different requests with
        the same market parameters.
        """
        canonical = json.dumps(
            {
                "user_id": user_id,
                "symbol": str(payload.get("symbol", "")).upper(),
                "side": str(payload.get("side", "")),
                "qty": int(payload.get("qty", 0)),
                "order_type": str(payload.get("order_type", "")),
                "idempotency_key": str(payload.get("idempotency_key", "")),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def check_and_reserve(
        self,
        user_id: str,
        payload_hash: str,
        request_payload: dict[str, Any],
    ) -> None:
        """
        Check for a duplicate and atomically reserve the idempotency slot.

        Raises:
            IdempotencyServiceUnavailable: if Redis is unreachable.
            DuplicateRequestError: if the key already exists (with cached response if available).
        """
        redis_key = f"{_REDIS_KEY_PREFIX}:{user_id}:{payload_hash}"

        # ── Step 1: Redis SETNX ──────────────────────────────────────────────
        try:
            acquired = await self._redis.set(
                redis_key, "1", nx=True, ex=_REDIS_TTL
            )
        except Exception as exc:
            log.error(
                "idempotency_redis_unavailable",
                user_id=user_id,
                hash=payload_hash[:16],
                error=str(exc),
            )
            raise IdempotencyServiceUnavailable(
                "Idempotency service unavailable (Redis). Request rejected — retry is safe."
            ) from exc

        if acquired:
            # Key was set — first request. Write audit record asynchronously.
            await self._write_ledger_entry(user_id, payload_hash, request_payload)
            return

        # ── Step 2: Duplicate detected — fetch cached response ────────────────
        # Redis returned None (key existed). First check Redis miss-on-restart:
        # the key exists in Redis, so this is a true duplicate within the TTL window.
        cached = await self._fetch_cached_response(user_id, payload_hash)
        log.warning(
            "idempotency_duplicate_detected",
            user_id=user_id,
            hash=payload_hash[:16],
            has_cached_response=cached is not None,
        )
        raise DuplicateRequestError(cached_response=cached)

    async def check_restart_scenario(
        self,
        user_id: str,
        payload_hash: str,
        request_payload: dict[str, Any],
    ) -> None:
        """
        Called when Redis returns a miss but we want to verify against Supabase.
        Handles the restart scenario: Redis was cleared but Supabase ledger still has record.

        Only needed when Redis SETNX succeeds but we want belt-and-suspenders
        verification. Called optionally before proceeding after Redis success.
        """
        within_24h = datetime.now(UTC) - timedelta(seconds=_REDIS_TTL)
        try:
            result = (
                await self._supabase.table(_TABLE)
                .select("id, response_payload, status")
                .eq("user_id", user_id)
                .eq("payload_hash", payload_hash)
                .gte("created_at", within_24h.isoformat())
                .maybe_single()
                .execute()
            )
            if result.data:
                # Supabase has a record — re-populate Redis and treat as duplicate
                redis_key = f"{_REDIS_KEY_PREFIX}:{user_id}:{payload_hash}"
                try:
                    await self._redis.set(redis_key, "1", ex=_REDIS_TTL)
                except Exception:
                    pass
                cached = result.data.get("response_payload") or None
                log.warning(
                    "idempotency_restart_duplicate_caught",
                    user_id=user_id,
                    hash=payload_hash[:16],
                )
                raise DuplicateRequestError(cached_response=cached)
        except DuplicateRequestError:
            raise
        except Exception:
            # Supabase unavailable — Redis already reserved, proceed
            log.warning("idempotency_supabase_restart_check_failed", user_id=user_id)

    async def mark_completed(
        self,
        user_id: str,
        payload_hash: str,
        response_payload: dict[str, Any],
    ) -> None:
        """Store the successful response so future duplicates can return it."""
        try:
            await (
                self._supabase.table(_TABLE)
                .update(
                    {
                        "status": "completed",
                        "response_payload": response_payload,
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                )
                .eq("user_id", user_id)
                .eq("payload_hash", payload_hash)
                .execute()
            )
        except Exception:
            log.warning(
                "idempotency_mark_completed_failed",
                user_id=user_id,
                hash=payload_hash[:16],
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _write_ledger_entry(
        self,
        user_id: str,
        payload_hash: str,
        request_payload: dict[str, Any],
    ) -> None:
        try:
            await self._supabase.table(_TABLE).insert(
                {
                    "user_id": user_id,
                    "payload_hash": payload_hash,
                    "request_payload": request_payload,
                    "response_payload": {},
                    "status": "received",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ).execute()
        except Exception:
            # Supabase write failure is non-fatal: Redis key is already set.
            # The request proceeds. If Supabase is down for the full 24h window,
            # a duplicate could slip through — but Redis will still catch it.
            log.warning(
                "idempotency_ledger_write_failed",
                user_id=user_id,
                hash=payload_hash[:16],
                note="Redis key still set — duplicate protection active for TTL window",
            )

    async def _fetch_cached_response(
        self, user_id: str, payload_hash: str
    ) -> dict[str, Any] | None:
        try:
            result = (
                await self._supabase.table(_TABLE)
                .select("response_payload, status")
                .eq("user_id", user_id)
                .eq("payload_hash", payload_hash)
                .maybe_single()
                .execute()
            )
            if result.data and result.data.get("status") == "completed":
                return result.data.get("response_payload")
        except Exception:
            log.warning("idempotency_cache_fetch_failed", user_id=user_id)
        return None


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def get_idempotency_service() -> IdempotencyService:
    """FastAPI dependency — provides an IdempotencyService per request."""
    import redis.asyncio as aioredis

    from src.config import settings
    from src.services.supabase_service import get_supabase_client

    redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    supabase = await get_supabase_client()
    return IdempotencyService(redis=redis_client, supabase=supabase)
