"""
Shadow Mode Service — first-class safety system, not a feature toggle.

Path: apps/api/src/trading/shadow.py
Security: Shadow state dual-written to Redis + Supabase on every change.
          Fail-safe: if Redis is unreachable, assume shadow ACTIVE. An
          infrastructure failure must never accidentally enable live trading.
          Deactivation (admin clear) writes Supabase first; if that fails,
          shadow stays active. Redis is updated second.
Scale: Redis serves the O(1) hot-path read on every order submission.
       Supabase is the authoritative source of truth on restart.
       Key namespaced by user_id for future multi-tenant support.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from supabase import AsyncClient

log = structlog.get_logger(__name__)

# Redis key schema (namespaced per user for future multi-tenancy)
_REDIS_KEY_ACTIVE = "shadow_mode:active:{user_id}"
_REDIS_TTL = 86_400 * 30  # 30 days — refreshed on every write

_TABLE_CONFIG = "shadow_mode_config"
_TABLE_TRADES = "shadow_trades"
_TABLE_PNL = "shadow_pnl"


class ShadowModeError(RuntimeError):
    """Raised when a required shadow mode write fails."""


class ShadowModeService:
    """
    Manages per-user shadow mode state and trade interception logging.

    Shadow mode is the default state for all new accounts. The only path
    to exiting shadow mode is an admin deactivation after a two-week run
    and manual journal audit (see CLAUDE.md — Shadow Mode section).

    Fail-safe invariant: any infrastructure failure (Redis down, Supabase
    unreachable) resolves to shadow ACTIVE, never shadow inactive.
    """

    def __init__(
        self,
        redis: "aioredis.Redis",
        supabase: "AsyncClient",
    ) -> None:
        self._redis = redis
        self._supabase = supabase

    # ── State Reads ───────────────────────────────────────────────────────────

    async def is_active(self, user_id: str) -> bool:
        """
        Return True if shadow mode is active for user_id.

        Read path: Redis → Supabase → default True (fail-safe).
        The in-memory Redis read is the hot path on every order submit.
        """
        redis_key = _REDIS_KEY_ACTIVE.format(user_id=user_id)

        try:
            val = await self._redis.get(redis_key)
            if val is not None:
                return val in (b"1", "1")
        except Exception:
            log.warning(
                "shadow_redis_unavailable_assuming_active",
                user_id=user_id,
            )
            return True  # fail-safe: Redis down → shadow stays on

        # Cache miss → authoritative read from Supabase
        try:
            result = (
                await self._supabase.table(_TABLE_CONFIG)
                .select("is_active")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if result.data:
                is_active: bool = result.data["is_active"]
            else:
                # New user — create default config (shadow active)
                await self._create_default_config(user_id)
                is_active = True

            # Back-populate Redis cache
            try:
                await self._redis.set(
                    redis_key,
                    "1" if is_active else "0",
                    ex=_REDIS_TTL,
                )
            except Exception:
                log.warning("shadow_redis_cache_populate_failed", user_id=user_id)

            return is_active

        except Exception:
            log.error(
                "shadow_supabase_read_failed_assuming_active",
                user_id=user_id,
            )
            return True  # fail-safe: Supabase down → shadow stays on

    # ── State Writes ─────────────────────────────────────────────────────────

    async def activate(self, user_id: str, activated_by: str) -> None:
        """
        Activate shadow mode for user_id. Both writes must succeed.
        Redis write first (fast); Supabase second (durable).
        If Supabase fails, Redis is rolled back to avoid inconsistency.
        """
        redis_key = _REDIS_KEY_ACTIVE.format(user_id=user_id)

        try:
            await self._redis.set(redis_key, "1", ex=_REDIS_TTL)
        except Exception as exc:
            raise ShadowModeError(
                "Shadow activate: Redis write failed — state unchanged"
            ) from exc

        try:
            await self._supabase.table(_TABLE_CONFIG).upsert(
                {
                    "user_id": user_id,
                    "is_active": True,
                    "activated_at": datetime.now(UTC).isoformat(),
                    "activated_by": activated_by,
                    "deactivated_at": None,
                    "deactivated_by": None,
                },
                on_conflict="user_id",
            ).execute()
        except Exception as exc:
            # Rollback Redis — shadow stays as it was
            try:
                await self._redis.delete(redis_key)
            except Exception:
                pass
            raise ShadowModeError(
                "Shadow activate: Supabase write failed — Redis rolled back"
            ) from exc

        log.info("shadow_mode_activated", user_id=user_id, by=activated_by)

    async def deactivate(self, user_id: str, cleared_by: str) -> None:
        """
        Deactivate shadow mode. ADMIN ONLY.

        Write order: Supabase FIRST, then Redis. If Supabase fails, neither
        write proceeds — shadow remains active (safer). If Redis fails after
        Supabase succeeds, the next is_active() call will re-populate Redis
        correctly from Supabase.
        """
        redis_key = _REDIS_KEY_ACTIVE.format(user_id=user_id)

        # Supabase first — authoritative record
        try:
            await self._supabase.table(_TABLE_CONFIG).upsert(
                {
                    "user_id": user_id,
                    "is_active": False,
                    "deactivated_at": datetime.now(UTC).isoformat(),
                    "deactivated_by": cleared_by,
                },
                on_conflict="user_id",
            ).execute()
        except Exception as exc:
            raise ShadowModeError(
                "Shadow deactivate: Supabase write failed — shadow remains ACTIVE"
            ) from exc

        # Redis second — if this fails, next is_active() read will correct it
        try:
            await self._redis.set(redis_key, "0", ex=_REDIS_TTL)
        except Exception:
            log.error(
                "shadow_deactivate_redis_failed_supabase_ok",
                user_id=user_id,
                note="Next is_active() call will re-sync Redis from Supabase",
            )

        log.warning(
            "shadow_mode_deactivated",
            user_id=user_id,
            cleared_by=cleared_by,
        )

    # ── Trade Interception Logging ────────────────────────────────────────────

    async def record_shadow_trade(
        self,
        user_id: str,
        symbol: str,
        side: str,
        qty: int,
        intended_entry_price: float,
        order_type: str,
        intended_idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Log a nullified order as a shadow trade entry.

        Called after shadow mode check prevents the real order from reaching
        the broker. Returns the shadow_trade_id for audit correlation.
        """
        shadow_id = str(uuid4())

        try:
            await self._supabase.table(_TABLE_TRADES).insert(
                {
                    "id": shadow_id,
                    "user_id": user_id,
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "order_type": order_type,
                    "intended_entry_price": intended_entry_price,
                    "intended_idempotency_key": intended_idempotency_key,
                    "status": "open",
                    "intercepted_at": datetime.now(UTC).isoformat(),
                    "metadata": metadata or {},
                }
            ).execute()
        except Exception:
            log.error(
                "shadow_trade_log_failed",
                shadow_id=shadow_id,
                symbol=symbol,
                user_id=user_id,
            )

        log.info(
            "shadow_trade_intercepted",
            shadow_id=shadow_id,
            symbol=symbol,
            side=side,
            qty=qty,
            intended_price=intended_entry_price,
        )
        return shadow_id

    # ── Summary (for banner / API) ────────────────────────────────────────────

    async def get_summary(self, user_id: str) -> dict[str, Any]:
        """
        Return shadow mode status and aggregated P&L for the UI banner.
        Non-critical path — errors return safe defaults so the banner
        always renders.
        """
        try:
            config_res = (
                await self._supabase.table(_TABLE_CONFIG)
                .select("is_active, activated_at, gate_passed_at")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            pnl_res = (
                await self._supabase.table(_TABLE_PNL)
                .select(
                    "total_shadow_pnl, total_trades, winning_trades, "
                    "losing_trades, hit_rate_pct, period_label"
                )
                .eq("user_id", user_id)
                .eq("period_label", "all-time")
                .maybe_single()
                .execute()
            )

            config = config_res.data or {}
            pnl = pnl_res.data or {}

            activated_at_raw = config.get("activated_at")
            days_active: int | None = None
            if activated_at_raw:
                try:
                    activated_dt = datetime.fromisoformat(activated_at_raw)
                    days_active = (datetime.now(UTC) - activated_dt).days
                except ValueError:
                    pass

            total = pnl.get("total_trades", 0)
            winning = pnl.get("winning_trades", 0)
            hit_rate = round((winning / total * 100), 1) if total > 0 else 0.0

            return {
                "is_active": config.get("is_active", True),
                "activated_at": activated_at_raw,
                "days_active": days_active,
                "gate_passed": config.get("gate_passed_at") is not None,
                "total_shadow_pnl": float(pnl.get("total_shadow_pnl") or 0),
                "total_trades": total,
                "winning_trades": winning,
                "losing_trades": pnl.get("losing_trades", 0),
                "hit_rate_pct": hit_rate,
            }

        except Exception:
            log.error("shadow_summary_fetch_failed", user_id=user_id)
            return {
                "is_active": True,
                "activated_at": None,
                "days_active": None,
                "gate_passed": False,
                "total_shadow_pnl": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "hit_rate_pct": 0.0,
            }

    # ── Trade Close + P&L ────────────────────────────────────────────────────

    async def close_shadow_trade(
        self,
        shadow_id: str,
        user_id: str,
        exit_price: float,
        close_reason: str = "price_triggered",
    ) -> dict[str, Any]:
        """
        Close an open shadow trade and record exit data.

        Called when the underlying price crosses the stop-loss or take-profit
        threshold for the shadow trade. Updates the trade row and triggers
        P&L aggregation.

        Returns the closed trade record, or {} on error.
        """
        try:
            # Fetch the open trade first to compute P&L
            res = (
                await self._supabase.table(_TABLE_TRADES)
                .select("id, user_id, symbol, side, qty, intended_entry_price")
                .eq("id", shadow_id)
                .eq("user_id", user_id)
                .eq("status", "open")
                .maybe_single()
                .execute()
            )
            if not res.data:
                log.warning("shadow_close_trade_not_found", shadow_id=shadow_id)
                return {}

            trade = res.data
            entry = float(trade["intended_entry_price"])
            qty = int(trade["qty"])
            side = trade["side"]

            # P&L: for a buy, profit when price rises; for a sell, profit when price falls
            if side == "buy":
                pnl_usd = (exit_price - entry) * qty
            else:
                pnl_usd = (entry - exit_price) * qty

            pnl_pct = (pnl_usd / (entry * qty)) if (entry * qty) > 0 else 0.0

            now = datetime.now(UTC).isoformat()
            await (
                self._supabase.table(_TABLE_TRADES)
                .update({
                    "status": "closed",
                    "intended_exit_price": exit_price,
                    "shadow_pnl_usd": round(pnl_usd, 4),
                    "shadow_pnl_pct": round(pnl_pct, 6),
                    "closed_at": now,
                    "metadata": {"close_reason": close_reason},
                })
                .eq("id", shadow_id)
                .eq("user_id", user_id)
                .execute()
            )

            log.info(
                "shadow_trade_closed",
                shadow_id=shadow_id,
                symbol=trade["symbol"],
                pnl_usd=round(pnl_usd, 2),
                reason=close_reason,
            )

            # Rebuild aggregated P&L after every close
            await self.aggregate_pnl(user_id)

            return {
                "shadow_id": shadow_id,
                "symbol": trade["symbol"],
                "pnl_usd": round(pnl_usd, 2),
                "pnl_pct": round(pnl_pct * 100, 2),
                "exit_price": exit_price,
                "close_reason": close_reason,
            }

        except Exception as exc:
            log.error(
                "shadow_close_trade_failed",
                shadow_id=shadow_id,
                error=str(exc),
            )
            return {}

    async def aggregate_pnl(self, user_id: str) -> None:
        """
        Recompute the all-time shadow P&L aggregate from closed trades.

        Reads all closed shadow_trades rows for user_id, computes aggregate
        statistics, and upserts to shadow_pnl with period_label='all-time'.

        Called automatically on every trade close. Safe to call manually
        (e.g. from the shadow report generator) — fully idempotent.
        """
        try:
            res = (
                await self._supabase.table(_TABLE_TRADES)
                .select(
                    "shadow_pnl_usd, shadow_pnl_pct, intercepted_at"
                )
                .eq("user_id", user_id)
                .eq("status", "closed")
                .execute()
            )
            trades = res.data or []

            if not trades:
                return

            pnls = [float(t["shadow_pnl_usd"]) for t in trades if t.get("shadow_pnl_usd") is not None]
            if not pnls:
                return

            total = len(pnls)
            winners = [p for p in pnls if p > 0]
            losers  = [p for p in pnls if p <= 0]
            hit_rate = round(len(winners) / total * 100, 2) if total > 0 else 0.0
            avg_win  = round(sum(winners) / len(winners), 4) if winners else 0.0
            avg_loss = round(sum(losers) / len(losers), 4) if losers else 0.0

            earliest = min(t["intercepted_at"] for t in trades)

            await (
                self._supabase.table(_TABLE_PNL)
                .upsert(
                    {
                        "user_id": user_id,
                        "period_label": "all-time",
                        "period_start": earliest,
                        "period_end": None,
                        "total_shadow_pnl": round(sum(pnls), 4),
                        "total_trades": total,
                        "winning_trades": len(winners),
                        "losing_trades": len(losers),
                        "largest_win": round(max(winners), 4) if winners else None,
                        "largest_loss": round(min(losers), 4) if losers else None,
                        "hit_rate_pct": hit_rate,
                        "avg_win_usd": avg_win,
                        "avg_loss_usd": avg_loss,
                        "updated_at": datetime.now(UTC).isoformat(),
                    },
                    on_conflict="user_id,period_label",
                )
                .execute()
            )

            log.info(
                "shadow_pnl_aggregated",
                user_id=user_id,
                total_trades=total,
                total_pnl=round(sum(pnls), 2),
                hit_rate=hit_rate,
            )

        except Exception as exc:
            log.error(
                "shadow_pnl_aggregation_failed",
                user_id=user_id,
                error=str(exc),
            )

    async def get_open_trades(self, user_id: str) -> list[dict[str, Any]]:
        """
        Return all open shadow trades for a user.
        Used by the shadow trade monitor to check exit conditions.
        """
        try:
            res = (
                await self._supabase.table(_TABLE_TRADES)
                .select(
                    "id, symbol, side, qty, intended_entry_price, intercepted_at"
                )
                .eq("user_id", user_id)
                .eq("status", "open")
                .execute()
            )
            return res.data or []
        except Exception:
            log.warning("shadow_get_open_trades_failed", user_id=user_id)
            return []

    # ── Internal Helpers ──────────────────────────────────────────────────────

    async def _create_default_config(self, user_id: str) -> None:
        """Insert a default (active) shadow config for a first-time user."""
        try:
            await self._supabase.table(_TABLE_CONFIG).insert(
                {
                    "user_id": user_id,
                    "is_active": True,
                    "activated_at": datetime.now(UTC).isoformat(),
                    "activated_by": "system_default",
                }
            ).execute()
        except Exception:
            log.warning(
                "shadow_default_config_create_failed",
                user_id=user_id,
                note="Will be retried on next is_active() call",
            )


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def get_shadow_service() -> ShadowModeService:
    """
    FastAPI dependency that provides a ShadowModeService instance.
    Creates Redis + Supabase clients on first call.
    """
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
    return ShadowModeService(redis=redis_client, supabase=supabase)
