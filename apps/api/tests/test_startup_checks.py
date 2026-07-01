"""
Path: apps/api/tests/test_startup_checks.py
Security: Verifies the boot gate refuses to start on non-paper Alpaca config
          or a live account, and passes cleanly on verified paper config.
Scale: Unit tests with mocked HTTPX client; no broker/network side effects.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.config import Settings
from src.core.startup_checks import AlpacaPaperModeViolation, verify_alpaca_paper_mode


def _settings(**overrides: object) -> Settings:
    base = dict(
        supabase_url="https://x.supabase.co",
        supabase_anon_key="anon",
        supabase_service_role_key="service",
        supabase_jwt_secret="secret",
        alpaca_api_key="key",
        alpaca_api_secret="secret",
        alpaca_paper=True,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]) -> _FakeResponse:
        return self._response


@pytest.mark.asyncio
async def test_refuses_start_when_alpaca_paper_flag_false() -> None:
    settings = _settings(alpaca_paper=False)
    with pytest.raises(AlpacaPaperModeViolation):
        await verify_alpaca_paper_mode(settings)


@pytest.mark.asyncio
async def test_refuses_start_when_live_account_detected() -> None:
    settings = _settings()
    response = _FakeResponse({"paper_trading": False, "id": "live-acct"})
    with patch(
        "src.core.startup_checks.httpx.AsyncClient",
        return_value=_FakeAsyncClient(response),
    ):
        with pytest.raises(AlpacaPaperModeViolation):
            await verify_alpaca_paper_mode(settings)


@pytest.mark.asyncio
async def test_passes_when_paper_account_confirmed() -> None:
    settings = _settings()
    response = _FakeResponse({"paper_trading": True, "id": "paper-acct"})
    with patch(
        "src.core.startup_checks.httpx.AsyncClient",
        return_value=_FakeAsyncClient(response),
    ):
        await verify_alpaca_paper_mode(settings)


@pytest.mark.asyncio
async def test_skips_live_check_when_no_credentials_configured() -> None:
    settings = _settings(alpaca_api_key="", alpaca_api_secret="")
    await verify_alpaca_paper_mode(settings)
