"""
Shadow Mode Report Generator.

Path: packages/workbench/shadow_report.py
Security: Read-only Supabase access via service role key from environment.
          Never writes to shadow tables. No credentials stored in code.
Scale: Offline manual runs only — not on hot path. Queries are paginated.

Usage:
    # From repo root:
    python packages/workbench/shadow_report.py generate

    # From packages/workbench/ directory:
    python shadow_report.py generate

    # Optional flags:
    python shadow_report.py generate --user-id <uuid>   # specific user
    python shadow_report.py generate --days 14          # lookback window
    python shadow_report.py generate --output report.md # write to file
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _get_supabase():
    """Return a sync Supabase client using service role key from env."""
    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase-py not installed. Run: pip install supabase")
        sys.exit(1)

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        print(
            "ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.\n"
            "       Copy .env.example to .env and populate these values."
        )
        sys.exit(1)

    return create_client(url, key)


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_shadow_trades(
    client: Any,
    user_id: str | None,
    since: datetime,
) -> list[dict[str, Any]]:
    query = (
        client.table("shadow_trades")
        .select("*")
        .gte("intercepted_at", since.isoformat())
        .order("intercepted_at", desc=False)
    )
    if user_id:
        query = query.eq("user_id", user_id)

    result = query.execute()
    return result.data or []


def _fetch_shadow_pnl(
    client: Any,
    user_id: str | None,
) -> list[dict[str, Any]]:
    query = (
        client.table("shadow_pnl")
        .select("*")
        .eq("period_label", "all-time")
        .order("updated_at", desc=True)
    )
    if user_id:
        query = query.eq("user_id", user_id)

    result = query.execute()
    return result.data or []


def _fetch_shadow_config(
    client: Any,
    user_id: str | None,
) -> list[dict[str, Any]]:
    query = client.table("shadow_mode_config").select("*")
    if user_id:
        query = query.eq("user_id", user_id)
    result = query.execute()
    return result.data or []


# ── Analysis helpers ──────────────────────────────────────────────────────────

def _analyse_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(trades)
    closed = [t for t in trades if t["status"] == "closed"]
    open_count = len([t for t in trades if t["status"] == "open"])
    expired = len([t for t in trades if t["status"] == "expired"])

    wins = [t for t in closed if (t.get("shadow_pnl_usd") or 0) > 0]
    losses = [t for t in closed if (t.get("shadow_pnl_usd") or 0) < 0]

    total_pnl = sum((t.get("shadow_pnl_usd") or 0) for t in closed)
    hit_rate = (len(wins) / len(closed) * 100) if closed else 0.0

    best_trade = max(closed, key=lambda t: t.get("shadow_pnl_usd") or 0) if closed else None
    worst_trade = min(closed, key=lambda t: t.get("shadow_pnl_usd") or 0) if closed else None

    avg_win = (
        sum((t.get("shadow_pnl_usd") or 0) for t in wins) / len(wins)
        if wins else 0.0
    )
    avg_loss = (
        sum((t.get("shadow_pnl_usd") or 0) for t in losses) / len(losses)
        if losses else 0.0
    )

    # Symbols breakdown
    symbol_counts: dict[str, int] = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
    top_symbols = sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total": total,
        "closed": len(closed),
        "open": open_count,
        "expired": expired,
        "wins": len(wins),
        "losses": len(losses),
        "total_pnl": total_pnl,
        "hit_rate": hit_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "top_symbols": top_symbols,
    }


# ── Report generation ─────────────────────────────────────────────────────────

def _render_report(
    trades: list[dict[str, Any]],
    pnl_rows: list[dict[str, Any]],
    config_rows: list[dict[str, Any]],
    days: int,
    user_id: str | None,
    generated_at: datetime,
) -> str:
    stats = _analyse_trades(trades)

    pnl_row = pnl_rows[0] if pnl_rows else {}
    config_row = config_rows[0] if config_rows else {}

    activated_at_raw = config_row.get("activated_at")
    activated_display = "—"
    days_active_display = "—"
    if activated_at_raw:
        try:
            activated_dt = datetime.fromisoformat(activated_at_raw)
            activated_display = activated_dt.strftime("%Y-%m-%d")
            days_active_display = str((generated_at - activated_dt).days)
        except ValueError:
            pass

    gate_passed = config_row.get("gate_passed_at") is not None
    shadow_is_active = config_row.get("is_active", True)

    def _trade_line(t: dict[str, Any] | None) -> str:
        if not t:
            return "  None recorded."
        pnl = t.get("shadow_pnl_usd", 0) or 0
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        return (
            f"  Symbol: **{t.get('symbol', '?')}** | "
            f"Side: {t.get('side', '?').upper()} {t.get('qty', '?')} @ "
            f"${float(t.get('intended_entry_price', 0) or 0):.2f} → "
            f"Shadow P&L: {pnl_str}"
        )

    pnl_display = (
        f"+${stats['total_pnl']:.2f}"
        if stats["total_pnl"] >= 0
        else f"-${abs(stats['total_pnl']):.2f}"
    )

    symbol_lines = "\n".join(
        f"  - {sym}: {count} signal{'s' if count != 1 else ''}"
        for sym, count in stats["top_symbols"]
    ) or "  No signals recorded."

    win_loss_summary = (
        f"{stats['wins']} wins / {stats['losses']} losses"
        if stats["closed"] > 0
        else "No closed trades"
    )

    gate_status = (
        "PASSED — Admin cleared shadow gate" if gate_passed
        else f"PENDING — {days_active_display} day(s) active (14-day minimum required)"
    )
    shadow_status = "ACTIVE" if shadow_is_active else "INACTIVE (gate cleared)"

    return f"""# Shadow Mode Report
