"""
Account settings API — GET and PATCH /api/v1/settings.

Path: apps/api/src/routers/settings.py
Security: Auth required (AuthenticatedUser). User can only read/write their own
          settings. Shadow overrides validated to enforce permitted ranges.
          Score threshold validated to 6.0–9.0.
Scale: Single-tenant for now; user_id key isolates rows. upsert is idempotent.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.middleware.auth import AuthenticatedUser, get_current_user
from src.services.supabase_service import get_supabase_client

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

# ── Defaults (mirrors migration defaults) ────────────────────────────────────

_DEFAULTS: dict[str, Any] = {
    "shadow_min_dte": 3,
    "shadow_max_dte": 21,
    "shadow_max_contracts": 3,
    "shadow_max_risk_usd": 15.00,
    "shadow_allow_earnings": False,
    "score_threshold": 7.0,
}


# ── Response / Request models ─────────────────────────────────────────────────


class AccountSettingsResponse(BaseModel):
    user_id: str
    shadow_min_dte: int
    shadow_max_dte: int
    shadow_max_contracts: int
    shadow_max_risk_usd: float
    shadow_allow_earnings: bool
    score_threshold: float
    updated_at: str | None = None


class AccountSettingsPatch(BaseModel):
    shadow_min_dte: Annotated[int, Field(ge=1, le=7)] | None = None
    shadow_max_dte: Annotated[int, Field(ge=7, le=60)] | None = None
    shadow_max_contracts: Annotated[int, Field(ge=1, le=3)] | None = None
    shadow_max_risk_usd: Annotated[float, Field(ge=5.0, le=15.0)] | None = None
    shadow_allow_earnings: bool | None = None
    score_threshold: Annotated[float, Field(ge=6.0, le=9.0)] | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=AccountSettingsResponse)
async def get_settings(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AccountSettingsResponse:
    """
    Return the authenticated user's account settings.
    If no row exists yet, returns default values without writing to DB.
    """
    user_id = str(user.user_id)

    try:
        supabase = await get_supabase_client()
        res = await supabase.table("account_settings").select("*").eq("user_id", user_id).execute()
        row = (res.data or [None])[0]
    except Exception as exc:
        log.warning("settings_fetch_failed", user_id=user_id, error=str(exc)[:80])
        row = None

    if row is None:
        return AccountSettingsResponse(user_id=user_id, **_DEFAULTS)

    return AccountSettingsResponse(
        user_id=user_id,
        shadow_min_dte=row["shadow_min_dte"],
        shadow_max_dte=row["shadow_max_dte"],
        shadow_max_contracts=row["shadow_max_contracts"],
        shadow_max_risk_usd=float(row["shadow_max_risk_usd"]),
        shadow_allow_earnings=row["shadow_allow_earnings"],
        score_threshold=float(row["score_threshold"]),
        updated_at=row.get("updated_at"),
    )


@router.patch("", response_model=AccountSettingsResponse)
async def patch_settings(
    body: AccountSettingsPatch,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AccountSettingsResponse:
    """
    Update account settings. Only provided fields are changed.
    Uses upsert to create the row on first write.
    """
    user_id = str(user.user_id)

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided to update.",
        )

    # Enforce cross-field invariant: min_dte must remain < max_dte
    if "shadow_min_dte" in updates or "shadow_max_dte" in updates:
        # Fetch current values if only one side is being changed
        try:
            supabase = await get_supabase_client()
            res = await supabase.table("account_settings").select(
                "shadow_min_dte,shadow_max_dte"
            ).eq("user_id", user_id).execute()
            current = (res.data or [{}])[0]
        except Exception:
            current = {}

        new_min = updates.get("shadow_min_dte", current.get("shadow_min_dte", _DEFAULTS["shadow_min_dte"]))
        new_max = updates.get("shadow_max_dte", current.get("shadow_max_dte", _DEFAULTS["shadow_max_dte"]))

        if new_min >= new_max:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"shadow_min_dte ({new_min}) must be less than shadow_max_dte ({new_max}).",
            )

    payload = {"user_id": user_id, **updates}

    try:
        supabase = await get_supabase_client()
        upsert_res = await supabase.table("account_settings").upsert(
            payload, on_conflict="user_id"
        ).execute()
        row = (upsert_res.data or [None])[0]
    except Exception as exc:
        log.error("settings_upsert_failed", user_id=user_id, error=str(exc)[:120])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save settings. Please try again.",
        ) from exc

    if row is None:
        # Upsert succeeded but no row returned — read it back
        return await get_settings(user)

    log.info("settings_updated", user_id=user_id, fields=list(updates.keys()))

    return AccountSettingsResponse(
        user_id=user_id,
        shadow_min_dte=row["shadow_min_dte"],
        shadow_max_dte=row["shadow_max_dte"],
        shadow_max_contracts=row["shadow_max_contracts"],
        shadow_max_risk_usd=float(row["shadow_max_risk_usd"]),
        shadow_allow_earnings=row["shadow_allow_earnings"],
        score_threshold=float(row["score_threshold"]),
        updated_at=row.get("updated_at"),
    )
