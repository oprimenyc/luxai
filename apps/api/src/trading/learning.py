"""
Path: apps/api/src/trading/learning.py
Security: Reads shadow_trades (service role). Writes learning_insights (service role).
          No PII — all queries keyed by user_id. No LLM calls. Pure Python + Supabase.
Scale: Single-tenant. Runs once weekly (Sunday 8PM ET). O(n) over closed trades.
       Table scan is bounded — shadow_trades is append-only, indexed on status.

Self-Learning Engine — analyses closed shadow trades and adjusts scanner thresholds.

Design:
  - Reads closed shadow_trades rows (exit_price and exit_reason populated)
  - Calculates win rate by: symbol, option_type, day_of_week, score_bucket
  - Writes a summary row to learning_insights
  - Returns the recommended scanner score threshold for next week

Win definition: exit_pnl > 0 (profitable close, not stop-loss exit).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from supabase import AsyncClient

log = structlog.get_logger(__name__)

_DEFAULT_THRESHOLD = 7.0
_MIN_THRESHOLD = 6.0
_MAX_THRESHOLD = 9.0

# Enough closed trades to make the win-rate adjustment meaningful
_MIN_SAMPLE_SIZE = 5


class LearningEngine:
    """
    Reads closed shadow trades and writes learning_insights.

    Adjusts the scanner's minimum score threshold based on observed win rate:
      win_rate > 65%  → lower threshold by 0.5 (more signals, same quality bar)
      win_rate < 40%  → raise threshold by 0.5 (be more selective)
      40–65%          → no change (within expected range per CLAUDE.md gate)
    """

    def __init__(self, supabase: "AsyncClient") -> None:
        self._supabase = supabase

    async def run(self, user_id: str) -> dict[str, Any]:
        """
        Run the weekly learning pass.

        Returns a summary dict suitable for logging and returning to callers.
        """
        log.info("learning_engine_starting", user_id=user_id)

        trades = await self._fetch_closed_trades(user_id)
        if not trades:
            log.info("learning_engine_no_trades", user_id=user_id)
            return {"status": "no_data", "trades_analysed": 0}

        summary = _analyse(trades)
        new_threshold = _recommend_threshold(summary["overall_win_rate"], summary["trade_count"])
        summary["recommended_threshold"] = new_threshold

        await self._write_insights(user_id, summary)
        log.info(
            "learning_engine_complete",
            user_id=user_id,
            win_rate=round(summary["overall_win_rate"], 3),
            recommended_threshold=new_threshold,
            trades=summary["trade_count"],
        )
        return summary

    async def _fetch_closed_trades(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch all shadow trades with exit_price set (closed trades)."""
        try:
            resp = (
                await self._supabase
                .table("shadow_trades")
                .select(
                    "id,symbol,side,qty,intended_entry_price,exit_price,"
                    "exit_reason,metadata,created_at"
                )
                .eq("user_id", user_id)
                .not_.is_("exit_price", "null")
                .execute()
            )
            return resp.data or []
        except Exception as exc:
            log.error("learning_engine_fetch_failed", error=str(exc)[:120])
            return []

    async def _write_insights(self, user_id: str, summary: dict[str, Any]) -> None:
        """Persist insights to learning_insights table."""
        try:
            await self._supabase.table("learning_insights").insert({
                "user_id": user_id,
                "computed_at": datetime.now(UTC).isoformat(),
                "trade_count": summary["trade_count"],
                "win_count": summary["win_count"],
                "overall_win_rate": summary["overall_win_rate"],
                "win_rate_by_symbol": summary["by_symbol"],
                "win_rate_by_option_type": summary["by_option_type"],
                "win_rate_by_day": summary["by_day"],
                "win_rate_by_score_bucket": summary["by_score_bucket"],
                "recommended_threshold": summary["recommended_threshold"],
            }).execute()
        except Exception as exc:
            log.error("learning_engine_write_failed", error=str(exc)[:120])


# ── Pure analysis helpers ─────────────────────────────────────────────────────

def _analyse(trades: list[dict[str, Any]]) -> dict[str, Any]:
    wins_total = 0
    total = len(trades)

    by_symbol: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "total": 0})
    by_option_type: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "total": 0})
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "total": 0})
    by_score_bucket: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "total": 0})

    for trade in trades:
        entry = float(trade.get("intended_entry_price") or 0)
        exit_p = float(trade.get("exit_price") or 0)
        is_win = exit_p > entry and entry > 0

        if is_win:
            wins_total += 1

        symbol = str(trade.get("symbol", "UNKNOWN"))
        by_symbol[symbol]["total"] += 1
        if is_win:
            by_symbol[symbol]["wins"] += 1

        meta = trade.get("metadata") or {}
        opt_type = str(meta.get("option_type", "unknown"))
        by_option_type[opt_type]["total"] += 1
        if is_win:
            by_option_type[opt_type]["wins"] += 1

        created = trade.get("created_at", "")
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            day = dt.strftime("%A")
        except Exception:
            day = "Unknown"
        by_day[day]["total"] += 1
        if is_win:
            by_day[day]["wins"] += 1

        score = float(meta.get("score") or 0)
        bucket = _score_bucket(score)
        by_score_bucket[bucket]["total"] += 1
        if is_win:
            by_score_bucket[bucket]["wins"] += 1

    def win_rate_dict(d: dict[str, dict[str, int]]) -> dict[str, float]:
        return {
            k: round(v["wins"] / v["total"], 3) if v["total"] else 0.0
            for k, v in d.items()
        }

    return {
        "trade_count": total,
        "win_count": wins_total,
        "overall_win_rate": wins_total / total if total else 0.0,
        "by_symbol": win_rate_dict(by_symbol),
        "by_option_type": win_rate_dict(by_option_type),
        "by_day": win_rate_dict(by_day),
        "by_score_bucket": win_rate_dict(by_score_bucket),
    }


def _score_bucket(score: float) -> str:
    if score >= 9.0:
        return "9+"
    if score >= 8.0:
        return "8-9"
    if score >= 7.0:
        return "7-8"
    return "<7"


def _recommend_threshold(win_rate: float, trade_count: int) -> float:
    """Adjust scanner threshold based on observed performance."""
    from src.trading.scanner import _MIN_SCORE as current_threshold

    if trade_count < _MIN_SAMPLE_SIZE:
        return current_threshold  # not enough data

    if win_rate > 0.65:
        # Performing well — can afford to lower the bar slightly for more signals
        return max(_MIN_THRESHOLD, round(current_threshold - 0.5, 1))
    if win_rate < 0.40:
        # Below expected gate — raise bar
        return min(_MAX_THRESHOLD, round(current_threshold + 0.5, 1))
    return current_threshold  # within 40–65% gate, no change


async def learning_weekly_run(user_id: str, supabase_client: "AsyncClient") -> None:
    """
    Entry point for the weekly scheduled run.

    Task name: learning_weekly_pass
    Cancellation: no long-running loops; runs once and exits.
    Timeout: bounded by Supabase query latency (~5s max expected).
    """
    engine = LearningEngine(supabase_client)
    await engine.run(user_id)