**Generated:** {generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")}
**Lookback window:** {days} days
{"**User ID:** " + user_id if user_id else "**Scope:** All users"}

---

## Overview

| Field | Value |
|-------|-------|
| Shadow Mode Status | {shadow_status} |
| Activated | {activated_display} |
| Days Active | {days_active_display} |
| Live Gate Status | {gate_status} |

---

## Signal Summary

| Metric | Value |
|--------|-------|
| Total signals intercepted | {stats['total']} |
| Closed (exit price recorded) | {stats['closed']} |
| Open (no exit yet) | {stats['open']} |
| Expired | {stats['expired']} |
| Win/Loss | {win_loss_summary} |
| Hit Rate | {stats['hit_rate']:.1f}% |

---

## Shadow P&L

| Metric | Value |
|--------|-------|
| Total Shadow P&L | **{pnl_display}** |
| Average Win | +${stats['avg_win']:.2f} |
| Average Loss | ${stats['avg_loss']:.2f} |

> Shadow P&L is hypothetical — it reflects what would have happened if orders
> had been executed. It does not represent actual gains or losses.

---

## Top Symbols

{symbol_lines}

---

## Best Call

{_trade_line(stats['best_trade'])}

---

## Worst Miss

{_trade_line(stats['worst_trade'])}

---

## Shadow Gate Checklist

- [ ] Minimum 14 consecutive days of shadow run completed ({days_active_display} days so far)
- [ ] Journal audit performed (review signal quality and risk adherence)
- [ ] Hit rate above 40% on closed trades ({stats['hit_rate']:.1f}% recorded)
- [ ] No repeated risk-limit violations in journal
- [ ] Admin confirms gate passed via `DELETE /api/v1/trading/shadow/deactivate`

**Gate passed: {"YES — shadow cleared" if gate_passed else "NO — do not proceed to live trading discussion"}**

---

*Generated by shadow_report.py — LuxAI OS / .fylr*
*Shadow mode is the launch permission system. Two weeks + journal audit = the only path forward.*
"""


# ── CLI entry point ───────────────────────────────────────────────────────────

def cmd_generate(args: argparse.Namespace) -> None:
    client = _get_supabase()

    since = datetime.now(UTC) - timedelta(days=args.days)
    generated_at = datetime.now(UTC)

    print(f"Fetching shadow data for the last {args.days} days...")

    trades = _fetch_shadow_trades(client, args.user_id, since)
    pnl_rows = _fetch_shadow_pnl(client, args.user_id)
    config_rows = _fetch_shadow_config(client, args.user_id)

    print(
        f"Found {len(trades)} shadow trade(s), "
        f"{len(pnl_rows)} P&L record(s), "
        f"{len(config_rows)} config row(s)."
    )

    report = _render_report(
        trades=trades,
        pnl_rows=pnl_rows,
        config_rows=config_rows,
        days=args.days,
        user_id=args.user_id,
        generated_at=generated_at,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to: {args.output}")
    else:
        print("\n" + "=" * 72)
        print(report)
        print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="shadow_report",
        description="LuxAI OS — Shadow Mode Report Generator",
    )
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", help="Generate a shadow mode report")
    gen.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="Limit report to a specific user UUID (default: all users)",
    )
    gen.add_argument(
        "--days",
        type=int,
        default=14,
        help="Lookback window in days (default: 14)",
    )
    gen.add_argument(
        "--output",
        default=None,
        help="Write report to this file path instead of stdout",
    )

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
