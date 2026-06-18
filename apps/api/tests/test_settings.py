"""Tests for account settings API and shadow override loading."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.account_constraints import (
    ShadowTestingOverrides,
    load_shadow_overrides,
)


# ── ShadowTestingOverrides defaults ──────────────────────────────────────────

def test_shadow_overrides_defaults() -> None:
    overrides = ShadowTestingOverrides.defaults()
    assert overrides.min_dte == 3
    assert overrides.max_dte == 21
    assert overrides.max_contracts == 3
    assert overrides.max_risk_usd == 15.0
    assert overrides.allow_earnings is False
    assert overrides.score_threshold == 7.0


def test_shadow_overrides_immutable() -> None:
    overrides = ShadowTestingOverrides.defaults()
    with pytest.raises((AttributeError, TypeError)):
        overrides.min_dte = 5  # type: ignore[misc]


# ── load_shadow_overrides ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_shadow_overrides_returns_db_values() -> None:
    mock_supabase = AsyncMock()
    mock_supabase.table = MagicMock(return_value=MagicMock(
        select=MagicMock(return_value=MagicMock(
            eq=MagicMock(return_value=MagicMock(
                execute=AsyncMock(return_value=MagicMock(data=[{
                    "shadow_min_dte": 5,
                    "shadow_max_dte": 30,
                    "shadow_max_contracts": 2,
                    "shadow_max_risk_usd": "12.00",
                    "shadow_allow_earnings": True,
                    "score_threshold": "7.5",
                }]))
            ))
        ))
    ))

    result = await load_shadow_overrides("user-1", mock_supabase)
    assert result.min_dte == 5
    assert result.max_dte == 30
    assert result.max_contracts == 2
    assert result.max_risk_usd == 12.0
    assert result.allow_earnings is True
    assert result.score_threshold == 7.5


@pytest.mark.asyncio
async def test_load_shadow_overrides_returns_defaults_on_missing_row() -> None:
    mock_supabase = AsyncMock()
    mock_supabase.table = MagicMock(return_value=MagicMock(
        select=MagicMock(return_value=MagicMock(
            eq=MagicMock(return_value=MagicMock(
                execute=AsyncMock(return_value=MagicMock(data=[]))
            ))
        ))
    ))

    result = await load_shadow_overrides("user-2", mock_supabase)
    assert result == ShadowTestingOverrides.defaults()


@pytest.mark.asyncio
async def test_load_shadow_overrides_returns_defaults_on_exception() -> None:
    mock_supabase = AsyncMock()
    mock_supabase.table = MagicMock(side_effect=Exception("DB down"))

    result = await load_shadow_overrides("user-3", mock_supabase)
    assert result == ShadowTestingOverrides.defaults()


# ── Settings Pydantic model validation ───────────────────────────────────────

def test_patch_settings_validates_min_dte_range() -> None:
    """Validate shadow_min_dte bounds via an inline Pydantic model matching route spec."""
    from typing import Annotated
    from pydantic import BaseModel, Field, ValidationError

    class _Patch(BaseModel):
        shadow_min_dte: Annotated[int, Field(ge=1, le=7)] | None = None
        shadow_max_dte: Annotated[int, Field(ge=7, le=60)] | None = None
        score_threshold: Annotated[float, Field(ge=6.0, le=9.0)] | None = None

    valid = _Patch(shadow_min_dte=3, shadow_max_dte=21)
    assert valid.shadow_min_dte == 3

    with pytest.raises(ValidationError):
        _Patch(shadow_min_dte=0)  # below min

    with pytest.raises(ValidationError):
        _Patch(shadow_min_dte=8)  # above max (Tiny live min is 7)


def test_patch_settings_rejects_score_threshold_out_of_range() -> None:
    from typing import Annotated
    from pydantic import BaseModel, Field, ValidationError

    class _Patch(BaseModel):
        score_threshold: Annotated[float, Field(ge=6.0, le=9.0)] | None = None

    with pytest.raises(ValidationError):
        _Patch(score_threshold=5.5)

    with pytest.raises(ValidationError):
        _Patch(score_threshold=9.5)

    valid = _Patch(score_threshold=7.0)
    assert valid.score_threshold == 7.0
