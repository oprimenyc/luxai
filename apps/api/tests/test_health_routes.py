"""
Path: apps/api/tests/test_health_routes.py
Security: Confirms health probes await the Supabase client correctly so
          readiness does not silently mask a broken dependency chain.
Scale: Pure unit tests with mocked service clients; no external network I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.routers.health import _check_supabase


@pytest.mark.asyncio
async def test_check_supabase_awaits_client_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    select = MagicMock()
    select.limit.return_value = select
    select.execute = AsyncMock(return_value=MagicMock(data=[]))
    client.table.return_value.select.return_value = select

    factory = AsyncMock(return_value=client)
    monkeypatch.setattr("src.services.supabase_service.get_supabase_client", factory)

    result = await _check_supabase()

    assert result.status == "ok"
    factory.assert_awaited_once()
    client.table.assert_called_once_with("shadow_mode_config")
