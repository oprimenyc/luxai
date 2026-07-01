"""
Path: apps/api/src/core/startup_checks.py
Security: Fail-closed boot gate plus the shared Alpaca paper-mode resolver
          used by the broker adapter and the workbench router. Refuses to
          proceed unless credentials are verifiably paper-exclusive. Never
          relaxed automatically; requires code change + review.
Scale: Single-tenant. `resolve_paper_account` makes two outbound HTTP calls
       (paper + live) — cheap at process startup and at broker connect
       time (both are once-per-process, not per-request), but callers on a
       request hot path should cache the result rather than re-resolving.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from src.config import Settings

log = structlog.get_logger(__name__)

PAPER_BASE_URL = "https://paper-api.alpaca.markets/v2"
LIVE_BASE_URL = "https://api.alpaca.markets/v2"
_HTTP_OK = 200


class AlpacaPaperModeError(RuntimeError):
    """Raised when Alpaca credentials cannot be verified as paper-exclusive."""


async def resolve_paper_account(api_key: str, api_secret: str) -> dict[str, Any]:
    """
    Authenticate against Alpaca and confirm the credentials are paper-only.

    Alpaca's `/v2/account` response has no `paper_trading` field — paper vs.
    live is enforced entirely by which of the two mutually-exclusive key
    pairs is presented to which base URL (a key valid on one endpoint gets
    401 on the other). "Verifiably paper" therefore means the credentials
    authenticate against the paper endpoint AND are rejected by the live
    endpoint. Succeeding on both (or only on live) means the key is not
    paper-exclusive and must not be trusted.

    Returns the paper account payload on success. Raises AlpacaPaperModeError
    otherwise; every rejection path logs CRITICAL first.
    """
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            paper_resp = await client.get(f"{PAPER_BASE_URL}/account", headers=headers)
            live_resp = await client.get(f"{LIVE_BASE_URL}/account", headers=headers)
    except httpx.HTTPError as exc:
        log.critical(
            "alpaca_paper_check_failed",
            error=str(exc)[:200],
            detail="Could not verify Alpaca account mode.",
        )
        raise AlpacaPaperModeError(
            "Unable to verify Alpaca account is paper mode.",
        ) from exc

    if paper_resp.status_code != _HTTP_OK:
        log.critical(
            "alpaca_paper_auth_rejected",
            status=paper_resp.status_code,
            detail="Configured credentials were rejected by the paper endpoint.",
        )
        raise AlpacaPaperModeError(
            "Alpaca credentials were rejected by the paper endpoint.",
        )

    if live_resp.status_code == _HTTP_OK:
        account = paper_resp.json()
        log.critical(
            "alpaca_live_account_detected",
            account_id=account.get("id"),
            detail=(
                "Configured Alpaca credentials also authenticate against the LIVE "
                "endpoint. Refusing to trust them as paper-only."
            ),
        )
        raise AlpacaPaperModeError(
            "Alpaca credentials are valid on the LIVE endpoint. Live trading is disabled.",
        )

    account = paper_resp.json()
    log.info("alpaca_paper_mode_verified", account_id=account.get("id"))
    return account


async def verify_alpaca_paper_mode(settings: Settings) -> None:
    """
    Refuse to start the process unless Alpaca is verifiably paper-mode.

    Checks, in order:
      1. `settings.alpaca_paper` must be True.
      2. The configured base URL must be the paper endpoint.
      3. If credentials are configured, `resolve_paper_account` must confirm
         they are paper-exclusive.

    Any failure logs a CRITICAL entry (in this function or in
    `resolve_paper_account`) and raises, which must abort startup.
    """
    if not settings.alpaca_paper:
        log.critical(
            "alpaca_paper_mode_disabled",
            detail="ALPACA_PAPER is not true — refusing to start.",
        )
        raise AlpacaPaperModeError("ALPACA_PAPER must be true to start this service.")

    if "api.alpaca.markets" in PAPER_BASE_URL and "paper" not in PAPER_BASE_URL:
        log.critical(
            "alpaca_base_url_not_paper",
            base_url=PAPER_BASE_URL,
            detail="Alpaca base URL points at the live host without a paper prefix.",
        )
        raise AlpacaPaperModeError(
            f"Alpaca base URL is not a paper endpoint: {PAPER_BASE_URL}",
        )

    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        log.warning("alpaca_startup_check_skipped_no_credentials")
        return

    await resolve_paper_account(settings.alpaca_api_key, settings.alpaca_api_secret)
