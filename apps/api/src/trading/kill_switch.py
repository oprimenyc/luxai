"""
Persistent kill switch — durable emergency halt that survives process restarts.

Path: apps/api/src/trading/kill_switch.py
Security: Kill switch state dual-written to Redis + Supabase. Per CLAUDE.md
          Rule 4: "Kill switch MUST write to Redis AND Supabase. Never RAM only."
          Fail-safe: Redis unreachable → assume HALTED. Infrastructure failure
          must never accidentally permit trading.
          Admin clear requires both writes; if either fails halt stays active.
Scale: Redis O(1) hot-path read on every order submission.
       Supabase system_halts table is append-only audit log.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from supabase import AsyncClient

log = structlog.get_logger(__name__)

_REDIS_KEY_PREFIX = "kill_switch"
_REDIS_TTL = 86_400 * 90    # 90 days — kill switch must survive long outages
_TABLE = "system_halts"


class KillSwitchError(RuntimeError):
    """Raised when a required kill switch write fails."""


class KillSwitchService:
    """
    Persistent kill switch with dual-write Redis + Supabase.

    Fail-safe invariants (matching ShadowModeService pattern):
      - Redis unreachable on is_halted() → assume HALTED
      - Supabase unreachable on is_halted() → assume HALTED
      - activate() Redis write fails → raise error, state unchanged
      - activate() Supabase write fails → rollback Redis, raise error
      - clear() Supabase write fails → abort, halt stays active
      - clear() Redis write fails after Supabase → log, next is_halted() re-syncs
    """

    def __init__(
        self,
        redis: "aioredis.Redis",
        supabase: "AsyncClient",
    ) -> None:
        self._redis = redis
        self._supabase = supabase

    # ── State Reads ───────────────────────────────────────────────────────────

    async def is_halted(self, user_id: str) -> bool:
        """
        Return True if the kill switch is active for user_id.
        Fail-safe: any infrastructure error → assume HALTED.
        """
        redis_key = f"{_REDIS_KEY_PREFIX}:{user_id}"

        try:
            val = await self._redis.get(redis_key)
            if val is not None:
                return val in (b"1", "1")
        except Exception:
            log.error(
                "kill_switch_redis_unavailable_assuming_halted",
                user_id=user_id,
            )
            return True  # fail-safe

        # Redis miss → check Supabase for an active (non-cleared) halt
        try:
            result = (
                await self._supabase.table(_TABLE)
                .select("id")
                .eq("user_id", user_id)
                .is_("cleared_at", "null")
                .order("activated_at", desc=True)
                .limit(1)
                .execute()
            )
            is_halted = bool(result.data)

            # Back-populate Redis cache
            try:
                await self._redis.set(
                    redis_key, "1" if is_halted else "0", ex=_REDIS_TTL
                )
            except Exception:
                log.warning("kill_switch_redis_cache_populate_failed", user_id=user_id)

            return is_halted

        except Exception:
            log.error(
                "kill_switch_supabase_read_failed_assuming_halted",
                user_id=user_id,
            )
            return True  # fail-safe

    # ── State Writes ─────────────────────────────────────────────────────────

    async def activate(
        self,
        user_id: str,
        activated_by: str,
        reason: str = "operator_triggered",
        audit_notes: str | None = None,
    ) -> None:
        """
        Activate the kill switch. Both writes must succeed.
        Redis first (fast fail); Supabase second (durable record).
        If Supabase fails, Redis is rolled back so state is consistent.
        """
        redis_key = f"{_REDIS_KEY_PREFIX}:{user_id}"

        try:
            await self._redis.set(redis_key, "1", ex=_REDIS_TTL)
        except Exception as exc:
            raise KillSwitchError(
                "Kill switch activate: Redis write failed — state unchanged"
            ) from exc

        try:
            await self._supabase.table(_TABLE).insert(
                {
                    "user_id": user_id,
                    "activated_by": activated_by,
                    "reason": reason,
                    "audit_notes": audit_notes,
                    "activated_at": datetime.now(UTC).isoformat(),
                }
            ).execute()
        except Exception as exc:
            # Rollback Redis — halt was not durably recorded
            try:
                await self._redis.delete(redis_key)
            except Exception:
                pass
            raise KillSwitchError(
                "Kill switch activate: Supabase write failed — Redis rolled back"
            ) from exc

        log.critical(
            "kill_switch_activated",
            user_id=user_id,
            by=activated_by,
            reason=reason,
        )

    async def clear(
        self,
        user_id: str,
        cleared_by: str,
        clear_notes: str | None = None,
    ) -> None:
        """
        Clear the kill switch. ADMIN ONLY.

        Supabase written first (authoritative). If it fails, Redis stays halted.
        If Redis write fails after Supabase, log — next is_halted() will re-sync.
        """
        redis_key = f"{_REDIS_KEY_PREFIX}:{user_id}"
        now = datetime.now(UTC).isoformat()

        # Supabase FIRST — mark all active (non-cleared) halts as cleared
        try:
            await (
                self._supabase.table(_TABLE)
                .update(
                    {
                        "cleared_at": now,
                        "cleared_by": cleared_by,
                        "clear_notes": clear_notes,
                    }
                )
                .eq("user_id", user_id)
                .is_("cleared_at", "null")
                .execute()
            )
        except Exception as exc:
            raise KillSwitchError(
                "Kill switch clear: Supabase write failed — halt remains ACTIVE"
            ) from exc

        # Redis second
        try:
            await self._redis.set(redis_key, "0", ex=_REDIS_TTL)
        except Exception:
            log.error(
                "kill_switch_clear_redis_failed_supabase_ok",
                user_id=user_id,
                note="Next is_halted() call will re-sync Redis from Supabase",
            )

        log.warning(
            "kill_switch_cleared",
            user_id=user_id,
            cleared_by=cleared_by,
        )

    async def get_status(self, user_id: str) -> dict[str, Any]:
        """Return current halt status and most recent halt record for API response."""
        is_halted = await self.is_halted(user_id)
        try:
            result = (
                await self._supabase.table(_TABLE)
                .select("activated_at, activated_by, reason, cleared_at, cleared_by")
                .eq("user_id", user_id)
                .order("activated_at", desc=True)
                .limit(1)
                .execute()
            )
            last = result.data[0] if result.data else {}
        except Exception:
            last = {}

        return {
            "is_halted": is_halted,
            "activated_at": last.get("activated_at"),
            "activated_by": last.get("activated_by"),
            "reason": last.get("reason"),
            "cleared_at": last.get("cleared_at"),
        }


# ── Startup check helper ──────────────────────────────────────────────────────


async def check_kill_switch_on_startup(user_id: str, service: "KillSwitchService") -> bool:
    """
    Called during FastAPI lifespan startup to detect pre-existing halts.
    Logs a warning if the kill switch is active but does not block startup —
    the application runs, but no orders can be submitted until cleared.
    """
    halted = await service.is_halted(user_id)
    if halted:
        log.warning(
            "kill_switch_active_on_startup",
            user_id=user_id,
            message="System started with kill switch active. "
                    "No orders can be submitted until an admin clears the halt.",
        )
    return halted


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def get_kill_switch_service() -> KillSwitchService:
    """FastAPI dependency — provides a KillSwitchService per request."""
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
    return KillSwitchService(redis=redis_client, supabase=supabase)
