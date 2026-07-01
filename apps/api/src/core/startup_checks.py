"""
Path: apps/api/src/core/startup_checks.py
Security: Fail-closed boot gate. Refuses process startup if Alpaca is not
          verifiably in paper mode — either by config flag or by live account
          state. Never relaxed automatically; requires code change + review.
Scale: Single-tenant, runs once per process boot. One outbound HTTP call to
       Alpaca at startup; not on any request hot path.
"""

from __future__ import annotations

import httpx
import structlog

from src.config import Settings

log = structlog.get_logger(__name__)

_PAPER_BASE_URL = "https://paper-api.alpaca.markets/v2"


class AlpacaPaperModeViolation(RuntimeError):
    """Raised when the runtime cannot verify Alpaca paper-trading mode."""


async def verify_alpaca_paper_mode(settings: Settings) -> None:
    """
    Refuse to start the process unless Alpaca is verifiably paper-mode.

    Checks, in order:
      1. `settings.alpaca_paper` must be True.
      2. The configured base URL must be the paper endpoint (contains
         "paper" and never the bare live host "api.alpaca.markets").
      3. If Alpaca credentials are configured, the live account is queried
         and must report `paper_trading: true` (or `paper: true`).

    Any failure logs a CRITICAL entry and raises, which must abort startup.
    """
    if not settings.alpaca_paper:
        log.critical(
            "alpaca_paper_mode_disabled",
            detail="ALPACA_PAPER is not true — refusing to start.",
        )
        raise AlpacaPaperModeViolation("ALPACA_PAPER must be true to start this service.")

    if "api.alpaca.markets" in _PAPER_BASE_URL and "paper" not in _PAPER_BASE_URL:
        log.critical(
            "alpaca_base_url_not_paper",
            base_url=_PAPER_BASE_URL,
            detail="Alpaca base URL points at the live host without a paper prefix.",
        )
        raise AlpacaPaperModeViolation(
            f"Alpaca base URL is not a paper endpoint: {_PAPER_BASE_URL}"
        )

    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        log.warning("alpaca_startup_check_skipped_no_credentials")
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_PAPER_BASE_URL}/account",
                headers={
                    "APCA-API-KEY-ID": settings.alpaca_api_key,
                    "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
                },
            )
        resp.raise_for_status()
        account = resp.json()
    except httpx.HTTPError as exc:
        log.critical(
            "alpaca_startup_check_failed",
            error=str(exc)[:200],
            detail="Could not verify Alpaca account mode at startup.",
        )
        raise AlpacaPaperModeViolation(
            "Unable to verify Alpaca account is paper mode at startup."
        ) from exc

    is_paper = account.get("paper_trading", account.get("paper", False))
    if not is_paper:
        log.critical(
            "alpaca_live_account_detected",
            account_id=account.get("id"),
            detail="Configured Alpaca credentials belong to a LIVE account. Refusing to start.",
        )
        raise AlpacaPaperModeViolation(
            "Alpaca account is NOT paper — refusing to start. Live trading is disabled."
        )

    log.info("alpaca_paper_mode_verified", account_id=account.get("id"))
